"""Regression tests for Stage7A protocol and held-out benchmark construction."""

from __future__ import annotations

import csv
import json
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


def test_stage7a_excludes_stage6b_smoke_tasks(tmp_path: Path) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a")

    exclusion = _json(out / "stage7_exclusion_manifest.json")
    excluded_ids = {row["task_id"] for row in exclusion["excluded_tasks"]}
    main_rows = _rows(out / "stage7_main_benchmark_manifest.csv")
    source_ids = {row["source_task_id"] for row in main_rows}

    assert len(excluded_ids) == 15
    assert not (source_ids & excluded_ids)
    assert _json(out / "method_version.json")["real_api_call_count"] == 0


def test_stage7a_main_manifest_hash_and_hard_checks(tmp_path: Path) -> None:
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
            }
            for row in manifest["tasks"]
        ]
    )
    hard_rows = _rows(out / "stage7a_hard_check.csv")

    assert manifest["actual_size"] == 48
    assert manifest["stage7_main_manifest_hash"] == expected_hash
    assert {row["status"] for row in hard_rows} == {"PASS"}


def test_stage7a_benchmark_has_required_strata(tmp_path: Path) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a")
    rows = _rows(out / "stage7_main_benchmark_manifest.csv")

    assert {row["product_type"] for row in rows} >= {
        "daily_review",
        "forward_attention",
        "metric_review",
        "all",
    }
    assert {row["unit_complexity_band"] for row in rows} >= {"LOW", "MEDIUM", "HIGH"}
    assert "REVISION_RELATED" in {row["revision_status"] for row in rows}
    assert "MIXED" in {row["epistemic_mix"] for row in rows}


def test_stage7a_gold_plan_does_not_expose_annotation_labels(tmp_path: Path) -> None:
    out = build_stage7a_protocol(REPO_ROOT, tmp_path / "stage7a")
    rows = _rows(out / "stage7_claim_gold_sampling_plan.csv")

    forbidden = {
        "expressibility_hidden_from_annotator",
        "abstention_reason_hidden_from_annotator",
    }
    assert rows
    assert not (set(rows[0]) & forbidden)
    assert {row["system_label_hidden_from_annotation_packet"] for row in rows} == {"true"}
