"""Stage 5B available metric exact-value integrity tests."""

from __future__ import annotations

from tests.unit.stage5b_helpers import read_csv, stage5b_artifact


def test_available_metric_exact_value_is_preserved(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    integrity_rows = read_csv(artifact / "metric_proposal_integrity_audit.csv")
    available = [
        row for row in integrity_rows if row["integrity_status"] == "AVAILABLE_VALUE_MATCH"
    ]

    assert available
    assert all(row["proposal_metric_value"] == row["upstream_metric_value"] for row in available)
    assert not any(row["integrity_status"] == "MISMATCH" for row in integrity_rows)
