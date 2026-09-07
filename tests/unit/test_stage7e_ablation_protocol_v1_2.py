"""Stage7E-A v1.2 executable-protocol regression tests."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pytest

from tbm_twin.evaluation.stage7e_protocol import NO_OUTPUT_TASKS, PROVIDER_CONFIG, _canonical
from tbm_twin.evaluation.stage7e_protocol_v1_2 import (
    A3_MAX_CLAIMS,
    A3_MAX_ESTIMATED_RESPONSE_CHARACTERS,
    _analyze,
    _load_v1_2_inputs,
    _semantic_analysis,
)
from tbm_twin.realization.io import stable_hash

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def inputs() -> dict[str, Any]:
    return _load_v1_2_inputs(REPO_ROOT)


@pytest.fixture(scope="module")
def analysis(inputs: dict[str, Any]) -> dict[str, Any]:
    return _analyze(inputs)


def _requests(analysis: dict[str, Any], arm: str) -> list[dict[str, Any]]:
    return [row for row in analysis["requests"] if row["arm_internal"] == arm]


def _message_text(rows: list[dict[str, Any]]) -> str:
    return "\n".join(_canonical(row["messages"]).lower() for row in rows)


def test_01_a1_infeasibility_is_reproducible(analysis: dict[str, Any]) -> None:
    rows = analysis["a1_feasibility"]
    assert len(rows) == 163
    assert len({row["proposal_id"] for row in rows}) == 145
    assert len({row["task_id"] for row in rows}) == 25
    assert Counter(row["original_abstain_reason"] for row in rows) == {
        "CONTEXT_ONLY_ROLE": 100,
        "STATE_ROLE_NOT_ALLOWED": 53,
        "REQUIRED_EPISTEMIC_STATUS_MISSING": 10,
    }


def test_02_a1_has_no_executable_request(analysis: dict[str, Any]) -> None:
    assert _requests(analysis, "A1_NO_SEMANTIC_CLAIM_GATE") == []
    assert analysis["budget"]["A1_NO_SEMANTIC_CLAIM_GATE"] == 0
    assert analysis["a1_gate_bypass_count"] == 0


def test_03_a1_never_fabricates_values(analysis: dict[str, Any]) -> None:
    assert all(row["no_value_fabrication"] for row in analysis["a1_feasibility"])
    assert all(row["resolved_candidate_value"] == "" for row in analysis["a1_feasibility"])
    assert all(
        row["value_resolution_basis"] == "NO_AVAILABLE_CONCRETE_VALUE"
        for row in analysis["a1_feasibility"]
    )


def test_04_a2_target_set_matches_frozen_v1(analysis: dict[str, Any]) -> None:
    targets = analysis["a2_targets"]
    assert len(targets) == 31
    assert len({row["task_id"] for row in targets}) == 24
    assert len({(row["task_id"], row["section_id"]) for row in targets}) == 31


def test_05_a2_contexts_are_semantically_resolved(analysis: dict[str, Any]) -> None:
    assert len(analysis["a2_contexts"]) == 31
    assert len(analysis["a2_resolution"]) == 56
    assert all(row["status"] == "PASS" for row in analysis["a2_resolution"])
    assert all(
        context["context_resolution_status"] == "PASS" for context in analysis["a2_contexts"]
    )


def test_06_a2_has_no_opaque_only_payload(analysis: dict[str, Any]) -> None:
    assert not any(row["opaque_only"] for row in analysis["a2_resolution"])
    for context in analysis["a2_contexts"]:
        assert all(
            item.get("exact_value") is not None
            or item.get("unavailable_explanation")
            or item.get("structured_attributes")
            for item in context["engineering_context_items"]
        )


def test_07_a2_messages_exclude_gate_metadata(analysis: dict[str, Any]) -> None:
    message = _message_text(_requests(analysis, "A2_NO_ARCHITECTURAL_ABSTENTION"))
    forbidden = (
        "expressible",
        "abstain",
        "claim contract",
        "original_abstain_reason",
        "state_role_not_allowed",
        "context_only_role",
        "required_epistemic_status_missing",
    )
    assert all(token not in message for token in forbidden)


def test_08_a3_typed_claim_identity(analysis: dict[str, Any]) -> None:
    pairs = [(row["task_id"], row["claim_id"]) for row in analysis["a3_claims"]]
    assert len(pairs) == 989
    assert len(set(pairs)) == 989
    assert len({task_id for task_id, _ in pairs}) == 45


def test_09_a3_frozen_plan_identity(analysis: dict[str, Any]) -> None:
    assert sum(row["p_plan_reused"] for row in analysis["a3_plan_audit"]) == 45
    excluded = {row["task_id"] for row in analysis["a3_plan_audit"] if row["expected_no_output"]}
    assert excluded == NO_OUTPUT_TASKS


def test_10_a3_every_claim_occurs_once(analysis: dict[str, Any]) -> None:
    source = Counter((row["task_id"], row["claim_id"]) for row in analysis["a3_claims"])
    chunked = Counter(
        (chunk["task_id"], claim["claim_id"])
        for chunk in analysis["a3_chunks"]
        for claim in chunk["claims"]
    )
    assert source == chunked
    assert set(source.values()) == {1}


def test_11_a3_chunk_claim_limit(analysis: dict[str, Any]) -> None:
    assert len(analysis["a3_chunks"]) == 147
    assert max(chunk["claim_count"] for chunk in analysis["a3_chunks"]) <= A3_MAX_CLAIMS


def test_12_a3_output_budget(analysis: dict[str, Any]) -> None:
    assert all(row["within_budget"] == "PASS" for row in analysis["a3_budget_rows"])
    assert (
        max(row["estimated_minimum_response_characters"] for row in analysis["a3_budget_rows"])
        <= A3_MAX_ESTIMATED_RESPONSE_CHARACTERS
    )


def test_13_a3_reconstruction_ordering(analysis: dict[str, Any]) -> None:
    expected: dict[str, list[str]] = defaultdict(list)
    actual: dict[str, list[str]] = defaultdict(list)
    for task_id in sorted({row["task_id"] for row in analysis["a3_claims"]}):
        rows = sorted(
            (row for row in analysis["a3_claims"] if row["task_id"] == task_id),
            key=lambda row: int(row["order_index"]),
        )
        expected[task_id] = [str(row["claim_id"]) for row in rows]
    for chunk in sorted(
        analysis["a3_chunks"], key=lambda row: (row["task_id"], row["chunk_index"])
    ):
        actual[chunk["task_id"]].extend(str(row["claim_id"]) for row in chunk["claims"])
    assert actual == expected


def test_14_a4_factlock_identity(analysis: dict[str, Any]) -> None:
    source = {(row["task_id"], row["fact_lock_id"]) for row in analysis["a4_facts"]}
    normalized = {
        (task_id, row["fact_lock_id"])
        for task_id, payload in analysis["a4_registry"]["tasks"].items()
        for row in payload["facts"]
    }
    assert len(source) == 1022
    assert normalized == source


def test_15_a4_normalized_roundtrip_is_lossless(analysis: dict[str, Any]) -> None:
    assert len(analysis["a4_roundtrip"]) == 1022
    assert all(row["status"] == "PASS" for row in analysis["a4_roundtrip"])
    assert analysis["a4_registry"]["global_prohibited_transformation_set_count"] == 1


def test_16_a4_messages_exclude_canonical_sentences(analysis: dict[str, Any]) -> None:
    message = _message_text(_requests(analysis, "A4_FREE_FINAL_REALIZATION"))
    assert "canonical_sentence" not in message


def test_17_a4_messages_exclude_p_plan(analysis: dict[str, Any]) -> None:
    message = _message_text(_requests(analysis, "A4_FREE_FINAL_REALIZATION"))
    assert "ordered_unit_ids" not in message
    assert "plan_id" not in message


def test_18_a4_payload_is_reduced_without_fact_deletion(analysis: dict[str, Any]) -> None:
    sizes = analysis["a4_size"]
    assert sizes["v1"]["maximum"] == 223663
    assert sizes["v1_2"]["maximum"] < sizes["v1"]["maximum"]
    assert sizes["max_character_reduction_percentage"] > 0
    assert sizes["fact_deletion_count"] == 0


def test_19_all_requests_share_the_frozen_model_config(analysis: dict[str, Any]) -> None:
    assert {_canonical(row["inference_config"]) for row in analysis["requests"]} == {
        _canonical(PROVIDER_CONFIG)
    }
    assert PROVIDER_CONFIG == {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "temperature": 0.0,
        "top_p": 1.0,
        "reasoning_effort": "none",
        "max_output_tokens": 4096,
        "max_retries": 0,
        "sdk_max_retries": 0,
        "api_key_env_var": "DEEPSEEK_API_KEY",
    }


def test_20_model_messages_have_no_experiment_identity(analysis: dict[str, Any]) -> None:
    assert len(analysis["leak_rows"]) == 226
    assert all(row["status"] == "PASS" for row in analysis["leak_rows"])


def test_21_request_hashes_are_deterministic(
    inputs: dict[str, Any], analysis: dict[str, Any]
) -> None:
    rebuilt = _analyze(inputs)
    first = [(row["request_id"], row["payload_hash"]) for row in analysis["requests"]]
    second = [(row["request_id"], row["payload_hash"]) for row in rebuilt["requests"]]
    assert first == second
    assert len(first) == len({request_id for request_id, _ in first})


def test_22_exact_asof_inputs_have_no_future_evidence(analysis: dict[str, Any]) -> None:
    assert len(analysis["bundle_audit"]) == 48
    assert all(row["status"] == "PASS" for row in analysis["bundle_audit"])
    assert all(row["no_later_evidence"] for row in analysis["bundle_audit"])


def test_23_protocol_materializes_without_api_or_llm(analysis: dict[str, Any]) -> None:
    assert analysis["budget"] == {
        "P_FULL": 0,
        "A1_NO_SEMANTIC_CLAIM_GATE": 0,
        "A2_NO_ARCHITECTURAL_ABSTENTION": 31,
        "A3_NO_FACTLOCK": 147,
        "A4_FREE_FINAL_REALIZATION": 48,
        "total": 226,
        "executed_this_round": 0,
    }
    assert {row["execution_status"] for row in analysis["requests"]} == {"MATERIALIZED_NOT_SENT"}


def test_24_complete_semantic_rebuild_is_deterministic(
    inputs: dict[str, Any], analysis: dict[str, Any]
) -> None:
    rebuilt = _analyze(inputs)
    assert stable_hash(_semantic_analysis(analysis)) == stable_hash(_semantic_analysis(rebuilt))
