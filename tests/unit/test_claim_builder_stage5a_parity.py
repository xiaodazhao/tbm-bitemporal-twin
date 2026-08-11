"""Stage 5B Frozen Stage5A parity tests."""

from __future__ import annotations

from tests.unit.stage5b_helpers import read_csv, stage5b_artifact


def test_stage5b_decisions_match_repeated_frozen_stage5a_evaluator(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    rows = read_csv(artifact / "claim_contract_parity_audit.csv")

    assert rows
    assert all(row["decision_mismatch"] == "false" for row in rows)
    assert all(row["status"] == "PASS" for row in rows)
