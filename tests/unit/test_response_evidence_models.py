from __future__ import annotations

from datetime import UTC, datetime

from tbm_twin.evidence.models import (
    EvidenceQualityComponents,
    EvidenceQualityGrade,
    EvidenceType,
    ResponseEvidence,
    ResponsePhaseScope,
    ResponseStatistics,
    UnitConfidence,
)


def test_response_evidence_model_keeps_trace_fields() -> None:
    record = ResponseEvidence(
        evidence_id="response-1",
        evidence_type=EvidenceType.RESPONSE,
        source_asset_ids=["asset-1"],
        valid_time=None,
        available_time=datetime(2026, 1, 1, tzinfo=UTC),
        ingested_time=datetime(2026, 1, 2, tzinfo=UTC),
        spatial_scope=None,
        quality_grade="A",
        quality_flags=[],
        method_version="test",
        provenance_refs=["obs-1"],
        episode_id="episode-1",
        phase_scope=ResponsePhaseScope.CORE_EXCAVATION,
        channel_name="advance_speed",
        unit=None,
        unit_confidence=UnitConfidence.UNVERIFIED,
        statistics=ResponseStatistics(
            sample_count=1,
            valid_count=1,
            missing_rate=0.0,
            mean=1.0,
            median=1.0,
            standard_deviation=None,
            p10=1.0,
            p90=1.0,
            minimum=1.0,
            maximum=1.0,
            coefficient_of_variation=None,
        ),
        baseline=None,
        deviation=None,
        temporal_coverage_ratio=1.0,
        quality_components=EvidenceQualityComponents(
            measurement_quality=EvidenceQualityGrade.A,
            temporal_scope_quality=EvidenceQualityGrade.A,
            spatial_scope_quality=EvidenceQualityGrade.A,
            measurement_reason_codes=[],
            temporal_scope_reason_codes=[],
            spatial_scope_reason_codes=[],
        ),
        core_observation_refs=["obs-1"],
    )

    assert record.source_asset_ids == ["asset-1"]
    assert record.provenance_refs == ["obs-1"]
    assert record.statistics.mean == 1.0
