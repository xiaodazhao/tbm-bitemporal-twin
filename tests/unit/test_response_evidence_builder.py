from __future__ import annotations

from tbm_twin.evidence.response_builder import ResponseEvidenceConfig, build_response_evidence
from tbm_twin.process.episode_builder import build_excavation_episodes
from tbm_twin.process.weak_labels import label_operation_phases
from tbm_twin.trajectory.footprint_builder import build_spatial_footprints
from tests.conftest import base_rows, normalize_rows


def test_response_evidence_uses_only_core_observation_refs(catalog, tmp_path) -> None:
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
    labeled = label_operation_phases(normalize_rows(tmp_path, rows, catalog))
    episodes = build_excavation_episodes(labeled)
    footprints = build_spatial_footprints(labeled, episodes)

    records = build_response_evidence(
        labeled,
        episodes,
        footprints,
        config=ResponseEvidenceConfig(features=["advance_speed"]),
    )

    assert records
    assert len(records) == 1
    assert all(
        record.core_observation_refs == episodes[0].core_observation_refs for record in records
    )
    assert all(
        record.unit is None and record.unit_confidence.value == "UNVERIFIED" for record in records
    )


def test_response_evidence_downgrades_zero_advance_and_censored_episode(catalog, tmp_path) -> None:
    rows = base_rows()
    for row in rows:
        row["导向盾首里程"] = 100.0
    labeled = label_operation_phases(normalize_rows(tmp_path, rows, catalog))
    episodes = build_excavation_episodes(labeled)
    footprints = build_spatial_footprints(labeled, episodes)

    records = build_response_evidence(
        labeled,
        episodes,
        footprints,
        config=ResponseEvidenceConfig(features=["advance_speed"]),
    )

    flags = {flag for record in records for flag in record.quality_flags}
    assert "ZERO_ADVANCE_TARGET" in flags
    assert "EPISODE_BOUNDARY_CENSORED" in flags


def test_response_evidence_generates_one_record_per_episode_channel(catalog, tmp_path) -> None:
    labeled = label_operation_phases(normalize_rows(tmp_path, base_rows(), catalog))
    episodes = build_excavation_episodes(labeled)
    footprints = build_spatial_footprints(labeled, episodes)

    records = build_response_evidence(
        labeled,
        episodes,
        footprints,
        config=ResponseEvidenceConfig(
            features=["advance_speed", "total_thrust"],
            min_core_observation_count=1,
        ),
    )

    assert len(records) == 2
    assert {record.channel_name for record in records} == {"advance_speed", "total_thrust"}
    assert all(record.statistics.mean is not None for record in records)
    assert all("mean" not in record.evidence_id for record in records)


def test_zero_advance_does_not_lower_plain_mechanical_measurement_quality(
    catalog, tmp_path
) -> None:
    rows = base_rows()
    for row in rows:
        row["导向盾首里程"] = 100.0
    labeled = label_operation_phases(normalize_rows(tmp_path, rows, catalog))
    episodes = build_excavation_episodes(labeled)
    footprints = build_spatial_footprints(labeled, episodes)

    records = build_response_evidence(
        labeled,
        episodes,
        footprints,
        config=ResponseEvidenceConfig(
            features=["advance_speed", "total_thrust"],
            min_core_observation_count=1,
        ),
    )
    by_channel = {record.channel_name: record for record in records}

    assert by_channel["advance_speed"].quality_components.spatial_scope_quality.value == "B"
    assert by_channel["total_thrust"].quality_components.spatial_scope_quality.value == "A"
    assert by_channel["total_thrust"].quality_components.measurement_quality.value == "B"
