"""Stage 5C metric availability tests."""

from __future__ import annotations

from tests.unit.stage5c_helpers import read_csv, stage5c_artifact


def test_stage5c_metric_availability_analysis(tmp_path_factory) -> None:
    artifact = stage5c_artifact(tmp_path_factory)
    rows = read_csv(artifact / "metric_availability_analysis.csv")

    assert any(row["metric_name"] == "RAI" and row["metric_status"] == "AVAILABLE" for row in rows)
    assert any(
        row["metric_name"] == "RAI"
        and row["metric_status"] == "NO_CELL_LINKED_OPERATIONAL_RESPONSE"
        for row in rows
    )
    assert sum(int(row["null_to_zero_interpretation_count"]) for row in rows) == 0
