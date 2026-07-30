"""Quality diagnostics for normalized PLC observations."""

from __future__ import annotations

import math

import pandas as pd

from tbm_twin.channels.catalog import ChannelCatalog
from tbm_twin.channels.models import ChannelUsageLevel
from tbm_twin.timeseries.models import (
    ChainageDiagnostics,
    ChannelDiagnostic,
    PLCQualityGrade,
    PLCQualityReport,
    TimeDiagnostics,
)

QUALITY_VERSION = "plc_quality_v1"
REVERSE_TOLERANCE_M = 0.01
LARGE_JUMP_THRESHOLD_M = 5.0


def _finite_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(str(value))
    return number if math.isfinite(number) else None


def _quantile_seconds(diffs: pd.Series, q: float) -> float | None:
    values = diffs[(diffs > 0) & diffs.notna()]
    if values.empty:
        return None
    return _finite_float(values.quantile(q))


def evaluate_plc_quality(
    *,
    asset_id: str,
    raw_frame: pd.DataFrame,
    normalized_frame: pd.DataFrame,
    catalog: ChannelCatalog,
    raw_columns_by_canonical: dict[str, str],
    parse_failed_count: int,
) -> PLCQualityReport:
    """Evaluate PLC quality without making geological conclusions."""

    reason_codes: list[str] = []
    warnings: list[str] = []

    timestamp_exists = "timestamp" in raw_columns_by_canonical
    if not timestamp_exists:
        reason_codes.append("TIME_FIELD_MISSING")
        warnings.append("Timestamp channel is missing.")
    if parse_failed_count:
        reason_codes.append("TIME_PARSE_FAILED")
        warnings.append(f"{parse_failed_count} rows failed timestamp parsing.")

    raw_time = (
        normalized_frame["timestamp"]
        if "timestamp" in normalized_frame
        else pd.Series(dtype="datetime64[ns, UTC]")
    )
    sorted_time = raw_time.dropna().sort_values()
    duplicate_count = int(raw_time.duplicated(keep=False).sum()) if not raw_time.empty else 0
    if duplicate_count:
        reason_codes.append("DUPLICATE_TIMESTAMP")
    original_diffs = raw_time.dropna().diff().dt.total_seconds()
    non_monotonic_count = int((original_diffs < 0).sum()) if not original_diffs.empty else 0
    if non_monotonic_count:
        reason_codes.append("TIME_NON_MONOTONIC")
    sorted_diffs = sorted_time.diff().dt.total_seconds().dropna()
    median_interval = _quantile_seconds(sorted_diffs, 0.5)
    p95_interval = _quantile_seconds(sorted_diffs, 0.95)
    positive_sorted_diffs = sorted_diffs[(sorted_diffs > 0) & sorted_diffs.notna()]
    large_gap_threshold = None
    if median_interval:
        large_gap_threshold = (
            max(5.0 * median_interval, 300.0) if len(positive_sorted_diffs) >= 3 else 300.0
        )
    large_gap_count = (
        int((sorted_diffs > large_gap_threshold).sum()) if large_gap_threshold is not None else 0
    )
    if large_gap_count:
        reason_codes.append("LARGE_TIME_GAP")

    chainage_exists = "shield_head_chainage" in raw_columns_by_canonical
    chainage = pd.to_numeric(
        normalized_frame.get("shield_head_chainage", pd.Series(dtype=float)),
        errors="coerce",
    )
    chainage_missing = int(chainage.isna().sum())
    if not chainage_exists:
        reason_codes.append("CHAINAGE_FIELD_MISSING")
        warnings.append("Shield-head chainage channel is missing.")
    diffs = chainage.dropna().diff().dropna()
    reverse_count = int((diffs < -REVERSE_TOLERANCE_M).sum()) if not diffs.empty else 0
    large_jump_count = int((diffs.abs() > LARGE_JUMP_THRESHOLD_M).sum()) if not diffs.empty else 0
    static_ratio = _finite_float((diffs.abs() <= 1e-6).mean()) if not diffs.empty else None
    if reverse_count:
        reason_codes.append("CHAINAGE_REVERSE")
    if large_jump_count:
        reason_codes.append("CHAINAGE_LARGE_JUMP")

    channel_diagnostics: list[ChannelDiagnostic] = []
    for definition in catalog.channels:
        series = normalized_frame.get(definition.canonical_name, pd.Series(dtype=object))
        missing_rate = float(series.isna().mean()) if len(series) else 1.0
        channel_warnings: list[str] = []
        if definition.required and definition.canonical_name not in raw_columns_by_canonical:
            channel_warnings.append("required_channel_missing")
            reason_codes.append(f"REQUIRED_CHANNEL_MISSING:{definition.canonical_name}")
        if (
            definition.usage_level in {ChannelUsageLevel.PRIMARY, ChannelUsageLevel.SUPPORTING}
            and not definition.unit_verified
        ):
            channel_warnings.append("unit_unverified")
            reason_codes.append(f"UNIT_UNVERIFIED:{definition.canonical_name}")
        numeric = pd.to_numeric(series, errors="coerce")
        if definition.valid_min is not None and bool((numeric < definition.valid_min).any()):
            channel_warnings.append("below_valid_min")
            reason_codes.append(f"VALUE_BELOW_MIN:{definition.canonical_name}")
        if definition.valid_max is not None and bool((numeric > definition.valid_max).any()):
            channel_warnings.append("above_valid_max")
            reason_codes.append(f"VALUE_ABOVE_MAX:{definition.canonical_name}")
        if definition.usage_level == ChannelUsageLevel.PRIMARY and missing_rate > 0.8:
            channel_warnings.append("primary_channel_high_missing_rate")
            reason_codes.append(f"PRIMARY_HIGH_MISSING:{definition.canonical_name}")
        channel_diagnostics.append(
            ChannelDiagnostic(
                canonical_name=definition.canonical_name,
                raw_name=raw_columns_by_canonical.get(definition.canonical_name),
                missing_rate=missing_rate,
                unit=definition.unit,
                unit_verified=definition.unit_verified,
                usage_level=definition.usage_level.value,
                warnings=channel_warnings,
            )
        )

    unique_reasons = sorted(set(reason_codes))
    grade = _grade_from_reasons(unique_reasons)
    return PLCQualityReport(
        asset_id=asset_id,
        catalog_version=catalog.catalog_version,
        quality_version=QUALITY_VERSION,
        row_count_raw=len(raw_frame),
        row_count_normalized=len(normalized_frame),
        grade=grade,
        reason_codes=unique_reasons,
        warnings=sorted(set(warnings)),
        time=TimeDiagnostics(
            missing_field=not timestamp_exists,
            parse_failed_count=parse_failed_count,
            duplicate_timestamp_count=duplicate_count,
            non_monotonic_count=non_monotonic_count,
            sample_interval_sec_median=median_interval,
            sample_interval_sec_p95=p95_interval,
            large_gap_count=large_gap_count,
            large_gap_threshold_sec=large_gap_threshold,
        ),
        chainage=ChainageDiagnostics(
            missing_field=not chainage_exists,
            missing_count=chainage_missing,
            reverse_count=reverse_count,
            large_jump_count=large_jump_count,
            static_ratio=static_ratio,
            reverse_tolerance_m=REVERSE_TOLERANCE_M,
            large_jump_threshold_m=LARGE_JUMP_THRESHOLD_M,
        ),
        channels=channel_diagnostics,
    )


def _grade_from_reasons(reasons: list[str]) -> PLCQualityGrade:
    hard = {
        "TIME_FIELD_MISSING",
        "CHAINAGE_FIELD_MISSING",
    }
    serious_prefixes = ("PRIMARY_HIGH_MISSING:",)
    if any(reason in hard for reason in reasons):
        return PLCQualityGrade.D
    if "CHAINAGE_LARGE_JUMP" in reasons or any(
        reason.startswith(serious_prefixes) for reason in reasons
    ):
        return PLCQualityGrade.C
    if {
        "TIME_PARSE_FAILED",
        "DUPLICATE_TIMESTAMP",
        "TIME_NON_MONOTONIC",
        "LARGE_TIME_GAP",
        "CHAINAGE_REVERSE",
    } & set(reasons):
        return PLCQualityGrade.B
    return PLCQualityGrade.A
