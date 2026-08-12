"""Build deterministic Stage 6A fact locks from frozen Stage5B claims."""

from __future__ import annotations

from typing import Any

from tbm_twin.realization.io import stable_hash, stable_id
from tbm_twin.realization.models import LockedEngineeringFact
from tbm_twin.realization.rendering_contract import build_rendering_contract

ATTENTION_CLAIM_TYPES = {
    "OPERATIONAL_RESPONSE_ATTENTION",
    "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
    "COUPLED_ATTENTION_REVIEW",
    "FORWARD_GEOLOGICAL_ATTENTION",
}


def build_fact_locks(
    claims: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> list[LockedEngineeringFact]:
    """Project every EXPRESSIBLE TypedEngineeringClaim into one immutable FactLock."""

    decisions_by_id = {str(row["decision_id"]): row for row in decisions}
    locks = []
    for claim in sorted(claims, key=lambda row: str(row["claim_id"])):
        decision_id = str((claim.get("metadata") or {}).get("decision_id") or "")
        decision = decisions_by_id[decision_id]
        locks.append(build_fact_lock(claim, decision))
    return locks


def build_fact_lock(claim: dict[str, Any], decision: dict[str, Any]) -> LockedEngineeringFact:
    """Build one immutable FactLock from a frozen Stage5B materialized claim."""

    if claim.get("expressibility_status") != "EXPRESSIBLE":
        msg = "FactLock can only be built from EXPRESSIBLE typed claims"
        raise ValueError(msg)
    if decision.get("expressibility") != "EXPRESSIBLE":
        msg = "FactLock can only be built from EXPRESSIBLE decisions"
        raise ValueError(msg)
    contract = build_rendering_contract()
    claim_type = str(claim["claim_type"])
    allowed_rendering_semantics = _allowed_semantics(claim_type)
    prohibited_transformations = list(contract.must_not)
    semantic_payload = _semantic_lock_payload(
        claim,
        decision,
        allowed_rendering_semantics,
        prohibited_transformations,
    )
    fact_lock_id = stable_id("fact_lock", semantic_payload)
    lock_hash = stable_hash(semantic_payload)
    return LockedEngineeringFact(
        fact_lock_id=fact_lock_id,
        source_claim_id=str(claim["claim_id"]),
        claim_type=claim_type,
        valid_date=claim.get("valid_date"),
        bitemporal_version_id=claim.get("bitemporal_version_id"),
        base_stage3a_state_version_id=claim.get("base_stage3a_state_version_id"),
        state_version_id=claim.get("state_version_id"),
        daily_state_id=claim.get("daily_state_id"),
        cell_id=claim.get("cell_id"),
        state_role=str(claim["state_role"]),
        spatial_scope=dict(claim["spatial_scope"]),
        claim_modality=str(claim["claim_modality"]),
        semantic_interpretation=str(claim["semantic_interpretation"]),
        claim_value=dict(claim["claim_value"]),
        required_qualifiers=[str(item) for item in claim.get("required_qualifiers", [])],
        authoritative_support_refs=[
            dict(item) for item in decision.get("resolved_support_refs", [])
        ],
        trace_refs=[str(item) for item in claim.get("trace_refs", [])],
        allowed_rendering_semantics=allowed_rendering_semantics,
        prohibited_transformations=prohibited_transformations,
        source_contract_id=str(claim["contract_id"]),
        source_schema_version=str(claim["schema_version"]),
        source_decision_id=str((claim.get("metadata") or {})["decision_id"]),
        source_opportunity_id=str((claim.get("metadata") or {})["opportunity_id"]),
        source_proposal_id=str((claim.get("metadata") or {})["proposal_id"]),
        lock_hash=lock_hash,
    )


def _semantic_lock_payload(
    claim: dict[str, Any],
    decision: dict[str, Any],
    allowed_rendering_semantics: list[str],
    prohibited_transformations: list[str],
) -> dict[str, Any]:
    return {
        "source_claim_id": claim["claim_id"],
        "claim_type": claim["claim_type"],
        "valid_date": claim.get("valid_date"),
        "bitemporal_version_id": claim.get("bitemporal_version_id"),
        "base_stage3a_state_version_id": claim.get("base_stage3a_state_version_id"),
        "state_version_id": claim.get("state_version_id"),
        "daily_state_id": claim.get("daily_state_id"),
        "cell_id": claim.get("cell_id"),
        "state_role": claim["state_role"],
        "spatial_scope": claim["spatial_scope"],
        "claim_modality": claim["claim_modality"],
        "semantic_interpretation": claim["semantic_interpretation"],
        "claim_value": claim["claim_value"],
        "required_qualifiers": claim.get("required_qualifiers", []),
        "authoritative_support_refs": decision.get("resolved_support_refs", []),
        "trace_refs": claim.get("trace_refs", []),
        "allowed_rendering_semantics": allowed_rendering_semantics,
        "prohibited_transformations": prohibited_transformations,
        "source_contract_id": claim["contract_id"],
        "source_schema_version": claim["schema_version"],
        "source_decision_id": (claim.get("metadata") or {}).get("decision_id"),
        "source_opportunity_id": (claim.get("metadata") or {}).get("opportunity_id"),
        "source_proposal_id": (claim.get("metadata") or {}).get("proposal_id"),
    }


def _allowed_semantics(claim_type: str) -> list[str]:
    if claim_type == "FORECAST_GEOLOGICAL_CONDITION":
        return ["forecast", "predicted", "indicates", "source_constrained"]
    if claim_type == "OBSERVED_GEOLOGICAL_CONDITION":
        return ["observed", "recorded", "source_constrained"]
    if claim_type in ATTENTION_CLAIM_TYPES:
        return ["nonprobabilistic_attention", "source_constrained"]
    return ["source_constrained"]


def fact_lock_to_dict(lock: LockedEngineeringFact) -> dict[str, Any]:
    """Serialize a FactLock with stable JSON-compatible values."""

    return lock.model_dump(mode="json")
