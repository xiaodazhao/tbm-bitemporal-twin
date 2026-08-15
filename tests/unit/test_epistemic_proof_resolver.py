"""Tests for trace-backed Stage 5A epistemic proof resolution."""

from __future__ import annotations

from scripts.build_stage5a_claim_contract import _support, build_stage5a_evaluator
from tbm_twin.claims.models import SupportKind


def test_epistemic_proof_resolver_ignores_unresolved_state_role() -> None:
    evaluator = build_stage5a_evaluator()
    proof = evaluator._epistemic_resolver.resolve(
        [_support(SupportKind.STATE_GRS, "state_grs_no_lineage")]
    )

    assert proof.status == "UNRESOLVED"
    assert proof.resolved_statuses == set()


def test_epistemic_proof_resolver_traces_grs_to_forecast_evidence() -> None:
    evaluator = build_stage5a_evaluator()
    proof = evaluator._epistemic_resolver.resolve(
        [_support(SupportKind.STATE_GRS, "state_grs_fixture")]
    )

    assert proof.status == "RESOLVED"
    assert "FORECAST" in proof.resolved_statuses
    assert "geo_forecast" in proof.proof_evidence_ids
