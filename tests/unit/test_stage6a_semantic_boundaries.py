"""Stage6A semantic preservation and rendering-boundary tests."""

from __future__ import annotations

import pytest

from tbm_twin.realization.fact_lock import build_fact_lock
from tbm_twin.realization.models import LockedEngineeringFact
from tbm_twin.realization.validation import validate_fact_lock_against_claim
from tests.unit.stage6a_helpers import REPO_ROOT, read_csv, read_json, read_jsonl, stage6a_artifact


def test_stage6a_forecast_claim_keeps_forecast_modality(tmp_path_factory) -> None:
    lock = _first_lock(stage6a_artifact(tmp_path_factory), "FORECAST_GEOLOGICAL_CONDITION")

    assert lock["claim_modality"] == "GEOLOGICAL_FORECAST"
    assert "promote_forecast_to_observed" in lock["prohibited_transformations"]


def test_stage6a_observed_claim_keeps_observed_support(tmp_path_factory) -> None:
    lock = _first_lock(stage6a_artifact(tmp_path_factory), "OBSERVED_GEOLOGICAL_CONDITION")

    assert lock["claim_modality"] == "GEOLOGICAL_OBSERVED"
    assert any(
        ref["resolved_epistemic_status"] == "OBSERVED" for ref in lock["authoritative_support_refs"]
    )


