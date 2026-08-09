from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from tbm_twin.evidence.models import BaselineMethod
from tbm_twin.evidence.response_builder import ResponseEvidenceConfig
from tbm_twin.operational_freeze.response import build_no_baseline_response_evidence
from tbm_twin.process.models import EpisodeBoundaryStatus, ExcavationEpisode
from tbm_twin.trajectory.models import ConsistencyStatus, SpatialFootprint


def test_response_evidence_can_disable_baseline_and_deviation() -> None:
    start = datetime(2023, 9, 15, tzinfo=UTC)
    frame = pd.DataFrame(
        {
            "observation_id": ["obs-1", "obs-2"],
            "asset_id": ["asset-1", "asset-1"],
            "source_row_number": [1, 2],
            "timestamp": [start, start + timedelta(seconds=20)],
            "advance_speed": [1.0, 2.0],
        }
    )
    episode = _episode(start)
    footprint = _footprint(episode.episode_id)
    reconstructed_at = datetime(2026, 7, 30, tzinfo=UTC)

    records = build_no_baseline_response_evidence(
        frame,
        [episode],
        [footprint],
        config=ResponseEvidenceConfig(
            features=["advance_speed"],
            baseline_method=BaselineMethod.NO_BASELINE,
        ),
        reconstruction_time=reconstructed_at,
    )

    assert len(records) == 1
    assert records[0].baseline is None
    assert records[0].deviation is None
    assert records[0].ingested_time == reconstructed_at
    assert records[0].core_observation_refs == ["obs-1", "obs-2"]


def _episode(start: datetime) -> ExcavationEpisode:
    return ExcavationEpisode(
        episode_id="episode-test",
        asset_ids=["asset-1"],
        context_start=start,
        context_end=start + timedelta(seconds=20),
        excavation_start=start,
        excavation_end=start + timedelta(seconds=20),
        context_duration_seconds=20,
        core_excavation_duration_seconds=20,
        interruption_duration_seconds=0,
        excavating_segment_count=1,
        temporal_coverage_ratio=1,
        boundary_status=EpisodeBoundaryStatus.COMPLETE,
        actual_start_known=True,
        actual_end_known=True,
        phase_sequence=[],
        observation_refs=["obs-1", "obs-2"],
        core_observation_refs=["obs-1", "obs-2"],
        cross_midnight_observed=False,
        quality_grade="A",
        quality_reason_codes=[],
        quality_flags=[],
        method_version="test",
    )


def _footprint(episode_id: str) -> SpatialFootprint:
    return SpatialFootprint(
        footprint_id="footprint-test",
        episode_id=episode_id,
        start_chainage=1,
        end_chainage=2,
        estimated_advance_m=1,
        primary_source="shield_head_chainage",
        supporting_sources=[],
        source_asset_count=1,
        channel_count=1,
        independent_source_count=1,
        supporting_channel_names=[],
        supporting_source_count=0,
        consistency_checks_performed=0,
        consistency_check_results=[],
        primary_observation_count=2,
        consistency_status=ConsistencyStatus.PRIMARY_CHANNEL_ONLY,
        uncertainty_m=1,
        quality_grade="A",
        quality_flags=[],
        method_version="test",
    )
