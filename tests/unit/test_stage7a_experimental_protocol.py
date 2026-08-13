"""Regression tests for Stage7A protocol and held-out benchmark construction."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from tbm_twin.evaluation.stage7a import build_stage7a_protocol
from tbm_twin.realization.io import stable_hash

REPO_ROOT = Path(__file__).resolve().parents[2]


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_stage7a_excludes_stage6b_smoke_factlocks_and_units(tmp_path: Path) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a")

    overlap_rows = {
        row["source_task_id"]: row for row in _rows(out / "stage7_smoke_overlap_audit.csv")
    }
    main_rows = _rows(out / "stage7_main_benchmark_manifest.csv")
    hard_rows = _rows(out / "stage7a_hard_check.csv")

    assert _json(out / "method_version.json")["real_api_call_count"] == 0
    assert len(_json(out / "stage7_smoke_exposure_manifest.json")["tasks"]) == 15
    for row in main_rows:
        audit = overlap_rows[row["source_task_id"]]
        assert audit["shared_factlock_count"] == "0"
        assert audit["shared_realization_unit_count"] == "0"
    assert {
        row["status"] for row in hard_rows if row["check_name"].startswith("stage6b_smoke_")
    } == {"PASS"}


def test_stage7a_main_manifest_hash_and_product_quotas(tmp_path: Path) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a")

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
    rows = _rows(out / "stage7_main_benchmark_manifest.csv")

    assert manifest["actual_size"] == 48
    assert manifest["stage7_main_manifest_hash"] == expected_hash
    assert Counter(row["product_type"] for row in rows) == {
        "all": 12,
        "daily_review": 12,
        "forward_attention": 12,
        "metric_review": 12,
    }


def test_stage7a_knowledge_time_and_snapshot_binding(tmp_path: Path) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a")

    benchmark_rows = _rows(out / "stage7_main_benchmark_manifest.csv")
    snapshots = _jsonl(out / "stage7_benchmark_evidence_snapshots.jsonl")
    snapshot_audit = _rows(out / "stage7_snapshot_audit.csv")

    assert len(snapshots) == 48
    assert {row["future_evidence_count"] for row in snapshot_audit} == {"0"}
    assert {row["b0_snapshot_match"] for row in snapshot_audit} == {"true"}
    assert {row["b1_snapshot_match"] for row in snapshot_audit} == {"true"}
    for row in benchmark_rows:
        assert row["knowledge_time_local_date"]
        assert row["knowledge_time_basis"] != "VALID_DATE_FALLBACK"
        assert row["state_version_ids"] != "[]"
        assert row["stage3b_bitemporal_version_ids"] != "[]"
    for snapshot in snapshots:
        assert snapshot["excluded_from_baseline_snapshot"]
        assert all("fact_lock_id" not in item for item in snapshot["evidence_items"])


def test_stage7a_b0_b1_inputs_are_evidence_equivalent(tmp_path: Path) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a")

    audit_rows = _rows(out / "stage7_baseline_information_equivalence_audit.csv")
    b0_payloads = _jsonl(out / "stage7_b0_input_payloads.jsonl")
    b1_payloads = _jsonl(out / "stage7_b1_input_payloads.jsonl")

    assert {row["status"] for row in audit_rows} == {"PASS"}
    assert {row["b0_b1_evidence_difference_count"] for row in audit_rows} == {"0"}
    for b0, b1 in zip(b0_payloads, b1_payloads, strict=True):
        assert b0["structured_evidence"] == b1["structured_evidence"]
        assert b0["method_id"] != b1["method_id"]


def test_stage7a_gold_plan_redistributes_without_overallocation(tmp_path: Path) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a")
    rows = _rows(out / "stage7_claim_gold_sampling_plan.csv")

    assert sum(int(row["allocated"]) for row in rows) == 600
    assert all(int(row["allocated"]) <= int(row["available"]) for row in rows)
    assert {row["system_label_hidden_from_annotation_packet"] for row in rows} == {"true"}
    assert {"EXPRESSIBLE", "ABSTAIN"} <= {row["decision_class"] for row in rows}


def test_stage7a_blind_manifest_masks_method_identity(tmp_path: Path) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a")
    blind_rows = _rows(out / "stage7_text_evaluation_blind_manifest.csv")
    internal_rows = _rows(out / "stage7_text_evaluation_internal_mapping.csv")

    forbidden = ["B0_", "B1_", "P_PROPOSED", "DIRECT_LLM", "STRUCTURED_PROMPT"]
    blind_text = json.dumps(blind_rows, ensure_ascii=False)
    assert all(token not in blind_text for token in forbidden)
    assert len(blind_rows) == len(internal_rows) == 48 * 3
    assert "true_method_identity" not in blind_rows[0]
    assert "true_method_identity" in internal_rows[0]
