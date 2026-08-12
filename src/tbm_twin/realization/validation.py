"""Stage 6A semantic preservation and boundary validation."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tbm_twin.realization.fact_lock import ATTENTION_CLAIM_TYPES, build_fact_lock
from tbm_twin.realization.io import read_json, stable_hash
from tbm_twin.realization.models import ControlledEvidencePack, LockedEngineeringFact
from tbm_twin.realization.rendering_contract import (
    build_rendering_contract,
    rendering_contract_hash,
)


def validate_fact_lock_against_claim(
    lock: LockedEngineeringFact,
    claim: dict[str, Any],
    decision: dict[str, Any],
) -> list[str]:
    """Return semantic preservation issue codes for one FactLock."""

    issues: list[str] = []
    if lock.source_claim_id != claim.get("claim_id"):
        issues.append("SOURCE_CLAIM_ID_CHANGED")
    if lock.claim_value != claim.get("claim_value"):
        issues.append("CLAIM_VALUE_CHANGED")
    if lock.claim_modality != claim.get("claim_modality"):
        issues.append("CLAIM_MODALITY_CHANGED")
    if lock.spatial_scope != claim.get("spatial_scope"):
        issues.append("SPATIAL_SCOPE_CHANGED")
    if lock.valid_date != claim.get("valid_date"):
        issues.append("VALID_DATE_CHANGED")
    if set(lock.required_qualifiers) != set(claim.get("required_qualifiers", [])):
        issues.append("REQUIRED_QUALIFIER_DROPPED")
    if not lock.trace_refs:
        issues.append("TRACE_LOSS")
    if not lock.authoritative_support_refs:
        issues.append("UNRESOLVED_PRIMARY_SUPPORT_IN_FACT_LOCK")
    if any(ref.get("resolution_status") != "RESOLVED" for ref in decision["resolved_support_refs"]):
        issues.append("UNRESOLVED_PRIMARY_SUPPORT_IN_FACT_LOCK")
    if lock.authoritative_support_refs != decision.get("resolved_support_refs", []):
        issues.append("AUTHORITATIVE_SUPPORT_DRIFT")
    if lock.claim_type == "FORECAST_GEOLOGICAL_CONDITION" and (
        lock.claim_modality == "GEOLOGICAL_OBSERVED"
        or lock.semantic_interpretation == "OBSERVED_GEOLOGICAL_CONDITION"
    ):
        issues.append("FORECAST_PROMOTED_TO_OBSERVED")
    if lock.claim_type in ATTENTION_CLAIM_TYPES and (
        lock.claim_value.get("is_probability") is not False
        or lock.claim_value.get("is_hazard_probability") is not False
    ):
        issues.append("ATTENTION_PROMOTED_TO_PROBABILITY")
    if lock.claim_type == "OPERATIONAL_RESPONSE_ATTENTION" and (
        lock.claim_value.get("is_causal_estimate") is not False
    ):
        issues.append("MECHANICAL_RESPONSE_PROMOTED_TO_GEOLOGICAL_CAUSE")
    if lock.claim_type in {
        "OBSERVED_GEOLOGICAL_CONDITION",
        "FORECAST_GEOLOGICAL_CONDITION",
    } and str(lock.claim_value.get("normalized_value", "")).upper() in {"UNKNOWN", ""}:
        issues.append("UNKNOWN_PROMOTED_TO_FACT")
    expected = build_fact_lock(claim, decision)
    if lock.allowed_rendering_semantics != expected.allowed_rendering_semantics:
        issues.append("ALLOWED_RENDERING_SEMANTICS_CHANGED")
    if lock.prohibited_transformations != expected.prohibited_transformations:
        issues.append("PROHIBITED_TRANSFORMATIONS_CHANGED")
    if lock.fact_lock_id != expected.fact_lock_id or lock.lock_hash != expected.lock_hash:
        issues.append("NON_DETERMINISTIC_LOCK_HASH")
    if lock.lock_hash != stable_hash(_lock_semantic_payload_from_lock(lock)):
        issues.append("LOCK_HASH_MISMATCH")
    return sorted(set(issues))


def _lock_semantic_payload_from_lock(lock: LockedEngineeringFact) -> dict[str, Any]:
    return {
        "source_claim_id": lock.source_claim_id,
        "claim_type": lock.claim_type,
        "valid_date": lock.valid_date,
        "bitemporal_version_id": lock.bitemporal_version_id,
        "base_stage3a_state_version_id": lock.base_stage3a_state_version_id,
        "state_version_id": lock.state_version_id,
        "daily_state_id": lock.daily_state_id,
        "cell_id": lock.cell_id,
        "state_role": lock.state_role,
        "spatial_scope": lock.spatial_scope,
        "claim_modality": lock.claim_modality,
        "semantic_interpretation": lock.semantic_interpretation,
        "claim_value": lock.claim_value,
        "required_qualifiers": lock.required_qualifiers,
        "authoritative_support_refs": lock.authoritative_support_refs,
        "trace_refs": lock.trace_refs,
        "allowed_rendering_semantics": lock.allowed_rendering_semantics,
        "prohibited_transformations": lock.prohibited_transformations,
        "source_contract_id": lock.source_contract_id,
        "source_schema_version": lock.source_schema_version,
        "source_decision_id": lock.source_decision_id,
        "source_opportunity_id": lock.source_opportunity_id,
        "source_proposal_id": lock.source_proposal_id,
    }


def validate_pack_boundary(pack: ControlledEvidencePack) -> list[str]:
    """Return boundary issue codes for a ControlledEvidencePack."""

    issues: list[str] = []
    fact_ids = {fact.fact_lock_id for fact in pack.locked_facts}
    if set(pack.provenance_index) - fact_ids:
        issues.append("EVIDENCE_PACK_CONTAINS_UNLOCKED_AUTHORITATIVE_FACT")
    if any(row.get("semantics") != "not_authoritative_fact" for row in pack.abstention_summary):
        issues.append("ABSTENTION_MATERIALIZED_AS_FACT")
    if not rendering_contract_hash_valid(pack.generation_contract.model_dump(mode="json")):
        issues.append("RENDERING_CONTRACT_HASH_INVALID")
    canonical_contract = build_rendering_contract()
    if pack.generation_contract.contract_hash != canonical_contract.contract_hash:
        issues.append("PACK_RENDERING_CONTRACT_MISMATCH")
    expected_pack_hash = stable_hash(
        {
            "task_context": pack.task_context,
            "slice_spec": pack.knowledge_context.get("slice_spec", {}),
            "locked_facts": [
                {"fact_lock_id": fact.fact_lock_id, "lock_hash": fact.lock_hash}
                for fact in pack.locked_facts
            ],
            "abstention_summary": pack.abstention_summary,
            "contract_hash": pack.generation_contract.contract_hash,
        }
    )
    if pack.pack_hash != expected_pack_hash:
        issues.append("PACK_HASH_INVALID")
    return issues


def rendering_contract_hash_valid(contract_payload: dict[str, Any]) -> bool:
    """Return whether a serialized RenderingContract hash matches its content."""

    return contract_payload.get("contract_hash") == rendering_contract_hash(contract_payload)


def upstream_hash_issue_count(repo_root: Path) -> int:
    """Validate frozen upstream file hash manifests without modifying upstream artifacts."""

    manifests = [
        repo_root / "artifacts/stage4_bitemporal_state_metrics_v1_1/file_hashes.sha256",
        repo_root / "artifacts/stage5a_typed_claim_contract_v1_1/file_hashes.sha256",
        repo_root / "artifacts/stage5b_deterministic_claim_builder_v1/file_hashes.sha256",
        repo_root / "artifacts/stage5c_claim_expressibility_analysis_v1/file_hashes.sha256",
    ]
    issue_count = 0
    for manifest in manifests:
        issue_count += _manifest_issue_count(manifest)
    return issue_count


def _manifest_issue_count(manifest: Path) -> int:
    base = manifest.parent
    count = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, rel_path = line.split(maxsplit=1)
        path = base / rel_path.strip()
        if not path.exists():
            count += 1
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        count += int(actual != expected)
    return count


def stage5c_tag_valid(repo_root: Path) -> bool:
    """Check the Stage5C frozen method remains present and frozen."""

    method = read_json(
        repo_root / "artifacts/stage5c_claim_expressibility_analysis_v1/method_version.json"
    )
    return (
        method.get("method_version") == "stage5c_claim_expressibility_analysis_v1_frozen"
        and method.get("status") == "FROZEN"
    )
