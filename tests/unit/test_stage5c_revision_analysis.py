"""Stage 5C bitemporal revision analysis tests."""

from __future__ import annotations

from tests.unit.stage5c_helpers import read_csv, stage5c_artifact


def test_stage5c_revision_analysis(tmp_path_factory) -> None:
    artifact = stage5c_artifact(tmp_path_factory)
    chains = read_csv(artifact / "revision_chain_expressibility_analysis.csv")
    transitions = read_csv(artifact / "revision_claim_transition_analysis.csv")
    key_rows = read_csv(artifact / "revision_comparison_key_audit.csv")

    assert chains
    assert transitions
    assert all(row["duplicate_key_count"] == "0" for row in key_rows)
