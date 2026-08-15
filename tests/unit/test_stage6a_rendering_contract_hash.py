"""Stage6A RenderingContract hash integrity tests."""

from __future__ import annotations

from tbm_twin.realization.evidence_pack import build_controlled_evidence_pack
from tbm_twin.realization.models import ControlledEvidencePack, LockedEngineeringFact
from tbm_twin.realization.rendering_contract import (
    build_rendering_contract,
    rendering_contract_hash,
)
from tbm_twin.realization.validation import rendering_contract_hash_valid, validate_pack_boundary
from tests.unit.stage6a_helpers import read_json, read_jsonl, stage6a_artifact


def test_stage6a_same_contract_hash_is_stable() -> None:
    assert build_rendering_contract().contract_hash == build_rendering_contract().contract_hash


def test_stage6a_contract_hash_changes_when_must_not_changes() -> None:
    payload = build_rendering_contract().model_dump(mode="json")
    original = payload["contract_hash"]
    payload["must_not"].append("new_forbidden_semantic")

    assert rendering_contract_hash(payload) != original


def test_stage6a_contract_hash_changes_when_claim_policy_changes() -> None:
    payload = build_rendering_contract().model_dump(mode="json")
    original = payload["contract_hash"]
    payload["claim_type_policies"]["FORECAST_GEOLOGICAL_CONDITION"]["forbidden_terms"].append(
        "new_term"
    )

    assert rendering_contract_hash(payload) != original


def test_stage6a_pack_hash_binds_contract_hash(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    locks = [LockedEngineeringFact(**row) for row in read_jsonl(artifact / "fact_locks.jsonl")[:5]]
    pack = build_controlled_evidence_pack(locks, [], task_context="contract_hash_probe")
    payload = pack.model_dump(mode="json")
    payload["generation_contract"]["contract_hash"] = "tampered"
    tampered = ControlledEvidencePack(**payload)

    assert "PACK_RENDERING_CONTRACT_MISMATCH" in validate_pack_boundary(tampered)
    assert "PACK_HASH_INVALID" in validate_pack_boundary(tampered)


def test_stage6a_contract_id_same_content_tamper_is_detected(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    contract = read_json(artifact / "rendering_contract.json")
    contract["must_not"].append("tampered")

    assert not rendering_contract_hash_valid(contract)


def test_stage6a_serialized_contract_hash_is_valid(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    contract = read_json(artifact / "rendering_contract.json")

    assert rendering_contract_hash_valid(contract)
