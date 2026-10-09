"""Tests for the non-destructive Stage7 200-task supplemental benchmark."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from tbm_twin.evaluation.stage7_supplemental import (
    build_supplemental_protocol,
    run_supplemental_execution,
    upstream_gold_readiness,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_supplemental_protocol_preserves_main_and_adds_balanced_tasks(tmp_path: Path) -> None:
    output = build_supplemental_protocol(REPO_ROOT, tmp_path / "protocol")
    additional = json.loads((output / "additional_benchmark_manifest.json").read_text())
    combined = json.loads((output / "combined_200_benchmark_manifest.json").read_text())
    assert len(additional["tasks"]) == 152
    assert len(combined["tasks"]) == 200
    assert Counter(row["product_type"] for row in additional["tasks"]) == {
        "all": 38,
        "daily_review": 38,
        "forward_attention": 38,
        "metric_review": 38,
    }
    assert Counter(row["product_type"] for row in combined["tasks"]) == {
        "all": 50,
        "daily_review": 50,
        "forward_attention": 50,
        "metric_review": 50,
    }
    frozen = json.loads(
        (
            REPO_ROOT
            / "artifacts/stage7a_experimental_protocol_v1_3/stage7_main_benchmark_manifest.json"
        ).read_text()
    )["tasks"]
    assert combined["tasks"][:48] == frozen


def test_supplemental_dry_run_has_456_items_and_no_api_calls(tmp_path: Path) -> None:
    protocol = build_supplemental_protocol(REPO_ROOT, tmp_path / "protocol")
    result = run_supplemental_execution(
        REPO_ROOT,
        provider="deepseek",
        model="deepseek-v4-flash",
        execute=False,
        protocol_dir=protocol,
        output_root=tmp_path / "execution",
    )
    assert result["status"] == "DRY_RUN_PASS"
    assert result["execution_manifest_item_count"] == 456
    assert result["real_api_request_attempt_count"] == 0


def test_upstream_gold_readiness_does_not_invent_labels(tmp_path: Path) -> None:
    result = upstream_gold_readiness(REPO_ROOT, tmp_path)
    assert result["plc_sample_count"] == 60
    assert result["geology_sample_count"] == 60
    assert result["status"] == "BLOCKED_PENDING_HUMAN_ANNOTATION"
    assert result["accuracy_metrics_generated"] is False
