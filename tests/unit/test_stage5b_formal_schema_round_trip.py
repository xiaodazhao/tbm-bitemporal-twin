"""Stage 5B formal typed claim schema round-trip tests."""

from __future__ import annotations

from tbm_twin.claims.models import TypedEngineeringClaim
from tests.unit.stage5b_helpers import read_csv, read_jsonl, stage5b_formal_artifact


def test_stage5b_formal_schema_round_trip(tmp_path_factory) -> None:
    artifact = stage5b_formal_artifact(tmp_path_factory)
    claims = read_jsonl(artifact / "typed_engineering_claims.jsonl")
    audit_rows = read_csv(artifact / "typed_claim_schema_validation_audit.csv")

    assert claims
    assert len(claims) == len(audit_rows)
    assert all(row["validation_status"] == "PASS" for row in audit_rows)
    for row in claims:
        claim = TypedEngineeringClaim.model_validate(row)
        TypedEngineeringClaim.model_validate(claim.model_dump(mode="json"))
