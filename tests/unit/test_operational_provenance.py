from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from tbm_twin.operational_freeze.validation import episode_integrity_rows
from tbm_twin.process.models import EpisodeBoundaryStatus, ExcavationEpisode, OperationPhase


def test_episode_integrity_requires_core_refs_to_be_excavating() -> None:
    start = datetime(2023, 9, 15, tzinfo=UTC)
    frame = pd.DataFrame(
        {
            "observation_id": ["obs-1", "obs-2"],
            "operation_phase": [OperationPhase.EXCAVATING.value, OperationPhase.IDLE.value],
        }
    )
    episode = ExcavationEpisode(
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

    rows = episode_integrity_rows(
        target_date=start.date(),
        episodes=[episode],
        labeled_frame=frame,
    )

    assert any(row["issue_code"].startswith("core_ref_not_excavating:obs-2") for row in rows)
