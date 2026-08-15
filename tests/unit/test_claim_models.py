"""Tests for Stage 5A claim schema models."""

from __future__ import annotations

import pytest

from tbm_twin.claims.models import (
    STAGE5A_SCHEMA_VERSION,
    ClaimAbstentionReason,
    ClaimDecision,
    ClaimExpressibility,
    ClaimModality,
    ClaimScope,
    ClaimScopeKind,
    ClaimSemanticInterpretation,
    ClaimSupportRole,
    ClaimType,
    MetricClaimValue,
    SupportKind,
    TypedEngineeringClaim,
    stable_id,
)


def test_claim_scope_requires_structured_geometry() -> None:
    with pytest.raises(ValueError, match="LOCATED_INTERVAL"):
        ClaimScope(
            scope_kind=ClaimScopeKind.LOCATED_INTERVAL,
            start_chainage=10.0,
            end_chainage=10.0,
            scope_basis="test",
        )

    scope = ClaimScope(
        scope_kind=ClaimScopeKind.LOCATED_POINT,
        point_chainage=1013184.2,
        scope_basis="face_header_chainage",
    )

    assert scope.scope_kind == ClaimScopeKind.LOCATED_POINT
    assert STAGE5A_SCHEMA_VERSION == "stage5a_typed_claim_contract.v1"


def test_stable_id_is_deterministic_and_generated_at_independent() -> None:
    payload = {
        "claim_type": ClaimType.OPERATIONAL_RESPONSE_ATTENTION.value,
        "state_version_id": "state_version_a",
        "metric": "RAI",
        "value": 0.42,
    }
    first = stable_id("claim", payload | {"generated_at": "2026-08-09T20:55:00+08:00"})
    second = stable_id("claim", payload | {"generated_at": "2026-08-09T21:55:00+08:00"})
    nested_runtime = stable_id(
        "claim",
        payload | {"metadata": {"generated_at_utc": "2026-08-09T12:55:00Z", "basis": "fixture"}},
    )
    nested_without_runtime = stable_id("claim", payload | {"metadata": {"basis": "fixture"}})

    assert first == second
    assert first == stable_id("claim", payload)
    assert nested_runtime == nested_without_runtime
    assert stable_id("claim", payload) == stable_id("claim", dict(reversed(payload.items())))


def test_claim_decision_expressibility_invariants() -> None:
    with pytest.raises(ValueError, match="EXPRESSIBLE decision"):
        ClaimDecision(
            decision_id="decision_invalid",
            proposal_id="proposal",
            contract_id="contract",
            claim_type=ClaimType.OPERATIONAL_RESPONSE_ATTENTION,
            expressibility=ClaimExpressibility.EXPRESSIBLE,
            abstention_reason=ClaimAbstentionReason.UNKNOWN_SOURCE_VALUE,
            failed_rules=[],
            passed_rules=[],
            required_qualifiers=[],
            resolved_support_refs=[],
        )

    with pytest.raises(ValueError, match="ABSTAIN decision"):
        ClaimDecision(
            decision_id="decision_invalid",
            proposal_id="proposal",
            contract_id="contract",
            claim_type=ClaimType.OPERATIONAL_RESPONSE_ATTENTION,
            expressibility=ClaimExpressibility.ABSTAIN,
            abstention_reason=None,
            failed_rules=["required_metric_available"],
            passed_rules=[],
            required_qualifiers=[],
            resolved_support_refs=[],
        )


def test_typed_engineering_claim_expressibility_invariants() -> None:
    scope = ClaimScope(
        scope_kind=ClaimScopeKind.CELL,
        valid_date="2023-09-23",
        cell_id="cell_fixture",
        scope_basis="fixture",
    )
    claim_value = MetricClaimValue(
        metric_name="RAI",
        metric_value=0.5,
        metric_status="AVAILABLE",
        metric_semantics="OPERATIONAL_RESPONSE_ATTENTION_INDEX",
        is_probability=False,
        is_hazard_probability=False,
        is_causal_estimate=False,
        source_metric_id="state_rai",
    )
    with pytest.raises(ValueError, match="EXPRESSIBLE claim"):
        TypedEngineeringClaim(
            claim_id="claim_invalid",
            schema_version=STAGE5A_SCHEMA_VERSION,
            claim_type=ClaimType.OPERATIONAL_RESPONSE_ATTENTION,
            state_role="DAILY_REVIEW_CELL",
            spatial_scope=scope,
            claim_modality=ClaimModality.DERIVED_ATTENTION,
            semantic_interpretation=ClaimSemanticInterpretation.OPERATIONAL_RESPONSE_ATTENTION,
            claim_value=claim_value,
            support_refs=[],
            contract_id="contract",
            expressibility_status=ClaimExpressibility.EXPRESSIBLE,
            abstention_reason=ClaimAbstentionReason.UNKNOWN_SOURCE_VALUE,
            required_qualifiers=[],
            trace_refs=[],
            metadata={},
        )

    with pytest.raises(ValueError, match="ABSTAIN claim"):
        TypedEngineeringClaim(
            claim_id="claim_invalid",
            schema_version=STAGE5A_SCHEMA_VERSION,
            claim_type=ClaimType.OPERATIONAL_RESPONSE_ATTENTION,
            state_role="DAILY_REVIEW_CELL",
            spatial_scope=scope,
            claim_modality=ClaimModality.DERIVED_ATTENTION,
            semantic_interpretation=ClaimSemanticInterpretation.OPERATIONAL_RESPONSE_ATTENTION,
            claim_value=claim_value,
            support_refs=[
                {
                    "support_kind": SupportKind.STATE_RAI,
                    "support_id": "state_rai",
                    "support_role": ClaimSupportRole.PRIMARY_SUPPORT,
                }
            ],
            contract_id="contract",
            expressibility_status=ClaimExpressibility.ABSTAIN,
            abstention_reason=None,
            required_qualifiers=[],
            trace_refs=[],
            metadata={},
        )
