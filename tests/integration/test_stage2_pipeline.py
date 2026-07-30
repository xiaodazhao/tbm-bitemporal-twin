from __future__ import annotations

import json
import subprocess
import sys

import pandas as pd

from tbm_twin.process.episode_builder import build_excavation_episodes
from tbm_twin.process.weak_labels import label_operation_phases
from tbm_twin.trajectory.footprint_builder import build_spatial_footprints
from tests.conftest import base_rows, normalize_rows


def test_stage2_validation_cli_writes_non_boolean_applicability(catalog, tmp_path) -> None:
    labeled = label_operation_phases(normalize_rows(tmp_path, base_rows(), catalog))
    episodes = build_excavation_episodes(labeled)
    footprints = build_spatial_footprints(labeled, episodes)
    date_dir = tmp_path / "stage1" / "2026-01-01"
    date_dir.mkdir(parents=True)
    (date_dir / "episodes.json").write_text(
        json.dumps([episode.model_dump(mode="json") for episode in episodes]),
        encoding="utf-8",
    )
    (date_dir / "spatial_footprints.json").write_text(
        json.dumps([footprint.model_dump(mode="json") for footprint in footprints]),
        encoding="utf-8",
    )
    labeled.to_parquet(date_dir / "normalized_plc.parquet")
    geology = tmp_path / "geology.csv"
    geology.write_text(
        "record_id,text\ng1,TSP forecast DK0+090 DK0+120\ng2,unclear geology note\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_stage2_evidence.py",
            "--stage1-artifact-dir",
            str(tmp_path / "stage1"),
            "--geology-input",
            str(geology),
            "--dates",
            "2026-01-01",
            "--output-dir",
            str(tmp_path / "stage2"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    diagnostics = json.loads(
        (tmp_path / "stage2" / "stage2_diagnostics.json").read_text(encoding="utf-8")
    )
    assignments = pd.read_csv(tmp_path / "stage2" / "applicability_summary.csv")
    assert diagnostics["future_evidence_leakage_count"] == 0
    assert diagnostics["available_time_unknown_count"] == 2
    assert diagnostics["real_data_temporal_applicability_validation"] == "NOT_EVALUABLE"
    assert "not_applicable_to_any_episode_count" not in diagnostics
    assert {"APPLICABLE", "APPLICABLE_WITH_QUALIFICATION", "UNDETERMINED"} & set(
        assignments["result"]
    )
    assert (tmp_path / "stage2" / "stage21_validation_report.md").exists()
    assert (tmp_path / "stage2" / "epistemic_mapping_audit.csv").exists()
    assert (tmp_path / "stage2" / "chainage_anomaly_audit.csv").exists()
    assert (tmp_path / "stage2" / "applicability_result_matrix.csv").exists()
    assert (tmp_path / "stage2" / "evidence_level_applicability_summary.csv").exists()
    assert (tmp_path / "stage2" / "temporal_validation_status.json").exists()
