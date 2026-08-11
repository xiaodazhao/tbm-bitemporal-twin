"""Stage 5B typed claim JSONL schema round-trip tests."""

from __future__ import annotations

from tbm_twin.claims.models import TypedEngineeringClaim
from tests.unit.stage5b_helpers import read_jsonl, stage5b_artifact


def test_typed_engineering_claim_jsonl_round_trip(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    rows = read_jsonl(artifact / "typed_engineering_claims.jsonl")

    assert rows
    for row in rows:
        claim = TypedEngineeringClaim.model_validate(row)
        TypedEngineeringClaim.model_validate(claim.model_dump(mode="json"))
