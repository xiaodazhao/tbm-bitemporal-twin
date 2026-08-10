"""Deterministic claim contract evaluator."""

from __future__ import annotations

from tbm_twin.claims.models import (
    ClaimAbstentionReason,
    ClaimContract,
    ClaimDecision,
    ClaimExpressibility,
    ClaimModality,
    ClaimProposal,
    ClaimSemanticInterpretation,
    ClaimSupportRole,
    ClaimType,
    GeologicalConditionClaimValue,
    MetricClaimValue,
    stable_id,
)
from tbm_twin.claims.registry import ClaimTypeRegistry
from tbm_twin.claims.resolution import (
    AuthoritativeSupportResolver,
    ClaimSubjectResolver,
    ClaimUpstreamLookup,
    EpistemicProofResolver,
    MetricSupportResolver,
    SpatialRelationEvaluator,
)

AVAILABLE = "AVAILABLE"
FORBIDDEN_PROBABILITY_SEMANTICS = {
    ClaimSemanticInterpretation.RISK_PROBABILITY,
    ClaimSemanticInterpretation.HAZARD_PROBABILITY,
    ClaimSemanticInterpretation.FAILURE_PROBABILITY,
}
PROMOTION_RULE_REGISTRY = {
    "FORECAST_TO_OBSERVED": "epistemic_status_to_observed_modality",
    "BACKGROUND_TO_OBSERVED": "epistemic_status_to_observed_modality",
    "RESPONSE_TO_GEOLOGICAL_FACT": "support_semantic_compatibility",
    "ATTENTION_TO_PROBABILITY": "semantic_and_metric_probability_flags",
    "ATTENTION_TO_CAUSAL_ESTIMATE": "semantic_and_metric_causal_flags",
}
PROMOTION_STATUS_RULES = {
    "FORECAST_TO_OBSERVED": ("FORECAST", ClaimModality.GEOLOGICAL_OBSERVED),
    "BACKGROUND_TO_OBSERVED": ("BACKGROUND", ClaimModality.GEOLOGICAL_OBSERVED),
}
SUPPORT_SEMANTIC_FAMILY = {
    "RESPONSE_EVIDENCE": "MECHANICAL_RESPONSE",
    "EXCAVATION_EPISODE": "MECHANICAL_RESPONSE",
    "STATE_RAI": "DERIVED_OPERATIONAL_ATTENTION",
    "RAI_FAMILY_COMPONENT": "DERIVED_OPERATIONAL_ATTENTION",
    "GEOLOGICAL_EVIDENCE": "GEOLOGICAL_EVIDENCE",
    "SOURCE_SPAN": "GEOLOGICAL_EVIDENCE",
    "SOURCE_ASSET": "GEOLOGICAL_EVIDENCE",
    "STATE_GRS": "DERIVED_GEOLOGICAL_ATTENTION",
    "GRS_DIMENSION_COMPONENT": "DERIVED_GEOLOGICAL_ATTENTION",
    "STATE_GRCI": "DERIVED_COUPLED_ATTENTION",
    "CONSTRUCTION_STATE_VERSION": "CONSTRUCTION_STATE",
    "DAILY_CONSTRUCTION_STATE": "CONSTRUCTION_STATE",
}
CLAIM_SEMANTIC_COMPATIBILITY = {
    ClaimSemanticInterpretation.OPERATIONAL_RESPONSE_ATTENTION: {
        "DERIVED_OPERATIONAL_ATTENTION",
        "MECHANICAL_RESPONSE",
        "CONSTRUCTION_STATE",
    },
    ClaimSemanticInterpretation.GEOLOGICAL_EVIDENCE_ATTENTION: {
        "DERIVED_GEOLOGICAL_ATTENTION",
        "GEOLOGICAL_EVIDENCE",
        "CONSTRUCTION_STATE",
    },
    ClaimSemanticInterpretation.COUPLED_ATTENTION: {
        "DERIVED_COUPLED_ATTENTION",
        "DERIVED_OPERATIONAL_ATTENTION",
        "DERIVED_GEOLOGICAL_ATTENTION",
        "MECHANICAL_RESPONSE",
        "GEOLOGICAL_EVIDENCE",
        "CONSTRUCTION_STATE",
    },
    ClaimSemanticInterpretation.OBSERVED_GEOLOGICAL_CONDITION: {"GEOLOGICAL_EVIDENCE"},
    ClaimSemanticInterpretation.FORECAST_GEOLOGICAL_CONDITION: {"GEOLOGICAL_EVIDENCE"},
}


