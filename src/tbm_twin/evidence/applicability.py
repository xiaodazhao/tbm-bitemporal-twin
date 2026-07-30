"""Evidence applicability assignment rules."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from tbm_twin.evidence.models import (
    ApplicabilityResult,
    ApplicabilityTargetType,
    EpistemicApplicabilityStatus,
    EvidenceApplicabilityAssignment,
    EvidenceBase,
    EvidenceType,
    GeologicalEpistemicStatus,
    GeologicalEvidence,
    QualityApplicabilityStatus,
    SpatialApplicabilityStatus,
    TemporalApplicabilityStatus,
)
from tbm_twin.evidence.spatial_rules import spatial_relation
from tbm_twin.evidence.temporal_rules import temporal_status
from tbm_twin.process.models import ExcavationEpisode
from tbm_twin.trajectory.models import SpatialFootprint

APPLICABILITY_METHOD_VERSION = "evidence_applicability_v1"


@dataclass(frozen=True)
class ApplicabilityConfig:
    """Applicability thresholds."""

    adjacent_tolerance_m: float = 5.0
    ahead_context_limit_m: float = 30.0
    background_context_limit_m: float = 50.0
    unknown_available_time_result: ApplicabilityResult = ApplicabilityResult.UNDETERMINED


def load_applicability_config(
    path: Path = Path("configs/evidence_applicability.yaml"),
) -> ApplicabilityConfig:
    """Load applicability configuration."""

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    temporal = data.get("temporal", {})
    spatial = data.get("spatial", {})
    return ApplicabilityConfig(
        adjacent_tolerance_m=float(spatial.get("adjacent_tolerance_m", 5.0)),
        ahead_context_limit_m=float(spatial.get("ahead_context_limit_m", 30.0)),
        background_context_limit_m=float(spatial.get("background_context_limit_m", 50.0)),
        unknown_available_time_result=ApplicabilityResult(
            str(temporal.get("unknown_available_time_result", "UNDETERMINED"))
        ),
    )


def assign_evidence_to_episode(
    evidence: EvidenceBase,
    episode: ExcavationEpisode,
    footprint: SpatialFootprint | None,
    *,
    evaluation_time: datetime,
    config: ApplicabilityConfig | None = None,
) -> EvidenceApplicabilityAssignment:
    """Assign one evidence record to one PLC-inferred episode."""

    config = config or load_applicability_config()
    reasons: set[str] = set()
    temporal = temporal_status(evidence, evaluation_time)
    if temporal == TemporalApplicabilityStatus.NOT_YET_AVAILABLE:
        reasons.add("EVIDENCE_NOT_YET_AVAILABLE")
    elif temporal == TemporalApplicabilityStatus.AVAILABLE_TIME_UNKNOWN:
        reasons.add("AVAILABLE_TIME_UNKNOWN")
    else:
        reasons.add("TEMPORAL_OVERLAP_CONFIRMED")

    spatial = _spatial_status(evidence, footprint, config)
    reasons.add(f"SPATIAL_{spatial.value}")
    epistemic = _epistemic_status(evidence, reasons)
    quality = _quality_status(evidence, episode, footprint, reasons)
    result, dominant_reason_code = combine_applicability(
        temporal_status=temporal,
        spatial_status=spatial,
        epistemic_status=epistemic,
        quality_status=quality,
        evidence_type=evidence.evidence_type,
    )
    reasons.add(dominant_reason_code)
    return EvidenceApplicabilityAssignment(
        assignment_id=_stable_id(
            evidence.evidence_id,
            episode.episode_id,
            evaluation_time.isoformat(),
            result.value,
        ),
        evidence_id=evidence.evidence_id,
        evidence_type=evidence.evidence_type,
        evidence_epistemic_status=evidence.epistemic_status.value
        if isinstance(evidence, GeologicalEvidence)
        else None,
        target_id=episode.episode_id,
        target_type=ApplicabilityTargetType.EPISODE,
        evaluation_time=evaluation_time,
        temporal_status=temporal,
        spatial_status=spatial,
        epistemic_status=epistemic,
        quality_status=quality,
        result=result,
        dominant_reason_code=dominant_reason_code,
        reason_codes=sorted(reasons),
        method_version=APPLICABILITY_METHOD_VERSION,
    )


def applicability_summary(records: list[EvidenceApplicabilityAssignment]) -> list[dict[str, Any]]:
    """Summarize applicability records for CSV output."""

    return [
        {
            "assignment_id": record.assignment_id,
            "evidence_id": record.evidence_id,
            "evidence_type": record.evidence_type.value,
            "evidence_epistemic_status": record.evidence_epistemic_status,
            "target_id": record.target_id,
            "result": record.result.value,
            "dominant_reason_code": record.dominant_reason_code,
            "temporal_status": record.temporal_status.value,
            "spatial_status": record.spatial_status.value,
            "epistemic_status": record.epistemic_status.value,
            "quality_status": record.quality_status.value,
            "reason_codes": ";".join(record.reason_codes),
        }
        for record in records
    ]


def _spatial_status(
    evidence: EvidenceBase,
    footprint: SpatialFootprint | None,
    config: ApplicabilityConfig,
) -> SpatialApplicabilityStatus:
    if isinstance(evidence, GeologicalEvidence):
        return spatial_relation(
            evidence.chainage_interval,
            footprint,
            adjacent_tolerance_m=config.adjacent_tolerance_m,
            ahead_context_limit_m=config.ahead_context_limit_m,
        )
    if evidence.evidence_type == EvidenceType.RESPONSE:
        return SpatialApplicabilityStatus.OVERLAP
    return SpatialApplicabilityStatus.UNKNOWN


def _epistemic_status(
    evidence: EvidenceBase,
    reasons: set[str],
) -> EpistemicApplicabilityStatus:
    if isinstance(evidence, GeologicalEvidence):
        if evidence.epistemic_status == GeologicalEpistemicStatus.FORECAST:
            reasons.add("FORECAST_NOT_OBSERVATION")
            return EpistemicApplicabilityStatus.COMPATIBLE_WITH_QUALIFICATION
        if evidence.epistemic_status == GeologicalEpistemicStatus.BACKGROUND:
            reasons.add("BACKGROUND_ONLY")
            return EpistemicApplicabilityStatus.COMPATIBLE_WITH_QUALIFICATION
        if evidence.epistemic_status == GeologicalEpistemicStatus.UNKNOWN:
            reasons.add("EPISTEMIC_STATUS_UNKNOWN")
            return EpistemicApplicabilityStatus.UNKNOWN
    reasons.add("EPISTEMICALLY_COMPATIBLE")
    return EpistemicApplicabilityStatus.EPISTEMICALLY_COMPATIBLE


def _quality_status(
    evidence: EvidenceBase,
    episode: ExcavationEpisode,
    footprint: SpatialFootprint | None,
    reasons: set[str],
) -> QualityApplicabilityStatus:
    low = False
    if evidence.quality_grade.value in {"C", "D"}:
        reasons.add("LOW_EVIDENCE_QUALITY")
        low = True
    if episode.quality_grade in {"C", "D"}:
        reasons.add("LOW_TARGET_QUALITY")
        low = True
    if footprint and footprint.consistency_status.value in {"INCONSISTENT", "INSUFFICIENT"}:
        reasons.add("TARGET_FOOTPRINT_UNUSABLE")
        low = True
    if footprint and "ZERO_ADVANCE_DURING_EXCAVATION" in footprint.quality_flags:
        reasons.add("ZERO_ADVANCE_TARGET")
        return QualityApplicabilityStatus.QUALIFIED
    return QualityApplicabilityStatus.LOW_QUALITY if low else QualityApplicabilityStatus.ACCEPTABLE


def combine_applicability(
    *,
    temporal_status: TemporalApplicabilityStatus,
    spatial_status: SpatialApplicabilityStatus,
    epistemic_status: EpistemicApplicabilityStatus,
    quality_status: QualityApplicabilityStatus,
    evidence_type: EvidenceType,
) -> tuple[ApplicabilityResult, str]:
    """Combine applicability dimensions with explicit Stage 2.1 priority."""

    if temporal_status == TemporalApplicabilityStatus.NOT_YET_AVAILABLE:
        return ApplicabilityResult.NOT_APPLICABLE, "EVIDENCE_NOT_YET_AVAILABLE"
    if temporal_status == TemporalApplicabilityStatus.INVALID_TEMPORAL_METADATA:
        return ApplicabilityResult.NOT_APPLICABLE, "INVALID_TEMPORAL_SCOPE"
    if spatial_status == SpatialApplicabilityStatus.INVALID:
        return ApplicabilityResult.NOT_APPLICABLE, "INVALID_SPATIAL_SCOPE"
    if spatial_status == SpatialApplicabilityStatus.DISJOINT:
        return ApplicabilityResult.NOT_APPLICABLE, "SPATIAL_DISJOINT"
    if epistemic_status == EpistemicApplicabilityStatus.EPISTEMICALLY_INCOMPATIBLE:
        return ApplicabilityResult.NOT_APPLICABLE, "EPISTEMICALLY_INCOMPATIBLE"

    if (
        evidence_type == EvidenceType.GEOLOGICAL_FORECAST
        and spatial_status == SpatialApplicabilityStatus.BEHIND
    ):
        return ApplicabilityResult.NOT_APPLICABLE, "FORECAST_BEHIND_TARGET"
    if (
        evidence_type == EvidenceType.GEOLOGICAL_OBSERVATION
        and spatial_status == SpatialApplicabilityStatus.AHEAD
    ):
        return ApplicabilityResult.NOT_APPLICABLE, "OBSERVED_AHEAD_OF_TARGET"
    if (
        evidence_type == EvidenceType.GEOLOGICAL_OBSERVATION
        and spatial_status == SpatialApplicabilityStatus.BEHIND
    ):
        return ApplicabilityResult.NOT_APPLICABLE, "OBSERVED_BEHIND_WITHOUT_TARGET_COVERAGE"

    if temporal_status == TemporalApplicabilityStatus.AVAILABLE_TIME_UNKNOWN:
        return ApplicabilityResult.UNDETERMINED, "AVAILABLE_TIME_UNKNOWN"
    if temporal_status == TemporalApplicabilityStatus.UNKNOWN_WITHIN_PRECISION:
        return ApplicabilityResult.UNDETERMINED, "UNKNOWN_WITHIN_PRECISION"
    if spatial_status == SpatialApplicabilityStatus.UNKNOWN:
        return ApplicabilityResult.UNDETERMINED, "SPATIAL_SCOPE_UNKNOWN"
    if epistemic_status == EpistemicApplicabilityStatus.UNKNOWN:
        return ApplicabilityResult.UNDETERMINED, "EPISTEMIC_STATUS_UNKNOWN"

    if evidence_type == EvidenceType.GEOLOGICAL_BACKGROUND:
        return ApplicabilityResult.APPLICABLE_WITH_QUALIFICATION, "BACKGROUND_CONTEXT_ONLY"
    if evidence_type == EvidenceType.GEOLOGICAL_FORECAST and spatial_status in {
        SpatialApplicabilityStatus.ADJACENT,
        SpatialApplicabilityStatus.AHEAD,
    }:
        return (
            ApplicabilityResult.APPLICABLE_WITH_QUALIFICATION,
            "FORECAST_CONTEXTUAL_SPATIAL_SCOPE",
        )
    if (
        evidence_type == EvidenceType.GEOLOGICAL_OBSERVATION
        and spatial_status == SpatialApplicabilityStatus.ADJACENT
    ):
        return (
            ApplicabilityResult.APPLICABLE_WITH_QUALIFICATION,
            "OBSERVED_ADJACENT_WITH_QUALIFICATION",
        )
    if (
        spatial_status in {SpatialApplicabilityStatus.ADJACENT, SpatialApplicabilityStatus.AHEAD}
        or epistemic_status == EpistemicApplicabilityStatus.COMPATIBLE_WITH_QUALIFICATION
        or quality_status != QualityApplicabilityStatus.ACCEPTABLE
    ):
        return ApplicabilityResult.APPLICABLE_WITH_QUALIFICATION, "QUALIFICATION_REQUIRED"
    return ApplicabilityResult.APPLICABLE, "ALL_APPLICABILITY_CONDITIONS_MET"


def _stable_id(*parts: str) -> str:
    return f"assign-{hashlib.sha256('|'.join(parts).encode()).hexdigest()[:24]}"
