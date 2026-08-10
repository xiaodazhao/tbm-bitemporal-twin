"""Tests for forbidden Stage 5A claim semantics."""

from __future__ import annotations

from pathlib import Path

from scripts.build_stage5a_claim_contract import (
    _cell_scope,
    _proposal,
    _support,
    build_stage5a_evaluator,
)
from tbm_twin.claims.models import (
    ClaimModality,
    ClaimSemanticInterpretation,
    ClaimType,
    SupportKind,
)


def test_grci_probability_interpretation_is_forbidden() -> None:
    evaluator = build_stage5a_evaluator()
    proposal = _proposal(
        "grci_probability",
        ClaimType.COUPLED_ATTENTION_REVIEW,
        "DAILY_REVIEW_CELL",
        ClaimModality.DERIVED_ATTENTION,
        ClaimSemanticInterpretation.HAZARD_PROBABILITY,
        [_support(SupportKind.STATE_GRCI, "state_grci", spatial_scope=_cell_scope())],
        metric_statuses={"GRCI": "AVAILABLE"},
    )

    decision = evaluator.evaluate(proposal)

    assert decision.expressibility == "ABSTAIN"
    assert decision.abstention_reason == "FORBIDDEN_SEMANTIC_INTERPRETATION"


def test_stage5a_does_not_define_metric_threshold_language() -> None:
    stage5_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            *Path("src/tbm_twin/claims").glob("*.py"),
            Path("configs/claim_contract_v1.yaml"),
        ]
    )

    forbidden = ["RAI >= ", "GRS >= ", "GRCI >= ", "risk level"]
    assert not any(pattern in stage5_text for pattern in forbidden)
