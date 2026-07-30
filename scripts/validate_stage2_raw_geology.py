#!/usr/bin/env python
"""Validate raw geological PDF ingestion and canonical evidence extraction."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from tbm_twin.evidence.applicability import applicability_summary, assign_evidence_to_episode
from tbm_twin.geology.document_models import GeologicalDocument, GeologicalPdfSourceAsset
from tbm_twin.geology.document_parsers import SOURCE_TIMEZONE, ParseResult, parser_for_source
from tbm_twin.geology.raw_documents import (
    collect_pdf_paths,
    register_pdf_source_asset_with_pages,
)
from tbm_twin.process.models import ExcavationEpisode
from tbm_twin.trajectory.models import SpatialFootprint
from tbm_twin.validation.stage2_diagnostics import evidence_level_applicability_summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tsp-dir", required=True, type=Path)
    parser.add_argument("--hsp-dir", required=True, type=Path)
    parser.add_argument("--sketch-dir", required=True, type=Path)
    parser.add_argument("--legacy-evidence-db", required=True, type=Path)
    parser.add_argument("--stage1-artifact-dir", required=True, type=Path)
    parser.add_argument("--dates", required=True)
    parser.add_argument(
        "--output-dir",
        default=Path("artifacts/stage2_raw_geology_validation"),
        type=Path,
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    try:
        dates = [date.strip() for date in args.dates.split(",") if date.strip()]
        episodes, footprints = _load_stage1(args.stage1_artifact_dir, dates)
        result = parse_raw_geology(
            tsp_dir=args.tsp_dir,
            hsp_dir=args.hsp_dir,
            sketch_dir=args.sketch_dir,
        )
        assignments = _assign(result["evidence"], episodes, footprints)
        _write_outputs(args.output_dir, result, assignments, args.legacy_evidence_db)
    except (OSError, ValueError) as exc:
        print(f"validate_stage2_raw_geology failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote raw geology validation to {args.output_dir}")
    return 0


def parse_raw_geology(*, tsp_dir: Path, hsp_dir: Path, sketch_dir: Path) -> dict[str, Any]:
    """Parse all raw geological PDFs."""

    pdf_paths = collect_pdf_paths(tsp_dir, hsp_dir, sketch_dir)
    assets: list[GeologicalPdfSourceAsset] = []
    page_rows: list[dict[str, Any]] = []
    documents: list[GeologicalDocument] = []
    evidence = []
    parse_rows: list[dict[str, Any]] = []
    unparsed_rows: list[dict[str, Any]] = []
    duplicate_rows: list[dict[str, Any]] = []
    out_of_scope_rows: list[dict[str, Any]] = []
    non_evidence_rows: list[dict[str, Any]] = []
    table_row_audit_rows: list[dict[str, Any]] = []
    unresolved_table_cell_rows: list[dict[str, Any]] = []
    duplicate_evidence_rows: list[dict[str, Any]] = []
    content_to_asset: dict[str, str] = {}
    total = len(pdf_paths)
    for index, path in enumerate(pdf_paths, start=1):
        if index == 1 or index % 25 == 0 or index == total:
            print(f"Parsing raw geology PDF {index}/{total}: {path.name}", file=sys.stderr)
        asset, pages = register_pdf_source_asset_with_pages(path)
        canonical_asset_id = content_to_asset.get(asset.content_id)
        if canonical_asset_id is None and asset.research_scope == "IN_SCOPE":
            content_to_asset[asset.content_id] = asset.asset_id
            canonical_asset_id = asset.asset_id
        elif canonical_asset_id is not None:
            asset = asset.model_copy(
                update={
                    "duplicate_of_asset_id": canonical_asset_id,
                    "canonical_asset_id": canonical_asset_id,
                }
            )
        else:
            canonical_asset_id = asset.asset_id
        parser = parser_for_source(asset.source_type)
        assets.append(asset)
        page_rows.extend(page.model_dump(mode="json") for page in pages)
        if asset.research_scope != "IN_SCOPE":
            out_of_scope_rows.append(_asset_boundary_row(asset, "OUT_OF_SCOPE"))
            _append_skipped_asset(
                parse_rows,
                asset,
                status="OUT_OF_SCOPE",
                reason=asset.scope_reason or "OUT_OF_SCOPE",
            )
            continue
        if asset.duplicate_of_asset_id is not None:
            duplicate_rows.append(_asset_boundary_row(asset, "DUPLICATE_ASSET_ALIAS"))
            _append_skipped_asset(
                parse_rows,
                asset,
                status="DUPLICATE_ASSET_ALIAS",
                reason="DUPLICATE_SHA256_CONTENT",
            )
            continue
        parsed = parser.parse(asset, pages)
        _append_parse_result(
            parse_rows=parse_rows,
            unparsed_rows=unparsed_rows,
            asset=asset,
            parsed=parsed,
        )
        if parsed.document is not None:
            documents.append(parsed.document)
        non_evidence_rows.extend(parsed.non_evidence_sections or [])
        table_row_audit_rows.extend(parsed.table_row_audit or [])
        unresolved_table_cell_rows.extend(parsed.unresolved_table_cells or [])
        duplicate_evidence_rows.extend(parsed.duplicate_evidence_rows or [])
        evidence.extend(parsed.evidence)
    return {
        "assets": assets,
        "page_rows": page_rows,
        "documents": documents,
        "evidence": evidence,
        "parse_rows": parse_rows,
        "unparsed_rows": unparsed_rows,
        "duplicate_rows": duplicate_rows,
        "out_of_scope_rows": out_of_scope_rows,
        "non_evidence_rows": non_evidence_rows,
        "table_row_audit_rows": table_row_audit_rows,
        "unresolved_table_cell_rows": unresolved_table_cell_rows,
        "duplicate_evidence_rows": duplicate_evidence_rows,
    }


def _asset_boundary_row(asset: GeologicalPdfSourceAsset, status: str) -> dict[str, Any]:
    return {
        "asset_id": asset.asset_id,
        "canonical_asset_id": asset.canonical_asset_id,
        "duplicate_of_asset_id": asset.duplicate_of_asset_id,
        "content_id": asset.content_id,
        "sha256": asset.sha256,
        "source_path": str(asset.source_path),
        "source_filename": asset.source_filename,
        "source_type": asset.source_type.value,
        "research_scope": asset.research_scope,
        "scope_reason": asset.scope_reason,
        "status": status,
    }


def _append_skipped_asset(
    parse_rows: list[dict[str, Any]],
    asset: GeologicalPdfSourceAsset,
    *,
    status: str,
    reason: str,
) -> None:
    parse_rows.append(
        {
            "asset_id": asset.asset_id,
            "source_path": str(asset.source_path),
            "source_type": asset.source_type.value,
            "research_scope": asset.research_scope,
            "duplicate_of_asset_id": asset.duplicate_of_asset_id,
            "text_layer_available": asset.text_layer_available,
            "document_id": None,
            "evidence_count": 0,
            "status": status,
            "unparsed_reason": reason,
        }
    )


def _append_parse_result(
    *,
    parse_rows: list[dict[str, Any]],
    unparsed_rows: list[dict[str, Any]],
    asset: GeologicalPdfSourceAsset,
    parsed: ParseResult,
) -> None:
    parse_rows.append(
        {
            "asset_id": asset.asset_id,
            "source_path": str(asset.source_path),
            "source_type": asset.source_type.value,
            "research_scope": asset.research_scope,
            "duplicate_of_asset_id": asset.duplicate_of_asset_id,
            "text_layer_available": asset.text_layer_available,
            "document_id": parsed.document.document_id if parsed.document else None,
            "evidence_count": len(parsed.evidence),
            "status": "PARSED" if parsed.document else "UNPARSED",
            "unparsed_reason": parsed.unparsed_reason,
        }
    )
    if parsed.document is None:
        unparsed_rows.append(
            {
                "asset_id": asset.asset_id,
                "source_path": str(asset.source_path),
                "source_type": asset.source_type.value,
                "unparsed_reason": parsed.unparsed_reason,
            }
        )


def _load_stage1(
    artifact_dir: Path, dates: list[str]
) -> tuple[list[ExcavationEpisode], list[SpatialFootprint]]:
    episodes: list[ExcavationEpisode] = []
    footprints: list[SpatialFootprint] = []
    for date in dates:
        date_dir = artifact_dir / date
        episodes.extend(
            ExcavationEpisode.model_validate(item)
            for item in json.loads((date_dir / "episodes.json").read_text(encoding="utf-8"))
        )
        footprints.extend(
            SpatialFootprint.model_validate(item)
            for item in json.loads(
                (date_dir / "spatial_footprints.json").read_text(encoding="utf-8")
            )
        )
    return episodes, footprints


def _assign(
    evidence: list[Any],
    episodes: list[ExcavationEpisode],
    footprints: list[SpatialFootprint],
) -> list[Any]:
    footprint_by_episode = {footprint.episode_id: footprint for footprint in footprints}
    assignments = []
    for record in evidence:
        for episode in episodes:
            assignments.append(
                assign_evidence_to_episode(
                    record,
                    episode,
                    footprint_by_episode.get(episode.episode_id),
                    evaluation_time=episode.excavation_end,
                )
            )
    return assignments


def _write_outputs(
    output_dir: Path,
    result: dict[str, Any],
    assignments: list[Any],
    legacy_db_path: Path,
) -> None:
    assets = result["assets"]
    documents = result["documents"]
    evidence = result["evidence"]
    pd.DataFrame([asset.model_dump(mode="json") for asset in assets]).to_csv(
        output_dir / "source_asset_audit.csv", index=False
    )
    pd.DataFrame(result["duplicate_rows"]).to_csv(
        output_dir / "duplicate_asset_audit.csv", index=False
    )
    pd.DataFrame(result["out_of_scope_rows"]).to_csv(
        output_dir / "out_of_scope_asset_audit.csv", index=False
    )
    pd.DataFrame(result["non_evidence_rows"]).to_csv(
        output_dir / "non_evidence_section_audit.csv", index=False
    )
    pd.DataFrame(result["table_row_audit_rows"]).to_csv(
        output_dir / "table_row_reconstruction_audit.csv", index=False
    )
    pd.DataFrame(result["unresolved_table_cell_rows"]).to_csv(
        output_dir / "unresolved_table_cell_audit.csv", index=False
    )
    pd.DataFrame(result["duplicate_evidence_rows"]).to_csv(
        output_dir / "duplicate_evidence_audit.csv", index=False
    )
    _write_jsonl(output_dir / "pdf_page_text_manifest.jsonl", result["page_rows"])
    pd.DataFrame(result["parse_rows"]).to_csv(output_dir / "document_parse_audit.csv", index=False)
    _write_jsonl(
        output_dir / "geological_documents.jsonl",
        [document.model_dump(mode="json") for document in documents],
    )
    pd.DataFrame(_document_summary(documents, evidence)).to_csv(
        output_dir / "geological_document_summary.csv", index=False
    )
    _write_jsonl(
        output_dir / "geological_evidence.jsonl",
        [record.model_dump(mode="json") for record in evidence],
    )
    pd.DataFrame(_evidence_summary(evidence)).to_csv(
        output_dir / "geological_evidence_summary.csv", index=False
    )
    pd.DataFrame(_temporal_candidates(documents, keep_irrelevant=False)).to_csv(
        output_dir / "temporal_candidate_audit.csv", index=False
    )
    local_consistency = _temporal_local_date_consistency(documents)
    pd.DataFrame(local_consistency["rows"]).to_csv(
        output_dir / "temporal_local_date_consistency_audit.csv", index=False
    )
    pd.DataFrame(_temporal_conflicts(documents)).to_csv(
        output_dir / "temporal_conflict_audit.csv", index=False
    )
    irrelevant_dates = _temporal_candidates(documents, keep_irrelevant=True, irrelevant_only=True)
    pd.DataFrame(irrelevant_dates).to_csv(
        output_dir / "irrelevant_date_candidate_audit.csv",
        index=False,
    )
    pd.DataFrame(_spatial_candidates(documents)).to_csv(
        output_dir / "spatial_candidate_audit.csv", index=False
    )
    pd.DataFrame(_forecast_face_chainage_audit(documents)).to_csv(
        output_dir / "forecast_face_chainage_audit.csv", index=False
    )
    pd.DataFrame(_chainage_anomalies(documents)).to_csv(
        output_dir / "chainage_anomaly_audit.csv", index=False
    )
    pd.DataFrame(_chainage_prefix_review(documents)).to_csv(
        output_dir / "chainage_prefix_review_audit.csv", index=False
    )
    pd.DataFrame(_inheritance_audit(documents, evidence)).to_csv(
        output_dir / "document_evidence_inheritance_audit.csv", index=False
    )
    pd.DataFrame(_structured_attribute_coverage(evidence)).to_csv(
        output_dir / "structured_attribute_coverage.csv", index=False
    )
    provenance_audit = _provenance_consistency(evidence, result["page_rows"])
    pd.DataFrame(provenance_audit["rows"]).to_csv(
        output_dir / "provenance_consistency_audit.csv", index=False
    )
    warning_audit = _warning_propagation_audit(documents, evidence)
    pd.DataFrame(warning_audit["rows"]).to_csv(
        output_dir / "warning_propagation_audit.csv", index=False
    )
    invalid_spatial = _invalid_spatial_evidence(evidence)
    pd.DataFrame(invalid_spatial).to_csv(
        output_dir / "invalid_spatial_evidence_audit.csv", index=False
    )
    pd.DataFrame(result["unparsed_rows"]).to_csv(
        output_dir / "unparsed_document_audit.csv",
        index=False,
    )
    summary = applicability_summary(assignments)
    _write_json(
        output_dir / "applicability_assignments.json",
        [item.model_dump(mode="json") for item in assignments],
    )
    matrix_columns = [
        "evidence_type",
        "evidence_epistemic_status",
        "temporal_status",
        "spatial_status",
        "result",
    ]
    app_frame = pd.DataFrame(summary)
    app_frame[matrix_columns].value_counts(dropna=False).reset_index(name="count").to_csv(
        output_dir / "applicability_result_matrix.csv", index=False
    )
    pd.DataFrame(
        evidence_level_applicability_summary(
            assignments=assignments,
            evidence_ids=[record.evidence_id for record in evidence],
            evidence_family="GEOLOGICAL",
        )
    ).to_csv(output_dir / "evidence_level_applicability_summary.csv", index=False)
    temporal_status = _temporal_status(documents, assignments)
    temporal_status.update(local_consistency["summary"])
    _write_json(output_dir / "temporal_validation_status.json", temporal_status)
    legacy = _legacy_comparison(legacy_db_path, assets, documents, evidence)
    validation_summary = _validation_summary(
        assets=assets,
        documents=documents,
        evidence=evidence,
        assignments=assignments,
        duplicate_rows=result["duplicate_rows"],
        out_of_scope_rows=result["out_of_scope_rows"],
        non_evidence_rows=result["non_evidence_rows"],
        table_row_audit_rows=result["table_row_audit_rows"],
        unresolved_table_cell_rows=result["unresolved_table_cell_rows"],
        duplicate_evidence_rows=result["duplicate_evidence_rows"],
        local_consistency=local_consistency["summary"],
        provenance_audit=provenance_audit["summary"],
        warning_audit=warning_audit["summary"],
        invalid_spatial=invalid_spatial,
    )
    _write_json(output_dir / "raw_geology_validation_summary.json", validation_summary)
    _write_json(output_dir / "legacy_database_comparison.json", legacy)
    pd.DataFrame(legacy["document_rows"]).to_csv(
        output_dir / "legacy_new_document_comparison.csv", index=False
    )
    pd.DataFrame(legacy["evidence_rows"]).to_csv(
        output_dir / "legacy_new_evidence_comparison.csv", index=False
    )
    _write_report(
        output_dir / "stage2_raw_geology_validation_report.md",
        assets,
        documents,
        evidence,
        temporal_status,
        legacy,
        validation_summary,
    )


def _document_summary(
    documents: list[GeologicalDocument],
    evidence: list[Any],
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for record in evidence:
        counts[record.document_id or ""] = counts.get(record.document_id or "", 0) + 1
    return [
        {
            "document_id": doc.document_id,
            "source_asset_id": doc.source_asset_id,
            "source_type": doc.source_type.value,
            "report_id": doc.report_id,
            "evidence_count": counts.get(doc.document_id, 0),
            "has_observed_time": doc.observed_time_extent is not None,
            "has_document_time": doc.document_time_extent is not None,
            "has_issued_time": doc.issued_time_extent is not None,
            "has_submitted_time": doc.submitted_time_extent is not None,
            "has_available_time": doc.available_time_extent is not None,
            "has_spatial_scope": doc.document_spatial_scope is not None,
            "face_chainage": doc.face_chainage,
            "face_chainage_basis": doc.face_chainage_basis,
            "face_chainage_source_page": doc.face_chainage_source_page,
            "face_chainage_validation_status": doc.face_chainage_validation_status,
            "document_warnings": ";".join(doc.document_warnings),
        }
        for doc in documents
    ]


def _evidence_summary(evidence: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": record.evidence_id,
            "document_id": record.document_id,
            "source_asset_id": record.source_asset_id,
            "source_type": record.geological_source_type.value,
            "source_level": record.source_level,
            "epistemic_status": record.epistemic_status.value,
            "start_chainage": record.spatial_scope.start_chainage if record.spatial_scope else None,
            "end_chainage": record.spatial_scope.end_chainage if record.spatial_scope else None,
            "source_page_refs": ";".join(str(page) for page in record.source_page_refs),
            "has_available_time_extent": record.available_time_extent is not None,
            "quality_grade": record.quality_grade.value,
            "quality_flags": ";".join(record.quality_flags),
            "section_role": record.structured_attributes.get("section_role"),
            "extraction_rule": record.structured_attributes.get("extraction_rule"),
            "lithology": record.structured_attributes.get("lithology"),
            "water_state": record.structured_attributes.get("water_state"),
            "source_risk_text": record.structured_attributes.get("source_risk_text"),
        }
        for record in evidence
    ]


def _temporal_candidates(
    documents: list[GeologicalDocument],
    *,
    keep_irrelevant: bool,
    irrelevant_only: bool = False,
) -> list[dict[str, Any]]:
    rows = []
    for doc in documents:
        for candidate in doc.temporal_candidates:
            is_irrelevant = candidate.semantic_role.value == "IRRELEVANT"
            if irrelevant_only and not is_irrelevant:
                continue
            if not keep_irrelevant and is_irrelevant:
                continue
            rows.append({"document_id": doc.document_id, **candidate.model_dump(mode="json")})
    return rows


def _temporal_conflicts(documents: list[GeologicalDocument]) -> list[dict[str, Any]]:
    rows = []
    for doc in documents:
        by_role: dict[str, set[str]] = {}
        for candidate in doc.temporal_candidates:
            if candidate.parsed_value is None or candidate.semantic_role.value == "IRRELEVANT":
                continue
            by_role.setdefault(candidate.semantic_role.value, set()).add(
                candidate.parsed_value.isoformat()
            )
        for role, values in by_role.items():
            if len(values) > 1:
                rows.append(
                    {
                        "document_id": doc.document_id,
                        "role": role,
                        "values": ";".join(sorted(values)),
                    }
                )
    return rows


def _spatial_candidates(documents: list[GeologicalDocument]) -> list[dict[str, Any]]:
    return [
        {"document_id": doc.document_id, **candidate.model_dump(mode="json")}
        for doc in documents
        for candidate in doc.spatial_candidates
    ]


def _chainage_anomalies(documents: list[GeologicalDocument]) -> list[dict[str, Any]]:
    rows = []
    for doc in documents:
        for candidate in doc.spatial_candidates:
            if candidate.validation_flags:
                rows.append({"document_id": doc.document_id, **candidate.model_dump(mode="json")})
    return rows


def _chainage_prefix_review(documents: list[GeologicalDocument]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for doc in documents:
        for candidate in doc.spatial_candidates:
            text = candidate.raw_expression
            if not isinstance(text, str) or "+" not in text:
                continue
            if (
                _crosses_km_boundary(text)
                or "CHAINAGE_PREFIX_MISMATCH" in candidate.validation_flags
            ):
                rows.append(
                    {
                        "document_id": doc.document_id,
                        "source_type": doc.source_type.value,
                        "candidate_id": candidate.candidate_id,
                        "raw_expression": text,
                        "start_chainage": candidate.start_chainage,
                        "end_chainage": candidate.end_chainage,
                        "validation_flags": ";".join(candidate.validation_flags),
                        "classification": _prefix_review_classification(candidate),
                        "source_context": candidate.source_context,
                    }
                )
    return rows


def _crosses_km_boundary(text: str) -> bool:
    matches = re.findall(r"(?:DyK|DK|K)\s*(\d+)\s*\+", text, flags=re.I)
    return len(matches) >= 2 and matches[0] != matches[1]


def _prefix_review_classification(candidate: Any) -> str:
    flags = set(candidate.validation_flags)
    if "CHAINAGE_PREFIX_MISMATCH" not in flags and _crosses_km_boundary(candidate.raw_expression):
        return "VALID_KM_BOUNDARY_CROSSING"
    if "CHAINAGE_DIRECTION_CONFLICT" in flags:
        return "SOURCE_TEXT_DIRECTION_ERROR"
    if "CHAINAGE_PREFIX_MISMATCH" in flags:
        return "TRUE_PREFIX_CONFLICT"
    return "UNDETERMINED"


def _temporal_local_date_consistency(documents: list[GeologicalDocument]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    zone = ZoneInfo(SOURCE_TIMEZONE)
    candidate_by_id = {
        candidate.candidate_id: candidate
        for doc in documents
        for candidate in doc.temporal_candidates
    }
    for doc in documents:
        for role, extent in [
            ("observed", doc.observed_time_extent),
            ("document", doc.document_time_extent),
            ("issued", doc.issued_time_extent),
            ("submitted", doc.submitted_time_extent),
            ("available", doc.available_time_extent),
        ]:
            if extent is None:
                continue
            extent_local_date = extent.earliest_possible_time.astimezone(zone).date()
            for candidate_id in extent.candidate_ids:
                candidate = candidate_by_id.get(candidate_id)
                candidate_local_date = candidate.source_local_date if candidate else None
                rows.append(
                    {
                        "document_id": doc.document_id,
                        "role": role,
                        "candidate_id": candidate_id,
                        "candidate_raw": candidate.raw_expression if candidate else None,
                        "candidate_source_local_date": str(candidate_local_date)
                        if candidate_local_date
                        else None,
                        "extent_start_local_date": str(extent_local_date),
                        "consistent": candidate_local_date == extent_local_date,
                    }
                )
    consistent = sum(row["consistent"] for row in rows)
    total = len(rows)
    return {
        "rows": rows,
        "summary": {
            "temporal_local_date_consistency_count": consistent,
            "temporal_local_date_consistency_total": total,
            "temporal_local_date_consistency_ratio": consistent / total if total else 1.0,
        },
    }


def _forecast_face_chainage_audit(documents: list[GeologicalDocument]) -> list[dict[str, Any]]:
    return [
        {
            "document_id": doc.document_id,
            "source_type": doc.source_type.value,
            "report_id": doc.report_id,
            "face_chainage": doc.face_chainage,
            "face_chainage_basis": doc.face_chainage_basis,
            "face_chainage_source_page": doc.face_chainage_source_page,
            "face_chainage_validation_status": doc.face_chainage_validation_status,
            "scope_start": doc.document_spatial_scope.start_chainage
            if doc.document_spatial_scope
            else None,
            "scope_end": doc.document_spatial_scope.end_chainage
            if doc.document_spatial_scope
            else None,
        }
        for doc in documents
        if doc.source_type.value in {"TSP_REPORT", "SONIC_FORECAST"}
    ]


def _structured_attribute_coverage(evidence: list[Any]) -> list[dict[str, Any]]:
    keys = [
        "lithology",
        "weathering",
        "surrounding_rock_grade",
        "joint_development",
        "rock_mass_state",
        "stability",
        "water_state",
        "water_type",
        "block_fall_or_collapse",
        "deformation",
        "anomaly_level",
        "source_risk_text",
        "forecast_qualifiers",
    ]
    rows: list[dict[str, Any]] = []
    for key in keys:
        known = sum(
            record.structured_attributes.get(key) not in {None, "UNKNOWN"} for record in evidence
        )
        rows.append(
            {
                "attribute": key,
                "known_count": known,
                "unknown_count": len(evidence) - known,
                "coverage_ratio": known / len(evidence) if evidence else 0.0,
            }
        )
    return rows


def _provenance_consistency(evidence: list[Any], page_rows: list[dict[str, Any]]) -> dict[str, Any]:
    page_text = {
        (row["asset_id"], row["page_number"]): _normalize_for_audit(row["page_text"])
        for row in page_rows
    }
    rows: list[dict[str, Any]] = []
    for record in evidence:
        raw = _normalize_for_audit(record.raw_text)
        source_text_match = record.source_text_refs == [record.raw_text]
        page_match = any(
            raw and raw in page_text.get((record.source_asset_id, page), "")
            for page in record.source_page_refs
        )
        rows.append(
            {
                "evidence_id": record.evidence_id,
                "document_id": record.document_id,
                "source_asset_id": record.source_asset_id,
                "source_page_refs": ";".join(str(page) for page in record.source_page_refs),
                "source_text_refs_match_raw_text": source_text_match,
                "raw_text_found_on_referenced_page": page_match,
                "consistent": source_text_match and page_match,
            }
        )
    consistent = sum(row["consistent"] for row in rows)
    total = len(rows)
    return {
        "rows": rows,
        "summary": {
            "provenance_consistency_count": consistent,
            "provenance_consistency_total": total,
            "provenance_consistency_ratio": consistent / total if total else 1.0,
        },
    }


def _normalize_for_audit(text: str | None) -> str:
    return " ".join((text or "").split())


def _warning_propagation_audit(
    documents: list[GeologicalDocument],
    evidence: list[Any],
) -> dict[str, Any]:
    doc_flags = {doc.document_id: set(doc.document_warnings) for doc in documents}
    rows: list[dict[str, Any]] = []
    before_pollution = 0
    after_pollution = 0
    for record in evidence:
        document_flags = doc_flags.get(record.document_id, set())
        own_flags = set(record.quality_flags)
        doc_chainage_flags = {flag for flag in document_flags if flag.startswith("CHAINAGE_")}
        own_chainage_flags = {flag for flag in own_flags if flag.startswith("CHAINAGE_")}
        would_have_inherited = bool(doc_chainage_flags and not own_chainage_flags)
        still_polluted = bool(would_have_inherited and doc_chainage_flags & own_flags)
        before_pollution += int(would_have_inherited)
        after_pollution += int(still_polluted)
        if would_have_inherited or own_chainage_flags:
            rows.append(
                {
                    "evidence_id": record.evidence_id,
                    "document_id": record.document_id,
                    "document_chainage_flags": ";".join(sorted(doc_chainage_flags)),
                    "evidence_quality_flags": ";".join(sorted(own_flags)),
                    "would_have_been_polluted_by_document_warning": would_have_inherited,
                    "still_polluted_after_fix": still_polluted,
                }
            )
    return {
        "rows": rows,
        "summary": {
            "legacy_style_warning_pollution_candidate_count": before_pollution,
            "post_fix_warning_pollution_count": after_pollution,
        },
    }


def _invalid_spatial_evidence(evidence: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for record in evidence:
        interval = record.chainage_interval
        if interval is None or interval.spatial_scope_usable:
            continue
        rows.append(
            {
                "evidence_id": record.evidence_id,
                "document_id": record.document_id,
                "source_type": record.geological_source_type.value,
                "source_level": record.source_level,
                "validation_flags": ";".join(interval.validation_flags),
                "start_chainage": interval.normalized_start_chainage,
                "end_chainage": interval.normalized_end_chainage,
            }
        )
    return rows


def _inheritance_audit(
    documents: list[GeologicalDocument],
    evidence: list[Any],
) -> list[dict[str, Any]]:
    by_doc: dict[str, list[Any]] = {}
    for record in evidence:
        by_doc.setdefault(record.document_id or "", []).append(record)
    rows = []
    for doc in documents:
        records = by_doc.get(doc.document_id, [])
        rows.append(
            {
                "document_id": doc.document_id,
                "report_id": doc.report_id,
                "source_type": doc.source_type.value,
                "evidence_count": len(records),
                "evidence_ids": ";".join(record.evidence_id for record in records),
                "shared_observed_time": doc.observed_time_extent.model_dump_json()
                if doc.observed_time_extent
                else None,
                "shared_issued_time": doc.issued_time_extent.model_dump_json()
                if doc.issued_time_extent
                else None,
                "shared_submitted_time": doc.submitted_time_extent.model_dump_json()
                if doc.submitted_time_extent
                else None,
                "shared_available_time_extent": doc.available_time_extent.model_dump_json()
                if doc.available_time_extent
                else None,
                "inheritance_status": "INHERITED" if records else "NO_EVIDENCE",
            }
        )
    return rows


def _temporal_status(documents: list[GeologicalDocument], assignments: list[Any]) -> dict[str, Any]:
    with_available_time = sum(doc.available_time_extent is not None for doc in documents)
    without_available_time = sum(doc.available_time_extent is None for doc in documents)
    future_leakage = sum(
        item.result.value != "NOT_APPLICABLE"
        and item.dominant_reason_code == "EVIDENCE_NOT_YET_AVAILABLE"
        for item in assignments
    )
    return {
        "document_count": len(documents),
        "documents_with_available_time_extent": with_available_time,
        "documents_without_available_time_extent": without_available_time,
        "detected_future_leakage_count": future_leakage,
        "same_day_temporal_uncertainty_count": sum(
            item.temporal_status.value == "UNKNOWN_WITHIN_PRECISION" for item in assignments
        ),
    }


def _legacy_comparison(
    legacy_db_path: Path,
    assets: list[GeologicalPdfSourceAsset],
    documents: list[GeologicalDocument],
    evidence: list[Any],
) -> dict[str, Any]:
    legacy = pd.read_csv(legacy_db_path) if legacy_db_path.exists() else pd.DataFrame()
    return {
        "legacy_database_path": str(legacy_db_path),
        "legacy_database_exists": legacy_db_path.exists(),
        "legacy_evidence_count": len(legacy),
        "new_pdf_count": len(assets),
        "new_document_count": len(documents),
        "new_evidence_count": len(evidence),
        "in_scope_asset_count": sum(asset.research_scope == "IN_SCOPE" for asset in assets),
        "out_of_scope_asset_count": sum(asset.research_scope != "IN_SCOPE" for asset in assets),
        "duplicate_asset_count": sum(asset.duplicate_of_asset_id is not None for asset in assets),
        "legacy_source_type_distribution": legacy["source_type"]
        .value_counts(dropna=False)
        .to_dict()
        if "source_type" in legacy
        else {},
        "new_source_type_distribution": pd.Series([asset.source_type.value for asset in assets])
        .value_counts()
        .to_dict(),
        "legacy_is_not_gold": True,
        "document_rows": [
            {
                "report_id": doc.report_id,
                "source_type": doc.source_type.value,
                "covered_by_new_parser": True,
            }
            for doc in documents
        ],
        "evidence_rows": [
            {
                "new_evidence_id": record.evidence_id,
                "document_id": record.document_id,
                "source_type": record.geological_source_type.value,
                "source_level": record.source_level,
            }
            for record in evidence
        ],
    }


def _validation_summary(
    *,
    assets: list[GeologicalPdfSourceAsset],
    documents: list[GeologicalDocument],
    evidence: list[Any],
    assignments: list[Any],
    duplicate_rows: list[dict[str, Any]],
    out_of_scope_rows: list[dict[str, Any]],
    non_evidence_rows: list[dict[str, Any]],
    table_row_audit_rows: list[dict[str, Any]],
    unresolved_table_cell_rows: list[dict[str, Any]],
    duplicate_evidence_rows: list[dict[str, Any]],
    local_consistency: dict[str, Any],
    provenance_audit: dict[str, Any],
    warning_audit: dict[str, Any],
    invalid_spatial: list[dict[str, Any]],
) -> dict[str, Any]:
    asset_source_counts = (
        pd.Series([asset.source_type.value for asset in assets]).value_counts().to_dict()
    )
    document_source_counts = (
        pd.Series([doc.source_type.value for doc in documents]).value_counts().to_dict()
    )
    evidence_source_counts = (
        pd.Series([record.geological_source_type.value for record in evidence])
        .value_counts()
        .to_dict()
    )
    evidence_type_counts = (
        pd.Series([record.evidence_type.value for record in evidence]).value_counts().to_dict()
    )
    epistemic_counts = (
        pd.Series([record.epistemic_status.value for record in evidence]).value_counts().to_dict()
    )
    assignment_result_counts = (
        pd.Series([item.result.value for item in assignments]).value_counts().to_dict()
    )
    temporal_counts = (
        pd.Series([item.temporal_status.value for item in assignments]).value_counts().to_dict()
    )
    spatial_counts = (
        pd.Series([item.spatial_status.value for item in assignments]).value_counts().to_dict()
    )
    cover_metadata_excluded = sum(
        1
        for doc in documents
        for candidate in doc.spatial_candidates
        if candidate.role in {"document_forecast_scope", "instrument_or_calibration_range"}
    )
    forecast_records = [
        record for record in evidence if record.evidence_type.value == "GEOLOGICAL_FORECAST"
    ]
    forecast_range_sources = (
        pd.Series([_forecast_range_source(record) for record in forecast_records])
        .value_counts()
        .to_dict()
    )
    no_range_forecast = sum(record.spatial_scope is None for record in forecast_records)
    face_status_counts = (
        pd.Series(
            [
                doc.face_chainage_validation_status or "UNKNOWN"
                for doc in documents
                if doc.source_type.value in {"TSP_REPORT", "SONIC_FORECAST"}
            ]
        )
        .value_counts()
        .to_dict()
    )
    return {
        "raw_asset_count": len(assets),
        "in_scope_asset_count": sum(asset.research_scope == "IN_SCOPE" for asset in assets),
        "duplicate_asset_count": len(duplicate_rows),
        "out_of_scope_asset_count": len(out_of_scope_rows),
        "canonical_document_count": len(documents),
        "canonical_evidence_count": len(evidence),
        "asset_source_type_distribution": asset_source_counts,
        "document_source_type_distribution": document_source_counts,
        "evidence_source_type_distribution": evidence_source_counts,
        "evidence_type_distribution": evidence_type_counts,
        "evidence_epistemic_distribution": epistemic_counts,
        "cover_metadata_excluded_count": cover_metadata_excluded,
        "non_evidence_section_count": len(non_evidence_rows),
        "non_evidence_reason_distribution": pd.Series(
            [row.get("reason") for row in non_evidence_rows]
        )
        .value_counts()
        .to_dict(),
        "forecast_evidence_count": len(forecast_records),
        "forecast_range_source_distribution": forecast_range_sources,
        "forecast_without_explicit_or_legal_inherited_range_count": no_range_forecast,
        "table_row_reconstruction_count": sum(
            row.get("status") == "EVIDENCE_CREATED" for row in table_row_audit_rows
        ),
        "unresolved_table_cell_count": len(unresolved_table_cell_rows),
        "exact_duplicate_evidence_count": len(duplicate_evidence_rows),
        "structured_attribute_coverage": _structured_attribute_coverage(evidence),
        "temporal_local_date_consistency": local_consistency,
        "provenance_consistency": provenance_audit,
        "forecast_face_chainage_validation": face_status_counts,
        "warning_propagation": warning_audit,
        "invalid_spatial_evidence_count": len(invalid_spatial),
        "invalid_spatial_reason_distribution": pd.Series(
            [row["validation_flags"] for row in invalid_spatial]
        )
        .value_counts()
        .to_dict(),
        "applicability_result_distribution": assignment_result_counts,
        "applicability_temporal_status_distribution": temporal_counts,
        "applicability_spatial_status_distribution": spatial_counts,
        "future_leakage_check": {
            "non_not_applicable_future_leakage_count": sum(
                item.result.value != "NOT_APPLICABLE"
                and item.dominant_reason_code == "EVIDENCE_NOT_YET_AVAILABLE"
                for item in assignments
            )
        },
    }


def _forecast_range_source(record: Any) -> str:
    rule = str(record.structured_attributes.get("extraction_rule"))
    basis = record.spatial_scope.basis if record.spatial_scope else "UNKNOWN"
    if rule == "forecast_table_row_reconstruction":
        return "TABLE_ROW_RANGE"
    if basis == "document_forecast_range":
        return "LEGAL_DOCUMENT_SCOPE_INHERITANCE"
    if record.spatial_scope is None:
        return "UNRESOLVED"
    return "SELF_RANGE"


def _write_report(
    path: Path,
    assets: list[GeologicalPdfSourceAsset],
    documents: list[GeologicalDocument],
    evidence: list[Any],
    temporal_status: dict[str, Any],
    legacy: dict[str, Any],
    validation_summary: dict[str, Any],
) -> None:
    lines = [
        "# Stage 2 Raw Geology Validation",
        "",
        (
            "Raw PDFs are the formal geological input. "
            "The legacy database is used only for comparison."
        ),
        "",
        f"- raw PDF count: {len(assets)}",
        f"- in-scope asset count: {validation_summary['in_scope_asset_count']}",
        f"- duplicate asset count: {validation_summary['duplicate_asset_count']}",
        f"- out-of-scope asset count: {validation_summary['out_of_scope_asset_count']}",
        f"- parsed document count: {len(documents)}",
        f"- canonical geological evidence count: {len(evidence)}",
        f"- source type documents: {validation_summary['document_source_type_distribution']}",
        f"- source type evidence: {validation_summary['evidence_source_type_distribution']}",
        (
            "- evidence epistemic distribution: "
            f"{validation_summary['evidence_epistemic_distribution']}"
        ),
        f"- cover metadata excluded count: {validation_summary['cover_metadata_excluded_count']}",
        f"- non evidence section count: {validation_summary['non_evidence_section_count']}",
        (
            "- non evidence reason distribution: "
            f"{validation_summary['non_evidence_reason_distribution']}"
        ),
        (
            "- forecast range source distribution: "
            f"{validation_summary['forecast_range_source_distribution']}"
        ),
        (
            "- forecast without range count: "
            f"{validation_summary['forecast_without_explicit_or_legal_inherited_range_count']}"
        ),
        (
            "- table row reconstruction count: "
            f"{validation_summary['table_row_reconstruction_count']}"
        ),
        (f"- unresolved table cell count: {validation_summary['unresolved_table_cell_count']}"),
        f"- exact duplicate evidence count: {validation_summary['exact_duplicate_evidence_count']}",
        (
            "- temporal local date consistency ratio: "
            f"{validation_summary['temporal_local_date_consistency']['temporal_local_date_consistency_ratio']:.6f}"
        ),
        (
            "- forecast face_chainage validation: "
            f"{validation_summary['forecast_face_chainage_validation']}"
        ),
        (f"- provenance consistency: {validation_summary['provenance_consistency']}"),
        (f"- warning propagation before/after: {validation_summary['warning_propagation']}"),
        (
            "- invalid spatial evidence count: "
            f"{validation_summary['invalid_spatial_evidence_count']}"
        ),
        (
            "- applicability result distribution: "
            f"{validation_summary['applicability_result_distribution']}"
        ),
        (
            "- applicability temporal distribution: "
            f"{validation_summary['applicability_temporal_status_distribution']}"
        ),
        (f"- real future leakage check: {validation_summary['future_leakage_check']}"),
        (
            "- documents with available_time_extent: "
            f"{temporal_status['documents_with_available_time_extent']}"
        ),
        (
            "- same-day temporal uncertainty assignments: "
            f"{temporal_status['same_day_temporal_uncertainty_count']}"
        ),
        f"- legacy evidence count: {legacy['legacy_evidence_count']}",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
