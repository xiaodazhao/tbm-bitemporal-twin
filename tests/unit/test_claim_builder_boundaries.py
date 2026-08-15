"""Stage 5B boundary hard-check tests."""

from __future__ import annotations

from tests.unit.stage5b_helpers import read_csv, stage5b_artifact


def test_stage5b_boundary_hard_checks_have_zero_issues(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    rows = read_csv(artifact / "stage5b_hard_check.csv")
    by_name = {row["check_name"]: row for row in rows}

    assert by_name["issue_count"]["actual"] == "0"
    assert all(row["status"] == "PASS" for row in rows)
    for check_name in [
        "standalone_local_background_claim_count",
        "forward_grci_claim_count",
        "forecast_promoted_to_observed_count",
        "unknown_factual_claim_count",
        "response_to_geological_fact_claim_count",
        "unlocated_spatial_factual_claim_count",
        "metric_value_mismatch_count",
        "claim_subject_decision_mismatch_count",
    ]:
        assert by_name[check_name]["actual"] == "0"
