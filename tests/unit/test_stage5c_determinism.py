"""Stage 5C determinism tests."""

from __future__ import annotations

from tests.unit.stage5c_helpers import read_csv, stage5c_artifact


def test_stage5c_determinism(tmp_path_factory) -> None:
    artifact = stage5c_artifact(tmp_path_factory)
    rows = read_csv(artifact / "stage5c_determinism_audit.csv")

    assert rows == [
        {
            "check_name": "analysis_artifact_semantic_content",
            "semantic_diff_count": "0",
            "status": "PASS",
        }
    ]
