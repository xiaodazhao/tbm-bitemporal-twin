from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tbm_twin.operational_freeze.builder import OperationalFreezeBuilder
from tbm_twin.operational_freeze.models import OperationalFreezeConfig
from tbm_twin.process.models import EpisodeBoundaryStatus


def test_stage2e_target_dates_come_from_frozen_applicability(tmp_path) -> None:
    builder = OperationalFreezeBuilder(
        OperationalFreezeConfig(
            repo_root=Path.cwd(),
            output_dir=tmp_path,
            reconstruction_time=datetime(2026, 7, 30, tzinfo=UTC),
        )
    )

    target_dates = builder._load_target_dates()

    assert len(target_dates.dates) == 91
    assert target_dates.dates[0].isoformat() == "2023-09-15"
    assert target_dates.dates[-1].isoformat() == "2023-12-30"
    assert target_dates.assignment_date_count == 91


def test_cross_file_candidates_are_not_merged(tmp_path) -> None:
    builder = OperationalFreezeBuilder(
        OperationalFreezeConfig(
            repo_root=Path.cwd(),
            output_dir=tmp_path,
            reconstruction_time=datetime(2026, 7, 30, tzinfo=UTC),
        )
    )
    left = _episode("left", EpisodeBoundaryStatus.RIGHT_CENSORED)
    right = _episode("right", EpisodeBoundaryStatus.LEFT_CENSORED)

    rows = builder._cross_file_candidates(
        [left.excavation_start.date(), right.excavation_start.date()],
        {
            left.excavation_start.date(): (left, left),
            right.excavation_start.date(): (right, right),
        },
        {
            left.episode_id: {
                "trusted_spatial_scope": {
                    "kind": "INTERVAL",
                    "start_chainage": 1.0,
                    "end_chainage": 2.0,
                    "basis": "trusted_episode_core_chainage_scope",
                },
                "spatial_scope_usable": True,
                "chainage_regime_status": "TRUSTED",
            },
            right.episode_id: {
                "trusted_spatial_scope": {
                    "kind": "INTERVAL",
                    "start_chainage": 2.0,
                    "end_chainage": 3.0,
                    "basis": "trusted_episode_core_chainage_scope",
                },
                "spatial_scope_usable": True,
                "chainage_regime_status": "TRUSTED",
            },
        },
    )

    assert rows
    assert rows[0]["decision"] == "NOT_MERGED_PENDING_REVIEW"
    assert rows[0]["classification"] == "REJECTED_TIME_GAP"


def _episode(episode_id: str, status: EpisodeBoundaryStatus):
    start = datetime(2023, 9, 15 if episode_id == "left" else 16, tzinfo=UTC)
    return {
        "left": _episode_model(episode_id, status, start),
        "right": _episode_model(episode_id, status, start),
    }[episode_id]


def _episode_model(episode_id: str, status: EpisodeBoundaryStatus, start: datetime):
    from datetime import timedelta

    from tbm_twin.process.models import ExcavationEpisode

    return ExcavationEpisode(
        episode_id=f"episode-{episode_id}",
        asset_ids=["asset-1"],
        context_start=start,
        context_end=start + timedelta(seconds=10),
        excavation_start=start,
        excavation_end=start + timedelta(seconds=10),
        context_duration_seconds=10,
        core_excavation_duration_seconds=10,
        interruption_duration_seconds=0,
        excavating_segment_count=1,
        temporal_coverage_ratio=1,
        boundary_status=status,
        actual_start_known=status != EpisodeBoundaryStatus.LEFT_CENSORED,
        actual_end_known=status != EpisodeBoundaryStatus.RIGHT_CENSORED,
        phase_sequence=[],
        observation_refs=[f"obs-{episode_id}"],
        core_observation_refs=[f"obs-{episode_id}"],
        cross_midnight_observed=False,
        quality_grade="B",
        quality_reason_codes=[],
        quality_flags=[],
        method_version="test",
    )
