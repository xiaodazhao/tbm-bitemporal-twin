"""Stage7E-A frozen ablation protocol regression tests."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from tbm_twin.evaluation.stage7e_protocol import (
    MISSING_VALUE_REASONS,
    NO_OUTPUT_TASKS,
    PROVIDER_CONFIG,
    _analyze,
    _canonical,
    _load_inputs,
    _semantic_analysis,
)
from tbm_twin.realization.io import stable_hash

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def inputs() -> dict[str, Any]:
    return _load_inputs(REPO_ROOT)


@pytest.fixture(scope="module")
def analysis(inputs: dict[str, Any]) -> dict[str, Any]:
    return _analyze(inputs)


def _requests(analysis: dict[str, Any], arm: str) -> list[dict[str, Any]]:
    return [row for row in analysis["requests"] if row["arm_internal"] == arm]


def _messages(rows: list[dict[str, Any]]) -> list[str]:
    return [_canonical(row["messages"]) for row in rows]


def test_01_frozen_benchmark_has_exact_tasks_and_quotas(inputs: dict[str, Any]) -> None:
    assert len(inputs["tasks"]) == 48
    assert Counter(row["product_type"] for row in inputs["tasks"]) == {
        "all": 12,
        "daily_review": 12,
        "forward_attention": 12,
        "metric_review": 12,
    }


def test_02_same_task_context_is_bound_across_all_arms(analysis: dict[str, Any]) -> None:
    rows = analysis["condition_rows"]
    assert len(rows) == 240
    assert Counter(row["task_id"] for row in rows) == Counter(
        {row["task_id"]: 5 for row in analysis["task_rows"]}
    )
    task_context = {
        row["task_id"]: (row["valid_date"], row["knowledge_as_of"]) for row in analysis["task_rows"]
    }
    assert all(
        (row["valid_date"], row["knowledge_as_of"]) == task_context[row["task_id"]] for row in rows
    )


def test_03_exact_asof_bundles_contain_no_later_evidence(analysis: dict[str, Any]) -> None:
    assert len(analysis["bundle_audit"]) == 48
    assert all(row["no_later_evidence"] for row in analysis["bundle_audit"])
    assert all(row["status"] == "PASS" for row in analysis["bundle_audit"])


def test_04_a1_keeps_only_structurally_renderable_candidates(
    analysis: dict[str, Any],
) -> None:
    assert analysis["a1_candidates"]
    assert all(row["structurally_renderable"] for row in analysis["a1_candidates"])


def test_05_a1_preserves_original_contract_decisions(analysis: dict[str, Any]) -> None:
    assert all(
        row["original_contract_decision"] in {"EXPRESSIBLE", "ABSTAIN"}
        for row in analysis["a1_candidates"]
    )
    assert all(
        row["contract_admissible"] == (row["original_contract_decision"] == "EXPRESSIBLE")
        for row in analysis["a1_candidates"]
    )


def test_06_a1_never_fabricates_missing_values(analysis: dict[str, Any]) -> None:
    ineligible = [row for row in analysis["a1_candidates"] if not row["contract_admissible"]]
    assert all(row["original_abstain_reason"] not in MISSING_VALUE_REASONS for row in ineligible)
    # Frozen Stage5B has no concrete-valued semantic rejection in these tasks.
    assert ineligible == []


def test_07_a2_targets_only_zero_legal_factlock_sections(
    analysis: dict[str, Any],
) -> None:
    assert analysis["a2_targets"]
    assert all(row["legal_fact_lock_count"] == 0 for row in analysis["a2_targets"])
    assert len({(row["task_id"], row["section_id"]) for row in analysis["a2_targets"]}) == len(
        analysis["a2_targets"]
    )


def test_08_a2_leaves_legal_and_invalid_plan_tasks_untouched(
    analysis: dict[str, Any],
) -> None:
    assert not ({row["task_id"] for row in analysis["a2_targets"]} & NO_OUTPUT_TASKS)
    for row in analysis["a2_targets"]:
        bundle = analysis["bundles"][row["task_id"]]
        legal_sections = {
            {
                "FORECAST_GEOLOGICAL_CONDITION": "geological_forecast",
                "OBSERVED_GEOLOGICAL_CONDITION": "geological_observed",
                "OPERATIONAL_RESPONSE_ATTENTION": "operational_attention",
                "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW": "geological_attention",
                "COUPLED_ATTENTION_REVIEW": "coupled_attention",
                "FORWARD_GEOLOGICAL_ATTENTION": "forward_attention",
            }[lock.claim_type]
            for lock in bundle["pack"].locked_facts
        }
        assert row["section_id"] not in legal_sections


def test_09_a3_claim_universe_equals_frozen_p_plan_selection(
    inputs: dict[str, Any], analysis: dict[str, Any]
) -> None:
    actual = {(row["task_id"], row["claim_id"]) for row in analysis["a3_claims"]}
    expected = set()
    for task_id, plan in inputs["plan_by_task"].items():
        if task_id in NO_OUTPUT_TASKS:
            continue
        units = {unit.realization_unit_id: unit for unit in analysis["bundles"][task_id]["units"]}
        for section in plan["sections"]:
            for unit_id in section["ordered_unit_ids"]:
                for lock_id in units[unit_id].member_fact_lock_ids:
                    expected.add((task_id, inputs["lock_by_id"][lock_id].source_claim_id))
    assert actual == expected


def test_10_a3_reuses_all_45_valid_frozen_plans(analysis: dict[str, Any]) -> None:
    assert sum(row["p_plan_reused"] for row in analysis["a3_plan_audit"]) == 45
    assert len(_requests(analysis, "A3_NO_FACTLOCK")) == 45


def test_11_a3_keeps_the_three_frozen_no_output_tasks(analysis: dict[str, Any]) -> None:
    actual = {row["task_id"] for row in analysis["a3_plan_audit"] if row["expected_no_output"]}
    assert actual == NO_OUTPUT_TASKS
    assert not ({row["task_id"] for row in _requests(analysis, "A3_NO_FACTLOCK")} & actual)


def test_12_a3_messages_contain_no_factlock_payload(analysis: dict[str, Any]) -> None:
    assert all(
        "fact_lock" not in message.lower()
        for message in _messages(_requests(analysis, "A3_NO_FACTLOCK"))
    )


def test_13_a4_factlock_identity_equals_frozen_task_packs(
    analysis: dict[str, Any],
) -> None:
    actual = {(row["task_id"], row["fact_lock_id"]) for row in analysis["a4_facts"]}
    expected = {
        (task_id, lock.fact_lock_id)
        for task_id, bundle in analysis["bundles"].items()
        for lock in bundle["pack"].locked_facts
    }
    assert actual == expected


def test_14_a4_messages_contain_no_canonical_sentence(analysis: dict[str, Any]) -> None:
    assert all(
        "canonical_sentence" not in message.lower()
        for message in _messages(_requests(analysis, "A4_FREE_FINAL_REALIZATION"))
    )


def test_15_a4_messages_contain_no_frozen_plan(analysis: dict[str, Any]) -> None:
    assert all(
        "ordered_unit_ids" not in message and "plan_id" not in message
        for message in _messages(_requests(analysis, "A4_FREE_FINAL_REALIZATION"))
    )


def test_16_all_new_requests_share_one_deepseek_config(analysis: dict[str, Any]) -> None:
    assert {_canonical(row["inference_config"]) for row in analysis["requests"]} == {
        _canonical(PROVIDER_CONFIG)
    }


def test_17_prompt_hashes_are_deterministic(inputs: dict[str, Any]) -> None:
    first = {name: stable_hash(text) for name, text in inputs["prompts"].items()}
    second = {name: stable_hash(text) for name, text in inputs["prompts"].items()}
    assert len(first) == 8
    assert first == second


def test_18_request_payload_hashes_are_deterministic(
    inputs: dict[str, Any], analysis: dict[str, Any]
) -> None:
    rebuilt = _analyze(inputs)
    assert analysis["requests"] == rebuilt["requests"]
    assert len({row["request_id"] for row in analysis["requests"]}) == len(analysis["requests"])


def test_19_expected_api_budget_is_deterministic(analysis: dict[str, Any]) -> None:
    budget = analysis["budget"]
    assert budget["total"] == sum(
        budget[arm]
        for arm in (
            "P_FULL",
            "A1_NO_SEMANTIC_CLAIM_GATE",
            "A2_NO_ARCHITECTURAL_ABSTENTION",
            "A3_NO_FACTLOCK",
            "A4_FREE_FINAL_REALIZATION",
        )
    )
    assert budget == {
        "P_FULL": 0,
        "A1_NO_SEMANTIC_CLAIM_GATE": 48,
        "A2_NO_ARCHITECTURAL_ABSTENTION": 31,
        "A3_NO_FACTLOCK": 45,
        "A4_FREE_FINAL_REALIZATION": 48,
        "total": 172,
        "executed_this_round": 0,
    }


def test_20_p_full_is_reused_without_new_requests(analysis: dict[str, Any]) -> None:
    assert len(analysis["p_rows"]) == 48
    assert sum(row["frozen_output_available"] for row in analysis["p_rows"]) == 45
    assert sum(row["planned_new_api_calls"] for row in analysis["p_rows"]) == 0
    assert _requests(analysis, "P_FULL") == []


def test_21_stage7e_a_materializes_but_never_executes_requests(
    analysis: dict[str, Any],
) -> None:
    assert analysis["budget"]["executed_this_round"] == 0
    assert {row["execution_status"] for row in analysis["requests"]} == {"MATERIALIZED_NOT_SENT"}
    source = (REPO_ROOT / "src/tbm_twin/evaluation/stage7e_protocol.py").read_text()
    assert "responses.create" not in source
    assert "chat.completions" not in source


def test_22_complete_semantic_rebuild_is_deterministic(
    inputs: dict[str, Any], analysis: dict[str, Any]
) -> None:
    rebuilt = _analyze(inputs)
    assert stable_hash(_semantic_analysis(analysis)) == stable_hash(_semantic_analysis(rebuilt))
