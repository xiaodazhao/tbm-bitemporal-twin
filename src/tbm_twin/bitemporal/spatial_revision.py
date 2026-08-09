"""Spatial and role eligibility for Stage 3B revisions."""

from __future__ import annotations

from typing import Any


def evidence_formal_id(evidence: dict[str, Any]) -> str:
    """Return the formal frozen Evidence ID used by Stage 3A."""

    return str(evidence.get("evidence_uid") or evidence["evidence_id"])


def evidence_source_span_ids(evidence: dict[str, Any]) -> list[str]:
    """Collect unique source span IDs from a frozen primary evidence row."""

    seen: set[str] = set()
    span_ids: list[str] = []
    for span in evidence.get("source_spans", []):
        span_id = str(span.get("span_id", ""))
        if span_id and span_id not in seen:
            seen.add(span_id)
            span_ids.append(span_id)
    for span_id in evidence.get("source_span_ids", []):
        text = str(span_id)
        if text and text not in seen:
            seen.add(text)
            span_ids.append(text)
    return span_ids


def evaluate_revision_role(
    *,
    cell_scope_role: str,
    epistemic_status: str,
) -> tuple[bool, str, list[str]]:
    """Evaluate role eligibility without changing frozen epistemic status."""

    if cell_scope_role == "DAILY_REVIEW_CELL":
        if epistemic_status in {"OBSERVED", "FORECAST"}:
            return True, "DAILY_REVIEW", ["REVISION_ROLE_FROM_DAILY_REVIEW_CELL"]
        if epistemic_status == "BACKGROUND":
            return False, "UNKNOWN", ["BACKGROUND_NOT_ALLOWED_FOR_DAILY_REVIEW"]
        return False, "UNKNOWN", ["UNKNOWN_EPISTEMIC_STATUS_NOT_REVISION_ELIGIBLE"]
    if cell_scope_role == "FORWARD_ATTENTION_CELL":
        if epistemic_status == "OBSERVED":
            return False, "UNKNOWN", ["OBSERVED_NOT_ALLOWED_FOR_FORWARD_ATTENTION"]
        if epistemic_status == "BACKGROUND":
            return False, "UNKNOWN", ["BACKGROUND_NOT_ALLOWED_FOR_FORWARD_ATTENTION"]
        if epistemic_status == "FORECAST":
            return True, "FORWARD_ATTENTION", ["REVISION_ROLE_FROM_FORWARD_ATTENTION_CELL"]
        return False, "UNKNOWN", ["UNKNOWN_EPISTEMIC_STATUS_NOT_REVISION_ELIGIBLE"]
    if cell_scope_role == "LOCAL_BACKGROUND_CELL":
        if epistemic_status in {"OBSERVED", "FORECAST", "BACKGROUND"}:
            return True, "LOCAL_BACKGROUND", ["REVISION_ROLE_FROM_LOCAL_BACKGROUND_CELL"]
        return False, "UNKNOWN", ["UNKNOWN_EPISTEMIC_STATUS_NOT_REVISION_ELIGIBLE"]
    return False, "UNKNOWN", ["UNKNOWN_CELL_SCOPE_ROLE"]


def evaluate_spatial_overlap(
    *,
    cell: dict[str, Any],
    evidence_scope: dict[str, Any],
) -> tuple[bool, dict[str, Any], list[str]]:
    """Evaluate POINT or INTERVAL overlap against the fixed Stage 3A cell."""

    kind = str(evidence_scope.get("kind", "UNKNOWN"))
    start = _float_or_none(evidence_scope.get("start_chainage"))
    end = _float_or_none(evidence_scope.get("end_chainage"))
    cell_start = float(cell["spatial_start"])
    cell_end = float(cell["spatial_end"])
    if start is None or end is None:
        return False, _empty_overlap(kind), ["MISSING_EVIDENCE_SPATIAL_SCOPE"]
    if kind == "POINT":
        if start != end:
            return False, _empty_overlap(kind), ["POINT_SCOPE_START_END_CONFLICT"]
        if cell_start < start <= cell_end:
            return (
                True,
                {
                    "cell_overlap_kind": "POINT",
                    "cell_overlap_start": start,
                    "cell_overlap_end": end,
                    "cell_overlap_length_m": 0.0,
                },
                ["POINT_MAPPED_TO_RIGHT_CLOSED_PREVIOUS_CELL"],
            )
        return False, _empty_overlap("POINT"), ["POINT_OUTSIDE_CELL"]
    if kind == "INTERVAL":
        if not start < end:
            return False, _empty_overlap(kind), ["INVALID_INTERVAL_SCOPE"]
        overlap_start = max(start, cell_start)
        overlap_end = min(end, cell_end)
        if overlap_start < overlap_end:
            return (
                True,
                {
                    "cell_overlap_kind": "INTERVAL",
                    "cell_overlap_start": overlap_start,
                    "cell_overlap_end": overlap_end,
                    "cell_overlap_length_m": round(overlap_end - overlap_start, 6),
                },
                ["INTERVAL_POSITIVE_CELL_OVERLAP"],
            )
        return False, _empty_overlap("INTERVAL"), ["INTERVAL_NO_POSITIVE_CELL_OVERLAP"]
    return False, _empty_overlap(kind), ["UNSUPPORTED_EVIDENCE_SPATIAL_KIND"]


def _empty_overlap(kind: str) -> dict[str, Any]:
    return {
        "cell_overlap_kind": kind,
        "cell_overlap_start": None,
        "cell_overlap_end": None,
        "cell_overlap_length_m": 0.0,
    }


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
