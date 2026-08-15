"""Stage 5B reference integrity tests."""

from __future__ import annotations

from tests.unit.stage5b_helpers import read_csv, stage5b_artifact


def test_claim_build_reference_audit_is_fully_valid(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    rows = read_csv(artifact / "claim_build_reference_audit.csv")

    assert rows
    assert all(int(row["invalid_count"]) == 0 for row in rows)
    assert all(int(row["valid_count"]) == int(row["total_count"]) for row in rows)
