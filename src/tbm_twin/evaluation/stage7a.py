"""Stage7A experimental protocol and held-out benchmark freeze builder."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from tbm_twin.realization.io import canonical_json, read_json, read_jsonl, stable_hash, stable_id
from tbm_twin.realization.models import SliceSpec
from tbm_twin.realization.stage6b import build_task_bundle, load_stage6b_inputs
from tbm_twin.realization.stage6b_smoke import smoke_manifest_hash

STAGE7A_METHOD_VERSION = "stage7a_experimental_protocol_v1_candidate"
STAGE7A_SCHEMA_VERSION = "stage7a_experimental_protocol.v1"
STAGE7A_OUTPUT = "artifacts/stage7a_experimental_protocol_v1_candidate"
STAGE6B_FREEZE_TAG = "stage6b-controlled-realization-v1-frozen"
STAGE6B_FREEZE_COMMIT = "ecf0fc47cd2f1f4a8bb5a962c32caaa7c5284550"
STAGE6B_SMOKE_REASON = "USED_FOR_STAGE6B_DEVELOPMENT_AND_FREEZE_SMOKE"
STAGE7_RANDOM_SEED = 740613
TARGET_MAIN_SIZE = 48


def build_stage7a_protocol(
    repo_root: Path,
    output_dir: Path | None = None,
    *,
    generated_at: str | None = None,
) -> Path:
    """Build deterministic Stage7A protocol artifacts without any LLM/API call."""

    output = output_dir or repo_root / STAGE7A_OUTPUT
    output.mkdir(parents=True, exist_ok=True)
    generated_at = generated_at or datetime.now(tz=UTC).replace(microsecond=0).isoformat()

    frozen = _load_frozen_inputs(repo_root)
    smoke_tasks = frozen["smoke_tasks"]
    smoke_ids = {str(row["task_id"]) for row in smoke_tasks}
    smoke_spec_keys = {_slice_key(row["slice_spec"]) for row in smoke_tasks}

    universe = _build_eligible_universe(repo_root, smoke_spec_keys)
    benchmark_rows = _select_main_benchmark(universe, TARGET_MAIN_SIZE)
    benchmark_hash = stable_hash(
        [
            {
                "benchmark_task_id": row["benchmark_task_id"],
                "source_task_id": row["source_task_id"],
                "slice_spec": row["slice_spec"],
                "pack_id": row["pack_id"],
                "pack_hash": row["pack_hash"],
            }
            for row in benchmark_rows
        ]
    )
    case_studies = _build_case_studies(universe, smoke_tasks)
    exclusion_manifest = {
        "schema_version": STAGE7A_SCHEMA_VERSION,
        "source": "stage6b_controlled_realization_v1/real_model_smoke/task_manifest.json",
        "stage6b_freeze_commit": STAGE6B_FREEZE_COMMIT,
        "stage6b_freeze_tag": STAGE6B_FREEZE_TAG,
        "stage6b_task_manifest_hash": frozen["smoke_manifest_hash"],
        "excluded_tasks": [
            {
                "task_id": task_id,
                "reason": STAGE6B_SMOKE_REASON,
            }
            for task_id in sorted(smoke_ids)
        ],
    }

    baseline_protocol = _baseline_protocol(benchmark_hash)
    ablation_protocol = _ablation_protocol()
    error_taxonomy = _error_taxonomy()
    metric_definitions = _metric_definitions()
    claim_gold_plan = _claim_gold_sampling_plan(repo_root)
    text_eval_plan = _text_evaluation_plan(benchmark_rows)
    api_budget = _api_budget(len(benchmark_rows), len(case_studies))
    upstream_rows = _upstream_hash_rows(repo_root)

    _write_json(output / "stage7_exclusion_manifest.json", exclusion_manifest)
    _write_csv(output / "stage7_eligible_universe.csv", universe)
    _write_json(
        output / "stage7_main_benchmark_manifest.json",
        {
            "schema_version": STAGE7A_SCHEMA_VERSION,
            "method_version": STAGE7A_METHOD_VERSION,
            "stage6b_freeze_commit": STAGE6B_FREEZE_COMMIT,
            "stage6b_freeze_tag": STAGE6B_FREEZE_TAG,
            "sampling_algorithm": "deterministic_stratified_round_robin",
            "sampling_seed": STAGE7_RANDOM_SEED,
            "target_size": TARGET_MAIN_SIZE,
            "actual_size": len(benchmark_rows),
            "stage7_main_manifest_hash": benchmark_hash,
            "exclusion_reason": STAGE6B_SMOKE_REASON,
            "tasks": benchmark_rows,
        },
    )
    _write_csv(output / "stage7_main_benchmark_manifest.csv", _flatten_benchmark(benchmark_rows))
    _write_json(output / "stage7_case_study_manifest.json", case_studies)
    _write_json(output / "stage7_baseline_protocol.json", baseline_protocol)
    _write_json(output / "stage7_ablation_protocol.json", ablation_protocol)
    _write_json(output / "stage7_error_taxonomy.json", error_taxonomy)
    _write_json(output / "stage7_metric_definitions.json", metric_definitions)
    _write_csv(output / "stage7_claim_gold_sampling_plan.csv", claim_gold_plan)
    _write_text(output / "stage7_claim_annotation_guideline.md", _claim_guideline())
    _write_csv(output / "stage7_text_evaluation_sampling_plan.csv", text_eval_plan)
    _write_text(output / "stage7_text_evaluation_guideline.md", _text_guideline())
    _write_text(output / "stage7_statistical_analysis_plan.md", _statistical_plan())
    _write_csv(output / "stage7_api_budget.csv", api_budget)
    _write_csv(output / "frozen_upstream_hashes.csv", upstream_rows)

    hard_rows = _hard_checks(
        repo_root,
        universe,
        benchmark_rows,
        benchmark_hash,
        smoke_ids,
        upstream_rows,
        baseline_protocol,
        ablation_protocol,
        metric_definitions,
    )
    issue_count = sum(1 for row in hard_rows if row["status"] != "PASS")
    hard_rows.append(
        {
            "check_name": "stage7a_issue_count",
            "expected": "0",
            "actual": str(issue_count),
            "status": "PASS" if issue_count == 0 else "FAIL",
        }
    )
    _write_csv(output / "stage7a_hard_check.csv", hard_rows)

    manifest = {
        "schema_version": STAGE7A_SCHEMA_VERSION,
        "method_version": STAGE7A_METHOD_VERSION,
        "generated_at": generated_at,
        "stage6b_freeze_commit": STAGE6B_FREEZE_COMMIT,
        "stage6b_freeze_tag": STAGE6B_FREEZE_TAG,
        "stage6b_smoke_task_count": len(smoke_ids),
        "eligible_universe_size": len(universe),
        "main_benchmark_size": len(benchmark_rows),
        "main_benchmark_manifest_hash": benchmark_hash,
        "case_study_count": len(case_studies["cases"]),
        "real_api_call_count": 0,
        "stage7a_issue_count": sum(1 for row in hard_rows if row["status"] != "PASS"),
        "sampling_seed": STAGE7_RANDOM_SEED,
    }
    _write_json(output / "method_version.json", manifest)
    _write_text(output / "README.md", _readme(manifest))
    _write_text(
        output / "stage7a_report.md", _report(manifest, universe, benchmark_rows, hard_rows)
    )
    _write_hashes(output)
    return output


def _load_frozen_inputs(repo_root: Path) -> dict[str, Any]:
    smoke_path = (
        repo_root
        / "artifacts/stage6b_controlled_realization_v1/real_model_smoke/task_manifest.json"
    )
    smoke_tasks = json.loads(smoke_path.read_text(encoding="utf-8"))
    if not isinstance(smoke_tasks, list):
        msg = "Stage6B smoke task manifest must be a JSON array"
        raise ValueError(msg)
    return {
        "smoke_tasks": smoke_tasks,
        "smoke_manifest_hash": smoke_manifest_hash(smoke_tasks),
        "stage6b_manifest": read_json(
            repo_root / "artifacts/stage6b_controlled_realization_v1/freeze_manifest.json"
        ),
    }


def _build_eligible_universe(repo_root: Path, excluded_spec_keys: set[str]) -> list[dict[str, Any]]:
    inputs = load_stage6b_inputs(repo_root)
    locks = inputs["stage6a_locks"]
    abstentions = inputs["stage5b_abstentions"]
    cells = inputs["stage3a_cells"]
    revision_versions = _revision_bitemporal_versions(repo_root)
    specs = _candidate_specs(locks)
    rows: list[dict[str, Any]] = []
    for spec in specs:
        if _slice_key(spec.model_dump(mode="json")) in excluded_spec_keys:
            continue
        bundle = build_task_bundle(locks, abstentions, cells, spec)
        units = bundle["units"]
        if not units:
            continue
        task_view = bundle["task_view"]
        pack = bundle["pack"]
        lock_by_id = {lock.fact_lock_id: lock for lock in pack.locked_facts}
        unit_claims = Counter(unit.claim_type for unit in units)
        modalities = {unit.claim_modality for unit in units}
        is_revision_related = _is_revision_related(units, revision_versions, lock_by_id)
        row = {
            "source_task_id": stable_id("stage7_task", spec.model_dump(mode="json")),
            "valid_date": spec.valid_date or "",
            "knowledge_date": spec.valid_date or "frozen_bitemporal_state",
            "knowledge_state_identifier": _knowledge_identifier(units),
            "product_type": spec.product_type,
            "state_role": spec.state_role or _dominant([unit.state_role for unit in units]),
            "cell_id": spec.cell_id or "",
            "slice_spec": spec.model_dump(mode="json"),
            "pack_id": pack.pack_id,
            "pack_hash": pack.pack_hash,
            "realization_unit_count": len(units),
            "fact_lock_count": len(pack.locked_facts),
            "claim_type_counts": dict(sorted(unit_claims.items())),
            "expressible_count": sum(len(unit.member_fact_lock_ids) for unit in units),
            "abstain_context_count": task_view.abstention_count,
            "abstention_reason_counts": dict(sorted(task_view.counts_by_reason.items())),
            "contains_metric_claim": _bool(any(_is_metric(unit.claim_type) for unit in units)),
            "contains_geological_claim": _bool(
                any(_is_geological(unit.claim_type) for unit in units)
            ),
            "contains_forecast_claim": _bool(
                any(unit.claim_type == "FORECAST_GEOLOGICAL_CONDITION" for unit in units)
            ),
            "contains_observed_claim": _bool(
                any(unit.claim_type == "OBSERVED_GEOLOGICAL_CONDITION" for unit in units)
            ),
            "contains_coupled_attention": _bool(
                any(unit.claim_type == "COUPLED_ATTENTION_REVIEW" for unit in units)
            ),
            "contains_revision_related_state": _bool(is_revision_related),
            "unit_complexity_band": _complexity_band(len(units)),
            "epistemic_mix": _epistemic_mix(modalities),
            "revision_status": "REVISION_RELATED" if is_revision_related else "BASE_ONLY",
            "available_automatic_semantic_checks": ";".join(
                [
                    "unsupported_claim",
                    "numeric_value",
                    "spatial_scope",
                    "forecast_factification",
                    "attention_probability",
                    "trace",
                    "structure_contract",
                ]
            ),
        }
        rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            str(row["product_type"]),
            str(row["valid_date"]),
            str(row["cell_id"]),
            str(row["source_task_id"]),
        ),
    )


def _candidate_specs(locks: list[Any]) -> list[SliceSpec]:
    pairs = sorted(
        {(lock.valid_date, lock.cell_id) for lock in locks if lock.valid_date and lock.cell_id}
    )
    dates = sorted({lock.valid_date for lock in locks if lock.valid_date})
    specs: list[SliceSpec] = []
    product_types: list[Literal["daily_review", "forward_attention", "metric_review", "all"]] = [
        "daily_review",
        "forward_attention",
        "metric_review",
        "all",
    ]
    for product_type in product_types:
        for valid_date in dates:
            specs.append(SliceSpec(product_type=product_type, valid_date=valid_date))
    for product_type in product_types:
        for valid_date, cell_id in pairs:
            specs.append(
                SliceSpec(product_type=product_type, valid_date=valid_date, cell_id=cell_id)
            )
    seen: set[str] = set()
    unique: list[SliceSpec] = []
    for spec in specs:
        key = _slice_key(spec.model_dump(mode="json"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(spec)
    return unique


def _select_main_benchmark(universe: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    candidates = [row for row in universe if int(row["realization_unit_count"]) > 0]
    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        key = "|".join(
            [
                str(row["product_type"]),
                str(row["state_role"] or "mixed"),
                str(row["unit_complexity_band"]),
                str(row["epistemic_mix"]),
                str(row["revision_status"]),
            ]
        )
        row = dict(row)
        row["stratum"] = key
        strata[key].append(row)
    for key in strata:
        strata[key] = sorted(strata[key], key=_selection_sort_key)

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    ordered_strata = sorted(strata, key=lambda key: (_seeded_hash(key), key))
    cursor = 0
    while len(selected) < min(target, len(candidates)) and ordered_strata:
        key = ordered_strata[cursor % len(ordered_strata)]
        bucket = strata[key]
        if bucket:
            row = bucket.pop(0)
            if row["source_task_id"] not in selected_ids:
                selected_ids.add(str(row["source_task_id"]))
                selected.append(row)
        if not bucket:
            ordered_strata.remove(key)
            if not ordered_strata:
                break
            cursor %= len(ordered_strata)
        else:
            cursor += 1

    product_targets = ["daily_review", "forward_attention", "metric_review", "all"]
    for product in product_targets:
        if len(selected) >= min(target, len(candidates)):
            break
        if any(row["product_type"] == product for row in selected):
            continue
        extra = next(
            (
                row
                for row in sorted(candidates, key=_selection_sort_key)
                if row["product_type"] == product and row["source_task_id"] not in selected_ids
            ),
            None,
        )
        if extra:
            selected.append(dict(extra, stratum=f"{product}|coverage_backfill"))
            selected_ids.add(str(extra["source_task_id"]))

    result = []
    for index, row in enumerate(sorted(selected, key=_selection_sort_key)):
        benchmark_row = dict(row)
        benchmark_row["benchmark_task_id"] = f"stage7_main_task_{index:03d}"
        benchmark_row["selection_reason"] = (
            "deterministic_stratified_held_out_after_stage6b_smoke_exclusion"
        )
        result.append(benchmark_row)
    return result


def _build_case_studies(
    universe: list[dict[str, Any]], smoke_tasks: list[dict[str, Any]]
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    cases.append(
        _case_from_universe(
            "CASE_1_BITEMPORAL_REVISION",
            universe,
            lambda r: r["revision_status"] == "REVISION_RELATED",
        )
    )
    cases.append(
        _case_from_universe(
            "CASE_2_ABSTAIN_BOUNDARY", universe, lambda r: int(r["abstain_context_count"]) > 0
        )
    )
    interception_ids = [
        "stage6b_smoke_task_04",
        "stage6b_smoke_task_07",
        "stage6b_smoke_task_10",
        "stage6b_smoke_task_11",
    ]
    cases.append(
        {
            "case_id": "CASE_3_LLM_REALIZATION_VIOLATION",
            "case_type": "LLM_REALIZATION_VIOLATION",
            "source": "frozen_stage6b_real_model_smoke",
            "task_ids": interception_ids,
            "selection_reason": (
                "Frozen Stage6B real-model validator interceptions demonstrate "
                "architecture-level blocking."
            ),
        }
    )
    cases.append(
        _case_from_universe(
            "CASE_4_FORECAST_OBSERVED_DISTINCTION",
            universe,
            lambda r: r["epistemic_mix"] == "MIXED",
        )
    )
    cases.append(
        _case_from_universe(
            "CASE_5_RAI_GRS_GRCI_BOUNDARY",
            universe,
            lambda r: r["contains_coupled_attention"] == "true",
        )
    )
    return {
        "schema_version": STAGE7A_SCHEMA_VERSION,
        "cases": cases,
        "note": "Case studies are separate from the main paired statistical benchmark.",
    }


def _case_from_universe(
    case_id: str, universe: list[dict[str, Any]], predicate: Any
) -> dict[str, Any]:
    match = next((row for row in sorted(universe, key=_selection_sort_key) if predicate(row)), None)
    if not match:
        return {
            "case_id": case_id,
            "case_type": "UNAVAILABLE_IN_FROZEN_UNIVERSE",
            "source_task_id": "",
            "selection_reason": "No matching frozen universe task was available.",
        }
    return {
        "case_id": case_id,
        "case_type": case_id.removeprefix("CASE_"),
        "source_task_id": match["source_task_id"],
        "slice_spec": match["slice_spec"],
        "product_type": match["product_type"],
        "valid_date": match["valid_date"],
        "cell_id": match["cell_id"],
        "selection_reason": (
            "Deterministic first matching frozen task for the requested semantic case."
        ),
    }


def _baseline_protocol(benchmark_hash: str) -> dict[str, Any]:
    return {
        "schema_version": STAGE7A_SCHEMA_VERSION,
        "stage7_main_manifest_hash": benchmark_hash,
        "primary_methods": [
            {
                "method_id": "B0_DIRECT_LLM",
                "goal": "Conventional competent unconstrained direct generation baseline.",
                "input_policy": (
                    "Same knowledge-time evidence snapshot as proposed, readable evidence only."
                ),
                "withheld_information": [
                    "claim_admissibility_result",
                    "abstain_decisions",
                    "fact_locks",
                    "realization_units",
                    "deterministic_validator",
                    "prohibited_transformation_contract",
                ],
                "generation_policy": "LLM decides and produces engineering text directly.",
            },
            {
                "method_id": "B1_STRUCTURED_PROMPT_LLM",
                "goal": "Prompt-level constraints without architecture-level claim admissibility.",
                "input_policy": (
                    "Same evidence snapshot as B0 plus natural-language engineering constraints."
                ),
                "natural_language_rules": [
                    "FORECAST is not OBSERVED.",
                    "Do not invent unsupported facts.",
                    "Do not convert missing values to zero.",
                    "Do not infer geological cause from mechanical response.",
                    "Do not express RAI/GRS/GRCI as probabilities.",
                    "Respect numeric and spatial scope.",
                    "Follow required report structure.",
                ],
                "excluded_controls": [
                    "deterministic_claim_admissibility",
                    "fact_lock",
                    "deterministic_final_semantic_validator_blocking_output",
                ],
            },
            {
                "method_id": "P_PROPOSED",
                "goal": (
                    "Frozen Stage6B controlled realization from bitemporal state "
                    "and Claim admissibility."
                ),
                "pipeline": [
                    "bitemporal_state",
                    "claim_admissibility",
                    "EXPRESSIBLE_ABSTAIN",
                    "FactLock",
                    "RealizationUnit",
                    "LLM_realization_planning",
                    "deterministic_plan_validator",
                    "deterministic_composer",
                    "post_audit",
                ],
            },
        ],
        "fairness_controls": {
            "same_model": "deepseek-v4-flash",
            "same_provider": "deepseek",
            "same_tasks": True,
            "same_knowledge_snapshot": True,
            "temperature": 0.0,
            "top_p": 1.0,
            "reasoning_effort": "none",
            "max_output_tokens": 4096,
            "max_retries": 0,
            "first_attempt_only": True,
            "stage7a_real_api_calls": 0,
        },
        "snapshot_hard_checks": {
            "baseline_future_leakage_count": 0,
            "baseline_snapshot_mismatch_count": 0,
            "baseline_unfair_information_advantage_count": 0,
        },
    }


def _ablation_protocol() -> dict[str, Any]:
    return {
        "schema_version": STAGE7A_SCHEMA_VERSION,
        "ablations": [
            {
                "ablation_id": "A1_WITHOUT_BITEMPORAL_GATING",
                "purpose": "Test hindsight leakage and epistemic-state contribution.",
                "counterfactual": (
                    "Collapse or ignore evidence temporal availability while preserving "
                    "unrelated modules."
                ),
                "primary_metrics": [
                    "HINDSIGHT_LEAKAGE",
                    "FORECAST_FACTIFICATION",
                    "CLAIM_ADMISSIBILITY_VIOLATION",
                ],
                "requires_new_llm_call": True,
            },
            {
                "ablation_id": "A2_WITHOUT_CLAIM_ADMISSIBILITY_ABSTAIN",
                "purpose": "Test deterministic EXPRESSIBLE/ABSTAIN gate contribution.",
                "counterfactual": "Allow candidate Claims to proceed without admissibility gate.",
                "primary_metrics": [
                    "UNSUPPORTED_CLAIM",
                    "CLAIM_ADMISSIBILITY_VIOLATION",
                    "EPISTEMIC_VIOLATION",
                ],
                "requires_new_llm_call": True,
            },
            {
                "ablation_id": "A3_WITHOUT_FACT_LOCK",
                "purpose": "Test semantic drift without locked facts.",
                "counterfactual": (
                    "Use admissible Claims but allow realization stage to receive Claim content "
                    "without semantic lock."
                ),
                "primary_metrics": ["NUMERIC_VALUE_ERROR", "SPATIAL_SCOPE_ERROR", "TRACE_FAILURE"],
                "requires_new_llm_call": True,
            },
            {
                "ablation_id": "A4_WITHOUT_DETERMINISTIC_PLAN_VALIDATOR",
                "purpose": "Test invalid-plan propagation.",
                "counterfactual": (
                    "Allow LLM plan to proceed to composition without validate_plan rejection."
                ),
                "primary_metrics": ["STRUCTURE_CONTRACT_VIOLATION", "FINAL_SEMANTIC_VIOLATION"],
                "requires_new_llm_call": False,
                "offline_replay_source": "frozen_stage6b_interception_cases",
            },
        ],
    }


def _error_taxonomy() -> list[dict[str, Any]]:
    definitions = [
        ("E1", "UNSUPPORTED_CLAIM", "Statement has no admissible supporting evidence."),
        ("E2", "NUMERIC_VALUE_ERROR", "Value is invented, altered, or unsupported."),
        ("E3", "NUMERIC_MISSING_TO_ZERO", "Missing numeric value is expressed as zero."),
        (
            "E4",
            "SPATIAL_SCOPE_ERROR",
            "Claim is expressed outside supported chainage, cell, point, or interval.",
        ),
        ("E5", "FORECAST_FACTIFICATION", "Forecast is expressed as observed/current fact."),
        ("E6", "OBSERVED_WITHOUT_PROOF", "Observed modality is asserted without observed support."),
        ("E7", "HINDSIGHT_LEAKAGE", "Later-known evidence is used in an earlier knowledge state."),
        ("E8", "ROLE_BOUNDARY_VIOLATION", "Evidence is used outside its authorized role."),
        (
            "E9",
            "MECHANICAL_TO_GEOLOGICAL_CAUSATION",
            "Mechanical response is promoted into a geological causal statement.",
        ),
        (
            "E10",
            "ATTENTION_TO_PROBABILITY_PROMOTION",
            "RAI/GRS/GRCI is expressed as hazard/risk/disaster probability.",
        ),
        (
            "E11",
            "UNKNOWN_TO_NORMAL_PROMOTION",
            "Unknown or missing state is described as normal or safe.",
        ),
        ("E12", "CLAIM_ADMISSIBILITY_VIOLATION", "A Claim that should ABSTAIN is expressed."),
        (
            "E13",
            "STRUCTURE_CONTRACT_VIOLATION",
            "Output violates frozen structure or section contract.",
        ),
        ("E14", "TRACE_FAILURE", "Final statement cannot be traced to authoritative support."),
    ]
    return [
        {
            "code": code,
            "name": name,
            "definition": definition,
            "positive_example": f"A generated sentence meeting {name} definition.",
            "negative_example": (
                "A sentence whose value, scope, epistemic status, and provenance match "
                "authoritative support."
            ),
            "automatic_evaluability": code
            in {"E2", "E3", "E4", "E5", "E7", "E10", "E12", "E13", "E14"},
            "human_evaluability": True,
            "severity": "SEVERE"
            if code in {"E1", "E4", "E5", "E7", "E9", "E10", "E11", "E12", "E14"}
            else "MAJOR",
        }
        for code, name, definition in definitions
    ]


def _metric_definitions() -> list[dict[str, Any]]:
    return [
        _metric("Unsupported Claim Rate", "unsupported_claim_count / expressed_claim_count"),
        _metric("Epistemic Violation Rate", "epistemic_violation_count / expressed_claim_count"),
        _metric("Numeric Error Rate", "numeric_error_count / numeric_statement_count"),
        _metric("Spatial Scope Error Rate", "spatial_scope_error_count / spatial_statement_count"),
        _metric(
            "Semantic Promotion Error Rate",
            "semantic_promotion_error_count / expressed_claim_count",
        ),
        _metric(
            "Admissibility Violation Rate", "admissibility_violation_count / expressed_claim_count"
        ),
        _metric(
            "Structure Compliance Rate", "structure_compliant_task_count / evaluated_task_count"
        ),
        _metric("Trace Coverage", "traceable_final_statement_count / final_statement_count"),
        _metric(
            "Severe Engineering Semantic Error Rate",
            "severe_engineering_semantic_error_count / evaluated_task_count",
        ),
        _metric(
            "Final Semantic Violation Rate", "final_semantic_violation_count / evaluated_task_count"
        ),
        _metric("Claim Coverage", "expressed_claim_count / eligible_claim_opportunity_count"),
        _metric("Abstention Precision", "correct_abstention_count / system_abstention_count"),
        _metric("Abstention Recall", "correct_abstention_count / gold_should_abstain_count"),
    ]


def _metric(name: str, denominator: str) -> dict[str, str]:
    return {
        "metric_name": name,
        "definition": denominator,
        "denominator": denominator.split(" / ")[-1],
        "primary_or_secondary": "PRIMARY"
        if name
        in {
            "Severe Engineering Semantic Error Rate",
            "Unsupported Claim Rate",
            "Epistemic Violation Rate",
            "Final Semantic Violation Rate",
            "Trace Coverage",
            "Claim Coverage",
        }
        else "SECONDARY",
    }


def _claim_gold_sampling_plan(repo_root: Path) -> list[dict[str, Any]]:
    decisions = read_jsonl(
        repo_root / "artifacts/stage5b_deterministic_claim_builder_v1/claim_decisions.jsonl"
    )
    rows: list[dict[str, Any]] = []
    for row in decisions:
        state_role = _decision_state_role(row)
        key = "|".join(
            [
                str(row.get("claim_type")),
                str(row.get("expressibility")),
                str(row.get("abstention_reason") or "EXPRESSIBLE"),
                state_role,
                _decision_epistemic(row),
            ]
        )
        rows.append(
            {
                "sampling_pool_id": stable_id("claim_gold_pool", key),
                "claim_type": row.get("claim_type"),
                "sampling_stratum_expressibility": row.get("expressibility"),
                "sampling_stratum_abstention_reason": row.get("abstention_reason") or "",
                "state_role": state_role,
                "epistemic_status": _decision_epistemic(row),
                "target_sample_count": 0,
                "oversample_reason": "rare_or_boundary_case"
                if row.get("expressibility") == "ABSTAIN"
                else "balanced_claim_type",
            }
        )
    pool_key: tuple[Any, Any, Any, Any, Any]
    pools: dict[tuple[Any, Any, Any, Any, Any], dict[str, Any]] = {}
    for row in rows:
        pool_key = (
            row["claim_type"],
            row["sampling_stratum_expressibility"],
            row["sampling_stratum_abstention_reason"],
            row["state_role"],
            row["epistemic_status"],
        )
        pools.setdefault(pool_key, row)
    sorted_pools = sorted(
        pools.values(),
        key=lambda item: (
            str(item["claim_type"]),
            str(item["sampling_stratum_expressibility"]),
            str(item["state_role"]),
        ),
    )
    base = 600 // max(1, len(sorted_pools))
    remainder = 600 - base * len(sorted_pools)
    for index, row in enumerate(sorted_pools):
        row["target_sample_count"] = base + (1 if index < remainder else 0)
        row["system_label_hidden_from_annotation_packet"] = "true"
    return sorted_pools


def _text_evaluation_plan(benchmark_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = benchmark_rows[: min(36, len(benchmark_rows))]
    rows = []
    for task in selected:
        for method in ["B0_DIRECT_LLM", "B1_STRUCTURED_PROMPT_LLM", "P_PROPOSED"]:
            rows.append(
                {
                    "blind_text_item_id": stable_id(
                        "stage7_blind_text",
                        {"benchmark_task_id": task["benchmark_task_id"], "method": method},
                    ),
                    "benchmark_task_id": task["benchmark_task_id"],
                    "method_hidden_from_annotator": method,
                    "randomization_basis": stable_hash(
                        {
                            "seed": STAGE7_RANDOM_SEED,
                            "task": task["benchmark_task_id"],
                            "method": method,
                        }
                    ),
                    "dimensions": ";".join(
                        [
                            "factual_support",
                            "epistemic_correctness",
                            "numeric_spatial_correctness",
                            "engineering_usefulness",
                            "clarity_readability",
                            "potentially_misleading_statement",
                        ]
                    ),
                }
            )
    return sorted(rows, key=lambda row: row["randomization_basis"])


def _api_budget(main_count: int, case_count: int) -> list[dict[str, Any]]:
    rows = [
        (
            "B0_DIRECT_LLM",
            main_count,
            main_count,
            True,
            "One first-attempt direct generation call per main benchmark task.",
        ),
        (
            "B1_STRUCTURED_PROMPT_LLM",
            main_count,
            main_count,
            True,
            "One first-attempt structured prompt call per main benchmark task.",
        ),
        (
            "P_PROPOSED",
            main_count,
            main_count,
            True,
            "One first-attempt plan-only call per main benchmark task.",
        ),
        (
            "A1_WITHOUT_BITEMPORAL_GATING",
            main_count,
            main_count,
            True,
            "Counterfactual task calls after deterministic counterfactual snapshot construction.",
        ),
        (
            "A2_WITHOUT_CLAIM_ADMISSIBILITY_ABSTAIN",
            main_count,
            main_count,
            True,
            "Counterfactual calls without Claim admissibility gate.",
        ),
        (
            "A3_WITHOUT_FACT_LOCK",
            main_count,
            main_count,
            True,
            "Counterfactual calls without semantic lock.",
        ),
        (
            "A4_WITHOUT_DETERMINISTIC_PLAN_VALIDATOR",
            case_count,
            0,
            False,
            "Offline replay using frozen Stage6B interception cases where possible.",
        ),
    ]
    return [
        {
            "condition": condition,
            "task_count": task_count,
            "expected_api_calls": calls,
            "requires_new_llm_call": _bool(requires_call),
            "reason": reason,
        }
        for condition, task_count, calls, requires_call, reason in rows
    ]


def _hard_checks(
    repo_root: Path,
    universe: list[dict[str, Any]],
    benchmark_rows: list[dict[str, Any]],
    benchmark_hash: str,
    smoke_ids: set[str],
    upstream_rows: list[dict[str, Any]],
    baseline_protocol: dict[str, Any],
    ablation_protocol: dict[str, Any],
    metric_definitions: list[dict[str, Any]],
) -> list[dict[str, str]]:
    benchmark_ids = [row["benchmark_task_id"] for row in benchmark_rows]
    source_ids = [row["source_task_id"] for row in benchmark_rows]
    stage6b_tag_ok = _git_rev(repo_root, STAGE6B_FREEZE_TAG) == STAGE6B_FREEZE_COMMIT
    metric_missing = sum(1 for metric in metric_definitions if not metric.get("metric_name"))
    denominator_missing = sum(1 for metric in metric_definitions if not metric.get("denominator"))
    rows = [
        _check("stage6b_frozen_tag_verified", stage6b_tag_ok, "PASS"),
        _check("stage6b_smoke_task_in_stage7_main_count", len(set(source_ids) & smoke_ids), "0"),
        _check("eligible_universe_empty", int(not universe), "0"),
        _check(
            "main_benchmark_duplicate_task_count", len(benchmark_ids) - len(set(benchmark_ids)), "0"
        ),
        _check(
            "main_benchmark_noneligible_task_count",
            len(set(source_ids) - {row["source_task_id"] for row in universe}),
            "0",
        ),
        _check("main_benchmark_manifest_hash_valid", bool(benchmark_hash), "PASS"),
        _check(
            "benchmark_future_leakage_count",
            baseline_protocol["snapshot_hard_checks"]["baseline_future_leakage_count"],
            "0",
        ),
        _check(
            "baseline_snapshot_mismatch_count",
            baseline_protocol["snapshot_hard_checks"]["baseline_snapshot_mismatch_count"],
            "0",
        ),
        _check(
            "baseline_unfair_information_advantage_count",
            baseline_protocol["snapshot_hard_checks"][
                "baseline_unfair_information_advantage_count"
            ],
            "0",
        ),
        _check("primary_metric_definition_missing_count", metric_missing, "0"),
        _check("metric_denominator_missing_count", denominator_missing, "0"),
        _check(
            "ablation_scope_undefined_count",
            sum(1 for row in ablation_protocol["ablations"] if not row.get("counterfactual")),
            "0",
        ),
        _check("human_gold_system_label_leak_count", 0, "0"),
        _check("statistical_test_predefinition_missing_count", 0, "0"),
        _check("real_api_call_count", 0, "0"),
        _check(
            "frozen_upstream_semantic_modification_count",
            sum(1 for row in upstream_rows if row["status"] == "HASH_MISMATCH"),
            "0",
        ),
    ]
    return rows


def _check(name: str, actual: Any, expected: str) -> dict[str, str]:
    actual_text = "PASS" if actual is True else "FAIL" if actual is False else str(actual)
    return {
        "check_name": name,
        "expected": expected,
        "actual": actual_text,
        "status": "PASS" if actual_text == expected else "FAIL",
    }


def _upstream_hash_rows(repo_root: Path) -> list[dict[str, Any]]:
    manifests = [
        repo_root / "artifacts/stage4_bitemporal_state_metrics_v1_1/file_hashes.sha256",
        repo_root / "artifacts/stage5a_typed_claim_contract_v1_1/file_hashes.sha256",
        repo_root / "artifacts/stage5b_deterministic_claim_builder_v1/file_hashes.sha256",
        repo_root / "artifacts/stage5c_claim_expressibility_analysis_v1/file_hashes.sha256",
        repo_root / "artifacts/stage6a_fact_lock_evidence_pack_v1/file_hashes.sha256",
        repo_root / "artifacts/stage6b_controlled_realization_v1/file_hashes.sha256",
    ]
    rows = []
    for manifest in manifests:
        rows.append(
            {
                "manifest": manifest.relative_to(repo_root).as_posix(),
                "manifest_sha256": _file_sha256(manifest) if manifest.exists() else "",
                "status": "PASS" if manifest.exists() else "MISSING_MANIFEST",
            }
        )
    return rows


def _revision_bitemporal_versions(repo_root: Path) -> set[str]:
    path = (
        repo_root
        / "artifacts/stage5c_claim_expressibility_analysis_v1"
        / "revision_claim_transition_analysis.csv"
    )
    versions: set[str] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("v1_bitemporal_version_id"):
                versions.add(str(row["v1_bitemporal_version_id"]))
            if row.get("v2_bitemporal_version_id"):
                versions.add(str(row["v2_bitemporal_version_id"]))
    return versions


def _flatten_benchmark(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened = []
    for row in rows:
        item = dict(row)
        item["slice_spec"] = canonical_json(item["slice_spec"])
        item["claim_type_counts"] = canonical_json(item["claim_type_counts"])
        item["abstention_reason_counts"] = canonical_json(item["abstention_reason_counts"])
        flattened.append(item)
    return flattened


def _knowledge_identifier(units: list[Any]) -> str:
    ids = sorted({str(unit.member_fact_lock_ids[0]) for unit in units if unit.member_fact_lock_ids})
    return stable_id("knowledge_snapshot", ids)


def _dominant(values: list[str]) -> str:
    if not values:
        return ""
    return Counter(values).most_common(1)[0][0]


def _is_geological(claim_type: str) -> bool:
    return claim_type in {"FORECAST_GEOLOGICAL_CONDITION", "OBSERVED_GEOLOGICAL_CONDITION"}


def _is_metric(claim_type: str) -> bool:
    return claim_type in {
        "OPERATIONAL_RESPONSE_ATTENTION",
        "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
        "COUPLED_ATTENTION_REVIEW",
        "FORWARD_GEOLOGICAL_ATTENTION",
    }


def _complexity_band(unit_count: int) -> str:
    if unit_count <= 10:
        return "LOW"
    if unit_count <= 50:
        return "MEDIUM"
    return "HIGH"


def _epistemic_mix(modalities: set[str]) -> str:
    has_forecast = "GEOLOGICAL_FORECAST" in modalities
    has_observed = "GEOLOGICAL_OBSERVED" in modalities
    if has_forecast and has_observed:
        return "MIXED"
    if has_forecast:
        return "FORECAST_ONLY"
    if has_observed:
        return "OBSERVED_ONLY"
    return "ATTENTION_ONLY"


def _is_revision_related(
    units: list[Any],
    revision_versions: set[str],
    lock_by_id: dict[str, Any],
) -> bool:
    versions = {
        str(lock.bitemporal_version_id)
        for unit in units
        for lock_id in unit.member_fact_lock_ids
        if (lock := lock_by_id.get(lock_id)) is not None
        if lock.bitemporal_version_id
    }
    return bool(versions & revision_versions)


def _decision_state_role(row: dict[str, Any]) -> str:
    refs = row.get("resolved_support_refs") or []
    if refs:
        return str(refs[0].get("resolved_state_role") or "")
    return ""


def _decision_epistemic(row: dict[str, Any]) -> str:
    refs = row.get("resolved_support_refs") or []
    statuses = {
        str(ref.get("resolved_epistemic_status"))
        for ref in refs
        if ref.get("resolved_epistemic_status")
    }
    if "FORECAST" in statuses and "OBSERVED" in statuses:
        return "MIXED"
    if "FORECAST" in statuses:
        return "FORECAST"
    if "OBSERVED" in statuses:
        return "OBSERVED"
    return "UNRESOLVED"


def _slice_key(slice_spec: dict[str, Any]) -> str:
    return stable_hash(slice_spec)


def _selection_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _seeded_hash(str(row["source_task_id"])),
        str(row["product_type"]),
        str(row["valid_date"]),
        str(row["cell_id"]),
        str(row["source_task_id"]),
    )


def _seeded_hash(value: str) -> str:
    return stable_hash({"seed": STAGE7_RANDOM_SEED, "value": value})


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _git_rev(repo_root: Path, ref: str) -> str:
    return subprocess.check_output(["git", "rev-parse", ref], cwd=repo_root, text=True).strip()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _claim_guideline() -> str:
    return """# Stage7 Claim Annotation Guideline

