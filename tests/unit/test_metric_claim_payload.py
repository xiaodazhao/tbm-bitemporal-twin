"""Tests for typed Stage 5A metric claim payload validation."""

from __future__ import annotations

from scripts.build_stage5a_claim_contract import _metric_payload_rows, build_stage5a_evaluator


def test_metric_payload_identity_value_and_probability_flags_are_enforced() -> None:
    rows = {row["case_id"]: row for row in _metric_payload_rows(build_stage5a_evaluator())}

    assert rows["M1_RAI_PAYLOAD_METRIC_NAME_GRCI"]["actual_reason"] == ("METRIC_IDENTITY_MISMATCH")
    assert rows["M3_RAI_VALUE_MISMATCH"]["actual_reason"] == "METRIC_VALUE_MISMATCH"
    assert rows["M5_RAI_IS_PROBABILITY_TRUE"]["actual_reason"] == "METRIC_SEMANTICS_MISMATCH"
    assert rows["M12_VALID_RAI_PAYLOAD"]["actual_expressibility"] == "EXPRESSIBLE"
