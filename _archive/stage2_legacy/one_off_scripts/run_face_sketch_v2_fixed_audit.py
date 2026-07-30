"""Run the fixed FaceSketch parser audit without touching HSP/TSP."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from tbm_twin.geology.table_parser_v2 import parse_pdf_v2
from tbm_twin.geology.table_parser_v2.text_utils import parse_all_chainage_intervals

REPO = Path(__file__).resolve().parents[1]
ASSET_AUDIT = REPO / "artifacts/stage2_raw_geology_validation/source_asset_audit.csv"
OUT = REPO / "artifacts/stage2_table_parser_v2_shadow"

STATUS_SUCCESS = "SUCCESS"
STATUS_EXCLUDED_OUT_OF_SCOPE = "EXCLUDED_OUT_OF_SCOPE"
STATUS_EXCLUDED_DUPLICATE = "EXCLUDED_DUPLICATE"
STATUS_PARSE_ERROR = "PARSE_ERROR"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    assets = [row for row in _read_assets() if row["source_type"] == "FACE_SKETCH"]
    evidence_rows: list[dict[str, Any]] = []
    scope_rows: list[dict[str, Any]] = []
    chainage_rows: list[dict[str, Any]] = []
    clause_rows: list[dict[str, Any]] = []
    checkbox_rows: list[dict[str, Any]] = []
    invalid_interval_rows: list[dict[str, Any]] = []
    outcome_rows: list[dict[str, Any]] = []

    for asset in assets:
        status = STATUS_SUCCESS
        error_code = ""
        if asset["research_scope"] == "OUT_OF_SCOPE":
            status = STATUS_EXCLUDED_OUT_OF_SCOPE
        elif asset["duplicate_of_asset_id"]:
            status = STATUS_EXCLUDED_DUPLICATE
        if status != STATUS_SUCCESS:
            outcome_rows.append({**_asset_min(asset), "parse_status": status, "error_code": ""})
            continue
        try:
            result = parse_pdf_v2(Path(asset["source_path"]))
        except Exception as exc:  # shadow audit records parser failures explicitly
            status = STATUS_PARSE_ERROR
            error_code = type(exc).__name__
            outcome_rows.append(
                {**_asset_min(asset), "parse_status": status, "error_code": error_code}
            )
            continue
        outcome_rows.append({**_asset_min(asset), "parse_status": status, "error_code": ""})
        point = _face_point(result.primary_evidence)
        forecast_count = sum(
            item.evidence_type == "FORECAST_SEGMENT" for item in result.primary_evidence
        )
        current_count = sum(
            item.evidence_type == "FACE_OBSERVATION"
            and item.spatial_scope.kind == "INTERVAL"
            and item.attributes.get("observation_scope") == "CURRENT_EXCAVATED_INTERVAL"
            for item in result.primary_evidence
        )
        for index, evidence in enumerate(result.primary_evidence, start=1):
            evidence_uid = f"{asset['asset_id']}_e{index:04d}"
            evidence_rows.append(
                {
                    "evidence_uid": evidence_uid,
                    **_asset_min(asset),
                    **_jsonable(evidence),
                }
            )
            scope_rows.append(
                _scope_row(
                    asset=asset,
                    evidence_uid=evidence_uid,
                    evidence=evidence,
                    document_has_forecast=forecast_count > 0,
                    document_has_current_interval=current_count > 0,
                )
            )
        chainage_rows.append(_chainage_row(asset, result, point))
        for audit in result.audit_rows:
            row = {**_asset_min(asset), **audit}
            if audit.get("audit_type") == "CLAUSE_ROLE":
                clause_rows.append(row)
            elif audit.get("audit_type") == "CHECKBOX_POSITION":
                checkbox_rows.append(row)
            elif audit.get("audit_type") == "INVALID_SOURCE_INTERVAL":
                invalid_interval_rows.append(row)

    _write_jsonl("face_sketch_evidence_v2_fixed.jsonl", evidence_rows)
    _write_csv("face_sketch_scope_audit_fixed.csv", scope_rows)
    _write_csv("face_chainage_audit.csv", chainage_rows)
    _write_csv("face_clause_role_audit.csv", clause_rows)
    _write_csv("face_checkbox_position_audit.csv", checkbox_rows)
    _write_csv("face_invalid_interval_audit.csv", invalid_interval_rows)
    _write_csv("face_sketch_parse_outcomes_fixed.csv", outcome_rows)
    metrics = _metrics(
        outcome_rows=outcome_rows,
        scope_rows=scope_rows,
        chainage_rows=chainage_rows,
        clause_rows=clause_rows,
        checkbox_rows=checkbox_rows,
        invalid_interval_rows=invalid_interval_rows,
    )
    (OUT / "face_sketch_fixed_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def _read_assets() -> list[dict[str, str]]:
    with ASSET_AUDIT.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _asset_min(asset: dict[str, str]) -> dict[str, Any]:
    return {
        "asset_id": asset["asset_id"],
        "filename": asset["source_filename"],
        "source_type": asset["source_type"],
        "source_path": asset["source_path"],
        "research_scope": asset["research_scope"],
        "duplicate_of_asset_id": asset["duplicate_of_asset_id"],
        "canonical_asset_id": asset["canonical_asset_id"],
    }


def _face_point(evidence: list[Any]) -> Any | None:
    for item in evidence:
        if (
            item.evidence_type == "FACE_OBSERVATION"
            and item.spatial_scope.kind == "POINT"
            and item.attributes.get("observation_scope") == "FACE_POINT"
        ):
            return item
    return None


def _scope_row(
    *,
    asset: dict[str, str],
    evidence_uid: str,
    evidence: Any,
    document_has_forecast: bool,
    document_has_current_interval: bool,
) -> dict[str, Any]:
    attrs = evidence.attributes
    is_point = attrs.get("observation_scope") == "FACE_POINT"
    compact_assembled = "".join(str(evidence.assembled_text).split())
    return {
        **_asset_min(asset),
        "evidence_uid": evidence_uid,
        "evidence_type": evidence.evidence_type,
        "epistemic_status": evidence.epistemic_status,
        "spatial_kind": evidence.spatial_scope.kind,
        "start_chainage": evidence.spatial_scope.start_chainage,
        "end_chainage": evidence.spatial_scope.end_chainage,
        "raw_expression": evidence.spatial_scope.raw_expression,
        "observation_scope": attrs.get("observation_scope"),
        "lithology": attrs.get("lithology"),
        "weathering": attrs.get("weathering"),
        "joint_development": attrs.get("joint_development"),
        "rock_mass_state": attrs.get("rock_mass_state"),
        "water_type": attrs.get("water_type"),
        "form_water_status": attrs.get("form_water_status"),
        "form_water_other_raw": attrs.get("form_water_other_raw"),
        "local_unlocated_observations": json.dumps(
            attrs.get("local_unlocated_observations") or [],
            ensure_ascii=False,
        ),
        "recommendations": json.dumps(attrs.get("recommendations") or [], ensure_ascii=False),
        "prediction_attribute_on_point": bool(
            is_point
            and document_has_forecast
            and any(token in compact_assembled for token in ["推测", "前方预计", "推测进入"])
        ),
        "current_interval_attribute_on_point": bool(
            is_point
            and document_has_current_interval
            and "当前开挖段落" in compact_assembled
            and bool(parse_all_chainage_intervals(evidence.assembled_text))
        ),
        "assembled_text": evidence.assembled_text,
    }


def _chainage_row(asset: dict[str, str], result: Any, point: Any | None) -> dict[str, Any]:
    audit = next(
        (row for row in result.audit_rows if row.get("audit_type") == "FACE_CHAINAGE"),
        {},
    )
    header_value = audit.get("value")
    filename_value = audit.get("filename_value")
    output_value = point.spatial_scope.start_chainage if point is not None else None
    conflict = (
        header_value is not None
        and filename_value is not None
        and abs(float(header_value) - float(filename_value)) > 1.0
    )
    mismatch = (
        header_value is not None
        and output_value is not None
        and abs(float(header_value) - float(output_value)) > 0.001
    )
    return {
        **_asset_min(asset),
        "header_face_chainage": header_value,
        "filename_chainage": filename_value,
        "output_face_chainage": output_value,
        "header_output_mismatch": mismatch,
        "source_chainage_conflict": conflict,
        "status": "SOURCE_CHAINAGE_CONFLICT" if conflict else audit.get("status", ""),
        "source_text": audit.get("raw_text", ""),
        "document_warnings": ";".join(result.document.parse_warnings),
    }


def _metrics(
    *,
    outcome_rows: list[dict[str, Any]],
    scope_rows: list[dict[str, Any]],
    chainage_rows: list[dict[str, Any]],
    clause_rows: list[dict[str, Any]],
    checkbox_rows: list[dict[str, Any]],
    invalid_interval_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    outcomes = Counter(row["parse_status"] for row in outcome_rows)
    scopes = Counter(row["observation_scope"] for row in scope_rows)
    prefix_fixed = sum(
        row.get("prefix_checkmark") is True
        and row.get("selection_rule")
        in {
            "prefix_checkmark_right_neighbor",
            "ignored_prefix_mark_because_suffix_cell_present",
        }
        for row in checkbox_rows
    )
    return {
        "outcomes": dict(outcomes),
        "face_point_count": scopes["FACE_POINT"],
        "forecast_segment_count": scopes["FORECAST_SEGMENT"],
        "current_excavated_interval_count": scopes["CURRENT_EXCAVATED_INTERVAL"],
        "local_unlocated_clause_count": sum(
            row.get("clause_role") == "LOCAL_UNLOCATED" for row in clause_rows
        ),
        "invalid_interval_count": len(invalid_interval_rows),
        "face_point_header_mismatch_count": sum(
            row["header_output_mismatch"] in {True, "True"} for row in chainage_rows
        ),
        "source_chainage_conflict_count": sum(
            row["source_chainage_conflict"] in {True, "True"} for row in chainage_rows
        ),
        "prediction_attribute_on_point_count": sum(
            row["prediction_attribute_on_point"] in {True, "True"} for row in scope_rows
        ),
        "current_interval_attribute_on_point_count": sum(
            row["current_interval_attribute_on_point"] in {True, "True"} for row in scope_rows
        ),
        "checkbox_boundary_fix_count": prefix_fixed,
        "joint_roughness_prefix_checkbox_count": sum(
            row.get("label") == "粗糙度" and row.get("prefix_checkmark") is True
            for row in checkbox_rows
        ),
    }


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
