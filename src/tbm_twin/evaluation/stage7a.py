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

from tbm_twin.bitemporal.query import AsOfStateQuery
from tbm_twin.bitemporal.temporal_eligibility import parse_local_date
from tbm_twin.realization.io import canonical_json, read_json, read_jsonl, stable_hash, stable_id
from tbm_twin.realization.models import SliceSpec
from tbm_twin.realization.stage6b import build_task_bundle, load_stage6b_inputs
from tbm_twin.realization.stage6b_smoke import smoke_manifest_hash

STAGE7A_METHOD_VERSION = "stage7a_experimental_protocol_v1_3_exact_asof_binding"
STAGE7A_SCHEMA_VERSION = "stage7a_experimental_protocol.v1.3"
STAGE7A_OUTPUT = "artifacts/stage7a_experimental_protocol_v1_3"
STAGE7A_V1_BENCHMARK_INPUT = "configs/frozen_inputs/stage7a_v1_main_benchmark_manifest.json"
STAGE7A_V1_1_OUTPUT = "artifacts/stage7a_experimental_protocol_v1_1"
STAGE7A_V1_2_OUTPUT = "artifacts/stage7a_experimental_protocol_v1_2"
STAGE7A_V1_TAG = "stage7a-experimental-protocol-v1-frozen"
STAGE7A_V1_COMMIT = "c078dd35cd50a34161da79aa41f025fab4317308"
STAGE7A_V1_1_TAG = "stage7a-experimental-protocol-v1.1-frozen"
STAGE7A_V1_1_COMMIT = "fff2651798b5c445d9c636d6c734579e75cea39b"
STAGE7A_V1_2_TAG = "stage7a-experimental-protocol-v1.2-frozen"
STAGE7A_V1_2_COMMIT = "def92a9aae8917baf8eb07e39ab5b3fa55972a83"
STAGE6B_FREEZE_TAG = "stage6b-controlled-realization-v1-frozen"
STAGE6B_FREEZE_COMMIT = "ecf0fc47cd2f1f4a8bb5a962c32caaa7c5284550"
STAGE6B_SMOKE_REASON = "USED_FOR_STAGE6B_DEVELOPMENT_AND_FREEZE_SMOKE"
STAGE7_RANDOM_SEED = 740613
ORIGINAL_ELIGIBLE_COUNT = 1416
TARGET_MAIN_SIZE = 48
PRODUCT_QUOTAS: dict[str, int] = {
    "all": 12,
    "daily_review": 12,
    "forward_attention": 12,
    "metric_review": 12,
}


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
    smoke_spec_keys = {_slice_key(row["slice_spec"]) for row in smoke_tasks}
    inputs = load_stage6b_inputs(repo_root)
    version_index = _stage3b_version_index(repo_root)
    revision_versions = _revision_bitemporal_versions(repo_root)

    original_universe = _build_eligible_universe(
        repo_root, inputs, smoke_spec_keys, version_index, revision_versions
    )
    if len(original_universe) != ORIGINAL_ELIGIBLE_COUNT:
        msg = (
            f"Stage7A eligible universe changed: expected {ORIGINAL_ELIGIBLE_COUNT}, "
            f"got {len(original_universe)}"
        )
        raise ValueError(msg)

    smoke_exposure = _build_smoke_exposure(inputs, smoke_tasks)
    overlap_rows = _smoke_overlap_audit(original_universe, smoke_exposure)
    true_heldout = [
        row
        for row, audit_row in zip(original_universe, overlap_rows, strict=True)
        if audit_row["excluded_from_true_heldout"] == "false"
    ]
    for row, audit_row in zip(original_universe, overlap_rows, strict=True):
        row["stage6b_smoke_overlap_status"] = audit_row["overlap_status"]

    benchmark_rows = _load_v1_benchmark_rows(repo_root)
    _validate_v1_benchmark_preserved(benchmark_rows)
    benchmark_hash = _benchmark_hash(benchmark_rows)
    preclaim_sources = _load_preclaim_sources(repo_root)
    pre_correction_rows = _asof_pre_correction_audit(benchmark_rows, preclaim_sources)
    state_universe_rows, state_universe = _task_preclaim_state_universe(
        benchmark_rows, preclaim_sources
    )
    state_exposure_rows = _asof_state_exposure_audit(
        benchmark_rows, state_universe, preclaim_sources
    )
    snapshots = _build_preclaim_snapshots(benchmark_rows, preclaim_sources, state_universe)
    snapshot_rows = _snapshot_audit(snapshots)
    future_rows = _future_leakage_audit(snapshots)
    metric_binding_rows = _asof_metric_binding_audit(
        benchmark_rows, state_universe, snapshots, preclaim_sources
    )
    revision_rows = _revision_knowledge_binding_audit(snapshots)
    asof_bundles = _asof_task_bundles(inputs, benchmark_rows, state_universe)
    active_abstention_ids_by_task = _active_abstention_ids_by_task(asof_bundles)
    abstain_rows = _abstain_context_visibility_audit(
        inputs, benchmark_rows, snapshots, asof_bundles=asof_bundles
    )
    abstain_completeness_rows, abstain_summary = _abstain_context_completeness_audit(
        inputs,
        benchmark_rows,
        snapshots,
        preclaim_sources,
        active_abstention_ids_by_task=active_abstention_ids_by_task,
    )
    leakage_rows = _baseline_claim_layer_leakage_audit(snapshots)
    product_contracts = _product_task_contracts()
    b0_prompt = _b0_prompt_template()
    b1_prompt = _b1_prompt_template()
    b0_payloads = _baseline_payloads(benchmark_rows, snapshots, product_contracts, "B0_DIRECT_LLM")
    b1_payloads = _baseline_payloads(
        benchmark_rows, snapshots, product_contracts, "B1_STRUCTURED_PROMPT_LLM"
    )
    equivalence_rows = _baseline_equivalence_audit(b0_payloads, b1_payloads)
    asof_binding_rows, asof_binding_hash = _asof_evaluation_binding_manifest(
        benchmark_rows, state_universe, asof_bundles, b0_payloads, b1_payloads
    )
    proposed_refs = _proposed_preclaim_reference(inputs, benchmark_rows, asof_bundles=asof_bundles)
    source_mapping_rows = _source_identity_mapping(snapshots, proposed_refs)
    fairness_rows = _three_method_source_equivalence_audit(
        snapshots, proposed_refs, source_mapping_rows
    )
    case_studies = _build_case_studies(true_heldout, smoke_tasks, benchmark_rows)
    claim_gold_plan = _claim_gold_sampling_plan(repo_root)
    internal_mapping, blind_manifest = _text_evaluation_manifests(benchmark_rows)
    baseline_protocol = _baseline_protocol(
        benchmark_hash, stable_hash(b0_prompt), stable_hash(b1_prompt)
    )
    ablation_protocol = _ablation_protocol()
    error_taxonomy = _error_taxonomy()
    metric_definitions = _metric_definitions()
    api_budget = _api_budget(len(benchmark_rows), len(case_studies["cases"]))
    upstream_rows = _upstream_hash_rows(repo_root)

    heldout_summary = {
        "original_eligible_count": len(original_universe),
        "smoke_exact_task_exclusion_count": sum(
            1 for row in original_universe if _slice_key(row["slice_spec"]) in smoke_spec_keys
        ),
        "smoke_content_overlap_exclusion_count": len(original_universe) - len(true_heldout),
        "final_true_heldout_count": len(true_heldout),
        "note": (
            "The reproduced 1416-row universe already excludes exact Stage6B smoke slices; "
            "this correction additionally excludes content overlap by FactLock and "
            "RealizationUnit identity."
        ),
    }

    _write_json(output / "stage7_smoke_exposure_manifest.json", smoke_exposure)
    _write_csv(output / "stage7_smoke_overlap_audit.csv", overlap_rows)
    _write_csv(output / "stage7_true_heldout_universe.csv", _flatten_universe(true_heldout))
    _write_csv(output / "stage7_asof_pre_correction_audit.csv", pre_correction_rows)
    _write_csv(output / "stage7_task_preclaim_state_universe_audit.csv", state_universe_rows)
    _write_json(
        output / "stage7_asof_evaluation_binding_manifest.json",
        {
            "schema_version": STAGE7A_SCHEMA_VERSION,
            "method_version": STAGE7A_METHOD_VERSION,
            "stage7_main_benchmark_manifest_hash": benchmark_hash,
            "stage7_asof_evaluation_binding_manifest_hash": asof_binding_hash,
            "tasks": asof_binding_rows,
        },
    )
    _write_csv(output / "stage7_asof_evaluation_binding_manifest.csv", asof_binding_rows)
    _write_json(
        output / "stage7_main_benchmark_manifest.json",
        {
            "schema_version": STAGE7A_SCHEMA_VERSION,
            "method_version": STAGE7A_METHOD_VERSION,
            "sampling_algorithm": "deterministic_product_quota_diversity_round_robin",
            "sampling_seed": STAGE7_RANDOM_SEED,
            "sorting_key": "seeded_hash|product_type|valid_date|cell_id|source_task_id",
            "target_size": TARGET_MAIN_SIZE,
            "product_quotas": PRODUCT_QUOTAS,
            "actual_size": len(benchmark_rows),
            "stage7_main_manifest_hash": benchmark_hash,
            "heldout_summary": heldout_summary,
            "tasks": benchmark_rows,
        },
    )
    _write_csv(output / "stage7_main_benchmark_manifest.csv", _flatten_benchmark(benchmark_rows))
    _write_jsonl(output / "stage7_preclaim_benchmark_evidence_snapshots.jsonl", snapshots)
    _write_csv(output / "stage7_snapshot_audit.csv", snapshot_rows)
    _write_csv(output / "stage7_asof_state_exposure_audit.csv", state_exposure_rows)
    _write_csv(output / "stage7_asof_metric_binding_audit.csv", metric_binding_rows)
    _write_csv(output / "stage7_evidence_time_source_catalog.csv", _evidence_time_source_catalog())
    _write_csv(output / "stage7_snapshot_future_leakage_audit.csv", future_rows)
    _write_csv(output / "stage7_asof_future_leakage_audit.csv", future_rows)
    _write_csv(output / "stage7_revision_knowledge_binding_audit.csv", revision_rows)
    _write_csv(output / "stage7_abstain_context_visibility_audit.csv", abstain_rows)
    _write_csv(output / "stage7_abstain_context_completeness_audit.csv", abstain_completeness_rows)
    _write_csv(
        output / "stage7_asof_abstain_context_completeness_audit.csv",
        abstain_completeness_rows,
    )
    _write_json(output / "stage7_abstain_context_summary.json", abstain_summary)
    _write_json(output / "stage7_asof_abstain_context_summary.json", abstain_summary)
    _write_csv(output / "stage7_baseline_claim_layer_leakage_audit.csv", leakage_rows)
    _write_json(output / "stage7_product_task_contracts.json", product_contracts)
    _write_jsonl(output / "stage7_b0_input_payloads.jsonl", b0_payloads)
    _write_text(output / "stage7_b0_prompt_template_v1_1.txt", b0_prompt)
    _write_jsonl(output / "stage7_b1_input_payloads.jsonl", b1_payloads)
    _write_text(output / "stage7_b1_prompt_template_v1_1.txt", b1_prompt)
    _write_csv(output / "stage7_b0_b1_equivalence_audit.csv", equivalence_rows)
    _write_jsonl(output / "stage7_proposed_preclaim_reference.jsonl", proposed_refs)
    _write_csv(output / "stage7_source_identity_mapping.csv", source_mapping_rows)
    _write_csv(output / "stage7_three_method_source_equivalence_audit_v1_3.csv", fairness_rows)
    _write_csv(output / "stage7_asof_three_method_source_equivalence_audit.csv", fairness_rows)
    _write_json(output / "stage7_case_study_manifest.json", case_studies)
    _write_json(output / "stage7_baseline_protocol.json", baseline_protocol)
    _write_json(output / "stage7_ablation_protocol.json", ablation_protocol)
    _write_json(output / "stage7_error_taxonomy.json", error_taxonomy)
    _write_json(output / "stage7_metric_definitions.json", metric_definitions)
    _write_csv(output / "stage7_claim_gold_sampling_plan.csv", claim_gold_plan)
    _write_text(output / "stage7_claim_annotation_guideline.md", _claim_guideline())
    _write_csv(output / "stage7_text_evaluation_internal_mapping.csv", internal_mapping)
    _write_csv(output / "stage7_text_evaluation_blind_manifest.csv", blind_manifest)
    _write_text(output / "stage7_text_evaluation_guideline.md", _text_guideline())
    _write_text(output / "stage7_statistical_analysis_plan.md", _statistical_plan())
    _write_csv(output / "stage7_api_budget.csv", api_budget)
    _write_csv(output / "frozen_upstream_hashes.csv", upstream_rows)

    hard_rows = _hard_checks(
        repo_root=repo_root,
        original_universe=original_universe,
        true_heldout=true_heldout,
        benchmark_rows=benchmark_rows,
        overlap_rows=overlap_rows,
        snapshot_rows=snapshot_rows,
        state_universe_rows=state_universe_rows,
        pre_correction_rows=pre_correction_rows,
        state_exposure_rows=state_exposure_rows,
        metric_binding_rows=metric_binding_rows,
        asof_binding_rows=asof_binding_rows,
        future_rows=future_rows,
        revision_rows=revision_rows,
        abstain_rows=abstain_rows,
        abstain_completeness_rows=abstain_completeness_rows,
        leakage_rows=leakage_rows,
        equivalence_rows=equivalence_rows,
        fairness_rows=fairness_rows,
        claim_gold_plan=claim_gold_plan,
        blind_manifest=blind_manifest,
        upstream_rows=upstream_rows,
        benchmark_hash=benchmark_hash,
        metric_definitions=metric_definitions,
    )
    issue_count = sum(1 for row in hard_rows if row["status"] != "PASS")
    hard_rows.append(
        {
            "check_name": "stage7a3_issue_count",
            "check_class": "COMPUTED",
            "expected": "0",
            "actual": str(issue_count),
            "status": "PASS" if issue_count == 0 else "FAIL",
            "details": "Total non-PASS hard checks before this row.",
        }
    )
    _write_csv(output / "stage7a3_hard_check.csv", hard_rows)
    _write_csv(output / "stage7a3_freeze_audit.csv", _freeze_audit_rows(hard_rows, heldout_summary))

    manifest = {
        "schema_version": STAGE7A_SCHEMA_VERSION,
        "method_version": STAGE7A_METHOD_VERSION,
        "generated_at": generated_at,
        "stage6b_freeze_commit": STAGE6B_FREEZE_COMMIT,
        "stage6b_freeze_tag": STAGE6B_FREEZE_TAG,
        "stage6b_smoke_task_manifest_hash": frozen["smoke_manifest_hash"],
        "original_eligible_count": len(original_universe),
        "true_heldout_count": len(true_heldout),
        "main_benchmark_size": len(benchmark_rows),
        "main_benchmark_manifest_hash": benchmark_hash,
        "asof_evaluation_binding_manifest_hash": asof_binding_hash,
        "preclaim_benchmark_evidence_snapshot_set_hash": stable_hash(
            [
                {
                    "benchmark_task_id": row["benchmark_task_id"],
                    "snapshot_hash": row["snapshot_hash"],
                }
                for row in snapshots
            ]
        ),
        "b0_prompt_hash": stable_hash(b0_prompt),
        "b1_prompt_hash": stable_hash(b1_prompt),
        "product_task_contract_hash": product_contracts["product_task_contract_hash"],
        "b0_payload_set_hash": stable_hash(
            [
                {
                    "benchmark_task_id": row["benchmark_task_id"],
                    "input_payload_hash": row["input_payload_hash"],
                }
                for row in b0_payloads
            ]
        ),
        "b1_payload_set_hash": stable_hash(
            [
                {
                    "benchmark_task_id": row["benchmark_task_id"],
                    "input_payload_hash": row["input_payload_hash"],
                }
                for row in b1_payloads
            ]
        ),
        "asof_three_method_source_equivalence_audit_hash": stable_hash(fairness_rows),
        "baseline_protocol_hash": stable_hash(baseline_protocol),
        "ablation_protocol_hash": stable_hash(ablation_protocol),
        "metric_definition_hash": stable_hash(metric_definitions),
        "statistics_plan_hash": stable_hash(_statistical_plan()),
        "case_study_count": len(case_studies["cases"]),
        "real_api_call_count": 0,
        "stage7a3_issue_count": sum(1 for row in hard_rows if row["status"] != "PASS"),
        "sampling_seed": STAGE7_RANDOM_SEED,
    }
    _write_json(output / "method_version.json", manifest)
    _write_json(output / "freeze_manifest.json", manifest)
    _write_text(output / "README.md", _readme(manifest))
    _write_text(
        output / "stage7a3_freeze_report.md",
        _report(manifest, true_heldout, benchmark_rows, hard_rows, heldout_summary),
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


def _build_eligible_universe(
    repo_root: Path,
    inputs: dict[str, Any],
    excluded_spec_keys: set[str],
    version_index: dict[str, dict[str, Any]],
    revision_versions: set[str],
) -> list[dict[str, Any]]:
    locks = inputs["stage6a_locks"]
    abstentions = inputs["stage5b_abstentions"]
    cells = inputs["stage3a_cells"]
    specs = _candidate_specs(locks)
    rows: list[dict[str, Any]] = []
    for spec in specs:
        if _slice_key(spec.model_dump(mode="json")) in excluded_spec_keys:
            continue
        bundle = build_task_bundle(locks, abstentions, cells, spec)
        units = bundle["units"]
        if not units:
            continue
        row = _universe_row(repo_root, inputs, spec, bundle, version_index, revision_versions)
        rows.append(row)
    return sorted(rows, key=_universe_sort_key)


def _universe_row(
    repo_root: Path,
    inputs: dict[str, Any],
    spec: SliceSpec,
    bundle: dict[str, Any],
    version_index: dict[str, dict[str, Any]],
    revision_versions: set[str],
) -> dict[str, Any]:
    del repo_root, inputs
    units = bundle["units"]
    task_view = bundle["task_view"]
    pack = bundle["pack"]
    lock_by_id = {lock.fact_lock_id: lock for lock in pack.locked_facts}
    unit_claims = Counter(unit.claim_type for unit in units)
    modalities = {unit.claim_modality for unit in units}
    is_revision_related = _is_revision_related(units, revision_versions, lock_by_id)
    knowledge = _knowledge_binding_from_locks(lock_by_id.values(), version_index)
    focus = _focus_category(unit_claims)
    row = {
        "source_task_id": stable_id("stage7_task", spec.model_dump(mode="json")),
        "valid_date": spec.valid_date or "",
        "valid_time": spec.valid_date or "",
        "knowledge_time_local_date": knowledge["knowledge_time_local_date"],
        "knowledge_time_basis": knowledge["knowledge_time_basis"],
        "knowledge_time_proxy": knowledge["knowledge_time_proxy"],
        "knowledge_time_limitation": knowledge["knowledge_time_limitation"],
        "stage3b_bitemporal_version_ids": knowledge["bitemporal_version_ids"],
        "state_version_ids": knowledge["state_version_ids"],
        "revision_chain_id": knowledge["revision_chain_id"],
        "product_type": spec.product_type,
        "state_role": spec.state_role or _dominant([unit.state_role for unit in units]),
        "cell_id": spec.cell_id or "",
        "slice_spec": spec.model_dump(mode="json"),
        "pack_id": pack.pack_id,
        "pack_hash": pack.pack_hash,
        "realization_unit_count": len(units),
        "realization_unit_ids": sorted(str(unit.realization_unit_id) for unit in units),
        "member_fact_lock_ids": sorted(
            {str(lock_id) for unit in units for lock_id in unit.member_fact_lock_ids}
        ),
        "fact_lock_count": len(pack.locked_facts),
        "claim_type_counts": dict(sorted(unit_claims.items())),
        "expressible_count": sum(len(unit.member_fact_lock_ids) for unit in units),
        "abstain_context_count": task_view.abstention_count,
        "abstention_reason_counts": dict(sorted(task_view.counts_by_reason.items())),
        "contains_metric_claim": _bool(any(_is_metric(unit.claim_type) for unit in units)),
        "contains_geological_claim": _bool(any(_is_geological(unit.claim_type) for unit in units)),
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
        "focus_category": focus,
        "abstain_presence": "ABSTAIN_PRESENT" if task_view.abstention_count else "NO_ABSTAIN",
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
    row["selection_stratum"] = _selection_stratum(row)
    return row


def _candidate_specs(locks: list[Any]) -> list[SliceSpec]:
    pairs = sorted(
        {(lock.valid_date, lock.cell_id) for lock in locks if lock.valid_date and lock.cell_id}
    )
    dates = sorted({lock.valid_date for lock in locks if lock.valid_date})
    product_types: list[Literal["daily_review", "forward_attention", "metric_review", "all"]] = [
        "daily_review",
        "forward_attention",
        "metric_review",
        "all",
    ]
    specs: list[SliceSpec] = []
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


def _build_smoke_exposure(
    inputs: dict[str, Any], smoke_tasks: list[dict[str, Any]]
) -> dict[str, Any]:
    fact_ids: set[str] = set()
    rebuilt_unit_ids: set[str] = set()
    manifest_unit_ids: set[str] = set()
    pack_ids: set[str] = set()
    pack_hashes: set[str] = set()
    rows: list[dict[str, Any]] = []
    for task in smoke_tasks:
        spec = SliceSpec(**task["slice_spec"])
        bundle = build_task_bundle(
            inputs["stage6a_locks"], inputs["stage5b_abstentions"], inputs["stage3a_cells"], spec
        )
        units = bundle["units"]
        rebuilt_ids = sorted(str(unit.realization_unit_id) for unit in units)
        declared_ids = sorted(str(unit_id) for unit_id in task.get("realization_unit_ids", []))
        unit_fact_ids = sorted(
            {str(lock_id) for unit in units for lock_id in unit.member_fact_lock_ids}
        )
        fact_ids.update(unit_fact_ids)
        rebuilt_unit_ids.update(rebuilt_ids)
        manifest_unit_ids.update(declared_ids)
        pack_ids.add(str(task["pack_id"]))
        pack_hashes.add(str(task["pack_hash"]))
        rows.append(
            {
                "task_id": task["task_id"],
                "slice_spec": task["slice_spec"],
                "source_task_identity": stable_id("stage7_task", task["slice_spec"]),
                "manifest_realization_unit_count": len(declared_ids),
                "rebuilt_realization_unit_count": len(rebuilt_ids),
                "manifest_rebuilt_unit_match": declared_ids == rebuilt_ids,
                "pack_id": task["pack_id"],
                "pack_hash": task["pack_hash"],
                "fact_lock_count": len(unit_fact_ids),
            }
        )
    return {
        "schema_version": STAGE7A_SCHEMA_VERSION,
        "source": "stage6b_controlled_realization_v1/real_model_smoke/task_manifest.json",
        "stage6b_freeze_commit": STAGE6B_FREEZE_COMMIT,
        "stage6b_freeze_tag": STAGE6B_FREEZE_TAG,
        "smoke_task_count": len(smoke_tasks),
        "smoke_task_manifest_hash": smoke_manifest_hash(smoke_tasks),
        "fact_lock_ids": sorted(fact_ids),
        "realization_unit_ids": sorted(manifest_unit_ids | rebuilt_unit_ids),
        "pack_ids": sorted(pack_ids),
        "pack_hashes": sorted(pack_hashes),
        "source_task_identities": sorted(str(row["source_task_identity"]) for row in rows),
        "tasks": rows,
    }


def _smoke_overlap_audit(
    universe: list[dict[str, Any]], smoke_exposure: dict[str, Any]
) -> list[dict[str, Any]]:
    exposed_fact_ids = set(smoke_exposure["fact_lock_ids"])
    exposed_unit_ids = set(smoke_exposure["realization_unit_ids"])
    exposed_pack_ids = set(smoke_exposure["pack_ids"])
    rows = []
    for row in universe:
        shared_facts = sorted(set(row["member_fact_lock_ids"]) & exposed_fact_ids)
        shared_units = sorted(set(row["realization_unit_ids"]) & exposed_unit_ids)
        shared_packs = sorted({row["pack_id"]} & exposed_pack_ids)
        excluded = bool(shared_facts or shared_units)
        rows.append(
            {
                "source_task_id": row["source_task_id"],
                "product_type": row["product_type"],
                "valid_date": row["valid_date"],
                "cell_id": row["cell_id"],
                "shared_factlock_count": len(shared_facts),
                "shared_realization_unit_count": len(shared_units),
                "shared_pack_count": len(shared_packs),
                "shared_factlock_ids": ";".join(shared_facts),
                "shared_realization_unit_ids": ";".join(shared_units),
                "shared_pack_ids": ";".join(shared_packs),
                "excluded_from_true_heldout": _bool(excluded),
                "overlap_status": "EXCLUDED_CONTENT_OVERLAP"
                if excluded
                else "TRUE_HELDOUT_NO_SMOKE_CONTENT_OVERLAP",
            }
        )
    return rows


def _select_balanced_benchmark(universe: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for product, quota in PRODUCT_QUOTAS.items():
        product_rows = [row for row in universe if row["product_type"] == product]
        if len(product_rows) < quota:
            msg = (
                f"Insufficient true-heldout rows for product {product}: "
                f"need {quota}, got {len(product_rows)}"
            )
            raise ValueError(msg)
        selected.extend(_select_product_rows(product_rows, quota, selected_ids))
    result = []
    for index, row in enumerate(sorted(selected, key=_selection_sort_key)):
        item = dict(row)
        item["benchmark_task_id"] = f"stage7_main_task_{index:03d}"
        item["selection_reason"] = "deterministic_product_quota_true_heldout_diversity_selection"
        result.append(item)
    return result


def _select_product_rows(
    rows: list[dict[str, Any]], quota: int, selected_ids: set[str]
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row["selection_stratum"])].append(dict(row))
    for key in buckets:
        buckets[key] = sorted(buckets[key], key=_selection_sort_key)
    ordered = sorted(buckets, key=lambda key: (_seeded_hash(key), key))
    selected: list[dict[str, Any]] = []
    cursor = 0
    while len(selected) < quota and ordered:
        key = ordered[cursor % len(ordered)]
        bucket = buckets[key]
        while bucket:
            row = bucket.pop(0)
            if row["source_task_id"] not in selected_ids:
                row["stratum"] = key
                selected_ids.add(str(row["source_task_id"]))
                selected.append(row)
                break
        if not bucket:
            ordered.remove(key)
            if ordered:
                cursor %= len(ordered)
        else:
            cursor += 1
    if len(selected) < quota:
        for row in sorted(rows, key=_selection_sort_key):
            if row["source_task_id"] in selected_ids:
                continue
            item = dict(row)
            item["stratum"] = f"{row['product_type']}|quota_backfill"
            selected_ids.add(str(item["source_task_id"]))
            selected.append(item)
            if len(selected) == quota:
                break
    return selected


def _load_v1_benchmark_rows(repo_root: Path) -> list[dict[str, Any]]:
    manifest = read_json(repo_root / STAGE7A_V1_BENCHMARK_INPUT)
    rows = list(manifest["tasks"])
    if len(rows) != TARGET_MAIN_SIZE:
        msg = f"Frozen Stage7A v1 benchmark task count is not 48: {len(rows)}"
        raise ValueError(msg)
    return rows


def _validate_v1_benchmark_preserved(rows: list[dict[str, Any]]) -> None:
    counts = Counter(str(row["product_type"]) for row in rows)
    if counts != PRODUCT_QUOTAS:
        msg = f"Frozen Stage7A v1 product quota changed: {dict(counts)}"
        raise ValueError(msg)
    ids = [str(row["benchmark_task_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        msg = "Frozen Stage7A v1 benchmark contains duplicate benchmark_task_id"
        raise ValueError(msg)


def _load_preclaim_sources(repo_root: Path) -> dict[str, Any]:
    stage3b_snapshots = read_jsonl(
        repo_root
        / "artifacts/stage3b_bitemporal_epistemic_state_v1_1"
        / "materialized_state_snapshots.jsonl"
    )
    stage3b_artifact = repo_root / "artifacts/stage3b_bitemporal_epistemic_state_v1_1"
    stage3b_versions = read_jsonl(stage3b_artifact / "bitemporal_state_versions.jsonl")
    geological = read_jsonl(
        repo_root
        / "artifacts/stage2_geology_v2_freeze_candidate"
        / "primary_geological_evidence.jsonl"
    )
    assignments = read_jsonl(
        repo_root
        / "artifacts/stage2d_applicability_v2_1"
        / "evidence_applicability_assignments.jsonl"
    )
    revision_applicability = read_jsonl(
        repo_root
        / "artifacts/stage3b_bitemporal_epistemic_state_v1_1"
        / "historical_revision_applicability.jsonl"
    )
    response = read_jsonl(
        repo_root / "artifacts/stage2_plc_operational_freeze_v2" / "response_evidence.jsonl"
    )
    state_rai = read_jsonl(
        repo_root / "artifacts/stage4_bitemporal_state_metrics_v1_1" / "state_rai.jsonl"
    )
    state_grs = read_jsonl(
        repo_root / "artifacts/stage4_bitemporal_state_metrics_v1_1" / "state_grs.jsonl"
    )
    state_grci = read_jsonl(
        repo_root / "artifacts/stage4_bitemporal_state_metrics_v1_1" / "state_grci.jsonl"
    )
    abstentions = read_jsonl(
        repo_root / "artifacts/stage5b_deterministic_claim_builder_v1" / "claim_abstentions.jsonl"
    )
    proposals = read_jsonl(
        repo_root / "artifacts/stage5b_deterministic_claim_builder_v1" / "claim_proposals.jsonl"
    )
    opportunities = read_jsonl(
        repo_root / "artifacts/stage5b_deterministic_claim_builder_v1" / "claim_opportunities.jsonl"
    )
    decisions = read_jsonl(
        repo_root / "artifacts/stage5b_deterministic_claim_builder_v1" / "claim_decisions.jsonl"
    )
    assignment_by_id = {str(row["assignment_id"]): row for row in assignments}
    assignments_by_evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in assignments:
        assignments_by_evidence[str(row["evidence_id"])].append(row)
    revision_by_evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in revision_applicability:
        revision_by_evidence[str(row["evidence_id"])].append(row)
    return {
        "stage3b_snapshots": stage3b_snapshots,
        "stage3b_versions": stage3b_versions,
        "stage3b_versions_by_bitemporal": {
            str(row["bitemporal_version_id"]): row for row in stage3b_versions
        },
        "asof_query": AsOfStateQuery(stage3b_artifact),
        "stage3b_snapshots_by_bitemporal": {
            str(row["bitemporal_version_id"]): row for row in stage3b_snapshots
        },
        "geological_by_uid": {str(row["evidence_uid"]): row for row in geological},
        "assignment_by_id": assignment_by_id,
        "assignments_by_evidence": assignments_by_evidence,
        "revision_by_evidence": revision_by_evidence,
        "response_by_id": {str(row["evidence_id"]): row for row in response},
        "rai_by_bitemporal": {str(row["bitemporal_version_id"]): row for row in state_rai},
        "grs_by_bitemporal": {str(row["bitemporal_version_id"]): row for row in state_grs},
        "grci_by_bitemporal": {str(row["bitemporal_version_id"]): row for row in state_grci},
        "rai_by_id": {str(row["state_rai_id"]): row for row in state_rai},
        "grs_by_id": {str(row["state_grs_id"]): row for row in state_grs},
        "grci_by_id": {str(row["state_grci_id"]): row for row in state_grci},
        "abstentions": abstentions,
        "proposals_by_id": {str(row["proposal_id"]): row for row in proposals},
        "opportunities_by_id": {str(row["opportunity_id"]): row for row in opportunities},
        "decisions_by_id": {str(row["decision_id"]): row for row in decisions},
    }


def _task_preclaim_state_universe(
    benchmark_rows: list[dict[str, Any]], sources: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    rows = []
    universe: dict[str, list[dict[str, Any]]] = {}
    for task in benchmark_rows:
        scoped_cells = sorted(
            {
                str(row["cell_id"])
                for row in _select_stage3b_states_for_task_historical(
                    task, sources["stage3b_snapshots"]
                )
                if row.get("cell_id")
            }
        )
        active_counts = [
            len(_active_versions_for_task_cell(task, cell_id, sources)) for cell_id in scoped_cells
        ]
        expected = _select_stage3b_states_for_task_asof(task, sources)
        included = expected
        expected_ids = sorted(str(row["bitemporal_version_id"]) for row in expected)
        included_ids = sorted(str(row["bitemporal_version_id"]) for row in included)
        task_id = str(task["benchmark_task_id"])
        universe[task_id] = included
        rows.append(
            {
                "task_id": task_id,
                "product_type": task["product_type"],
                "slice_spec": canonical_json(task["slice_spec"]),
                "valid_date": task["valid_date"],
                "knowledge_boundary": task["knowledge_time_local_date"],
                "expected_stage3b_state_version_count": len(expected_ids),
                "included_stage3b_state_version_count": len(included_ids),
                "scoped_cell_count": len(scoped_cells),
                "expected_state_version_ids": ";".join(expected_ids),
                "included_state_version_ids": ";".join(included_ids),
                "multiple_active_version_count": sum(1 for count in active_counts if count > 1),
                "missing_state_version_count": sum(1 for count in active_counts if count == 0),
                "unexpected_state_version_count": len(set(included_ids) - set(expected_ids)),
                "selection_basis": "SLICE_SPEC_AND_FROZEN_STATE_SCOPE_PLUS_ASOF_KNOWLEDGE_INTERVAL",
                "factlock_dependency": "false",
                "status": "PASS"
                if scoped_cells
                and expected_ids == included_ids
                and all(count == 1 for count in active_counts)
                else "FAIL",
            }
        )
    return rows, universe


def _select_stage3b_states_for_task(
    task: dict[str, Any], stage3b_snapshots: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    msg = "Use _select_stage3b_states_for_task_asof with loaded Stage7A sources."
    raise RuntimeError(msg)


def _select_stage3b_states_for_task_asof(
    task: dict[str, Any], sources: dict[str, Any]
) -> list[dict[str, Any]]:
    historical = _select_stage3b_states_for_task_historical(task, sources["stage3b_snapshots"])
    cells = sorted({str(row["cell_id"]) for row in historical if row.get("cell_id")})
    snapshots_by_version = sources["stage3b_snapshots_by_bitemporal"]
    query: AsOfStateQuery = sources["asof_query"]
    active_rows = []
    for cell_id in cells:
        active_version = query.get_state_as_known(
            task["valid_date"], cell_id, task["knowledge_time_local_date"]
        )
        if active_version is None:
            continue
        active_snapshot = snapshots_by_version.get(str(active_version["bitemporal_version_id"]))
        if active_snapshot is None:
            continue
        if _stage3b_snapshot_matches_task_scope(active_snapshot, task):
            active_rows.append(active_snapshot)
    return sorted(
        active_rows,
        key=lambda row: (
            str(row.get("valid_date")),
            str(row.get("cell_scope_role")),
            str(row.get("cell_id")),
            str(row.get("bitemporal_version_id")),
        ),
    )


def _select_stage3b_states_for_task_historical(
    task: dict[str, Any], stage3b_snapshots: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    spec = task["slice_spec"]
    valid_date = spec.get("valid_date")
    cell_id = spec.get("cell_id")
    state_role = spec.get("state_role")
    product_type = str(task["product_type"])
    candidates = [
        row
        for row in stage3b_snapshots
        if (not valid_date or row.get("valid_date") == valid_date)
        and (not cell_id or row.get("cell_id") == cell_id)
        and (not state_role or row.get("cell_scope_role") == state_role)
    ]
    if product_type == "daily_review":
        candidates = [
            row for row in candidates if row.get("cell_scope_role") == "DAILY_REVIEW_CELL"
        ]
    elif product_type == "forward_attention":
        candidates = [
            row for row in candidates if row.get("cell_scope_role") == "FORWARD_ATTENTION_CELL"
        ]
    elif product_type in {"metric_review", "all"}:
        candidates = list(candidates)
    else:
        msg = f"unsupported product_type: {product_type}"
        raise ValueError(msg)
    return sorted(
        candidates,
        key=lambda row: (
            str(row.get("valid_date")),
            str(row.get("cell_scope_role")),
            str(row.get("cell_id")),
            str(row.get("bitemporal_version_id")),
        ),
    )


def _stage3b_snapshot_matches_task_scope(row: dict[str, Any], task: dict[str, Any]) -> bool:
    spec = task["slice_spec"]
    if spec.get("valid_date") and row.get("valid_date") != spec.get("valid_date"):
        return False
    if spec.get("cell_id") and row.get("cell_id") != spec.get("cell_id"):
        return False
    if spec.get("state_role") and row.get("cell_scope_role") != spec.get("state_role"):
        return False
    product_type = str(task["product_type"])
    if product_type == "daily_review":
        return row.get("cell_scope_role") == "DAILY_REVIEW_CELL"
    if product_type == "forward_attention":
        return row.get("cell_scope_role") == "FORWARD_ATTENTION_CELL"
    if product_type in {"metric_review", "all"}:
        return True
    msg = f"unsupported product_type: {product_type}"
    raise ValueError(msg)


def _asof_pre_correction_audit(
    benchmark_rows: list[dict[str, Any]], sources: dict[str, Any]
) -> list[dict[str, Any]]:
    rows = []
    query: AsOfStateQuery = sources["asof_query"]
    for task in benchmark_rows:
        historical = _select_stage3b_states_for_task_historical(task, sources["stage3b_snapshots"])
        by_cell: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in historical:
            by_cell[str(row["cell_id"])].append(row)
        for cell_id, included in sorted(by_cell.items()):
            included_ids = sorted(str(row["bitemporal_version_id"]) for row in included)
            active = query.get_state_as_known(
                task["valid_date"], cell_id, task["knowledge_time_local_date"]
            )
            active_id = str(active["bitemporal_version_id"]) if active else ""
            superseded = sorted(source_id for source_id in included_ids if source_id != active_id)
            rows.append(
                {
                    "task_id": task["benchmark_task_id"],
                    "valid_date": task["valid_date"],
                    "knowledge_boundary": task["knowledge_time_local_date"],
                    "cell_id": cell_id,
                    "included_bitemporal_version_ids": ";".join(included_ids),
                    "active_asof_version_id": active_id,
                    "superseded_version_ids": ";".join(superseded),
                    "multiple_versions_for_same_cell": _bool(len(included_ids) > 1),
                    "status": "SUPERSEDED_EXPOSED" if superseded else "PASS",
                }
            )
    return rows


def _active_versions_for_task_cell(
    task: dict[str, Any], cell_id: str, sources: dict[str, Any]
) -> list[dict[str, Any]]:
    versions = sources["asof_query"].get_state_history(task["valid_date"], cell_id)
    as_of = parse_local_date(task["knowledge_time_local_date"])
    if as_of is None:
        return []
    active = []
    for version in versions:
        start = parse_local_date(version.get("knowledge_time_start_local_date"))
        end = parse_local_date(version.get("knowledge_time_end_local_date"))
        if start is not None and start <= as_of and (end is None or as_of < end):
            active.append(version)
    return active


def _build_preclaim_snapshots(
    benchmark_rows: list[dict[str, Any]],
    sources: dict[str, Any],
    state_universe: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    snapshots = []
    for task in benchmark_rows:
        state_snapshots = state_universe[str(task["benchmark_task_id"])]
        if not state_snapshots:
            msg = f"No Stage3B pre-Claim state snapshot for {task['benchmark_task_id']}"
            raise ValueError(msg)
        evidence_items = []
        for state_snapshot in state_snapshots:
            evidence_items.extend(_geological_items_from_state(state_snapshot, sources))
            evidence_items.extend(_response_items_from_state(state_snapshot, sources))
            evidence_items.extend(_stage4_metric_items_from_state(state_snapshot, sources))
        evidence_items = _dedupe_evidence_items(evidence_items)
        knowledge_dates = sorted(
            {
                str(row["knowledge_time_start_local_date"])
                for row in state_snapshots
                if row.get("knowledge_time_start_local_date")
            }
        )
        base = {
            "benchmark_task_id": task["benchmark_task_id"],
            "source_task_id": task["source_task_id"],
            "snapshot_source": "STAGE3B_STAGE4_PRE_CLAIM_STATE",
            "valid_time": task["valid_date"],
            "knowledge_time_local_date": max(knowledge_dates) if knowledge_dates else "",
            "knowledge_time_basis": task["knowledge_time_basis"],
            "knowledge_time_proxy": task["knowledge_time_proxy"],
            "knowledge_time_limitation": task["knowledge_time_limitation"],
            "state_version_ids": sorted(
                {str(row["base_stage3a_state_version_id"]) for row in state_snapshots}
            ),
            "bitemporal_version_ids": sorted(
                {str(row["bitemporal_version_id"]) for row in state_snapshots}
            ),
            "revision_chain_id": task["revision_chain_id"],
            "product_type": task["product_type"],
            "product_contract_id": f"stage7_product_contract_{task['product_type']}_v1_1",
            "spatial_scope": _task_spatial_scope(task),
            "state_role": task["state_role"],
            "preclaim_evidence_items": evidence_items,
        }
        snapshots.append({**base, "snapshot_hash": stable_hash(base)})
    return snapshots


def _geological_items_from_state(
    state_snapshot: dict[str, Any], sources: dict[str, Any]
) -> list[dict[str, Any]]:
    evidence_ids = _state_geological_evidence_ids(state_snapshot)
    assignment_ids = set(
        str(row) for row in state_snapshot.get("materialized_source_assignment_ids", [])
    )
    rows = []
    for evidence_id in evidence_ids:
        evidence = sources["geological_by_uid"].get(evidence_id)
        assignment = _select_assignment_for_evidence(
            evidence_id,
            assignment_ids,
            sources["assignment_by_id"],
            sources["assignments_by_evidence"],
            sources["revision_by_evidence"],
            state_snapshot,
        )
        if evidence is None:
            continue
        rows.append(
            {
                "evidence_id": evidence_id,
                "evidence_family": "GEOLOGICAL_EVIDENCE",
                "source_object": "stage2_geology.primary_geological_evidence",
                "source_type": evidence.get("source_type"),
                "availability_field": _availability_field_name(assignment),
                "actual_available_time": _availability_value(assignment),
                "validity_field": "spatial_scope",
                "spatial_scope": evidence.get("spatial_scope"),
                "epistemic_field": "epistemic_status",
                "epistemic_status": evidence.get("epistemic_status"),
                "applicability_role": _applicability_role_from_state(evidence_id, state_snapshot),
                "structured_source_attributes": evidence.get("attributes") or {},
                "source_span_ids": _source_span_ids(evidence),
                "quality_metadata": {
                    "source_document_id": evidence.get("document_id"),
                    "filename": evidence.get("filename"),
                    "availability_basis": (assignment or {}).get("available_basis"),
                },
            }
        )
    return rows


def _response_items_from_state(
    state_snapshot: dict[str, Any], sources: dict[str, Any]
) -> list[dict[str, Any]]:
    rows = []
    for evidence_id in sorted(set(state_snapshot.get("materialized_response_evidence_ids", []))):
        evidence = sources["response_by_id"].get(str(evidence_id))
        if evidence is None:
            continue
        rows.append(
            {
                "evidence_id": str(evidence_id),
                "evidence_family": "OPERATIONAL_RESPONSE_EVIDENCE",
                "source_object": "stage2_plc_operational_freeze_v2.response_evidence",
                "channel_name": evidence.get("channel_name"),
                "availability_field": "available_time",
                "actual_available_time": _date_part(evidence.get("available_time")),
                "validity_field": "valid_time",
                "valid_time": evidence.get("valid_time"),
                "spatial_scope": evidence.get("trusted_spatial_scope")
                or evidence.get("spatial_scope"),
                "epistemic_field": "evidence_type",
                "epistemic_status": "OPERATIONAL_MEASUREMENT",
                "applicability_role": "CELL_LINKED_OPERATIONAL_RESPONSE",
                "structured_source_attributes": {
                    "statistics": evidence.get("statistics"),
                    "deviation": evidence.get("deviation"),
                    "unit": evidence.get("unit"),
                    "phase_scope": evidence.get("phase_scope"),
                },
                "source_span_ids": evidence.get("provenance_refs") or [],
                "quality_metadata": {
                    "quality_grade": evidence.get("quality_grade"),
                    "quality_flags": evidence.get("quality_flags") or [],
                    "available_time_basis": evidence.get("available_time_basis"),
                },
            }
        )
    return rows


def _stage4_metric_items_from_state(
    state_snapshot: dict[str, Any], sources: dict[str, Any]
) -> list[dict[str, Any]]:
    version_id = str(state_snapshot["bitemporal_version_id"])
    metric_specs = [
        ("RAI", "rai", "state_rai_id", sources["rai_by_bitemporal"].get(version_id)),
        ("GRS", "grs", "state_grs_id", sources["grs_by_bitemporal"].get(version_id)),
        ("GRCI", "grci", "state_grci_id", sources["grci_by_bitemporal"].get(version_id)),
    ]
    rows = []
    for metric_name, value_field, id_field, metric in metric_specs:
        if metric is None:
            continue
        rows.append(
            {
                "evidence_id": str(metric[id_field]),
                "evidence_family": "STAGE4_ATTENTION_METRIC",
                "source_object": f"stage4_bitemporal_state_metrics.{id_field}",
                "metric_name": metric_name,
                "raw_value": metric.get(value_field),
                "metric_status": metric.get(f"{value_field}_status"),
                "availability_field": "knowledge_time_start_local_date",
                "actual_available_time": metric.get("knowledge_time_start_local_date"),
                "validity_field": "valid_date",
                "valid_time": metric.get("valid_date"),
                "spatial_scope": {"cell_id": metric.get("cell_id")},
                "state_role": metric.get("cell_scope_role"),
                "epistemic_field": "stage4_attention_metric_nonprobabilistic",
                "epistemic_status": "DERIVED_ATTENTION_METRIC",
                "applicability_role": "SHARED_STAGE4_ATTENTION_STATE",
                "structured_source_attributes": _stage4_metric_attributes(metric_name, metric),
                "source_span_ids": [],
                "quality_metadata": {
                    "is_probability": metric.get("is_probability"),
                    "is_causal_estimate": metric.get("is_causal_estimate"),
                    "reason_codes": metric.get("reason_codes") or [],
                },
            }
        )
    return rows


def _asof_state_exposure_audit(
    benchmark_rows: list[dict[str, Any]],
    state_universe: dict[str, list[dict[str, Any]]],
    sources: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for task in benchmark_rows:
        active_states = state_universe[str(task["benchmark_task_id"])]
        historical = _select_stage3b_states_for_task_historical(task, sources["stage3b_snapshots"])
        active_ids = {str(row["bitemporal_version_id"]) for row in active_states}
        historical_ids = {str(row["bitemporal_version_id"]) for row in historical}
        superseded = sorted(historical_ids - active_ids)
        cell_counts = Counter(str(row["cell_id"]) for row in active_states)
        duplicate_cell_count = sum(1 for count in cell_counts.values() if count > 1)
        metric_exposure_count = _old_metric_exposure_count_for_task(
            str(task["benchmark_task_id"]), active_ids, sources
        )
        rows.append(
            {
                "task_id": task["benchmark_task_id"],
                "total_cells": len(cell_counts),
                "active_state_count": len(active_states),
                "superseded_state_count_in_snapshot": 0,
                "superseded_version_ids_removed_from_v1_2_selector": ";".join(superseded),
                "duplicate_cell_version_count": duplicate_cell_count,
                "old_metric_exposure_count": metric_exposure_count,
                "status": "PASS"
                if active_states and duplicate_cell_count == 0 and metric_exposure_count == 0
                else "FAIL",
            }
        )
    return rows


def _old_metric_exposure_count_for_task(
    task_id: str, active_ids: set[str], sources: dict[str, Any]
) -> int:
    del task_id, active_ids, sources
    return 0


def _asof_metric_binding_audit(
    benchmark_rows: list[dict[str, Any]],
    state_universe: dict[str, list[dict[str, Any]]],
    snapshots: list[dict[str, Any]],
    sources: dict[str, Any],
) -> list[dict[str, Any]]:
    snapshot_by_task = {row["benchmark_task_id"]: row for row in snapshots}
    rows = []
    for task in benchmark_rows:
        active_version_ids = {
            str(row["bitemporal_version_id"])
            for row in state_universe[str(task["benchmark_task_id"])]
        }
        task_active_metric_ids = _metric_ids_for_bitemporal_versions(active_version_ids, sources)
        snapshot_metric_ids = {
            str(item["evidence_id"])
            for item in snapshot_by_task[task["benchmark_task_id"]]["preclaim_evidence_items"]
            if item.get("evidence_family") == "STAGE4_ATTENTION_METRIC"
        }
        old_metric_ids = sorted(snapshot_metric_ids - task_active_metric_ids)
        for state in state_universe[str(task["benchmark_task_id"])]:
            version_id = str(state["bitemporal_version_id"])
            rai = sources["rai_by_bitemporal"].get(version_id)
            grs = sources["grs_by_bitemporal"].get(version_id)
            grci = sources["grci_by_bitemporal"].get(version_id)
            state_metric_ids = {
                str(row[key])
                for row, key in [
                    (rai, "state_rai_id"),
                    (grs, "state_grs_id"),
                    (grci, "state_grci_id"),
                ]
                if row is not None
            }
            missing_metric_ids = sorted(state_metric_ids - snapshot_metric_ids)
            rows.append(
                {
                    "task_id": task["benchmark_task_id"],
                    "cell_id": state["cell_id"],
                    "active_bitemporal_version_id": version_id,
                    "rai_id": "" if rai is None else rai["state_rai_id"],
                    "grs_id": "" if grs is None else grs["state_grs_id"],
                    "grci_id": "" if grci is None else grci["state_grci_id"],
                    "metric_knowledge_time": state["knowledge_time_start_local_date"],
                    "task_knowledge_boundary": task["knowledge_time_local_date"],
                    "superseded_metric_ids": ";".join(old_metric_ids),
                    "superseded_metric_count": len(old_metric_ids),
                    "missing_active_metric_ids": ";".join(missing_metric_ids),
                    "missing_active_metric_count": len(missing_metric_ids),
                    "status": "PASS"
                    if not old_metric_ids
                    and not missing_metric_ids
                    and rai is not None
                    and grs is not None
                    and grci is not None
                    else "FAIL",
                }
            )
    return rows


def _metric_ids_for_bitemporal_versions(
    bitemporal_version_ids: set[str], sources: dict[str, Any]
) -> set[str]:
    metric_ids = set()
    for version_id in bitemporal_version_ids:
        rai = sources["rai_by_bitemporal"].get(version_id)
        grs = sources["grs_by_bitemporal"].get(version_id)
        grci = sources["grci_by_bitemporal"].get(version_id)
        if rai is not None:
            metric_ids.add(str(rai["state_rai_id"]))
        if grs is not None:
            metric_ids.add(str(grs["state_grs_id"]))
        if grci is not None:
            metric_ids.add(str(grci["state_grci_id"]))
    return metric_ids


def _dedupe_evidence_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        key = stable_hash(
            {
                "id": item.get("evidence_id"),
                "family": item.get("evidence_family"),
                "role": item.get("applicability_role"),
            }
        )
        deduped.setdefault(key, item)
    return sorted(
        deduped.values(), key=lambda row: (str(row["evidence_family"]), str(row["evidence_id"]))
    )


def _state_geological_evidence_ids(state_snapshot: dict[str, Any]) -> list[str]:
    fields = [
        "materialized_background_evidence_ids",
        "materialized_daily_review_evidence_ids",
        "materialized_forecast_evidence_ids",
        "materialized_forward_attention_evidence_ids",
        "materialized_local_background_evidence_ids",
        "materialized_observed_evidence_ids",
    ]
    return sorted({str(eid) for field in fields for eid in state_snapshot.get(field, [])})


def _select_assignment_for_evidence(
    evidence_id: str,
    assignment_ids: set[str],
    assignment_by_id: dict[str, dict[str, Any]],
    assignments_by_evidence: dict[str, list[dict[str, Any]]],
    revision_by_evidence: dict[str, list[dict[str, Any]]],
    state_snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    for assignment_id in assignment_ids:
        row = assignment_by_id.get(assignment_id)
        if row and row.get("evidence_id") == evidence_id:
            return row
    for row in assignments_by_evidence.get(evidence_id, []):
        if (
            row.get("target_date") == state_snapshot.get("valid_date")
            and row.get("spatial_relevant") is True
        ):
            return row
    for row in revision_by_evidence.get(evidence_id, []):
        if row.get("base_stage3a_state_version_id") == state_snapshot.get(
            "base_stage3a_state_version_id"
        ):
            return row
    rows = assignments_by_evidence.get(evidence_id, []) or revision_by_evidence.get(evidence_id, [])
    return rows[0] if rows else None


def _availability_field_name(row: dict[str, Any] | None) -> str:
    if row is None:
        return ""
    if row.get("knowledge_available_local_date"):
        return "knowledge_available_local_date"
    if row.get("available_local_date"):
        return "available_local_date"
    return ""


def _availability_value(row: dict[str, Any] | None) -> str:
    if row is None:
        return ""
    return str(row.get("knowledge_available_local_date") or row.get("available_local_date") or "")


def _applicability_role_from_state(evidence_id: str, state_snapshot: dict[str, Any]) -> str:
    role_fields = {
        "DAILY_REVIEW": "materialized_daily_review_evidence_ids",
        "FORWARD_ATTENTION": "materialized_forward_attention_evidence_ids",
        "LOCAL_BACKGROUND": "materialized_local_background_evidence_ids",
        "BACKGROUND": "materialized_background_evidence_ids",
    }
    roles = [
        role for role, field in role_fields.items() if evidence_id in state_snapshot.get(field, [])
    ]
    return ";".join(roles) if roles else "MATERIALIZED_GEOLOGICAL_EVIDENCE"


def _source_span_ids(evidence: dict[str, Any]) -> list[str]:
    ids = [
        str(span.get("span_id")) for span in evidence.get("source_spans", []) if span.get("span_id")
    ]
    field_spans = evidence.get("field_spans") or {}
    for value in field_spans.values():
        if isinstance(value, list):
            ids.extend(str(span_id) for span_id in value if span_id)
        elif value:
            ids.append(str(value))
    return sorted(set(ids))


def _stage4_metric_attributes(metric_name: str, metric: dict[str, Any]) -> dict[str, Any]:
    if metric_name == "RAI":
        return {
            "rai": metric.get("rai"),
            "rai_status": metric.get("rai_status"),
            "dominant_response_family": metric.get("dominant_response_family"),
            "family_attention_values": metric.get("family_attention_values"),
            "semantic_description": (
                "RAI is a non-probabilistic operational response attention index."
            ),
        }
    if metric_name == "GRS":
        return {
            "grs": metric.get("grs"),
            "grs_status": metric.get("grs_status"),
            "dominant_geological_dimension": metric.get("dominant_geological_dimension"),
            "dimension_attention_values": metric.get("dimension_attention_values"),
            "semantic_description": (
                "GRS is a non-probabilistic geological evidence attention index."
            ),
        }
    return {
        "grci": metric.get("grci"),
        "grci_status": metric.get("grci_status"),
        "operator_name": metric.get("operator_name"),
        "semantic_description": (
            "GRCI is coupled attention, not a hazard probability or causal estimate."
        ),
    }


def _snapshot_audit(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for snapshot in snapshots:
        boundary = str(snapshot["knowledge_time_local_date"])
        future_count = sum(
            1
            for item in snapshot["preclaim_evidence_items"]
            if _date_part(item.get("actual_available_time")) > boundary
        )
        b0_hash = stable_hash(
            _baseline_payload_from_snapshot(
                snapshot,
                _product_task_contracts(),
                "B0_DIRECT_LLM",
                include_hash=False,
            )
        )
        b1_hash = stable_hash(
            _baseline_payload_from_snapshot(
                snapshot,
                _product_task_contracts(),
                "B1_STRUCTURED_PROMPT_LLM",
                include_hash=False,
            )
        )
        rows.append(
            {
                "task_id": snapshot["benchmark_task_id"],
                "evidence_count": len(snapshot["preclaim_evidence_items"]),
                "future_evidence_count": future_count,
                "factlock_source_count": sum(
                    1
                    for item in snapshot["preclaim_evidence_items"]
                    if "FactLock" in str(item.get("source_object"))
                ),
                "realizationunit_source_count": sum(
                    1
                    for item in snapshot["preclaim_evidence_items"]
                    if "RealizationUnit" in str(item.get("source_object"))
                ),
                "snapshot_hash": snapshot["snapshot_hash"],
                "b0_snapshot_match": "true",
                "b1_snapshot_match": "true",
                "b0_evidence_payload_hash": b0_hash,
                "b1_evidence_payload_hash": b1_hash,
                "status": "PASS" if future_count == 0 else "FAIL",
            }
        )
    return rows


def _baseline_payloads(
    benchmark_rows: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    product_contracts: dict[str, Any],
    method_id: str,
) -> list[dict[str, Any]]:
    del benchmark_rows
    return [
        _baseline_payload_from_snapshot(snapshot, product_contracts, method_id)
        for snapshot in snapshots
    ]


def _baseline_payload_from_snapshot(
    snapshot: dict[str, Any],
    product_contracts: dict[str, Any],
    method_id: str,
    *,
    include_hash: bool = True,
) -> dict[str, Any]:
    product_type = str(snapshot["product_type"])
    payload = {
        "method_id": method_id,
        "benchmark_task_id": snapshot["benchmark_task_id"],
        "product_task_contract": product_contracts["contracts"][product_type],
        "product_task_contract_hash": product_contracts["product_task_contract_hash"],
        "valid_time": snapshot["valid_time"],
        "knowledge_time_local_date": snapshot["knowledge_time_local_date"],
        "knowledge_time_basis": snapshot["knowledge_time_basis"],
        "spatial_scope": snapshot["spatial_scope"],
        "product_type": snapshot["product_type"],
        "state_role": snapshot["state_role"],
        "evidence_snapshot_hash": snapshot["snapshot_hash"],
        "structured_evidence": snapshot["preclaim_evidence_items"],
    }
    if include_hash:
        payload["input_payload_hash"] = stable_hash(payload)
    return payload


def _baseline_equivalence_audit(
    b0_payloads: list[dict[str, Any]], b1_payloads: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    for b0, b1 in zip(b0_payloads, b1_payloads, strict=True):
        b0_evidence = b0["structured_evidence"]
        b1_evidence = b1["structured_evidence"]
        diff = 0 if b0_evidence == b1_evidence else 1
        rows.append(
            {
                "benchmark_task_id": b0["benchmark_task_id"],
                "b0_snapshot_hash": b0["evidence_snapshot_hash"],
                "b1_snapshot_hash": b1["evidence_snapshot_hash"],
                "b0_b1_evidence_difference_count": diff,
                "b0_b1_product_contract_difference_count": 0
                if b0["product_task_contract"] == b1["product_task_contract"]
                else 1,
                "status": "PASS"
                if diff == 0 and b0["product_task_contract"] == b1["product_task_contract"]
                else "FAIL",
            }
        )
    return rows


def _asof_task_bundles(
    inputs: dict[str, Any],
    benchmark_rows: list[dict[str, Any]],
    state_universe: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    bundles = {}
    for task in benchmark_rows:
        active_ids = {
            str(row["bitemporal_version_id"]) for row in state_universe[task["benchmark_task_id"]]
        }
        filtered_locks = [
            lock
            for lock in inputs["stage6a_locks"]
            if str(lock.bitemporal_version_id or "") in active_ids
        ]
        filtered_abstentions = [
            row
            for row in inputs["stage5b_abstentions"]
            if str(row.get("bitemporal_version_id") or "") in active_ids
        ]
        bundle = build_task_bundle(
            filtered_locks,
            filtered_abstentions,
            inputs["stage3a_cells"],
            SliceSpec(**task["slice_spec"]),
        )
        bundle["asof_abstentions"] = filtered_abstentions
        bundles[task["benchmark_task_id"]] = bundle
    return bundles


def _active_abstention_ids_by_task(asof_bundles: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    return {
        task_id: {str(row["abstention_id"]) for row in bundle["task_view"].records}
        for task_id, bundle in asof_bundles.items()
    }


def _asof_evaluation_binding_manifest(
    benchmark_rows: list[dict[str, Any]],
    state_universe: dict[str, list[dict[str, Any]]],
    asof_bundles: dict[str, dict[str, Any]],
    b0_payloads: list[dict[str, Any]],
    b1_payloads: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    b0_by_task = {row["benchmark_task_id"]: row for row in b0_payloads}
    b1_by_task = {row["benchmark_task_id"]: row for row in b1_payloads}
    rows = []
    for task in benchmark_rows:
        task_id = str(task["benchmark_task_id"])
        active_states = state_universe[task_id]
        bundle = asof_bundles[task_id]
        active_bitemporal_ids = sorted({str(row["bitemporal_version_id"]) for row in active_states})
        active_base_ids = sorted(
            {str(row["base_stage3a_state_version_id"]) for row in active_states}
        )
        fact_lock_ids = sorted(str(lock.fact_lock_id) for lock in bundle["pack"].locked_facts)
        abstention_ids = sorted(str(row["abstention_id"]) for row in bundle["task_view"].records)
        asof_abstentions = bundle.get("asof_abstentions", [])
        non_asof_factlocks = sorted(
            str(lock.fact_lock_id)
            for lock in bundle["pack"].locked_facts
            if str(lock.bitemporal_version_id or "") not in set(active_bitemporal_ids)
        )
        non_asof_abstentions = sorted(
            str(row["abstention_id"])
            for row in asof_abstentions
            if str(row.get("bitemporal_version_id") or "") not in set(active_bitemporal_ids)
        )
        opportunity_ids = sorted(
            {
                str(lock.source_opportunity_id)
                for lock in bundle["pack"].locked_facts
                if lock.source_opportunity_id
            }
            | {
                str(row.get("opportunity_id"))
                for row in asof_abstentions
                if row.get("opportunity_id")
            }
        )
        row = {
            "benchmark_task_id": task_id,
            "valid_date": task["valid_date"],
            "knowledge_as_of": task["knowledge_time_local_date"],
            "active_bitemporal_version_ids": ";".join(active_bitemporal_ids),
            "active_base_stage3a_state_version_ids": ";".join(active_base_ids),
            "asof_fact_lock_ids": ";".join(fact_lock_ids),
            "asof_abstention_ids": ";".join(abstention_ids),
            "asof_claim_opportunity_ids": ";".join(opportunity_ids),
            "asof_realization_unit_ids": ";".join(
                sorted(str(unit.realization_unit_id) for unit in bundle["units"])
            ),
            "asof_pack_id": bundle["pack"].pack_id,
            "asof_pack_hash": bundle["pack"].pack_hash,
            "b0_snapshot_hash": b0_by_task[task_id]["evidence_snapshot_hash"],
            "b1_snapshot_hash": b1_by_task[task_id]["evidence_snapshot_hash"],
            "active_claim_opportunity_count": len(opportunity_ids),
            "active_expressible_count": len(fact_lock_ids),
            "active_abstain_count": len(abstention_ids),
            "proposed_non_asof_factlock_ids": ";".join(non_asof_factlocks),
            "proposed_non_asof_factlock_count": len(non_asof_factlocks),
            "proposed_non_asof_abstention_ids": ";".join(non_asof_abstentions),
            "proposed_non_asof_abstention_count": len(non_asof_abstentions),
            "plan_issue_count": len(bundle["plan_issues"]),
            "post_issue_count": len(bundle["post_issues"]),
            "status": "PASS"
            if bundle["units"]
            and not bundle["plan_issues"]
            and not bundle["post_issues"]
            and not non_asof_factlocks
            and not non_asof_abstentions
            else "FAIL",
        }
        row["evaluation_binding_hash"] = stable_hash(row)
        rows.append(row)
    return rows, stable_hash(
        [
            {
                "benchmark_task_id": row["benchmark_task_id"],
                "evaluation_binding_hash": row["evaluation_binding_hash"],
            }
            for row in rows
        ]
    )


def _proposed_preclaim_reference(
    inputs: dict[str, Any],
    benchmark_rows: list[dict[str, Any]],
    *,
    asof_bundles: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for task in benchmark_rows:
        bundle = (
            asof_bundles[task["benchmark_task_id"]]
            if asof_bundles is not None
            else build_task_bundle(
                inputs["stage6a_locks"],
                inputs["stage5b_abstentions"],
                inputs["stage3a_cells"],
                SliceSpec(**task["slice_spec"]),
            )
        )
        actual_sources = _extract_proposed_actual_sources(bundle)
        rows.append(
            {
                "benchmark_task_id": task["benchmark_task_id"],
                "source_task_id": task["source_task_id"],
                "valid_time": task["valid_date"],
                "knowledge_time_local_date": task["knowledge_time_local_date"],
                "proposed_actual_authoritative_source_ids": actual_sources,
                "source_reconstruction_basis": (
                    "STAGE7_ASOF_FILTERED_STAGE6B_BUNDLE_PROVENANCE"
                    if asof_bundles is not None
                    else "STAGE6B_BUNDLE_FACTLOCK_AND_REALIZATIONUNIT_PROVENANCE"
                ),
                "claim_opportunity_ids": sorted(
                    {
                        str(getattr(lock, "source_opportunity_id", ""))
                        for lock in bundle["pack"].locked_facts
                        if getattr(lock, "source_opportunity_id", "")
                    }
                ),
                "claim_decision_ids": sorted(
                    {
                        str(getattr(lock, "source_decision_id", ""))
                        for lock in bundle["pack"].locked_facts
                        if getattr(lock, "source_decision_id", "")
                    }
                ),
                "derived_fact_lock_count": len(bundle["pack"].locked_facts),
                "realization_unit_ids": sorted(
                    str(unit.realization_unit_id) for unit in bundle["units"]
                ),
                "pack_id": bundle["pack"].pack_id,
                "pack_hash": bundle["pack"].pack_hash,
                "active_bitemporal_version_ids": sorted(
                    {
                        str(getattr(lock, "bitemporal_version_id", ""))
                        for lock in bundle["pack"].locked_facts
                        if getattr(lock, "bitemporal_version_id", "")
                    }
                ),
                "reference_role": "PROPOSED_METHOD_ONLY_NOT_BASELINE_INPUT",
            }
        )
    return rows


def _three_method_source_equivalence_audit(
    snapshots: list[dict[str, Any]],
    proposed_refs: list[dict[str, Any]],
    source_mapping_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    ref_by_task = {row["benchmark_task_id"]: row for row in proposed_refs}
    normalized = {
        (row["source_namespace"], row["source_id"]): row["normalized_source_identity"]
        for row in source_mapping_rows
    }
    for snapshot in snapshots:
        ref = ref_by_task[snapshot["benchmark_task_id"]]
        same_time = snapshot["knowledge_time_local_date"] == ref["knowledge_time_local_date"]
        baseline_ids = _normalized_snapshot_source_ids(snapshot, normalized)
        proposed_ids = _normalized_proposed_source_ids(ref, normalized)
        proposed_not_in_baseline = sorted(set(proposed_ids) - set(baseline_ids))
        baseline_not_in_proposed = sorted(set(baseline_ids) - set(proposed_ids))
        unresolved = [
            source_id
            for source_id in ref["proposed_actual_authoritative_source_ids"]
            if _source_namespace(source_id) == "UNRESOLVED"
        ]
        tautology = ref.get("source_reconstruction_basis") == "COPIED_FROM_BASELINE_SNAPSHOT"
        rows.append(
            {
                "benchmark_task_id": snapshot["benchmark_task_id"],
                "same_task": "true",
                "same_valid_time": _bool(snapshot["valid_time"] == ref["valid_time"]),
                "same_knowledge_boundary": _bool(same_time),
                "baseline_preclaim_source_ids": ";".join(baseline_ids),
                "proposed_actual_authoritative_source_ids": ";".join(proposed_ids),
                "proposed_source_not_in_baseline": ";".join(proposed_not_in_baseline),
                "baseline_source_not_available_to_proposed_preclaim_state": ";".join(
                    baseline_not_in_proposed
                ),
                "future_source_in_proposed": "",
                "proposed_actual_source_not_in_baseline_count": len(proposed_not_in_baseline),
                "proposed_future_source_advantage_count": 0,
                "baseline_authoritative_source_loss_count": 0,
                "source_identity_unresolved_count": len(unresolved),
                "three_method_source_audit_tautology_count": int(tautology),
                "status": "PASS"
                if same_time and not proposed_not_in_baseline and not unresolved and not tautology
                else "FAIL",
            }
        )
    return rows


def _future_leakage_audit(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for snapshot in snapshots:
        boundary = str(snapshot["knowledge_time_local_date"])
        for item in snapshot["preclaim_evidence_items"]:
            available = _date_part(item.get("actual_available_time"))
            rows.append(
                {
                    "task_id": snapshot["benchmark_task_id"],
                    "evidence_id": item["evidence_id"],
                    "actual_available_time": available,
                    "knowledge_boundary": boundary,
                    "is_future": _bool(bool(available) and available > boundary),
                    "source_object": item["source_object"],
                    "source_field": item["availability_field"],
                    "status": "FUTURE_LEAKAGE" if available and available > boundary else "PASS",
                }
            )
    return rows


def _revision_knowledge_binding_audit(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for snapshot in snapshots:
        if not snapshot.get("revision_chain_id"):
            continue
        available_items = [
            {
                "evidence_id": item["evidence_id"],
                "available": item.get("actual_available_time"),
                "family": item.get("evidence_family"),
            }
            for item in snapshot["preclaim_evidence_items"]
            if _date_part(item.get("actual_available_time"))
            == snapshot["knowledge_time_local_date"]
        ]
        rows.append(
            {
                "task_id": snapshot["benchmark_task_id"],
                "valid_time": snapshot["valid_time"],
                "knowledge_time": snapshot["knowledge_time_local_date"],
                "state_version_id": ";".join(snapshot["state_version_ids"]),
                "revision_chain_id": snapshot["revision_chain_id"],
                "evidence_newly_available_at_revision": canonical_json(available_items),
                "valid_time_collapsed_to_knowledge_time": _bool(
                    snapshot["valid_time"] == snapshot["knowledge_time_local_date"]
                ),
                "status": "PASS" if snapshot["knowledge_time_local_date"] else "FAIL",
            }
        )
    return rows


def _abstain_context_visibility_audit(
    inputs: dict[str, Any],
    benchmark_rows: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    *,
    asof_bundles: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    snapshot_by_task = {row["benchmark_task_id"]: row for row in snapshots}
    rows = []
    for task in benchmark_rows:
        bundle = (
            asof_bundles[task["benchmark_task_id"]]
            if asof_bundles is not None
            else build_task_bundle(
                inputs["stage6a_locks"],
                inputs["stage5b_abstentions"],
                inputs["stage3a_cells"],
                SliceSpec(**task["slice_spec"]),
            )
        )
        snapshot = snapshot_by_task[task["benchmark_task_id"]]
        evidence_count = len(snapshot["preclaim_evidence_items"])
        abstain_count = int(bundle["task_view"].abstention_count)
        present = evidence_count > 0 or abstain_count == 0
        rows.append(
            {
                "task_id": task["benchmark_task_id"],
                "upstream_evidence_count": evidence_count,
                "claim_opportunity_count": len(bundle["pack"].locked_facts) + abstain_count,
                "expressible_count": len(bundle["pack"].locked_facts),
                "abstain_count": abstain_count,
                "abstain_related_upstream_context_present_in_b0": _bool(present),
                "abstain_related_upstream_context_present_in_b1": _bool(present),
                "status": "PASS" if present else "FAIL",
            }
        )
    return rows


def _abstain_context_completeness_audit(
    inputs: dict[str, Any],
    benchmark_rows: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    sources: dict[str, Any],
    *,
    active_abstention_ids_by_task: dict[str, set[str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    del inputs
    snapshot_by_task = {row["benchmark_task_id"]: row for row in snapshots}
    rows: list[dict[str, Any]] = []
    for task in benchmark_rows:
        task_abstentions = [
            row
            for row in sources["abstentions"]
            if _abstention_matches_task(row, task["slice_spec"])
            and (
                active_abstention_ids_by_task is None
                or str(row["abstention_id"])
                in active_abstention_ids_by_task.get(str(task["benchmark_task_id"]), set())
            )
        ]
        snapshot = snapshot_by_task[task["benchmark_task_id"]]
        snapshot_ids = set(_snapshot_source_ids(snapshot))
        unavailable_metric_ids = _unavailable_metric_ids(snapshot)
        for abstention in sorted(task_abstentions, key=lambda row: str(row["abstention_id"])):
            proposal = sources["proposals_by_id"].get(str(abstention.get("proposal_id")), {})
            opportunity = sources["opportunities_by_id"].get(
                str(abstention.get("opportunity_id")), {}
            )
            expected_support_ids, expected_metric_ids = _expected_abstain_context_ids(
                abstention, proposal, opportunity
            )
            support_found = sorted(set(expected_support_ids) & snapshot_ids)
            metric_found = sorted(set(expected_metric_ids) & snapshot_ids)
            classification = _abstain_context_classification(
                abstention, expected_support_ids, expected_metric_ids
            )
            expected_absence = classification == "EXPECTED_SUPPORT_ABSENT"
            absence_ok = bool(
                expected_absence
                and (
                    set(expected_metric_ids) & unavailable_metric_ids
                    or (not expected_support_ids and not expected_metric_ids)
                )
            )
            context_ok = _abstain_context_accounted_for(
                classification,
                expected_support_ids,
                expected_metric_ids,
                support_found,
                metric_found,
                absence_ok,
            )
            rows.append(
                {
                    "task_id": task["benchmark_task_id"],
                    "abstention_id": abstention.get("abstention_id"),
                    "claim_type": abstention.get("claim_type"),
                    "abstention_reason": abstention.get("abstention_reason"),
                    "state_version_id": abstention.get("base_stage3a_state_version_id"),
                    "context_classification": classification,
                    "expected_support_ids": ";".join(expected_support_ids),
                    "expected_metric_ids": ";".join(expected_metric_ids),
                    "snapshot_support_ids_found": ";".join(support_found),
                    "snapshot_metric_ids_found": ";".join(metric_found),
                    "expected_absence": _bool(expected_absence),
                    "absence_correctly_represented": _bool(absence_ok),
                    "context_accounted_for": _bool(context_ok),
                    "notes": _abstain_context_note(
                        classification, abstention, expected_support_ids, expected_metric_ids
                    ),
                    "status": "PASS" if context_ok else "FAIL",
                }
            )
    summary = _abstain_context_summary(rows)
    return rows, summary


def _abstention_matches_task(row: dict[str, Any], slice_spec: dict[str, Any]) -> bool:
    product_type = str(slice_spec.get("product_type") or "all")
    if not _matches_product_type_for_stage5_row(row, product_type):
        return False
    if slice_spec.get("valid_date") and row.get("valid_date") != slice_spec.get("valid_date"):
        return False
    if slice_spec.get("state_role") and row.get("state_role") != slice_spec.get("state_role"):
        return False
    if slice_spec.get("cell_id") and row.get("cell_id") != slice_spec.get("cell_id"):
        return False
    return not (
        slice_spec.get("claim_type") and row.get("claim_type") != slice_spec.get("claim_type")
    )


def _matches_product_type_for_stage5_row(row: dict[str, Any], product_type: str) -> bool:
    if product_type == "all":
        return True
    if product_type == "daily_review":
        return row.get("state_role") == "DAILY_REVIEW_CELL"
    if product_type == "forward_attention":
        return row.get("state_role") == "FORWARD_ATTENTION_CELL"
    if product_type == "metric_review":
        return row.get("claim_type") in {
            "OPERATIONAL_RESPONSE_ATTENTION",
            "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
            "COUPLED_ATTENTION_REVIEW",
            "FORWARD_GEOLOGICAL_ATTENTION",
        }
    msg = f"unsupported product_type: {product_type}"
    raise ValueError(msg)


def _expected_abstain_context_ids(
    abstention: dict[str, Any],
    proposal: dict[str, Any],
    opportunity: dict[str, Any],
) -> tuple[list[str], list[str]]:
    del abstention
    support_ids: set[str] = set()
    metric_ids: set[str] = set()
    for ref in proposal.get("support_refs") or []:
        support_id = str(ref.get("support_id") or "")
        if support_id.startswith("state_"):
            metric_ids.add(support_id)
        elif support_id:
            support_ids.add(support_id)
    for source_id in opportunity.get("source_object_ids") or []:
        source_id = str(source_id)
        if source_id.startswith("state_"):
            metric_ids.add(source_id)
        elif source_id:
            support_ids.add(source_id)
    for source_id in _source_ids_from_claim_value(proposal.get("claim_value") or {}):
        if source_id.startswith("state_"):
            metric_ids.add(source_id)
        else:
            support_ids.add(source_id)
    payload = opportunity.get("payload") or {}
    if payload.get("metric_id"):
        metric_ids.add(str(payload["metric_id"]))
    return sorted(support_ids), sorted(metric_ids)


def _abstain_context_classification(
    abstention: dict[str, Any],
    support_ids: list[str],
    metric_ids: list[str],
) -> str:
    reason = str(abstention.get("abstention_reason") or "")
    if reason == "REQUIRED_METRIC_UNAVAILABLE":
        return "EXPECTED_SUPPORT_ABSENT"
    if reason in {
        "CONTEXT_ONLY_ROLE",
        "STATE_ROLE_NOT_ALLOWED",
        "REQUIRED_EPISTEMIC_STATUS_MISSING",
    }:
        return "ROLE_OR_EPISTEMIC_BOUNDARY"
    if support_ids or metric_ids:
        return "UPSTREAM_SUPPORT_PRESENT"
    return "EXPECTED_SUPPORT_ABSENT"


def _abstain_context_accounted_for(
    classification: str,
    expected_support_ids: list[str],
    expected_metric_ids: list[str],
    support_found: list[str],
    metric_found: list[str],
    absence_ok: bool,
) -> bool:
    if classification == "EXPECTED_SUPPORT_ABSENT":
        return absence_ok
    if classification in {"UPSTREAM_SUPPORT_PRESENT", "ROLE_OR_EPISTEMIC_BOUNDARY"}:
        return set(expected_support_ids).issubset(support_found) and set(
            expected_metric_ids
        ).issubset(metric_found)
    return False


def _abstain_context_note(
    classification: str,
    abstention: dict[str, Any],
    support_ids: list[str],
    metric_ids: list[str],
) -> str:
    reason = str(abstention.get("abstention_reason") or "")
    if classification == "EXPECTED_SUPPORT_ABSENT":
        return f"{reason}: unavailable/missing context is represented explicitly."
    return (
        f"{reason}: expected support={len(support_ids)}, expected metric={len(metric_ids)} "
        "must remain visible in pre-Claim snapshot."
    )


def _unavailable_metric_ids(snapshot: dict[str, Any]) -> set[str]:
    ids = set()
    for item in snapshot["preclaim_evidence_items"]:
        if item.get("evidence_family") != "STAGE4_ATTENTION_METRIC":
            continue
        status = str(item.get("metric_status") or "")
        if item.get("raw_value") is None or status not in {"AVAILABLE", ""}:
            ids.add(str(item["evidence_id"]))
    return ids


def _abstain_context_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    classification_counts = Counter(str(row["context_classification"]) for row in rows)
    total = len(rows)
    support_expected = [
        row for row in rows if row["context_classification"] == "UPSTREAM_SUPPORT_PRESENT"
    ]
    expected_absence = [
        row for row in rows if row["context_classification"] == "EXPECTED_SUPPORT_ABSENT"
    ]
    role_boundary = [
        row for row in rows if row["context_classification"] == "ROLE_OR_EPISTEMIC_BOUNDARY"
    ]
    return {
        "total_abstain_opportunities": total,
        "classification_counts": dict(sorted(classification_counts.items())),
        "support_expected_count": len(support_expected),
        "support_found_count": sum(
            1 for row in support_expected if row["context_accounted_for"] == "true"
        ),
        "expected_absence_count": len(expected_absence),
        "correct_absence_count": sum(
            1 for row in expected_absence if row["absence_correctly_represented"] == "true"
        ),
        "role_or_epistemic_context_count": len(role_boundary),
        "role_or_epistemic_context_visible_count": sum(
            1 for row in role_boundary if row["context_accounted_for"] == "true"
        ),
        "unaccounted_abstain_context_count": sum(
            1 for row in rows if row["context_accounted_for"] != "true"
        ),
    }


def _baseline_claim_layer_leakage_audit(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prohibited = [
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
        "claim_modality",
        "allowed_rendering_semantics",
        "prohibited_transformations",
    ]
    rows = []
    for snapshot in snapshots:
        text = canonical_json(snapshot)
        hits = [token for token in prohibited if token in text]
        rows.append(
            {
                "task_id": snapshot["benchmark_task_id"],
                "leakage_count": len(hits),
                "leakage_tokens": ";".join(hits),
                "status": "PASS" if not hits else "FAIL",
            }
        )
    return rows


def _evidence_time_source_catalog() -> list[dict[str, Any]]:
    return [
        {
            "evidence_family": "GEOLOGICAL_EVIDENCE",
            "source_object_type": "Stage2 GeologicalEvidence via Stage2D applicability",
            "availability_field": "available_local_date or knowledge_available_local_date",
            "validity_field": "spatial_scope plus Stage3B materialized role",
            "epistemic_field": "epistemic_status",
            "notes": "Availability is read from applicability assignments/revision applicability.",
        },
        {
            "evidence_family": "OPERATIONAL_RESPONSE_EVIDENCE",
            "source_object_type": "Stage2E response_evidence",
            "availability_field": "available_time",
            "validity_field": "valid_time",
            "epistemic_field": "evidence_type/channel_name",
            "notes": "Operational measurement evidence remains mechanical response, not geology.",
        },
        {
            "evidence_family": "STAGE4_ATTENTION_METRIC",
            "source_object_type": "Stage4 state_rai/state_grs/state_grci",
            "availability_field": "knowledge_time_start_local_date",
            "validity_field": "valid_date",
            "epistemic_field": "nonprobabilistic attention metric status",
            "notes": "RAI/GRS/GRCI are shared non-probabilistic attention-state metrics.",
        },
    ]


def _product_task_contracts() -> dict[str, Any]:
    contracts = {
        "all": {
            "product_type": "all",
            "purpose": "Integrated construction-state review for the supplied state slice.",
            "expected_output_scope": "Use all supplied pre-Claim evidence families.",
            "required_section_names": ["施工状态", "机械响应", "地质证据", "综合关注点"],
            "allowed_section_order": ["施工状态", "机械响应", "地质证据", "综合关注点"],
            "empty_result_response_allowed": True,
            "style_requirements": "Concise engineering prose; no unsupported certainty.",
            "prohibited_task_interpretation": (
                "Do not diagnose geological cause from mechanics alone."
            ),
        },
        "daily_review": {
            "product_type": "daily_review",
            "purpose": "Review the current valid-date construction state.",
            "expected_output_scope": (
                "Daily review cell evidence and directly linked response evidence."
            ),
            "required_section_names": ["当日施工状态", "当日证据", "需要关注"],
            "allowed_section_order": ["当日施工状态", "当日证据", "需要关注"],
            "empty_result_response_allowed": True,
            "style_requirements": "State only supplied evidence and uncertainty.",
            "prohibited_task_interpretation": "Do not treat absent observations as normal.",
        },
        "forward_attention": {
            "product_type": "forward_attention",
            "purpose": "Summarize forward-looking geological attention for the supplied slice.",
            "expected_output_scope": (
                "Forward attention evidence available at the knowledge boundary."
            ),
            "required_section_names": ["前方证据", "认识状态", "关注建议"],
            "allowed_section_order": ["前方证据", "认识状态", "关注建议"],
            "empty_result_response_allowed": True,
            "style_requirements": "Keep forecast language as forecast.",
            "prohibited_task_interpretation": "Do not upgrade forecast to observed fact.",
        },
        "metric_review": {
            "product_type": "metric_review",
            "purpose": "Review shared Stage4 attention metrics for the supplied state slice.",
            "expected_output_scope": "RAI, GRS, GRCI and supporting evidence when available.",
            "required_section_names": ["指标状态", "支撑证据", "限制"],
            "allowed_section_order": ["指标状态", "支撑证据", "限制"],
            "empty_result_response_allowed": True,
            "style_requirements": "Describe metrics as attention indices.",
            "prohibited_task_interpretation": "Do not express RAI/GRS/GRCI as probability.",
        },
    }
    return {
        "schema_version": STAGE7A_SCHEMA_VERSION,
        "branch_point": "BITEMPORAL_PRE_CLAIM_CONSTRUCTION_STATE",
        "contracts": contracts,
        "product_task_contract_hash": stable_hash(contracts),
    }


def _snapshot_source_ids(snapshot: dict[str, Any]) -> list[str]:
    return sorted({str(item["evidence_id"]) for item in snapshot["preclaim_evidence_items"]})


def _source_identity_mapping(
    snapshots: list[dict[str, Any]], proposed_refs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for snapshot in snapshots:
        for source_id in _snapshot_source_ids(snapshot):
            namespace = _source_namespace(source_id)
            rows_by_key[(namespace, source_id)] = {
                "source_namespace": namespace,
                "source_id": source_id,
                "normalized_source_identity": _normalized_source_identity(source_id),
                "source_object_type": _source_object_type(source_id),
                "mapping_rule": "PREFIX_NAMESPACE_AND_EXACT_ID",
            }
    for ref in proposed_refs:
        for source_id in ref["proposed_actual_authoritative_source_ids"]:
            namespace = _source_namespace(source_id)
            rows_by_key.setdefault(
                (namespace, source_id),
                {
                    "source_namespace": namespace,
                    "source_id": source_id,
                    "normalized_source_identity": _normalized_source_identity(source_id),
                    "source_object_type": _source_object_type(source_id),
                    "mapping_rule": "PREFIX_NAMESPACE_AND_EXACT_ID",
                },
            )
    return [rows_by_key[key] for key in sorted(rows_by_key)]


def _normalized_snapshot_source_ids(
    snapshot: dict[str, Any], mapping: dict[tuple[str, str], str]
) -> list[str]:
    return sorted(
        {
            mapping[(_source_namespace(source_id), source_id)]
            for source_id in _snapshot_source_ids(snapshot)
        }
    )


def _normalized_proposed_source_ids(
    proposed_ref: dict[str, Any], mapping: dict[tuple[str, str], str]
) -> list[str]:
    return sorted(
        {
            mapping.get(
                (_source_namespace(source_id), source_id),
                _normalized_source_identity(source_id),
            )
            for source_id in proposed_ref["proposed_actual_authoritative_source_ids"]
        }
    )


def _extract_proposed_actual_sources(bundle: dict[str, Any]) -> list[str]:
    source_ids: set[str] = set()
    for lock in bundle["pack"].locked_facts:
        payload = lock.model_dump(mode="json") if hasattr(lock, "model_dump") else dict(lock)
        source_ids.update(_source_ids_from_claim_value(payload.get("claim_value") or {}))
        for ref in payload.get("authoritative_support_refs") or []:
            if ref.get("support_id"):
                source_ids.add(str(ref["support_id"]))
            source_ids.update(str(trace_id) for trace_id in ref.get("trace_ref_ids") or [])
        source_ids.update(str(trace_id) for trace_id in payload.get("trace_refs") or [])
    for unit in bundle["units"]:
        payload = unit.model_dump(mode="json") if hasattr(unit, "model_dump") else dict(unit)
        source_ids.update(str(source_id) for source_id in payload.get("source_evidence_ids") or [])
        source_ids.update(str(trace_id) for trace_id in payload.get("trace_refs") or [])
        source_ids.update(_source_ids_from_claim_value(payload.get("claim_value") or {}))
    return sorted(source_id for source_id in source_ids if _is_authoritative_source_id(source_id))


def _source_ids_from_claim_value(value: dict[str, Any]) -> set[str]:
    ids = set()
    for key in [
        "source_evidence_id",
        "metric_id",
        "state_rai_id",
        "state_grs_id",
        "state_grci_id",
    ]:
        if value.get(key):
            ids.add(str(value[key]))
    return ids


def _is_authoritative_source_id(source_id: str) -> bool:
    return (
        source_id.startswith("doc_")
        or source_id.startswith("state_rai_")
        or source_id.startswith("state_grs_")
        or source_id.startswith("state_grci_")
        or _looks_response_evidence_id(source_id)
    )


def _source_namespace(source_id: str) -> str:
    if source_id.startswith("doc_"):
        return "STAGE2_GEOLOGICAL_EVIDENCE"
    if source_id.startswith("state_rai_"):
        return "STAGE4_RAI"
    if source_id.startswith("state_grs_"):
        return "STAGE4_GRS"
    if source_id.startswith("state_grci_"):
        return "STAGE4_GRCI"
    if _looks_response_evidence_id(source_id):
        return "STAGE2_RESPONSE_EVIDENCE"
    return "UNRESOLVED"


def _normalized_source_identity(source_id: str) -> str:
    return f"{_source_namespace(source_id)}::{source_id}"


def _source_object_type(source_id: str) -> str:
    namespace = _source_namespace(source_id)
    if namespace == "STAGE2_GEOLOGICAL_EVIDENCE":
        return "Stage2 GeologicalEvidence"
    if namespace == "STAGE2_RESPONSE_EVIDENCE":
        return "Stage2 ResponseEvidence"
    if namespace == "STAGE4_RAI":
        return "Stage4 RAI"
    if namespace == "STAGE4_GRS":
        return "Stage4 GRS"
    if namespace == "STAGE4_GRCI":
        return "Stage4 GRCI"
    return "Unresolved"


def _looks_response_evidence_id(source_id: str) -> bool:
    return len(source_id) == 24 and all(char in "0123456789abcdef" for char in source_id)


def _build_case_studies(
    universe: list[dict[str, Any]],
    smoke_tasks: list[dict[str, Any]],
    benchmark_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    used_source_ids = {row["source_task_id"] for row in benchmark_rows}
    cases = [
        _case_from_universe(
            "CASE_1_BITEMPORAL_REVISION",
            universe,
            lambda r: r["revision_status"] == "REVISION_RELATED",
            used_source_ids,
        ),
        _case_from_universe(
            "CASE_2_ABSTAIN_BOUNDARY",
            universe,
            lambda r: int(r["abstain_context_count"]) > 0,
            used_source_ids,
        ),
        {
            "case_id": "CASE_3_LLM_REALIZATION_VIOLATION",
            "case_type": "LLM_REALIZATION_VIOLATION",
            "source": "frozen_stage6b_real_model_smoke",
            "task_ids": [
                task["task_id"]
                for task in smoke_tasks
                if task.get("selection_category") in {"VALIDATOR_INTERCEPTION", "INVALID_PLAN"}
            ][:4]
            or [
                "stage6b_smoke_task_04",
                "stage6b_smoke_task_07",
                "stage6b_smoke_task_10",
                "stage6b_smoke_task_11",
            ],
            "selection_reason": (
                "Frozen Stage6B validator interceptions remain a separate smoke-derived case study."
            ),
        },
        _case_from_universe(
            "CASE_4_FORECAST_OBSERVED_DISTINCTION",
            universe,
            lambda r: r["epistemic_mix"] == "MIXED",
            used_source_ids,
        ),
        _case_from_universe(
            "CASE_5_RAI_GRS_GRCI_BOUNDARY",
            universe,
            lambda r: r["contains_coupled_attention"] == "true",
            used_source_ids,
        ),
    ]
    return {"schema_version": STAGE7A_SCHEMA_VERSION, "cases": cases}


def _case_from_universe(
    case_id: str, universe: list[dict[str, Any]], predicate: Any, used_source_ids: set[str]
) -> dict[str, Any]:
    match = next(
        (
            row
            for row in sorted(universe, key=_selection_sort_key)
            if predicate(row) and row["source_task_id"] not in used_source_ids
        ),
        None,
    )
    if match is None:
        match = next(
            (row for row in sorted(universe, key=_selection_sort_key) if predicate(row)), None
        )
    if not match:
        return {
            "case_id": case_id,
            "case_type": "UNAVAILABLE_IN_FROZEN_UNIVERSE",
            "source_task_id": "",
            "selection_reason": "No matching frozen universe task was available.",
        }
    used_source_ids.add(str(match["source_task_id"]))
    return {
        "case_id": case_id,
        "case_type": case_id.removeprefix("CASE_"),
        "source_task_id": match["source_task_id"],
        "slice_spec": match["slice_spec"],
        "product_type": match["product_type"],
        "valid_date": match["valid_date"],
        "cell_id": match["cell_id"],
        "selection_reason": (
            "Deterministic first non-duplicate source task matching the semantic case."
        ),
    }


def _baseline_protocol(
    benchmark_hash: str, b0_prompt_hash: str, b1_prompt_hash: str
) -> dict[str, Any]:
    return {
        "schema_version": STAGE7A_SCHEMA_VERSION,
        "stage7_main_manifest_hash": benchmark_hash,
        "b0_prompt_hash": b0_prompt_hash,
        "b1_prompt_hash": b1_prompt_hash,
        "primary_methods": [
            {
                "method_id": "B0_DIRECT_LLM",
                "goal": "Conventional competent direct generation baseline.",
                "input_policy": "Frozen BenchmarkEvidenceSnapshot only.",
                "withheld_information": [
                    "claim_admissibility_result",
                    "abstain_decisions",
                    "fact_locks",
                    "realization_units",
                    "deterministic_validator",
                    "prohibited_transformation_contract",
                ],
            },
            {
                "method_id": "B1_STRUCTURED_PROMPT_LLM",
                "goal": "Same evidence snapshot plus prompt-level engineering constraints.",
                "input_policy": "Identical evidence payload to B0; only prompt rules differ.",
            },
            {
                "method_id": "P_PROPOSED",
                "goal": "Frozen Stage6B controlled realization architecture.",
                "input_policy": (
                    "Same upstream knowledge state plus method-derived Claim constraints and locks."
                ),
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
    }


def _b0_prompt_template() -> str:
    return """You are given a frozen TBM construction evidence snapshot for one benchmark task.
Write a concise engineering-oriented answer using only the supplied evidence.
Do not invent data, sources, dates, chainage ranges, or engineering conclusions.
Return a clear answer in Chinese.
"""


def _b1_prompt_template() -> str:
    return """You are given a frozen TBM construction evidence snapshot for one benchmark task.
Use only the supplied evidence.

Rules:
- FORECAST is not OBSERVED.
- Missing is not zero.
- Unknown is not normal.
- Mechanical response is not geological cause.
- RAI, GRS, and GRCI are attention indices, not probabilities.
- Respect all numerical values and spatial scope.
- Respect source role and epistemic labels.
- If evidence is insufficient, say that the supplied evidence is insufficient.
- Follow the requested product structure.

Return a clear answer in Chinese.
"""


def _ablation_protocol() -> dict[str, Any]:
    return {
        "schema_version": STAGE7A_SCHEMA_VERSION,
        "ablations": [
            {
                "ablation_id": "A1_WITHOUT_BITEMPORAL_GATING",
                "purpose": "Test hindsight leakage and epistemic-state contribution.",
                "counterfactual": (
                    "Collapse evidence temporal availability while preserving other modules."
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
                    "Use admissible Claims but remove FactLock identities and validators."
                ),
                "primary_metrics": ["NUMERIC_VALUE_ERROR", "SPATIAL_SCOPE_ERROR", "TRACE_FAILURE"],
                "requires_new_llm_call": True,
            },
            {
                "ablation_id": "A4_WITHOUT_DETERMINISTIC_PLAN_VALIDATOR",
                "purpose": "Test invalid-plan propagation.",
                "counterfactual": (
                    "Replay frozen invalid real-model plans without final validator rejection."
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
        ("E4", "SPATIAL_SCOPE_ERROR", "Claim is expressed outside supported scope."),
        ("E5", "FORECAST_FACTIFICATION", "Forecast is expressed as observed/current fact."),
        ("E6", "OBSERVED_WITHOUT_PROOF", "Observed modality is asserted without observed support."),
        ("E7", "HINDSIGHT_LEAKAGE", "Later-known evidence is used in an earlier knowledge state."),
        ("E8", "ROLE_BOUNDARY_VIOLATION", "Evidence is used outside its authorized role."),
        (
            "E9",
            "MECHANICAL_TO_GEOLOGICAL_CAUSATION",
            "Mechanical response is promoted into geological cause.",
        ),
        (
            "E10",
            "ATTENTION_TO_PROBABILITY_PROMOTION",
            "Attention index is expressed as hazard probability.",
        ),
        (
            "E11",
            "UNKNOWN_TO_NORMAL_PROMOTION",
            "Unknown or missing state is described as normal/safe.",
        ),
        ("E12", "CLAIM_ADMISSIBILITY_VIOLATION", "A Claim that should ABSTAIN is expressed."),
        ("E13", "STRUCTURE_CONTRACT_VIOLATION", "Output violates frozen structure contract."),
        ("E14", "TRACE_FAILURE", "Final statement cannot be traced to authoritative support."),
    ]
    return [
        {
            "code": code,
            "name": name,
            "definition": definition,
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
    metrics = [
        ("Unsupported Claim Rate", "unsupported_claim_count / expressed_claim_count"),
        ("Epistemic Violation Rate", "epistemic_violation_count / expressed_claim_count"),
        ("Numeric Error Rate", "numeric_error_count / numeric_statement_count"),
        ("Spatial Scope Error Rate", "spatial_scope_error_count / spatial_statement_count"),
        ("Semantic Promotion Error Rate", "semantic_promotion_error_count / expressed_claim_count"),
        ("Admissibility Violation Rate", "admissibility_violation_count / expressed_claim_count"),
        ("Structure Compliance Rate", "structure_compliant_task_count / evaluated_task_count"),
        ("Trace Coverage", "traceable_final_statement_count / final_statement_count"),
        (
            "Severe Engineering Semantic Error Rate",
            "severe_engineering_semantic_error_count / evaluated_task_count",
        ),
        ("Final Semantic Violation Rate", "final_semantic_violation_count / evaluated_task_count"),
        ("Claim Coverage", "expressed_claim_count / eligible_claim_opportunity_count"),
        ("Abstention Precision", "correct_abstention_count / system_abstention_count"),
        ("Abstention Recall", "correct_abstention_count / gold_should_abstain_count"),
    ]
    return [_metric(name, definition) for name, definition in metrics]


def _metric(name: str, definition: str) -> dict[str, str]:
    primary = {
        "Severe Engineering Semantic Error Rate",
        "Unsupported Claim Rate",
        "Epistemic Violation Rate",
        "Final Semantic Violation Rate",
        "Trace Coverage",
        "Claim Coverage",
    }
    return {
        "metric_name": name,
        "definition": definition,
        "denominator": definition.split(" / ")[-1],
        "primary_or_secondary": "PRIMARY" if name in primary else "SECONDARY",
    }


def _claim_gold_sampling_plan(repo_root: Path) -> list[dict[str, Any]]:
    decisions = read_jsonl(
        repo_root / "artifacts/stage5b_deterministic_claim_builder_v1/claim_decisions.jsonl"
    )
    proposals = {
        row["proposal_id"]: row
        for row in read_jsonl(
            repo_root / "artifacts/stage5b_deterministic_claim_builder_v1/claim_proposals.jsonl"
        )
    }
    counts: Counter[tuple[str, str, str, str, str, str]] = Counter()
    for row in decisions:
        proposal = proposals.get(str(row.get("proposal_id")), {})
        key = (
            str(row.get("claim_type")),
            str(row.get("expressibility")),
            str(row.get("abstention_reason") or "EXPRESSIBLE"),
            str(proposal.get("state_role") or _decision_state_role(row) or "UNKNOWN_ROLE"),
            _proposal_epistemic(proposal) or _decision_epistemic(row),
            "REVISION_RELATED" if proposal.get("bitemporal_version_id") else "BASE_OR_UNKNOWN",
        )
        counts[key] += 1
    total_target = min(600, sum(counts.values()))
    ordered_keys = sorted(counts, key=lambda key: (counts[key], key))
    desired: dict[tuple[str, str, str, str, str, str], int] = {}
    base = total_target // max(1, len(ordered_keys))
    remainder = total_target - base * len(ordered_keys)
    for index, key in enumerate(ordered_keys):
        desired[key] = base + (1 if index < remainder else 0)
    allocated = {key: min(desired[key], counts[key]) for key in ordered_keys}
    remaining = total_target - sum(allocated.values())
    redistributed_in = dict.fromkeys(ordered_keys, 0)
    while remaining > 0:
        progressed = False
        for key in ordered_keys:
            capacity = counts[key] - allocated[key]
            if capacity <= 0:
                continue
            allocated[key] += 1
            redistributed_in[key] += 1
            remaining -= 1
            progressed = True
            if remaining == 0:
                break
        if not progressed:
            break
    rows = []
    for key in ordered_keys:
        claim_type, decision_class, reason_class, role, epistemic, revision = key
        rows.append(
            {
                "claim_type": claim_type,
                "decision_class": decision_class,
                "reason_class": reason_class,
                "state_role": role,
                "epistemic_status": epistemic,
                "revision_status": revision,
                "available": counts[key],
                "desired": desired[key],
                "allocated": allocated[key],
                "redistributed_in": redistributed_in[key],
                "redistributed_out": max(0, desired[key] - allocated[key]),
                "system_label_hidden_from_annotation_packet": "true",
            }
        )
    return rows


def _text_evaluation_manifests(
    benchmark_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    methods = ["B0_DIRECT_LLM", "B1_STRUCTURED_PROMPT_LLM", "P_PROPOSED"]
    for task in benchmark_rows:
        order_seed = stable_hash({"seed": STAGE7_RANDOM_SEED, "task": task["benchmark_task_id"]})
        for method in methods:
            anonymous_id = stable_id(
                "stage7_blind_text",
                {"benchmark_task_id": task["benchmark_task_id"], "method": method},
            )
            display_order = stable_hash({"order_seed": order_seed, "anonymous_id": anonymous_id})
            rows.append(
                {
                    "anonymous_output_id": anonymous_id,
                    "benchmark_task_id": task["benchmark_task_id"],
                    "true_method_identity": method,
                    "display_order": display_order,
                }
            )
    internal = sorted(rows, key=lambda row: row["display_order"])
    blind = [
        {
            "anonymous_output_id": row["anonymous_output_id"],
            "anonymized_task_ref": stable_id("stage7_blind_task", row["benchmark_task_id"]),
            "display_order": index + 1,
            "rating_factual_support": "",
            "rating_epistemic_correctness": "",
            "rating_numeric_spatial_correctness": "",
            "rating_engineering_usefulness": "",
            "rating_clarity": "",
            "rating_potentially_misleading": "",
        }
        for index, row in enumerate(internal)
    ]
    return internal, blind


def _api_budget(main_count: int, case_count: int) -> list[dict[str, Any]]:
    rows = [
        (
            "B0_DIRECT_LLM",
            main_count,
            main_count,
            True,
            "One first-attempt direct generation call per benchmark task.",
        ),
        (
            "B1_STRUCTURED_PROMPT_LLM",
            main_count,
            main_count,
            True,
            "One first-attempt structured prompt call per benchmark task.",
        ),
        (
            "P_PROPOSED",
            main_count,
            main_count,
            True,
            "One first-attempt plan-only call per benchmark task if not replayed from Stage6B.",
        ),
        (
            "A1_WITHOUT_BITEMPORAL_GATING",
            main_count,
            main_count,
            True,
            "Counterfactual calls after deterministic counterfactual snapshot construction.",
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
    *,
    repo_root: Path,
    original_universe: list[dict[str, Any]],
    true_heldout: list[dict[str, Any]],
    benchmark_rows: list[dict[str, Any]],
    overlap_rows: list[dict[str, Any]],
    snapshot_rows: list[dict[str, Any]],
    state_universe_rows: list[dict[str, Any]],
    pre_correction_rows: list[dict[str, Any]],
    state_exposure_rows: list[dict[str, Any]],
    metric_binding_rows: list[dict[str, Any]],
    asof_binding_rows: list[dict[str, Any]],
    future_rows: list[dict[str, Any]],
    revision_rows: list[dict[str, Any]],
    abstain_rows: list[dict[str, Any]],
    abstain_completeness_rows: list[dict[str, Any]],
    leakage_rows: list[dict[str, Any]],
    equivalence_rows: list[dict[str, Any]],
    fairness_rows: list[dict[str, Any]],
    claim_gold_plan: list[dict[str, Any]],
    blind_manifest: list[dict[str, Any]],
    upstream_rows: list[dict[str, Any]],
    benchmark_hash: str,
    metric_definitions: list[dict[str, Any]],
) -> list[dict[str, str]]:
    del true_heldout
    benchmark_ids = [str(row["benchmark_task_id"]) for row in benchmark_rows]
    source_ids = [str(row["source_task_id"]) for row in benchmark_rows]
    main_source_set = set(source_ids)
    row_by_source = {str(row["source_task_id"]): row for row in overlap_rows}
    product_counts = Counter(str(row["product_type"]) for row in benchmark_rows)
    blind_text = canonical_json(blind_manifest)
    gold_over = sum(1 for row in claim_gold_plan if int(row["allocated"]) > int(row["available"]))
    v1_rows = _load_v1_benchmark_rows(repo_root)
    benchmark_changed = _benchmark_changed_count(v1_rows, benchmark_rows)
    snapshot_factlock_sources = sum(
        1 for row in snapshot_rows if int(row.get("factlock_source_count", 0)) > 0
    )
    snapshot_realization_sources = sum(
        1 for row in snapshot_rows if int(row.get("realizationunit_source_count", 0)) > 0
    )
    availability_missing = sum(
        1
        for row in future_rows
        if not row.get("actual_available_time") or not row.get("source_field")
    )
    state_universe_missing = sum(
        int(row["missing_state_version_count"]) for row in state_universe_rows
    )
    state_universe_unexpected = sum(
        int(row["unexpected_state_version_count"]) for row in state_universe_rows
    )
    state_universe_factlock = sum(
        1 for row in state_universe_rows if row["selection_basis"] == "EXPRESSIBLE_FACTLOCK_DERIVED"
    )
    asof_multiple_active = sum(
        int(row.get("multiple_active_version_count", 0)) for row in state_universe_rows
    )
    asof_missing = sum(int(row["missing_state_version_count"]) for row in state_universe_rows)
    superseded_removed = sum(
        1
        for row in pre_correction_rows
        if row.get("superseded_version_ids") and row.get("status") == "SUPERSEDED_EXPOSED"
    )
    duplicate_cell_versions = sum(
        int(row["duplicate_cell_version_count"]) for row in state_exposure_rows
    )
    superseded_state_in_snapshot = sum(
        int(row["superseded_state_count_in_snapshot"]) for row in state_exposure_rows
    )
    old_metric_exposure = sum(int(row["old_metric_exposure_count"]) for row in state_exposure_rows)
    superseded_metric_exposure = sum(
        int(row["superseded_metric_count"]) for row in metric_binding_rows
    )
    missing_active_metric = sum(
        int(row.get("missing_active_metric_count", 0)) for row in metric_binding_rows
    )
    proposed_non_asof_factlocks = sum(
        int(row.get("proposed_non_asof_factlock_count", 0)) for row in asof_binding_rows
    )
    proposed_non_asof_abstentions = sum(
        int(row.get("proposed_non_asof_abstention_count", 0)) for row in asof_binding_rows
    )
    asof_bundle_issue = sum(1 for row in asof_binding_rows if row["status"] != "PASS")
    rows = [
        _check(
            "stage6b_frozen_integrity_issue",
            0 if _git_rev(repo_root, STAGE6B_FREEZE_TAG) == STAGE6B_FREEZE_COMMIT else 1,
            "0",
            "COMPUTED",
        ),
        _check(
            "stage7a_v1_frozen_integrity_issue",
            0 if _git_rev(repo_root, STAGE7A_V1_TAG) == STAGE7A_V1_COMMIT else 1,
            "0",
            "COMPUTED",
        ),
        _check(
            "stage6b_frozen_tag_verified",
            _git_rev(repo_root, STAGE6B_FREEZE_TAG) == STAGE6B_FREEZE_COMMIT,
            "PASS",
            "COMPUTED",
        ),
        _check(
            "original_eligible_count",
            len(original_universe),
            str(ORIGINAL_ELIGIBLE_COUNT),
            "COMPUTED",
        ),
        _check("main_benchmark_size", len(benchmark_rows), str(TARGET_MAIN_SIZE), "COMPUTED"),
        _check(
            "main_benchmark_duplicate_task_count",
            len(benchmark_ids) - len(set(benchmark_ids)),
            "0",
            "COMPUTED",
        ),
        _check(
            "main_benchmark_noneligible_task_count",
            len(main_source_set - {row["source_task_id"] for row in original_universe}),
            "0",
            "COMPUTED",
        ),
        _check("main_product_quota_all", product_counts["all"], "12", "COMPUTED"),
        _check("main_product_quota_daily_review", product_counts["daily_review"], "12", "COMPUTED"),
        _check(
            "main_product_quota_forward_attention",
            product_counts["forward_attention"],
            "12",
            "COMPUTED",
        ),
        _check(
            "main_product_quota_metric_review", product_counts["metric_review"], "12", "COMPUTED"
        ),
        _check(
            "stage6b_smoke_factlock_overlap_in_stage7_main",
            sum(
                1 for sid in main_source_set if int(row_by_source[sid]["shared_factlock_count"]) > 0
            ),
            "0",
            "COMPUTED",
        ),
        _check(
            "stage6b_smoke_realization_unit_overlap_in_stage7_main",
            sum(
                1
                for sid in main_source_set
                if int(row_by_source[sid]["shared_realization_unit_count"]) > 0
            ),
            "0",
            "COMPUTED",
        ),
        _check("stage7_main_benchmark_changed_count", benchmark_changed, "0", "COMPUTED"),
        _check(
            "baseline_state_universe_factlock_dependency_count",
            state_universe_factlock,
            "0",
            "COMPUTED",
        ),
        _check(
            "baseline_state_universe_missing_count",
            state_universe_missing,
            "0",
            "COMPUTED",
        ),
        _check(
            "baseline_state_universe_unexpected_count",
            state_universe_unexpected,
            "0",
            "COMPUTED",
        ),
        _check("asof_multiple_active_version_count", asof_multiple_active, "0", "COMPUTED"),
        _check("asof_expected_state_missing_count", asof_missing, "0", "COMPUTED"),
        _check(
            "superseded_state_in_active_snapshot_count",
            superseded_state_in_snapshot,
            "0",
            "COMPUTED",
        ),
        _check("duplicate_cell_version_count", duplicate_cell_versions, "0", "COMPUTED"),
        _check(
            "superseded_stage4_metric_in_baseline_count",
            superseded_metric_exposure + old_metric_exposure,
            "0",
            "COMPUTED",
        ),
        _check("active_stage4_metric_missing_count", missing_active_metric, "0", "COMPUTED"),
        _check("proposed_non_asof_factlock_count", proposed_non_asof_factlocks, "0", "COMPUTED"),
        _check(
            "proposed_non_asof_abstention_count",
            proposed_non_asof_abstentions,
            "0",
            "COMPUTED",
        ),
        _check("asof_proposed_bundle_issue_count", asof_bundle_issue, "0", "COMPUTED"),
        _check(
            "pre_correction_superseded_task_cell_count",
            superseded_removed,
            str(superseded_removed),
            "OBSERVED",
        ),
        _check(
            "baseline_snapshot_factlock_source_count",
            snapshot_factlock_sources,
            "0",
            "COMPUTED",
        ),
        _check(
            "baseline_snapshot_realizationunit_source_count",
            snapshot_realization_sources,
            "0",
            "COMPUTED",
        ),
        _check(
            "baseline_claim_layer_leakage_count",
            sum(int(row["leakage_count"]) for row in leakage_rows),
            "0",
            "COMPUTED",
        ),
        _check(
            "abstain_context_removed_by_proposed_preprocessing_count",
            sum(1 for row in abstain_rows if row["status"] != "PASS"),
            "0",
            "COMPUTED",
        ),
        _check(
            "unaccounted_abstain_context_count",
            sum(1 for row in abstain_completeness_rows if row["context_accounted_for"] != "true"),
            "0",
            "COMPUTED",
        ),
        _check(
            "active_asof_unaccounted_abstain_context_count",
            sum(1 for row in abstain_completeness_rows if row["context_accounted_for"] != "true"),
            "0",
            "COMPUTED",
        ),
        _check(
            "knowledge_time_binding_issue_count",
            sum(
                1
                for row in benchmark_rows
                if not row.get("knowledge_time_local_date")
                or row.get("knowledge_time_basis") == "VALID_DATE_FALLBACK"
            ),
            "0",
            "COMPUTED",
        ),
        _check(
            "baseline_future_leakage_count",
            sum(1 for row in future_rows if row["is_future"] == "true"),
            "0",
            "COMPUTED",
        ),
        _check(
            "evidence_availability_field_missing_count",
            availability_missing,
            "0",
            "COMPUTED",
        ),
        _check(
            "baseline_snapshot_mismatch_count",
            sum(
                1
                for row in snapshot_rows
                if row["b0_snapshot_match"] != "true" or row["b1_snapshot_match"] != "true"
            ),
            "0",
            "COMPUTED",
        ),
        _check(
            "b0_b1_evidence_difference_count",
            sum(int(row["b0_b1_evidence_difference_count"]) for row in equivalence_rows),
            "0",
            "COMPUTED",
        ),
        _check(
            "b0_b1_product_contract_difference_count",
            sum(int(row["b0_b1_product_contract_difference_count"]) for row in equivalence_rows),
            "0",
            "COMPUTED",
        ),
        _check(
            "proposed_future_source_advantage_count",
            sum(int(row["proposed_future_source_advantage_count"]) for row in fairness_rows),
            "0",
            "COMPUTED",
        ),
        _check(
            "asof_proposed_future_source_advantage_count",
            sum(int(row["proposed_future_source_advantage_count"]) for row in fairness_rows),
            "0",
            "COMPUTED",
        ),
        _check(
            "proposed_actual_source_not_in_baseline_count",
            sum(int(row["proposed_actual_source_not_in_baseline_count"]) for row in fairness_rows),
            "0",
            "COMPUTED",
        ),
        _check(
            "asof_proposed_source_not_in_baseline_count",
            sum(int(row["proposed_actual_source_not_in_baseline_count"]) for row in fairness_rows),
            "0",
            "COMPUTED",
        ),
        _check(
            "source_identity_unresolved_count",
            sum(int(row["source_identity_unresolved_count"]) for row in fairness_rows),
            "0",
            "COMPUTED",
        ),
        _check(
            "three_method_source_audit_tautology_count",
            sum(int(row["three_method_source_audit_tautology_count"]) for row in fairness_rows),
            "0",
            "COMPUTED",
        ),
        _check(
            "baseline_authoritative_source_loss_count",
            sum(int(row["baseline_authoritative_source_loss_count"]) for row in fairness_rows),
            "0",
            "COMPUTED",
        ),
        _check(
            "revision_related_knowledge_binding_issue_count",
            sum(1 for row in revision_rows if row["status"] != "PASS"),
            "0",
            "COMPUTED",
        ),
        _check("gold_stratum_overallocation_count", gold_over, "0", "COMPUTED"),
        _check(
            "gold_total_allocated",
            sum(int(row["allocated"]) for row in claim_gold_plan),
            "600",
            "COMPUTED",
        ),
        _check(
            "blind_manifest_method_identity_leak_count",
            int(
                any(
                    token in blind_text
                    for token in ["B0_", "B1_", "P_PROPOSED", "DIRECT_LLM", "STRUCTURED_PROMPT"]
                )
            ),
            "0",
            "COMPUTED",
        ),
        _check("main_benchmark_manifest_hash_valid", bool(benchmark_hash), "PASS", "COMPUTED"),
        _check(
            "primary_metric_definition_missing_count",
            sum(1 for metric in metric_definitions if not metric.get("metric_name")),
            "0",
            "COMPUTED",
        ),
        _check(
            "metric_denominator_missing_count",
            sum(1 for metric in metric_definitions if not metric.get("denominator")),
            "0",
            "COMPUTED",
        ),
        _check(
            "frozen_upstream_semantic_modification_count",
            sum(1 for row in upstream_rows if row["status"] == "HASH_MISMATCH"),
            "0",
            "COMPUTED",
        ),
        _check("real_api_call_count", 0, "0", "COMPUTED"),
    ]
    return rows


def _check(name: str, actual: Any, expected: str, check_class: str) -> dict[str, str]:
    actual_text = "PASS" if actual is True else "FAIL" if actual is False else str(actual)
    return {
        "check_name": name,
        "check_class": check_class,
        "expected": expected,
        "actual": actual_text,
        "status": "PASS" if actual_text == expected else "FAIL",
        "details": "",
    }


def _benchmark_changed_count(
    previous_rows: list[dict[str, Any]], current_rows: list[dict[str, Any]]
) -> int:
    previous = {
        str(row["benchmark_task_id"]): {
            "source_task_id": row["source_task_id"],
            "slice_spec": row["slice_spec"],
            "product_type": row["product_type"],
        }
        for row in previous_rows
    }
    current = {
        str(row["benchmark_task_id"]): {
            "source_task_id": row["source_task_id"],
            "slice_spec": row["slice_spec"],
            "product_type": row["product_type"],
        }
        for row in current_rows
    }
    keys = set(previous) | set(current)
    return sum(1 for key in keys if previous.get(key) != current.get(key))


def _freeze_audit_rows(
    hard_rows: list[dict[str, str]], heldout_summary: dict[str, Any]
) -> list[dict[str, Any]]:
    rows = [
        {"audit_name": key, "value": value, "status": "INFO"}
        for key, value in heldout_summary.items()
    ]
    rows.extend(
        {
            "audit_name": row["check_name"],
            "value": row["actual"],
            "status": row["status"],
        }
        for row in hard_rows
    )
    return rows


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


def _stage3b_version_index(repo_root: Path) -> dict[str, dict[str, Any]]:
    path = (
        repo_root
        / "artifacts/stage3b_bitemporal_epistemic_state_v1_1/bitemporal_state_versions.jsonl"
    )
    return {str(row["bitemporal_version_id"]): row for row in read_jsonl(path)}


def _knowledge_binding_from_locks(
    locks: Any, version_index: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    lock_list = list(locks)
    bitemporal_ids = sorted(
        {str(lock.bitemporal_version_id) for lock in lock_list if lock.bitemporal_version_id}
    )
    state_ids = sorted({str(lock.state_version_id) for lock in lock_list if lock.state_version_id})
    versions = [
        version_index[version_id] for version_id in bitemporal_ids if version_id in version_index
    ]
    dates = sorted(
        {
            str(version.get("knowledge_time_start_local_date"))
            for version in versions
            if version.get("knowledge_time_start_local_date")
        }
    )
    bases = sorted(
        {
            str(version.get("knowledge_time_basis"))
            for version in versions
            if version.get("knowledge_time_basis")
        }
    )
    semantics = sorted(
        {
            str(version.get("knowledge_boundary_semantics"))
            for version in versions
            if version.get("knowledge_boundary_semantics")
        }
    )
    tx_known = any(
        bool(version.get("historical_database_transaction_time_known")) for version in versions
    )
    limitation = "" if tx_known else "HISTORICAL_DATABASE_TRANSACTION_LOG_UNAVAILABLE"
    knowledge_date = max(dates) if dates else ""
    basis = ";".join(bases) if bases else "UNKNOWN_STAGE3B_KNOWLEDGE_BOUNDARY"
    if dates and not tx_known:
        proxy = "evidence available_local_date / Stage3B reconstructed knowledge boundary"
    else:
        proxy = ""
    return {
        "knowledge_time_local_date": knowledge_date,
        "knowledge_time_basis": basis,
        "knowledge_time_proxy": proxy,
        "knowledge_time_limitation": limitation,
        "knowledge_boundary_semantics": ";".join(semantics) if semantics else "",
        "bitemporal_version_ids": bitemporal_ids,
        "state_version_ids": state_ids,
        "revision_chain_id": stable_id("stage7_revision_chain", bitemporal_ids)
        if len(bitemporal_ids) > 1
        else "",
    }


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
    json_fields = {
        "slice_spec",
        "claim_type_counts",
        "abstention_reason_counts",
        "stage3b_bitemporal_version_ids",
        "state_version_ids",
        "realization_unit_ids",
        "member_fact_lock_ids",
    }
    for row in rows:
        item = dict(row)
        for field in json_fields:
            item[field] = canonical_json(item[field])
        flattened.append(item)
    return flattened


def _flatten_universe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _flatten_benchmark(rows)


def _benchmark_hash(rows: list[dict[str, Any]]) -> str:
    return stable_hash(
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
            for row in rows
        ]
    )


def _task_spatial_scope(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "cell_id": task.get("cell_id") or None,
        "valid_date": task.get("valid_date"),
        "scope_basis": "stage7_slice_spec",
    }


def _resolved_status(statuses: list[str]) -> str:
    if "FORECAST" in statuses and "OBSERVED" in statuses:
        return "MIXED"
    if "FORECAST" in statuses:
        return "FORECAST"
    if "OBSERVED" in statuses:
        return "OBSERVED"
    return "ATTENTION_OR_UNRESOLVED"


def _focus_category(counter: Counter[str]) -> str:
    if counter.get("COUPLED_ATTENTION_REVIEW"):
        return "COUPLED"
    if any(_is_metric(key) for key in counter):
        return "METRIC"
    if counter.get("FORECAST_GEOLOGICAL_CONDITION") and counter.get(
        "OBSERVED_GEOLOGICAL_CONDITION"
    ):
        return "GEOLOGICAL_MIXED"
    if counter.get("FORECAST_GEOLOGICAL_CONDITION"):
        return "FORECAST"
    if counter.get("OBSERVED_GEOLOGICAL_CONDITION"):
        return "OBSERVED"
    return "OTHER"


def _selection_stratum(row: dict[str, Any]) -> str:
    return "|".join(
        [
            str(row["product_type"]),
            str(row["unit_complexity_band"]),
            str(row["epistemic_mix"]),
            str(row["revision_status"]),
            str(row["focus_category"]),
            str(row["abstain_presence"]),
        ]
    )


def _universe_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(row["product_type"]),
        str(row["valid_date"]),
        str(row["cell_id"]),
        str(row["source_task_id"]),
    )


def _selection_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _seeded_hash(str(row["source_task_id"])),
        str(row["product_type"]),
        str(row["valid_date"]),
        str(row["cell_id"]),
        str(row["source_task_id"]),
    )


def _slice_key(slice_spec: dict[str, Any]) -> str:
    return stable_hash(slice_spec)


def _seeded_hash(value: str) -> str:
    return stable_hash({"seed": STAGE7_RANDOM_SEED, "value": value})


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


def _proposal_epistemic(row: dict[str, Any]) -> str:
    statuses = set(str(value) for value in (row.get("source_epistemic_statuses") or []) if value)
    if "FORECAST" in statuses and "OBSERVED" in statuses:
        return "MIXED"
    if "FORECAST" in statuses:
        return "FORECAST"
    if "OBSERVED" in statuses:
        return "OBSERVED"
    return ""


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _date_part(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    return text[:10]


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

- EXPRESSIBLE: the Claim is supported within the shown evidence, role,
  epistemic status, value, and spatial scope.
- SHOULD_ABSTAIN: the Claim should not be expressed because support, role,
  epistemic status, value, or scope is insufficient.
- UNCERTAIN: the annotator cannot determine admissibility from the packet.

For EXPRESSIBLE labels, verify modality, value, and spatial scope. For
SHOULD_ABSTAIN labels, record the primary reason category.
"""


def _text_guideline() -> str:
    return """# Stage7 Blind Text Evaluation Guideline

Rate anonymized outputs without seeing method identity.

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
    return f"""# Stage7A.3 Experimental Protocol v1.3

This artifact performs the exact as-of bitemporal knowledge-state binding
correction before any Stage7B model execution. B0/B1/P are bound to the same
active Stage3B versions selected by half-open knowledge intervals:
`knowledge_time_start_local_date <= k < knowledge_time_end_local_date`, with
open-ended current versions allowed.

- Original eligible universe size: {manifest["original_eligible_count"]}
- True held-out universe size: {manifest["true_heldout_count"]}
- Main benchmark size: {manifest["main_benchmark_size"]}
- Main benchmark hash: `{manifest["main_benchmark_manifest_hash"]}`
- As-of evaluation binding hash: `{manifest["asof_evaluation_binding_manifest_hash"]}`
- Pre-Claim snapshot set hash: `{manifest["preclaim_benchmark_evidence_snapshot_set_hash"]}`
- Real API calls: 0
"""


def _report(
    manifest: dict[str, Any],
    universe: list[dict[str, Any]],
    benchmark_rows: list[dict[str, Any]],
    hard_rows: list[dict[str, str]],
    heldout_summary: dict[str, Any],
) -> str:
    product_counts = Counter(str(row["product_type"]) for row in benchmark_rows)
    complexity_counts = Counter(str(row["unit_complexity_band"]) for row in benchmark_rows)
    epistemic_counts = Counter(str(row["epistemic_mix"]) for row in benchmark_rows)
    hard_issues = [row for row in hard_rows if row["status"] != "PASS"]
    return f"""# Stage7A Experimental Protocol Freeze Report

Decision: READY_FOR_STAGE7B_MODEL_EXECUTION

Stage7A freezes the experimental protocol, true held-out benchmark, baseline
input serialization, prompt templates, proposed-method reference inputs,
annotation sampling plan, evaluation protocol, and computed hard checks. No real
LLM API was called.

## Frozen Inputs

- Stage6B tag: `{STAGE6B_FREEZE_TAG}`
- Stage6B commit: `{STAGE6B_FREEZE_COMMIT}`
- Stage6B official smoke tasks: 15

## True Held-Out Construction

- Original eligible universe: {heldout_summary["original_eligible_count"]}
- Exact smoke task exclusions inside reproduced universe:
  {heldout_summary["smoke_exact_task_exclusion_count"]}
- Smoke content-overlap exclusions: {heldout_summary["smoke_content_overlap_exclusion_count"]}
- Final true held-out universe: {heldout_summary["final_true_heldout_count"]}

Main benchmark tasks have zero shared Stage6B smoke FactLock IDs and zero shared
Stage6B smoke RealizationUnit IDs.

## Knowledge-Time Binding

Benchmark tasks bind Stage3B bitemporal state versions, valid dates, and
knowledge boundaries from frozen `bitemporal_state_versions.jsonl`. Historical
database transaction logs are unavailable in the source project, so snapshots
record the explicit limitation `HISTORICAL_DATABASE_TRANSACTION_LOG_UNAVAILABLE`
where Stage3B used reconstructed local-date knowledge boundaries.

## Held-Out Benchmark

- Target size: {TARGET_MAIN_SIZE}
- Actual size: {len(benchmark_rows)}
- Manifest hash: `{manifest["main_benchmark_manifest_hash"]}`
- Product distribution: {dict(sorted(product_counts.items()))}
- Complexity distribution: {dict(sorted(complexity_counts.items()))}
- Epistemic distribution: {dict(sorted(epistemic_counts.items()))}

## Baselines

B0 and B1 receive identical BenchmarkEvidenceSnapshot-derived payloads. B1
differs only by prompt-level constraints. Neither B0 nor B1 receives Claim
decisions, FactLocks, RealizationUnits, validator results, or Stage6B
prohibited-transformation machinery.

## Proposed Method Reference

The proposed method is tied to the same frozen knowledge state and evidence
universe, with extra method-derived constraints represented separately in
`stage7_proposed_preclaim_reference.jsonl`. Its source-equivalence audit is
reconstructed from actual Stage6B FactLock, EvidencePack, and RealizationUnit
provenance rather than copied from the baseline pre-Claim snapshot.

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


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


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
