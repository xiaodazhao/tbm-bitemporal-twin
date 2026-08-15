"""Stage 5C rate integrity tests."""

from __future__ import annotations

from tests.unit.stage5c_helpers import read_csv, stage5c_artifact


def test_stage5c_rate_integrity(tmp_path_factory) -> None:
    artifact = stage5c_artifact(tmp_path_factory)
    rows = read_csv(artifact / "analysis_rate_integrity_audit.csv")

    assert rows
    assert all(row["invalid_count"] == "0" for row in rows)
