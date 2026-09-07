from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from tbm_twin.evaluation.stage7d import (
    METRIC_TYPES,
    _analyze,
    _claim_epistemic_status,
    _claim_transition_matrix,
    _experiment_protocol,
    _future_evidence_rows,
    _hindsight_enabled_rows,
    _is_active_at,
    _load_inputs,
    _logical_claim_key,
    _mechanical_rewrite_rows,
    _metric_pair_rows,
    _no_later_support_in_exact,
    _select_cases,
    _task_level_rows,
    _unknown_to_known_rows,
)
from tbm_twin.realization.io import stable_hash

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def inputs() -> Any:
    return _load_inputs(REPO_ROOT)


@pytest.fixture(scope="module")
def analysis(inputs: Any) -> dict[str, Any]:
    return _analyze(inputs)


def _revision_binding(inputs: Any) -> dict[str, Any]:
    histories: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for version in inputs.versions:
        histories[(str(version["valid_date"]), str(version["cell_id"]))].append(version)
    for (valid_date, cell_id), history in sorted(histories.items()):
        if len(history) < 2:
            continue
        ordered = sorted(history, key=lambda row: int(row["version_number"]))
        exact, final = ordered[0], ordered[-1]
        if set(_evidence_ids(final)) - set(_evidence_ids(exact)):
            return {
                "task_id": "synthetic_revision_task",
                "cell_id": cell_id,
                "exact_state_version_id": exact["bitemporal_version_id"],
                "final_state_version_id": final["bitemporal_version_id"],
                "knowledge_as_of": exact["knowledge_time_start_local_date"],
                "state_role": exact["cell_scope_role"],
                "later_version_used": True,
                "valid_date": valid_date,
            }
    raise AssertionError("Frozen corpus has no revision with added evidence")


def _evidence_ids(version: dict[str, Any]) -> list[str]:
    return [
        str(value)
        for field in (
            "materialized_daily_review_evidence_ids",
            "materialized_forward_attention_evidence_ids",
            "materialized_local_background_evidence_ids",
        )
        for value in version.get(field, [])
    ]


def test_exact_asof_uses_half_open_interval() -> None:
    version = {
        "knowledge_time_start_local_date": "2023-10-07",
        "knowledge_time_end_local_date": "2023-10-09",
    }
    assert _is_active_at(version, "2023-10-07")
    assert _is_active_at(version, "2023-10-08")
    assert not _is_active_at(version, "2023-10-09")


def test_final_history_is_latest_same_valid_state(analysis: dict[str, Any]) -> None:
    assert all(row["final_is_latest"] for row in analysis["binding_rows"])


def test_arms_keep_same_valid_date_and_cell(analysis: dict[str, Any]) -> None:
    assert all(row["same_valid_date"] and row["same_cell"] for row in analysis["binding_rows"])


def test_no_future_valid_date_contamination(analysis: dict[str, Any]) -> None:
    assert {row["valid_date"] for row in analysis["binding_rows"]} == {
        row["valid_date"] for row in analysis["task_rows"]
    }


def test_later_evidence_has_provenance(inputs: Any) -> None:
    rows = _future_evidence_rows(inputs, [_revision_binding(inputs)])
    assert rows
    assert all(row["evidence_id"] and row["source_document_id"] for row in rows)
    assert all(row["available_strictly_after_as_of"] for row in rows)


def test_affected_state_detection_on_revision(inputs: Any) -> None:
    binding = _revision_binding(inputs)
    assert binding["exact_state_version_id"] != binding["final_state_version_id"]
    assert binding["later_version_used"] is True


def test_metric_pairing_covers_three_frozen_metrics(inputs: Any) -> None:
    rows = _metric_pair_rows(inputs, [_revision_binding(inputs)])
    assert {row["metric_type"] for row in rows} == set(METRIC_TYPES)


def test_rai_is_independent_of_later_geology(inputs: Any) -> None:
    binding = _revision_binding(inputs)
    metrics = _metric_pair_rows(inputs, [binding])
    audit = _mechanical_rewrite_rows(inputs, [binding], metrics)
    assert len(audit) == 1
    assert audit[0]["unintended_mechanical_rewrite"] is False


def test_claim_logical_key_ignores_version_wrapper_identity() -> None:
    base = {
        "claim_type": "OPERATIONAL_RESPONSE_ATTENTION",
        "opportunity": {
            "base_stage3a_state_version_id": "base",
            "bitemporal_version_id": "v1",
            "valid_date": "2023-10-07",
            "cell_id": "cell",
            "state_role": "DAILY_REVIEW_CELL",
            "source_kind": "STATE_RAI",
            "payload": {"metric_name": "RAI", "metric_id": "metric-v1"},
        },
        "proposal": {"claim_value": {"metric_name": "RAI", "metric_value": 0.2}},
    }
    revised = {
        **base,
        "opportunity": {
            **base["opportunity"],
            "bitemporal_version_id": "v2",
            "payload": {"metric_name": "RAI", "metric_id": "metric-v2"},
        },
    }
    assert _logical_claim_key("task", base) == _logical_claim_key("task", revised)


