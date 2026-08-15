"""Stage 5B materialization invariant tests."""

from __future__ import annotations

from collections import Counter

from tests.unit.stage5b_helpers import read_jsonl, stage5b_artifact


def test_expressible_decision_materializes_exactly_one_claim(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    decisions = read_jsonl(artifact / "claim_decisions.jsonl")
    claims = read_jsonl(artifact / "typed_engineering_claims.jsonl")
    claim_count_by_decision = Counter(row["metadata"]["decision_id"] for row in claims)

    for decision in decisions:
        if decision["expressibility"] == "EXPRESSIBLE":
            assert claim_count_by_decision[decision["decision_id"]] == 1
        else:
            assert claim_count_by_decision[decision["decision_id"]] == 0


def test_materialized_claims_use_resolved_decision_support_refs(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    decisions = {row["decision_id"]: row for row in read_jsonl(artifact / "claim_decisions.jsonl")}
    claims = read_jsonl(artifact / "typed_engineering_claims.jsonl")

    assert claims
    assert all(decisions[row["metadata"]["decision_id"]]["resolved_support_refs"] for row in claims)
    assert all(
        row["trace_refs"]
        == [
            ref["support_id"]
            for ref in decisions[row["metadata"]["decision_id"]]["resolved_support_refs"]
        ]
        for row in claims
    )
    assert not any(
        ref.get("epistemic_status") or ref.get("spatial_scope") or ref.get("state_role")
        for row in claims
        for ref in row["support_refs"]
    )
