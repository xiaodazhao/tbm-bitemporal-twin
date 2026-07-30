from __future__ import annotations

from tbm_twin.process.episode_builder import build_excavation_episodes
from tbm_twin.process.weak_labels import label_operation_phases
from tbm_twin.trajectory.footprint_builder import build_spatial_footprints
from tests.conftest import base_rows, normalize_rows


def test_footprint_consistent_for_clean_chainage(tmp_path, catalog) -> None:
    labeled = label_operation_phases(normalize_rows(tmp_path, base_rows(), catalog))
    episodes = build_excavation_episodes(labeled)

    footprints = build_spatial_footprints(labeled, episodes)

    assert footprints[0].consistency_status.value == "PRIMARY_CHANNEL_ONLY"
    assert footprints[0].estimated_advance_m is not None


def test_inconsistent_footprint_does_not_emit_fake_advance(tmp_path, catalog) -> None:
    rows = base_rows()
    rows[1]["导向盾首里程"] = 130.0
    labeled = label_operation_phases(normalize_rows(tmp_path, rows, catalog))
    episodes = build_excavation_episodes(labeled)

    footprints = build_spatial_footprints(labeled, episodes)

    assert footprints[0].consistency_status.value == "INCONSISTENT"
    assert footprints[0].estimated_advance_m is None


def test_multi_source_consistent_requires_supporting_source(tmp_path, catalog) -> None:
    rows = base_rows()
    rows[0]["日进尺"] = 0.0
    rows[1]["日进尺"] = 0.02
    rows[2]["日进尺"] = 0.04
    labeled = label_operation_phases(normalize_rows(tmp_path, rows, catalog))
    episodes = build_excavation_episodes(labeled)

    footprints = build_spatial_footprints(labeled, episodes)

    assert footprints[0].consistency_status.value == "MULTI_CHANNEL_CONSISTENT"
    assert footprints[0].supporting_source_count == 1
    assert footprints[0].consistency_checks_performed == 1
    assert footprints[0].source_asset_count == 1
    assert footprints[0].independent_source_count == 1


def test_zero_advance_during_excavation_gets_review_flags(tmp_path, catalog) -> None:
    rows = base_rows()
    for row in rows:
        row["导向盾首里程"] = 100.0
    labeled = label_operation_phases(normalize_rows(tmp_path, rows, catalog))
    episodes = build_excavation_episodes(labeled)

    footprints = build_spatial_footprints(labeled, episodes)

    assert "ZERO_ADVANCE_DURING_EXCAVATION" in footprints[0].quality_flags
    assert "static_chainage_signal" in footprints[0].quality_flags
