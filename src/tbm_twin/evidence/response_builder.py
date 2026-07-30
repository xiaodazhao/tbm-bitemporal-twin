"""Build ResponseEvidence from PLC-inferred excavation episodes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from tbm_twin.evidence.models import (
    BaselineMethod,
    BaselineReference,
    DeviationAssessment,
    DeviationDirection,
    EvidenceQualityComponents,
    EvidenceQualityGrade,
    EvidenceType,
    ResponseBaseline,
    ResponseEvidence,
    ResponsePhaseScope,
    ResponseStatistics,
    SpatialScope,
    TimeInterval,
    UnitConfidence,
)
from tbm_twin.process.models import EpisodeBoundaryStatus, ExcavationEpisode
from tbm_twin.trajectory.models import SpatialFootprint

RESPONSE_METHOD_VERSION = "response_evidence_v2_episode_channel"


@dataclass(frozen=True)
class ResponseEvidenceConfig:
    """Configuration for response evidence construction."""

    features: list[str]
    min_core_observation_count: int = 5
    max_missing_rate_for_a: float = 0.2
    max_missing_rate_for_b: float = 0.5
    min_temporal_coverage_for_a: float = 0.8
    robust_z_near_threshold: float = 1.5
    robust_z_strong_threshold: float = 3.0
    baseline_method: BaselineMethod = BaselineMethod.GLOBAL_ROBUST_BASELINE
    advance_related_features: frozenset[str] = frozenset({"advance_speed", "penetration"})


def load_response_config(
    path: Path = Path("configs/response_evidence.yaml"),
) -> ResponseEvidenceConfig:
    """Load response evidence configuration."""

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    quality = data.get("quality", {})
    baseline = data.get("baseline", {})
    return ResponseEvidenceConfig(
        features=list(data.get("features", [])),
        min_core_observation_count=int(quality.get("min_core_observation_count", 5)),
        max_missing_rate_for_a=float(quality.get("max_missing_rate_for_a", 0.2)),
        max_missing_rate_for_b=float(quality.get("max_missing_rate_for_b", 0.5)),
        min_temporal_coverage_for_a=float(quality.get("min_temporal_coverage_for_a", 0.8)),
        robust_z_near_threshold=float(baseline.get("robust_z_near_threshold", 1.5)),
        robust_z_strong_threshold=float(baseline.get("robust_z_strong_threshold", 3.0)),
        baseline_method=BaselineMethod(str(baseline.get("method", "GLOBAL_ROBUST_BASELINE"))),
        advance_related_features=frozenset(
            str(item)
            for item in quality.get("advance_related_features", ["advance_speed", "penetration"])
        ),
    )


def build_global_robust_baselines(
    normalized_frame: pd.DataFrame,
    *,
    features: list[str],
    data_scope: str,
    created_at: datetime | None = None,
) -> dict[str, ResponseBaseline]:
    """Build transparent median/MAD baselines from an explicit data scope."""

    created = created_at or datetime.now(UTC)
    baselines: dict[str, ResponseBaseline] = {}
    for feature in features:
        series = pd.to_numeric(
            normalized_frame.get(feature, pd.Series(dtype=float)), errors="coerce"
        )
        values = series.dropna()
        median = float(values.median()) if not values.empty else None
        mad = (
            float((values - median).abs().median())
            if median is not None and not values.empty
            else None
        )
        baseline_id = _stable_id("baseline", feature, data_scope, str(median), str(mad))
        baselines[feature] = ResponseBaseline(
            baseline_id=baseline_id,
            baseline_method=BaselineMethod.GLOBAL_ROBUST_BASELINE,
            baseline_data_scope=data_scope,
            baseline_created_at=created,
            baseline_feature=feature,
            baseline_median=median,
            baseline_mad=mad,
            sample_count=int(values.shape[0]),
        )
    return baselines


def build_response_evidence(
    normalized_frame: pd.DataFrame,
    episodes: list[ExcavationEpisode],
    footprints: list[SpatialFootprint],
    *,
    config: ResponseEvidenceConfig | None = None,
    baselines: dict[str, ResponseBaseline] | None = None,
) -> list[ResponseEvidence]:
    """Build response evidence over core EXCAVATING observations only."""

    config = config or load_response_config()
    baselines = baselines or build_global_robust_baselines(
        normalized_frame,
        features=config.features,
        data_scope="provided_normalized_frame",
    )
    by_obs = normalized_frame.set_index("observation_id", drop=False)
    footprint_by_episode = {footprint.episode_id: footprint for footprint in footprints}
    evidence: list[ResponseEvidence] = []
    for episode in episodes:
        refs = [ref for ref in episode.core_observation_refs if ref in by_obs.index]
        rows = by_obs.loc[refs].copy()
        footprint = footprint_by_episode.get(episode.episode_id)
        for feature in config.features:
            record = _feature_evidence(
                episode=episode,
                rows=rows,
                feature=feature,
                baseline=baselines.get(feature),
                footprint=footprint,
                config=config,
            )
            if record is not None:
                evidence.append(record)
    return evidence


def _feature_evidence(
    *,
    episode: ExcavationEpisode,
    rows: pd.DataFrame,
    feature: str,
    baseline: ResponseBaseline | None,
    footprint: SpatialFootprint | None,
    config: ResponseEvidenceConfig,
) -> ResponseEvidence | None:
    if feature not in rows.columns:
        return None
    series = pd.to_numeric(rows.get(feature, pd.Series(dtype=float)), errors="coerce")
    stats = _stats(series)
    if stats.valid_count == 0:
        return None
    quality_components = _response_quality_components(episode, stats, footprint, feature, config)
    reason_codes = (
        quality_components.measurement_reason_codes
        + quality_components.temporal_scope_reason_codes
        + quality_components.spatial_scope_reason_codes
    )
    quality = _worst_grade(
        [
            quality_components.measurement_quality,
            quality_components.temporal_scope_quality,
            quality_components.spatial_scope_quality,
        ]
    )
    unit = None
    unit_confidence = UnitConfidence.UNVERIFIED
    source_asset_ids = (
        sorted(set(rows["asset_id"].astype(str).to_list()))
        if "asset_id" in rows
        else episode.asset_ids
    )
    spatial_scope = (
        SpatialScope(
            start_chainage=footprint.start_chainage,
            end_chainage=footprint.end_chainage,
            basis=f"footprint:{footprint.consistency_status.value}",
        )
        if footprint
        else None
    )
    baseline_ref = (
        BaselineReference(
            baseline_id=baseline.baseline_id,
            baseline_method=baseline.baseline_method,
            baseline_data_scope=baseline.baseline_data_scope,
            baseline_value=baseline.baseline_median,
            sample_count=baseline.sample_count,
        )
        if baseline
        else None
    )
    deviation_value, direction, strength = _deviation(stats.mean, baseline, config)
    deviation = DeviationAssessment(
        statistic="mean",
        deviation_value=deviation_value,
        deviation_direction=direction or DeviationDirection.UNDETERMINED,
        deviation_strength=strength,
    )
    evidence_id = _stable_id("response", episode.episode_id, feature, RESPONSE_METHOD_VERSION)
    return ResponseEvidence(
        evidence_id=evidence_id,
        evidence_type=EvidenceType.RESPONSE,
        source_asset_ids=source_asset_ids,
        valid_time=TimeInterval(start=episode.excavation_start, end=episode.excavation_end),
        available_time=episode.excavation_end,
        ingested_time=datetime.now(UTC),
        spatial_scope=spatial_scope,
        quality_grade=quality,
        quality_flags=sorted(set(reason_codes)),
        method_version=RESPONSE_METHOD_VERSION,
        provenance_refs=episode.core_observation_refs,
        episode_id=episode.episode_id,
        phase_scope=ResponsePhaseScope.CORE_EXCAVATION,
        channel_name=feature,
        unit=unit,
        unit_confidence=unit_confidence,
        statistics=stats,
        baseline=baseline_ref,
        deviation=deviation,
        temporal_coverage_ratio=episode.temporal_coverage_ratio,
        quality_components=quality_components,
        core_observation_refs=episode.core_observation_refs,
    )


def _stats(series: pd.Series) -> ResponseStatistics:
    count = len(series)
    valid = pd.to_numeric(series, errors="coerce").dropna()
    valid_count = len(valid)
    mean = float(valid.mean()) if not valid.empty else None
    std = float(valid.std()) if len(valid) > 1 else None
    return ResponseStatistics(
        sample_count=count,
        valid_count=valid_count,
        missing_rate=1.0 - valid_count / count if count else 1.0,
        mean=mean,
        median=float(valid.median()) if not valid.empty else None,
        standard_deviation=std,
        p10=float(valid.quantile(0.1)) if not valid.empty else None,
        p90=float(valid.quantile(0.9)) if not valid.empty else None,
        minimum=float(valid.min()) if not valid.empty else None,
        maximum=float(valid.max()) if not valid.empty else None,
        coefficient_of_variation=abs(std / mean)
        if std is not None and mean not in {None, 0.0}
        else None,
    )


def _response_quality_components(
    episode: ExcavationEpisode,
    stats: ResponseStatistics,
    footprint: SpatialFootprint | None,
    feature: str,
    config: ResponseEvidenceConfig,
) -> EvidenceQualityComponents:
    measurement: set[str] = set()
    temporal: set[str] = set()
    spatial: set[str] = set()
    if episode.boundary_status != EpisodeBoundaryStatus.COMPLETE:
        temporal.add("EPISODE_BOUNDARY_CENSORED")
    if len(episode.core_observation_refs) < config.min_core_observation_count:
        measurement.add("LOW_SAMPLE_COUNT")
    missing_rate = stats.missing_rate
    if missing_rate > config.max_missing_rate_for_b:
        measurement.add("HIGH_MISSING_RATE")
    elif missing_rate > config.max_missing_rate_for_a:
        measurement.add("MODERATE_MISSING_RATE")
    measurement.add("UNIT_UNVERIFIED")
    if episode.temporal_coverage_ratio < config.min_temporal_coverage_for_a:
        temporal.add("LOW_TEMPORAL_COVERAGE")
    if episode.interruption_duration_seconds > 0:
        temporal.add("INTERNAL_INTERRUPTION_PRESENT")
    if footprint and footprint.consistency_status.value in {"INCONSISTENT", "INSUFFICIENT"}:
        spatial.add(f"FOOTPRINT_{footprint.consistency_status.value}")
    if (
        footprint
        and "ZERO_ADVANCE_DURING_EXCAVATION" in footprint.quality_flags
        and feature in config.advance_related_features
    ):
        spatial.add("ZERO_ADVANCE_TARGET")
    if episode.quality_grade in {"C", "D"}:
        temporal.add("LOW_TARGET_QUALITY")
    return EvidenceQualityComponents(
        measurement_quality=_component_grade(sorted(measurement)),
        temporal_scope_quality=_component_grade(sorted(temporal)),
        spatial_scope_quality=_component_grade(sorted(spatial)),
        measurement_reason_codes=sorted(measurement),
        temporal_scope_reason_codes=sorted(temporal),
        spatial_scope_reason_codes=sorted(spatial),
    )


def _deviation(
    value: float | None,
    baseline: ResponseBaseline | None,
    config: ResponseEvidenceConfig,
) -> tuple[float | None, DeviationDirection | None, str | None]:
    if (
        value is None
        or baseline is None
        or baseline.baseline_median is None
        or not baseline.baseline_mad
    ):
        return None, DeviationDirection.UNDETERMINED, None
    robust_z = (value - baseline.baseline_median) / (1.4826 * baseline.baseline_mad)
    abs_z = abs(robust_z)
    if abs_z <= config.robust_z_near_threshold:
        return robust_z, DeviationDirection.NEAR_BASELINE, "NEAR"
    direction = (
        DeviationDirection.ABOVE_BASELINE if robust_z > 0 else DeviationDirection.BELOW_BASELINE
    )
    strength = "STRONG" if abs_z >= config.robust_z_strong_threshold else "MODERATE"
    return robust_z, direction, strength


def response_evidence_summary(records: list[ResponseEvidence]) -> list[dict[str, Any]]:
    """Summarize response evidence for CSV diagnostics."""

    return [
        {
            "evidence_id": record.evidence_id,
            "episode_id": record.episode_id,
            "channel_name": record.channel_name,
            "sample_count": record.statistics.sample_count,
            "valid_count": record.statistics.valid_count,
            "missing_rate": record.statistics.missing_rate,
            "mean": record.statistics.mean,
            "median": record.statistics.median,
            "standard_deviation": record.statistics.standard_deviation,
            "p10": record.statistics.p10,
            "p90": record.statistics.p90,
            "minimum": record.statistics.minimum,
            "maximum": record.statistics.maximum,
            "coefficient_of_variation": record.statistics.coefficient_of_variation,
            "quality_grade": record.quality_grade.value,
            "measurement_quality": record.quality_components.measurement_quality.value,
            "temporal_scope_quality": record.quality_components.temporal_scope_quality.value,
            "spatial_scope_quality": record.quality_components.spatial_scope_quality.value,
            "quality_flags": ";".join(record.quality_flags),
            "unit_confidence": record.unit_confidence.value,
            "baseline_id": record.baseline.baseline_id if record.baseline else None,
            "baseline_value": record.baseline.baseline_value if record.baseline else None,
            "deviation_direction": record.deviation.deviation_direction.value
            if record.deviation
            else None,
            "deviation_strength": record.deviation.deviation_strength if record.deviation else None,
        }
        for record in records
    ]


def _component_grade(reason_codes: list[str]) -> EvidenceQualityGrade:
    serious = {
        "HIGH_MISSING_RATE",
        "LOW_SAMPLE_COUNT",
        "FOOTPRINT_INCONSISTENT",
        "FOOTPRINT_INSUFFICIENT",
    }
    moderate = {
        "MODERATE_MISSING_RATE",
        "UNIT_UNVERIFIED",
        "EPISODE_BOUNDARY_CENSORED",
        "LOW_TEMPORAL_COVERAGE",
        "INTERNAL_INTERRUPTION_PRESENT",
        "ZERO_ADVANCE_TARGET",
        "LOW_TARGET_QUALITY",
    }
    if set(reason_codes) & serious:
        return EvidenceQualityGrade.C
    if set(reason_codes) & moderate:
        return EvidenceQualityGrade.B
    return EvidenceQualityGrade.A


def _worst_grade(grades: list[EvidenceQualityGrade]) -> EvidenceQualityGrade:
    order = {
        EvidenceQualityGrade.A: 0,
        EvidenceQualityGrade.B: 1,
        EvidenceQualityGrade.C: 2,
        EvidenceQualityGrade.D: 3,
    }
    return max(grades, key=lambda grade: order[grade])


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]
