"""Stage 6A machine-readable rendering contract."""

from __future__ import annotations

from typing import Any

from tbm_twin.realization.io import stable_hash
from tbm_twin.realization.models import STAGE6A_SCHEMA_VERSION, RenderingContract


def rendering_contract_semantic_payload(
    contract: RenderingContract | dict[str, Any],
) -> dict[str, Any]:
    """Return contract content that determines realization semantics."""

    payload = (
        contract.model_dump(mode="json") if isinstance(contract, RenderingContract) else contract
    )
    return {
        "schema_version": payload["schema_version"],
        "may": payload["may"],
        "must": payload["must"],
        "must_not": payload["must_not"],
        "claim_type_policies": payload["claim_type_policies"],
    }


def rendering_contract_hash(payload: dict[str, Any]) -> str:
    """Return deterministic content hash for a rendering contract payload."""

    return stable_hash(rendering_contract_semantic_payload(payload))


def build_rendering_contract() -> RenderingContract:
    """Return the frozen Stage6A rendering boundary."""

    payload: dict[str, Any] = {
        "contract_id": "stage6a_controlled_rendering_contract_v1_frozen",
        "schema_version": STAGE6A_SCHEMA_VERSION,
        "may": [
            "order_locked_facts",
            "merge_semantically_compatible_locked_facts",
            "add_non_factual_connective_words",
            "organize_surface_language_without_changing_epistemic_strength",
            "explicitly_state_evidence_insufficiency_from_abstention_summary",
        ],
        "must": [
            "preserve_fact_lock_id",
            "preserve_numeric_value",
            "preserve_unit_when_present",
            "preserve_valid_date",
            "preserve_spatial_scope",
            "preserve_claim_modality",
            "preserve_required_qualifiers",
            "use_only_provided_locked_fact_ids_for_authoritative_claims",
            "trace_every_realized_fact_to_fact_lock",
        ],
        "must_not": [
            "invent_numeric_value",
            "change_numeric_value",
            "change_unit",
            "expand_spatial_scope",
            "expand_temporal_scope",
            "promote_forecast_to_observed",
            "promote_unknown_to_normal",
            "promote_attention_to_probability",
            "infer_geological_cause_from_mechanical_response",
            "use_local_background_as_direct_support",
            "render_grci_as_geological_risk_probability",
            "fill_missing_fact_from_common_sense",
            "extrapolate_from_other_cell",
            "use_pack_external_knowledge_for_engineering_claim",
        ],
        "claim_type_policies": {
            "OPERATIONAL_RESPONSE_ATTENTION": {
                "required_semantics": "nonprobabilistic operational response attention",
                "allowed_terms": ["attention index", "operational response attention"],
                "forbidden_terms": [
                    "geological cause",
                    "caused by geology",
                    "risk probability",
                    "failure probability",
                ],
            },
            "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW": {
                "required_semantics": "nonprobabilistic geological evidence attention",
                "allowed_terms": ["geological evidence attention", "attention index"],
                "forbidden_terms": ["probability", "hazard probability", "confirmed hazard"],
            },
            "COUPLED_ATTENTION_REVIEW": {
                "required_semantics": "coupled noncausal attention",
                "allowed_terms": ["coupled attention", "joint attention index"],
                "forbidden_terms": [
                    "causal diagnosis",
                    "risk probability",
                    "geological risk probability",
                ],
            },
            "FORWARD_GEOLOGICAL_ATTENTION": {
                "required_semantics": "source-constrained forward geological attention",
                "allowed_terms": ["forward attention", "ahead-of-face attention"],
                "forbidden_terms": ["observed ahead", "confirmed ahead", "probability"],
            },
            "OBSERVED_GEOLOGICAL_CONDITION": {
                "required_semantics": "authoritatively observed geological condition",
                "allowed_terms": ["observed", "recorded", "source-constrained"],
                "forbidden_terms": ["forecast", "predicted", "inferred without observation"],
            },
            "FORECAST_GEOLOGICAL_CONDITION": {
                "required_semantics": "authoritatively forecast geological condition",
                "allowed_terms": ["forecast", "predicted", "indicates", "suggests"],
                "forbidden_terms": ["observed", "encountered", "confirmed", "actually exists"],
            },
        },
    }
    payload["contract_hash"] = rendering_contract_hash(payload)
    return RenderingContract(**payload)
