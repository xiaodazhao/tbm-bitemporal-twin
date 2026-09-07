from __future__ import annotations

import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from tbm_twin.evaluation.stage7d_revision import (
    EXPECTED_REVISION_EVENT_COUNT,
    _analyze,
    _load_inputs,
    _protocol,
    _select_cases,
    _write_audit_zip,
)
from tbm_twin.realization.io import stable_hash

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = REPO_ROOT / "artifacts/stage7d_bitemporal_value_v1_1"


@pytest.fixture(scope="module")
def inputs() -> dict[str, Any]:
    return _load_inputs(REPO_ROOT)


@pytest.fixture(scope="module")
def analysis(inputs: dict[str, Any]) -> dict[str, Any]:
    return _analyze(inputs)


def test_revision_census_contains_all_53_events(
    inputs: dict[str, Any], analysis: dict[str, Any]
) -> None:
    assert len(inputs["events"]) == EXPECTED_REVISION_EVENT_COUNT == 53
    assert len(analysis["pair_rows"]) == 53


def test_event_pre_and_post_ids_are_bound_exactly(
    inputs: dict[str, Any], analysis: dict[str, Any]
) -> None:
    expected = {
        (
            row["revision_event_id"],
            row["previous_bitemporal_version_id"],
            row["bitemporal_version_id"],
        )
        for row in inputs["events"]
    }
    actual = {
        (row["revision_event_id"], row["pre_version_id"], row["post_version_id"])
        for row in analysis["pair_rows"]
    }
    assert actual == expected


def test_revision_arms_keep_same_valid_date_and_cell(analysis: dict[str, Any]) -> None:
    assert all(row["same_valid_date"] and row["same_cell"] for row in analysis["pair_rows"])


def test_post_knowledge_is_strictly_later(analysis: dict[str, Any]) -> None:
    assert all(row["post_knowledge_later"] for row in analysis["pair_rows"])
    assert all(row["post_start_matches_availability"] for row in analysis["pair_rows"])


def test_later_evidence_provenance_is_resolved(analysis: dict[str, Any]) -> None:
    assert analysis["evidence_rows"]
    assert all(row["provenance_resolved"] for row in analysis["evidence_rows"])
    assert all(
        not row["present_in_pre"] and row["present_in_post"] for row in analysis["evidence_rows"]
    )


def test_event_links_and_unique_evidence_are_counted_separately(
    analysis: dict[str, Any],
) -> None:
    assert len(analysis["evidence_rows"]) == 72
    assert len({row["evidence_id"] for row in analysis["evidence_rows"]}) == 34


def test_frozen_epistemic_status_is_preserved(analysis: dict[str, Any]) -> None:
    assert all(row["source_epistemic_status_preserved"] for row in analysis["epistemic_rows"])
    assert {row["epistemic_status"] for row in analysis["evidence_rows"]} <= {
        "FORECAST",
        "OBSERVED",
        "BACKGROUND",
    }


def test_metric_pairs_bind_exact_pre_and_post_versions(analysis: dict[str, Any]) -> None:
    pairs = {
        row["revision_event_id"]: (row["pre_version_id"], row["post_version_id"])
        for row in analysis["pair_rows"]
    }
    assert len(analysis["metric_rows"]) == 53 * 3
    assert all(
        (row["pre_version_id"], row["post_version_id"]) == pairs[row["revision_event_id"]]
        for row in analysis["metric_rows"]
    )


def test_rai_mechanical_response_is_revision_independent(analysis: dict[str, Any]) -> None:
    assert all(row["status"] == "PASS" for row in analysis["mechanical_rows"])
    assert not any(row["mechanical_rewrite_failure"] for row in analysis["mechanical_rows"])


def test_claim_pipeline_is_independently_reexecuted(
    inputs: dict[str, Any], analysis: dict[str, Any]
) -> None:
    assert _protocol(inputs)["claim_pipeline"].startswith("INDEPENDENT_")
    assert _protocol(inputs)["stage5c_use"] == "POST_HOC_RECONCILIATION_ONLY"
    assert len(analysis["claim_rows"]) == 975


