"""Build ExcavationEpisode objects from weak operation phases."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import cast

import pandas as pd

from tbm_twin.process.models import (
    EpisodeBoundaryStatus,
    ExcavationEpisode,
    OperationPhase,
    PhaseInterval,
)
from tbm_twin.process.weak_labels import label_operation_phases

EPISODE_METHOD_VERSION = "excavation_episode_builder_v1"


@dataclass(frozen=True)
class EpisodeBuilderConfig:
    """Centralized thresholds for episode segmentation."""

    max_short_idle_seconds: float = 120.0
    max_edge_phase_seconds: float = 180.0
    min_core_observation_count_for_a: int = 3
    min_core_duration_seconds_for_a: float = 1.0
    min_temporal_coverage_ratio_for_a: float = 0.8
    chainage_reverse_tolerance_m: float = 0.01
    chainage_jump_threshold_m: float = 5.0


def build_excavation_episodes(
    normalized_frame: pd.DataFrame,
    config: EpisodeBuilderConfig | None = None,
) -> list[ExcavationEpisode]:
    """Build stable excavation episodes from normalized observations."""

    config = config or EpisodeBuilderConfig()
    labeled = (
        normalized_frame
        if "operation_phase" in normalized_frame.columns
        else label_operation_phases(normalized_frame)
    )
    labeled = labeled.sort_values(["timestamp", "source_row_number"]).reset_index(drop=True)
    if labeled.empty:
        return []

    groups = _candidate_groups(labeled, config)
    episodes: list[ExcavationEpisode] = []
    for group in groups:
        part = labeled.iloc[group].copy()
        if not bool(part["operation_phase"].eq(OperationPhase.EXCAVATING.value).any()):
            continue
        phase_intervals = _build_phase_intervals(part)
        core = part[part["operation_phase"].eq(OperationPhase.EXCAVATING.value)].copy()
        observation_refs = part["observation_id"].astype(str).to_list()
        core_observation_refs = core["observation_id"].astype(str).to_list()
        context_start = _to_datetime(part["timestamp"].iloc[0])
        context_end = _to_datetime(part["timestamp"].iloc[-1])
        excavation_start = _to_datetime(core["timestamp"].iloc[0])
        excavation_end = _to_datetime(core["timestamp"].iloc[-1])
        context_duration = max((context_end - context_start).total_seconds(), 0.0)
        core_duration = _phase_duration(phase_intervals, OperationPhase.EXCAVATING)
        interruption_count, interruption_duration = _interruption_metrics(
            phase_intervals,
            excavation_start,
            excavation_end,
        )
        core_span = max((excavation_end - excavation_start).total_seconds(), 0.0)
        coverage_ratio = core_duration / core_span if core_span > 0 else 1.0
        boundary_status = _boundary_status(labeled, group)
        quality_grade, reason_codes, assessed_flags = assess_episode_quality(
            part,
            core,
            boundary_status,
            core_duration,
            interruption_count,
            interruption_duration,
            coverage_ratio,
            config,
        )
        quality_flags = sorted(set([*_collect_quality_flags(part), *assessed_flags]))
        asset_ids = sorted(set(part["asset_id"].astype(str).to_list()))
        episode = ExcavationEpisode(
            episode_id=_stable_episode_id(
                asset_ids,
                excavation_start,
                excavation_end,
                core_observation_refs,
            ),
            asset_ids=asset_ids,
            context_start=context_start,
            context_end=context_end,
            excavation_start=excavation_start,
            excavation_end=excavation_end,
            context_duration_seconds=context_duration,
            core_excavation_duration_seconds=core_duration,
            interruption_duration_seconds=interruption_duration,
            excavating_segment_count=sum(
                interval.phase == OperationPhase.EXCAVATING for interval in phase_intervals
            ),
            temporal_coverage_ratio=coverage_ratio,
            boundary_status=boundary_status,
            actual_start_known=boundary_status
            not in {EpisodeBoundaryStatus.LEFT_CENSORED, EpisodeBoundaryStatus.BOTH_CENSORED},
            actual_end_known=boundary_status
            not in {EpisodeBoundaryStatus.RIGHT_CENSORED, EpisodeBoundaryStatus.BOTH_CENSORED},
            phase_sequence=phase_intervals,
            observation_refs=observation_refs,
            core_observation_refs=core_observation_refs,
            cross_midnight_observed=context_start.date() != context_end.date(),
            quality_grade=quality_grade,
            quality_reason_codes=reason_codes,
            quality_flags=quality_flags,
            method_version=EPISODE_METHOD_VERSION,
        )
        episodes.append(episode)
    return episodes


def assess_episode_quality(
    context_rows: pd.DataFrame,
    core_rows: pd.DataFrame,
    boundary_status: EpisodeBoundaryStatus,
    core_duration_seconds: float,
    internal_interruption_count: int,
    internal_interruption_duration_seconds: float,
    temporal_coverage_ratio: float,
    config: EpisodeBuilderConfig,
    *,
    footprint_status: str | None = None,
    zero_advance_conflict: bool = False,
) -> tuple[str, list[str], list[str]]:
    """Assess Episode quality from episode-local evidence instead of daily PLC grade."""

    reason_codes: set[str] = set()
    flags: set[str] = set(_collect_quality_flags(context_rows))
    if boundary_status != EpisodeBoundaryStatus.COMPLETE:
        reason_codes.add(f"BOUNDARY_{boundary_status.value}")
        flags.add(boundary_status.value.lower())
    if len(core_rows) < config.min_core_observation_count_for_a:
        reason_codes.add("LOW_CORE_OBSERVATION_COUNT")
    if core_duration_seconds < config.min_core_duration_seconds_for_a:
        reason_codes.add("LOW_CORE_DURATION")
    unknown_ratio = (
        float(context_rows["operation_phase"].eq(OperationPhase.UNKNOWN.value).mean())
        if len(context_rows)
        else 1.0
    )
    if unknown_ratio > 0.1:
        reason_codes.add("HIGH_UNKNOWN_RATIO")
    if internal_interruption_count:
        reason_codes.add("INTERNAL_INTERRUPTION_PRESENT")
    if internal_interruption_duration_seconds > config.max_short_idle_seconds:
        reason_codes.add("LONG_INTERNAL_INTERRUPTION")
    if temporal_coverage_ratio < config.min_temporal_coverage_ratio_for_a:
        reason_codes.add("LOW_TEMPORAL_COVERAGE")

    chainage = pd.to_numeric(
        core_rows.get("shield_head_chainage", pd.Series(dtype=float)),
        errors="coerce",
    )
    if len(chainage):
        missing_rate = float(chainage.isna().mean())
        diffs = chainage.dropna().diff().dropna()
        if missing_rate > 0:
            reason_codes.add("CORE_CHAINAGE_MISSING")
        if bool((diffs < -config.chainage_reverse_tolerance_m).any()):
            reason_codes.add("CORE_CHAINAGE_REVERSE")
        if bool((diffs.abs() > config.chainage_jump_threshold_m).any()):
            reason_codes.add("CORE_CHAINAGE_JUMP")
    else:
        reason_codes.add("CORE_CHAINAGE_MISSING")

    if footprint_status in {"INCONSISTENT", "INSUFFICIENT"}:
        reason_codes.add(f"FOOTPRINT_{footprint_status}")
    if zero_advance_conflict:
        reason_codes.add("ZERO_ADVANCE_DURING_EXCAVATION")
        flags.add("zero_advance_review_required")

    serious = {
        "CORE_CHAINAGE_JUMP",
        "FOOTPRINT_INCONSISTENT",
        "FOOTPRINT_INSUFFICIENT",
    }
    if reason_codes & serious:
        grade = "C"
    elif reason_codes:
        grade = "B"
    else:
        grade = "A"
    return grade, sorted(reason_codes), sorted(flags)


def finalize_episode_quality(
    episode: ExcavationEpisode,
    labeled_frame: pd.DataFrame,
    *,
    footprint_status: str | None,
    footprint_quality_flags: list[str],
    config: EpisodeBuilderConfig | None = None,
) -> ExcavationEpisode:
    """Return an episode with footprint-aware quality fields."""

    config = config or EpisodeBuilderConfig()
    by_obs = labeled_frame.set_index("observation_id", drop=False)
    context_refs = [ref for ref in episode.observation_refs if ref in by_obs.index]
    core_refs = [ref for ref in episode.core_observation_refs if ref in by_obs.index]
    context_rows = by_obs.loc[context_refs].copy()
    core_rows = by_obs.loc[core_refs].copy()
    interruption_count = sum(
        interval.phase != OperationPhase.EXCAVATING
        and interval.valid_end >= episode.excavation_start
        and interval.valid_start <= episode.excavation_end
        for interval in episode.phase_sequence
    )
    grade, reason_codes, assessed_flags = assess_episode_quality(
        context_rows,
        core_rows,
        episode.boundary_status,
        episode.core_excavation_duration_seconds,
        interruption_count,
        episode.interruption_duration_seconds,
        episode.temporal_coverage_ratio,
        config,
        footprint_status=footprint_status,
        zero_advance_conflict="ZERO_ADVANCE_DURING_EXCAVATION" in footprint_quality_flags,
    )
    return episode.model_copy(
        update={
            "quality_grade": grade,
            "quality_reason_codes": sorted(set([*episode.quality_reason_codes, *reason_codes])),
            "quality_flags": sorted(
                set([*episode.quality_flags, *assessed_flags, *footprint_quality_flags])
            ),
        }
    )


def _candidate_groups(labeled: pd.DataFrame, config: EpisodeBuilderConfig) -> list[list[int]]:
    groups: list[list[int]] = []
    current: list[int] = []
    idle_run: list[int] = []

    for idx, phase_text in enumerate(labeled["operation_phase"].astype(str).to_list()):
        phase = OperationPhase(phase_text)
        if phase == OperationPhase.DATA_GAP:
            _flush(groups, current)
            current = []
            idle_run = []
            continue
        if phase == OperationPhase.IDLE:
            idle_run.append(idx)
            if _duration(labeled, idle_run) <= config.max_short_idle_seconds:
                continue
            _flush(groups, current)
            current = []
            idle_run = []
            continue
        if idle_run:
            if _duration(labeled, idle_run) <= config.max_short_idle_seconds:
                current.extend(idle_run)
            else:
                _flush(groups, current)
                current = []
            idle_run = []
        current.append(idx)
    if idle_run and _duration(labeled, idle_run) <= config.max_short_idle_seconds:
        current.extend(idle_run)
    _flush(groups, current)
    return groups


def _flush(groups: list[list[int]], current: list[int]) -> None:
    if current:
        groups.append(list(dict.fromkeys(current)))


def _duration(frame: pd.DataFrame, indexes: list[int]) -> float:
    if len(indexes) < 2:
        return 0.0
    start = _to_datetime(frame["timestamp"].iloc[indexes[0]])
    end = _to_datetime(frame["timestamp"].iloc[indexes[-1]])
    return max((end - start).total_seconds(), 0.0)


def _boundary_status(labeled: pd.DataFrame, group: list[int]) -> EpisodeBoundaryStatus:
    left = (
        bool(group)
        and group[0] == 0
        and str(labeled["operation_phase"].iloc[0]) == OperationPhase.EXCAVATING.value
    )
    right = (
        bool(group)
        and group[-1] == len(labeled) - 1
        and str(labeled["operation_phase"].iloc[-1]) == OperationPhase.EXCAVATING.value
    )
    if left and right:
        return EpisodeBoundaryStatus.BOTH_CENSORED
    if left:
        return EpisodeBoundaryStatus.LEFT_CENSORED
    if right:
        return EpisodeBoundaryStatus.RIGHT_CENSORED
    return EpisodeBoundaryStatus.COMPLETE


def _build_phase_intervals(part: pd.DataFrame) -> list[PhaseInterval]:
    intervals: list[PhaseInterval] = []
    for _, segment in part.groupby(
        (part["operation_phase"] != part["operation_phase"].shift()).cumsum()
    ):
        start = _to_datetime(segment["timestamp"].iloc[0])
        end = _to_datetime(segment["timestamp"].iloc[-1])
        reasons = sorted(
            {
                reason
                for item in segment["phase_reason_codes"].to_list()
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


def _phase_duration(intervals: list[PhaseInterval], phase: OperationPhase) -> float:
    return sum(interval.duration_seconds for interval in intervals if interval.phase == phase)


def _interruption_metrics(
    intervals: list[PhaseInterval],
    excavation_start: datetime,
    excavation_end: datetime,
) -> tuple[int, float]:
    count = 0
    duration = 0.0
    for interval in intervals:
        if interval.phase == OperationPhase.EXCAVATING:
            continue
        if interval.valid_end < excavation_start or interval.valid_start > excavation_end:
            continue
        count += 1
        duration += interval.duration_seconds
    return count, duration


def _collect_quality_flags(part: pd.DataFrame) -> list[str]:
    flags: set[str] = set()
    if "quality_flags" not in part.columns:
        return []
    for item in part["quality_flags"].to_list():
        if isinstance(item, list):
            flags.update(str(flag) for flag in item)
        elif item:
            flags.add(str(item))
    return sorted(flags)


def _stable_episode_id(
    asset_ids: list[str],
    start: datetime,
    end: datetime,
    observation_refs: list[str],
) -> str:
    seed = "|".join([*asset_ids, start.isoformat(), end.isoformat(), *observation_refs]).encode(
        "utf-8"
    )
    return f"episode-{hashlib.sha256(seed).hexdigest()[:24]}"


def _to_datetime(value: object) -> datetime:
    timestamp = pd.Timestamp(value)
    py_value = cast(datetime, timestamp.to_pydatetime())
    if py_value.tzinfo is None:
        msg = "Episode timestamps must be timezone-aware."
        raise ValueError(msg)
    return py_value
