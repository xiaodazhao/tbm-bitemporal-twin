"""Stage 4A2 metric validation helpers."""

from __future__ import annotations

from typing import Any

from tbm_twin.metrics.validation import hard_check_row


def unique_id_check(rows: list[dict[str, Any]], key: str) -> bool:
    """Return true when all IDs are unique."""

    values = [str(row[key]) for row in rows]
    return len(values) == len(set(values))


__all__ = ["hard_check_row", "unique_id_check"]
