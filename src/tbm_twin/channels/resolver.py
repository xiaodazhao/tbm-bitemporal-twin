"""Column matching helpers for PLC channel catalogs."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class MatchMethod(StrEnum):
    """Column resolution method."""

    EXACT = "exact"
    NORMALIZED_EXACT = "normalized_exact"
    ALIAS = "alias"
    UNMATCHED = "unmatched"


class ChannelMatch(BaseModel):
    """Resolution result for a raw column."""

    model_config = ConfigDict(frozen=True)

    raw_name: str
    canonical_name: str | None
    method: MatchMethod
    warnings: list[str]


def normalize_header(value: str) -> str:
    """Normalize case and whitespace for exact matching."""

    return re.sub(r"\s+", "", value).lower()
