"""Tests that caller-supplied epistemic fields cannot spoof proof."""

from __future__ import annotations

from scripts.build_stage5a_claim_contract import _epistemic_proof_rows, build_stage5a_evaluator


def test_proposal_self_declared_epistemic_status_cannot_make_claim_expressible() -> None:
    rows = {row["case_id"]: row for row in _epistemic_proof_rows(build_stage5a_evaluator())}

    assert rows["E1_FORECAST_SPOOFED_BY_PROPOSAL_FIELD"]["actual_expressibility"] == "ABSTAIN"
    assert rows["E2_OBSERVED_SPOOFED_BY_PROPOSAL_FIELD"]["actual_expressibility"] == "ABSTAIN"
    assert rows["E4_REAL_FORWARD_EVIDENCE_FORECAST_RESOLVED"]["actual_expressibility"] == (
        "EXPRESSIBLE"
    )
