"""Tests for authoritative Stage 5A claim subject binding."""

from __future__ import annotations

from pathlib import Path

from scripts.build_stage5a_claim_contract import (
    _build_lookup,
    _claim_subject_binding_rows,
    build_stage5a_evaluator,
)


def test_metric_claim_subject_fields_must_match_upstream_metric() -> None:
    evaluator = build_stage5a_evaluator()
    rows = {
        row["case_id"]: row
        for row in _claim_subject_binding_rows(evaluator, _build_lookup(Path.cwd()))
    }

    assert rows["SB1_FAKE_BITEMPORAL_VERSION"]["abstention_reason"] == ("CLAIM_SUBJECT_MISMATCH")
    assert rows["SB2_WRONG_BASE_STATE_VERSION"]["abstention_reason"] == ("CLAIM_SUBJECT_MISMATCH")
    assert rows["SB3_WRONG_CELL_ID"]["abstention_reason"] == "CLAIM_SUBJECT_MISMATCH"
    assert rows["SB4_WRONG_VALID_DATE"]["abstention_reason"] == "CLAIM_SUBJECT_MISMATCH"
    assert rows["SB5_WRONG_STATE_ROLE"]["abstention_reason"] == "STATE_ROLE_NOT_ALLOWED"
    assert rows["SB6_SUBJECT_MATCHES_METRIC"]["subject_match"] == "true"
    assert rows["SB6_SUBJECT_MATCHES_METRIC"]["decision"] == "EXPRESSIBLE"
    assert rows["SB7_SCOPE_CELL_DIFFERS_FROM_METRIC"]["abstention_reason"] == (
        "CLAIM_SUBJECT_MISMATCH"
    )
    assert rows["SB8_FAKE_DAILY_STATE_ID"]["abstention_reason"] == ("CLAIM_SUBJECT_MISMATCH")


def test_geological_condition_subject_fields_must_match_stage3_link_context() -> None:
    evaluator = build_stage5a_evaluator()
    rows = {
        row["case_id"]: row
        for row in _claim_subject_binding_rows(evaluator, _build_lookup(Path.cwd()))
    }

    assert rows["GS1_OBSERVED_GEOLOGICAL_SUBJECT_MATCH"]["subject_source_type"] == (
        "GEOLOGICAL_EVIDENCE_BACKED"
    )
    assert rows["GS1_OBSERVED_GEOLOGICAL_SUBJECT_MATCH"]["decision"] == "EXPRESSIBLE"
    assert rows["GS6_FORECAST_GEOLOGICAL_SUBJECT_MATCH"]["decision"] == "EXPRESSIBLE"
    assert rows["GS2_OBSERVED_FAKE_BITEMPORAL_VERSION"]["abstention_reason"] == (
        "CLAIM_SUBJECT_MISMATCH"
    )
    assert rows["GS3_OBSERVED_WRONG_CELL_ID"]["abstention_reason"] == ("CLAIM_SUBJECT_MISMATCH")
    assert rows["GS4_OBSERVED_WRONG_VALID_DATE"]["abstention_reason"] == ("CLAIM_SUBJECT_MISMATCH")
    assert rows["GS7_FORECAST_FAKE_STATE_VERSION"]["abstention_reason"] == (
        "CLAIM_SUBJECT_MISMATCH"
    )
    assert rows["GS8_FORECAST_WRONG_CELL_DATE_ROLE"]["abstention_reason"] == (
        "CLAIM_SUBJECT_MISMATCH"
    )
    assert rows["GS_FINAL_1_OBSERVED_ALL_FAKE_SUBJECT"]["abstention_reason"] == (
        "CLAIM_SUBJECT_MISMATCH"
    )
    assert rows["GS_FINAL_2_FORECAST_ALL_FAKE_SUBJECT"]["abstention_reason"] == (
        "CLAIM_SUBJECT_MISMATCH"
    )