def test_abstain_to_expressible_transition_is_detected() -> None:
    matrix = _claim_transition_matrix(
        [{"pairing_status": "MATCHED", "transition": "ABSTAIN_TO_EXPRESSIBLE"}]
    )
    assert matrix["ABSTAIN_TO_EXPRESSIBLE"] == 1


def test_hindsight_enabled_claim_requires_later_support() -> None:
    claim = {
        "task_id": "task",
        "cell_id": "cell",
        "claim_opportunity_key": "key",
        "claim_type": "OBSERVED_GEOLOGICAL_CONDITION",
        "transition": "ABSTAIN_TO_EXPRESSIBLE",
        "exact_abstain_reason": "REQUIRED_EPISTEMIC_STATUS_MISSING",
        "final_value": "known",
        "later_support_ids": "evidence",
    }
    leakage = [
        {
            "task_id": "task",
            "cell_id": "cell",
            "evidence_id": "evidence",
            "available_local_date": "2023-10-09",
            "days_after_as_of": 2,
        }
    ]
    assert _hindsight_enabled_rows([claim], leakage)[0]["later_support_provenance_present"]
    assert not _no_later_support_in_exact([{**claim, "exact_support_ids": "evidence"}], leakage)


def test_observed_claim_epistemic_status_is_preserved() -> None:
    record = {"claim_type": "OBSERVED_GEOLOGICAL_CONDITION"}
    assert _claim_epistemic_status(record) == "OBSERVED"


def test_unknown_to_known_classification() -> None:
    row = {
        "pairing_status": "MATCHED",
        "task_id": "task",
        "cell_id": "cell",
        "claim_opportunity_key": "key",
        "claim_type": "FORECAST_GEOLOGICAL_CONDITION",
        "exact_abstain_reason": "UNKNOWN_SOURCE_VALUE",
        "exact_value": '{"normalized_value":"UNKNOWN"}',
        "final_value": '{"normalized_value":"IV"}',
        "exact_decision": "ABSTAIN",
        "final_decision": "EXPRESSIBLE",
        "later_support_ids": "evidence",
    }
    assert _unknown_to_known_rows([row])[0]["transition_class"] == "UNKNOWN_TO_KNOWN"


def test_task_level_aggregation_counts_multiple_cells(inputs: Any) -> None:
    bindings = [
        {
            "task_id": "task",
            "product_type": "all",
            "valid_date": "2023-10-07",
            "knowledge_as_of": "2023-10-07",
            "later_version_used": False,
        },
        {
            "task_id": "task",
            "product_type": "all",
            "valid_date": "2023-10-07",
            "knowledge_as_of": "2023-10-07",
            "later_version_used": True,
        },
    ]
    row = _task_level_rows(inputs, bindings, [], [], [], [])[0]
    assert row["number_of_cells"] == 2
    assert row["affected_state_cells"] == 1
    assert row["task_affected_by_hindsight"] is True


def test_case_selection_is_deterministic() -> None:
    rows = [
        {
            "task_id": "b",
            "valid_date": "2023-10-08",
            "knowledge_as_of": "2023-10-08",
            "task_affected_by_hindsight": True,
            "later_evidence_count": 2,
            "claim_decision_change_count": 1,
            "hindsight_enabled_claim_count": 1,
            "observed_claim_newly_enabled_count": 0,
        },
        {
            "task_id": "a",
            "valid_date": "2023-10-07",
            "knowledge_as_of": "2023-10-07",
            "task_affected_by_hindsight": True,
            "later_evidence_count": 2,
            "claim_decision_change_count": 0,
            "hindsight_enabled_claim_count": 0,
            "observed_claim_newly_enabled_count": 0,
        },
    ]
    assert _select_cases(rows) == _select_cases(list(reversed(rows)))
    assert _select_cases(rows)[0]["task_id"] == "a"


def test_rebuild_is_semantically_deterministic(inputs: Any, analysis: dict[str, Any]) -> None:
    assert stable_hash(analysis) == stable_hash(_analyze(inputs))


def test_frozen_main_benchmark_has_48_tasks(inputs: Any, analysis: dict[str, Any]) -> None:
    assert len(inputs.tasks) == 48
    assert len({row["task_id"] for row in analysis["binding_rows"]}) == 48


def test_stage7d_performs_no_api_or_llm_calls(analysis: dict[str, Any]) -> None:
    assert analysis["primary_endpoints"]["P1"]["denominator"] == 48
    protocol = _experiment_protocol(_load_inputs(REPO_ROOT))
    assert protocol["api_calls"] == protocol["llm_calls"] == 0
