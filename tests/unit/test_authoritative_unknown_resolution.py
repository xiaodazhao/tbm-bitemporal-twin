"""Tests that UNKNOWN source values are resolved from frozen upstream evidence."""

from __future__ import annotations

from scripts.build_stage5a_claim_contract import (
    _unknown_detection_rows,
    build_stage5a_evaluator,
)


def test_unknown_source_value_cannot_be_overridden_by_proposal_flag() -> None:
    rows = {row["case_id"]: row for row in _unknown_detection_rows(build_stage5a_evaluator())}

    assert rows["U1_UPSTREAM_UNKNOWN_PROPOSAL_FLAG_FALSE"]["actual_reason"] == (
        "UNKNOWN_SOURCE_VALUE"
    )
    assert rows["U2_UPSTREAM_UNKNOWN_PROPOSAL_VALUE_UNKNOWN"]["actual_reason"] == (
        "UNKNOWN_SOURCE_VALUE"
    )
    assert rows["U3_UPSTREAM_UNKNOWN_PROPOSAL_VALUE_III"]["actual_reason"] == (
        "UNKNOWN_SOURCE_VALUE"
    )
    assert rows["U4_UPSTREAM_IV_PROPOSAL_IV"]["actual_expressibility"] == "EXPRESSIBLE"
    assert rows["U5_UPSTREAM_IV_PROPOSAL_III"]["actual_reason"] == ("ATTRIBUTE_VALUE_MISMATCH")
    assert rows["U6_ATTRIBUTE_NOT_FOUND"]["actual_reason"] == "ATTRIBUTE_NOT_FOUND"
