"""Stage 5C denominator contract tests."""

from __future__ import annotations

from tests.unit.stage5c_helpers import read_json, stage5c_artifact


def test_stage5c_denominator_contract_names_all_primary_rates(tmp_path_factory) -> None:
    artifact = stage5c_artifact(tmp_path_factory)
    contract = read_json(artifact / "analysis_denominator_contract.json")

    for key in [
        "overall_expressibility_rate",
        "claim_type_expressibility_rate",
        "abstention_reason_share",
        "claim_type_abstention_reason_share",
        "daily_expressibility_rate",
        "role_expressibility_rate",
        "revision_transition_rate",
    ]:
        assert key in contract
        assert contract[key]["numerator"]
        assert contract[key]["denominator"]