class ClaimContractEvaluator:
    """Evaluate a structured claim proposal against Stage 5A contracts."""

    def __init__(
        self,
        registry: ClaimTypeRegistry,
        lookup: ClaimUpstreamLookup | None = None,
    ) -> None:
        self._registry = registry
        self._lookup = lookup or ClaimUpstreamLookup()
        self._epistemic_resolver = EpistemicProofResolver(self._lookup)
        self._metric_resolver = MetricSupportResolver(self._lookup)
        self._subject_resolver = ClaimSubjectResolver(self._lookup)
        self._spatial_evaluator = SpatialRelationEvaluator(self._lookup)
        self._support_resolver = AuthoritativeSupportResolver(self._lookup)

    def evaluate(self, proposal: ClaimProposal) -> ClaimDecision:
        """Evaluate one proposal and return a deterministic decision."""

        contract = self._registry.contract_for(proposal.claim_type)
        if contract is None:
            return self._abstain(
                proposal,
                None,
                ClaimAbstentionReason.UNSUPPORTED_CLAIM_TYPE,
                [],
                ["claim_type_registered"],
            )
        failed: list[str] = []
        passed: list[str] = []
        reason = self._first_failure(proposal, contract, failed, passed)
        if reason is not None:
            return self._abstain(proposal, contract, reason, failed, passed)
        return ClaimDecision(
            decision_id=stable_id(
                "claim_decision",
                {
                    "proposal_id": proposal.proposal_id,
                    "contract_id": contract.contract_id,
                    "expressibility": ClaimExpressibility.EXPRESSIBLE.value,
                },
            ),
            proposal_id=proposal.proposal_id,
            contract_id=contract.contract_id,
            claim_type=proposal.claim_type,
            expressibility=ClaimExpressibility.EXPRESSIBLE,
            abstention_reason=None,
            failed_rules=[],
            passed_rules=passed,
            required_qualifiers=contract.required_qualifiers,
            resolved_support_refs=self._support_resolver.resolve_many(proposal.support_refs),
        )

    def _first_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
        failed: list[str],
        passed: list[str],
    ) -> ClaimAbstentionReason | None:
        checks = [
            ("generation_eligible", self._generation_failure),
            ("allowed_state_roles", self._state_role_failure),
            ("forbidden_semantics", self._forbidden_semantic_failure),
            ("allowed_semantic_interpretations", self._semantic_interpretation_failure),
            ("allowed_modalities", self._modality_failure),
            ("support_semantic_compatibility", self._semantic_support_failure),
            ("allowed_support_kinds", self._allowed_support_failure),
            ("forbidden_support_kinds", self._forbidden_support_failure),
            ("required_primary_support", self._required_support_failure),
            ("forbidden_epistemic_promotions", self._epistemic_promotion_failure),
            ("unknown_source_value", self._unknown_source_failure),
            ("required_epistemic_statuses", self._required_epistemic_failure),
            ("claim_subject_binding", self._subject_binding_failure),
            ("metric_payload_contract", self._metric_payload_failure),
            ("geological_payload_contract", self._geological_payload_failure),
            ("spatial_containment", self._spatial_failure),
            ("resolved_support_integrity", self._resolved_support_failure),
        ]
        for rule_name, handler in checks:
            reason = handler(proposal, contract)
            if reason is not None:
                failed.append(rule_name)
                return reason
            passed.append(rule_name)
        return None

    def _generation_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        if not contract.generation_eligible or proposal.state_role == "LOCAL_BACKGROUND_CELL":
            return ClaimAbstentionReason.CONTEXT_ONLY_ROLE
        return None

    def _state_role_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        if proposal.state_role not in contract.allowed_state_roles:
            return ClaimAbstentionReason.STATE_ROLE_NOT_ALLOWED
        return None

    def _forbidden_semantic_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        if proposal.semantic_interpretation in contract.forbidden_semantics:
            return ClaimAbstentionReason.FORBIDDEN_SEMANTIC_INTERPRETATION
        if proposal.semantic_interpretation in FORBIDDEN_PROBABILITY_SEMANTICS:
            return ClaimAbstentionReason.FORBIDDEN_SEMANTIC_INTERPRETATION
        return None

    def _semantic_interpretation_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        if proposal.semantic_interpretation not in contract.allowed_semantic_interpretations:
            return ClaimAbstentionReason.SUPPORT_SEMANTIC_MISMATCH
        return None

    def _modality_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        if proposal.modality not in contract.allowed_modalities:
            return ClaimAbstentionReason.SUPPORT_SEMANTIC_MISMATCH
        return None

    def _semantic_support_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        allowed_families = CLAIM_SEMANTIC_COMPATIBILITY.get(proposal.semantic_interpretation)
        if allowed_families is None:
            return ClaimAbstentionReason.SUPPORT_SEMANTIC_MISMATCH
        for ref in proposal.support_refs:
            if ref.support_role != ClaimSupportRole.PRIMARY_SUPPORT:
                continue
            family = SUPPORT_SEMANTIC_FAMILY.get(ref.support_kind.value)
            if family is not None and family not in allowed_families:
                return ClaimAbstentionReason.SUPPORT_SEMANTIC_MISMATCH
        return None

    def _allowed_support_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        if any(
            ref.support_kind not in contract.allowed_support_kinds for ref in proposal.support_refs
        ):
            return ClaimAbstentionReason.SUPPORT_KIND_NOT_ALLOWED
        return None

    def _forbidden_support_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        if any(
            ref.support_kind in contract.forbidden_support_kinds for ref in proposal.support_refs
        ):
            return ClaimAbstentionReason.SUPPORT_SEMANTIC_MISMATCH
        return None

    def _required_support_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        primary_kinds = {
            ref.support_kind
            for ref in proposal.support_refs
            if ref.support_role == ClaimSupportRole.PRIMARY_SUPPORT
        }
        if not all(kind in primary_kinds for kind in contract.required_support_kinds):
            return ClaimAbstentionReason.REQUIRED_SUPPORT_MISSING
        return None

    def _epistemic_promotion_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        proof = self._epistemic_resolver.resolve(proposal.support_refs)
        for rule in contract.forbidden_epistemic_promotions:
            source_status, target_modality = PROMOTION_STATUS_RULES.get(rule, ("", None))
            if source_status in proof.resolved_statuses and proposal.modality == target_modality:
                return ClaimAbstentionReason.EPISTEMIC_PROMOTION_FORBIDDEN
            if rule == "RESPONSE_TO_GEOLOGICAL_FACT":
                reason = self._semantic_support_failure(proposal, contract)
                if reason is not None:
                    return reason
            if rule in {"ATTENTION_TO_PROBABILITY", "ATTENTION_TO_CAUSAL_ESTIMATE"}:
                reason = self._metric_semantic_flag_failure(proposal)
                if reason is not None:
                    return reason
        return None

    def _required_epistemic_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        required = {status.upper() for status in contract.required_epistemic_statuses}
        if not required:
            return None
        proof = self._epistemic_resolver.resolve(proposal.support_refs)
        if not bool(required & proof.resolved_statuses):
            return ClaimAbstentionReason.REQUIRED_EPISTEMIC_STATUS_MISSING
        return None

    def _metric_payload_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        if contract.required_metric is None:
            return None
        if proposal.metric_statuses.get(contract.required_metric) != AVAILABLE:
            return ClaimAbstentionReason.REQUIRED_METRIC_UNAVAILABLE
        payload = (
            proposal.claim_value if isinstance(proposal.claim_value, MetricClaimValue) else None
        )
        result = self._metric_resolver.validate(
            payload,
            contract.required_metric,
            contract.metric_semantics,
            proposal.support_refs,
        )
        if result.status == "PASS":
            return None
        return ClaimAbstentionReason(result.reason or "MALFORMED_CLAIM_VALUE")

    def _subject_binding_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        if contract.required_metric is not None:
            payload = (
                proposal.claim_value if isinstance(proposal.claim_value, MetricClaimValue) else None
            )
            result = self._subject_resolver.validate_metric_subject(proposal, payload)
        elif proposal.claim_type in {
            ClaimType.OBSERVED_GEOLOGICAL_CONDITION,
            ClaimType.FORECAST_GEOLOGICAL_CONDITION,
        }:
            geological_payload = (
                proposal.claim_value
                if isinstance(proposal.claim_value, GeologicalConditionClaimValue)
                else None
            )
            result = self._subject_resolver.validate_geological_subject(
                proposal,
                geological_payload,
            )
        else:
            return None
        if result.status == "PASS":
            return None
        return ClaimAbstentionReason(result.reason or "CLAIM_SUBJECT_MISMATCH")

    def _metric_semantic_flag_failure(
        self,
        proposal: ClaimProposal,
    ) -> ClaimAbstentionReason | None:
        if not isinstance(proposal.claim_value, MetricClaimValue):
            return None
        if proposal.claim_value.metric_semantics in {
            "RISK_PROBABILITY",
            "HAZARD_PROBABILITY",
            "FAILURE_PROBABILITY",
        }:
            return ClaimAbstentionReason.METRIC_SEMANTICS_MISMATCH
        if (
            proposal.claim_value.is_probability
            or proposal.claim_value.is_hazard_probability
            or proposal.claim_value.is_causal_estimate
        ):
            return ClaimAbstentionReason.METRIC_SEMANTICS_MISMATCH
        return None

    def _geological_payload_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        if proposal.claim_type not in {
            ClaimType.OBSERVED_GEOLOGICAL_CONDITION,
            ClaimType.FORECAST_GEOLOGICAL_CONDITION,
        }:
            return None
        if not isinstance(proposal.claim_value, GeologicalConditionClaimValue):
            return ClaimAbstentionReason.MALFORMED_CLAIM_VALUE
        evidence = self._lookup.geological_evidence.get(proposal.claim_value.source_evidence_id)
        if evidence is None:
            return ClaimAbstentionReason.REQUIRED_SUPPORT_MISSING
        if proposal.claim_value.source_evidence_id not in {
            ref.support_id
            for ref in proposal.support_refs
            if ref.support_role == ClaimSupportRole.PRIMARY_SUPPORT
        }:
            return ClaimAbstentionReason.REQUIRED_SUPPORT_MISSING
        actual = evidence.attributes.get(proposal.claim_value.attribute_name)
        if actual is None:
            return ClaimAbstentionReason.ATTRIBUTE_NOT_FOUND
        if _is_unknown_source_value(actual):
            return ClaimAbstentionReason.UNKNOWN_SOURCE_VALUE
        if actual != proposal.claim_value.normalized_value:
            return ClaimAbstentionReason.ATTRIBUTE_VALUE_MISMATCH
        return None

    def _unknown_source_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        return None

    def _spatial_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        if not contract.requires_spatial_location:
            return None
        if contract.required_metric is not None:
            result = self._spatial_evaluator.validate_metric_scope(
                proposal.scope,
                proposal.claim_value
                if isinstance(proposal.claim_value, MetricClaimValue)
                else None,
            )
        else:
            result = self._spatial_evaluator.validate_fact_scope(
                proposal.scope,
                proposal.support_refs,
            )
        if result.status == "PASS":
            return None
        return ClaimAbstentionReason(result.reason or "CLAIM_SCOPE_EXCEEDS_SUPPORT")

    def _resolved_support_failure(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract,
    ) -> ClaimAbstentionReason | None:
        resolved = self._support_resolver.resolve_many(proposal.support_refs)
        for support in resolved:
            if (
                support.support_role == ClaimSupportRole.PRIMARY_SUPPORT
                and support.resolution_status != "RESOLVED"
            ):
                return ClaimAbstentionReason.REQUIRED_SUPPORT_MISSING
        return None

    def _abstain(
        self,
        proposal: ClaimProposal,
        contract: ClaimContract | None,
        reason: ClaimAbstentionReason,
        failed: list[str],
        passed: list[str],
    ) -> ClaimDecision:
        contract_id = contract.contract_id if contract is not None else None
        qualifiers = contract.required_qualifiers if contract is not None else []
        failed_rules = failed or [reason.value.lower()]
        return ClaimDecision(
            decision_id=stable_id(
                "claim_decision",
                {
                    "proposal_id": proposal.proposal_id,
                    "contract_id": contract_id,
                    "expressibility": ClaimExpressibility.ABSTAIN.value,
                    "reason": reason.value,
                },
            ),
            proposal_id=proposal.proposal_id,
            contract_id=contract_id,
            claim_type=proposal.claim_type,
            expressibility=ClaimExpressibility.ABSTAIN,
            abstention_reason=reason,
            failed_rules=failed_rules,
            passed_rules=passed,
            required_qualifiers=qualifiers,
            resolved_support_refs=[],
        )


def _is_unknown_source_value(value: str) -> bool:
    """Return whether a frozen structured value is an explicit unknown sentinel."""

    normalized = value.strip().upper()
    return normalized in {"", "UNKNOWN", "NULL", "NONE", "UNMAPPED", "UNMAPPABLE"}
