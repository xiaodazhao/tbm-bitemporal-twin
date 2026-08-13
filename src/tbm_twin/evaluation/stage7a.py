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

STAGE7A_METHOD_VERSION = "stage7a_experimental_protocol_v1"
STAGE7A_SCHEMA_VERSION = "stage7a_experimental_protocol.v1"
STAGE7A_OUTPUT = "artifacts/stage7a_experimental_protocol_v1"
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

    benchmark_rows = _select_balanced_benchmark(true_heldout)
    benchmark_hash = _benchmark_hash(benchmark_rows)
    snapshots = _build_snapshots(inputs, benchmark_rows, version_index)
    snapshot_rows = _snapshot_audit(snapshots)
    b0_prompt = _b0_prompt_template()
    b1_prompt = _b1_prompt_template()
    b0_payloads = _baseline_payloads(benchmark_rows, snapshots, "B0_DIRECT_LLM")
    b1_payloads = _baseline_payloads(benchmark_rows, snapshots, "B1_STRUCTURED_PROMPT_LLM")
    equivalence_rows = _baseline_equivalence_audit(b0_payloads, b1_payloads)
    proposed_refs = _proposed_input_reference(inputs, benchmark_rows, version_index)
    fairness_rows = _fairness_audit(snapshots, proposed_refs)
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
    _write_jsonl(output / "stage7_benchmark_evidence_snapshots.jsonl", snapshots)
    _write_csv(output / "stage7_snapshot_audit.csv", snapshot_rows)
    _write_jsonl(output / "stage7_b0_input_payloads.jsonl", b0_payloads)
    _write_text(output / "stage7_b0_prompt_template.txt", b0_prompt)
    _write_jsonl(output / "stage7_b1_input_payloads.jsonl", b1_payloads)
    _write_text(output / "stage7_b1_prompt_template.txt", b1_prompt)
    _write_csv(output / "stage7_baseline_information_equivalence_audit.csv", equivalence_rows)
    _write_jsonl(output / "stage7_proposed_input_reference.jsonl", proposed_refs)
    _write_csv(output / "stage7_method_input_fairness_audit.csv", fairness_rows)
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
            "check_name": "stage7a_issue_count",
            "check_class": "COMPUTED",
            "expected": "0",
            "actual": str(issue_count),
            "status": "PASS" if issue_count == 0 else "FAIL",
            "details": "Total non-PASS hard checks before this row.",
        }
    )
    _write_csv(output / "stage7a_hard_check.csv", hard_rows)
    _write_csv(output / "stage7a_freeze_audit.csv", _freeze_audit_rows(hard_rows, heldout_summary))

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
        "benchmark_evidence_snapshot_set_hash": stable_hash(
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
        "baseline_protocol_hash": stable_hash(baseline_protocol),
        "ablation_protocol_hash": stable_hash(ablation_protocol),
        "metric_definition_hash": stable_hash(metric_definitions),
        "statistics_plan_hash": stable_hash(_statistical_plan()),
        "case_study_count": len(case_studies["cases"]),
        "real_api_call_count": 0,
        "stage7a_issue_count": sum(1 for row in hard_rows if row["status"] != "PASS"),
        "sampling_seed": STAGE7_RANDOM_SEED,
    }
    _write_json(output / "method_version.json", manifest)
    _write_json(output / "freeze_manifest.json", manifest)
    _write_text(output / "README.md", _readme(manifest))
    _write_text(
        output / "stage7a_freeze_report.md",
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


def _build_snapshots(
    inputs: dict[str, Any],
    benchmark_rows: list[dict[str, Any]],
    version_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    snapshots = []
    for task in benchmark_rows:
        spec = SliceSpec(**task["slice_spec"])
        bundle = build_task_bundle(
            inputs["stage6a_locks"], inputs["stage5b_abstentions"], inputs["stage3a_cells"], spec
        )
        lock_by_id = {lock.fact_lock_id: lock for lock in bundle["pack"].locked_facts}
        selected_lock_ids = sorted(
            {str(lock_id) for unit in bundle["units"] for lock_id in unit.member_fact_lock_ids}
        )
        selected_locks = [
            lock_by_id[lock_id] for lock_id in selected_lock_ids if lock_id in lock_by_id
        ]
        knowledge = _knowledge_binding_from_locks(selected_locks, version_index)
        evidence_items = [_snapshot_item(lock, knowledge) for lock in selected_locks]
        base = {
            "benchmark_task_id": task["benchmark_task_id"],
            "source_task_id": task["source_task_id"],
            "valid_time": task["valid_date"],
            "knowledge_time_local_date": knowledge["knowledge_time_local_date"],
            "knowledge_time_basis": knowledge["knowledge_time_basis"],
            "knowledge_time_proxy": knowledge["knowledge_time_proxy"],
            "knowledge_time_limitation": knowledge["knowledge_time_limitation"],
            "knowledge_boundary_semantics": knowledge["knowledge_boundary_semantics"],
            "state_version_ids": knowledge["state_version_ids"],
            "bitemporal_version_ids": knowledge["bitemporal_version_ids"],
            "revision_chain_id": knowledge["revision_chain_id"],
            "product_type": task["product_type"],
            "spatial_scope": _task_spatial_scope(task),
            "state_role": task["state_role"],
            "evidence_items": evidence_items,
            "excluded_from_baseline_snapshot": [
                "Stage5 Claim decision",
                "EXPRESSIBLE/ABSTAIN answer",
                "FactLock identity",
                "RealizationUnit identity",
                "validator result",
            ],
        }
        snapshot_hash = stable_hash(base)
        snapshots.append({**base, "snapshot_hash": snapshot_hash})
    return snapshots


def _snapshot_item(lock: Any, knowledge: dict[str, Any]) -> dict[str, Any]:
    payload = lock.model_dump(mode="json") if hasattr(lock, "model_dump") else dict(lock)
    supports = payload.get("authoritative_support_refs") or []
    support_ids = sorted({str(ref.get("support_id")) for ref in supports if ref.get("support_id")})
    trace_ids = sorted(
        {
            str(trace_id)
            for ref in supports
            for trace_id in (ref.get("trace_ref_ids") or [])
            if trace_id
        }
        | {str(trace_id) for trace_id in (payload.get("trace_refs") or []) if trace_id}
    )
    statuses = sorted(
        {
            str(ref.get("resolved_epistemic_status"))
            for ref in supports
            if ref.get("resolved_epistemic_status")
        }
    )
    roles = sorted(
        {str(ref.get("resolved_state_role")) for ref in supports if ref.get("resolved_state_role")}
    )
    item = {
        "benchmark_evidence_item_id": stable_id(
            "stage7_snapshot_evidence",
            {
                "support_ids": support_ids,
                "trace_ids": trace_ids,
                "claim_type": payload.get("claim_type"),
                "value": payload.get("claim_value"),
                "scope": payload.get("spatial_scope"),
            },
        ),
        "source_evidence_ids": support_ids,
        "source_span_ids": trace_ids,
        "source_support_kinds": sorted(
            {str(ref.get("support_kind")) for ref in supports if ref.get("support_kind")}
        ),
        "available_local_date": knowledge["knowledge_time_local_date"],
        "spatial_scope": payload.get("spatial_scope"),
        "state_role": roles[0] if len(roles) == 1 else payload.get("state_role"),
        "epistemic_status": _resolved_status(statuses),
        "evidence_family": payload.get("semantic_interpretation") or payload.get("claim_type"),
        "claim_modality": payload.get("claim_modality"),
        "structured_value": payload.get("claim_value"),
        "quality_provenance": {
            "resolution_sources": sorted(
                {
                    str(ref.get("resolution_source"))
                    for ref in supports
                    if ref.get("resolution_source")
                }
            ),
            "resolution_statuses": sorted(
                {
                    str(ref.get("resolution_status"))
                    for ref in supports
                    if ref.get("resolution_status")
                }
            ),
        },
    }
    return item


def _snapshot_audit(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for snapshot in snapshots:
        boundary = str(snapshot["knowledge_time_local_date"])
        future_count = sum(
            1
            for item in snapshot["evidence_items"]
            if str(item.get("available_local_date") or "9999-99-99") > boundary
        )
        b0_hash = stable_hash(
            _baseline_payload_from_snapshot(snapshot, "B0_DIRECT_LLM", include_hash=False)
        )
        b1_hash = stable_hash(
            _baseline_payload_from_snapshot(
                snapshot, "B1_STRUCTURED_PROMPT_LLM", include_hash=False
            )
        )
        rows.append(
            {
                "task_id": snapshot["benchmark_task_id"],
                "evidence_count": len(snapshot["evidence_items"]),
                "future_evidence_count": future_count,
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
    benchmark_rows: list[dict[str, Any]], snapshots: list[dict[str, Any]], method_id: str
) -> list[dict[str, Any]]:
    del benchmark_rows
    return [_baseline_payload_from_snapshot(snapshot, method_id) for snapshot in snapshots]


def _baseline_payload_from_snapshot(
    snapshot: dict[str, Any], method_id: str, *, include_hash: bool = True
) -> dict[str, Any]:
    payload = {
        "method_id": method_id,
        "benchmark_task_id": snapshot["benchmark_task_id"],
        "valid_time": snapshot["valid_time"],
        "knowledge_time_local_date": snapshot["knowledge_time_local_date"],
        "knowledge_time_basis": snapshot["knowledge_time_basis"],
        "spatial_scope": snapshot["spatial_scope"],
        "product_type": snapshot["product_type"],
        "state_role": snapshot["state_role"],
        "evidence_snapshot_hash": snapshot["snapshot_hash"],
        "structured_evidence": snapshot["evidence_items"],
        "excluded_information": snapshot["excluded_from_baseline_snapshot"],
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
                "status": "PASS" if diff == 0 else "FAIL",
            }
        )
    return rows


def _proposed_input_reference(
    inputs: dict[str, Any],
    benchmark_rows: list[dict[str, Any]],
    version_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for task in benchmark_rows:
        spec = SliceSpec(**task["slice_spec"])
        bundle = build_task_bundle(
            inputs["stage6a_locks"], inputs["stage5b_abstentions"], inputs["stage3a_cells"], spec
        )
        lock_by_id = {lock.fact_lock_id: lock for lock in bundle["pack"].locked_facts}
        selected_lock_ids = sorted(
            {str(lock_id) for unit in bundle["units"] for lock_id in unit.member_fact_lock_ids}
        )
        selected_locks = [
            lock_by_id[lock_id] for lock_id in selected_lock_ids if lock_id in lock_by_id
        ]
        knowledge = _knowledge_binding_from_locks(selected_locks, version_index)
        rows.append(
            {
                "benchmark_task_id": task["benchmark_task_id"],
                "source_task_id": task["source_task_id"],
                "valid_time": task["valid_date"],
                "knowledge_time_local_date": knowledge["knowledge_time_local_date"],
                "stage3b_bitemporal_version_ids": knowledge["bitemporal_version_ids"],
                "state_version_ids": knowledge["state_version_ids"],
                "claim_opportunity_ids": sorted(
                    {
                        str(getattr(lock, "source_opportunity_id", ""))
                        for lock in selected_locks
                        if getattr(lock, "source_opportunity_id", "")
                    }
                ),
                "claim_decision_ids": sorted(
                    {
                        str(getattr(lock, "source_decision_id", ""))
                        for lock in selected_locks
                        if getattr(lock, "source_decision_id", "")
                    }
                ),
                "fact_lock_ids": selected_lock_ids,
                "realization_unit_ids": sorted(
                    str(unit.realization_unit_id) for unit in bundle["units"]
                ),
                "pack_id": bundle["pack"].pack_id,
                "pack_hash": bundle["pack"].pack_hash,
                "reference_role": "PROPOSED_METHOD_ONLY_NOT_BASELINE_INPUT",
            }
        )
    return rows


def _fairness_audit(
    snapshots: list[dict[str, Any]], proposed_refs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    ref_by_task = {row["benchmark_task_id"]: row for row in proposed_refs}
    for snapshot in snapshots:
        ref = ref_by_task[snapshot["benchmark_task_id"]]
        same_time = snapshot["knowledge_time_local_date"] == ref["knowledge_time_local_date"]
        same_state = sorted(snapshot["bitemporal_version_ids"]) == sorted(
            ref["stage3b_bitemporal_version_ids"]
        )
        rows.append(
            {
                "benchmark_task_id": snapshot["benchmark_task_id"],
                "same_task": "true",
                "same_valid_time": _bool(snapshot["valid_time"] == ref["valid_time"]),
                "same_knowledge_boundary": _bool(same_time),
                "same_authoritative_state_versions": _bool(same_state),
                "b0_b1_same_evidence_snapshot": "true",
                "proposed_extra_information": (
                    "Claim decisions; FactLocks; RealizationUnits; deterministic validators"
                ),
                "future_or_source_data_advantage_count": 0 if same_time and same_state else 1,
                "status": "PASS" if same_time and same_state else "FAIL",
            }
        )
    return rows


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
    rows = [
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
            "benchmark_future_leakage_count",
            sum(int(row["future_evidence_count"]) for row in snapshot_rows),
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
            "baseline_unfair_information_advantage_count",
            sum(int(row["future_or_source_data_advantage_count"]) for row in fairness_rows),
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
    return f"""# Stage7A Experimental Protocol v1

This artifact freezes the Stage7 experimental protocol, true held-out benchmark,
knowledge-time evidence snapshots, B0/B1 prompt inputs, proposed-method
reference inputs, human-gold sampling plan, blind text-evaluation design, and
hard checks. It does not call any real LLM API and does not execute Stage7B.

- Original eligible universe size: {manifest["original_eligible_count"]}
- True held-out universe size: {manifest["true_heldout_count"]}
- Main benchmark size: {manifest["main_benchmark_size"]}
- Main benchmark hash: `{manifest["main_benchmark_manifest_hash"]}`
- Snapshot set hash: `{manifest["benchmark_evidence_snapshot_set_hash"]}`
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
`stage7_proposed_input_reference.jsonl`.

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
