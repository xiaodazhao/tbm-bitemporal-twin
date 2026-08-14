"""Regression tests for Stage7A.1 pre-Claim protocol construction."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from tbm_twin.evaluation.stage7a import _future_leakage_audit, build_stage7a_protocol
from tbm_twin.realization.io import canonical_json, stable_hash

REPO_ROOT = Path(__file__).resolve().parents[2]


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_stage7a1_preserves_v1_benchmark_and_smoke_exclusion(tmp_path: Path) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a1")

    v1 = _json(
        REPO_ROOT / "artifacts/stage7a_experimental_protocol_v1/stage7_main_benchmark_manifest.json"
    )
    manifest = _json(out / "stage7_main_benchmark_manifest.json")
    overlap_rows = {
        row["source_task_id"]: row for row in _rows(out / "stage7_smoke_overlap_audit.csv")
    }
    hard_rows = _rows(out / "stage7a1_hard_check.csv")

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
    for row in manifest["tasks"]:
        audit = overlap_rows[row["source_task_id"]]
        assert audit["shared_factlock_count"] == "0"
        assert audit["shared_realization_unit_count"] == "0"
    assert {row["status"] for row in hard_rows} == {"PASS"}


def test_stage7a1_manifest_hash_and_product_quotas(tmp_path: Path) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a1")

    manifest = _json(out / "stage7_main_benchmark_manifest.json")
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

    assert manifest["actual_size"] == 48
    assert manifest["stage7_main_manifest_hash"] == expected_hash


def test_stage7a1_preclaim_snapshot_has_no_downstream_sources(tmp_path: Path) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a1")

    snapshots = _jsonl(out / "stage7_preclaim_benchmark_evidence_snapshots.jsonl")
    leakage_rows = _rows(out / "stage7_baseline_claim_layer_leakage_audit.csv")
    payloads = _jsonl(out / "stage7_b0_input_payloads.jsonl")
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
    for snapshot in snapshots:
        assert snapshot["snapshot_source"] == "STAGE3B_STAGE4_PRE_CLAIM_STATE"
        assert snapshot["preclaim_evidence_items"]
        assert all(
            item["source_object"] not in {"Stage6A FactLock", "Stage6B RealizationUnit"}
            for item in snapshot["preclaim_evidence_items"]
        )
    payload_text = canonical_json(payloads)
    assert all(token not in payload_text for token in forbidden)


def test_stage7a1_preserves_actual_availability_and_detects_future_injection(
    tmp_path: Path,
) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a1")

    future_rows = _rows(out / "stage7_snapshot_future_leakage_audit.csv")
    snapshots = _jsonl(out / "stage7_preclaim_benchmark_evidence_snapshots.jsonl")
    injected = json.loads(json.dumps(snapshots[0]))
    injected["preclaim_evidence_items"][0]["actual_available_time"] = "2999-01-01"

    assert {row["is_future"] for row in future_rows} == {"false"}
    assert all(row["actual_available_time"] for row in future_rows)
    assert all(row["source_field"] for row in future_rows)
    injected_audit = _future_leakage_audit([injected])
    assert any(row["is_future"] == "true" for row in injected_audit)


def test_stage7a1_revision_knowledge_binding_is_explicit(tmp_path: Path) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a1")

    rows = _rows(out / "stage7_revision_knowledge_binding_audit.csv")

    assert rows
    assert {row["status"] for row in rows} == {"PASS"}
    assert "false" in {row["valid_time_collapsed_to_knowledge_time"] for row in rows}
    assert all(row["state_version_id"] for row in rows)
    assert all(row["revision_chain_id"] for row in rows)


def test_stage7a1_abstain_context_remains_visible(tmp_path: Path) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a1")
    rows = _rows(out / "stage7_abstain_context_visibility_audit.csv")

    abstain_rows = [row for row in rows if int(row["abstain_count"]) > 0]
    assert abstain_rows
    assert {row["status"] for row in rows} == {"PASS"}
    assert {row["abstain_related_upstream_context_present_in_b0"] for row in rows} == {"true"}
    assert {row["abstain_related_upstream_context_present_in_b1"] for row in rows} == {"true"}


def test_stage7a1_b0_b1_inputs_and_product_contracts_are_equivalent(
    tmp_path: Path,
) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a1")

    audit_rows = _rows(out / "stage7_b0_b1_equivalence_audit.csv")
    b0_payloads = _jsonl(out / "stage7_b0_input_payloads.jsonl")
    b1_payloads = _jsonl(out / "stage7_b1_input_payloads.jsonl")

    assert {row["status"] for row in audit_rows} == {"PASS"}
    assert {row["b0_b1_evidence_difference_count"] for row in audit_rows} == {"0"}
    assert {row["b0_b1_product_contract_difference_count"] for row in audit_rows} == {"0"}
    for b0, b1 in zip(b0_payloads, b1_payloads, strict=True):
        assert b0["structured_evidence"] == b1["structured_evidence"]
        assert b0["product_task_contract"] == b1["product_task_contract"]
        assert b0["method_id"] != b1["method_id"]


def test_stage7a1_proposed_has_no_extra_source_evidence(tmp_path: Path) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a1")
    rows = _rows(out / "stage7_three_method_source_equivalence_audit.csv")

    assert {row["status"] for row in rows} == {"PASS"}
    assert {row["proposed_future_source_advantage_count"] for row in rows} == {"0"}
    assert {row["baseline_source_information_loss_count"] for row in rows} == {"0"}


def test_stage7a1_gold_and_blind_protocols_remain_valid(tmp_path: Path) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a1")
    gold_rows = _rows(out / "stage7_claim_gold_sampling_plan.csv")
    blind_rows = _rows(out / "stage7_text_evaluation_blind_manifest.csv")
    internal_rows = _rows(out / "stage7_text_evaluation_internal_mapping.csv")

    forbidden = ["B0_", "B1_", "P_PROPOSED", "DIRECT_LLM", "STRUCTURED_PROMPT"]
    blind_text = json.dumps(blind_rows, ensure_ascii=False)
    assert sum(int(row["allocated"]) for row in gold_rows) == 600
    assert all(int(row["allocated"]) <= int(row["available"]) for row in gold_rows)
    assert {"EXPRESSIBLE", "ABSTAIN"} <= {row["decision_class"] for row in gold_rows}
    assert all(token not in blind_text for token in forbidden)
    assert len(blind_rows) == len(internal_rows) == 48 * 3
    assert "true_method_identity" not in blind_rows[0]
    assert "true_method_identity" in internal_rows[0]
