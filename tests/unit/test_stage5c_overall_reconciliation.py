"""Stage 5C overall reconciliation tests."""

from __future__ import annotations

from tests.unit.stage5c_helpers import read_csv, stage5c_artifact


def test_stage5c_overall_reconciliation(tmp_path_factory) -> None:
    artifact = stage5c_artifact(tmp_path_factory)
    overall = read_csv(artifact / "overall_expressibility_summary.csv")[0]
    reconciliation = read_csv(artifact / "analysis_reconciliation_audit.csv")

    assert overall["opportunity_count"] == "8679"
    assert overall["expressible_count"] == "6279"
    assert overall["abstain_count"] == "2400"
    assert overall["materialized_claim_count"] == overall["expressible_count"]
    assert all(row["difference"] == "0" for row in reconciliation)
