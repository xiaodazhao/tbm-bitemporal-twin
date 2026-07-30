"""Models for normalized PLC observations and quality reports."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict

NORMALIZED_COLUMNS = [
    "observation_id",
    "asset_id",
    "source_row_number",
    "timestamp",
    "shield_head_chainage",
    "daily_advance",
    "cumulative_advance",
    "cylinder_displacement",
    "excavation_state",
    "advance_speed",
    "set_advance_speed",
    "total_thrust",
    "cutterhead_torque",
    "cutterhead_rpm",
    "penetration",
    "quality_flags",
]


class PLCQualityGrade(StrEnum):
    """Explainable quality grades for PLC data."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"


class ChannelDiagnostic(BaseModel):
    """Diagnostics for one canonical channel."""

    model_config = ConfigDict(frozen=True)

    canonical_name: str
    raw_name: str | None
    missing_rate: float
    unit: str | None
    unit_verified: bool
    usage_level: str
    warnings: list[str]


class TimeDiagnostics(BaseModel):
    """Time quality diagnostics."""

    model_config = ConfigDict(frozen=True)

    missing_field: bool
    parse_failed_count: int
    duplicate_timestamp_count: int
    non_monotonic_count: int
    sample_interval_sec_median: float | None
    sample_interval_sec_p95: float | None
    large_gap_count: int
    large_gap_threshold_sec: float | None


class ChainageDiagnostics(BaseModel):
    """Shield-head chainage quality diagnostics."""

    model_config = ConfigDict(frozen=True)

    missing_field: bool
    missing_count: int
    reverse_count: int
    large_jump_count: int
    static_ratio: float | None
    reverse_tolerance_m: float
    large_jump_threshold_m: float


class PLCQualityReport(BaseModel):
    """Explainable PLC data quality report."""

    model_config = ConfigDict(frozen=True)

    asset_id: str
    catalog_version: str
    quality_version: str
    row_count_raw: int
    row_count_normalized: int
    grade: PLCQualityGrade
    reason_codes: list[str]
    warnings: list[str]
    time: TimeDiagnostics
    chainage: ChainageDiagnostics
    channels: list[ChannelDiagnostic]


class NormalizationMetadata(BaseModel):
    """Metadata written beside the normalized Parquet output."""

    model_config = ConfigDict(frozen=True)

    asset_id: str
    catalog_version: str
    normalization_version: str
    source_timezone: str | None
    canonical_timezone: str
    timezone_confidence: str
    timezone_basis: str
    timezone_warnings: list[str]
    row_count_raw: int
    row_count_normalized: int
    warning_count: int


class NormalizationResult(BaseModel):
    """Normalized PLC frame plus its diagnostics."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    frame: pd.DataFrame
    quality_report: PLCQualityReport
    metadata: NormalizationMetadata
    output_path: Path | None = None
