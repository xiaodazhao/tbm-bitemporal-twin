"""Temporal eligibility rules for Stage 3B revisions."""

from __future__ import annotations

from datetime import date
from typing import Any


def parse_local_date(value: Any) -> date | None:
    """Parse a local date string if present."""

    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def evaluate_temporal_eligibility(
    *,
    valid_date: date,
    observed_local_date: date | None,
    available_local_date: date | None,
    knowledge_cutoff_date: date,
) -> tuple[bool, list[str]]:
    """Evaluate whether evidence can revise a valid-date state."""

    if observed_local_date is None:
        return False, ["MISSING_OBSERVED_LOCAL_DATE"]
    if available_local_date is None:
        return False, ["MISSING_AVAILABLE_LOCAL_DATE"]
    if observed_local_date > valid_date:
        return False, ["OBSERVED_AFTER_STATE_VALID_DATE"]
    if available_local_date <= valid_date:
        return False, ["ALREADY_AVAILABLE_IN_INITIAL_STATE"]
    if available_local_date > knowledge_cutoff_date:
        return False, ["NOT_AVAILABLE_BY_KNOWLEDGE_CUTOFF"]
    return True, ["LATE_AVAILABLE_PRIMARY_EVIDENCE"]
