"""Stage 5B metric-backed proposal tests."""

from __future__ import annotations

from tests.unit.stage5b_helpers import read_csv, read_jsonl, rows_by_type, stage5b_artifact


def test_metric_claim_builder_keeps_unavailable_metrics_as_abstentions(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    summary = rows_by_type(read_csv(artifact / "claim_type_summary.csv"))
    claims = read_jsonl(artifact / "typed_engineering_claims.jsonl")

    assert int(summary["OPERATIONAL_RESPONSE_ATTENTION"]["opportunity_count"]) == 1375
    assert int(summary["OPERATIONAL_RESPONSE_ATTENTION"]["expressible_count"]) == 174
    assert int(summary["OPERATIONAL_RESPONSE_ATTENTION"]["abstain_count"]) == 1201
    assert int(summary["COUPLED_ATTENTION_REVIEW"]["opportunity_count"]) == 190
    assert not any(
        row["claim_type"] == "COUPLED_ATTENTION_REVIEW" and row["state_role"] != "DAILY_REVIEW_CELL"
        for row in claims
    )


def test_metric_proposals_reference_formal_stage4_metric_payloads(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    proposals = read_jsonl(artifact / "claim_proposals.jsonl")
    integrity_rows = read_csv(artifact / "metric_proposal_integrity_audit.csv")
    metric_proposals = [
        row
        for row in proposals
        if row["claim_type"]
        in {
            "OPERATIONAL_RESPONSE_ATTENTION",
            "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
            "COUPLED_ATTENTION_REVIEW",
            "FORWARD_GEOLOGICAL_ATTENTION",
        }
    ]
    available = [row for row in metric_proposals if row["claim_value"] is not None]
    unavailable = [row for row in metric_proposals if row["claim_value"] is None]

    assert metric_proposals
    assert available
    assert unavailable
    assert all(
        row["claim_value"]["source_metric_id"] == row["support_refs"][0]["support_id"]
        for row in available
    )
    assert all(row["claim_value"]["is_probability"] is False for row in available)
    assert all(row["claim_value"]["is_hazard_probability"] is False for row in available)
    assert all(row["claim_value"]["is_causal_estimate"] is False for row in available)
    assert all(
        row["integrity_status"] in {"AVAILABLE_VALUE_MATCH", "UNAVAILABLE_VALUE_PRESERVED_NULL"}
        for row in integrity_rows
    )
