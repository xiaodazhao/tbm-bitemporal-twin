from __future__ import annotations

from tbm_twin.assets.models import SourceType
from tbm_twin.assets.registry import register_source_asset
from tbm_twin.process.episode_builder import build_excavation_episodes
from tbm_twin.process.weak_labels import label_operation_phases
from tbm_twin.timeseries.normalization import normalize_plc_csv
from tbm_twin.timeseries.quality import LARGE_JUMP_THRESHOLD_M
from tbm_twin.trajectory.footprint_builder import build_spatial_footprints
from tbm_twin.validation.config import load_validation_config
from tbm_twin.validation.diagnostics import (
    build_automatic_diagnostics,
    build_channel_audit,
    build_phase_intervals,
)
from tests.conftest import base_rows, write_plc_csv


def test_channel_audit_keeps_shield_head_anchor_explicit(tmp_path, catalog) -> None:
    rows = base_rows()
    rows[0]["导向盾中里程"] = 99.0
    raw_path = write_plc_csv(tmp_path / "tbm_data_20231230.csv", rows)

    audit = build_channel_audit(__import__("pandas").read_csv(raw_path), catalog)
    anchor = next(row for row in audit if row["canonical_name"] == "shield_head_chainage")

    assert anchor["matched_raw_column"] == "导向盾首里程"
    assert "导向盾中里程" not in anchor["candidate_raw_columns"]
    assert any("primary_anchor_selected" in warning for warning in anchor["warnings"])


def test_automatic_diagnostics_counts_untrusted_inconsistent_footprint(tmp_path, catalog) -> None:
    rows = base_rows()
    rows[1]["导向盾首里程"] = rows[0]["导向盾首里程"] + LARGE_JUMP_THRESHOLD_M + 1.0
    raw_path = write_plc_csv(tmp_path / "tbm_data_20231230.csv", rows)
    asset = register_source_asset(raw_path, SourceType.PLC_CSV)
    result = normalize_plc_csv(raw_path, asset, catalog)
    labeled = label_operation_phases(result.frame)
    episodes = build_excavation_episodes(labeled)
    footprints = build_spatial_footprints(labeled, episodes)
    intervals = build_phase_intervals(labeled)

    diagnostics = build_automatic_diagnostics(
        date="2023-12-30",
        raw_frame=__import__("pandas").DataFrame(rows),
        normalized_frame=result.frame,
        labeled_frame=labeled,
        quality_report=result.quality_report,
        phase_intervals=intervals,
        episodes=episodes,
        footprints=footprints,
        config=load_validation_config(),
    )

    assert diagnostics["footprint"]["inconsistent_count"] == 1
    assert diagnostics["footprint"]["precise_advance_suppressed_count"] == 1