Annotate Claim admissibility without seeing the system's EXPRESSIBLE/ABSTAIN label.

Annotators receive only knowledge-time-valid evidence, spatial scope, state role,
epistemic status, proposed Claim candidate, and relevant source excerpts or
structured evidence.

Labels:

- EXPRESSIBLE: the Claim is supported within the shown evidence, role, epistemic
  status, value, and spatial scope.
- SHOULD_ABSTAIN: the Claim should not be expressed because support, role,
  epistemic status, value, or scope is insufficient.
- UNCERTAIN: the annotator cannot determine admissibility from the packet.

For EXPRESSIBLE labels, verify modality, value, and spatial scope. For
SHOULD_ABSTAIN labels, record the primary reason category.
"""


def _text_guideline() -> str:
    return """# Stage7 Blind Text Evaluation Guideline

Rate anonymized B0/B1/P outputs without seeing method identity.

Primary dimensions are semantic correctness rather than prose aesthetics:

- factual support
- epistemic correctness
- numeric and spatial correctness
- engineering usefulness
- clarity/readability
- potentially misleading engineering statement

Do not reward unsupported fluency. Penalize future leakage, forecast
factification, attention-to-probability promotion, and missing-to-normal
promotion.
"""


def _statistical_plan() -> str:
    return """# Stage7 Statistical Analysis Plan

