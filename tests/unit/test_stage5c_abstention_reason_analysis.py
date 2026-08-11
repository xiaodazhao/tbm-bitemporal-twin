"""Stage 5C abstention taxonomy tests."""

from __future__ import annotations

from tests.unit.stage5c_helpers import read_csv, stage5c_artifact


def test_stage5c_abstention_reason_analysis(tmp_path_factory) -> None:
    artifact = stage5c_artifact(tmp_path_factory)
    reasons = {
        row["abstention_reason"]: row
        for row in read_csv(artifact / "abstention_reason_summary.csv")
    }
    groups = {
        row["analysis_reason_group"]: row
        for row in read_csv(artifact / "abstention_reason_group_summary.csv")
    }

    assert reasons["UNKNOWN_SOURCE_VALUE"]["count"] == "1078"
    assert reasons["CONTEXT_ONLY_ROLE"]["analysis_reason_group"] == "CONTEXT_POLICY_BOUNDARY"
    assert groups["CONTEXT_POLICY_BOUNDARY"]["count"] == "1185"
    assert sum(int(row["count"]) for row in reasons.values()) == 2400
