"""Tests for Stage 5A fixed and adversarial contract evaluation cases."""

from __future__ import annotations

from scripts.build_stage5a_claim_contract import (
    _adversarial_case_rows,
    _fixed_case_rows,
    build_stage5a_evaluator,
)


def test_twelve_fixed_contract_cases_match_expected_outcomes() -> None:
    evaluator = build_stage5a_evaluator()
    rows = _fixed_case_rows(evaluator)

    assert len(rows) == 12
    assert {row["status"] for row in rows} == {"PASS"}
    assert rows[0]["actual_expressibility"] == "EXPRESSIBLE"
    assert rows[4]["actual_reason"] == "EPISTEMIC_PROMOTION_FORBIDDEN"
    assert rows[7]["actual_reason"] == "SUPPORT_SEMANTIC_MISMATCH"


def test_adversarial_contract_cases_prove_runtime_enforcement() -> None:
    evaluator = build_stage5a_evaluator()
    rows = _adversarial_case_rows(evaluator)
    by_case = {row["case_id"]: row for row in rows}

    assert {row["status"] for row in rows} == {"PASS"}
    assert by_case["A1_FORECAST_WITHOUT_FORECAST_PROOF"]["actual_reason"] == (
        "REQUIRED_EPISTEMIC_STATUS_MISSING"
    )
    assert by_case["A2_OBSERVED_WITHOUT_OBSERVED_PROOF"]["actual_reason"] == (
        "REQUIRED_EPISTEMIC_STATUS_MISSING"
    )
    assert by_case["A3_FORECAST_SUPPORT_AS_OBSERVED"]["actual_reason"] == (
        "EPISTEMIC_PROMOTION_FORBIDDEN"
    )
    assert by_case["A5_EXTRA_UNSUPPORTED_SUPPORT_KIND"]["actual_reason"] == (
        "SUPPORT_KIND_NOT_ALLOWED"
    )
    assert by_case["A6_REQUIRED_SUPPORT_ONLY_TRACE"]["actual_reason"] == (
        "REQUIRED_SUPPORT_MISSING"
    )
    assert (
        by_case["M2_REQUIRED_EPISTEMIC_STATUS_CONTRACT_DRIVES_RUNTIME"]["actual_reason"]
        == "REQUIRED_EPISTEMIC_STATUS_MISSING"
    )
    assert by_case["M3_ALLOWED_SUPPORT_KINDS_CONTRACT_DRIVES_RUNTIME"]["actual_reason"] == (
        "SUPPORT_KIND_NOT_ALLOWED"
    )
