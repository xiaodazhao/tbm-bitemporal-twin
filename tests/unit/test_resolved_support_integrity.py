"""Tests for authoritative resolved support output in ClaimDecision."""

from __future__ import annotations

from pathlib import Path

from scripts.build_stage5a_claim_contract import (
    _build_lookup,
    _cell_scope,
    _geological_value,
    _interval_scope,
    _metric_value,
    _point_scope,
    _proposal,
    _resolved_support_integrity_rows,
    _support,
    build_stage5a_evaluator,
)
from tbm_twin.claims.models import (
    ClaimExpressibility,
    ClaimModality,
    ClaimSemanticInterpretation,
    ClaimSupportRole,
    ClaimType,
    SupportKind,
)


def test_resolved_support_refs_are_not_proposal_support_refs() -> None:
    evaluator = build_stage5a_evaluator()
    proposal = _proposal(
        "resolved_support_not_copy",
        ClaimType.OBSERVED_GEOLOGICAL_CONDITION,
        "DAILY_REVIEW_CELL",
        ClaimModality.GEOLOGICAL_OBSERVED,
        ClaimSemanticInterpretation.OBSERVED_GEOLOGICAL_CONDITION,
        [
            _support(
                SupportKind.GEOLOGICAL_EVIDENCE,
                "geo_interval_100_110",
                epistemic="FORECAST",
                spatial_scope=_interval_scope(100.0, 110.0),
            )
        ],
        scope=_point_scope(105.0),
        claim_value=_geological_value("geo_interval_100_110"),
    )

    decision = evaluator.evaluate(proposal)

    assert decision.expressibility == ClaimExpressibility.EXPRESSIBLE
    assert decision.resolved_support_refs is not proposal.support_refs
    assert decision.resolved_support_refs[0].resolved_epistemic_status == "OBSERVED"
    assert decision.resolved_support_refs[0].resolved_spatial_scope is not None
    assert decision.resolved_support_refs[0].resolved_spatial_scope.start_chainage == 100.0
    assert decision.resolved_support_refs[0].resolved_spatial_scope.end_chainage == 110.0


def test_resolved_support_integrity_counterexamples() -> None:
    evaluator = build_stage5a_evaluator()
    rows = {
        row["case_id"]: row
        for row in _resolved_support_integrity_rows(evaluator, _build_lookup(Path.cwd()))
    }

    rso1 = rows["RSO1_ASSERTED_FORECAST_RESOLVES_OBSERVED"]
    assert rso1["asserted_epistemic_status"] == "FORECAST"
    assert rso1["resolved_epistemic_status"] == "OBSERVED"
    assert rso1["decision"] == "EXPRESSIBLE"
    assert rso1["proposal_metadata_used_as_authority"] == "false"

    rso2 = rows["RSO2_ASSERTED_SCOPE_NULL_RESOLVES_INTERVAL"]
    assert rso2["asserted_spatial_scope"] == ""
    assert rso2["resolved_spatial_scope"] == "INTERVAL:100.0-110.0"
    assert rso2["decision"] == "EXPRESSIBLE"

    rso3 = rows["RSO3_ASSERTED_SCOPE_SPOOF_ABSTAINS"]
    assert rso3["asserted_spatial_scope"] == "INTERVAL:190.0-210.0"
    assert rso3["decision"] == "ABSTAIN"
    assert rso3["abstention_reason"] == "SUPPORT_SCOPE_MISMATCH"
    assert rso3["resolved_spatial_scope"] == ""

    rso4 = rows["RSO4_ASSERTED_EPISTEMIC_NULL_RESOLVES_OBSERVED"]
    assert rso4["asserted_epistemic_status"] == ""
    assert rso4["resolved_epistemic_status"] == "OBSERVED"
    assert rso4["decision"] == "EXPRESSIBLE"


def test_metric_resolved_support_uses_stage4_subject_metadata() -> None:
    evaluator = build_stage5a_evaluator()
    proposal = _proposal(
        "resolved_metric_support_no_asserted_metadata",
        ClaimType.OPERATIONAL_RESPONSE_ATTENTION,
        "DAILY_REVIEW_CELL",
        ClaimModality.DERIVED_ATTENTION,
        ClaimSemanticInterpretation.OPERATIONAL_RESPONSE_ATTENTION,
        [
            _support(
                SupportKind.STATE_RAI,
                "state_rai_fixture",
                role=ClaimSupportRole.PRIMARY_SUPPORT,
            )
        ],
        scope=_cell_scope(),
        metric_statuses={"RAI": "AVAILABLE"},
        claim_value=_metric_value(
            "RAI",
            0.5,
            "state_rai_fixture",
            "OPERATIONAL_RESPONSE_ATTENTION_INDEX",
        ),
    )

    decision = evaluator.evaluate(proposal)
    resolved = decision.resolved_support_refs[0]

    assert decision.expressibility == ClaimExpressibility.EXPRESSIBLE
    assert resolved.resolution_source == "FROZEN_STAGE4_METRIC"
    assert resolved.resolution_status == "RESOLVED"
    assert resolved.resolved_state_role == "DAILY_REVIEW_CELL"
    assert resolved.resolved_cell_id == "cell_fixture"
    assert str(resolved.resolved_valid_date) == "2023-09-23"
