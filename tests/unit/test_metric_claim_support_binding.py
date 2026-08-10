"""Tests that typed metric payloads bind to formal Stage 4 support IDs."""

from __future__ import annotations

from scripts.build_stage5a_claim_contract import _metric_payload_rows, build_stage5a_evaluator


def test_metric_payload_value_must_match_referenced_support_record() -> None:
    rows = {row["case_id"]: row for row in _metric_payload_rows(build_stage5a_evaluator())}

    assert rows["M3_RAI_VALUE_MISMATCH"]["status"] == "PASS"
    assert rows["M10_METRIC_VALUE_NONSENSE"]["actual_expressibility"] == "MODEL_ERROR"
    assert rows["M11_METRIC_VALUE_OUT_OF_RANGE"]["actual_expressibility"] == "MODEL_ERROR"
