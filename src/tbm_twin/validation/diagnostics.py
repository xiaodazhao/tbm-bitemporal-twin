"""Automatic diagnostics for Stage 1 validation runs."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, cast

import pandas as pd

from tbm_twin.channels.catalog import ChannelCatalog
from tbm_twin.process.models import ExcavationEpisode, OperationPhase, PhaseInterval
from tbm_twin.timeseries.models import PLCQualityReport
from tbm_twin.trajectory.models import SpatialFootprint
from tbm_twin.validation.models import ValidationConfig


def build_channel_audit(
    raw_frame: pd.DataFrame,
    catalog: ChannelCatalog,
) -> list[dict[str, Any]]:
    """Audit all canonical channels against one raw PLC dataframe."""

    raw_columns = [str(column) for column in raw_frame.columns]
    matches_by_canonical: dict[str, list[dict[str, Any]]] = {}
    for raw_name in raw_columns:
        match = catalog.resolve(raw_name)
        if match.canonical_name is None:
            continue
        matches_by_canonical.setdefault(match.canonical_name, []).append(
            {
                "raw_name": raw_name,
                "match_method": match.method.value,
                "warnings": match.warnings,
            }
        )

    selected = catalog.resolve_columns(raw_columns)
    rows: list[dict[str, Any]] = []
    for definition in catalog.channels:
        selected_match = selected.get(definition.canonical_name)
        candidates = matches_by_canonical.get(definition.canonical_name, [])
        selected_raw_name = selected_match.raw_name if selected_match else None
        series = (
            raw_frame[selected_raw_name]
            if selected_raw_name is not None and selected_raw_name in raw_frame.columns
            else pd.Series(dtype=object)
        )
        numeric = pd.to_numeric(series, errors="coerce")
        warnings = list(selected_match.warnings if selected_match else [])
        if len(candidates) > 1:
            warnings.append("multiple_explicit_candidates; selected by catalog match priority")
        if definition.canonical_name == "shield_head_chainage":
            _audit_chainage_anchor(raw_columns, selected_raw_name, warnings)
        rows.append(
            {
                "canonical_name": definition.canonical_name,
                "matched_raw_column": selected_raw_name,
                "match_method": selected_match.method.value if selected_match else "unmatched",
                "candidate_raw_columns": [candidate["raw_name"] for candidate in candidates],
                "selection_reason": _selection_reason(
                    definition.canonical_name,
                    selected_raw_name,
                    candidates,
                ),
                "required": definition.required,
                "usage_level": definition.usage_level.value,
                "unit": definition.unit,
                "unit_verified": definition.unit_verified,
                "dtype": str(series.dtype),
                "non_null_count": int(series.notna().sum()) if len(series) else 0,
                "missing_rate": float(series.isna().mean()) if len(series) else 1.0,
                "numeric_min": _safe_float(numeric.min()) if numeric.notna().any() else None,
                "numeric_max": _safe_float(numeric.max()) if numeric.notna().any() else None,
                "unique_count": int(series.nunique(dropna=True)) if len(series) else 0,
                "warnings": sorted(set(warnings)),
            }
        )
    return rows


def build_phase_intervals(labeled_frame: pd.DataFrame) -> list[PhaseInterval]:
    """Build phase intervals over all labeled observations."""

    if labeled_frame.empty:
        return []
    intervals: list[PhaseInterval] = []
    frame = labeled_frame.sort_values(["timestamp", "source_row_number"]).reset_index(drop=True)
    groups = (frame["operation_phase"] != frame["operation_phase"].shift()).cumsum()
    for _, segment in frame.groupby(groups):
        start = _to_datetime(segment["timestamp"].iloc[0])
        end = _to_datetime(segment["timestamp"].iloc[-1])
        reasons = sorted(
            {
                reason
                for item in segment.get("phase_reason_codes", pd.Series(dtype=object)).to_list()
                for reason in (item if isinstance(item, list) else [str(item)])
            }
        )
        intervals.append(
            PhaseInterval(
                phase=OperationPhase(str(segment["operation_phase"].iloc[0])),
                valid_start=start,
                valid_end=end,
                duration_seconds=max((end - start).total_seconds(), 0.0),
                observation_refs=segment["observation_id"].astype(str).to_list(),
                reason_codes=reasons,
            )
        )
    return intervals


def build_automatic_diagnostics(
    *,
    date: str,
    raw_frame: pd.DataFrame,
    normalized_frame: pd.DataFrame,
    labeled_frame: pd.DataFrame,
    quality_report: PLCQualityReport,
    phase_intervals: list[PhaseInterval],
    episodes: list[ExcavationEpisode],
    footprints: list[SpatialFootprint],
    config: ValidationConfig,
) -> dict[str, Any]:
    """Compute validation diagnostics for one date."""

    chainage = pd.to_numeric(normalized_frame["shield_head_chainage"], errors="coerce")
    timestamps = pd.to_datetime(normalized_frame["timestamp"], utc=True, errors="coerce")
    diffs = timestamps.sort_values().diff().dt.total_seconds().dropna()
    positive_diffs = diffs[diffs > 0]
    chainage_diffs = chainage.dropna().diff().dropna()
    phase_counts = labeled_frame["operation_phase"].value_counts().to_dict()
    phase_durations = _phase_durations(phase_intervals)
    episode_core_durations = [episode.core_excavation_duration_seconds for episode in episodes]
    episode_context_durations = [episode.context_duration_seconds for episode in episodes]

    diagnostics = {
        "date": date,
        "data_scale": {
            "raw_row_count": len(raw_frame),
            "normalized_row_count": len(normalized_frame),
            "valid_timestamp_count": int(timestamps.notna().sum()),
            "valid_chainage_count": int(chainage.notna().sum()),
            "time_span_seconds": _span_seconds(timestamps),
            "chainage_start_raw": _first_float(chainage),
            "chainage_end_raw": _last_float(chainage),
            "raw_chainage_difference": _diff_first_last(chainage),
        },
        "time": {
            "duplicate_timestamp_count": quality_report.time.duplicate_timestamp_count,
            "non_monotonic_timestamp_count": quality_report.time.non_monotonic_count,
            "median_sampling_interval_seconds": quality_report.time.sample_interval_sec_median,
            "p95_sampling_interval_seconds": quality_report.time.sample_interval_sec_p95,
            "data_gap_count": quality_report.time.large_gap_count,
            "largest_data_gap_seconds": _safe_float(positive_diffs.max())
            if not positive_diffs.empty
            else None,
            "timezone_handling": (
                "normalized metadata records source_timezone, canonical_timezone, "
                "timezone_confidence, timezone_basis, and timezone_warnings"
            ),
            "cross_midnight": _cross_midnight(timestamps),
        },
        "chainage": {
            "missing_chainage_rate": float(chainage.isna().mean()) if len(chainage) else 1.0,
            "negative_chainage_step_count": int((chainage_diffs < 0).sum()),
            "small_reverse_step_count": int(
                (
                    (chainage_diffs < -config.small_reverse_tolerance_m)
                    & (chainage_diffs >= -config.large_reverse_threshold_m)
                ).sum()
            ),
            "large_reverse_step_count": int(
                (chainage_diffs < -config.large_reverse_threshold_m).sum()
            ),
            "large_jump_count": int((chainage_diffs.abs() > config.large_jump_threshold_m).sum()),
            "static_chainage_ratio": _safe_float((chainage_diffs.abs() <= 1e-9).mean())
            if not chainage_diffs.empty
            else None,
            "minimum_chainage": _safe_float(chainage.min()) if chainage.notna().any() else None,
            "maximum_chainage": _safe_float(chainage.max()) if chainage.notna().any() else None,
        },
        "phase": {
            "phase_sample_counts": {str(key): int(value) for key, value in phase_counts.items()},
            "phase_duration_seconds": phase_durations,
            "phase_duration_ratios": _duration_ratios(phase_durations),
            "unknown_ratio": _phase_ratio(labeled_frame, OperationPhase.UNKNOWN),
            "data_gap_ratio": _phase_ratio(labeled_frame, OperationPhase.DATA_GAP),
            "phase_transition_count": max(len(phase_intervals) - 1, 0),
            "rapid_phase_flip_count": sum(
                interval.duration_seconds <= config.rapid_phase_flip_seconds
                for interval in phase_intervals
            ),
        },
        "episode": {
            "episode_count": len(episodes),
            "total_episode_duration_seconds": sum(episode_core_durations),
            "median_episode_duration_seconds": _median(episode_core_durations),
            "minimum_episode_duration_seconds": min(episode_core_durations)
            if episode_core_durations
            else None,
            "maximum_episode_duration_seconds": max(episode_core_durations)
            if episode_core_durations
            else None,
            "total_context_duration_seconds": sum(episode_context_durations),
            "median_context_duration_seconds": _median(episode_context_durations),
            "boundary_status_distribution": _count_values(
                episode.boundary_status.value for episode in episodes
            ),
            "quality_distribution": _count_values(episode.quality_grade for episode in episodes),
            "quality_reason_code_distribution": _count_values(
                reason for episode in episodes for reason in episode.quality_reason_codes
            ),
            "short_episode_count": sum(
                duration < config.short_episode_seconds for duration in episode_core_durations
            ),
            "episode_observation_count": [
                len(episode.core_observation_refs) for episode in episodes
            ],
            "episode_context_observation_count": [
                len(episode.observation_refs) for episode in episodes
            ],
            "episode_gap_crossing_count": sum(
                _contains_phase(ep, OperationPhase.DATA_GAP) for ep in episodes
            ),
            "episode_long_idle_crossing_count": sum(
                _contains_long_idle(ep, config.max_short_idle_seconds) for ep in episodes
            ),
        },
        "footprint": {
            "footprint_consistency_distribution": _count_values(
                footprint.consistency_status.value for footprint in footprints
            ),
            "footprint_quality_distribution": _count_values(
                footprint.quality_grade for footprint in footprints
            ),
            "estimated_advance_distribution": _numeric_distribution(
                footprint.estimated_advance_m
                for footprint in footprints
                if footprint.estimated_advance_m is not None
            ),
            "inconsistent_count": sum(
                footprint.consistency_status.value == "INCONSISTENT" for footprint in footprints
            ),
            "insufficient_count": sum(
                footprint.consistency_status.value == "INSUFFICIENT" for footprint in footprints
            ),
            "negative_advance_count": sum(
                footprint.estimated_advance_m is not None and footprint.estimated_advance_m < 0
                for footprint in footprints
            ),
            "implausible_advance_count": sum(
                footprint.estimated_advance_m is not None
                and footprint.estimated_advance_m > config.implausible_advance_m
                for footprint in footprints
            ),
            "zero_advance_flag_count": sum(
                "ZERO_ADVANCE_DURING_EXCAVATION" in footprint.quality_flags
                for footprint in footprints
            ),
            "precise_advance_suppressed_count": sum(
                footprint.consistency_status.value in {"INCONSISTENT", "INSUFFICIENT"}
                and footprint.estimated_advance_m is None
                for footprint in footprints
            ),
        },
    }
    return diagnostics


def _audit_chainage_anchor(
    raw_columns: list[str], raw_name: str | None, warnings: list[str]
) -> None:
    forbidden_candidates = ["导向盾中里程", "导向盾尾里程", "日进尺", "开累进尺"]
    present_forbidden = [
        candidate for candidate in forbidden_candidates if candidate in raw_columns
    ]
    if raw_name == "导向盾首里程":
        warnings.append("primary_anchor_selected:导向盾首里程")
    elif raw_name is not None:
        warnings.append(f"primary_anchor_selected:{raw_name}; expected 导向盾首里程 when present")
    if present_forbidden:
        warnings.append(f"nearby_non_anchor_columns_present:{','.join(present_forbidden)}")


def _selection_reason(
    canonical_name: str,
    raw_name: str | None,
    candidates: list[dict[str, Any]],
) -> str:
    if raw_name is None:
        return "no catalog match"
    if canonical_name == "shield_head_chainage" and raw_name == "导向盾首里程":
        return "selected explicit shield-head chainage alias"
    if len(candidates) > 1:
        return "selected by exact/normalized/alias priority"
    return "single explicit catalog match"


def _phase_durations(intervals: list[PhaseInterval]) -> dict[str, float]:
    durations: dict[str, float] = {}
    for interval in intervals:
        durations[interval.phase.value] = (
            durations.get(interval.phase.value, 0.0) + interval.duration_seconds
        )
    return durations


def _duration_ratios(durations: dict[str, float]) -> dict[str, float]:
    total = sum(durations.values())
    if total <= 0:
        return {key: 0.0 for key in durations}
    return {key: value / total for key, value in durations.items()}


def _phase_ratio(frame: pd.DataFrame, phase: OperationPhase) -> float:
    if frame.empty:
        return 0.0
    return float(frame["operation_phase"].eq(phase.value).mean())


def _contains_phase(episode: ExcavationEpisode, phase: OperationPhase) -> bool:
    return any(interval.phase == phase for interval in episode.phase_sequence)


def _contains_long_idle(episode: ExcavationEpisode, threshold_seconds: float) -> bool:
    return any(
        interval.phase == OperationPhase.IDLE and interval.duration_seconds > threshold_seconds
        for interval in episode.phase_sequence
    )


def _count_values(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value)
        counts[text] = counts.get(text, 0) + 1
    return counts


def _numeric_distribution(values: Any) -> dict[str, float | None]:
    numbers = [
        float(value) for value in values if value is not None and math.isfinite(float(value))
    ]
    if not numbers:
        return {"min": None, "median": None, "max": None}
    series = pd.Series(numbers)
    return {
        "min": _safe_float(series.min()),
        "median": _safe_float(series.median()),
        "max": _safe_float(series.max()),
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return _safe_float(pd.Series(values).median())


def _span_seconds(timestamps: pd.Series) -> float | None:
    valid = timestamps.dropna()
    if valid.empty:
        return None
    return _safe_float((valid.max() - valid.min()).total_seconds())


def _cross_midnight(timestamps: pd.Series) -> bool:
    valid = timestamps.dropna()
    if valid.empty:
        return False
    return bool(valid.min().date() != valid.max().date())


def _diff_first_last(series: pd.Series) -> float | None:
    valid = pd.to_numeric(series, errors="coerce").dropna()
    if valid.empty:
        return None
    return _safe_float(valid.iloc[-1] - valid.iloc[0])


def _first_float(series: pd.Series) -> float | None:
    valid = pd.to_numeric(series, errors="coerce").dropna()
    return _safe_float(valid.iloc[0]) if not valid.empty else None


def _last_float(series: pd.Series) -> float | None:
    valid = pd.to_numeric(series, errors="coerce").dropna()
    return _safe_float(valid.iloc[-1]) if not valid.empty else None


def _safe_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(str(value))
    return number if math.isfinite(number) else None


def _to_datetime(value: object) -> datetime:
    timestamp = pd.Timestamp(value)
    py_value = cast(datetime, timestamp.to_pydatetime())
    if py_value.tzinfo is None:
        msg = "Validation timestamps must be timezone-aware."
        raise ValueError(msg)
    return py_value
