"""Stage 5B unavailable metric missingness tests."""

from __future__ import annotations

from tests.unit.stage5b_helpers import read_csv, read_jsonl, stage5b_artifact


def test_unavailable_metric_preserves_null_payload_value(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    proposals = read_jsonl(artifact / "claim_proposals.jsonl")
    integrity_rows = read_csv(artifact / "metric_proposal_integrity_audit.csv")

    unavailable_metric_ids = {
        row["source_metric_id"]
        for row in integrity_rows
        if row["integrity_status"] == "UNAVAILABLE_VALUE_PRESERVED_NULL"
    }
    assert unavailable_metric_ids
    assert all(
        row["claim_value"] is None
        for row in proposals
        if row["support_refs"][0]["support_id"] in unavailable_metric_ids
    )
    assert not any(row["upstream_null_to_numeric_substitution"] == "true" for row in integrity_rows)
