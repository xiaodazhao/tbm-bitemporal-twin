"""Stage 5B candidate-to-formal semantic equivalence tests."""

from __future__ import annotations

from tests.unit.stage5b_helpers import read_csv, stage5b_formal_artifact


def test_stage5b_candidate_formal_semantic_equivalence(tmp_path_factory) -> None:
    artifact = stage5b_formal_artifact(tmp_path_factory)
    rows = read_csv(artifact / "stage5b_candidate_formal_semantic_audit.csv")

    assert rows
    assert all(row["business_diff_count"] == "0" for row in rows)
    assert all(row["status"] == "PASS" for row in rows)
