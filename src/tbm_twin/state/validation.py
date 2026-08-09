"""Validation helpers for Stage 3A state builds."""

from __future__ import annotations

from collections import Counter
from typing import Any


def hard_check_rows(checks: dict[str, bool | tuple[bool, str]]) -> list[dict[str, str]]:
    """Return failed hard-check rows."""

    rows = []
    for name, value in checks.items():
        if isinstance(value, tuple):
            passed, details = value
        else:
            passed, details = value, ""
        if not passed:
            rows.append({"check_name": name, "status": "FAIL", "details": details})
    return rows


def duplicate_ids(*groups: list[str]) -> list[str]:
    """Return duplicated IDs across groups."""

    counter: Counter[str] = Counter()
    for group in groups:
        counter.update(group)
    return sorted([item for item, count in counter.items() if count > 1])


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    """Count rows by a key."""

    return dict(sorted(Counter(str(row.get(key, "")) for row in rows).items()))
