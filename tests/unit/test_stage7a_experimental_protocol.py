"""Regression tests for Stage7A.3 exact as-of protocol construction."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from tbm_twin.evaluation.stage7a import (
    _abstain_context_completeness_audit,
    _future_leakage_audit,
    _load_preclaim_sources,
    _load_v1_benchmark_rows,
    _source_identity_mapping,
    _three_method_source_equivalence_audit,
    build_stage7a_protocol,
)
from tbm_twin.realization.io import canonical_json, read_jsonl, stable_hash

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def stage7a3_out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_stage7a_protocol(REPO_ROOT, tmp_path_factory.mktemp("stage7a3"))


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_stage7a3_preserves_48_task_selection_and_product_quotas(
    stage7a3_out: Path,
) -> None:
    v1 = _json(REPO_ROOT / "configs/frozen_inputs/stage7a_v1_main_benchmark_manifest.json")
    manifest = _json(stage7a3_out / "stage7_main_benchmark_manifest.json")
    hard_rows = _rows(stage7a3_out / "stage7a3_hard_check.csv")

    assert [row["benchmark_task_id"] for row in manifest["tasks"]] == [
        row["benchmark_task_id"] for row in v1["tasks"]
    ]
    assert manifest["actual_size"] == 48
    assert Counter(row["product_type"] for row in manifest["tasks"]) == {
        "all": 12,
        "daily_review": 12,
        "forward_attention": 12,
        "metric_review": 12,
    }
    assert {row["status"] for row in hard_rows} == {"PASS"}


def test_stage7a3_manifest_hash_remains_selection_identity(stage7a3_out: Path) -> None:
    manifest = _json(stage7a3_out / "stage7_main_benchmark_manifest.json")
    expected_hash = stable_hash(
        [
            {
                "benchmark_task_id": row["benchmark_task_id"],
                "source_task_id": row["source_task_id"],
                "slice_spec": row["slice_spec"],
                "pack_id": row["pack_id"],
                "pack_hash": row["pack_hash"],
                "snapshot_binding": {
                    "valid_time": row["valid_time"],
                    "knowledge_time_local_date": row["knowledge_time_local_date"],
                    "state_version_ids": row["state_version_ids"],
                    "bitemporal_version_ids": row["stage3b_bitemporal_version_ids"],
                },
            }
            for row in manifest["tasks"]
        ]
    )
    method = _json(stage7a3_out / "method_version.json")

    assert manifest["actual_size"] == 48
    assert manifest["stage7_main_manifest_hash"] == expected_hash
    assert method["main_benchmark_manifest_hash"] == expected_hash
    assert method["asof_evaluation_binding_manifest_hash"]


def test_stage7a3_reproduces_pre_correction_superseded_exposure(
    stage7a3_out: Path,
) -> None:
    rows = _rows(stage7a3_out / "stage7_asof_pre_correction_audit.csv")
    exposed = [row for row in rows if row["status"] == "SUPERSEDED_EXPOSED"]

    assert exposed
    assert len({row["task_id"] for row in exposed}) == 22
    assert sum(len(row["superseded_version_ids"].split(";")) for row in exposed) == 37
    assert {row["multiple_versions_for_same_cell"] for row in exposed} == {"true"}


def test_stage7a3_active_state_scope_uses_half_open_asof_interval(
    stage7a3_out: Path,
) -> None:
    sources = _load_preclaim_sources(REPO_ROOT)
    query = sources["asof_query"]
    pre_rows = _rows(stage7a3_out / "stage7_asof_pre_correction_audit.csv")
    boundary_case = next(
        row
        for row in pre_rows
        if row["status"] == "SUPERSEDED_EXPOSED"
        and any(
            sources["stage3b_versions_by_bitemporal"][version_id]["knowledge_time_end_local_date"]
            == row["knowledge_boundary"]
            for version_id in row["superseded_version_ids"].split(";")
        )
    )

    selected = query.get_state_as_known(
        boundary_case["valid_date"],
        boundary_case["cell_id"],
        boundary_case["knowledge_boundary"],
    )

    assert selected is not None
    assert selected["bitemporal_version_id"] == boundary_case["active_asof_version_id"]
    assert selected["bitemporal_version_id"] not in boundary_case["superseded_version_ids"].split(
        ";"
    )


def test_stage7a3_one_active_version_per_cell_and_no_superseded_snapshot(
    stage7a3_out: Path,
) -> None:
    state_rows = _rows(stage7a3_out / "stage7_task_preclaim_state_universe_audit.csv")
    exposure_rows = _rows(stage7a3_out / "stage7_asof_state_exposure_audit.csv")

    assert {row["selection_basis"] for row in state_rows} == {
        "SLICE_SPEC_AND_FROZEN_STATE_SCOPE_PLUS_ASOF_KNOWLEDGE_INTERVAL"
    }
    assert {row["factlock_dependency"] for row in state_rows} == {"false"}
    assert {row["multiple_active_version_count"] for row in state_rows} == {"0"}
    assert {row["missing_state_version_count"] for row in state_rows} == {"0"}
    assert {row["unexpected_state_version_count"] for row in state_rows} == {"0"}
    assert {row["duplicate_cell_version_count"] for row in exposure_rows} == {"0"}
    assert {row["superseded_state_count_in_snapshot"] for row in exposure_rows} == {"0"}
    assert {row["status"] for row in exposure_rows} == {"PASS"}


def test_stage7a3_stage4_metrics_bind_only_active_versions(stage7a3_out: Path) -> None:
    rows = _rows(stage7a3_out / "stage7_asof_metric_binding_audit.csv")

    assert rows
    assert {row["status"] for row in rows} == {"PASS"}
    assert {row["superseded_metric_count"] for row in rows} == {"0"}
    assert all(row["active_bitemporal_version_id"] for row in rows)
    assert all(row["task_knowledge_boundary"] for row in rows)


def test_stage7a3_snapshot_has_preclaim_metrics_and_no_downstream_sources(
    stage7a3_out: Path,
) -> None:
    snapshots = _jsonl(stage7a3_out / "stage7_preclaim_benchmark_evidence_snapshots.jsonl")
    leakage_rows = _rows(stage7a3_out / "stage7_baseline_claim_layer_leakage_audit.csv")
    payloads = _jsonl(stage7a3_out / "stage7_b0_input_payloads.jsonl")
    items = [item for snapshot in snapshots for item in snapshot["preclaim_evidence_items"]]
    metric_items = [item for item in items if item["evidence_family"] == "STAGE4_ATTENTION_METRIC"]
    forbidden = [
        "fact_lock_",
        "realization_unit_",
        "typed_claim_",
        "claim_decision_",
        "claim_opportunity_",
        "EXPRESSIBLE",
        "ABSTAIN",
        "OPERATIONAL_RESPONSE_ATTENTION",
        "OBSERVED_GEOLOGICAL_CONDITION",
        "FORECAST_GEOLOGICAL_CONDITION",
        "COUPLED_ATTENTION_REVIEW",
    ]

    assert len(snapshots) == 48
    assert {row["status"] for row in leakage_rows} == {"PASS"}
    assert metric_items
    for snapshot in snapshots:
        assert snapshot["snapshot_source"] == "STAGE3B_STAGE4_PRE_CLAIM_STATE"
        assert snapshot["preclaim_evidence_items"]
        assert all(
            item["source_object"] not in {"Stage6A FactLock", "Stage6B RealizationUnit"}
            for item in snapshot["preclaim_evidence_items"]
        )
    payload_text = canonical_json(payloads)
    assert all(token not in payload_text for token in forbidden)


def test_stage7a3_proposed_bundle_filters_factlocks_and_abstentions_to_asof(
    stage7a3_out: Path,
) -> None:
    rows = _rows(stage7a3_out / "stage7_asof_evaluation_binding_manifest.csv")
    proposed_refs = _jsonl(stage7a3_out / "stage7_proposed_preclaim_reference.jsonl")

    assert len(rows) == 48
    assert {row["status"] for row in rows} == {"PASS"}
    assert {row["proposed_non_asof_factlock_count"] for row in rows} == {"0"}
    assert {row["proposed_non_asof_abstention_count"] for row in rows} == {"0"}
    assert all(row["asof_pack_id"] for row in rows)
    assert all(row["asof_realization_unit_ids"] for row in rows)
    assert {row["source_reconstruction_basis"] for row in proposed_refs} == {
        "STAGE7_ASOF_FILTERED_STAGE6B_BUNDLE_PROVENANCE"
    }


def test_stage7a3_active_abstain_context_completeness(stage7a3_out: Path) -> None:
    summary = _json(stage7a3_out / "stage7_asof_abstain_context_summary.json")
    rows = _rows(stage7a3_out / "stage7_asof_abstain_context_completeness_audit.csv")
    binding_rows = _rows(stage7a3_out / "stage7_asof_evaluation_binding_manifest.csv")

    assert len(rows) == sum(int(row["active_abstain_count"]) for row in binding_rows)
    assert len(rows) < 386
    assert summary["total_abstain_opportunities"] == len(rows)
    assert summary["unaccounted_abstain_context_count"] == 0
    assert {row["status"] for row in rows} == {"PASS"}
    assert {
        "CONTEXT_ONLY_ROLE",
        "REQUIRED_EPISTEMIC_STATUS_MISSING",
        "REQUIRED_METRIC_UNAVAILABLE",
        "STATE_ROLE_NOT_ALLOWED",
        "UNKNOWN_SOURCE_VALUE",
    } <= {row["abstention_reason"] for row in rows}


def test_stage7a3_abstain_audit_detects_removed_active_context(stage7a3_out: Path) -> None:
    snapshots = _jsonl(stage7a3_out / "stage7_preclaim_benchmark_evidence_snapshots.jsonl")
    sources = _load_preclaim_sources(REPO_ROOT)
    benchmark_rows = _load_v1_benchmark_rows(REPO_ROOT)
    audit_rows = _rows(stage7a3_out / "stage7_asof_abstain_context_completeness_audit.csv")
    binding_rows = _rows(stage7a3_out / "stage7_asof_evaluation_binding_manifest.csv")
    active_ids = {
        row["benchmark_task_id"]: set(row["asof_abstention_ids"].split(";"))
        if row["asof_abstention_ids"]
        else set()
        for row in binding_rows
    }
    target = next(row for row in audit_rows if row["snapshot_support_ids_found"])
    mutated = json.loads(json.dumps(snapshots))
    snapshot = next(row for row in mutated if row["benchmark_task_id"] == target["task_id"])
    removed_id = target["snapshot_support_ids_found"].split(";")[0]
    snapshot["preclaim_evidence_items"] = [
        item for item in snapshot["preclaim_evidence_items"] if item["evidence_id"] != removed_id
    ]

    rows, summary = _abstain_context_completeness_audit(
        {},
        benchmark_rows,
        mutated,
        sources,
        active_abstention_ids_by_task=active_ids,
    )

    assert summary["unaccounted_abstain_context_count"] > 0
    assert any(row["status"] == "FAIL" for row in rows if row["task_id"] == target["task_id"])


def test_stage7a3_preserves_availability_and_detects_future_injection(
    stage7a3_out: Path,
) -> None:
    future_rows = _rows(stage7a3_out / "stage7_asof_future_leakage_audit.csv")
    snapshots = _jsonl(stage7a3_out / "stage7_preclaim_benchmark_evidence_snapshots.jsonl")
    injected = json.loads(json.dumps(snapshots[0]))
    injected["preclaim_evidence_items"][0]["actual_available_time"] = "2999-01-01"

    assert {row["is_future"] for row in future_rows} == {"false"}
    assert all(row["actual_available_time"] for row in future_rows)
    assert all(row["source_field"] for row in future_rows)
    injected_audit = _future_leakage_audit([injected])
    assert any(row["is_future"] == "true" for row in injected_audit)


def test_stage7a3_asof_source_equivalence_is_reconstructed_independently(
    stage7a3_out: Path,
) -> None:
    rows = _rows(stage7a3_out / "stage7_asof_three_method_source_equivalence_audit.csv")
    proposed_refs = _jsonl(stage7a3_out / "stage7_proposed_preclaim_reference.jsonl")

    assert {row["status"] for row in rows} == {"PASS"}
    assert {row["proposed_actual_source_not_in_baseline_count"] for row in rows} == {"0"}
    assert {row["proposed_future_source_advantage_count"] for row in rows} == {"0"}
    assert {row["source_identity_unresolved_count"] for row in rows} == {"0"}
    assert {row["three_method_source_audit_tautology_count"] for row in rows} == {"0"}
    assert {row["baseline_authoritative_source_loss_count"] for row in rows} == {"0"}
    assert all("preclaim_source_evidence_ids" not in row for row in proposed_refs)


def test_stage7a3_proposed_only_source_is_detected(stage7a3_out: Path) -> None:
    snapshots = _jsonl(stage7a3_out / "stage7_preclaim_benchmark_evidence_snapshots.jsonl")
    proposed_refs = _jsonl(stage7a3_out / "stage7_proposed_preclaim_reference.jsonl")
    mutated = json.loads(json.dumps(proposed_refs))
    mutated[0]["proposed_actual_authoritative_source_ids"].append("doc_injected_future_source")

    mapping = _source_identity_mapping(snapshots, mutated)
    rows = _three_method_source_equivalence_audit(snapshots, mutated, mapping)

    assert any(row["status"] == "FAIL" for row in rows)
    assert any(int(row["proposed_actual_source_not_in_baseline_count"]) > 0 for row in rows)


def test_stage7a3_source_equivalence_cannot_pass_by_copying_baseline_ids(
    stage7a3_out: Path,
) -> None:
    snapshots = _jsonl(stage7a3_out / "stage7_preclaim_benchmark_evidence_snapshots.jsonl")
    proposed_refs = _jsonl(stage7a3_out / "stage7_proposed_preclaim_reference.jsonl")
    mutated = json.loads(json.dumps(proposed_refs))
    baseline_ids = {
        snapshot["benchmark_task_id"]: sorted(
            {item["evidence_id"] for item in snapshot["preclaim_evidence_items"]}
        )
        for snapshot in snapshots
    }
    for ref in mutated:
        ref["source_reconstruction_basis"] = "COPIED_FROM_BASELINE_SNAPSHOT"
        ref["proposed_actual_authoritative_source_ids"] = baseline_ids[ref["benchmark_task_id"]]

    mapping = _source_identity_mapping(snapshots, mutated)
    rows = _three_method_source_equivalence_audit(snapshots, mutated, mapping)

    assert any(row["status"] == "FAIL" for row in rows)
    assert {row["three_method_source_audit_tautology_count"] for row in rows} == {1}


def test_stage7a3_b0_b1_inputs_and_product_contracts_are_equivalent(
    stage7a3_out: Path,
) -> None:
    audit_rows = _rows(stage7a3_out / "stage7_b0_b1_equivalence_audit.csv")
    b0_payloads = _jsonl(stage7a3_out / "stage7_b0_input_payloads.jsonl")
    b1_payloads = _jsonl(stage7a3_out / "stage7_b1_input_payloads.jsonl")

    assert {row["status"] for row in audit_rows} == {"PASS"}
    assert {row["b0_b1_evidence_difference_count"] for row in audit_rows} == {"0"}
    assert {row["b0_b1_product_contract_difference_count"] for row in audit_rows} == {"0"}
    for b0, b1 in zip(b0_payloads, b1_payloads, strict=True):
        assert b0["structured_evidence"] == b1["structured_evidence"]
        assert b0["product_task_contract"] == b1["product_task_contract"]
        assert b0["method_id"] != b1["method_id"]


def test_stage7a3_gold_and_blind_protocols_remain_valid(stage7a3_out: Path) -> None:
    gold_rows = _rows(stage7a3_out / "stage7_claim_gold_sampling_plan.csv")
    blind_rows = _rows(stage7a3_out / "stage7_text_evaluation_blind_manifest.csv")
    internal_rows = _rows(stage7a3_out / "stage7_text_evaluation_internal_mapping.csv")

    forbidden = ["B0_", "B1_", "P_PROPOSED", "DIRECT_LLM", "STRUCTURED_PROMPT"]
    blind_text = json.dumps(blind_rows, ensure_ascii=False)
    assert sum(int(row["allocated"]) for row in gold_rows) == 600
    assert all(int(row["allocated"]) <= int(row["available"]) for row in gold_rows)
    assert {"EXPRESSIBLE", "ABSTAIN"} <= {row["decision_class"] for row in gold_rows}
    assert all(token not in blind_text for token in forbidden)
    assert len(blind_rows) == len(internal_rows) == 48 * 3
    assert "true_method_identity" not in blind_rows[0]
    assert "true_method_identity" in internal_rows[0]


def test_stage7a3_generated_artifact_contains_complete_required_files(
    stage7a3_out: Path,
) -> None:
    required = {
        "stage7_main_benchmark_manifest.json",
        "stage7_main_benchmark_manifest.csv",
        "stage7_asof_evaluation_binding_manifest.json",
        "stage7_asof_evaluation_binding_manifest.csv",
        "stage7_asof_pre_correction_audit.csv",
        "stage7_asof_state_exposure_audit.csv",
        "stage7_asof_metric_binding_audit.csv",
        "stage7_preclaim_benchmark_evidence_snapshots.jsonl",
        "stage7_b0_input_payloads.jsonl",
        "stage7_b1_input_payloads.jsonl",
        "stage7_asof_abstain_context_completeness_audit.csv",
        "stage7_asof_abstain_context_summary.json",
        "stage7_asof_three_method_source_equivalence_audit.csv",
        "stage7_asof_future_leakage_audit.csv",
        "stage7a3_hard_check.csv",
        "stage7a3_freeze_report.md",
        "method_version.json",
        "file_hashes.sha256",
    }
    existing = {path.name for path in stage7a3_out.iterdir() if path.is_file()}

    assert required <= existing
    assert (
        len(read_jsonl(stage7a3_out / "stage7_preclaim_benchmark_evidence_snapshots.jsonl")) == 48
    )
