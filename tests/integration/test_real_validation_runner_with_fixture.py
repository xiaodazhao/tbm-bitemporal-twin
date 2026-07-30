from __future__ import annotations

import json

import pandas as pd

from tbm_twin.validation.runner import run_stage1_validation
from tests.conftest import base_rows, write_plc_csv


def test_validation_runner_single_success_and_one_failure(tmp_path) -> None:
    plc_dir = tmp_path / "plc"
    artifact_dir = tmp_path / "artifacts"
    plc_dir.mkdir()
    write_plc_csv(plc_dir / "tbm_data_20231230.csv", base_rows())

    result = run_stage1_validation(
        plc_data_dir=plc_dir,
        dates=["2023-12-30", "2023-12-28"],
        artifact_dir=artifact_dir,
    )

    assert result["success_count"] + result["warning_count"] == 1
    assert result["failed_count"] == 1
    assert (artifact_dir / "2023-12-30" / "source_asset.json").exists()
    assert (artifact_dir / "2023-12-30" / "episode_review.csv").exists()
    assert (artifact_dir / "validation_summary.csv").exists()
    assert (artifact_dir / "plc_episode_reference_review.csv").exists()
    failed = json.loads(
        (artifact_dir / "2023-12-28" / "validation_summary.json").read_text(encoding="utf-8")
    )
    assert failed["error"]["error_type"] == "FileNotFoundError"


def test_manual_template_fields_are_complete(tmp_path) -> None:
    plc_dir = tmp_path / "plc"
    artifact_dir = tmp_path / "artifacts"
    plc_dir.mkdir()
    write_plc_csv(plc_dir / "tbm_data_20231230.csv", base_rows())

    run_stage1_validation(
        plc_data_dir=plc_dir,
        dates=["2023-12-30"],
        artifact_dir=artifact_dir,
    )

    template = pd.read_csv(artifact_dir / "plc_episode_reference_review.csv")

    assert list(template.columns) == [
        "date",
        "system_episode_id",
        "plc_support_label",
        "supported_core_start",
        "supported_core_end",
        "merge_candidate",
        "split_candidate",
        "signal_conflicts",
        "review_confidence",
        "review_notes",
    ]
