"""Stage 5B deduplication tests."""

from __future__ import annotations

from tests.unit.stage5b_helpers import read_csv, read_jsonl, stage5b_artifact


def test_stage5b_ids_are_unique_after_semantic_deduplication(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    outputs = {
        "opportunity": [
            row["opportunity_id"] for row in read_jsonl(artifact / "claim_opportunities.jsonl")
        ],
        "proposal": [row["proposal_id"] for row in read_jsonl(artifact / "claim_proposals.jsonl")],
        "decision": [row["decision_id"] for row in read_jsonl(artifact / "claim_decisions.jsonl")],
        "claim": [
            row["claim_id"] for row in read_jsonl(artifact / "typed_engineering_claims.jsonl")
        ],
    }

    for ids in outputs.values():
        assert len(ids) == len(set(ids))


def test_dedup_audit_reports_no_duplicate_business_ids(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    rows = read_csv(artifact / "claim_deduplication_audit.csv")
    duplicate_rows = [row for row in rows if row["semantic_key"].startswith("duplicate_")]

    assert duplicate_rows
    assert all(int(row["duplicate_removed_count"]) == 0 for row in duplicate_rows)
