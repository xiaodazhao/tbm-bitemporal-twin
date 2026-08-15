"""Tests that Stage 5A real fixtures are evaluated with real subject fields."""

from __future__ import annotations

from pathlib import Path

from scripts.build_stage5a_claim_contract import _real_fixture_rows, build_stage5a_evaluator


def test_real_fixture_subject_fields_match_resolved_stage4_subject() -> None:
    rows = _real_fixture_rows(Path.cwd(), build_stage5a_evaluator())
    metric_rows = [row for row in rows if row.get("proposal_bitemporal_version_id")]

    assert metric_rows
    assert {row["subject_match"] for row in metric_rows} == {"true"}
    for row in metric_rows:
        assert row["proposal_bitemporal_version_id"] == row["resolved_bitemporal_version_id"]
        assert row["proposal_base_state_version_id"] == row["resolved_base_state_version_id"]
        assert row["proposal_daily_state_id"] == row["resolved_daily_state_id"]
        assert row["proposal_cell_id"] == row["resolved_cell_id"]
        assert row["proposal_valid_date"] == row["resolved_valid_date"]
        assert row["proposal_state_role"] == row["resolved_state_role"]


def test_real_geological_fixture_subject_fields_match_resolved_stage3_context() -> None:
    rows = _real_fixture_rows(Path.cwd(), build_stage5a_evaluator())
    by_fixture = {row["fixture_id"]: row for row in rows}

    observed = by_fixture["REAL_OBSERVED_GEOLOGICAL_CONDITION_SUBJECT"]
    forecast = by_fixture["REAL_FORECAST_GEOLOGICAL_CONDITION_SUBJECT"]
    assert observed["subject_match"] == "true"
    assert observed["expressibility"] == "EXPRESSIBLE"
    assert forecast["subject_match"] == "true"
    assert forecast["expressibility"] == "EXPRESSIBLE"
    assert observed["proposal_cell_id"] == observed["resolved_cell_id"]
    assert forecast["proposal_valid_date"] == forecast["resolved_valid_date"]