def test_logical_claim_keys_are_unique_in_each_arm(analysis: dict[str, Any]) -> None:
    assert all(row["status"] == "PASS" for row in analysis["key_audit"])


def test_opportunity_added_is_not_abstain_to_expressible(analysis: dict[str, Any]) -> None:
    added = [
        row for row in analysis["claim_rows"] if row["transition_class"] == "OPPORTUNITY_ADDED"
    ]
    assert added
    assert all(row["pre_decision"] == "" and row["post_decision"] for row in added)


def test_existing_abstain_to_expressible_is_detected(analysis: dict[str, Any]) -> None:
    transitions = Counter(row["transition_class"] for row in analysis["claim_rows"])
    assert transitions["ABSTAIN_TO_EXPRESSIBLE"] == 27


def test_claim_value_change_is_detected(analysis: dict[str, Any]) -> None:
    changed = [
        row for row in analysis["claim_rows"] if row["transition_class"] == "CLAIM_VALUE_CHANGED"
    ]
    assert len(changed) == 10
    assert all(row["business_claim_value_changed"] == "true" for row in changed)


def test_resolved_support_change_is_detected(analysis: dict[str, Any]) -> None:
    changed = [
        row
        for row in analysis["claim_rows"]
        if row["transition_class"] == "RESOLVED_SUPPORT_CHANGED"
    ]
    assert len(changed) == 26
    assert all(row["support_semantics_changed"] == "true" for row in changed)


def test_stage5c_reconciliation_has_no_mismatch(analysis: dict[str, Any]) -> None:
    assert len(analysis["reconciliation_rows"]) == 975
    assert analysis["reconciliation_mismatch_count"] == 0


def test_revision_event_aggregation_uses_53_primary_units(analysis: dict[str, Any]) -> None:
    assert len(analysis["event_rows"]) == 53
    assert {row["revision_event_id"] for row in analysis["event_rows"]} == {
        row["revision_event_id"] for row in analysis["pair_rows"]
    }


def test_stage7d_v1_null_result_is_diagnosed(analysis: dict[str, Any]) -> None:
    diagnostic = analysis["v1_diagnostic"]
    assert diagnostic["benchmark_task_count"] == 48
    assert diagnostic["task_cell_binding_count"] == 201
    assert diagnostic["exact_differs_final_binding_count"] == 0
    assert diagnostic["true_pre_revision_exposure_count"] == 0


def test_case_selection_is_deterministic(analysis: dict[str, Any]) -> None:
    selected = _select_cases(analysis["event_rows"])
    assert selected == _select_cases(list(reversed(analysis["event_rows"])))
    assert [row["case_label"] for row in selected] == ["A", "B", "C"]
    assert len({row["revision_event_id"] for row in selected}) == 3


def test_audit_zip_contains_all_detailed_csvs(analysis: dict[str, Any]) -> None:
    assert analysis["reconciliation_mismatch_count"] == 0
    zip_path = _write_audit_zip(REPO_ROOT, ARTIFACT_DIR)
    required = {
        "stage7d_revision_pairs.csv",
        "stage7d_revision_evidence_delta.csv",
        "stage7d_revision_metric_pairs.csv",
        "stage7d_revision_claim_transition_rows.csv",
        "stage7d_revision_event_summary.csv",
        "stage7d_stage5c_revision_reconciliation_audit.csv",
        "mechanical_response_revision_independence_audit.csv",
    }
    with zipfile.ZipFile(zip_path) as archive:
        names = {Path(name).name for name in archive.namelist()}
    assert required <= names


def test_rebuild_is_deterministic_and_uses_no_api_or_llm(
    inputs: dict[str, Any], analysis: dict[str, Any]
) -> None:
    assert stable_hash(analysis) == stable_hash(_analyze(inputs))
    protocol = _protocol(inputs)
    assert protocol["api_calls"] == protocol["llm_calls"] == 0
