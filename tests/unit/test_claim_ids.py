"""Tests for Stage 5A deterministic proposal and decision IDs."""

from __future__ import annotations

from scripts.build_stage5a_claim_contract import _fixed_case_rows, build_stage5a_evaluator


def test_claim_decision_ids_repeat_for_same_business_inputs() -> None:
    evaluator = build_stage5a_evaluator()
    first = _fixed_case_rows(evaluator)
    second = _fixed_case_rows(evaluator)

    assert [row["proposal_id"] for row in first] == [row["proposal_id"] for row in second]
    assert [row["decision_id"] for row in first] == [row["decision_id"] for row in second]
