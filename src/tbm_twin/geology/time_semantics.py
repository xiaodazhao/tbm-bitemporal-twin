"""Temporal parsing for geological evidence."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd

from tbm_twin.evidence.models import TemporalValue, TemporalValueConfidence


def parse_temporal_value(
    value: object,
    *,
    source_timezone: str = "Asia/Shanghai",
    confidence: TemporalValueConfidence = TemporalValueConfidence.DERIVED,
    basis: str = "explicit_field",
) -> TemporalValue:
    """Parse a temporal value without fabricating missing historical availability."""

    if value is None or str(value).strip() == "" or str(value).lower() == "nan":
        return TemporalValue(
            value=None, confidence=TemporalValueConfidence.UNKNOWN, basis="UNKNOWN"
        )
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return TemporalValue(
            value=None, confidence=TemporalValueConfidence.UNKNOWN, basis="parse_failed"
        )
    timestamp = pd.Timestamp(timestamp)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(ZoneInfo(source_timezone))
    return TemporalValue(
        value=timestamp.tz_convert("UTC").to_pydatetime(),
        confidence=confidence,
        basis=basis,
    )
