"""Tests for authoritative upstream spatial support resolution."""

from __future__ import annotations

from pathlib import Path

from scripts.build_stage5a_claim_contract import (
    _authoritative_support_resolution_rows,
    _build_lookup,
    build_stage5a_evaluator,
)


def test_support_ref_declared_scope_is_not_used_as_authority() -> None:
    rows = _authoritative_support_resolution_rows(
        build_stage5a_evaluator(),
        _build_lookup(Path.cwd()),
    )

    assert {row["proposal_override_used"] for row in rows} == {"false"}
    spoof_rows = [row for row in rows if row["declared_spatial_scope"] == "INTERVAL:190.0-210.0"]
    assert spoof_rows
    assert spoof_rows[0]["resolved_spatial_scope"] == "INTERVAL:100.0-110.0"
    assert spoof_rows[0]["scope_match"] == "false"
    assert spoof_rows[0]["abstention_reason"] == "SUPPORT_SCOPE_MISMATCH"
