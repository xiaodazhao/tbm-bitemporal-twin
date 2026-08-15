"""Tests that Stage 5A preserves geological epistemic status."""

from __future__ import annotations

from scripts.build_stage5a_claim_contract import (
    _interval_scope,
    _proposal,
    _support,
    build_stage5a_evaluator,
)
from tbm_twin.claims.models import (
    ClaimModality,
    ClaimSemanticInterpretation,
    ClaimSupportRole,
    ClaimType,
    SupportKind,
)


def test_forecast_support_cannot_be_promoted_to_observed_claim() -> None:
    evaluator = build_stage5a_evaluator()
    proposal = _proposal(
        "forecast_to_observed",
        ClaimType.OBSERVED_GEOLOGICAL_CONDITION,
        "DAILY_REVIEW_CELL",
        ClaimModality.GEOLOGICAL_OBSERVED,
        ClaimSemanticInterpretation.OBSERVED_GEOLOGICAL_CONDITION,
        [
            _support(
                SupportKind.GEOLOGICAL_EVIDENCE,
                "geo_forecast",
                role=ClaimSupportRole.PRIMARY_SUPPORT,
                epistemic="FORECAST",
                spatial_scope=_interval_scope(),
            )
        ],
        scope=_interval_scope(),
        source_epistemic_statuses=["FORECAST"],
    )

    decision = evaluator.evaluate(proposal)

    assert decision.expressibility == "ABSTAIN"
    assert decision.abstention_reason == "EPISTEMIC_PROMOTION_FORBIDDEN"
