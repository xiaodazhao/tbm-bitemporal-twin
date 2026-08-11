"""Stage 5B formal one-to-many geological context audit tests."""

from __future__ import annotations

from tests.unit.stage5b_helpers import read_csv, stage5b_artifact


def test_formal_one_to_many_geological_evidence_resolves_current_claim_context(
    tmp_path_factory,
) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    rows = read_csv(artifact / "geological_resolved_context_audit.csv")
    one_to_many = [row for row in rows if int(row["available_context_count"]) >= 2]

    assert one_to_many
    assert all(row["status"] == "PASS" for row in one_to_many)
    assert all(row["context_match"] == "true" for row in one_to_many)
