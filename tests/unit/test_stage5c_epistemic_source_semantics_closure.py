"""Stage 5C epistemic source semantics closure tests."""

from __future__ import annotations

from tbm_twin.claim_analysis.analysis import _epistemic_expressibility


def test_stage5c_unknown_early_abstain_keeps_forecast_source_status() -> None:
    rows = _epistemic_expressibility(
        [_geological_unknown_record("FORECAST_GEOLOGICAL_CONDITION", "ev_forecast")],
        {"ev_forecast": {"epistemic_status": "FORECAST"}},
    )

    assert rows[0]["authoritative_source_epistemic_status"] == "FORECAST"
    assert rows[0]["decision_resolved_epistemic_status"] == "MISSING_NOT_MATERIALIZED"
    assert rows[0]["source_epistemic_status_missing_count"] == 0


def test_stage5c_unknown_early_abstain_keeps_observed_source_status() -> None:
    rows = _epistemic_expressibility(
        [_geological_unknown_record("OBSERVED_GEOLOGICAL_CONDITION", "ev_observed")],
        {"ev_observed": {"epistemic_status": "OBSERVED"}},
    )

    assert rows[0]["authoritative_source_epistemic_status"] == "OBSERVED"
    assert rows[0]["decision_resolved_epistemic_status"] == "MISSING_NOT_MATERIALIZED"
    assert rows[0]["source_epistemic_status_missing_count"] == 0


def _geological_unknown_record(claim_type: str, evidence_id: str) -> dict:
    return {
        "claim_type": claim_type,
        "expressible": False,
        "abstained": True,
        "abstention_reason": "UNKNOWN_SOURCE_VALUE",
        "proposal": {
            "claim_value": {
                "attribute_name": "water_type",
                "normalized_value": "UNKNOWN",
                "source_evidence_id": evidence_id,
            }
        },
        "decision": {"expressibility": "ABSTAIN", "resolved_support_refs": []},
    }
