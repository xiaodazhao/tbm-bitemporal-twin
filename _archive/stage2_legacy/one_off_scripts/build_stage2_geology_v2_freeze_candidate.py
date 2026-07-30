"""Build the Stage 2 geology table_parser_v2 freeze candidate artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import pdfplumber

from tbm_twin.geology.table_parser_v2 import parse_pdf_v2
from tbm_twin.geology.table_parser_v2.text_utils import compact_text, parse_all_chainage_intervals

REPO = Path(__file__).resolve().parents[1]
SHADOW = REPO / "artifacts/stage2_table_parser_v2_shadow"
RAW = REPO / "artifacts/stage2_raw_geology_validation"
ASSET_AUDIT = RAW / "source_asset_audit.csv"
OUT = REPO / "artifacts/stage2_geology_v2_freeze_candidate"

STATUS_SUCCESS = "SUCCESS"
STATUS_SUCCESS_WITH_WARNINGS = "SUCCESS_WITH_WARNINGS"
STATUS_EXCLUDED_DUPLICATE = "EXCLUDED_DUPLICATE"
STATUS_EXCLUDED_OUT_OF_SCOPE = "EXCLUDED_OUT_OF_SCOPE"
STATUS_UNSUPPORTED_TEMPLATE = "UNSUPPORTED_TEMPLATE"
STATUS_PARSE_ERROR = "PARSE_ERROR"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    assets = _read_csv(ASSET_AUDIT)
    hsp_tsp_documents = [
        row
        for row in _read_jsonl(SHADOW / "geological_documents_v2.jsonl")
        if row["source_type"] != "FACE_SKETCH"
    ]
    hsp_tsp_evidence = [
        row
        for row in _read_jsonl(SHADOW / "primary_geological_evidence_v2.jsonl")
        if row["source_type"] != "FACE_SKETCH"
    ]
    assertions = _read_jsonl(SHADOW / "report_assertions_v2.jsonl")

    sketch_documents: list[dict[str, Any]] = []
    sketch_evidence: list[dict[str, Any]] = []
    unlocated_clauses: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    source_issues: list[dict[str, Any]] = []

    for asset in assets:
        status = STATUS_SUCCESS
        warnings: list[str] = []
        error_code = ""
        if asset["duplicate_of_asset_id"]:
            status = STATUS_EXCLUDED_DUPLICATE
        elif asset["research_scope"] == "OUT_OF_SCOPE":
            status = STATUS_EXCLUDED_OUT_OF_SCOPE
        elif asset["source_type"] != "FACE_SKETCH":
            status = STATUS_SUCCESS
        else:
            try:
                result = parse_pdf_v2(Path(asset["source_path"]))
            except Exception as exc:  # final audit records parser failures explicitly
                status = STATUS_PARSE_ERROR
                error_code = type(exc).__name__
            else:
                warnings = list(result.document.parse_warnings)
                status = STATUS_SUCCESS_WITH_WARNINGS if warnings else STATUS_SUCCESS
                document_id = f"doc_{asset['asset_id']}"
                sketch_documents.append(_document_json(document_id, asset, result))
                for index, evidence in enumerate(result.primary_evidence, start=1):
                    evidence_uid = f"{document_id}_e{index:04d}"
                    sketch_evidence.append(
                        {
                            "evidence_uid": evidence_uid,
                            "document_id": document_id,
                            "asset_id": asset["asset_id"],
                            "filename": asset["source_filename"],
                            "source_type": asset["source_type"],
                            **_governed_primary_evidence(evidence),
                        }
                    )
                for clause_index, clause in enumerate(
                    _clauses_from_audit(asset, document_id, result.audit_rows),
                    start=1,
                ):
                    unlocated_clauses.append(
                        {
                            "clause_id": f"{document_id}_c{clause_index:04d}",
                            **clause,
                        }
                    )
                source_issues.extend(_source_issues_from_sketch(asset, result.audit_rows, warnings))
        outcomes.append(_outcome_row(asset, status, warnings, error_code))

    documents = sorted(
        [*hsp_tsp_documents, *sketch_documents],
        key=lambda row: (row["source_type"], row["asset_id"]),
    )
    evidence = sorted(
        [*hsp_tsp_evidence, *sketch_evidence],
        key=lambda row: (row["source_type"], row["asset_id"], row["evidence_uid"]),
    )
    source_issues.extend(_source_issues_from_tsp_conflicts(assertions))
    spans = _source_span_rows(evidence, assertions, unlocated_clauses)
    hard_checks = _hard_checks(documents, evidence)
    span_audit, orphan_audit = _source_span_audits(
        documents, evidence, assertions, unlocated_clauses
    )
    unlocated_audit = _unlocated_clause_audit(unlocated_clauses)
    expected_count_rows = _count_difference_rows(evidence)

    _write_jsonl("geological_documents.jsonl", documents)
    _write_jsonl("primary_geological_evidence.jsonl", evidence)
    _write_jsonl("report_assertions.jsonl", assertions)
    _write_jsonl("source_spans.jsonl", spans)
    _write_jsonl("unlocated_clauses.jsonl", unlocated_clauses)
    _write_csv("document_parse_outcomes.csv", outcomes)
    _write_csv("primary_evidence_hard_check.csv", hard_checks)
    _write_csv("unlocated_clause_audit.csv", unlocated_audit)
    _write_csv("final_source_span_audit.csv", span_audit)
    _write_csv("orphan_reference_audit.csv", orphan_audit)
    _write_csv("source_data_issue_audit.csv", source_issues)
    _write_csv("evidence_count_difference_audit.csv", expected_count_rows)

    manifest = _freeze_manifest(
        assets=assets,
        documents=documents,
        evidence=evidence,
        assertions=assertions,
        clauses=unlocated_clauses,
        spans=spans,
        outcomes=outcomes,
        source_issues=source_issues,
        hard_checks=hard_checks,
        span_audit=span_audit,
        orphan_audit=orphan_audit,
    )
    method = _method_version()
    schema = _schema_manifest(documents, evidence, assertions, unlocated_clauses, spans)
    _write_json("freeze_manifest.json", manifest)
    _write_json("method_version.json", method)
    _write_json("schema_manifest.json", schema)
    _write_hashes()
    _write_report(manifest)
    print(json.dumps(manifest["summary"], ensure_ascii=False, indent=2))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _document_json(document_id: str, asset: dict[str, str], result: Any) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "asset_id": asset["asset_id"],
        "filename": asset["source_filename"],
        "source_type": asset["source_type"],
        "source_path": asset["source_path"],
        "research_scope": asset["research_scope"],
        "duplicate_of_asset_id": asset["duplicate_of_asset_id"],
        "canonical_asset_id": asset["canonical_asset_id"],
        "document": _jsonable(result.document),
    }


def _governed_primary_evidence(evidence: Any) -> dict[str, Any]:
    row = _jsonable(evidence)
    attrs = dict(row.get("attributes", {}))
    field_spans = dict(row.get("field_spans", {}))
    assembled_text = str(row.get("assembled_text", ""))
    for key in ["local_unlocated_observations", "recommendations", "statement_role"]:
        for value in _list_values(attrs.get(key)):
            assembled_text = assembled_text.replace(str(value), " ")
        attrs.pop(key, None)
        field_spans.pop(key, None)
    if attrs.get("observation_scope") == "FACE_POINT" and _has_unseparated_forecast_text(
        assembled_text
    ):
        assembled_text = _strip_forecast_like_text(assembled_text)
        for key in [
            "lithology",
            "joint_development",
            "rock_mass_state",
            "stability",
            "block_fall_or_collapse",
            "narrative_water_observation",
            "source_risk_text",
        ]:
            attrs.pop(key, None)
            field_spans.pop(key, None)
        if attrs.get("form_water_status"):
            attrs["water_type"] = attrs["form_water_status"]
        else:
            attrs.pop("water_type", None)
            field_spans.pop("water_type", None)
        attrs["water_status_conflict"] = False
    row["attributes"] = attrs
    row["field_spans"] = field_spans
    row["assembled_text"] = assembled_text
    return row


def _list_values(value: Any) -> list[Any]:
    if value in (None, "", [], {}, False):
        return []
    return value if isinstance(value, list) else [value]


def _has_unseparated_forecast_text(text: str) -> bool:
    compact = compact_text(text)
    return any(token in compact for token in ["推测", "前方预计", "推测进入", "预计于"])


def _strip_forecast_like_text(text: str) -> str:
    sentences = re_split_keep(text)
    kept = [
        sentence
        for sentence in sentences
        if not any(
            token in compact_text(sentence) for token in ["推测", "前方预计", "推测进入", "预计于"]
        )
    ]
    return " ".join(kept)


def re_split_keep(text: str) -> list[str]:
    parts = []
    current = []
    for char in text:
        current.append(char)
        if char in {"。", "\uff1b", ";"}:
            parts.append("".join(current))
            current = []
    if current:
        parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _outcome_row(
    asset: dict[str, str],
    status: str,
    warnings: list[str],
    error_code: str,
) -> dict[str, Any]:
    return {
        "asset_id": asset["asset_id"],
        "filename": asset["source_filename"],
        "source_type": asset["source_type"],
        "source_path": asset["source_path"],
        "research_scope": asset["research_scope"],
        "duplicate_of_asset_id": asset["duplicate_of_asset_id"],
        "canonical_asset_id": asset["canonical_asset_id"],
        "parse_status": status,
        "warning_codes": ";".join(warnings),
        "error_code": error_code,
    }


def _clauses_from_audit(
    asset: dict[str, str],
    document_id: str,
    audit_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    clauses = []
    for row in audit_rows:
        if row.get("audit_type") != "CLAUSE_ROLE":
            continue
        role = row.get("clause_role")
        if role not in {"LOCAL_UNLOCATED", "RECOMMENDATION"}:
            continue
        statement_role = _statement_role(row)
        clauses.append(
            {
                "document_id": document_id,
                "asset_id": asset["asset_id"],
                "filename": asset["source_filename"],
                "source_type": asset["source_type"],
                "statement_role": statement_role,
                "source_clause_role": role,
                "raw_text": row.get("raw_text", ""),
                "source_span_ids": str(row.get("source_span_ids", "")).split(";")
                if row.get("source_span_ids")
                else [],
                "enters_primary_evidence": False,
                "enters_document_scope": False,
            }
        )
    return clauses


def _statement_role(row: dict[str, Any]) -> str:
    role = row.get("clause_role")
    text = str(row.get("raw_text", ""))
    if role == "RECOMMENDATION":
        return "RECOMMENDATION"
    if "当前开挖段落" in text and any(term in text for term in ["出水", "渗水", "涌水"]):
        return "WATER_OBSERVATION_UNLOCATED"
    if "当前开挖段落" in text:
        return "CURRENT_LOCAL_UNLOCATED"
    if text:
        return "GENERAL_DESCRIPTION"
    return "OTHER"


def _source_issues_from_sketch(
    asset: dict[str, str],
    audit_rows: list[dict[str, Any]],
    warnings: list[str],
) -> list[dict[str, Any]]:
    issues = []
    for row in audit_rows:
        if row.get("audit_type") == "INVALID_SOURCE_INTERVAL":
            issues.append(
                {
                    "asset_id": asset["asset_id"],
                    "filename": asset["source_filename"],
                    "source_type": asset["source_type"],
                    "issue_category": "SOURCE_DOCUMENT_ERROR",
                    "issue_code": "INVALID_SOURCE_INTERVAL",
                    "detail": row.get("raw_interval", ""),
                    "raw_text": row.get("raw_text", ""),
                }
            )
    for warning in warnings:
        category = (
            "SOURCE_METADATA_CONFLICT"
            if warning == "SOURCE_CHAINAGE_CONFLICT"
            else "PARSER_WARNING"
        )
        issues.append(
            {
                "asset_id": asset["asset_id"],
                "filename": asset["source_filename"],
                "source_type": asset["source_type"],
                "issue_category": category,
                "issue_code": warning,
                "detail": warning,
                "raw_text": "",
            }
        )
    return issues


def _source_issues_from_tsp_conflicts(assertions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues = []
    for assertion in assertions:
        if assertion.get("consistency_status") != "CONFLICT":
            continue
        issues.append(
            {
                "asset_id": assertion["asset_id"],
                "filename": assertion["filename"],
                "source_type": assertion["source_type"],
                "issue_category": "INTERNAL_REPORT_CONFLICT",
                "issue_code": assertion["assertion_type"],
                "detail": json.dumps(assertion.get("conflict_details", []), ensure_ascii=False),
                "raw_text": assertion.get("raw_text", ""),
            }
        )
    return issues


def _source_span_rows(
    evidence: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
    clauses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for evidence_row in evidence:
        for span in evidence_row.get("source_spans", []):
            rows.append(
                {
                    "owner_type": "PRIMARY_EVIDENCE",
                    "owner_id": evidence_row["evidence_uid"],
                    "document_id": evidence_row["document_id"],
                    "asset_id": evidence_row["asset_id"],
                    "source_type": evidence_row["source_type"],
                    **span,
                }
            )
    for assertion in assertions:
        for span in assertion.get("source_spans", []):
            rows.append(
                {
                    "owner_type": "REPORT_ASSERTION",
                    "owner_id": assertion["assertion_uid"],
                    "document_id": assertion["document_id"],
                    "asset_id": assertion["asset_id"],
                    "source_type": assertion["source_type"],
                    **span,
                }
            )
    span_by_id = {row["span_id"]: row for row in rows}
    for clause in clauses:
        for span_id in clause["source_span_ids"]:
            span = span_by_id.get(span_id, {})
            rows.append(
                {
                    "owner_type": "UNLOCATED_CLAUSE",
                    "owner_id": clause["clause_id"],
                    "document_id": clause["document_id"],
                    "asset_id": clause["asset_id"],
                    "source_type": clause["source_type"],
                    **span,
                    "span_id": span_id,
                }
            )
    return rows


def _hard_checks(
    documents: list[dict[str, Any]], evidence: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    doc_scope_by_id = {
        row["document_id"]: row["document"].get("document_spatial_scope") for row in documents
    }
    rows = []
    for item in evidence:
        attrs = item.get("attributes", {})
        scope = item["spatial_scope"]
        combo = (item["evidence_type"], item["epistemic_status"], scope["kind"])
        valid_combo = combo in {
            ("FACE_OBSERVATION", "OBSERVED", "POINT"),
            ("FACE_OBSERVATION", "OBSERVED", "INTERVAL"),
            ("FORECAST_SEGMENT", "FORECAST", "INTERVAL"),
            ("DESIGN_BACKGROUND", "BACKGROUND", "INTERVAL"),
        }
        if not valid_combo:
            rows.append(_check_row(item, "INVALID_TYPE_STATUS_SPATIAL_COMBO", str(combo)))
        if scope["kind"] == "POINT" and scope["start_chainage"] != scope["end_chainage"]:
            rows.append(_check_row(item, "POINT_START_END_MISMATCH", scope["raw_expression"]))
        if scope["kind"] == "INTERVAL" and scope["start_chainage"] >= scope["end_chainage"]:
            rows.append(_check_row(item, "INVALID_INTERVAL", scope["raw_expression"]))
        if item["evidence_type"] == "FORECAST_SEGMENT":
            doc_scope = doc_scope_by_id.get(item["document_id"])
            if (
                doc_scope
                and item["source_type"] != "FACE_SKETCH"
                and (
                    scope["start_chainage"] < doc_scope["start_chainage"] - 1
                    or scope["end_chainage"] > doc_scope["end_chainage"] + 1
                )
            ):
                rows.append(
                    _check_row(item, "FORECAST_OUTSIDE_DOCUMENT_SCOPE", scope["raw_expression"])
                )
            if item["source_type"] == "FACE_SKETCH" and scope["basis"] != "forecast_segment":
                rows.append(_check_row(item, "SKETCH_FORECAST_NOT_FROM_CLAUSE", scope["basis"]))
        if attrs.get("observation_scope") == "FACE_POINT":
            text = compact_text(item.get("assembled_text", ""))
            if any(token in text for token in ["推测", "前方预计", "推测进入"]):
                rows.append(_check_row(item, "PREDICTION_TEXT_ON_FACE_POINT", ""))
            if "当前开挖段落" in text and parse_all_chainage_intervals(
                item.get("assembled_text", "")
            ):
                rows.append(_check_row(item, "CURRENT_INTERVAL_TEXT_ON_FACE_POINT", ""))
            if attrs.get("face_chainage_source_text") and scope["basis"] != "header_face_chainage":
                rows.append(_check_row(item, "FACE_POINT_NOT_HEADER_CHAINAGE", scope["basis"]))
        if "INVALID_SOURCE_INTERVAL" in json.dumps(item, ensure_ascii=False):
            rows.append(_check_row(item, "INVALID_SOURCE_INTERVAL_AS_EVIDENCE", ""))
        if attrs.get("statement_role") == "RECOMMENDATION" and attrs.get("source_risk_text"):
            rows.append(_check_row(item, "RECOMMENDATION_IN_RISK_FIELD", ""))
    return rows


def _check_row(item: dict[str, Any], code: str, detail: str) -> dict[str, Any]:
    return {
        "document_id": item["document_id"],
        "evidence_uid": item["evidence_uid"],
        "asset_id": item["asset_id"],
        "filename": item["filename"],
        "source_type": item["source_type"],
        "check_code": code,
        "detail": detail,
    }


def _source_span_audits(
    documents: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
    clauses: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    doc_ids = {row["document_id"] for row in documents}
    all_rows = [
        ("PRIMARY_EVIDENCE", row["evidence_uid"], row["document_id"], row) for row in evidence
    ] + [("REPORT_ASSERTION", row["assertion_uid"], row["document_id"], row) for row in assertions]
    span_records = []
    orphan = []
    for owner_type, owner_id, document_id, row in all_rows:
        if document_id not in doc_ids:
            orphan.append(
                {
                    "owner_type": owner_type,
                    "owner_id": owner_id,
                    "problem": "MISSING_DOCUMENT_REFERENCE",
                    "document_id": document_id,
                }
            )
        source_span_ids = {span["span_id"] for span in row.get("source_spans", [])}
        for field, ids in row.get("field_spans", {}).items():
            for span_id in ids:
                if span_id not in source_span_ids:
                    orphan.append(
                        {
                            "owner_type": owner_type,
                            "owner_id": owner_id,
                            "problem": "FIELD_SPAN_NOT_IN_SOURCE_SPANS",
                            "document_id": document_id,
                            "span_id": span_id,
                            "field": field,
                        }
                    )
        for span in row.get("source_spans", []):
            span_records.append((row, owner_type, owner_id, span))
    known_span_ids = {
        span["span_id"] for _, _, _, row in all_rows for span in row.get("source_spans", [])
    }
    for clause in clauses:
        if clause["document_id"] not in doc_ids:
            orphan.append(
                {
                    "owner_type": "UNLOCATED_CLAUSE",
                    "owner_id": clause["clause_id"],
                    "problem": "MISSING_DOCUMENT_REFERENCE",
                    "document_id": clause["document_id"],
                }
            )
        for span_id in clause["source_span_ids"]:
            if span_id not in known_span_ids:
                orphan.append(
                    {
                        "owner_type": "UNLOCATED_CLAUSE",
                        "owner_id": clause["clause_id"],
                        "problem": "CLAUSE_SPAN_NOT_FOUND",
                        "document_id": clause["document_id"],
                        "span_id": span_id,
                    }
                )
    return _validate_span_records(span_records), orphan


def _validate_span_records(
    records: list[tuple[dict[str, Any], str, str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    out = []
    by_asset: dict[str, list[tuple[dict[str, Any], str, str, dict[str, Any]]]] = defaultdict(list)
    for record in records:
        by_asset[record[0]["asset_id"]].append(record)
    for asset_id, asset_records in by_asset.items():
        path = _source_path_for_asset(asset_id)
        try:
            with pdfplumber.open(path) as pdf, fitz.open(path) as doc:
                for row, owner_type, owner_id, span in asset_records:
                    out.append(
                        _validate_span_with_open_pdf(row, owner_type, owner_id, span, pdf, doc)
                    )
        except Exception as exc:
            for row, owner_type, owner_id, span in asset_records:
                out.append(
                    _span_audit_row(
                        row=row,
                        owner_type=owner_type,
                        owner_id=owner_id,
                        span=span,
                        valid=False,
                        problems=[type(exc).__name__],
                    )
                )
    return out


def _validate_span_with_open_pdf(
    row: dict[str, Any],
    owner_type: str,
    owner_id: str,
    span: dict[str, Any],
    pdf: Any,
    doc: Any,
) -> dict[str, Any]:
    valid = True
    problems = []
    try:
        page_number = int(span["page_number"])
        if page_number < 1 or page_number > len(pdf.pages):
            valid = False
            problems.append("PAGE_OUT_OF_RANGE")
        elif span.get("bbox") is not None:
            x0, y0, x1, y1 = [float(value) for value in span["bbox"]]
            page = pdf.pages[page_number - 1]
            if (x0, y0, x1, y1) == (0.0, 0.0, 0.0, 0.0) or x1 <= x0 or y1 <= y0:
                valid = False
                problems.append("INVALID_BBOX")
            if x0 < -1 or y0 < -1 or x1 > page.width + 1 or y1 > page.height + 1:
                valid = False
                problems.append("BBOX_OUTSIDE_PAGE")
            if valid:
                crop = page.crop((x0, y0, x1, y1)).extract_text() or ""
                if not _text_overlap(crop, span["raw_text"]):
                    valid = False
                    problems.append("BBOX_TEXT_MISMATCH")
        else:
            page_text = doc[page_number - 1].get_text("text")
            if compact_text(span["raw_text"]) not in compact_text(page_text):
                valid = False
                problems.append("TEXT_BLOCK_NOT_ON_PAGE")
    except Exception as exc:  # validation audit should not abort freeze assembly
        valid = False
        problems.append(type(exc).__name__)
    return _span_audit_row(
        row=row,
        owner_type=owner_type,
        owner_id=owner_id,
        span=span,
        valid=valid,
        problems=problems,
    )


def _span_audit_row(
    *,
    row: dict[str, Any],
    owner_type: str,
    owner_id: str,
    span: dict[str, Any],
    valid: bool,
    problems: list[str],
) -> dict[str, Any]:
    return {
        "owner_type": owner_type,
        "owner_id": owner_id,
        "document_id": row["document_id"],
        "asset_id": row["asset_id"],
        "source_type": row["source_type"],
        "span_id": span["span_id"],
        "page_number": span.get("page_number"),
        "bbox": span.get("bbox"),
        "extraction_method": span.get("extraction_method"),
        "valid": valid,
        "problems": ";".join(problems),
    }


def _source_path_for_asset(asset_id: str) -> Path:
    for row in _read_csv(ASSET_AUDIT):
        if row["asset_id"] == asset_id:
            return Path(row["source_path"])
    return Path("")


def _text_overlap(left: str, right: str) -> bool:
    left_c = compact_text(left)
    right_c = compact_text(right)
    return bool(left_c and right_c and (left_c in right_c or right_c in left_c))


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


def _count_difference_rows(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expected = {
        ("FACE_SKETCH", "FACE_OBSERVATION", "POINT"): 167,
        ("FACE_SKETCH", "FORECAST_SEGMENT", "INTERVAL"): 100,
        ("FACE_SKETCH", "FACE_OBSERVATION", "INTERVAL"): 55,
        ("SONIC_FORECAST", "FACE_OBSERVATION", "POINT"): 49,
        ("SONIC_FORECAST", "FORECAST_SEGMENT", "INTERVAL"): 214,
        ("TSP_REPORT", "FACE_OBSERVATION", "POINT"): 7,
        ("TSP_REPORT", "FORECAST_SEGMENT", "INTERVAL"): 67,
    }
    actual = Counter(
        (row["source_type"], row["evidence_type"], row["spatial_scope"]["kind"]) for row in evidence
    )
    rows = []
    for key, expected_count in expected.items():
        actual_count = actual[key]
        if actual_count != expected_count:
            rows.append(
                {
                    "source_type": key[0],
                    "evidence_type": key[1],
                    "spatial_kind": key[2],
                    "expected_count": expected_count,
                    "actual_count": actual_count,
                    "difference": actual_count - expected_count,
                    "reason": "Count differs from freeze expectation; inspect source rows.",
                }
            )
    total = len(evidence)
    if total != 659:
        rows.append(
            {
                "source_type": "ALL",
                "evidence_type": "ALL",
                "spatial_kind": "ALL",
                "expected_count": 659,
                "actual_count": total,
                "difference": total - 659,
                "reason": "Total Primary Evidence differs from freeze expectation.",
            }
        )
    return rows


def _freeze_manifest(
    *,
    assets: list[dict[str, str]],
    documents: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
    clauses: list[dict[str, Any]],
    spans: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    source_issues: list[dict[str, Any]],
    hard_checks: list[dict[str, Any]],
    span_audit: list[dict[str, Any]],
    orphan_audit: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence_type_counts = Counter(row["evidence_type"] for row in evidence)
    evidence_combo_counts = Counter(
        f"{row['source_type']}|{row['evidence_type']}|{row['spatial_scope']['kind']}"
        for row in evidence
    )
    assertion_counts = Counter(row["assertion_type"] for row in assertions)
    clause_counts = Counter(row["statement_role"] for row in clauses)
    outcome_counts = Counter(row["parse_status"] for row in outcomes)
    issue_counts = Counter(row["issue_code"] for row in source_issues)
    invalid_spans = sum(row["valid"] in {False, "False"} for row in span_audit)
    summary = {
        "canonical_documents": len(documents),
        "primary_evidence": len(evidence),
        "primary_evidence_type_counts": dict(evidence_type_counts),
        "primary_evidence_combo_counts": dict(evidence_combo_counts),
        "report_assertions": len(assertions),
        "report_assertion_type_counts": dict(assertion_counts),
        "unlocated_clauses": len(clauses),
        "unlocated_clause_type_counts": dict(clause_counts),
        "source_spans": len(spans),
        "outcome_status_counts": dict(outcome_counts),
        "source_issue_counts": dict(issue_counts),
        "hard_check_count": len(hard_checks),
        "invalid_source_span_count": invalid_spans,
        "orphan_reference_count": len(orphan_audit),
        "input_asset_count": len(assets),
        "input_asset_manifest_sha256": _sha256(ASSET_AUDIT),
        "parser_entrypoint": "tbm_twin.geology.table_parser_v2.parse_pdf_v2",
    }
    return {
        "summary": summary,
        "files": _file_hash_map(),
    }


def _method_version() -> dict[str, Any]:
    return {
        "parser_name": "table_parser_v2",
        "parser_version": "stage2_freeze_candidate_2026-07-30",
        "source_asset_snapshot_version": _sha256(ASSET_AUDIT),
        "schema_version": "geology_v2_freeze_candidate.v1",
        "manual_gold_version": _hash_tree(REPO / "tests/manual_gold/geology"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "git_commit_hash": _git(["rev-parse", "HEAD"]) or "NO_COMMITS",
        "working_tree_dirty": bool(_git(["status", "--short"])),
        "pdfplumber_version": getattr(pdfplumber, "__version__", "UNKNOWN"),
        "pymupdf_version": fitz.version[0],
    }


def _schema_manifest(
    documents: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
    clauses: list[dict[str, Any]],
    spans: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "geological_documents": sorted({key for row in documents for key in row}),
        "primary_geological_evidence": sorted({key for row in evidence for key in row}),
        "report_assertions": sorted({key for row in assertions for key in row}),
        "unlocated_clauses": sorted({key for row in clauses for key in row}),
        "source_spans": sorted({key for row in spans for key in row}),
    }


def _write_report(manifest: dict[str, Any]) -> None:
    summary = manifest["summary"]
    lines = [
        "# Stage 2 Geology V2 Freeze Candidate",
        "",
        "This directory is a freeze candidate assembled from table_parser_v2 shadow outputs.",
        (
            "It does not recalculate Applicability, switch the formal pipeline, "
            "enter Stage 3, or write Gold."
        ),
        "",
        "## Counts",
        "",
        f"- canonical documents: {summary['canonical_documents']}",
        f"- primary evidence: {summary['primary_evidence']}",
        f"- report assertions: {summary['report_assertions']}",
        f"- unlocated clauses: {summary['unlocated_clauses']}",
        f"- source spans: {summary['source_spans']}",
        "",
        "## Evidence Distribution",
        "",
        *[
            f"- {key}: {value}"
            for key, value in sorted(summary["primary_evidence_combo_counts"].items())
        ],
        "",
        "## Integrity",
        "",
        f"- hard check findings: {summary['hard_check_count']}",
        f"- invalid source spans: {summary['invalid_source_span_count']}",
        f"- orphan references: {summary['orphan_reference_count']}",
        "",
        "## Outcomes",
        "",
        *[f"- {key}: {value}" for key, value in sorted(summary["outcome_status_counts"].items())],
        "",
        "## Source Issues Kept",
        "",
        *[f"- {key}: {value}" for key, value in sorted(summary["source_issue_counts"].items())],
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hash_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for file_path in sorted(path.glob("**/*")):
        if file_path.is_file():
            digest.update(file_path.relative_to(path).as_posix().encode())
            digest.update(file_path.read_bytes())
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


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def _write_jsonl(filename: str, rows: list[dict[str, Any]]) -> None:
    with (OUT / filename).open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _write_json(filename: str, data: dict[str, Any]) -> None:
    (OUT / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(filename: str, rows: list[dict[str, Any]]) -> None:
    path = OUT / filename
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


if __name__ == "__main__":
    main()