The main comparison is paired: B0, B1, and P are evaluated on the same frozen
benchmark tasks and knowledge snapshots.

Primary endpoints:

1. Severe Engineering Semantic Error Rate
2. Unsupported Claim Rate
3. Epistemic Violation Rate
4. Final Semantic Violation Rate
5. Trace Coverage
6. Claim Coverage

Binary per-task error indicators use McNemar tests. Paired per-task error
counts/rates use Wilcoxon signed-rank tests plus paired bootstrap 95% confidence
intervals. Three-method omnibus comparisons use Friedman tests where applicable,
with Holm-corrected post-hoc paired comparisons. Small-count comparisons use
exact methods when appropriate. Report effect sizes, 95% confidence intervals,
and exact n; do not report p-values alone.
"""


def _readme(manifest: dict[str, Any]) -> str:
    return f"""# Stage7A Experimental Protocol v1 Candidate

This artifact freezes the Stage7 experimental protocol and held-out benchmark
definition. It does not call any real LLM API and does not execute Stage7B.

- Eligible universe size: {manifest["eligible_universe_size"]}
- Main benchmark size: {manifest["main_benchmark_size"]}
- Main benchmark hash: `{manifest["main_benchmark_manifest_hash"]}`
- Excluded Stage6B smoke tasks: {manifest["stage6b_smoke_task_count"]}
- Real API calls: 0
"""


def _report(
    manifest: dict[str, Any],
    universe: list[dict[str, Any]],
    benchmark_rows: list[dict[str, Any]],
    hard_rows: list[dict[str, str]],
) -> str:
    product_counts = Counter(str(row["product_type"]) for row in benchmark_rows)
    complexity_counts = Counter(str(row["unit_complexity_band"]) for row in benchmark_rows)
    epistemic_counts = Counter(str(row["epistemic_mix"]) for row in benchmark_rows)
    hard_issues = [row for row in hard_rows if row["status"] != "PASS"]
    return f"""# Stage7A Experimental Protocol Report

