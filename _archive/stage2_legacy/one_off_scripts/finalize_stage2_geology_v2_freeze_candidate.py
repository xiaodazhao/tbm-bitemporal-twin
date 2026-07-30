"""Finalize the Stage 2 geology V2 freeze candidate verification artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import tarfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import pdfplumber

from tbm_twin.geology.table_parser_v2.text_utils import (
    compact_text,
    parse_all_chainage_intervals,
)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "artifacts/stage2_geology_v2_freeze_candidate"
RAW = REPO / "artifacts/stage2_raw_geology_validation"
ASSET_AUDIT = RAW / "source_asset_audit.csv"

WATER_TERMS = [
    "滴渗水-线状出水",
    "滴渗水~线状出水",
    "渗滴水~线状出水",
    "线-股状出水",
    "线股状出水",
    "线状出水",
    "股状出水",
    "滴渗水",
    "渗滴水",
    "渗水",
    "涌水",
    "出水",
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    documents = _read_jsonl(OUT / "geological_documents.jsonl")
    evidence = _read_jsonl(OUT / "primary_geological_evidence.jsonl")
    assertions = _read_jsonl(OUT / "report_assertions.jsonl")
    clauses = _read_jsonl(OUT / "unlocated_clauses.jsonl")
    spans = _read_jsonl(OUT / "source_spans.jsonl")
    outcomes = _read_csv(OUT / "document_parse_outcomes.csv")
    source_issues = _read_csv(OUT / "source_data_issue_audit.csv")
    hard_checks = _read_csv(OUT / "primary_evidence_hard_check.csv")
    orphan_reference = _read_csv(OUT / "orphan_reference_audit.csv")

    water_audit, governance_counts = _audit_and_govern_water_clauses(
        evidence=evidence,
        clauses=clauses,
        spans=spans,
    )
    _write_jsonl(OUT / "primary_geological_evidence.jsonl", evidence)
    _write_csv(OUT / "water_unlocated_final_audit.csv", water_audit)
    _write_csv(OUT / "unlocated_clause_audit.csv", _unlocated_clause_audit(clauses))

    span_audit, span_reference_audit = _all_source_span_validation(
        spans=spans,
        documents=documents,
        evidence=evidence,
        assertions=assertions,
        clauses=clauses,
    )
    _write_csv(OUT / "all_source_span_validation.csv", span_audit)
    _write_csv(OUT / "all_source_span_reference_audit.csv", span_reference_audit)

    snapshot_files = _snapshot_files()
    source_tree_hash = _hash_file_list(snapshot_files)
    _write_source_hashes(snapshot_files)
    snapshot_sha = _write_source_snapshot(snapshot_files)

    method = _read_json(OUT / "method_version.json")
    method.update(
        {
            "source_snapshot_sha256": snapshot_sha,
            "parser_source_tree_hash": source_tree_hash,
            "working_tree_dirty": bool(_git(["status", "--short"])),
            "git_commit_hash": "NO_COMMITS",
            "finalized_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    _write_json(OUT / "method_version.json", method)

    manifest = _build_manifest(
        documents=documents,
        evidence=evidence,
        assertions=assertions,
        clauses=clauses,
        spans=spans,
        outcomes=outcomes,
        source_issues=source_issues,
        hard_checks=hard_checks,
        orphan_reference=[*orphan_reference, *span_reference_audit],
        span_audit=span_audit,
        water_audit=water_audit,
        governance_counts=governance_counts,
        source_snapshot_sha256=snapshot_sha,
        parser_source_tree_hash=source_tree_hash,
    )
    _write_json(OUT / "freeze_manifest.json", manifest)
    _write_report(manifest)
    _write_hashes()
    manifest["files"] = _file_hash_map()
    _write_json(OUT / "freeze_manifest.json", manifest)
    _write_hashes()
    print(json.dumps(manifest["summary"], ensure_ascii=False, indent=2))


def _audit_and_govern_water_clauses(
    *,
    evidence: list[dict[str, Any]],
    clauses: list[dict[str, Any]],
    spans: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    evidence_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in evidence:
        evidence_by_doc[item["document_id"]].append(item)
    span_by_id = {row["span_id"]: row for row in spans}
    counts: Counter[str] = Counter()
    rows = []
    water_clauses = [
        clause
        for clause in clauses
        if clause.get("statement_role") == "WATER_OBSERVATION_UNLOCATED"
    ]

    for clause in water_clauses:
        doc_evidence = evidence_by_doc.get(clause["document_id"], [])
        raw_text = str(clause.get("raw_text", ""))
        intervals = parse_all_chainage_intervals(raw_text)
        forecast_matches = _matching_interval_evidence(doc_evidence, "FORECAST_SEGMENT", intervals)
        observed_matches = _matching_interval_evidence(
            doc_evidence,
            "FACE_OBSERVATION",
            intervals,
            observation_scope="CURRENT_EXCAVATED_INTERVAL",
        )
        linked = _linked_evidence(doc_evidence, raw_text)
        checkbox_duplicate = _is_checkbox_only_duplicate(doc_evidence, raw_text)
        before_attr_hits = _face_point_attr_hits(doc_evidence, raw_text)

        if forecast_matches:
            classification_after = "MERGED_INTO_FORECAST_SEGMENT"
            decision_reason = "Water clause has an explicit interval matching forecast evidence."
            counts["merged_into_forecast"] += 1
        elif observed_matches:
            classification_after = "MERGED_INTO_CURRENT_EXCAVATED_INTERVAL"
            decision_reason = (
                "Water clause has an explicit interval matching observed interval evidence."
            )
            counts["merged_into_observed_interval"] += 1
        elif checkbox_duplicate:
            classification_after = "CHECKBOX_DUPLICATE_REMOVED"
            decision_reason = "Water text is represented by the face form checkbox only."
            counts["checkbox_duplicate"] += 1
        else:
            classification_after = "WATER_OBSERVATION_UNLOCATED"
            decision_reason = "No explicit spatial interval is available; no range is inferred."
            counts["retained_water_unlocated"] += 1

        corrected_fields = []
        if classification_after == "WATER_OBSERVATION_UNLOCATED" and before_attr_hits:
            corrected_fields = _remove_unlocated_water_from_face_point(doc_evidence, raw_text)
            if corrected_fields:
                counts["face_point_attribute_governance"] += 1

        source_span_id = ";".join(clause.get("source_span_ids", []))
        source_pages = sorted(
            {
                str(span_by_id.get(span_id, {}).get("page_number", ""))
                for span_id in clause.get("source_span_ids", [])
                if span_by_id.get(span_id, {}).get("page_number") not in (None, "")
            }
        )
        rows.append(
            {
                "document_id": clause["document_id"],
                "filename": clause["filename"],
                "clause_id": clause["clause_id"],
                "raw_text": raw_text,
                "source_page": ";".join(source_pages),
                "source_span_id": source_span_id,
                "explicit_interval_in_clause": _format_intervals(intervals),
                "nearest_forecast_interval": _nearest_interval(doc_evidence, "FORECAST_SEGMENT"),
                "nearest_observed_interval": _nearest_interval(
                    doc_evidence,
                    "FACE_OBSERVATION",
                    observation_scope="CURRENT_EXCAVATED_INTERVAL",
                ),
                "linked_primary_evidence_ids": ";".join(item["evidence_uid"] for item in linked),
                "text_already_in_primary_evidence": bool(linked),
                "classification_before": clause.get("statement_role", ""),
                "classification_after": classification_after,
                "decision_reason": decision_reason,
                "face_point_attribute_hits_before": ";".join(before_attr_hits),
                "face_point_fields_corrected": ";".join(corrected_fields),
            }
        )
    return rows, counts


def _matching_interval_evidence(
    evidence: list[dict[str, Any]],
    evidence_type: str,
    intervals: list[Any],
    *,
    observation_scope: str | None = None,
) -> list[dict[str, Any]]:
    if not intervals:
        return []
    matches = []
    for item in evidence:
        if item.get("evidence_type") != evidence_type:
            continue
        if (
            observation_scope
            and item.get("attributes", {}).get("observation_scope") != observation_scope
        ):
            continue
        scope = item.get("spatial_scope", {})
        if scope.get("kind") != "INTERVAL":
            continue
        for interval in intervals:
            start = getattr(interval, "start_chainage", None)
            end = getattr(interval, "end_chainage", None)
            if start is None or end is None:
                continue
            if (
                abs(float(scope["start_chainage"]) - float(start)) < 0.01
                and abs(float(scope["end_chainage"]) - float(end)) < 0.01
            ):
                matches.append(item)
                break
    return matches


def _linked_evidence(evidence: list[dict[str, Any]], raw_text: str) -> list[dict[str, Any]]:
    raw = compact_text(raw_text)
    if not raw:
        return []
    linked = []
    for item in evidence:
        assembled = compact_text(str(item.get("assembled_text", "")))
        attrs = compact_text(json.dumps(item.get("attributes", {}), ensure_ascii=False))
        if raw in assembled or raw in attrs:
            linked.append(item)
    return linked


def _is_checkbox_only_duplicate(evidence: list[dict[str, Any]], raw_text: str) -> bool:
    raw = compact_text(raw_text)
    if "当前开挖段落" in raw:
        return False
    terms = _water_terms(raw_text)
    if not terms:
        return False
    for item in evidence:
        attrs = item.get("attributes", {})
        if attrs.get("observation_scope") != "FACE_POINT":
            continue
        form = compact_text(str(attrs.get("form_water_status", "")))
        if form and any(compact_text(term) in form for term in terms):
            return True
    return False


def _face_point_attr_hits(evidence: list[dict[str, Any]], raw_text: str) -> list[str]:
    raw = compact_text(raw_text)
    hits = set()
    for item in evidence:
        attrs = item.get("attributes", {})
        if attrs.get("observation_scope") != "FACE_POINT":
            continue
        for field, value in attrs.items():
            compact_value = compact_text(json.dumps(value, ensure_ascii=False))
            if raw and raw in compact_value:
                hits.add(field)
    return sorted(hits)


def _remove_unlocated_water_from_face_point(
    evidence: list[dict[str, Any]],
    raw_text: str,
) -> list[str]:
    corrected = set()
    terms_to_remove = {term.replace("~", "-") for term in _water_terms(raw_text)}
    raw_compact = compact_text(raw_text)
    for item in evidence:
        attrs = item.get("attributes", {})
        if attrs.get("observation_scope") != "FACE_POINT":
            continue
        field_spans = item.get("field_spans", {})
        risk_text = attrs.get("source_risk_text")
        if isinstance(risk_text, list):
            kept_risk = [text for text in risk_text if raw_compact not in compact_text(str(text))]
            if len(kept_risk) != len(risk_text):
                corrected.add("source_risk_text")
                if kept_risk:
                    attrs["source_risk_text"] = kept_risk
                else:
                    attrs.pop("source_risk_text", None)
                    field_spans.pop("source_risk_text", None)
            remaining_terms = _terms_from_texts(kept_risk)
        else:
            remaining_terms = set()

        narrative = str(attrs.get("narrative_water_observation") or "")
        narrative_terms = set(_split_water_values(narrative))
        if narrative_terms:
            governed_terms = sorted(
                term
                for term in narrative_terms
                if term.replace("~", "-") not in terms_to_remove or term in remaining_terms
            )
            if set(governed_terms) != narrative_terms:
                corrected.add("narrative_water_observation")
                if governed_terms:
                    attrs["narrative_water_observation"] = ";".join(governed_terms)
                else:
                    attrs.pop("narrative_water_observation", None)
                    field_spans.pop("narrative_water_observation", None)

        narrative_after = attrs.get("narrative_water_observation")
        form_water = attrs.get("form_water_status")
        old_water_type = attrs.get("water_type")
        if narrative_after:
            attrs["water_type"] = narrative_after
        elif form_water:
            attrs["water_type"] = form_water
        else:
            attrs.pop("water_type", None)
            field_spans.pop("water_type", None)
        if old_water_type != attrs.get("water_type"):
            corrected.add("water_type")

        conflict = bool(form_water and attrs.get("narrative_water_observation"))
        if attrs.get("water_status_conflict") != conflict:
            attrs["water_status_conflict"] = conflict
            corrected.add("water_status_conflict")
        item["attributes"] = attrs
        item["field_spans"] = field_spans
    return sorted(corrected)


def _terms_from_texts(texts: list[str]) -> set[str]:
    terms: set[str] = set()
    for text in texts:
        terms.update(_water_terms(text))
    return {term.replace("~", "-") for term in terms}


def _water_terms(text: str) -> list[str]:
    compact = compact_text(text)
    found = []
    for term in WATER_TERMS:
        if compact_text(term) in compact:
            canonical = term.replace("~", "-")
            if not any(canonical in existing for existing in found):
                found.append(canonical)
    return found


def _split_water_values(value: str) -> list[str]:
    parts = re.split(r"[;\uff1b\u3001,\uff0c]+", value)
    return [part.strip().replace("~", "-") for part in parts if part.strip()]


def _format_intervals(intervals: list[Any]) -> str:
    values = []
    for interval in intervals:
        start = getattr(interval, "start_chainage", "")
        end = getattr(interval, "end_chainage", "")
        if start != "" and end != "":
            values.append(f"{start}-{end}")
    return ";".join(values)


def _nearest_interval(
    evidence: list[dict[str, Any]],
    evidence_type: str,
    *,
    observation_scope: str | None = None,
) -> str:
    point = next(
        (
            item["spatial_scope"]["start_chainage"]
            for item in evidence
            if item.get("attributes", {}).get("observation_scope") == "FACE_POINT"
        ),
        None,
    )
    candidates = []
    for item in evidence:
        if item.get("evidence_type") != evidence_type:
            continue
        if (
            observation_scope
            and item.get("attributes", {}).get("observation_scope") != observation_scope
        ):
            continue
        scope = item.get("spatial_scope", {})
        if scope.get("kind") != "INTERVAL":
            continue
        start = float(scope["start_chainage"])
        end = float(scope["end_chainage"])
        distance = 0.0 if point is None else min(abs(point - start), abs(point - end))
        candidates.append((distance, start, end, item["evidence_uid"]))
    if not candidates:
        return ""
    _, start, end, evidence_uid = sorted(candidates)[0]
    return f"{start}-{end}|{evidence_uid}"


def _all_source_span_validation(
    *,
    spans: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
    clauses: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    refs = _reference_index(documents, evidence, assertions, clauses)
    assets = {row["asset_id"]: row for row in _read_csv(ASSET_AUDIT)}
    rows = []
    for asset_id, asset_spans in _group_by(spans, "asset_id").items():
        asset = assets.get(asset_id)
        if not asset:
            rows.extend(_asset_error_rows(asset_spans, "ASSET_NOT_FOUND"))
            continue
        path = Path(asset["source_path"])
        try:
            with pdfplumber.open(path) as pdf, fitz.open(path) as doc:
                for span in asset_spans:
                    rows.append(_validate_source_span_row(span, pdf, doc, refs))
        except Exception as exc:
            rows.extend(_asset_error_rows(asset_spans, type(exc).__name__))
    reference_rows = _span_reference_audit(spans, documents, evidence, assertions, clauses)
    return rows, reference_rows


def _reference_index(
    documents: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
    clauses: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "documents": {row["document_id"] for row in documents},
        "primary": {row["evidence_uid"] for row in evidence},
        "assertions": {row["assertion_uid"] for row in assertions},
        "clauses": {row["clause_id"] for row in clauses},
        "clause_span_ids": {
            span_id for row in clauses for span_id in row.get("source_span_ids", []) if span_id
        },
    }


def _validate_source_span_row(
    span: dict[str, Any],
    pdf: Any,
    doc: Any,
    refs: dict[str, Any],
) -> dict[str, Any]:
    problems = []
    page_width = ""
    page_height = ""
    crop_text_compact = ""
    raw_text_compact = compact_text(str(span.get("raw_text", "")))
    owner_type = span.get("owner_type", "")
    owner_id = span.get("owner_id", "")
    if span.get("document_id") not in refs["documents"]:
        problems.append("MISSING_DOCUMENT_REFERENCE")
    if owner_type == "PRIMARY_EVIDENCE" and owner_id not in refs["primary"]:
        problems.append("MISSING_PRIMARY_EVIDENCE_REFERENCE")
    elif owner_type == "REPORT_ASSERTION" and owner_id not in refs["assertions"]:
        problems.append("MISSING_REPORT_ASSERTION_REFERENCE")
    elif owner_type == "UNLOCATED_CLAUSE" and owner_id not in refs["clauses"]:
        problems.append("MISSING_UNLOCATED_CLAUSE_REFERENCE")
    elif owner_type not in {"PRIMARY_EVIDENCE", "REPORT_ASSERTION", "UNLOCATED_CLAUSE"}:
        problems.append("UNKNOWN_OWNER_TYPE")
    try:
        page_number = int(span.get("page_number", 0))
        if page_number < 1 or page_number > len(pdf.pages):
            problems.append("PAGE_OUT_OF_RANGE")
        else:
            page = pdf.pages[page_number - 1]
            page_width = round(float(page.width), 3)
            page_height = round(float(page.height), 3)
            bbox = span.get("bbox")
            if bbox is not None:
                x0, y0, x1, y1 = [float(value) for value in bbox]
                if (x0, y0, x1, y1) == (0.0, 0.0, 0.0, 0.0) or x1 <= x0 or y1 <= y0:
                    problems.append("INVALID_BBOX")
                if x0 < -1 or y0 < -1 or x1 > page.width + 1 or y1 > page.height + 1:
                    problems.append("BBOX_OUTSIDE_PAGE")
                if not any(
                    problem in problems for problem in ["INVALID_BBOX", "BBOX_OUTSIDE_PAGE"]
                ):
                    crop_text = page.crop((x0, y0, x1, y1)).extract_text() or ""
                    crop_text_compact = compact_text(crop_text)
                    if not _text_overlap(crop_text, str(span.get("raw_text", ""))):
                        problems.append("BBOX_TEXT_MISMATCH")
            else:
                page_text = doc[page_number - 1].get_text("text")
                if raw_text_compact not in compact_text(page_text):
                    problems.append("TEXT_BLOCK_NOT_ON_PAGE")
    except Exception as exc:
        problems.append(type(exc).__name__)
    return {
        "owner_type": owner_type,
        "owner_id": owner_id,
        "document_id": span.get("document_id", ""),
        "asset_id": span.get("asset_id", ""),
        "source_type": span.get("source_type", ""),
        "span_id": span.get("span_id", ""),
        "page_number": span.get("page_number", ""),
        "bbox": json.dumps(span.get("bbox"), ensure_ascii=False),
        "page_width": page_width,
        "page_height": page_height,
        "extraction_method": span.get("extraction_method", ""),
        "source_role": span.get("source_role", ""),
        "raw_text_compact_length": len(raw_text_compact),
        "crop_text_compact_length": len(crop_text_compact),
        "referenced_by_unlocated_clause": span.get("span_id") in refs["clause_span_ids"],
        "valid": not problems,
        "problems": ";".join(problems),
    }


def _asset_error_rows(spans: list[dict[str, Any]], problem: str) -> list[dict[str, Any]]:
    return [
        {
            "owner_type": span.get("owner_type", ""),
            "owner_id": span.get("owner_id", ""),
            "document_id": span.get("document_id", ""),
            "asset_id": span.get("asset_id", ""),
            "source_type": span.get("source_type", ""),
            "span_id": span.get("span_id", ""),
            "page_number": span.get("page_number", ""),
            "bbox": json.dumps(span.get("bbox"), ensure_ascii=False),
            "page_width": "",
            "page_height": "",
            "extraction_method": span.get("extraction_method", ""),
            "source_role": span.get("source_role", ""),
            "raw_text_compact_length": len(compact_text(str(span.get("raw_text", "")))),
            "crop_text_compact_length": "",
            "referenced_by_unlocated_clause": "",
            "valid": False,
            "problems": problem,
        }
        for span in spans
    ]


def _span_reference_audit(
    spans: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
    clauses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    span_ids = {row["span_id"] for row in spans}
    doc_ids = {row["document_id"] for row in documents}
    primary_ids = {row["evidence_uid"] for row in evidence}
    assertion_ids = {row["assertion_uid"] for row in assertions}
    clause_ids = {row["clause_id"] for row in clauses}
    for span in spans:
        owner_type = span.get("owner_type", "")
        owner_id = span.get("owner_id", "")
        if span.get("document_id") not in doc_ids:
            rows.append(_reference_problem(span, "MISSING_DOCUMENT_REFERENCE"))
        if owner_type == "PRIMARY_EVIDENCE" and owner_id not in primary_ids:
            rows.append(_reference_problem(span, "MISSING_PRIMARY_EVIDENCE_REFERENCE"))
        elif owner_type == "REPORT_ASSERTION" and owner_id not in assertion_ids:
            rows.append(_reference_problem(span, "MISSING_REPORT_ASSERTION_REFERENCE"))
        elif owner_type == "UNLOCATED_CLAUSE" and owner_id not in clause_ids:
            rows.append(_reference_problem(span, "MISSING_UNLOCATED_CLAUSE_REFERENCE"))
    for clause in clauses:
        for span_id in clause.get("source_span_ids", []):
            if span_id not in span_ids:
                rows.append(
                    {
                        "owner_type": "UNLOCATED_CLAUSE",
                        "owner_id": clause["clause_id"],
                        "document_id": clause["document_id"],
                        "asset_id": clause["asset_id"],
                        "source_type": clause["source_type"],
                        "span_id": span_id,
                        "problem": "CLAUSE_SPAN_NOT_FOUND",
                    }
                )
    return rows


def _reference_problem(span: dict[str, Any], problem: str) -> dict[str, Any]:
    return {
        "owner_type": span.get("owner_type", ""),
        "owner_id": span.get("owner_id", ""),
        "document_id": span.get("document_id", ""),
        "asset_id": span.get("asset_id", ""),
        "source_type": span.get("source_type", ""),
        "span_id": span.get("span_id", ""),
        "problem": problem,
    }


def _unlocated_clause_audit(clauses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "clause_id": row["clause_id"],
            "document_id": row["document_id"],
            "asset_id": row["asset_id"],
            "filename": row["filename"],
            "statement_role": row["statement_role"],
            "source_clause_role": row["source_clause_role"],
            "enters_primary_evidence": row["enters_primary_evidence"],
            "enters_document_scope": row["enters_document_scope"],
            "raw_text": row["raw_text"],
        }
        for row in clauses
    ]


def _snapshot_files() -> list[Path]:
    candidates = [
        REPO / "src/tbm_twin/geology/table_parser_v2",
        REPO / "scripts/run_stage2_table_parser_v2_shadow.py",
        REPO / "scripts/run_face_sketch_v2_fixed_audit.py",
        REPO / "scripts/build_stage2_geology_v2_freeze_candidate.py",
        REPO / "scripts/finalize_stage2_geology_v2_freeze_candidate.py",
        REPO / "pyproject.toml",
        REPO / "tests/manual_gold/geology",
        REPO / "tests/unit/test_table_parser_v2_gold.py",
    ]
    for pattern in ("requirements*.txt", "*.lock", "poetry.lock", "uv.lock", "pdm.lock"):
        candidates.extend(REPO.glob(pattern))
    files: list[Path] = []
    for path in candidates:
        if path.is_dir():
            files.extend(sorted(item for item in path.rglob("*") if item.is_file()))
        elif path.is_file():
            files.append(path)
    return sorted(set(files))


def _write_source_hashes(files: list[Path]) -> None:
    lines = []
    for path in files:
        rel = path.relative_to(REPO).as_posix()
        lines.append(f"{_sha256(path)}  {rel}")
    (OUT / "parser_source_hashes.sha256").write_text(
        "\n".join(sorted(lines)) + "\n",
        encoding="utf-8",
    )


def _write_source_snapshot(files: list[Path]) -> str:
    snapshot = OUT / "parser_source_snapshot.tar.gz"
    with tarfile.open(snapshot, "w:gz") as tar:
        for path in files:
            tar.add(path, arcname=path.relative_to(REPO).as_posix())
    return _sha256(snapshot)


def _hash_file_list(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(REPO).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _build_manifest(
    *,
    documents: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
    clauses: list[dict[str, Any]],
    spans: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    source_issues: list[dict[str, Any]],
    hard_checks: list[dict[str, Any]],
    orphan_reference: list[dict[str, Any]],
    span_audit: list[dict[str, Any]],
    water_audit: list[dict[str, Any]],
    governance_counts: Counter[str],
    source_snapshot_sha256: str,
    parser_source_tree_hash: str,
) -> dict[str, Any]:
    evidence_combo_counts = Counter(
        f"{row['source_type']}|{row['evidence_type']}|{row['spatial_scope']['kind']}"
        for row in evidence
    )
    invalid_span_count = sum(not _as_bool(row.get("valid")) for row in span_audit)
    water_counts = Counter(row["classification_after"] for row in water_audit)
    summary = {
        "canonical_documents": len(documents),
        "primary_evidence": len(evidence),
        "primary_evidence_type_counts": dict(Counter(row["evidence_type"] for row in evidence)),
        "primary_evidence_combo_counts": dict(evidence_combo_counts),
        "report_assertions": len(assertions),
        "report_assertion_type_counts": dict(Counter(row["assertion_type"] for row in assertions)),
        "unlocated_clauses": len(clauses),
        "unlocated_clause_type_counts": dict(Counter(row["statement_role"] for row in clauses)),
        "source_spans": len(spans),
        "outcome_status_counts": dict(Counter(row["parse_status"] for row in outcomes)),
        "source_issue_counts": dict(Counter(row["issue_code"] for row in source_issues)),
        "source_issue_category_counts": dict(
            Counter(row["issue_category"] for row in source_issues)
        ),
        "hard_check_count": len(hard_checks),
        "all_source_span_audited_count": len(span_audit),
        "all_source_span_valid_count": len(span_audit) - invalid_span_count,
        "invalid_source_span_count": invalid_span_count,
        "orphan_reference_count": len(orphan_reference),
        "water_observation_unlocated_original_count": len(water_audit),
        "water_observation_unlocated_retained_count": water_counts["WATER_OBSERVATION_UNLOCATED"],
        "water_observation_merged_into_forecast_count": water_counts[
            "MERGED_INTO_FORECAST_SEGMENT"
        ],
        "water_observation_merged_into_observed_interval_count": water_counts[
            "MERGED_INTO_CURRENT_EXCAVATED_INTERVAL"
        ],
        "water_observation_checkbox_duplicate_count": water_counts["CHECKBOX_DUPLICATE_REMOVED"],
        "water_observation_duplicate_clause_removed_count": 0,
        "water_face_point_attribute_governance_count": governance_counts[
            "face_point_attribute_governance"
        ],
        "input_asset_manifest_sha256": _sha256(ASSET_AUDIT),
        "parser_entrypoint": "tbm_twin.geology.table_parser_v2.parse_pdf_v2",
        "source_snapshot_sha256": source_snapshot_sha256,
        "parser_source_tree_hash": parser_source_tree_hash,
    }
    return {"summary": summary, "files": _file_hash_map()}


def _write_report(manifest: dict[str, Any]) -> None:
    summary = manifest["summary"]
    water_line = (
        f"- WATER_OBSERVATION_UNLOCATED: original "
        f"{summary['water_observation_unlocated_original_count']}, retained "
        f"{summary['water_observation_unlocated_retained_count']}, merged forecast "
        f"{summary['water_observation_merged_into_forecast_count']}, merged observed "
        f"{summary['water_observation_merged_into_observed_interval_count']}, checkbox duplicate "
        f"{summary['water_observation_checkbox_duplicate_count']}, duplicate clauses removed "
        f"{summary['water_observation_duplicate_clause_removed_count']}"
    )
    lines = [
        "# Stage 2 Geology V2 Freeze Candidate",
        "",
        "This directory is the final freeze-candidate verification snapshot for table_parser_v2.",
        (
            "It does not recalculate Applicability, switch the formal pipeline, "
            "enter Stage 3, or write Gold."
        ),
        "",
        "## Final Counts",
        "",
        f"- Documents: {summary['canonical_documents']}",
        f"- Primary Evidence: {summary['primary_evidence']}",
        f"- ReportAssertion: {summary['report_assertions']}",
        f"- Unlocated Clause: {summary['unlocated_clauses']}",
        f"- SourceSpan: {summary['source_spans']}",
        "",
        "## Primary Evidence Distribution",
        "",
        *[
            f"- {key}: {value}"
            for key, value in sorted(summary["primary_evidence_combo_counts"].items())
        ],
        "",
        "## LOCAL_UNLOCATED Governance",
        "",
        *[
            f"- {key}: {value}"
            for key, value in sorted(summary["unlocated_clause_type_counts"].items())
        ],
        water_line,
        (
            f"- FACE_POINT water attribute governance corrections: "
            f"{summary['water_face_point_attribute_governance_count']}"
        ),
        "",
        "## SourceSpan Integrity",
        "",
        f"- audited SourceSpan rows: {summary['all_source_span_audited_count']}",
        f"- valid SourceSpan rows: {summary['all_source_span_valid_count']}",
        f"- invalid SourceSpan rows: {summary['invalid_source_span_count']}",
        f"- missing/orphan references: {summary['orphan_reference_count']}",
        "",
        "## Outcomes",
        "",
        *[f"- {key}: {value}" for key, value in sorted(summary["outcome_status_counts"].items())],
        "",
        "## Source Issues Kept",
        "",
        *[f"- {key}: {value}" for key, value in sorted(summary["source_issue_counts"].items())],
        "",
        "## Regression Status",
        "",
        "- manual Gold: see pytest run, expected 3/3",
        "- fixed regression: see pytest run, expected 10/10",
        "",
        "## Snapshot",
        "",
        f"- parser source snapshot sha256: {summary['source_snapshot_sha256']}",
        f"- parser source tree hash: {summary['parser_source_tree_hash']}",
    ]
    (OUT / "freeze_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _file_hash_map() -> dict[str, str]:
    return {
        path.name: _sha256(path)
        for path in sorted(OUT.iterdir())
        if path.is_file() and path.name not in {"file_hashes.sha256", "freeze_manifest.json"}
    }


def _write_hashes() -> None:
    lines = [f"{digest}  {name}" for name, digest in sorted(_file_hash_map().items())]
    (OUT / "file_hashes.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key, ""))].append(row)
    return grouped


def _text_overlap(left: str, right: str) -> bool:
    left_c = compact_text(left)
    right_c = compact_text(right)
    return bool(left_c and right_c and (left_c in right_c or right_c in left_c))


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(args: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=REPO,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return ""


if __name__ == "__main__":
    main()
