"""Stage 5C claim type expressibility tests."""

from __future__ import annotations

from tests.unit.stage5c_helpers import read_csv, stage5c_artifact


def test_stage5c_claim_type_expressibility(tmp_path_factory) -> None:
    artifact = stage5c_artifact(tmp_path_factory)
    rows = {row["claim_type"]: row for row in read_csv(artifact / "claim_type_expressibility.csv")}

    assert set(rows) == {
        "OPERATIONAL_RESPONSE_ATTENTION",
        "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
        "COUPLED_ATTENTION_REVIEW",
        "FORWARD_GEOLOGICAL_ATTENTION",
        "OBSERVED_GEOLOGICAL_CONDITION",
        "FORECAST_GEOLOGICAL_CONDITION",
    }
    assert rows["OPERATIONAL_RESPONSE_ATTENTION"]["opportunity_count"] == "1375"
    assert rows["FORECAST_GEOLOGICAL_CONDITION"]["expressible_count"] == "4783"
