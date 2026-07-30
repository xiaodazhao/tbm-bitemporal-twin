"""Schema mapping helpers for geological evidence records."""

from __future__ import annotations

from typing import Any


def first_present(record: dict[str, Any], aliases: list[str]) -> Any:
    """Return the first non-empty record value for aliases."""

    lower = {str(key).strip().lower(): key for key in record}
    for alias in aliases:
        key = lower.get(alias.strip().lower())
        if key is not None and str(record[key]).strip() not in {"", "nan", "None"}:
            return record[key]
    return None
