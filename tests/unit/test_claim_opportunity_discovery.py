"""Stage 5B opportunity discovery tests."""

from __future__ import annotations

from tests.unit.stage5b_helpers import (
    read_csv,
    read_json,
    read_jsonl,
    rows_by_type,
    stage5b_artifact,
)


def test_claim_opportunity_discovery_uses_only_frozen_six_claim_types(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    summary = rows_by_type(read_csv(artifact / "claim_type_summary.csv"))
    universe = read_json(artifact / "claim_opportunity_universe.json")
    opportunities = read_jsonl(artifact / "claim_opportunities.jsonl")

    assert set(summary) == {
        "OPERATIONAL_RESPONSE_ATTENTION",
        "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
        "COUPLED_ATTENTION_REVIEW",
        "FORWARD_GEOLOGICAL_ATTENTION",
        "OBSERVED_GEOLOGICAL_CONDITION",
        "FORECAST_GEOLOGICAL_CONDITION",
    }
    assert len(opportunities) == sum(int(row["opportunity_count"]) for row in summary.values())
    assert all(row["source_origin"] == "FORMAL_UPSTREAM" for row in opportunities)
    assert {row["claim_type"] for row in universe} == set(summary)
