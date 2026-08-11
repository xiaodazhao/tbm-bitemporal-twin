"""Stage 5B abstention materialization tests."""

from __future__ import annotations

from collections import Counter

from tests.unit.stage5b_helpers import read_jsonl, stage5b_artifact


def test_abstain_decision_materializes_abstention_not_claim(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    decisions = read_jsonl(artifact / "claim_decisions.jsonl")
    claims = read_jsonl(artifact / "typed_engineering_claims.jsonl")
    abstentions = read_jsonl(artifact / "claim_abstentions.jsonl")
    claims_by_decision = Counter(row["metadata"]["decision_id"] for row in claims)
    abstentions_by_decision = Counter(row["decision_id"] for row in abstentions)

    for decision in decisions:
        if decision["expressibility"] == "ABSTAIN":
            assert claims_by_decision[decision["decision_id"]] == 0
            assert abstentions_by_decision[decision["decision_id"]] == 1


def test_abstention_reason_inventory_is_stage5a_structured(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    reasons = Counter(
        row["abstention_reason"] for row in read_jsonl(artifact / "claim_abstentions.jsonl")
    )

    assert reasons
    assert set(reasons) <= {
        "UNKNOWN_SOURCE_VALUE",
        "CONTEXT_ONLY_ROLE",
        "STATE_ROLE_NOT_ALLOWED",
        "REQUIRED_EPISTEMIC_STATUS_MISSING",
        "REQUIRED_METRIC_UNAVAILABLE",
    }
