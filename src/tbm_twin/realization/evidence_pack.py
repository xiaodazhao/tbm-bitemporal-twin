"""Controlled Evidence Pack construction and deterministic slicing."""

from __future__ import annotations

from collections import Counter
from typing import Any

from tbm_twin.realization.fact_lock import fact_lock_to_dict
from tbm_twin.realization.io import stable_hash, stable_id
from tbm_twin.realization.models import (
    STAGE6A_METHOD_VERSION,
    ControlledEvidencePack,
    LockedEngineeringFact,
    SliceSpec,
)
from tbm_twin.realization.rendering_contract import build_rendering_contract

DAILY_REVIEW_PRODUCT_ROLES = {"DAILY_REVIEW_CELL"}
FORWARD_ATTENTION_PRODUCT_ROLES = {"FORWARD_ATTENTION_CELL"}
METRIC_REVIEW_PRODUCT_CLAIM_TYPES = {
    "OPERATIONAL_RESPONSE_ATTENTION",
    "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
    "COUPLED_ATTENTION_REVIEW",
    "FORWARD_GEOLOGICAL_ATTENTION",
}

PRODUCT_TYPE_SEMANTICS = {
    "all": {
        "description": "No product-specific filtering; explicit filters still apply.",
        "state_roles": [],
        "claim_types": [],
        "overlap_allowed": True,
    },
    "daily_review": {
        "description": "Facts attached to DAILY_REVIEW_CELL state role.",
        "state_roles": sorted(DAILY_REVIEW_PRODUCT_ROLES),
        "claim_types": [],
        "overlap_allowed": True,
    },
    "forward_attention": {
        "description": "Facts attached to FORWARD_ATTENTION_CELL state role.",
        "state_roles": sorted(FORWARD_ATTENTION_PRODUCT_ROLES),
        "claim_types": [],
        "overlap_allowed": True,
    },
    "metric_review": {
        "description": "Nonprobabilistic attention metric claim families.",
        "state_roles": [],
        "claim_types": sorted(METRIC_REVIEW_PRODUCT_CLAIM_TYPES),
        "overlap_allowed": True,
    },
}


def build_abstention_summary(abstentions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize abstentions without exposing unsupported values as facts."""

    counts = Counter(
        (
            row["claim_type"],
            row["state_role"],
            row["abstention_reason"],
        )
        for row in abstentions
    )
    rows = []
    for (claim_type, state_role, reason), count in sorted(counts.items()):
        rows.append(
            {
                "claim_type": claim_type,
                "state_role": state_role,
                "abstention_reason": reason,
                "count": count,
                "semantics": "not_authoritative_fact",
            }
        )
    return rows


def build_controlled_evidence_pack(
    locks: list[LockedEngineeringFact],
    abstentions: list[dict[str, Any]],
    *,
    task_context: str = "stage6a_all_locked_facts_candidate",
    slice_spec: SliceSpec | None = None,
) -> ControlledEvidencePack:
    """Build a minimal controlled pack where FactLocks are the only facts."""

    selected = slice_fact_locks(locks, slice_spec or SliceSpec())
    contract = build_rendering_contract()
    abstention_summary = build_abstention_summary(abstentions)
    provenance_index = {
        lock.fact_lock_id: {
            "source_claim_id": lock.source_claim_id,
            "source_decision_id": lock.source_decision_id,
            "trace_refs": lock.trace_refs,
            "support_ref_count": len(lock.authoritative_support_refs),
        }
        for lock in selected
    }
    semantic_payload = {
        "task_context": task_context,
        "slice_spec": (slice_spec or SliceSpec()).model_dump(mode="json"),
        "locked_facts": [
            {"fact_lock_id": lock.fact_lock_id, "lock_hash": lock.lock_hash} for lock in selected
        ],
        "abstention_summary": abstention_summary,
        "contract_hash": contract.contract_hash,
    }
    pack_hash = stable_hash(semantic_payload)
    return ControlledEvidencePack(
        pack_id=stable_id("evidence_pack", semantic_payload),
        schema_version="stage6a_fact_lock_evidence_pack.v1",
        method_version=STAGE6A_METHOD_VERSION,
        task_context=task_context,
        valid_date=(slice_spec.valid_date if slice_spec else None),
        knowledge_context={
            "source": "frozen_stage5b_stage5c",
            "slice_spec": (slice_spec or SliceSpec()).model_dump(mode="json"),
            "product_type_semantics": PRODUCT_TYPE_SEMANTICS,
            "authoritative_fact_source": "locked_facts_only",
        },
        locked_facts=selected,
        abstention_summary=abstention_summary,
        generation_contract=contract,
        provenance_index=provenance_index,
        pack_hash=pack_hash,
    )


def slice_fact_locks(
    locks: list[LockedEngineeringFact],
    slice_spec: SliceSpec,
) -> list[LockedEngineeringFact]:
    """Return deterministic filtered facts without changing fact content."""

    selected = []
    for lock in locks:
        if not _matches_product_type(lock, slice_spec.product_type):
            continue
        if slice_spec.valid_date and lock.valid_date != slice_spec.valid_date:
            continue
        if slice_spec.state_role and lock.state_role != slice_spec.state_role:
            continue
        if slice_spec.cell_id and lock.cell_id != slice_spec.cell_id:
            continue
        if slice_spec.claim_type and lock.claim_type != slice_spec.claim_type:
            continue
        selected.append(lock)
    return sorted(selected, key=lambda item: item.fact_lock_id)


def _matches_product_type(lock: LockedEngineeringFact, product_type: str) -> bool:
    if product_type == "all":
        return True
    if product_type == "daily_review":
        return lock.state_role in DAILY_REVIEW_PRODUCT_ROLES
    if product_type == "forward_attention":
        return lock.state_role in FORWARD_ATTENTION_PRODUCT_ROLES
    if product_type == "metric_review":
        return lock.claim_type in METRIC_REVIEW_PRODUCT_CLAIM_TYPES
    msg = f"unsupported product_type: {product_type}"
    raise ValueError(msg)


def pack_to_dict(
    pack: ControlledEvidencePack, *, include_full_facts: bool = True
) -> dict[str, Any]:
    """Serialize a ControlledEvidencePack for artifact output."""

    payload = pack.model_dump(mode="json")
    if include_full_facts:
        return payload
    payload["locked_facts"] = [fact_lock_to_dict(lock) for lock in pack.locked_facts[:20]]
    payload["truncated_locked_fact_count"] = max(0, len(pack.locked_facts) - 20)
    return payload
