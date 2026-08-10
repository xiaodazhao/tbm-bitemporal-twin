"""Tests for Stage 5A spatial containment closure."""

from __future__ import annotations

from scripts.build_stage5a_claim_contract import _spatial_containment_rows, build_stage5a_evaluator


def test_spatial_containment_cases_cover_point_interval_cell_and_unlocated() -> None:
    rows = {row["case_id"]: row for row in _spatial_containment_rows(build_stage5a_evaluator())}

    assert rows["S1_POINT_INSIDE_INTERVAL"]["actual_expressibility"] == "EXPRESSIBLE"
    assert rows["S2_POINT_OUTSIDE_INTERVAL"]["actual_reason"] == "CLAIM_SCOPE_EXCEEDS_SUPPORT"
    assert rows["S7_POINT_SUPPORT_TO_CELL_FACT"]["actual_reason"] == ("CLAIM_SCOPE_EXCEEDS_SUPPORT")
    assert rows["S8_UNLOCATED_TO_CELL_FACT"]["actual_reason"] == "SPATIAL_SCOPE_UNAVAILABLE"
    assert rows["S9_METRIC_WRONG_CELL"]["actual_reason"] == "CLAIM_SUBJECT_MISMATCH"
    assert rows["SP1_SUPPORT_SCOPE_SPOOF_POINT_OUTSIDE_UPSTREAM"]["actual_reason"] == (
        "SUPPORT_SCOPE_MISMATCH"
    )
    assert rows["SP2_SUPPORT_SCOPE_DECLARED_MATCHES_UPSTREAM"]["actual_expressibility"] == (
        "EXPRESSIBLE"
    )
    assert rows["SP3_POINT_SUPPORT_SCOPE_EXPANDED_TO_INTERVAL"]["actual_reason"] == (
        "SUPPORT_SCOPE_MISMATCH"
    )
    assert (
        rows["SP4_NO_DECLARED_SCOPE_UPSTREAM_AUTHORITY_SUFFICIENT"]["actual_expressibility"]
        == "EXPRESSIBLE"
    )
