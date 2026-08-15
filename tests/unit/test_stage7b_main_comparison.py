"""Regression tests for Stage7B main benchmark execution layer."""

from __future__ import annotations

import json
from pathlib import Path

from tbm_twin.evaluation.stage7b import (
    B0_METHOD,
    B1_METHOD,
    EXPECTED_STAGE7_MAIN_HASH,
    P_METHOD,
    build_execution_manifest,
    build_proposed_requests,
    execution_protocol,
    provider_config_public,
    run_stage7b,
)
from tbm_twin.realization.io import read_json, read_jsonl
from tbm_twin.realization.stage6b import load_stage6b_inputs

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE7A = REPO_ROOT / "artifacts/stage7a_experimental_protocol_v1_3"


def _by_task(path: Path) -> dict[str, dict[str, object]]:
    return {str(row["benchmark_task_id"]): row for row in read_jsonl(path)}


def _asof_by_task(path: Path) -> dict[str, dict[str, object]]:
    return {str(row["benchmark_task_id"]): row for row in read_json(path)["tasks"]}


def test_stage7b_execution_manifest_has_144_balanced_rotating_rows() -> None:
    tasks = read_json(STAGE7A / "stage7_main_benchmark_manifest.json")["tasks"]
    b0 = _by_task(STAGE7A / "stage7_b0_input_payloads.jsonl")
    b1 = _by_task(STAGE7A / "stage7_b1_input_payloads.jsonl")
    asof = _asof_by_task(STAGE7A / "stage7_asof_evaluation_binding_manifest.json")
    bundles, requests, audit_rows = build_proposed_requests(
        tasks, asof, load_stage6b_inputs(REPO_ROOT)
    )
    protocol = execution_protocol(provider_config_public("deepseek", "deepseek-v4-flash"))

    manifest = build_execution_manifest(tasks, b0, b1, requests, protocol)
    rows = manifest["items"]

    assert bundles
    assert {row["status"] for row in audit_rows} == {"PASS"}
    assert len(rows) == 144
    assert manifest["execution_manifest_hash"]
    assert [row["method_id"] for row in rows[:9]] == [
        B0_METHOD,
        B1_METHOD,
        P_METHOD,
        B1_METHOD,
        P_METHOD,
        B0_METHOD,
        P_METHOD,
        B0_METHOD,
        B1_METHOD,
    ]
    assert sum(row["method_id"] == B0_METHOD for row in rows) == 48
    assert sum(row["method_id"] == B1_METHOD for row in rows) == 48
    assert sum(row["method_id"] == P_METHOD for row in rows) == 48


def test_stage7b_dry_run_writes_manifest_without_api_attempts(tmp_path: Path) -> None:
    result = run_stage7b(
        REPO_ROOT,
        provider="deepseek",
        model="deepseek-v4-flash",
        execute=False,
        output_root=tmp_path / "stage7b",
    )
    manifest = json.loads((tmp_path / "stage7b" / "execution_manifest.json").read_text())
    summary = json.loads((tmp_path / "stage7b" / "run_summary.json").read_text())

    assert result["stage7b_status"] == "DRY_RUN_PASS"
    assert result["real_api_request_attempt_count"] == 0
    assert manifest["item_count"] == 144
    assert summary["execution_manifest_item_count"] == 144


def test_stage7b_preflight_uses_frozen_stage7a_hashes(tmp_path: Path) -> None:
    result = run_stage7b(
        REPO_ROOT,
        provider="deepseek",
        model="deepseek-v4-flash",
        execute=False,
        output_root=tmp_path / "stage7b",
    )
    protocol = json.loads((tmp_path / "stage7b" / "execution_protocol.json").read_text())

    assert result["benchmark_task_count"] == 48
    assert protocol["stage7_main_manifest_hash"] == EXPECTED_STAGE7_MAIN_HASH
    assert protocol["provider_config_public"]["provider"] == "deepseek"
    assert protocol["provider_config_public"]["model"] == "deepseek-v4-flash"
