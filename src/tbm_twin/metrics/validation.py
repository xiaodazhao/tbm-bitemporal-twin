"""Validation helpers for Stage 4A1 outputs."""

from __future__ import annotations

from collections import Counter
from typing import Any


def hard_check_row(check_name: str, passed: bool, details: str) -> dict[str, str]:
    """Build one stable hard-check row."""

    return {
        "check_name": check_name,
        "status": "PASS" if passed else "FAIL",
        "details": details,
    }


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    """Count rows by one string key."""

    return dict(sorted(Counter(str(row.get(key)) for row in rows).items()))
