from __future__ import annotations

from tbm_twin.evidence.models import DeviationDirection
from tbm_twin.evidence.response_builder import (
    ResponseEvidenceConfig,
    build_global_robust_baselines,
    build_response_evidence,
)
from tbm_twin.process.episode_builder import build_excavation_episodes
from tbm_twin.process.weak_labels import label_operation_phases
from tbm_twin.trajectory.footprint_builder import build_spatial_footprints
from tests.conftest import base_rows, normalize_rows


def test_global_robust_baseline_is_reproducible(catalog, tmp_path) -> None:
    frame = normalize_rows(tmp_path, base_rows(), catalog)

    first = build_global_robust_baselines(frame, features=["advance_speed"], data_scope="fixture")
    second = build_global_robust_baselines(frame, features=["advance_speed"], data_scope="fixture")

    assert first["advance_speed"].baseline_id == second["advance_speed"].baseline_id


def test_response_deviation_uses_configured_baseline(catalog, tmp_path) -> None:
    rows = base_rows()
    frame = normalize_rows(tmp_path, rows, catalog)
    labeled = label_operation_phases(frame)
    episodes = build_excavation_episodes(labeled)
    footprints = build_spatial_footprints(labeled, episodes)
    config = ResponseEvidenceConfig(features=["advance_speed"])

    records = build_response_evidence(labeled, episodes, footprints, config=config)
    record = records[0]

    assert record.deviation is not None
    assert record.deviation.deviation_direction in {
        DeviationDirection.NEAR_BASELINE,
        DeviationDirection.UNDETERMINED,
    }
