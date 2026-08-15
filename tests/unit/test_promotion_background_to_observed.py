"""Tests that BACKGROUND_TO_OBSERVED promotion has a directly matching case."""

from __future__ import annotations

from scripts.build_stage5a_claim_contract import (
    _adversarial_case_rows,
    _metric_payload_rows,
    _promotion_rule_registry_rows,
    build_stage5a_evaluator,
)
from tbm_twin.claims.contracts import load_claim_contracts


def test_background_to_observed_promotion_uses_background_case() -> None:
    adversarial = {row["case_id"]: row for row in _adversarial_case_rows(build_stage5a_evaluator())}
    promotion = {
        row["promotion_rule"]: row for row in _promotion_rule_registry_rows(load_claim_contracts())
    }

    assert adversarial["P_BG_1_BACKGROUND_PROMOTED_TO_OBSERVED"]["actual_reason"] == (
        "EPISTEMIC_PROMOTION_FORBIDDEN"
    )
    assert (
        "P_BG_1_BACKGROUND_PROMOTED_TO_OBSERVED"
        in (promotion["BACKGROUND_TO_OBSERVED"]["test_case_ids"])
    )


def test_attention_to_causal_estimate_uses_direct_causal_cases() -> None:
    evaluator = build_stage5a_evaluator()
    metric_rows = {row["case_id"]: row for row in _metric_payload_rows(evaluator)}
    promotion = {
        row["promotion_rule"]: row for row in _promotion_rule_registry_rows(load_claim_contracts())
    }

    assert metric_rows["P_CAUSAL_1_GRCI_CAUSAL_ESTIMATE_TRUE"]["actual_reason"] == (
        "METRIC_SEMANTICS_MISMATCH"
    )
    assert metric_rows["P_CAUSAL_2_RAI_CAUSAL_ESTIMATE_TRUE"]["actual_reason"] == (
        "METRIC_SEMANTICS_MISMATCH"
    )
    assert (
        "P_CAUSAL_1_GRCI_CAUSAL_ESTIMATE_TRUE"
        in (promotion["ATTENTION_TO_CAUSAL_ESTIMATE"]["test_case_ids"])
    )
    assert (
        "P_CAUSAL_2_RAI_CAUSAL_ESTIMATE_TRUE"
        in (promotion["ATTENTION_TO_CAUSAL_ESTIMATE"]["test_case_ids"])
    )
    assert (
        "CASE_12_GRCI_PROBABILITY_MISUSE"
        not in (promotion["ATTENTION_TO_CAUSAL_ESTIMATE"]["test_case_ids"])
    )
