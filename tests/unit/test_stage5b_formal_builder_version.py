"""Stage 5B formal builder-version packaging tests."""

from __future__ import annotations

from tbm_twin.claim_building.models import STAGE5B_FORMAL_METHOD_VERSION
from tests.unit.stage5b_helpers import read_jsonl, stage5b_formal_artifact


def test_stage5b_formal_builder_version(tmp_path_factory) -> None:
    artifact = stage5b_formal_artifact(tmp_path_factory)

    opportunities = read_jsonl(artifact / "claim_opportunities.jsonl")
    records = read_jsonl(artifact / "proposal_construction_records.jsonl")
    abstentions = read_jsonl(artifact / "claim_abstentions.jsonl")
    claims = read_jsonl(artifact / "typed_engineering_claims.jsonl")

    assert opportunities and records and abstentions and claims
    assert all(row["builder_version"] == STAGE5B_FORMAL_METHOD_VERSION for row in opportunities)
    assert all(row["builder_version"] == STAGE5B_FORMAL_METHOD_VERSION for row in records)
    assert all(row["builder_version"] == STAGE5B_FORMAL_METHOD_VERSION for row in abstentions)
    assert all(
        row["metadata"]["builder_version"] == STAGE5B_FORMAL_METHOD_VERSION for row in claims
    )
    assert not any(
        "stage5b_deterministic_claim_builder_v1_candidate" in str(row)
        for rows in [opportunities, records, abstentions, claims]
        for row in rows
    )
