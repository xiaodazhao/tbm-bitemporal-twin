"""Tests for Stage 5A promotion rule registry closure."""

from __future__ import annotations

from scripts.build_stage5a_claim_contract import (
    _contract_config_adversarial_rows,
    _promotion_rule_registry_rows,
)
from tbm_twin.claims.contracts import load_claim_contracts


def test_promotion_rules_declared_in_config_have_runtime_handlers() -> None:
    rows = _promotion_rule_registry_rows(load_claim_contracts())

    assert len(rows) == 5
    assert {row["status"] for row in rows} == {"PASS"}


def test_unknown_promotion_rule_fails_contract_validation() -> None:
    rows = {
        row["case_id"]: row for row in _contract_config_adversarial_rows(load_claim_contracts())
    }

    assert rows["C1_UNKNOWN_PROMOTION_RULE"]["actual_status"] == "FAIL"
    assert rows["C2_UNKNOWN_SUPPORT_KIND"]["actual_status"] == "MODEL_ERROR"