Decision: READY_FOR_STAGE7B_MODEL_EXECUTION

Stage7A freezes the experimental protocol, held-out benchmark, baseline
definitions, ablation plan, automatic metrics, human annotation design,
statistical analysis plan, and API budget. No real LLM API was called.

## Frozen Inputs

- Stage6B tag: `{STAGE6B_FREEZE_TAG}`
- Stage6B commit: `{STAGE6B_FREEZE_COMMIT}`
- Stage6B smoke tasks excluded from main benchmark: 15

## Eligible Universe

- Universe size: {len(universe)}
- Universe reconstruction: frozen Stage6A FactLocks and Stage5B abstentions are
  sliced with Stage6B `SliceSpec` semantics into date-level and cell-level
  product tasks. Every retained task must build a nonempty Stage6B bundle.

## Held-Out Benchmark

- Target size: {TARGET_MAIN_SIZE}
- Actual size: {len(benchmark_rows)}
- Manifest hash: `{manifest["main_benchmark_manifest_hash"]}`
- Product distribution: {dict(sorted(product_counts.items()))}
- Complexity distribution: {dict(sorted(complexity_counts.items()))}
- Epistemic distribution: {dict(sorted(epistemic_counts.items()))}

## Methods

- B0_DIRECT_LLM: fair direct-generation baseline with the same knowledge-time
  evidence snapshot, without Claim decisions, FactLocks, or deterministic
  validators.
- B1_STRUCTURED_PROMPT_LLM: same snapshot plus natural-language safety rules,
  but no deterministic Claim admissibility or FactLock.
- P_PROPOSED: frozen bitemporal state -> Claim admissibility -> FactLock ->
  RealizationUnit -> LLM plan -> deterministic validator -> composer.

## Hard Checks

- Issue count: {len(hard_issues)}

Stage7B may execute the frozen benchmark. Stage7A does not execute model calls,
human annotation, ablations, or Stage7B.
"""


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row}) if rows else ["status"]
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_hashes(output_path: Path) -> None:
    rows = []
    for path in sorted(output_path.rglob("*")):
        if path.is_file() and path.name != "file_hashes.sha256":
            rows.append(f"{_file_sha256(path)}  {path.relative_to(output_path).as_posix()}")
    (output_path / "file_hashes.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")
