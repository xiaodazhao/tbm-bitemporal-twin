"""Stage 5B geological claim builder tests."""

from __future__ import annotations

from tests.unit.stage5b_helpers import read_csv, read_jsonl, rows_by_type, stage5b_artifact


def test_geological_claim_builder_materializes_observed_and_forecast_attributes(
    tmp_path_factory,
) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    summary = rows_by_type(read_csv(artifact / "claim_type_summary.csv"))
    claims = read_jsonl(artifact / "typed_engineering_claims.jsonl")

    assert int(summary["OBSERVED_GEOLOGICAL_CONDITION"]["expressible_count"]) > 0
    assert int(summary["FORECAST_GEOLOGICAL_CONDITION"]["expressible_count"]) > 0
    assert any(row["claim_type"] == "OBSERVED_GEOLOGICAL_CONDITION" for row in claims)
    assert any(row["claim_type"] == "FORECAST_GEOLOGICAL_CONDITION" for row in claims)
    assert not any(row["state_role"] == "LOCAL_BACKGROUND_CELL" for row in claims)


def test_unknown_geological_attributes_abstain_without_factual_claim(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    abstentions = read_jsonl(artifact / "claim_abstentions.jsonl")
    claims = read_jsonl(artifact / "typed_engineering_claims.jsonl")

    assert any(row["abstention_reason"] == "UNKNOWN_SOURCE_VALUE" for row in abstentions)
    assert not any(row["claim_value"].get("normalized_value") == "UNKNOWN" for row in claims)
