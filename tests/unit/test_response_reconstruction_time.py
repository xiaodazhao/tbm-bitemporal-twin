from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tbm_twin.evidence.models import (
    BaselineMethod,
    EvidenceQualityComponents,
    EvidenceQualityGrade,
    EvidenceType,
    ResponseEvidence,
    ResponsePhaseScope,
    ResponseStatistics,
    SpatialScope,
    TimeInterval,
    UnitConfidence,
)
from tbm_twin.operational_freeze.builder import OperationalFreezeBuilder
from tbm_twin.operational_freeze.models import (
    OperationalFreezeConfig,
    OperationalResponseEvidenceRecord,
)


def test_response_record_marks_reconstruction_time_as_non_historical() -> None:
    reconstructed_at = datetime(2026, 7, 30, tzinfo=UTC)
    builder = OperationalFreezeBuilder(
        OperationalFreezeConfig(
            repo_root=Path.cwd(),
            output_dir=Path("artifacts/test"),
            reconstruction_time=reconstructed_at,
        )
    )
    response = ResponseEvidence(
        evidence_id="response-1",
        evidence_type=EvidenceType.RESPONSE,
        source_asset_ids=["asset-1"],
        valid_time=TimeInterval(start=reconstructed_at, end=reconstructed_at),
        available_time=reconstructed_at,
        ingested_time=reconstructed_at,
        spatial_scope=SpatialScope(
            start_chainage=1.0,
            end_chainage=2.0,
            basis="raw_episode_core_chainage_scope",
        ),
        quality_grade=EvidenceQualityGrade.A,
        quality_flags=[],
        method_version="test",
        provenance_refs=["obs-1"],
        episode_id="episode-1",
        phase_scope=ResponsePhaseScope.CORE_EXCAVATION,
        channel_name="thrust_force",
        unit="kN",
        unit_confidence=UnitConfidence.VERIFIED,
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
    rows = builder._response_records(
        datetime(2023, 9, 15).date(),
        [response],
        {
            "episode-1": {
                "raw_spatial_scope": {
                    "kind": "INTERVAL",
                    "start_chainage": 1.0,
                    "end_chainage": 2.0,
                    "basis": "raw_episode_core_chainage_scope",
                },
                "trusted_spatial_scope": {
                    "kind": "INTERVAL",
                    "start_chainage": 1.0,
                    "end_chainage": 2.0,
                    "basis": "trusted_episode_core_chainage_scope",
                },
                "spatial_scope_usable": True,
                "chainage_regime_status": "TRUSTED",
                "chainage_regime_reason_codes": [],
            }
        },
    )

    assert rows[0]["reconstructed_at"] == "2026-07-30T00:00:00Z"
    assert rows[0]["historical_ingestion_time"] is None
    assert rows[0]["ingestion_time_known"] is False
    assert rows[0]["ingestion_time_basis"] == "OFFLINE_RECONSTRUCTION_NOT_HISTORICAL"
    assert rows[0]["baseline_method"] == BaselineMethod.NO_BASELINE.value
    assert rows[0]["spatial_scope"] == {
        "start_chainage": 1.0,
        "end_chainage": 2.0,
        "basis": "trusted_episode_core_chainage_scope",
    }
    reloaded = OperationalResponseEvidenceRecord.model_validate(rows[0])
    assert reloaded.reconstructed_at == reconstructed_at
    assert reloaded.ingestion_time_known is False
