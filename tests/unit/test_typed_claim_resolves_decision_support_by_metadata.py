"""Stage 5B claim-to-decision support resolution tests."""

from __future__ import annotations

from tests.unit.stage5b_helpers import read_csv, read_jsonl, stage5b_artifact

EXPECTED_CLAIM_TYPES = {
    "OPERATIONAL_RESPONSE_ATTENTION",
    "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
    "COUPLED_ATTENTION_REVIEW",
    "OBSERVED_GEOLOGICAL_CONDITION",
    "FORECAST_GEOLOGICAL_CONDITION",
}


def test_typed_claim_resolves_decision_support_by_metadata(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    decisions = {row["decision_id"]: row for row in read_jsonl(artifact / "claim_decisions.jsonl")}
    claims = read_jsonl(artifact / "typed_engineering_claims.jsonl")

    matched_types: set[str] = set()
    for claim in claims:
        decision = decisions[claim["metadata"]["decision_id"]]
        matched_types.add(claim["claim_type"])
        assert claim["metadata"]["proposal_id"] == decision["proposal_id"]
        assert sorted(claim["trace_refs"]) == sorted(
            ref["support_id"] for ref in decision["resolved_support_refs"]
        )

    assert matched_types >= EXPECTED_CLAIM_TYPES


def test_claim_reference_audit_uses_metadata_resolution_path(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    rows = {
        row["check_name"]: row for row in read_csv(artifact / "claim_build_reference_audit.csv")
    }

    for check_name in [
        "CLAIM_TO_OPPORTUNITY",
        "CLAIM_TO_PROPOSAL",
        "CLAIM_TO_DECISION",
        "CLAIM_TRACE_TO_RESOLVED_SUPPORT",
    ]:
        assert rows[check_name]["invalid_count"] == "0"
