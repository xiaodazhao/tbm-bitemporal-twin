"""Build deterministic Stage 2D applicability from the V2 geology freeze snapshot."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from tbm_twin.channels.catalog import load_channel_catalog

REPO = Path(__file__).resolve().parents[1]
FREEZE = REPO / "artifacts/stage2_geology_v2_freeze_candidate"
OUT = REPO / "artifacts/stage2d_applicability_v2"
STAGE1_SUMMARY = REPO / "artifacts/stage1_validation/validation_summary.json"
V1_ASSIGNMENTS = (
    REPO
    / "_archive"
    / "artifacts_stage2_history"
    / "stage2_raw_geology_validation"
    / "applicability_assignments.json"
)

METHOD_VERSION = "stage2d_applicability_v2"
CELL_SIZE_M = 10.0
LOOKAHEAD_M = 30.0
LOCAL_BACKGROUND_BACK_M = 100.0

ROLE_DAILY_REVIEW = "DAILY_REVIEW"
ROLE_FORWARD_ATTENTION = "FORWARD_ATTENTION"
ROLE_LOCAL_BACKGROUND = "LOCAL_BACKGROUND"
ROLE_NOT_APPLICABLE = "NOT_APPLICABLE"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    freeze = _load_freeze()
    _assert_freeze_baseline(freeze)
    plc_days = _load_plc_daily_scopes()
    source_freeze_manifest_hash = _sha256(FREEZE / "freeze_manifest.json")
    method_version = _method_version(plc_days, source_freeze_manifest_hash)

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

    daily_summary = _daily_summary(primary_assignments, assertion_assignments, clause_assignments)
    evidence_summary = _evidence_summary(primary_assignments)
    forecast_audit = _forecast_transition_audit(freeze["evidence"], primary_assignments)
    time_gate = _time_gate_audit(primary_assignments)
    spatial_gate = _spatial_gate_audit(primary_assignments)
    not_applicable = _not_applicable_reason_audit(
        primary_assignments,
        assertion_assignments,
        clause_assignments,
    )
    fixed_cases = _fixed_case_audit(primary_assignments, assertion_assignments, freeze)
    comparison = _comparison_with_v1(primary_assignments)
    hard_checks = _hard_checks(
        freeze=freeze,
        primary_assignments=primary_assignments,
        assertion_assignments=assertion_assignments,
        clause_assignments=clause_assignments,
        plc_days=plc_days,
    )

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
    _write_json(OUT / "method_version.json", method_version)
    _write_report(
        method_version=method_version,
        freeze=freeze,
        plc_days=plc_days,
        primary_assignments=primary_assignments,
        assertion_assignments=assertion_assignments,
        clause_assignments=clause_assignments,
        forecast_audit=forecast_audit,
        hard_checks=hard_checks,
    )
    _write_hashes()
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
                "hard_check_findings": len(hard_checks),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _load_freeze() -> dict[str, Any]:
    return {
        "documents": _read_jsonl(FREEZE / "geological_documents.jsonl"),
        "evidence": _read_jsonl(FREEZE / "primary_geological_evidence.jsonl"),
        "assertions": _read_jsonl(FREEZE / "report_assertions.jsonl"),
        "clauses": _read_jsonl(FREEZE / "unlocated_clauses.jsonl"),
        "spans": _read_jsonl(FREEZE / "source_spans.jsonl"),
        "manifest": _read_json(FREEZE / "freeze_manifest.json"),
        "method": _read_json(FREEZE / "method_version.json"),
        "source_issues": _read_csv(FREEZE / "source_data_issue_audit.csv"),
    }


def _assert_freeze_baseline(freeze: dict[str, Any]) -> None:
    expected = {
        "documents": 223,
        "evidence": 659,
        "assertions": 122,
        "clauses": 496,
        "spans": 4713,
    }
    actual = {key: len(freeze[key]) for key in expected}
    if actual != expected:
        raise ValueError(f"Freeze baseline mismatch: expected {expected}, got {actual}")


def _load_plc_daily_scopes() -> list[dict[str, Any]]:
    summary = _read_json(STAGE1_SUMMARY)
    data_dir = Path(summary["plc_data_dir"])
    files = sorted(data_dir.glob("tbm_data_*.csv"))
    catalog = load_channel_catalog()
    scopes = []
    for path in files:
        raw_columns, encoding = _read_plc_header(path)
        matches = catalog.resolve_columns(raw_columns)
        chainage_column = matches["shield_head_chainage"].raw_name
        raw = pd.read_csv(path, encoding=encoding, usecols=[chainage_column])
        values = pd.to_numeric(raw[chainage_column], errors="coerce")
        values = values[(values > 0) & values.notna()]
        if values.empty:
            continue
        date = path.stem.removeprefix("tbm_data_")
        target_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        daily_min = float(values.min())
        daily_max = float(values.max())
        excavated_start = math.floor(daily_min / CELL_SIZE_M) * CELL_SIZE_M
        excavated_end = math.ceil(daily_max / CELL_SIZE_M) * CELL_SIZE_M
        if excavated_end <= excavated_start:
            excavated_end = excavated_start + CELL_SIZE_M
        scope = {
            "target_date": target_date,
            "daily_plc_range": _scope("INTERVAL", daily_min, daily_max, "plc_raw_daily_range"),
            "daily_excavated_scope": _scope(
                "INTERVAL",
                excavated_start,
                excavated_end,
                "ten_meter_aligned_daily_review_scope",
            ),
            "forward_scope": _scope(
                "INTERVAL",
                excavated_end,
                excavated_end + LOOKAHEAD_M,
                "forward_attention_scope",
            ),
            "local_background_scope": _scope(
                "INTERVAL",
                excavated_start - LOCAL_BACKGROUND_BACK_M,
                excavated_start,
                "local_background_scope",
            ),
            "current_chainage": daily_max,
            "raw_plc_file": str(path),
            "chainage_column": chainage_column,
        }
        scopes.append(scope)
    return scopes


def _read_plc_header(path: Path) -> tuple[list[str], str]:
    encodings = ("utf-8-sig", "utf-8", "gb18030")
    failures = []
    for encoding in encodings:
        try:
            columns = pd.read_csv(path, encoding=encoding, nrows=0).columns
            return [str(column) for column in columns], encoding
        except UnicodeDecodeError as exc:
            failures.append(f"{encoding}: {exc}")
    msg = f"Could not decode CSV header {path}. Tried: {'; '.join(failures)}"
    raise ValueError(msg)


def _primary_assignments(
    *,
    freeze: dict[str, Any],
    plc_days: list[dict[str, Any]],
    method_version: str,
    source_freeze_manifest_hash: str,
) -> list[dict[str, Any]]:
    doc_by_id = {row["document_id"]: row for row in freeze["documents"]}
    issue_by_asset = _issue_codes_by_asset(freeze["source_issues"])
    span_ids_by_owner = _span_ids_by_owner(freeze["spans"])
    assignments = []
    for day in plc_days:
        for evidence in freeze["evidence"]:
            document = doc_by_id[evidence["document_id"]]
            temporal = document["document"].get("temporal", {})
            assignment = _assign_spatial_role(
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
            assignments.append(assignment)
    return assignments


def _assertion_assignments(
    *,
    freeze: dict[str, Any],
    plc_days: list[dict[str, Any]],
    method_version: str,
    source_freeze_manifest_hash: str,
) -> list[dict[str, Any]]:
    doc_by_id = {row["document_id"]: row for row in freeze["documents"]}
    span_ids_by_owner = _span_ids_by_owner(freeze["spans"])
    rows = []
    for day in plc_days:
        for assertion in freeze["assertions"]:
            temporal = doc_by_id[assertion["document_id"]]["document"].get("temporal", {})
            base = _assign_spatial_role(
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
            base["assertion_id"] = assertion["assertion_id"]
            base["assertion_type"] = assertion["assertion_type"]
            base["consistency_status"] = assertion.get("consistency_status", "")
            base["reason_codes"] = sorted(
                set(base["reason_codes"] + ["REPORT_ASSERTION_TRACE_ONLY"])
            )
            rows.append(base)
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
            time_valid, time_reason = _time_valid(
                temporal.get("available_local_date"),
                day["target_date"],
            )
            reasons = [time_reason, "NO_EXPLICIT_SPATIAL_SCOPE"]
            if clause.get("statement_role") == "RECOMMENDATION":
                reasons.append("RECOMMENDATION_NOT_OBSERVED_RISK")
            rows.append(
                {
                    "assignment_id": _stable_id(
                        "clause",
                        day["target_date"],
                        clause["clause_id"],
                    ),
                    "target_date": day["target_date"],
                    "clause_id": clause["clause_id"],
                    "document_id": clause["document_id"],
                    "source_type": clause["source_type"],
                    "statement_role": clause.get("statement_role", ""),
                    "applicability_role": ROLE_NOT_APPLICABLE,
                    "time_valid": time_valid,
                    "spatial_relevant": False,
                    "available_local_date": temporal.get("available_local_date"),
                    "available_basis": temporal.get("available_basis"),
                    "daily_plc_range": day["daily_plc_range"],
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
    time_valid, time_reason = _time_valid(available_local_date, target_day["target_date"])
    scope = item.get("spatial_scope") or {}
    reasons = [time_reason]
    role = ROLE_NOT_APPLICABLE
    spatial_relevant = False
    overlap_scope = None
    overlap_length = 0.0
    distance = _distance_to_face(scope, target_day["current_chainage"])
    if not time_valid:
        reasons.append("TIME_GATE_FAILED")
    elif not _valid_scope(scope):
        reasons.append("INVALID_OR_MISSING_SPATIAL_SCOPE")
    else:
        role, spatial_relevant, overlap_scope, overlap_length, spatial_reasons = _role_for_scope(
            item,
            target_day,
        )
        reasons.extend(spatial_reasons)
    reasons.extend(f"SOURCE_WARNING_{code}" for code in source_issue_codes)
    return {
        "assignment_id": _stable_id(
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


def _role_for_scope(
    item: dict[str, Any],
    target_day: dict[str, Any],
) -> tuple[str, bool, dict[str, Any] | None, float, list[str]]:
    scope = item["spatial_scope"]
    evidence_type = item["evidence_type"]
    epistemic_status = item["epistemic_status"]
    observation_scope = item.get("attributes", {}).get("observation_scope", "")
    daily_overlap = _overlap(scope, target_day["daily_excavated_scope"])
    forward_overlap = _overlap(scope, target_day["forward_scope"])
    local_overlap = _overlap(scope, target_day["local_background_scope"])

    if evidence_type == "DESIGN_BACKGROUND" or epistemic_status == "BACKGROUND":
        if local_overlap[1] > 0:
            return (
                ROLE_LOCAL_BACKGROUND,
                True,
                local_overlap[0],
                local_overlap[1],
                ["BACKGROUND_LOCAL_CONTEXT_ONLY"],
            )
        return ROLE_NOT_APPLICABLE, False, None, 0.0, ["BACKGROUND_OUTSIDE_LOCAL_CONTEXT"]

    if evidence_type == "FACE_OBSERVATION" and epistemic_status == "OBSERVED":
        if daily_overlap[1] > 0:
            return ROLE_DAILY_REVIEW, True, daily_overlap[0], daily_overlap[1], ["DAILY_OVERLAP"]
        if local_overlap[1] > 0:
            return (
                ROLE_LOCAL_BACKGROUND,
                True,
                local_overlap[0],
                local_overlap[1],
                ["OBSERVED_LOCAL_CONTEXT"],
            )
        if forward_overlap[1] > 0:
            return (
                ROLE_NOT_APPLICABLE,
                False,
                forward_overlap[0],
                forward_overlap[1],
                ["OBSERVED_NOT_FORWARD_ATTENTION"],
            )
        return ROLE_NOT_APPLICABLE, False, None, 0.0, ["SPATIAL_DISJOINT"]

    if evidence_type == "FORECAST_SEGMENT" and epistemic_status == "FORECAST":
        if observation_scope == "FACE_POINT":
            return ROLE_NOT_APPLICABLE, False, None, 0.0, ["INVALID_FORECAST_POINT"]
        if daily_overlap[1] > 0:
            return (
                ROLE_DAILY_REVIEW,
                True,
                daily_overlap[0],
                daily_overlap[1],
                ["FORECAST_DAILY_REVIEW_REMAINS_FORECAST"],
            )
        if forward_overlap[1] > 0:
            return (
                ROLE_FORWARD_ATTENTION,
                True,
                forward_overlap[0],
                forward_overlap[1],
                ["FORECAST_FORWARD_OVERLAP"],
            )
        if local_overlap[1] > 0:
            return (
                ROLE_LOCAL_BACKGROUND,
                True,
                local_overlap[0],
                local_overlap[1],
                ["FORECAST_LOCAL_CONTEXT"],
            )
        return ROLE_NOT_APPLICABLE, False, None, 0.0, ["SPATIAL_DISJOINT"]

    if evidence_type == "REPORT_ASSERTION":
        if daily_overlap[1] > 0:
            return (
                ROLE_DAILY_REVIEW,
                True,
                daily_overlap[0],
                daily_overlap[1],
                ["ASSERTION_DAILY_TRACE"],
            )
        if forward_overlap[1] > 0:
            return (
                ROLE_FORWARD_ATTENTION,
                True,
                forward_overlap[0],
                forward_overlap[1],
                ["ASSERTION_FORWARD_TRACE"],
            )
        if local_overlap[1] > 0:
            return (
                ROLE_LOCAL_BACKGROUND,
                True,
                local_overlap[0],
                local_overlap[1],
                ["ASSERTION_LOCAL_TRACE"],
            )
        return ROLE_NOT_APPLICABLE, False, None, 0.0, ["SPATIAL_DISJOINT"]

    return ROLE_NOT_APPLICABLE, False, None, 0.0, ["UNSUPPORTED_EVIDENCE_TYPE"]


def _time_valid(available_local_date: str | None, target_date: str) -> tuple[bool, str]:
    if not available_local_date:
        return False, "MISSING_AVAILABLE_TIME"
    if available_local_date > target_date:
        return False, "NOT_YET_AVAILABLE"
    return True, "AVAILABLE_ON_TARGET_DATE"


def _valid_scope(scope: dict[str, Any]) -> bool:
    try:
        start = float(scope["start_chainage"])
        end = float(scope["end_chainage"])
    except (KeyError, TypeError, ValueError):
        return False
    if scope.get("kind") == "POINT":
        return start == end
    if scope.get("kind") == "INTERVAL":
        return start < end
    return False


def _overlap(
    scope: dict[str, Any],
    target: dict[str, Any],
) -> tuple[dict[str, Any] | None, float]:
    kind = scope.get("kind")
    start = float(scope["start_chainage"])
    end = float(scope["end_chainage"])
    target_start = float(target["start_chainage"])
    target_end = float(target["end_chainage"])
    if kind == "POINT":
        if target_start <= start <= target_end:
            return _scope("POINT", start, start, "point_in_scope"), 1.0
        return None, 0.0
    overlap_start = max(start, target_start)
    overlap_end = min(end, target_end)
    if overlap_end > overlap_start:
        overlap_scope = _scope("INTERVAL", overlap_start, overlap_end, "interval_overlap")
        return overlap_scope, overlap_end - overlap_start
    return None, 0.0


def _distance_to_face(scope: dict[str, Any], face: float) -> float | None:
    if not _valid_scope(scope):
        return None
    start = float(scope["start_chainage"])
    end = float(scope["end_chainage"])
    if start <= face <= end:
        return 0.0
    return min(abs(face - start), abs(face - end))


def _scope(kind: str, start: float, end: float, basis: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "start_chainage": round(float(start), 3),
        "end_chainage": round(float(end), 3),
        "basis": basis,
    }


def _daily_summary(
    primary: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
    clauses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    primary_by_date = _group_by(primary, "target_date")
    assertions_by_date = _group_by(assertions, "target_date")
    clauses_by_date = _group_by(clauses, "target_date")
    for target_date in sorted(primary_by_date):
        items = primary_by_date[target_date]
        role_counts = Counter(row["applicability_role"] for row in items)
        source_counts = Counter(
            f"{row['source_type']}|{row['applicability_role']}" for row in items
        )
        epistemic_counts = Counter(
            f"{row['epistemic_status']}|{row['applicability_role']}" for row in items
        )
        rows.append(
            {
                "target_date": target_date,
                "primary_assignment_count": len(items),
                "applicable_primary_evidence_count": sum(
                    row["applicability_role"] != ROLE_NOT_APPLICABLE for row in items
                ),
                "daily_review_count": role_counts[ROLE_DAILY_REVIEW],
                "forward_attention_count": role_counts[ROLE_FORWARD_ATTENTION],
                "local_background_count": role_counts[ROLE_LOCAL_BACKGROUND],
                "not_applicable_count": role_counts[ROLE_NOT_APPLICABLE],
                "sketch_distribution": _counter_prefix(source_counts, "FACE_SKETCH"),
                "hsp_distribution": _counter_prefix(source_counts, "SONIC_FORECAST"),
                "tsp_distribution": _counter_prefix(source_counts, "TSP_REPORT"),
                "observed_distribution": _counter_prefix(epistemic_counts, "OBSERVED"),
                "forecast_distribution": _counter_prefix(epistemic_counts, "FORECAST"),
                "background_distribution": _counter_prefix(epistemic_counts, "BACKGROUND"),
                "time_gate_blocked_count": sum(not row["time_valid"] for row in items),
                "spatial_gate_blocked_count": sum(
                    row["time_valid"] and not row["spatial_relevant"] for row in items
                ),
                "unlocated_clause_not_applicable_count": len(clauses_by_date[target_date]),
                "assertion_assignment_count": len(assertions_by_date[target_date]),
            }
        )
    return rows


def _evidence_summary(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for evidence_id, items in sorted(_group_by(assignments, "evidence_id").items()):
        role_counts = Counter(row["applicability_role"] for row in items)
        first_applicable = _first_date(
            row for row in items if row["applicability_role"] != ROLE_NOT_APPLICABLE
        )
        sample = items[0]
        rows.append(
            {
                "evidence_id": evidence_id,
                "document_id": sample["document_id"],
                "source_type": sample["source_type"],
                "evidence_type": sample["evidence_type"],
                "epistemic_status": sample["epistemic_status"],
                "available_local_date": sample["available_local_date"],
                "ever_applicable": first_applicable != "",
                "first_applicable_date": first_applicable,
                "daily_review_count": role_counts[ROLE_DAILY_REVIEW],
                "forward_attention_count": role_counts[ROLE_FORWARD_ATTENTION],
                "local_background_count": role_counts[ROLE_LOCAL_BACKGROUND],
                "not_applicable_count": role_counts[ROLE_NOT_APPLICABLE],
                "role_sequence": _role_sequence(items),
            }
        )
    return rows


def _forecast_transition_audit(
    evidence: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    assignment_by_evidence = _group_by(assignments, "evidence_id")
    rows = []
    for item in evidence:
        if item["evidence_type"] != "FORECAST_SEGMENT":
            continue
        items = sorted(
            assignment_by_evidence[item["evidence_uid"]],
            key=lambda row: row["target_date"],
        )
        daily_before_available = any(
            row["applicability_role"] == ROLE_DAILY_REVIEW
            and row["available_local_date"]
            and row["target_date"] < row["available_local_date"]
            for row in items
        )
        daily_without_overlap = any(
            row["applicability_role"] == ROLE_DAILY_REVIEW
            and "FORECAST_DAILY_REVIEW_REMAINS_FORECAST" not in row["reason_codes"]
            for row in items
        )
        sequence = _role_sequence(items)
        transition_valid = not daily_before_available and not daily_without_overlap
        warning = []
        if daily_before_available:
            warning.append("DAILY_REVIEW_BEFORE_AVAILABLE")
        if daily_without_overlap:
            warning.append("DAILY_REVIEW_WITHOUT_OVERLAP")
        rows.append(
            {
                "evidence_id": item["evidence_uid"],
                "source_type": item["source_type"],
                "spatial_start": item["spatial_scope"]["start_chainage"],
                "spatial_end": item["spatial_scope"]["end_chainage"],
                "available_local_date": items[0]["available_local_date"],
                "first_applicable_date": _first_date(
                    row for row in items if row["applicability_role"] != ROLE_NOT_APPLICABLE
                ),
                "first_forward_attention_date": _first_date(
                    row for row in items if row["applicability_role"] == ROLE_FORWARD_ATTENTION
                ),
                "first_daily_review_date": _first_date(
                    row for row in items if row["applicability_role"] == ROLE_DAILY_REVIEW
                ),
                "last_daily_review_date": _last_date(
                    row for row in items if row["applicability_role"] == ROLE_DAILY_REVIEW
                ),
                "role_sequence": sequence,
                "transition_valid": transition_valid,
                "warning_code": ";".join(warning),
            }
        )
    return rows


def _time_gate_audit(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter = Counter()
    for row in assignments:
        reason = (
            "AVAILABLE_ON_TARGET_DATE"
            if row["time_valid"]
            else _first_reason(row, "NOT_YET_AVAILABLE", "MISSING_AVAILABLE_TIME")
        )
        counter[(row["target_date"], reason)] += 1
    return [
        {"target_date": target_date, "time_gate_status": reason, "assignment_count": count}
        for (target_date, reason), count in sorted(counter.items())
    ]


def _spatial_gate_audit(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter = Counter()
    for row in assignments:
        if not row["time_valid"]:
            continue
        reason = row["applicability_role"]
        if not row["spatial_relevant"]:
            reason = _first_reason(
                row,
                "SPATIAL_DISJOINT",
                "OBSERVED_NOT_FORWARD_ATTENTION",
                "INVALID_OR_MISSING_SPATIAL_SCOPE",
                "BACKGROUND_OUTSIDE_LOCAL_CONTEXT",
            )
        counter[(row["target_date"], row["source_type"], reason)] += 1
    return [
        {
            "target_date": target_date,
            "source_type": source_type,
            "spatial_gate_status": reason,
            "assignment_count": count,
        }
        for (target_date, source_type, reason), count in sorted(counter.items())
    ]


def _not_applicable_reason_audit(*assignment_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter = Counter()
    for group in assignment_groups:
        for row in group:
            if row["applicability_role"] != ROLE_NOT_APPLICABLE:
                continue
            primary_reason = _primary_not_applicable_reason(row)
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


def _fixed_case_audit(
    primary: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
    freeze: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence_ids = _fixed_case_evidence_ids(freeze)
    assertion_ids = {
        "TSP_DYK1013_080_200_ASSERTIONS": [
            row["assertion_uid"]
            for row in freeze["assertions"]
            if "DyK1013+080.2" in row["filename"]
        ]
    }
    rows = []
    for label, ids in evidence_ids.items():
        for row in primary:
            if row["evidence_id"] in ids:
                rows.append(_case_row(label, row))
    for label, ids in assertion_ids.items():
        for row in assertions:
            if row["evidence_id"] in ids:
                rows.append(_case_row(label, row))
    return sorted(rows, key=lambda row: (row["case_id"], row["target_date"], row["evidence_id"]))


def _fixed_case_evidence_ids(freeze: dict[str, Any]) -> dict[str, list[str]]:
    cases: dict[str, list[str]] = defaultdict(list)
    for item in freeze["evidence"]:
        filename = item["filename"]
        scope = item["spatial_scope"]
        start = float(scope["start_chainage"])
        end = float(scope["end_chainage"])
        if "DyK1013+080.2" in filename:
            cases["TSP_DYK1013_080_200"].append(item["evidence_uid"])
        if "DyK1013+190.2" in filename and "水平声波" in filename:
            cases["HSP_DYK1013_190_290"].append(item["evidence_uid"])
        if item["source_type"] == "FACE_SKETCH" and start == 1014675.0 and end == 1014705.0:
            cases["SKETCH_DYK1014_675_705_FORECAST"].append(item["evidence_uid"])
        if item["source_type"] == "FACE_SKETCH" and start == 1015610.0 and end == 1015625.0:
            cases["SKETCH_DYK1015_610_625_CURRENT_INTERVAL"].append(item["evidence_uid"])
        if "DyK1016+998" in filename and "水平声波" in filename:
            cases["HSP_CROSS_KM_DYK1016_998_1017_098"].append(item["evidence_uid"])
        if item["asset_id"] == "2219b50acc3ffb1f749f26de":
            cases["SKETCH_SOURCE_CHAINAGE_CONFLICT"].append(item["evidence_uid"])
    return cases


def _case_row(label: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": label,
        "target_date": row["target_date"],
        "evidence_id": row["evidence_id"],
        "document_id": row["document_id"],
        "source_type": row["source_type"],
        "evidence_type": row["evidence_type"],
        "epistemic_status": row["epistemic_status"],
        "applicability_role": row["applicability_role"],
        "time_valid": row["time_valid"],
        "spatial_relevant": row["spatial_relevant"],
        "available_local_date": row["available_local_date"],
        "overlap_scope": row["overlap_scope"],
        "overlap_length_m": row["overlap_length_m"],
        "distance_to_face_m": row["distance_to_face_m"],
        "reason_codes": ";".join(row["reason_codes"]),
    }


def _comparison_with_v1(primary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    v1_count = 0
    v1_reasons: Counter[str] = Counter()
    if V1_ASSIGNMENTS.exists():
        v1 = _read_json(V1_ASSIGNMENTS)
        if isinstance(v1, list):
            v1_count = len(v1)
            v1_reasons = Counter(str(row.get("dominant_reason_code", "")) for row in v1)
    role_counts = Counter(row["applicability_role"] for row in primary)
    rows.append(
        {
            "comparison_category": "V1_EPISODE_ASSIGNMENTS_REFERENCE_ONLY",
            "v1_count": v1_count,
            "v2_count": "",
            "interpretation": "V1 targeted episode assignments and is not a formal input.",
        }
    )
    for role, count in sorted(role_counts.items()):
        rows.append(
            {
                "comparison_category": f"V2_PURPOSE_ROLE_{role}",
                "v1_count": "",
                "v2_count": count,
                "interpretation": (
                    "V2 assigns purpose roles over frozen primary evidence and daily PLC scopes."
                ),
            }
        )
    for reason, count in sorted(v1_reasons.items()):
        if reason:
            rows.append(
                {
                    "comparison_category": f"V1_REASON_{reason}",
                    "v1_count": count,
                    "v2_count": "",
                    "interpretation": "Legacy reason retained only for difference audit.",
                }
            )
    rows.extend(
        [
            {
                "comparison_category": "V1_FORECAST_AS_POINT_OBSERVATION_CHECK",
                "v1_count": "",
                "v2_count": sum(
                    row["applicability_role"] == ROLE_FORWARD_ATTENTION
                    and row["epistemic_status"] == "OBSERVED"
                    and row["evidence_type"] == "FACE_OBSERVATION"
                    for row in primary
                ),
                "interpretation": (
                    "Target is 0: observed face points must not become forward attention."
                ),
            },
            {
                "comparison_category": "V2_NEW_SKETCH_INTERVAL_ASSIGNMENTS",
                "v1_count": "",
                "v2_count": sum(
                    row["source_type"] == "FACE_SKETCH"
                    and row["observation_scope"]
                    in {"FORECAST_SEGMENT", "CURRENT_EXCAVATED_INTERVAL"}
                    and row["applicability_role"] != ROLE_NOT_APPLICABLE
                    for row in primary
                ),
                "interpretation": "V2 separates sketch intervals from face points.",
            },
        ]
    )
    return rows


def _hard_checks(
    *,
    freeze: dict[str, Any],
    primary_assignments: list[dict[str, Any]],
    assertion_assignments: list[dict[str, Any]],
    clause_assignments: list[dict[str, Any]],
    plc_days: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    evidence_ids = {row["evidence_uid"] for row in freeze["evidence"]}
    span_owner_ids = {row["owner_id"] for row in freeze["spans"]}
    expected_assignments = len(plc_days) * 659
    if len(primary_assignments) != expected_assignments:
        rows.append(_check("PRIMARY_ASSIGNMENT_COUNT_MISMATCH", str(len(primary_assignments))))
    for row in primary_assignments:
        if row["evidence_id"] not in evidence_ids:
            rows.append(_check("UNKNOWN_EVIDENCE_ID", row["evidence_id"]))
        if (
            row["available_local_date"]
            and row["target_date"] < row["available_local_date"]
            and row["applicability_role"] != ROLE_NOT_APPLICABLE
        ):
            rows.append(_check("TIME_LEAKAGE", row["assignment_id"]))
        if (
            row["evidence_type"] == "FACE_OBSERVATION"
            and row["epistemic_status"] == "OBSERVED"
            and row["applicability_role"] == ROLE_FORWARD_ATTENTION
        ):
            rows.append(_check("OBSERVED_FACE_FORWARD_ATTENTION", row["assignment_id"]))
        if row["source_span_ids"] and row["evidence_id"] not in span_owner_ids:
            rows.append(_check("MISSING_SOURCE_SPAN_TRACE", row["assignment_id"]))
    for row in clause_assignments:
        if row["applicability_role"] != ROLE_NOT_APPLICABLE:
            rows.append(_check("UNLOCATED_CLAUSE_SPATIALIZED", row["assignment_id"]))
    for row in assertion_assignments:
        if row["evidence_type"] != "REPORT_ASSERTION":
            rows.append(_check("ASSERTION_PROMOTED_TO_PRIMARY", row["assignment_id"]))
    return rows


def _check(code: str, detail: str) -> dict[str, str]:
    return {"check_code": code, "detail": detail}


def _issue_codes_by_asset(rows: list[dict[str, str]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        out[row["asset_id"]].append(row["issue_code"])
    return out


def _span_ids_by_owner(spans: list[dict[str, Any]]) -> dict[tuple[str, str], list[str]]:
    out: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in spans:
        out[(row["owner_type"], row["owner_id"])].append(row["span_id"])
    return out


def _counter_prefix(counter: Counter[str], prefix: str) -> str:
    return json.dumps(
        {key.split("|", 1)[1]: value for key, value in counter.items() if key.startswith(prefix)},
        ensure_ascii=False,
        sort_keys=True,
    )


def _first_date(rows: Any) -> str:
    dates = sorted(row["target_date"] for row in rows)
    return dates[0] if dates else ""


def _last_date(rows: Any) -> str:
    dates = sorted(row["target_date"] for row in rows)
    return dates[-1] if dates else ""


def _role_sequence(rows: list[dict[str, Any]]) -> str:
    sequence = []
    last = None
    for row in sorted(rows, key=lambda item: item["target_date"]):
        role = row["applicability_role"]
        if role != last:
            sequence.append(f"{row['target_date']}:{role}")
            last = role
    return " -> ".join(sequence)


def _primary_not_applicable_reason(row: dict[str, Any]) -> str:
    for reason in [
        "NOT_YET_AVAILABLE",
        "MISSING_AVAILABLE_TIME",
        "NO_EXPLICIT_SPATIAL_SCOPE",
        "INVALID_OR_MISSING_SPATIAL_SCOPE",
        "OBSERVED_NOT_FORWARD_ATTENTION",
        "BACKGROUND_OUTSIDE_LOCAL_CONTEXT",
        "SPATIAL_DISJOINT",
    ]:
        if reason in row["reason_codes"]:
            return reason
    return "NOT_APPLICABLE_OTHER"


def _first_reason(row: dict[str, Any], *reasons: str) -> str:
    for reason in reasons:
        if reason in row["reason_codes"]:
            return reason
    return "OTHER"


def _group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        out[str(row[key])].append(row)
    return out


def _method_version(
    plc_days: list[dict[str, Any]],
    source_freeze_manifest_hash: str,
) -> dict[str, Any]:
    return {
        "method_version": METHOD_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_freeze_dir": str(FREEZE),
        "source_freeze_manifest_hash": source_freeze_manifest_hash,
        "source_freeze_method_version": _read_json(FREEZE / "method_version.json"),
        "plc_date_count": len(plc_days),
        "cell_size_m": CELL_SIZE_M,
        "lookahead_m": LOOKAHEAD_M,
        "local_background_back_m": LOCAL_BACKGROUND_BACK_M,
        "parser_rerun": False,
        "llm_used": False,
        "applicability_scope": "daily_plc_date_x_frozen_primary_evidence",
        "git_commit_hash": _git(["rev-parse", "HEAD"]) or "NO_COMMITS",
        "working_tree_dirty": bool(_git(["status", "--short"])),
    }


def _write_report(
    *,
    method_version: dict[str, Any],
    freeze: dict[str, Any],
    plc_days: list[dict[str, Any]],
    primary_assignments: list[dict[str, Any]],
    assertion_assignments: list[dict[str, Any]],
    clause_assignments: list[dict[str, Any]],
    forecast_audit: list[dict[str, Any]],
    hard_checks: list[dict[str, Any]],
) -> None:
    role_counts = Counter(row["applicability_role"] for row in primary_assignments)
    time_blocked = sum(not row["time_valid"] for row in primary_assignments)
    spatial_blocked = sum(
        row["time_valid"] and not row["spatial_relevant"] for row in primary_assignments
    )
    ever_applicable = {
        row["evidence_id"]
        for row in primary_assignments
        if row["applicability_role"] != ROLE_NOT_APPLICABLE
    }
    invalid_transitions = sum(not row["transition_valid"] for row in forecast_audit)
    future_leakage = sum(
        row["applicability_role"] != ROLE_NOT_APPLICABLE
        and row["available_local_date"]
        and row["target_date"] < row["available_local_date"]
        for row in primary_assignments
    )
    unlocated_spatialized = sum(
        row["applicability_role"] != ROLE_NOT_APPLICABLE for row in clause_assignments
    )
    lines = [
        "# Stage 2D Applicability V2 Report",
        "",
        "Input geology is exclusively the Stage 2 V2 freeze candidate.",
        (
            "The run did not rerun the PDF parser, did not modify frozen evidence, "
            "and did not compute GRCI."
        ),
        "",
        "## PLC Dates",
        "",
        f"- actual PLC date count: {len(plc_days)}",
        f"- first date: {plc_days[0]['target_date'] if plc_days else ''}",
        f"- last date: {plc_days[-1]['target_date'] if plc_days else ''}",
        "",
        "## Frozen Inputs",
        "",
        f"- Documents: {len(freeze['documents'])}",
        f"- Primary Evidence: {len(freeze['evidence'])}",
        f"- ReportAssertion: {len(freeze['assertions'])}",
        f"- Unlocated Clause: {len(freeze['clauses'])}",
        f"- SourceSpan: {len(freeze['spans'])}",
        "",
        "## Assignments",
        "",
        f"- primary assignments: {len(primary_assignments)}",
        f"- assertion assignments: {len(assertion_assignments)}",
        f"- clause assignments: {len(clause_assignments)}",
        f"- evidence ever applicable: {len(ever_applicable)} / 659",
        *[f"- {role}: {count}" for role, count in sorted(role_counts.items())],
        "",
        "## Gates",
        "",
        f"- time gate blocked primary assignments: {time_blocked}",
        f"- spatial gate blocked primary assignments after time pass: {spatial_blocked}",
        f"- future leakage findings: {future_leakage}",
        f"- unlocated clauses spatialized: {unlocated_spatialized}",
        "",
        "## Forecast Role Transitions",
        "",
        f"- forecast segments audited: {len(forecast_audit)}",
        f"- invalid transition count: {invalid_transitions}",
        "",
        "## Hard Checks",
        "",
        f"- hard check findings: {len(hard_checks)}",
        "",
        "## Stage Boundary",
        "",
        (
            "The outputs are suitable for human review before ConstructionStateVersion if "
            "hard check findings remain zero and reviewers accept the deterministic scope rules."
        ),
        "This report does not declare Stage 3 started.",
        "",
        "## Method",
        "",
        f"- method_version: {method_version['method_version']}",
        f"- source_freeze_manifest_hash: {method_version['source_freeze_manifest_hash']}",
    ]
    (OUT / "applicability_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_hashes() -> None:
    lines = []
    for path in sorted(OUT.iterdir()):
        if path.is_file() and path.name != "file_hashes.sha256":
            lines.append(f"{_sha256(path)}  {path.name}")
    (OUT / "file_hashes.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_id(*parts: Any) -> str:
    seed = "|".join(str(part) for part in parts)
    return f"appv2_{hashlib.sha256(seed.encode()).hexdigest()[:24]}"


def _git(args: list[str]) -> str:
    import subprocess

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
