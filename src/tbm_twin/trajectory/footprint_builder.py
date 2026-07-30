"""Build simplified quality-aware spatial footprints for episodes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pandas as pd

from tbm_twin.process.models import ExcavationEpisode
from tbm_twin.trajectory.models import (
    ConsistencyCheckResult,
    ConsistencyStatus,
    SpatialFootprint,
)

FOOTPRINT_METHOD_VERSION = "spatial_footprint_quality_aware_v1"
REVERSE_TOLERANCE_M = 0.01
LARGE_JUMP_THRESHOLD_M = 5.0
SUPPORT_CONFLICT_TOLERANCE_M = 2.0
ZERO_ADVANCE_THRESHOLD_M = 0.01


@dataclass(frozen=True)
class FootprintBuilderConfig:
    """Centralized thresholds for spatial footprint diagnostics."""

    support_conflict_tolerance_m: float = SUPPORT_CONFLICT_TOLERANCE_M
    zero_advance_threshold_m: float = ZERO_ADVANCE_THRESHOLD_M


def build_spatial_footprints(
    normalized_frame: pd.DataFrame,
    episodes: list[ExcavationEpisode],
    config: FootprintBuilderConfig | None = None,
) -> list[SpatialFootprint]:
    """Estimate spatial footprints from shield-head chainage and supporting signals."""

    config = config or FootprintBuilderConfig()
    by_obs = normalized_frame.set_index("observation_id", drop=False)
    footprints: list[SpatialFootprint] = []
    for episode in episodes:
        refs = [ref for ref in episode.core_observation_refs if ref in by_obs.index]
        rows = by_obs.loc[refs].copy()
        footprints.append(_build_one(rows, episode, config))
    return footprints


def _build_one(
    rows: pd.DataFrame,
    episode: ExcavationEpisode,
    config: FootprintBuilderConfig,
) -> SpatialFootprint:
    flags: list[str] = []
    supporting_sources: list[str] = []
    checks: list[ConsistencyCheckResult] = []
    if rows.empty or "shield_head_chainage" not in rows.columns:
        flags.append("insufficient_chainage")
        return _footprint(
            episode=episode,
            start_chainage=None,
            end_chainage=None,
            estimated_advance_m=None,
            primary_source=None,
            supporting_sources=supporting_sources,
            checks=checks,
            primary_observation_count=0,
            status=ConsistencyStatus.INSUFFICIENT,
            uncertainty_m=None,
            quality_flags=flags,
        )

    chainage = pd.to_numeric(rows["shield_head_chainage"], errors="coerce").dropna()
    if len(chainage) < 2:
        flags.append("insufficient_chainage")
        return _footprint(
            episode=episode,
            start_chainage=float(chainage.iloc[0]) if len(chainage) == 1 else None,
            end_chainage=float(chainage.iloc[-1]) if len(chainage) == 1 else None,
            estimated_advance_m=None,
            primary_source="shield_head_chainage",
            supporting_sources=supporting_sources,
            checks=checks,
            primary_observation_count=len(chainage),
            status=ConsistencyStatus.INSUFFICIENT,
            uncertainty_m=None,
            quality_flags=flags,
        )

    start = float(chainage.iloc[0])
    end = float(chainage.iloc[-1])
    advance = end - start
    diffs = chainage.diff().dropna()
    reverse_count = int((diffs < -REVERSE_TOLERANCE_M).sum())
    large_jump_count = int((diffs.abs() > LARGE_JUMP_THRESHOLD_M).sum())
    if reverse_count:
        flags.append("chainage_reverse")
    if large_jump_count:
        flags.append("chainage_large_jump")
    if advance < -REVERSE_TOLERANCE_M or large_jump_count:
        return _footprint(
            episode=episode,
            start_chainage=start,
            end_chainage=end,
            estimated_advance_m=None,
            primary_source="shield_head_chainage",
            supporting_sources=supporting_sources,
            checks=checks,
            primary_observation_count=len(chainage),
            status=ConsistencyStatus.INCONSISTENT,
            uncertainty_m=None,
            quality_flags=flags,
        )

    conflicts = 0
    for column in ["daily_advance", "cumulative_advance", "cylinder_displacement"]:
        support_delta = _support_delta(rows, column)
        if support_delta is None:
            checks.append(
                ConsistencyCheckResult(
                    source=column,
                    performed=False,
                    reference_advance_m=advance,
                    support_advance_m=None,
                    tolerance_m=config.support_conflict_tolerance_m,
                    status="NOT_PERFORMED",
                    reason="insufficient_supporting_values",
                )
            )
            continue
        supporting_sources.append(column)
        consistent = abs(support_delta - advance) <= config.support_conflict_tolerance_m
        checks.append(
            ConsistencyCheckResult(
                source=column,
                performed=True,
                reference_advance_m=advance,
                support_advance_m=support_delta,
                tolerance_m=config.support_conflict_tolerance_m,
                status="CONSISTENT" if consistent else "CONFLICT",
                reason="within_tolerance" if consistent else "outside_tolerance",
            )
        )
        if not consistent:
            flags.append(f"support_conflict:{column}")
            conflicts += 1

    if conflicts and conflicts == len(supporting_sources):
        status = ConsistencyStatus.INCONSISTENT
        estimated = None
        uncertainty = None
    elif conflicts:
        status = ConsistencyStatus.PARTIALLY_CONSISTENT
        estimated = max(advance, 0.0)
        uncertainty = config.support_conflict_tolerance_m
    elif supporting_sources:
        status = ConsistencyStatus.MULTI_CHANNEL_CONSISTENT
        estimated = max(advance, 0.0)
        uncertainty = 0.5
    else:
        status = ConsistencyStatus.PRIMARY_CHANNEL_ONLY
        estimated = max(advance, 0.0)
        uncertainty = 1.0

    if estimated is not None and estimated <= config.zero_advance_threshold_m:
        flags.append("ZERO_ADVANCE_DURING_EXCAVATION")
        flags.extend(_zero_advance_reasons(rows))

    return _footprint(
        episode=episode,
        start_chainage=start,
        end_chainage=end,
        estimated_advance_m=estimated,
        primary_source="shield_head_chainage",
        supporting_sources=supporting_sources,
        checks=checks,
        primary_observation_count=len(chainage),
        status=status,
        uncertainty_m=uncertainty,
        quality_flags=flags,
    )


def _support_delta(rows: pd.DataFrame, column: str) -> float | None:
    if column not in rows.columns:
        return None
    series = pd.to_numeric(rows[column], errors="coerce").dropna()
    if len(series) < 2:
        return None
    return abs(float(series.iloc[-1] - series.iloc[0]))


def _zero_advance_reasons(rows: pd.DataFrame) -> list[str]:
    reasons: list[str] = []
    chainage = pd.to_numeric(rows["shield_head_chainage"], errors="coerce").dropna()
    if len(chainage) >= 2 and bool((chainage.diff().dropna().abs() <= 1e-9).all()):
        reasons.append("static_chainage_signal")
    if chainage.nunique(dropna=True) <= 1:
        reasons.append("insufficient_chainage_resolution")
    if len(rows) <= 3:
        reasons.append("phase_false_positive_candidate")
    reasons.append("episode_boundary_issue")
    return reasons


def _footprint(
    *,
    episode: ExcavationEpisode,
    start_chainage: float | None,
    end_chainage: float | None,
    estimated_advance_m: float | None,
    primary_source: str | None,
    supporting_sources: list[str],
    checks: list[ConsistencyCheckResult],
    primary_observation_count: int,
    status: ConsistencyStatus,
    uncertainty_m: float | None,
    quality_flags: list[str],
) -> SpatialFootprint:
    if status == ConsistencyStatus.INCONSISTENT:
        grade = "C"
    elif status == ConsistencyStatus.INSUFFICIENT:
        grade = "D"
    elif quality_flags:
        grade = "B"
    else:
        grade = "A"
    return SpatialFootprint(
        footprint_id=_stable_footprint_id(episode.episode_id),
        episode_id=episode.episode_id,
        start_chainage=start_chainage,
        end_chainage=end_chainage,
        estimated_advance_m=estimated_advance_m,
        primary_source=primary_source,
        supporting_sources=sorted(supporting_sources),
        source_asset_count=len(episode.asset_ids),
        channel_count=(1 if primary_source else 0) + len(set(supporting_sources)),
        independent_source_count=len(episode.asset_ids),
        supporting_channel_names=sorted(supporting_sources),
        supporting_source_count=len(set(supporting_sources)),
        consistency_checks_performed=sum(check.performed for check in checks),
        consistency_check_results=checks,
        primary_observation_count=primary_observation_count,
        consistency_status=status,
        uncertainty_m=uncertainty_m,
        quality_grade=grade,
        quality_flags=sorted(set(quality_flags)),
        method_version=FOOTPRINT_METHOD_VERSION,
    )


def _stable_footprint_id(episode_id: str) -> str:
    return f"footprint-{hashlib.sha256(episode_id.encode('utf-8')).hexdigest()[:24]}"
