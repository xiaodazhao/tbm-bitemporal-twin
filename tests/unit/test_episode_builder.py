from __future__ import annotations

from tbm_twin.process.episode_builder import build_excavation_episodes
from tbm_twin.process.weak_labels import label_operation_phases
from tests.conftest import base_rows, normalize_rows


def test_episode_builder_splits_on_long_idle(tmp_path, catalog) -> None:
    rows = base_rows()
    rows.extend(
        [
            {
                **rows[-1],
                "运行时间-time": "2026-01-01T00:01:00+00:00",
                "掘进状态": 0,
                "推进速度": 0.0,
                "推力": 0.0,
                "刀盘扭矩": 0.0,
                "刀盘实际转速": 0.0,
            },
            {
                **rows[-1],
                "运行时间-time": "2026-01-01T00:05:00+00:00",
                "掘进状态": 0,
                "推进速度": 0.0,
                "推力": 0.0,
                "刀盘扭矩": 0.0,
                "刀盘实际转速": 0.0,
            },
            {
                **rows[-1],
                "运行时间-time": "2026-01-01T00:05:10+00:00",
                "掘进状态": 1,
                "推进速度": 2.0,
                "推力": 10.0,
                "刀盘扭矩": 20.0,
                "刀盘实际转速": 3.0,
                "导向盾首里程": 100.2,
            },
        ]
    )
    labeled = label_operation_phases(normalize_rows(tmp_path, rows, catalog))

    episodes = build_excavation_episodes(labeled)

    assert len(episodes) == 2


def test_episode_id_is_stable_and_cross_midnight_is_recorded(tmp_path, catalog) -> None:
    rows = base_rows()
    rows[0]["运行时间-time"] = "2026-01-01T23:59:50+00:00"
    rows[1]["运行时间-time"] = "2026-01-02T00:00:00+00:00"
    rows[2]["运行时间-time"] = "2026-01-02T00:00:10+00:00"
    labeled = label_operation_phases(normalize_rows(tmp_path, rows, catalog))

    first = build_excavation_episodes(labeled)
    second = build_excavation_episodes(labeled)

    assert first[0].episode_id == second[0].episode_id
    assert first[0].cross_midnight_observed


def test_context_idle_does_not_change_excavation_start_and_unknown_tail_does_not_change_end(
    tmp_path, catalog
) -> None:
    rows = base_rows()
    rows.insert(
        0,
        {
            **rows[0],
            "运行时间-time": "2025-12-31T23:59:50+00:00",
            "掘进状态": 0,
            "推进速度": 0.0,
            "推力": 0.0,
            "刀盘扭矩": 0.0,
            "刀盘实际转速": 0.0,
        },
    )
    rows.append(
        {
            **rows[-1],
            "运行时间-time": "2026-01-01T00:00:30+00:00",
            "掘进状态": "",
            "推进速度": "",
            "推力": "",
            "刀盘扭矩": "",
            "刀盘实际转速": "",
        }
    )
    labeled = label_operation_phases(normalize_rows(tmp_path, rows, catalog))

    episode = build_excavation_episodes(labeled)[0]

    assert episode.context_start.isoformat() == "2025-12-31T23:59:50+00:00"
    assert episode.excavation_start.isoformat() == "2026-01-01T00:00:00+00:00"
    assert episode.excavation_end.isoformat() == "2026-01-01T00:00:20+00:00"


def test_internal_short_idle_is_recorded_as_interruption(tmp_path, catalog) -> None:
    rows = base_rows()
    rows.insert(
        2,
        {
            **rows[1],
            "运行时间-time": "2026-01-01T00:00:15+00:00",
            "掘进状态": 0,
            "推进速度": 0.0,
            "推力": 0.0,
            "刀盘扭矩": 0.0,
            "刀盘实际转速": 0.0,
        },
    )
    labeled = label_operation_phases(normalize_rows(tmp_path, rows, catalog))

    episode = build_excavation_episodes(labeled)[0]

    assert episode.interruption_duration_seconds == 0.0
    assert episode.excavating_segment_count == 2
    assert "INTERNAL_INTERRUPTION_PRESENT" in episode.quality_reason_codes


def test_file_boundaries_are_censored_when_excavating_at_edges(tmp_path, catalog) -> None:
    labeled = label_operation_phases(normalize_rows(tmp_path, base_rows(), catalog))

    episode = build_excavation_episodes(labeled)[0]

    assert episode.boundary_status.value == "BOTH_CENSORED"
    assert not episode.actual_start_known
    assert not episode.actual_end_known
    assert "BOUNDARY_BOTH_CENSORED" in episode.quality_reason_codes


def test_left_censored_when_file_starts_excavating_then_stops(tmp_path, catalog) -> None:
    rows = base_rows()
    rows.append(
        {
            **rows[-1],
            "运行时间-time": "2026-01-01T00:00:30+00:00",
            "掘进状态": 0,
            "推进速度": 0.0,
            "推力": 0.0,
            "刀盘扭矩": 0.0,
            "刀盘实际转速": 0.0,
        }
    )
    labeled = label_operation_phases(normalize_rows(tmp_path, rows, catalog))

    episode = build_excavation_episodes(labeled)[0]

    assert episode.boundary_status.value == "LEFT_CENSORED"
    assert not episode.actual_start_known
    assert episode.actual_end_known


def test_right_censored_when_file_ends_excavating_after_startup(tmp_path, catalog) -> None:
    rows = base_rows()
    rows.insert(
        0,
        {
            **rows[0],
            "运行时间-time": "2025-12-31T23:59:50+00:00",
            "掘进状态": 1,
            "推进速度": 0.0,
            "推力": 10.0,
            "刀盘扭矩": 20.0,
            "刀盘实际转速": 3.0,
        },
    )
    labeled = label_operation_phases(normalize_rows(tmp_path, rows, catalog))

    episode = build_excavation_episodes(labeled)[0]

    assert episode.boundary_status.value == "RIGHT_CENSORED"
    assert episode.actual_start_known
    assert not episode.actual_end_known


def test_short_idle_jitter_is_merged(tmp_path, catalog) -> None:
    rows = base_rows()
    rows.insert(
        2,
        {
            **rows[1],
            "运行时间-time": "2026-01-01T00:00:15+00:00",
            "掘进状态": 0,
            "推进速度": 0.0,
            "推力": 0.0,
            "刀盘扭矩": 0.0,
            "刀盘实际转速": 0.0,
        },
    )
    labeled = label_operation_phases(normalize_rows(tmp_path, rows, catalog))

    episodes = build_excavation_episodes(labeled)

    assert len(episodes) == 1
    assert any(interval.phase.value == "IDLE" for interval in episodes[0].phase_sequence)
