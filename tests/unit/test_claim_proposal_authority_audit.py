"""Tests for proposal-vs-authoritative-evidence field classification."""

from __future__ import annotations

from scripts.build_stage5a_claim_contract import _claim_proposal_authority_rows


def test_proposal_fact_fields_cannot_override_upstream_authority() -> None:
    rows = _claim_proposal_authority_rows()
    by_field = {row["proposal_field"]: row for row in rows}

    for field in [
        "support_ref.epistemic_status",
        "support_ref.spatial_scope",
        "has_unknown_source_value",
        "claim_value.metric_value",
        "cell_id",
        "valid_date",
        "state_role",
        "scope",
    ]:
        assert by_field[field]["authoritative_from_upstream"] == "true"
        assert by_field[field]["proposal_can_override"] == "false"

    assert by_field["claim_type"]["classification"] == "PROPOSAL_INTENT"
