"""Supplemental 200-task automatic benchmark built on frozen Stage7 artifacts.

The frozen 48-task benchmark remains the primary experiment. This module
selects 152 additional true-heldout tasks, executes only those additions, and
combines both runs for deterministic automatic evaluation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from tbm_twin.evaluation import stage7a, stage7b, stage7c
from tbm_twin.realization.io import (
    read_json,
    stable_hash,
    stable_id,
    write_csv,
    write_hashes,
    write_json,
    write_jsonl,
)
from tbm_twin.realization.providers.deepseek_adapter import (
    DEEPSEEK_RESPONSES_SUPPORTED_MODEL,
)
from tbm_twin.realization.stage6b import load_stage6b_inputs

METHOD_VERSION = "stage7_supplemental_automated_benchmark_v1"
SCHEMA_VERSION = "stage7_supplemental_automated_benchmark.v1"
PROTOCOL_DIR = Path("artifacts/stage7_supplemental_automated_benchmark_v1/protocol")
EXECUTION_DIR = Path("artifacts/stage7_supplemental_automated_benchmark_v1/execution")
EVALUATION_DIR = Path("artifacts/stage7_supplemental_automated_benchmark_v1/evaluation")
FROZEN_STAGE7A_DIR = Path("artifacts/stage7a_experimental_protocol_v1_3")
FROZEN_STAGE7B_RUN = Path(
    "artifacts/stage7b_main_comparison_v1/runs/stage7b_main_execution_3ae0f791811a2e711cb9f488"
)

MAIN_COUNT = 48
ADDITIONAL_COUNT = 152
COMBINED_COUNT = 200
PRODUCTS = ("all", "daily_review", "forward_attention", "metric_review")
MAIN_QUOTA = 12
ADDITIONAL_QUOTA = 38
COMBINED_QUOTA = 50


def _git_head(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _audit_row(name: str, passed: bool, details: object) -> dict[str, object]:
    return {
        "check_name": name,
        "status": "PASS" if passed else "FAIL",
        "details": details,
    }


def _write_loose_csv(path: Path, rows: object) -> None:
    write_csv(path, cast(list[dict[str, object]], rows))


def _status_fail_count(rows: list[dict[str, Any]]) -> int:
    return sum(str(row.get("status", "PASS")) != "PASS" for row in rows)


def _select_additional_tasks(
    true_heldout: list[dict[str, Any]], main_tasks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    main_source_ids = {str(row["source_task_id"]) for row in main_tasks}
    candidates = [row for row in true_heldout if str(row["source_task_id"]) not in main_source_ids]
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for product in PRODUCTS:
        product_rows = [row for row in candidates if row["product_type"] == product]
        selected.extend(stage7a._select_product_rows(product_rows, ADDITIONAL_QUOTA, selected_ids))
    result: list[dict[str, Any]] = []
    for index, row in enumerate(sorted(selected, key=stage7a._selection_sort_key), start=1):
        item = dict(row)
        item["benchmark_task_id"] = f"stage7_supplemental_task_{index:03d}"
        item["selection_reason"] = "deterministic_product_quota_true_heldout_supplemental_selection"
        result.append(item)
    return result


def build_supplemental_protocol(repo_root: Path, output_dir: Path | None = None) -> Path:
    """Freeze 152 additions and all inputs needed for the combined 200-task audit."""

    repo_root = repo_root.resolve()
    output = (output_dir or repo_root / PROTOCOL_DIR).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    frozen_stage7a = repo_root / FROZEN_STAGE7A_DIR
    main_manifest = read_json(frozen_stage7a / "stage7_main_benchmark_manifest.json")
    main_tasks = list(main_manifest["tasks"])

    frozen = stage7a._load_frozen_inputs(repo_root)
    smoke_tasks = frozen["smoke_tasks"]
    smoke_spec_keys = {stage7a._slice_key(row["slice_spec"]) for row in smoke_tasks}
    stage6b_inputs = load_stage6b_inputs(repo_root)
    original_universe = stage7a._build_eligible_universe(
        repo_root,
        stage6b_inputs,
        smoke_spec_keys,
        stage7a._stage3b_version_index(repo_root),
        stage7a._revision_bitemporal_versions(repo_root),
    )
    smoke_exposure = stage7a._build_smoke_exposure(stage6b_inputs, smoke_tasks)
    overlap_rows = stage7a._smoke_overlap_audit(original_universe, smoke_exposure)
    true_heldout = [
        row
        for row, audit in zip(original_universe, overlap_rows, strict=True)
        if audit["excluded_from_true_heldout"] == "false"
    ]
    additional_tasks = _select_additional_tasks(true_heldout, main_tasks)
    combined_tasks = main_tasks + additional_tasks

    sources = stage7a._load_preclaim_sources(repo_root)
    state_rows, state_universe = stage7a._task_preclaim_state_universe(combined_tasks, sources)
    state_exposure_rows = stage7a._asof_state_exposure_audit(
        combined_tasks, state_universe, sources
    )
    snapshots = stage7a._build_preclaim_snapshots(combined_tasks, sources, state_universe)
    snapshot_rows = stage7a._snapshot_audit(snapshots)
    future_rows = stage7a._future_leakage_audit(snapshots)
    metric_rows = stage7a._asof_metric_binding_audit(
        combined_tasks, state_universe, snapshots, sources
    )
    revision_rows = stage7a._revision_knowledge_binding_audit(snapshots)
    asof_bundles = stage7a._asof_task_bundles(stage6b_inputs, combined_tasks, state_universe)
    product_contracts = read_json(frozen_stage7a / "stage7_product_task_contracts.json")
    b0_payloads = stage7a._baseline_payloads(
        combined_tasks, snapshots, product_contracts, stage7b.B0_METHOD
    )
    b1_payloads = stage7a._baseline_payloads(
        combined_tasks, snapshots, product_contracts, stage7b.B1_METHOD
    )
    equivalence_rows = stage7a._baseline_equivalence_audit(b0_payloads, b1_payloads)
    asof_rows, asof_hash = stage7a._asof_evaluation_binding_manifest(
        combined_tasks, state_universe, asof_bundles, b0_payloads, b1_payloads
    )
    proposed_refs = stage7a._proposed_preclaim_reference(
        stage6b_inputs, combined_tasks, asof_bundles=asof_bundles
    )
    source_mapping = stage7a._source_identity_mapping(snapshots, proposed_refs)
    fairness_rows = stage7a._three_method_source_equivalence_audit(
        snapshots, proposed_refs, source_mapping
    )

    main_hash = stage7a._benchmark_hash(main_tasks)
    additional_hash = stage7a._benchmark_hash(additional_tasks)
    combined_hash = stage7a._benchmark_hash(combined_tasks)
    true_ids = {str(row["source_task_id"]) for row in true_heldout}
    main_ids = {str(row["source_task_id"]) for row in main_tasks}
    additional_ids = {str(row["source_task_id"]) for row in additional_tasks}
    hard_rows = [
        _audit_row(
            "original_eligible_count", len(original_universe) == 1416, len(original_universe)
        ),
        _audit_row("true_heldout_count", len(true_heldout) == 1282, len(true_heldout)),
        _audit_row("frozen_main_count", len(main_tasks) == MAIN_COUNT, len(main_tasks)),
        _audit_row(
            "frozen_main_hash_preserved",
            main_hash == main_manifest["stage7_main_manifest_hash"],
            main_hash,
        ),
        _audit_row(
            "additional_count", len(additional_tasks) == ADDITIONAL_COUNT, len(additional_tasks)
        ),
        _audit_row(
            "additional_product_quota",
            Counter(row["product_type"] for row in additional_tasks)
            == {product: ADDITIONAL_QUOTA for product in PRODUCTS},
            dict(Counter(row["product_type"] for row in additional_tasks)),
        ),
        _audit_row("combined_count", len(combined_tasks) == COMBINED_COUNT, len(combined_tasks)),
        _audit_row(
            "combined_product_quota",
            Counter(row["product_type"] for row in combined_tasks)
            == {product: COMBINED_QUOTA for product in PRODUCTS},
            dict(Counter(row["product_type"] for row in combined_tasks)),
        ),
        _audit_row(
            "main_additional_disjoint",
            not (main_ids & additional_ids),
            len(main_ids & additional_ids),
        ),
        _audit_row(
            "additional_true_heldout", additional_ids <= true_ids, len(additional_ids - true_ids)
        ),
        _audit_row(
            "combined_unique_source_tasks",
            len(main_ids | additional_ids) == COMBINED_COUNT,
            len(main_ids | additional_ids),
        ),
        _audit_row(
            "snapshot_audit",
            _status_fail_count(snapshot_rows) == 0,
            _status_fail_count(snapshot_rows),
        ),
        _audit_row(
            "future_leakage_audit",
            _status_fail_count(future_rows) == 0,
            _status_fail_count(future_rows),
        ),
        _audit_row(
            "metric_binding_audit",
            _status_fail_count(metric_rows) == 0,
            _status_fail_count(metric_rows),
        ),
        _audit_row(
            "baseline_equivalence",
            _status_fail_count(equivalence_rows) == 0,
            _status_fail_count(equivalence_rows),
        ),
        _audit_row(
            "three_method_source_equivalence",
            _status_fail_count(fairness_rows) == 0,
            _status_fail_count(fairness_rows),
        ),
    ]
    if any(row["status"] != "PASS" for row in hard_rows):
        failed = [row["check_name"] for row in hard_rows if row["status"] != "PASS"]
        raise RuntimeError(f"Supplemental protocol hard checks failed: {failed}")

    metadata = {
        "schema_version": SCHEMA_VERSION,
        "method_version": METHOD_VERSION,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "git_commit_hash": _git_head(repo_root),
        "frozen_main_task_count": MAIN_COUNT,
        "additional_task_count": ADDITIONAL_COUNT,
        "combined_task_count": COMBINED_COUNT,
        "frozen_main_manifest_hash": main_hash,
        "additional_manifest_hash": additional_hash,
        "combined_manifest_hash": combined_hash,
        "combined_asof_binding_hash": asof_hash,
        "selection_policy": "preserve_frozen_48_plus_38_per_product_from_remaining_true_heldout",
        "human_evaluation_scope": "FROZEN_MAIN_48_ONLY",
        "supplemental_evaluation_scope": "DETERMINISTIC_AUTOMATIC_ONLY",
    }
    write_json(
        output / "additional_benchmark_manifest.json",
        {**metadata, "tasks": additional_tasks},
    )
    write_csv(
        output / "additional_benchmark_manifest.csv",
        stage7a._flatten_benchmark(additional_tasks),
    )
    write_json(
        output / "combined_200_benchmark_manifest.json",
        {**metadata, "tasks": combined_tasks},
    )
    write_csv(
        output / "combined_200_benchmark_manifest.csv",
        stage7a._flatten_benchmark(combined_tasks),
    )
    write_jsonl(output / "stage7_preclaim_benchmark_evidence_snapshots.jsonl", snapshots)
    write_jsonl(output / "stage7_b0_input_payloads.jsonl", b0_payloads)
    write_jsonl(output / "stage7_b1_input_payloads.jsonl", b1_payloads)
    write_jsonl(output / "stage7_proposed_preclaim_reference.jsonl", proposed_refs)
    write_json(
        output / "stage7_asof_evaluation_binding_manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "method_version": METHOD_VERSION,
            "combined_manifest_hash": combined_hash,
            "stage7_asof_evaluation_binding_manifest_hash": asof_hash,
            "tasks": asof_rows,
        },
    )
    write_csv(output / "stage7_asof_evaluation_binding_manifest.csv", asof_rows)
    write_csv(output / "stage7_task_preclaim_state_universe_audit.csv", state_rows)
    write_csv(output / "stage7_asof_state_exposure_audit.csv", state_exposure_rows)
    write_csv(output / "stage7_snapshot_audit.csv", snapshot_rows)
    write_csv(output / "stage7_future_leakage_audit.csv", future_rows)
    write_csv(output / "stage7_metric_binding_audit.csv", metric_rows)
    write_csv(output / "stage7_revision_knowledge_binding_audit.csv", revision_rows)
    write_csv(output / "stage7_b0_b1_equivalence_audit.csv", equivalence_rows)
    write_csv(output / "stage7_source_identity_mapping.csv", source_mapping)
    write_csv(output / "stage7_three_method_source_equivalence_audit.csv", fairness_rows)
    write_csv(output / "protocol_hard_check.csv", hard_rows)
    _copy(
        frozen_stage7a / "stage7_b0_prompt_template_v1_1.txt",
        output / "stage7_b0_prompt_template_v1_1.txt",
    )
    _copy(
        frozen_stage7a / "stage7_b1_prompt_template_v1_1.txt",
        output / "stage7_b1_prompt_template_v1_1.txt",
    )
    for name in [
        "stage7_baseline_protocol.json",
        "stage7_product_task_contracts.json",
        "stage7_error_taxonomy.json",
        "stage7_metric_definitions.json",
    ]:
        _copy(frozen_stage7a / name, output / name)
    write_json(output / "method_version.json", metadata)
    write_json(output / "freeze_manifest.json", metadata)
    (output / "README.md").write_text(
        "\n".join(
            [
                "# Stage7 Supplemental 200-Task Automatic Benchmark",
                "",
                "The frozen 48-task main benchmark is unchanged.",
                "This protocol adds 152 disjoint true-heldout tasks (38 per product type).",
                "Only the additions are sent to the provider; combined evaluation uses 200 tasks.",
                "The additions receive deterministic automatic evaluation only, not human ratings.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    write_hashes(output)
    return output


def _supplemental_execution_protocol(
    protocol_metadata: dict[str, Any], provider_config: dict[str, Any]
) -> dict[str, Any]:
    payload = {
        "protocol_version": METHOD_VERSION,
        "additional_manifest_hash": protocol_metadata["additional_manifest_hash"],
        "combined_manifest_hash": protocol_metadata["combined_manifest_hash"],
        "combined_asof_binding_hash": protocol_metadata["combined_asof_binding_hash"],
        "frozen_main_manifest_hash": protocol_metadata["frozen_main_manifest_hash"],
        "provider_config_public": provider_config,
        "method_order_policy": {
            "task_index_mod_0": [stage7b.B0_METHOD, stage7b.B1_METHOD, stage7b.P_METHOD],
            "task_index_mod_1": [stage7b.B1_METHOD, stage7b.P_METHOD, stage7b.B0_METHOD],
            "task_index_mod_2": [stage7b.P_METHOD, stage7b.B0_METHOD, stage7b.B1_METHOD],
        },
        "retry_policy": {
            "max_retries": 0,
            "retry_on_transport_failure": False,
            "retry_on_parse_failure": False,
            "retry_on_validation_failure": False,
        },
        "baseline_output_policy": "preserve raw model text exactly",
        "proposed_output_policy": (
            "raw plan first, strict parse, deterministic validation, deterministic composition"
        ),
        "execution_scope": "ADDITIONAL_152_ONLY",
    }
    return {**payload, "execution_protocol_hash": stable_hash(payload)}


def run_supplemental_execution(
    repo_root: Path,
    *,
    provider: str,
    model: str,
    execute: bool,
    protocol_dir: Path | None = None,
    output_root: Path | None = None,
) -> dict[str, Any]:
    """Dry-run or execute exactly the 152 supplemental tasks."""

    repo_root = repo_root.resolve()
    protocol_path = (protocol_dir or repo_root / PROTOCOL_DIR).resolve()
    output = (output_root or repo_root / EXECUTION_DIR).resolve()
    output.mkdir(parents=True, exist_ok=True)
    metadata = read_json(protocol_path / "method_version.json")
    provider_config = stage7b.provider_config_public(provider, model)
    execution_protocol = _supplemental_execution_protocol(metadata, provider_config)
    additional = read_json(protocol_path / "additional_benchmark_manifest.json")["tasks"]
    combined = read_json(protocol_path / "combined_200_benchmark_manifest.json")["tasks"]
    asof_rows = stage7b._asof_rows_by_task(
        protocol_path / "stage7_asof_evaluation_binding_manifest.json"
    )
    b0_payloads = stage7b._jsonl_by_task(protocol_path / "stage7_b0_input_payloads.jsonl")
    b1_payloads = stage7b._jsonl_by_task(protocol_path / "stage7_b1_input_payloads.jsonl")
    stage6b_inputs = load_stage6b_inputs(repo_root)
    p_bundles, p_requests, binding_rows = stage7b.build_proposed_requests(
        additional, asof_rows, stage6b_inputs
    )
    manifest = stage7b.build_execution_manifest(
        additional, b0_payloads, b1_payloads, p_requests, execution_protocol
    )
    credential_present = bool(os.environ.get("DEEPSEEK_API_KEY"))
    credential_ok = (not execute) or credential_present
    try:
        import openai  # noqa: F401

        sdk_ok = True
    except ImportError:
        sdk_ok = False
    preflight_rows = [
        _audit_row("additional_task_count", len(additional) == ADDITIONAL_COUNT, len(additional)),
        _audit_row("combined_task_count", len(combined) == COMBINED_COUNT, len(combined)),
        _audit_row(
            "additional_product_quota",
            Counter(row["product_type"] for row in additional)
            == {product: ADDITIONAL_QUOTA for product in PRODUCTS},
            dict(Counter(row["product_type"] for row in additional)),
        ),
        _audit_row("execution_item_count", manifest["item_count"] == 456, manifest["item_count"]),
        _audit_row(
            "proposed_binding",
            _status_fail_count(binding_rows) == 0,
            _status_fail_count(binding_rows),
        ),
        _audit_row("provider", provider == "deepseek", provider),
        _audit_row("model", model == DEEPSEEK_RESPONSES_SUPPORTED_MODEL, model),
        _audit_row(
            "max_retries", provider_config["max_retries"] == 0, provider_config["max_retries"]
        ),
        _audit_row(
            "credential_env_present",
            credential_ok,
            (
                "present"
                if credential_present
                else "not_required_for_dry_run"
                if not execute
                else "missing"
            ),
        ),
        _audit_row("openai_sdk_importable", sdk_ok, sdk_ok),
    ]
    write_json(output / "execution_protocol.json", execution_protocol)
    write_json(output / "execution_manifest.json", manifest)
    write_csv(output / "execution_manifest.csv", manifest["items"])
    write_csv(output / "preflight_audit.csv", preflight_rows)
    write_csv(output / "proposed_asof_binding_audit.csv", binding_rows)
    failures = [row["check_name"] for row in preflight_rows if row["status"] != "PASS"]
    if failures:
        summary = {
            "status": "NOT_RUN",
            "failure_codes": failures,
            "real_api_request_attempt_count": 0,
        }
        write_json(output / "run_summary.json", summary)
        write_hashes(output)
        if execute:
            raise RuntimeError(f"Supplemental preflight failed: {failures}")
        return summary
    if not execute:
        summary = {
            "status": "DRY_RUN_PASS",
            "additional_task_count": len(additional),
            "combined_task_count": len(combined),
            "execution_manifest_item_count": manifest["item_count"],
            "execution_protocol_hash": execution_protocol["execution_protocol_hash"],
            "execution_manifest_hash": manifest["execution_manifest_hash"],
            "real_api_request_attempt_count": 0,
        }
        write_json(output / "run_summary.json", summary)
        write_hashes(output)
        return summary

    run_id = stable_id(
        "stage7_supplemental_execution",
        {
            "protocol_hash": execution_protocol["execution_protocol_hash"],
            "started_at": datetime.now(tz=UTC).isoformat(),
        },
    )
    run_dir = output / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json(run_dir / "execution_protocol.json", execution_protocol)
    write_json(run_dir / "execution_manifest.json", manifest)
    write_csv(run_dir / "execution_manifest.csv", manifest["items"])
    write_csv(run_dir / "proposed_asof_binding_audit.csv", binding_rows)
    result = stage7b.execute_stage7b_manifest(
        run_id,
        manifest["items"],
        b0_payloads,
        b1_payloads,
        p_bundles,
        p_requests,
        (protocol_path / "stage7_b0_prompt_template_v1_1.txt").read_text(encoding="utf-8"),
        (protocol_path / "stage7_b1_prompt_template_v1_1.txt").read_text(encoding="utf-8"),
        provider_config,
        execution_protocol,
        run_dir,
    )
    hard_rows = [
        _audit_row(
            "execution_manifest_count", manifest["item_count"] == 456, manifest["item_count"]
        ),
        _audit_row(
            "real_api_attempts",
            result["real_api_request_attempt_count"] == 456,
            result["real_api_request_attempt_count"],
        ),
        _audit_row(
            "transport_failures",
            result["transport_failure_count"] == 0,
            result["transport_failure_count"],
        ),
        _audit_row(
            "p_post_audit",
            result["p_post_audit_fail_count"] == 0,
            result["p_post_audit_fail_count"],
        ),
    ]
    formal = {
        "schema_version": SCHEMA_VERSION,
        "method_version": METHOD_VERSION,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "execution_protocol_hash": execution_protocol["execution_protocol_hash"],
        "execution_manifest_hash": manifest["execution_manifest_hash"],
        "run_dir": run_dir.relative_to(output).as_posix(),
        "run_summary": result,
        "hard_check_fail_count": sum(row["status"] != "PASS" for row in hard_rows),
    }
    write_csv(output / "execution_hard_check.csv", hard_rows)
    write_json(output / "latest_run.json", formal)
    write_json(output / "run_summary.json", result)
    write_hashes(output)
    return result


def _latest_supplemental_run(execution_root: Path) -> Path:
    latest = read_json(execution_root / "latest_run.json")
    return execution_root / str(latest["run_dir"])


def _load_outputs_from_runs(run_dirs: list[Path]) -> dict[str, dict[str, str]]:
    outputs: dict[str, dict[str, str]] = {}
    for run_dir in run_dirs:
        outputs.update(stage7c._load_actual_outputs(run_dir))
    return outputs


def build_supplemental_auto_eval(
    repo_root: Path,
    output_dir: Path | None = None,
    *,
    protocol_dir: Path | None = None,
    execution_root: Path | None = None,
) -> dict[str, Any]:
    """Combine frozen 48 outputs and supplemental outputs for automatic evaluation."""

    repo_root = repo_root.resolve()
    protocol_path = (protocol_dir or repo_root / PROTOCOL_DIR).resolve()
    execution_path = (execution_root or repo_root / EXECUTION_DIR).resolve()
    output = (output_dir or repo_root / EVALUATION_DIR).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    supplemental_run = _latest_supplemental_run(execution_path)
    original_run = repo_root / FROZEN_STAGE7B_RUN
    tasks = read_json(protocol_path / "combined_200_benchmark_manifest.json")["tasks"]
    task_by_id = {str(row["benchmark_task_id"]): row for row in tasks}
    b0_payloads = stage7c._jsonl_by_key(
        protocol_path / "stage7_b0_input_payloads.jsonl", "benchmark_task_id"
    )
    preclaim_refs = stage7c._jsonl_by_key(
        protocol_path / "stage7_proposed_preclaim_reference.jsonl", "benchmark_task_id"
    )
    execution_items: list[dict[str, Any]] = []
    plan_rows: list[dict[str, Any]] = []
    for run_dir in [original_run, supplemental_run]:
        execution_items.extend(read_json(run_dir / "execution_manifest.json")["items"])
        plan_rows.extend(stage7c._read_csv(run_dir / "P_plan_validation.csv"))
    execution_items.sort(
        key=lambda row: (row["benchmark_task_id"], row["method_position_for_task"])
    )
    plan_by_item = {str(row["execution_item_id"]): row for row in plan_rows}
    text_by_item = _load_outputs_from_runs([original_run, supplemental_run])
    condition_rows, no_output_rows = stage7c._build_condition_manifest(
        execution_items, task_by_id, b0_payloads, text_by_item, plan_by_item
    )
    actual_text_rows = stage7c._build_actual_text_manifest(condition_rows, text_by_item)
    statement_rows, context_rows = stage7c._build_statement_and_context_tables(actual_text_rows)
    context_by_task = {
        task_id: stage7c._evaluation_context(
            task_id,
            b0_payloads[task_id],
            task_by_id[task_id],
            preclaim_refs.get(task_id, {}),
            repo_root,
        )
        for task_id in sorted(task_by_id)
    }
    binding_rows = stage7c._statement_subject_binding(
        statement_rows, condition_rows, context_by_task
    )
    trace_rows, trace_cardinality = stage7c._statement_trace_table(
        statement_rows,
        condition_rows,
        task_by_id,
        preclaim_refs,
        repo_root,
        asof_binding_path=protocol_path / "stage7_asof_evaluation_binding_manifest.csv",
    )
    audit_rows = stage7c._evaluate_statements(
        statement_rows,
        condition_rows,
        context_by_task,
        plan_by_item,
        binding_rows,
        trace_rows,
    )
    condition_summary = stage7c._condition_summary(condition_rows, audit_rows)
    binary_rows = stage7c._condition_binary_endpoints(condition_rows, audit_rows)
    method_summary = stage7c._method_summary(condition_rows, audit_rows)
    main_ids = {
        str(row["benchmark_task_id"])
        for row in read_json(
            repo_root / FROZEN_STAGE7A_DIR / "stage7_main_benchmark_manifest.json"
        )["tasks"]
    }
    additional_ids = set(task_by_id) - main_ids
    subgroup_rows = []
    for group_name, task_ids in [
        ("FROZEN_MAIN_48", main_ids),
        ("SUPPLEMENTAL_152", additional_ids),
        ("COMBINED_200", set(task_by_id)),
    ]:
        group_conditions = [row for row in condition_rows if str(row["task_id"]) in task_ids]
        condition_ids = {str(row["condition_id"]) for row in group_conditions}
        group_audits = [row for row in audit_rows if str(row["condition_id"]) in condition_ids]
        for row in stage7c._method_summary(group_conditions, group_audits):
            subgroup_rows.append({"analysis_group": group_name, **row})

    method_counts = Counter(str(row["method_internal"]) for row in condition_rows)
    actual_text_counts = Counter(str(row["method_internal"]) for row in actual_text_rows)
    automatic_fail_counts = Counter(
        (str(row["method_internal"]), str(row["error_code"]))
        for row in audit_rows
        if row["result"] == "FAIL"
    )
    trace_incomplete_count = sum(row["trace_status"] == "TRACE_INCOMPLETE" for row in trace_rows)
    actual_text_counts_summary = dict(sorted(actual_text_counts.items()))
    automatic_fail_counts_summary = {
        f"{method}:{code}": count for (method, code), count in sorted(automatic_fail_counts.items())
    }
    hard_rows = [
        _audit_row("task_count_200", len(tasks) == COMBINED_COUNT, len(tasks)),
        _audit_row("condition_count_600", len(condition_rows) == 600, len(condition_rows)),
        _audit_row(
            "method_condition_counts",
            method_counts
            == {
                stage7b.B0_METHOD: COMBINED_COUNT,
                stage7b.B1_METHOD: COMBINED_COUNT,
                stage7b.P_METHOD: COMBINED_COUNT,
            },
            dict(method_counts),
        ),
        _audit_row("main_task_count", len(main_ids) == MAIN_COUNT, len(main_ids)),
        _audit_row(
            "additional_task_count", len(additional_ids) == ADDITIONAL_COUNT, len(additional_ids)
        ),
        _audit_row(
            "unique_execution_items",
            len({row["execution_item_id"] for row in execution_items}) == 600,
            len({row["execution_item_id"] for row in execution_items}),
        ),
        _audit_row(
            "context_complete", set(context_by_task) == set(task_by_id), len(context_by_task)
        ),
    ]
    _write_loose_csv(output / "condition_manifest.csv", condition_rows)
    _write_loose_csv(output / "actual_text_manifest.csv", actual_text_rows)
    _write_loose_csv(output / "no_output_conditions.csv", no_output_rows)
    _write_loose_csv(output / "statement_table.csv", statement_rows)
    _write_loose_csv(output / "statement_context_table.csv", context_rows)
    _write_loose_csv(output / "statement_subject_binding.csv", binding_rows)
    _write_loose_csv(output / "statement_trace_table.csv", trace_rows)
    _write_loose_csv(output / "trace_cardinality_audit.csv", trace_cardinality)
    _write_loose_csv(output / "automatic_statement_audit.csv", audit_rows)
    _write_loose_csv(output / "automatic_condition_summary.csv", condition_summary)
    _write_loose_csv(output / "automatic_condition_binary_endpoints.csv", binary_rows)
    _write_loose_csv(output / "method_automatic_summary.csv", method_summary)
    _write_loose_csv(output / "grouped_method_automatic_summary.csv", subgroup_rows)
    write_csv(output / "hard_check.csv", hard_rows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "method_version": METHOD_VERSION,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "task_count": len(tasks),
        "condition_count": len(condition_rows),
        "actual_text_count": len(actual_text_rows),
        "no_output_condition_count": len(no_output_rows),
        "statement_count": len(statement_rows),
        "actual_text_counts_by_method": actual_text_counts_summary,
        "p_fail_closed_count": sum(
            row["method_internal"] == stage7b.P_METHOD and row["output_available"] == "false"
            for row in condition_rows
        ),
        "automatic_fail_count": sum(automatic_fail_counts.values()),
        "automatic_fail_counts_by_method_and_code": automatic_fail_counts_summary,
        "trace_incomplete_count": trace_incomplete_count,
        "hard_check_fail_count": sum(row["status"] != "PASS" for row in hard_rows),
        "original_run": original_run.relative_to(repo_root).as_posix(),
        "supplemental_run": supplemental_run.relative_to(repo_root).as_posix(),
        "uses_llm_as_judge": False,
        "human_evaluation_added": False,
    }
    write_json(output / "summary.json", summary)
    write_json(output / "method_version.json", summary)
    (output / "evaluation_report.md").write_text(
        "\n".join(
            [
                "# Stage7 Supplemental 200-Task Automatic Evaluation",
                "",
                f"- Tasks: {summary['task_count']}",
                f"- Method-task conditions: {summary['condition_count']}",
                f"- Actual texts: {summary['actual_text_count']}",
                f"- No-output conditions: {summary['no_output_condition_count']}",
                f"- Statements: {summary['statement_count']}",
                f"- Hard-check failures: {summary['hard_check_fail_count']}",
                f"- Strict automatic error instances: {summary['automatic_fail_count']}",
                f"- Proposed fail-closed tasks: {summary['p_fail_closed_count']}",
                f"- Incomplete Proposed traces: {summary['trace_incomplete_count']}",
                "",
                "## Method outputs",
                "",
                *[
                    f"- {method}: {count}/200 actual texts"
                    for method, count in actual_text_counts_summary.items()
                ],
                "",
                "## Strict automatic errors",
                "",
                *(
                    [f"- {key}: {count}" for key, count in automatic_fail_counts_summary.items()]
                    or ["- None"]
                ),
                "",
                "The original 48-task human evaluation remains unchanged. The 152 additions",
                "receive deterministic automatic evaluation only.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    write_hashes(output)
    return summary


def upstream_gold_readiness(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    """Audit whether frozen upstream annotations are complete enough to score."""

    import csv

    root = repo_root / "artifacts/paper_evidence_completion_v2"

    def rows(path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    plc = rows(root / "plc_episode_annotation/annotation_template.csv")
    geology = rows(root / "geology_field_annotation/field_annotation_template.csv")
    plc_complete = sum(str(row.get("review_complete", "")).lower() == "true" for row in plc)
    geology_complete = sum(str(row.get("review_complete", "")).lower() == "true" for row in geology)
    geology_samples = {row["sample_id"] for row in geology}
    completed_geology_samples = {
        row["sample_id"] for row in geology if str(row.get("review_complete", "")).lower() == "true"
    }
    audit = [
        {
            "component": "PLC_EPISODE_GOLD",
            "sample_count": len(plc),
            "annotation_row_count": len(plc),
            "completed_row_count": plc_complete,
            "status": "READY_TO_SCORE" if plc_complete == len(plc) else "PENDING_HUMAN_ANNOTATION",
        },
        {
            "component": "GEOLOGY_FIELD_GOLD",
            "sample_count": len(geology_samples),
            "annotation_row_count": len(geology),
            "completed_row_count": geology_complete,
            "completed_sample_count": len(completed_geology_samples),
            "status": (
                "READY_TO_SCORE" if geology_complete == len(geology) else "PENDING_HUMAN_ANNOTATION"
            ),
        },
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "upstream_gold_readiness_audit.csv", audit)
    summary = {
        "plc_sample_count": len(plc),
        "plc_completed_count": plc_complete,
        "geology_sample_count": len(geology_samples),
        "geology_field_row_count": len(geology),
        "geology_completed_field_row_count": geology_complete,
        "status": (
            "READY_TO_SCORE"
            if plc_complete == len(plc) and geology_complete == len(geology)
            else "BLOCKED_PENDING_HUMAN_ANNOTATION"
        ),
        "accuracy_metrics_generated": False,
        "reason": "Gold labels must be source-verified by a human and cannot be self-generated.",
    }
    write_json(output_dir / "upstream_gold_readiness_summary.json", summary)
    (output_dir / "upstream_gold_readiness_report.md").write_text(
        "\n".join(
            [
                "# Upstream Gold Readiness",
                "",
                f"- Status: {summary['status']}",
                f"- PLC samples: {summary['plc_sample_count']}",
                f"- PLC completed labels: {summary['plc_completed_count']}",
                f"- Geology samples: {summary['geology_sample_count']}",
                f"- Geology field rows: {summary['geology_field_row_count']}",
                f"- Geology completed field labels: {summary['geology_completed_field_row_count']}",
                "- Accuracy metrics generated: false",
                "",
                "No accuracy, precision, recall, F1, or boundary-error metric is reported because",
                "the source-verification labels have not been completed by human annotators.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    write_hashes(output_dir)
    return summary
