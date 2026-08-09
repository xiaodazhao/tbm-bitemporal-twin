"""Build Stage 2D Applicability V2.1 from trusted Stage 2E PLC scopes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from scripts import run_stage2d_applicability_v2 as base  # noqa: E402
from tbm_twin.operational_freeze.builder import _write_source_snapshot  # noqa: E402

FREEZE = REPO / "artifacts/stage2_geology_v2_freeze_candidate"
PLC_FREEZE = REPO / "artifacts/stage2_plc_operational_freeze_v2"
OLD_OUT = REPO / "artifacts/stage2d_applicability_v2"
OUT = REPO / "artifacts/stage2d_applicability_v2_1"

METHOD_VERSION = "stage2d_applicability_v2_1_trusted_plc_scope"


def main() -> None:
    args = _parse_args()
    generated_at = _parse_generated_at(args.generated_at)
    global FREEZE, PLC_FREEZE, OUT
    FREEZE = _resolve_repo_path(args.geology_freeze_dir)
    PLC_FREEZE = _resolve_repo_path(args.plc_freeze_dir)
    OUT = _resolve_repo_path(args.output_dir)
    base.FREEZE = FREEZE
    OUT.mkdir(parents=True, exist_ok=True)
    freeze = base._load_freeze()
    base._assert_freeze_baseline(freeze)
    plc_days = _load_trusted_plc_daily_scopes()
    source_freeze_manifest_hash = base._sha256(FREEZE / "freeze_manifest.json")
    snapshot_sha, source_tree_hash = _write_source_snapshot(
        repo=REPO,
        output_dir=OUT,
        archive_name="applicability_v2_1_source_snapshot.tar.gz",
        hashes_name="applicability_v2_1_source_hashes.sha256",
        include_paths=[
            "scripts/run_stage2d_applicability_v2.py",
            "scripts/run_stage2d_applicability_v2_1.py",
            "configs/evidence_applicability.yaml",
            "tests/unit/test_evidence_applicability.py",
            "tests/integration/test_stage2_pipeline.py",
            "pyproject.toml",
        ],
    )
    method_version = _method_version(
        plc_days,
        source_freeze_manifest_hash,
        generated_at,
        snapshot_sha,
        source_tree_hash,
    )

    primary_assignments = _primary_assignments(
        freeze=freeze,
        plc_days=plc_days,
        method_version=method_version["method_version"],
        source_freeze_manifest_hash=source_freeze_manifest_hash,
    )
    assertion_assignments = _assertion_assignments(
        freeze=freeze,
        plc_days=plc_days,
        method_version=method_version["method_version"],
        source_freeze_manifest_hash=source_freeze_manifest_hash,
    )
    clause_assignments = _clause_assignments(
        freeze=freeze,
        plc_days=plc_days,
        method_version=method_version["method_version"],
        source_freeze_manifest_hash=source_freeze_manifest_hash,
    )

    daily_summary = base._daily_summary(
        primary_assignments,
        assertion_assignments,
        clause_assignments,
    )
    evidence_summary = base._evidence_summary(primary_assignments)
    forecast_audit = base._forecast_transition_audit(freeze["evidence"], primary_assignments)
    time_gate = base._time_gate_audit(primary_assignments)
    spatial_gate = base._spatial_gate_audit(primary_assignments)
    not_applicable = _not_applicable_reason_audit(
        primary_assignments,
        assertion_assignments,
        clause_assignments,
    )
    fixed_cases = base._fixed_case_audit(primary_assignments, assertion_assignments, freeze)
    comparison = base._comparison_with_v1(primary_assignments)
    hard_checks = _hard_checks(
        freeze=freeze,
        primary_assignments=primary_assignments,
        assertion_assignments=assertion_assignments,
        clause_assignments=clause_assignments,
        plc_days=plc_days,
    )
    difference = _semantic_difference_with_v2(primary_assignments)
    difference_summary = _difference_summary(difference, len(primary_assignments))
    leakage_audit = _spatial_leakage_regression_audit(primary_assignments)

    _write_jsonl(OUT / "evidence_applicability_assignments.jsonl", primary_assignments)
    _write_jsonl(OUT / "assertion_applicability_assignments.jsonl", assertion_assignments)
    _write_jsonl(OUT / "clause_applicability_assignments.jsonl", clause_assignments)
    _write_csv(OUT / "applicability_daily_summary.csv", daily_summary)
    _write_csv(OUT / "applicability_evidence_summary.csv", evidence_summary)
    _write_csv(OUT / "forecast_role_transition_audit.csv", forecast_audit)
    _write_csv(OUT / "time_gate_audit.csv", time_gate)
    _write_csv(OUT / "spatial_gate_audit.csv", spatial_gate)
    _write_csv(OUT / "not_applicable_reason_audit.csv", not_applicable)
    _write_csv(OUT / "fixed_applicability_case_audit.csv", fixed_cases)
    _write_csv(OUT / "applicability_comparison_with_v1.csv", comparison)
    _write_csv(OUT / "applicability_hard_check_audit.csv", hard_checks)
    _write_csv(OUT / "applicability_v2_v2_1_difference.csv", difference)
    _write_csv(OUT / "applicability_v2_v2_1_semantic_difference.csv", difference)
    _write_json(OUT / "applicability_v2_v2_1_difference_summary.json", difference_summary)
    _write_csv(OUT / "spatial_leakage_regression_audit.csv", leakage_audit)
    _write_json(OUT / "method_version.json", method_version)
    _write_json(
        OUT / "freeze_manifest.json",
        _freeze_manifest(
            method_version=method_version,
            primary_assignments=primary_assignments,
            assertion_assignments=assertion_assignments,
            clause_assignments=clause_assignments,
            plc_days=plc_days,
            difference_summary=difference_summary,
            leakage_audit=leakage_audit,
            hard_checks=hard_checks,
        ),
    )
    _write_report(
        primary_assignments=primary_assignments,
        assertion_assignments=assertion_assignments,
        clause_assignments=clause_assignments,
        plc_days=plc_days,
        difference=difference,
        difference_summary=difference_summary,
        leakage_audit=leakage_audit,
        hard_checks=hard_checks,
    )
    _write_hashes(OUT)
    print(
        json.dumps(
            {
                "plc_dates": len(plc_days),
                "primary_assignments": len(primary_assignments),
                "assertion_assignments": len(assertion_assignments),
                "clause_assignments": len(clause_assignments),
                "role_counts": dict(
                    Counter(row["applicability_role"] for row in primary_assignments)
                ),
                "difference_rows": len(difference),
                "role_changed": difference_summary["role_changed"],
                "hard_check_findings": len(hard_checks),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/stage2d_applicability_v2_1"),
    )
    parser.add_argument(
        "--plc-freeze-dir",
        type=Path,
        default=Path("artifacts/stage2_plc_operational_freeze_v2"),
    )
    parser.add_argument(
        "--geology-freeze-dir",
        type=Path,
        default=Path("artifacts/stage2_geology_v2_freeze_candidate"),
    )
    return parser.parse_args()


def _parse_generated_at(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        msg = "--generated-at must be timezone-aware"
        raise ValueError(msg)
    return value


def _resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO / path


def _load_trusted_plc_daily_scopes() -> list[dict[str, Any]]:
    rows = _read_jsonl(PLC_FREEZE / "plc_daily_scope_v2.jsonl")
    if len(rows) != 91:
        msg = f"Expected 91 trusted PLC daily scopes, found {len(rows)}"
        raise ValueError(msg)
    return sorted(rows, key=lambda row: row["target_date"])


def _primary_assignments(
    *,
    freeze: dict[str, Any],
    plc_days: list[dict[str, Any]],
    method_version: str,
    source_freeze_manifest_hash: str,
) -> list[dict[str, Any]]:
    doc_by_id = {row["document_id"]: row for row in freeze["documents"]}
    issue_by_asset = base._issue_codes_by_asset(freeze["source_issues"])
    span_ids_by_owner = base._span_ids_by_owner(freeze["spans"])
    assignments = []
    for day in plc_days:
        for evidence in freeze["evidence"]:
            document = doc_by_id[evidence["document_id"]]
            temporal = document["document"].get("temporal", {})
            assignments.append(
                _assign_spatial_role(
                    item=evidence,
                    target_day=day,
                    available_local_date=temporal.get("available_local_date"),
                    available_basis=temporal.get("available_basis"),
                    method_version=method_version,
                    source_freeze_manifest_hash=source_freeze_manifest_hash,
                    source_issue_codes=issue_by_asset.get(evidence["asset_id"], []),
                    source_span_ids=span_ids_by_owner.get(
                        ("PRIMARY_EVIDENCE", evidence["evidence_uid"]),
                        [],
                    ),
                )
            )
    return assignments


def _assertion_assignments(
    *,
    freeze: dict[str, Any],
    plc_days: list[dict[str, Any]],
    method_version: str,
    source_freeze_manifest_hash: str,
) -> list[dict[str, Any]]:
    doc_by_id = {row["document_id"]: row for row in freeze["documents"]}
    span_ids_by_owner = base._span_ids_by_owner(freeze["spans"])
    rows = []
    for day in plc_days:
        for assertion in freeze["assertions"]:
            temporal = doc_by_id[assertion["document_id"]]["document"].get("temporal", {})
            row = _assign_spatial_role(
                item={
                    "evidence_uid": assertion["assertion_uid"],
                    "document_id": assertion["document_id"],
                    "asset_id": assertion["asset_id"],
                    "filename": assertion["filename"],
                    "source_type": assertion["source_type"],
                    "evidence_type": "REPORT_ASSERTION",
                    "epistemic_status": "ASSERTION",
                    "spatial_scope": assertion["spatial_scope"],
                    "attributes": {},
                },
                target_day=day,
                available_local_date=temporal.get("available_local_date"),
                available_basis=temporal.get("available_basis"),
                method_version=method_version,
                source_freeze_manifest_hash=source_freeze_manifest_hash,
                source_issue_codes=[],
                source_span_ids=span_ids_by_owner.get(
                    ("REPORT_ASSERTION", assertion["assertion_uid"]),
                    [],
                ),
            )
            row["assertion_id"] = assertion["assertion_id"]
            row["assertion_type"] = assertion["assertion_type"]
            row["consistency_status"] = assertion.get("consistency_status", "")
            row["reason_codes"] = sorted({*row["reason_codes"], "REPORT_ASSERTION_TRACE_ONLY"})
            rows.append(row)
    return rows


def _clause_assignments(
    *,
    freeze: dict[str, Any],
    plc_days: list[dict[str, Any]],
    method_version: str,
    source_freeze_manifest_hash: str,
) -> list[dict[str, Any]]:
    doc_by_id = {row["document_id"]: row for row in freeze["documents"]}
    rows = []
    for day in plc_days:
        for clause in freeze["clauses"]:
            temporal = doc_by_id[clause["document_id"]]["document"].get("temporal", {})
            time_valid, time_reason = base._time_valid(
                temporal.get("available_local_date"),
                day["target_date"],
            )
            reasons = [time_reason, "NO_EXPLICIT_SPATIAL_SCOPE"]
            if clause.get("statement_role") == "RECOMMENDATION":
                reasons.append("RECOMMENDATION_NOT_OBSERVED_RISK")
            rows.append(
                {
                    "assignment_id": base._stable_id(
                        "clause",
                        day["target_date"],
                        clause["clause_id"],
                    ),
                    "target_date": day["target_date"],
                    "clause_id": clause["clause_id"],
                    "document_id": clause["document_id"],
                    "source_type": clause["source_type"],
                    "statement_role": clause.get("statement_role", ""),
                    "applicability_role": base.ROLE_NOT_APPLICABLE,
                    "time_valid": time_valid,
                    "spatial_relevant": False,
                    "available_local_date": temporal.get("available_local_date"),
                    "available_basis": temporal.get("available_basis"),
                    "daily_plc_range": day["daily_plc_range"],
                    "raw_daily_plc_range": day["raw_daily_plc_range"],
                    "trusted_daily_plc_range": day["trusted_daily_plc_range"],
                    "spatial_scope_status": day["spatial_scope_status"],
                    "daily_excavated_scope": day["daily_excavated_scope"],
                    "forward_scope": day["forward_scope"],
                    "local_background_scope": day["local_background_scope"],
                    "overlap_scope": None,
                    "overlap_length_m": 0.0,
                    "distance_to_face_m": "",
                    "reason_codes": sorted(set(reasons)),
                    "applicability_method_version": method_version,
                    "source_freeze_manifest_hash": source_freeze_manifest_hash,
                    "source_span_ids": clause.get("source_span_ids", []),
                }
            )
    return rows


def _assign_spatial_role(
    *,
    item: dict[str, Any],
    target_day: dict[str, Any],
    available_local_date: str | None,
    available_basis: str | None,
    method_version: str,
    source_freeze_manifest_hash: str,
    source_issue_codes: list[str],
    source_span_ids: list[str],
) -> dict[str, Any]:
    time_valid, time_reason = base._time_valid(available_local_date, target_day["target_date"])
    scope = item.get("spatial_scope") or {}
    reasons = [time_reason]
    role = base.ROLE_NOT_APPLICABLE
    spatial_relevant = False
    overlap_scope = None
    overlap_length = 0.0
    distance = _distance_to_face(scope, target_day.get("current_chainage"))
    if not time_valid:
        reasons.append("TIME_GATE_FAILED")
    elif target_day.get("spatial_scope_status") == "UNAVAILABLE":
        reasons.append("PLC_SPATIAL_SCOPE_UNAVAILABLE")
    elif not base._valid_scope(scope):
        reasons.append("INVALID_OR_MISSING_SPATIAL_SCOPE")
    else:
        role, spatial_relevant, overlap_scope, overlap_length, spatial_reasons = (
            base._role_for_scope(item, target_day)
        )
        reasons.extend(spatial_reasons)
    reasons.extend(f"SOURCE_WARNING_{code}" for code in source_issue_codes)
    return {
        "assignment_id": base._stable_id(
            "assignment",
            target_day["target_date"],
            item["document_id"],
            item["evidence_uid"],
        ),
        "target_date": target_day["target_date"],
        "evidence_id": item["evidence_uid"],
        "document_id": item["document_id"],
        "asset_id": item["asset_id"],
        "filename": item.get("filename", ""),
        "source_type": item["source_type"],
        "evidence_type": item["evidence_type"],
        "epistemic_status": item["epistemic_status"],
        "observation_scope": item.get("attributes", {}).get("observation_scope", ""),
        "applicability_role": role,
        "time_valid": time_valid,
        "spatial_relevant": spatial_relevant,
        "available_local_date": available_local_date,
        "available_basis": available_basis,
        "daily_plc_range": target_day["daily_plc_range"],
        "raw_daily_plc_range": target_day["raw_daily_plc_range"],
        "trusted_daily_plc_range": target_day["trusted_daily_plc_range"],
        "spatial_scope_status": target_day["spatial_scope_status"],
        "daily_excavated_scope": target_day["daily_excavated_scope"],
        "forward_scope": target_day["forward_scope"],
        "local_background_scope": target_day["local_background_scope"],
        "overlap_scope": overlap_scope,
        "overlap_length_m": round(overlap_length, 3),
        "distance_to_face_m": round(distance, 3) if distance is not None else "",
        "reason_codes": sorted(set(reasons)),
        "applicability_method_version": method_version,
        "source_freeze_manifest_hash": source_freeze_manifest_hash,
        "source_span_ids": source_span_ids,
    }


def _distance_to_face(scope: dict[str, Any], face: Any) -> float | None:
    if face is None:
        return None
    return base._distance_to_face(scope, float(face))


def _not_applicable_reason_audit(*assignment_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter = Counter()
    for group in assignment_groups:
        for row in group:
            if row["applicability_role"] != base.ROLE_NOT_APPLICABLE:
                continue
            for reason in [
                "NOT_YET_AVAILABLE",
                "MISSING_AVAILABLE_TIME",
                "PLC_SPATIAL_SCOPE_UNAVAILABLE",
                "NO_EXPLICIT_SPATIAL_SCOPE",
                "INVALID_OR_MISSING_SPATIAL_SCOPE",
                "OBSERVED_NOT_FORWARD_ATTENTION",
                "BACKGROUND_OUTSIDE_LOCAL_CONTEXT",
                "SPATIAL_DISJOINT",
            ]:
                if reason in row["reason_codes"]:
                    primary_reason = reason
                    break
            else:
                primary_reason = "NOT_APPLICABLE_OTHER"
            counter[(row["target_date"], row.get("source_type", ""), primary_reason)] += 1
    return [
        {
            "target_date": target_date,
            "source_type": source_type,
            "reason_code": reason,
            "assignment_count": count,
        }
        for (target_date, source_type, reason), count in sorted(counter.items())
    ]


def _semantic_difference_with_v2(primary_assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old_path = OLD_OUT / "evidence_applicability_assignments.jsonl"
    old_by_id = {row["assignment_id"]: row for row in _read_jsonl(old_path)}
    rows = []
    for row in primary_assignments:
        old = old_by_id.get(row["assignment_id"])
        if old is None:
            rows.append(
                {
                    "assignment_id": row["assignment_id"],
                    "target_date": row["target_date"],
                    "evidence_id": row["evidence_id"],
                    "change_type": "NEW_ASSIGNMENT",
                    "semantic_changed": True,
                    "role_changed": True,
                    "reason_changed": True,
                    "daily_plc_range_geometry_changed": True,
                    "daily_excavated_scope_geometry_changed": True,
                    "forward_scope_geometry_changed": True,
                    "local_background_scope_geometry_changed": True,
                    "basis_or_metadata_changed": True,
                    "old_role": "",
                    "new_role": row["applicability_role"],
                    "old_reason_codes": "",
                    "new_reason_codes": ";".join(row["reason_codes"]),
                }
            )
            continue
        role_changed = old["applicability_role"] != row["applicability_role"]
        reason_changed = set(old["reason_codes"]) != set(row["reason_codes"])
        daily_plc_changed = _scope_geometry(old.get("daily_plc_range")) != _scope_geometry(
            row.get("daily_plc_range")
        )
        daily_excavated_changed = _scope_geometry(
            old.get("daily_excavated_scope")
        ) != _scope_geometry(row.get("daily_excavated_scope"))
        forward_changed = _scope_geometry(old.get("forward_scope")) != _scope_geometry(
            row.get("forward_scope")
        )
        local_background_changed = _scope_geometry(
            old.get("local_background_scope")
        ) != _scope_geometry(row.get("local_background_scope"))
        geometry_changed = any(
            [
                daily_plc_changed,
                daily_excavated_changed,
                forward_changed,
                local_background_changed,
            ]
        )
        basis_or_metadata_changed = (
            any(
                old.get(field) != row.get(field)
                for field in [
                    "daily_plc_range",
                    "daily_excavated_scope",
                    "forward_scope",
                    "local_background_scope",
                ]
            )
            and not geometry_changed
        )
        if role_changed or reason_changed or geometry_changed or basis_or_metadata_changed:
            rows.append(
                {
                    "assignment_id": row["assignment_id"],
                    "target_date": row["target_date"],
                    "evidence_id": row["evidence_id"],
                    "change_type": _change_type(
                        role_changed,
                        reason_changed,
                        geometry_changed,
                        basis_or_metadata_changed,
                    ),
                    "semantic_changed": role_changed or reason_changed or geometry_changed,
                    "role_changed": role_changed,
                    "reason_changed": reason_changed,
                    "daily_plc_range_geometry_changed": daily_plc_changed,
                    "daily_excavated_scope_geometry_changed": daily_excavated_changed,
                    "forward_scope_geometry_changed": forward_changed,
                    "local_background_scope_geometry_changed": local_background_changed,
                    "basis_or_metadata_changed": basis_or_metadata_changed,
                    "old_role": old["applicability_role"],
                    "new_role": row["applicability_role"],
                    "old_reason_codes": ";".join(old["reason_codes"]),
                    "new_reason_codes": ";".join(row["reason_codes"]),
                }
            )
    return rows


def _scope_geometry(scope: Any) -> tuple[str, float | None, float | None]:
    if not isinstance(scope, dict):
        return ("", None, None)
    try:
        start = round(float(scope["start_chainage"]), 3)
        end = round(float(scope["end_chainage"]), 3)
    except (KeyError, TypeError, ValueError):
        return (str(scope.get("kind", "")), None, None)
    return (str(scope.get("kind", "")), start, end)


def _change_type(
    role_changed: bool,
    reason_changed: bool,
    geometry_changed: bool,
    basis_or_metadata_changed: bool,
) -> str:
    parts = []
    if role_changed:
        parts.append("ROLE_CHANGED")
    if reason_changed:
        parts.append("REASON_CHANGED")
    if geometry_changed:
        parts.append("SPATIAL_GEOMETRY_CHANGED")
    if basis_or_metadata_changed:
        parts.append("BASIS_OR_METADATA_CHANGED")
    return "+".join(parts)


def _difference_summary(rows: list[dict[str, Any]], total_assignments: int) -> dict[str, Any]:
    affected_dates = sorted(
        {row["target_date"] for row in rows if _truthy(row["semantic_changed"])}
    )
    return {
        "total_assignments": total_assignments,
        "difference_rows": len(rows),
        "semantic_changed_rows": sum(_truthy(row["semantic_changed"]) for row in rows),
        "role_changed": sum(_truthy(row["role_changed"]) for row in rows),
        "reason_changed": sum(_truthy(row["reason_changed"]) for row in rows),
        "daily_plc_scope_geometry_changed": sum(
            _truthy(row["daily_plc_range_geometry_changed"]) for row in rows
        ),
        "daily_excavated_scope_geometry_changed": sum(
            _truthy(row["daily_excavated_scope_geometry_changed"]) for row in rows
        ),
        "forward_scope_geometry_changed": sum(
            _truthy(row["forward_scope_geometry_changed"]) for row in rows
        ),
        "local_background_scope_geometry_changed": sum(
            _truthy(row["local_background_scope_geometry_changed"]) for row in rows
        ),
        "basis_or_metadata_only_changed": sum(
            _truthy(row["basis_or_metadata_changed"]) and not _truthy(row["semantic_changed"])
            for row in rows
        ),
        "affected_dates": affected_dates,
        "affected_date_count": len(affected_dates),
    }


def _truthy(value: Any) -> bool:
    return value is True or value == "True" or value == "true"


def _spatial_leakage_regression_audit(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dy_1014018 = [
        row
        for row in assignments
        if row["target_date"] == "2023-11-05"
        and _scope_contains_point(row.get("overlap_scope"), 1014018.8)
        and row["applicability_role"] == base.ROLE_DAILY_REVIEW
    ]
    unavailable_leakage = [
        row
        for row in assignments
        if row["spatial_scope_status"] == "UNAVAILABLE"
        and row["applicability_role"] != base.ROLE_NOT_APPLICABLE
    ]
    future_leakage = [
        row
        for row in assignments
        if row["available_local_date"]
        and row["target_date"] < row["available_local_date"]
        and row["applicability_role"] != base.ROLE_NOT_APPLICABLE
    ]
    return [
        {
            "check_name": "DYK1014_018_8_NOT_DAILY_REVIEW_ON_2023_11_05",
            "finding_count": len(dy_1014018),
            "status": "PASS" if not dy_1014018 else "FAIL",
        },
        {
            "check_name": "NO_ROLE_FROM_UNAVAILABLE_PLC_SPATIAL_SCOPE",
            "finding_count": len(unavailable_leakage),
            "status": "PASS" if not unavailable_leakage else "FAIL",
        },
        {
            "check_name": "TEMPORAL_FUTURE_LEAKAGE",
            "finding_count": len(future_leakage),
            "status": "PASS" if not future_leakage else "FAIL",
        },
        {
            "check_name": "SPATIAL_REGIME_LEAKAGE",
            "finding_count": len(unavailable_leakage),
            "status": "PASS" if not unavailable_leakage else "FAIL",
        },
    ]


def _scope_contains_point(scope: Any, chainage: float) -> bool:
    if not isinstance(scope, dict):
        return False
    try:
        start = float(scope["start_chainage"])
        end = float(scope["end_chainage"])
    except (KeyError, TypeError, ValueError):
        return False
    return start <= chainage <= end


def _hard_checks(
    *,
    freeze: dict[str, Any],
    primary_assignments: list[dict[str, Any]],
    assertion_assignments: list[dict[str, Any]],
    clause_assignments: list[dict[str, Any]],
    plc_days: list[dict[str, Any]],
) -> list[dict[str, str]]:
    rows = base._hard_checks(
        freeze=freeze,
        primary_assignments=primary_assignments,
        assertion_assignments=assertion_assignments,
        clause_assignments=clause_assignments,
        plc_days=plc_days,
    )
    if any(
        row["spatial_scope_status"] == "UNAVAILABLE"
        and row["applicability_role"] != base.ROLE_NOT_APPLICABLE
        for row in primary_assignments
    ):
        rows.append(base._check("PLC_SPATIAL_SCOPE_UNAVAILABLE_LEAKAGE", ""))
    role_counts = Counter(row["applicability_role"] for row in primary_assignments)
    expected_role_counts = {
        base.ROLE_DAILY_REVIEW: 285,
        base.ROLE_FORWARD_ATTENTION: 138,
        base.ROLE_LOCAL_BACKGROUND: 1052,
        base.ROLE_NOT_APPLICABLE: 58494,
    }
    if dict(role_counts) != expected_role_counts:
        rows.append(base._check("ROLE_COUNT_MISMATCH", json.dumps(dict(role_counts))))
    leakage = _spatial_leakage_regression_audit(primary_assignments)
    if any(row["status"] != "PASS" for row in leakage):
        rows.append(base._check("SPATIAL_LEAKAGE_REGRESSION_FAILED", json.dumps(leakage)))
    return rows


def _method_version(
    plc_days: list[dict[str, Any]],
    source_freeze_manifest_hash: str,
    generated_at: datetime,
    source_snapshot_sha256: str,
    source_tree_hash: str,
) -> dict[str, Any]:
    return {
        "method_version": METHOD_VERSION,
        "generated_at": generated_at.isoformat(),
        "source_freeze_dir": _repo_relative(FREEZE),
        "source_freeze_manifest_hash": source_freeze_manifest_hash,
        "source_freeze_method_version": _read_json(FREEZE / "method_version.json"),
        "plc_operational_freeze_dir": _repo_relative(PLC_FREEZE),
        "plc_operational_freeze_manifest_hash": _sha256(PLC_FREEZE / "freeze_manifest.json"),
        "output_dir": _repo_relative(OUT),
        "plc_date_count": len(plc_days),
        "trusted_plc_scope_used": True,
        "parser_rerun": False,
        "llm_used": False,
        "applicability_scope": "daily_trusted_plc_scope_x_frozen_primary_evidence",
        "git_commit_hash": _git(["rev-parse", "HEAD"]) or "NO_COMMITS",
        "working_tree_dirty": bool(_git(["status", "--short"])),
        "source_snapshot_sha256": source_snapshot_sha256,
        "applicability_source_tree_hash": source_tree_hash,
    }


def _repo_relative(path: Path) -> str:
    return path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else path.as_posix()


def _write_report(
    *,
    primary_assignments: list[dict[str, Any]],
    assertion_assignments: list[dict[str, Any]],
    clause_assignments: list[dict[str, Any]],
    plc_days: list[dict[str, Any]],
    difference: list[dict[str, Any]],
    difference_summary: dict[str, Any],
    leakage_audit: list[dict[str, Any]],
    hard_checks: list[dict[str, Any]],
) -> None:
    role_counts = Counter(row["applicability_role"] for row in primary_assignments)
    spatial_status_counts = Counter(row["spatial_scope_status"] for row in plc_days)
    unavailable_dates = [
        row["target_date"] for row in plc_days if row["spatial_scope_status"] == "UNAVAILABLE"
    ]
    lines = [
        "# Stage 2D Applicability V2.1 Report",
        "",
        "This run uses Stage 2E trusted PLC spatial scopes and does not modify geology evidence.",
        "",
        f"- PLC dates: {len(plc_days)}",
        f"- trusted spatial unavailable dates: {unavailable_dates}",
        f"- primary assignments: {len(primary_assignments)}",
        f"- assertion assignments: {len(assertion_assignments)}",
        f"- clause assignments: {len(clause_assignments)}",
        f"- role counts: {dict(sorted(role_counts.items()))}",
        f"- trusted spatial AVAILABLE dates: {spatial_status_counts['AVAILABLE']}",
        f"- trusted spatial PARTIAL dates: {spatial_status_counts['PARTIAL']}",
        f"- trusted spatial UNAVAILABLE dates: {spatial_status_counts['UNAVAILABLE']}",
        f"- semantic difference rows: {difference_summary['semantic_changed_rows']}",
        f"- role changed rows: {difference_summary['role_changed']}",
        f"- reason changed rows: {difference_summary['reason_changed']}",
        "- daily PLC scope geometry changed rows: "
        f"{difference_summary['daily_plc_scope_geometry_changed']}",
        "- basis or metadata only changed rows: "
        f"{difference_summary['basis_or_metadata_only_changed']}",
        f"- semantic affected dates: {difference_summary['affected_dates']}",
        f"- hard check findings: {len(hard_checks)}",
        "",
        "## Leakage Regression",
        "",
        *[
            f"- {row['check_name']}: {row['status']} ({row['finding_count']})"
            for row in leakage_audit
        ],
    ]
    (OUT / "applicability_v2_1_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _freeze_manifest(
    *,
    method_version: dict[str, Any],
    primary_assignments: list[dict[str, Any]],
    assertion_assignments: list[dict[str, Any]],
    clause_assignments: list[dict[str, Any]],
    plc_days: list[dict[str, Any]],
    difference_summary: dict[str, Any],
    leakage_audit: list[dict[str, Any]],
    hard_checks: list[dict[str, Any]],
) -> dict[str, Any]:
    role_counts = Counter(row["applicability_role"] for row in primary_assignments)
    spatial_status_counts = Counter(row["spatial_scope_status"] for row in plc_days)
    return {
        "method_version": method_version["method_version"],
        "generated_at": method_version["generated_at"],
        "source_freeze_dir": method_version["source_freeze_dir"],
        "plc_operational_freeze_dir": method_version["plc_operational_freeze_dir"],
        "primary_assignment_count": len(primary_assignments),
        "assertion_assignment_count": len(assertion_assignments),
        "clause_assignment_count": len(clause_assignments),
        "role_counts": dict(sorted(role_counts.items())),
        "trusted_spatial_status_counts": dict(sorted(spatial_status_counts.items())),
        "difference_summary": difference_summary,
        "leakage_audit": leakage_audit,
        "hard_check_issue_count": len(hard_checks),
        "source_snapshot_sha256": method_version["source_snapshot_sha256"],
        "applicability_source_tree_hash": method_version["applicability_source_tree_hash"],
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return base._read_jsonl(path)


def _read_json(path: Path) -> dict[str, Any]:
    return base._read_json(path)


def _sha256(path: Path) -> str:
    return base._sha256(path)


def _git(args: list[str]) -> str:
    return base._git(args)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row}) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fields})


def _csv_value(value: Any) -> str | int | float | bool | None:
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _write_hashes(directory: Path) -> None:
    hashes: dict[str, str] = {}
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        if path.name == "file_hashes.sha256":
            continue
        hashes[path.relative_to(directory).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    content = "".join(f"{digest}  {rel}\n" for rel, digest in sorted(hashes.items()))
    (directory / "file_hashes.sha256").write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
