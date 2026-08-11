"""Stage 5B typed claim output boundary tests."""

from __future__ import annotations

from tests.unit.stage5b_helpers import read_csv, read_jsonl, stage5b_artifact

FORBIDDEN_TOP_LEVEL_FIELDS = {
    "decision_id",
    "proposal_id",
    "opportunity_id",
    "resolved_support_refs",
}


def test_typed_engineering_claim_output_has_no_stage5b_extra_fields(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    rows = read_jsonl(artifact / "typed_engineering_claims.jsonl")

    assert rows
    for row in rows:
        assert FORBIDDEN_TOP_LEVEL_FIELDS.isdisjoint(row)
        assert row["metadata"]["decision_id"]
        assert row["metadata"]["proposal_id"]
        assert row["metadata"]["opportunity_id"]


def test_typed_claim_schema_validation_audit_is_clean(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    rows = read_csv(artifact / "typed_claim_schema_validation_audit.csv")

    assert rows
    assert all(row["validation_status"] == "PASS" for row in rows)
    assert all(row["extra_field_count"] == "0" for row in rows)
