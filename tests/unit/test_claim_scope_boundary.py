"""Tests for Stage 5A spatial boundary rules."""

from __future__ import annotations

from scripts.build_stage5a_claim_contract import (
    _geological_value,
    _interval_scope,
    _proposal,
    _support,
    build_stage5a_evaluator,
)
from tbm_twin.claims.models import (
    ClaimModality,
    ClaimScope,
    ClaimScopeKind,
    ClaimSemanticInterpretation,
    ClaimType,
    SupportKind,
)


def test_unlocated_support_cannot_become_cell_specific_claim() -> None:
    evaluator = build_stage5a_evaluator()
    proposal = _proposal(
        "unlocated",
        ClaimType.OBSERVED_GEOLOGICAL_CONDITION,
        "DAILY_REVIEW_CELL",
        ClaimModality.GEOLOGICAL_OBSERVED,
        ClaimSemanticInterpretation.OBSERVED_GEOLOGICAL_CONDITION,
        [
            _support(
                SupportKind.GEOLOGICAL_EVIDENCE,
                "geo_unlocated",
                epistemic="OBSERVED",
                spatial_scope=ClaimScope(scope_kind=ClaimScopeKind.UNLOCATED, scope_basis="source"),
            )
        ],
        source_epistemic_statuses=["OBSERVED"],
        claim_value=_geological_value("geo_unlocated"),
    )

    decision = evaluator.evaluate(proposal)

    assert decision.expressibility == "ABSTAIN"
    assert decision.abstention_reason == "SPATIAL_SCOPE_UNAVAILABLE"


def test_claim_scope_cannot_exceed_support_interval() -> None:
    evaluator = build_stage5a_evaluator()
    proposal = _proposal(
        "exceeds_support",
        ClaimType.OBSERVED_GEOLOGICAL_CONDITION,
        "DAILY_REVIEW_CELL",
        ClaimModality.GEOLOGICAL_OBSERVED,
        ClaimSemanticInterpretation.OBSERVED_GEOLOGICAL_CONDITION,
        [
            _support(
                SupportKind.GEOLOGICAL_EVIDENCE,
                "geo_interval_100_110",
                epistemic="OBSERVED",
                spatial_scope=_interval_scope(100.0, 110.0),
            )
        ],
        scope=_interval_scope(90.0, 110.0),
        source_epistemic_statuses=["OBSERVED"],
        claim_value=_geological_value("geo_interval_100_110"),
    )

    decision = evaluator.evaluate(proposal)

    assert decision.expressibility == "ABSTAIN"
    assert decision.abstention_reason == "CLAIM_SCOPE_EXCEEDS_SUPPORT"