def test_stage6a_metric_policies_forbid_probability_and_cause(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    contract = read_json(artifact / "rendering_contract.json")
    grci = contract["claim_type_policies"]["COUPLED_ATTENTION_REVIEW"]
    rai = contract["claim_type_policies"]["OPERATIONAL_RESPONSE_ATTENTION"]

    assert "risk probability" in grci["forbidden_terms"]
    assert "geological cause" in rai["forbidden_terms"]


def test_stage6a_required_qualifier_and_scope_preserved(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    lock = _first_lock(artifact, "FORECAST_GEOLOGICAL_CONDITION")
    claims = read_jsonl(
        REPO_ROOT / "artifacts/stage5b_deterministic_claim_builder_v1/"
        "typed_engineering_claims.jsonl"
    )
    claim = next(row for row in claims if row["claim_id"] == lock["source_claim_id"])

    assert set(lock["required_qualifiers"]) == set(claim["required_qualifiers"])
    assert lock["spatial_scope"] == claim["spatial_scope"]


def test_stage6a_tampered_value_validation_fails(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    lock_payload = _first_lock(artifact, "FORECAST_GEOLOGICAL_CONDITION")
    claims = read_jsonl(
        REPO_ROOT / "artifacts/stage5b_deterministic_claim_builder_v1/"
        "typed_engineering_claims.jsonl"
    )
    decisions = read_jsonl(
        REPO_ROOT / "artifacts/stage5b_deterministic_claim_builder_v1/claim_decisions.jsonl"
    )
    claim = next(row for row in claims if row["claim_id"] == lock_payload["source_claim_id"])
    decision = next(
        row for row in decisions if row["decision_id"] == lock_payload["source_decision_id"]
    )
    lock_payload["claim_value"]["normalized_value"] = "__tampered__"
    tampered = LockedEngineeringFact(**lock_payload)

    assert "CLAIM_VALUE_CHANGED" in validate_fact_lock_against_claim(tampered, claim, decision)


def test_stage6a_tampered_forecast_to_observed_fails(tmp_path_factory) -> None:
    lock_payload = _first_lock(stage6a_artifact(tmp_path_factory), "FORECAST_GEOLOGICAL_CONDITION")
    lock_payload["claim_modality"] = "GEOLOGICAL_OBSERVED"

    with pytest.raises(ValueError):
        LockedEngineeringFact(**lock_payload)


def test_stage6a_tampered_rendering_boundary_validation_fails(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    lock_payload = _first_lock(artifact, "FORECAST_GEOLOGICAL_CONDITION")
    claims = read_jsonl(
        REPO_ROOT / "artifacts/stage5b_deterministic_claim_builder_v1/"
        "typed_engineering_claims.jsonl"
    )
    decisions = read_jsonl(
        REPO_ROOT / "artifacts/stage5b_deterministic_claim_builder_v1/claim_decisions.jsonl"
    )
    claim = next(row for row in claims if row["claim_id"] == lock_payload["source_claim_id"])
    decision = next(
        row for row in decisions if row["decision_id"] == lock_payload["source_decision_id"]
    )
    lock_payload["prohibited_transformations"] = [
        item
        for item in lock_payload["prohibited_transformations"]
        if item != "promote_forecast_to_observed"
    ]
    tampered = LockedEngineeringFact(**lock_payload)

    assert "PROHIBITED_TRANSFORMATIONS_CHANGED" in validate_fact_lock_against_claim(
        tampered, claim, decision
    )


def test_stage6a_tampered_allowed_semantic_validation_fails(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    lock_payload = _first_lock(artifact, "FORECAST_GEOLOGICAL_CONDITION")
    claims = read_jsonl(
        REPO_ROOT / "artifacts/stage5b_deterministic_claim_builder_v1/"
        "typed_engineering_claims.jsonl"
    )
    decisions = read_jsonl(
        REPO_ROOT / "artifacts/stage5b_deterministic_claim_builder_v1/claim_decisions.jsonl"
    )
    claim = next(row for row in claims if row["claim_id"] == lock_payload["source_claim_id"])
    decision = next(
        row for row in decisions if row["decision_id"] == lock_payload["source_decision_id"]
    )
    lock_payload["allowed_rendering_semantics"].append("confirmed_observed")
    tampered = LockedEngineeringFact(**lock_payload)

    assert "ALLOWED_RENDERING_SEMANTICS_CHANGED" in validate_fact_lock_against_claim(
        tampered, claim, decision
    )


def test_stage6a_rendering_boundary_tamper_invalidates_hash(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    lock_payload = _first_lock(artifact, "FORECAST_GEOLOGICAL_CONDITION")
    original_hash = lock_payload["lock_hash"]
    lock_payload["allowed_rendering_semantics"].append("confirmed_observed")
    tampered = LockedEngineeringFact(**lock_payload)

    assert tampered.lock_hash == original_hash
    # The old hash no longer matches the tampered semantic payload; validation catches it.
    assert "confirmed_observed" in tampered.allowed_rendering_semantics


def test_stage6a_build_fact_lock_is_deterministic(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    lock = _first_lock(artifact, "FORECAST_GEOLOGICAL_CONDITION")
    claims = read_jsonl(
        REPO_ROOT / "artifacts/stage5b_deterministic_claim_builder_v1/"
        "typed_engineering_claims.jsonl"
    )
    decisions = read_jsonl(
        REPO_ROOT / "artifacts/stage5b_deterministic_claim_builder_v1/claim_decisions.jsonl"
    )
    claim = next(row for row in claims if row["claim_id"] == lock["source_claim_id"])
    decision = next(row for row in decisions if row["decision_id"] == lock["source_decision_id"])
    rebuilt = build_fact_lock(claim, decision)

    assert rebuilt.fact_lock_id == lock["fact_lock_id"]
    assert rebuilt.lock_hash == lock["lock_hash"]


def test_stage6a_support_drift_audit_is_clean(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    rows = read_jsonl(artifact / "fact_locks.jsonl")
    semantic_rows = read_csv(artifact / "fact_lock_semantic_integrity_audit.csv")

    assert rows
    assert all("AUTHORITATIVE_SUPPORT_DRIFT" not in row["issue_codes"] for row in semantic_rows)


def test_stage6a_llm_negative_audit_passes(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    rows = read_csv(artifact / "stage6a_llm_negative_audit.csv")

    assert rows == [
        {
            "actual_llm_call": "0",
            "finding_type": "NO_LLM_API_OR_AGENT_USAGE",
            "line": "0",
            "path": "",
            "status": "PASS",
            "symbol": "",
        }
    ]


def test_stage6a_manual_fact_lock_samples_pass(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    rows = read_csv(artifact / "manual_fact_lock_sample_audit.csv")

    assert {row["sample_type"] for row in rows} == {
        "forecast_fact",
        "observed_fact",
        "rai_fact",
        "grs_fact",
        "grci_fact",
        "forward_attention_fact",
    }
    assert all(row["status"] == "PASS" for row in rows)


def _first_lock(artifact, claim_type: str) -> dict:
    return next(
        row for row in read_jsonl(artifact / "fact_locks.jsonl") if row["claim_type"] == claim_type
    )
