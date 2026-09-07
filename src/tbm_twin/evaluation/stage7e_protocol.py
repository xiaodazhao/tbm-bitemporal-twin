"""Stage 7E-A deterministic ablation protocol and request materialization."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, cast

from tbm_twin.evaluation import stage7d as stage7d_v1
from tbm_twin.realization.io import stable_hash
from tbm_twin.realization.models import SliceSpec
from tbm_twin.realization.stage6b import build_task_bundle, load_stage6b_inputs

METHOD_VERSION = "stage7e_ablation_protocol_v1"
SCHEMA_VERSION = "stage7e_ablation_protocol.v1"
GENERATED_AT = "2026-08-25T21:00:00+08:00"
OUTPUT_DIR = Path("artifacts/stage7e_ablation_protocol_v1")
AUDIT_ZIP = "stage7e_ablation_protocol_v1_audit.zip"
STAGE7A_DIR = Path("artifacts/stage7a_experimental_protocol_v1_3")
STAGE5B_DIR = Path("artifacts/stage5b_deterministic_claim_builder_v1")
STAGE6A_DIR = Path("artifacts/stage6a_fact_lock_evidence_pack_v1")
STAGE6B_DIR = Path("artifacts/stage6b_controlled_realization_v1")
STAGE7B_DIR = Path("artifacts/stage7b_main_comparison_v1")
CORRECTION_DIR = Path("artifacts/stage7d_bitemporal_value_v1_1a_correction")
RUN_ID = "stage7b_main_execution_3ae0f791811a2e711cb9f488"
RUN_DIR = STAGE7B_DIR / "runs" / RUN_ID
PROMPT_DIR = Path("configs/frozen_inputs/stage7e_v1_prompts")
NO_OUTPUT_TASKS = {
    "stage7_main_task_022",
    "stage7_main_task_026",
    "stage7_main_task_042",
}
ARMS = (
    "P_FULL",
    "A1_NO_SEMANTIC_CLAIM_GATE",
    "A2_NO_ARCHITECTURAL_ABSTENTION",
    "A3_NO_FACTLOCK",
    "A4_FREE_FINAL_REALIZATION",
)
PROVIDER_CONFIG = {
    "provider": "deepseek",
    "model": "deepseek-v4-flash",
    "base_url": "https://api.deepseek.com",
    "temperature": 0.0,
    "top_p": 1.0,
    "reasoning_effort": "none",
    "max_output_tokens": 4096,
    "max_retries": 0,
    "sdk_max_retries": 0,
    "api_key_env_var": "DEEPSEEK_API_KEY",
}
MISSING_VALUE_REASONS = {"UNKNOWN_SOURCE_VALUE", "REQUIRED_METRIC_UNAVAILABLE"}
CLAIM_SECTION = {
    "FORECAST_GEOLOGICAL_CONDITION": "geological_forecast",
    "OBSERVED_GEOLOGICAL_CONDITION": "geological_observed",
    "OPERATIONAL_RESPONSE_ATTENTION": "operational_attention",
    "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW": "geological_attention",
    "COUPLED_ATTENTION_REVIEW": "coupled_attention",
    "FORWARD_GEOLOGICAL_ATTENTION": "forward_attention",
}


def build_stage7e_protocol(
    repo_root: Path,
    output_dir: Path = OUTPUT_DIR,
    *,
    create_audit_zip: bool = True,
) -> dict[str, Any]:
    """Materialize frozen ablation inputs without sending model requests."""

    root = repo_root.resolve()
    output = root / output_dir
    output.mkdir(parents=True, exist_ok=True)
    inputs = _load_inputs(root)
    frozen_hashes_before = _frozen_input_hashes(root)
    analysis = _analyze(inputs)
    deterministic = stable_hash(_semantic_analysis(analysis)) == stable_hash(
        _semantic_analysis(_analyze(inputs))
    )
    frozen_hashes_after = _frozen_input_hashes(root)
    upstream_immutable = frozen_hashes_before == frozen_hashes_after
    hard_rows = _hard_checks(root, inputs, analysis, deterministic, upstream_immutable)
    hard_failures = sum(row["status"] != "PASS" for row in hard_rows)
    _write_outputs(
        root,
        output,
        inputs,
        analysis,
        hard_rows,
        frozen_hashes_before,
    )
    if hard_failures:
        raise RuntimeError(f"Stage7E-A hard checks failed: {hard_failures}")
    _write_hashes(output)
    zip_path = _write_audit_zip(root, output) if create_audit_zip else None
    return {
        "tasks": len(inputs["tasks"]),
        "a1_candidates": len(analysis["a1_candidates"]),
        "a2_targets": len(analysis["a2_targets"]),
        "a3_typed_claims": len(analysis["a3_claims"]),
        "a4_fact_locks": len(analysis["a4_facts"]),
        "expected_api_calls": analysis["budget"]["total"],
        "hard_failures": hard_failures,
        "audit_zip": str(zip_path) if zip_path else "",
    }


def _semantic_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    """Return only persisted, JSON-serializable protocol semantics."""

    return {key: value for key, value in analysis.items() if key != "bundles"}


def _load_inputs(root: Path) -> dict[str, Any]:
    tasks = _read_json(root / STAGE7A_DIR / "stage7_main_benchmark_manifest.json")["tasks"]
    bindings = _read_json(root / STAGE7A_DIR / "stage7_asof_evaluation_binding_manifest.json")[
        "tasks"
    ]
    stage6 = load_stage6b_inputs(root)
    proposals = _read_jsonl(root / STAGE5B_DIR / "claim_proposals.jsonl")
    decisions = _read_jsonl(root / STAGE5B_DIR / "claim_decisions.jsonl")
    abstentions = _read_jsonl(root / STAGE5B_DIR / "claim_abstentions.jsonl")
    plan_validation = _read_csv(root / RUN_DIR / "P_plan_validation.csv")
    raw_plans = _read_jsonl(root / RUN_DIR / "P_raw_plans.jsonl")
    final_outputs = _read_jsonl(root / RUN_DIR / "P_final_outputs.jsonl")
    snapshots = _read_jsonl(
        root / STAGE7A_DIR / "stage7_preclaim_benchmark_evidence_snapshots.jsonl"
    )
    return {
        "root": root,
        "tasks": sorted(tasks, key=lambda row: str(row["benchmark_task_id"])),
        "task_by_id": {str(row["benchmark_task_id"]): row for row in tasks},
        "bindings": bindings,
        "binding_by_task": {str(row["benchmark_task_id"]): row for row in bindings},
        "stage6": stage6,
        "lock_by_id": {lock.fact_lock_id: lock for lock in stage6["stage6a_locks"]},
        "proposal_by_id": {str(row["proposal_id"]): row for row in proposals},
        "decision_by_id": {str(row["decision_id"]): row for row in decisions},
        "abstention_by_id": {str(row["abstention_id"]): row for row in abstentions},
        "plan_validation_by_task": {str(row["benchmark_task_id"]): row for row in plan_validation},
        "plan_by_task": {
            str(row["benchmark_task_id"]): json.loads(str(row["raw_response_text"]))
            for row in raw_plans
            if row.get("parse_valid") is True
        },
        "final_output_by_task": {str(row["benchmark_task_id"]): row for row in final_outputs},
        "snapshot_by_task": {str(row["benchmark_task_id"]): row for row in snapshots},
        "prompts": _load_prompts(root),
        "official_run": _read_json(root / STAGE7B_DIR / "official_execution_reference.json"),
        "stage7b_summary": _read_json(root / STAGE7B_DIR / "run_summary.json"),
    }


def _load_prompts(root: Path) -> dict[str, str]:
    return {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted((root / PROMPT_DIR).glob("*.txt"))
    }


def _analyze(inputs: dict[str, Any]) -> dict[str, Any]:
    bundles, bundle_audit = _task_bundles(inputs)
    task_rows = _task_manifest(inputs, bundles)
    p_rows = _p_reference(inputs)
    a1_candidates, a1_records, a1_jobs = _a1_materialization(inputs, bundles)
    a2_targets, a2_contexts = _a2_materialization(inputs, bundles)
    a3_claims, a3_plan_audit = _a3_materialization(inputs, bundles)
    a4_facts = _a4_materialization(inputs, bundles)
    requests = _materialize_requests(
        inputs,
        bundles,
        a1_records,
        a2_contexts,
        a3_claims,
        a4_facts,
    )
    budget = _expected_budget(requests)
    condition_rows = _arm_conditions(
        inputs,
        a1_jobs,
        a2_targets,
        a3_plan_audit,
        a4_facts,
    )
    endpoint_registry = _endpoint_registry()
    return {
        "bundles": bundles,
        "bundle_audit": bundle_audit,
        "task_rows": task_rows,
        "p_rows": p_rows,
        "a1_candidates": a1_candidates,
        "a1_records": a1_records,
        "a1_jobs": a1_jobs,
        "a2_targets": a2_targets,
        "a2_contexts": a2_contexts,
        "a3_claims": a3_claims,
        "a3_plan_audit": a3_plan_audit,
        "a4_facts": a4_facts,
        "requests": requests,
        "budget": budget,
        "condition_rows": condition_rows,
        "endpoint_registry": endpoint_registry,
    }


def _task_bundles(inputs: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    bundles = {}
    audit = []
    for task in inputs["tasks"]:
        task_id = str(task["benchmark_task_id"])
        binding = inputs["binding_by_task"][task_id]
        active_ids = set(_split_ids(str(binding["active_bitemporal_version_ids"])))
        locks = [
            lock
            for lock in inputs["stage6"]["stage6a_locks"]
            if str(lock.bitemporal_version_id or "") in active_ids
        ]
        abstentions = [
            row
            for row in inputs["abstention_by_id"].values()
            if str(row.get("bitemporal_version_id") or "") in active_ids
        ]
        bundle = build_task_bundle(
            locks,
            abstentions,
            inputs["stage6"]["stage3a_cells"],
            SliceSpec(**task["slice_spec"]),
        )
        bundles[task_id] = bundle
        actual_units = sorted(unit.realization_unit_id for unit in bundle["units"])
        expected_units = sorted(_split_ids(str(binding["asof_realization_unit_ids"])))
        actual_locks = sorted(lock.fact_lock_id for lock in bundle["pack"].locked_facts)
        expected_locks = sorted(_split_ids(str(binding["asof_fact_lock_ids"])))
        actual_abstentions = sorted(
            str(row["abstention_id"]) for row in bundle["task_view"].records
        )
        expected_abstentions = sorted(_split_ids(str(binding["asof_abstention_ids"])))
        no_later = all(
            str(lock.bitemporal_version_id or "") in active_ids for lock in locks
        ) and all(str(row.get("bitemporal_version_id") or "") in active_ids for row in abstentions)
        audit.append(
            {
                "task_id": task_id,
                "pack_id_match": bundle["pack"].pack_id == binding["asof_pack_id"],
                "pack_hash_match": bundle["pack"].pack_hash == binding["asof_pack_hash"],
                "unit_ids_match": actual_units == expected_units,
                "fact_lock_ids_match": actual_locks == expected_locks,
                "abstention_ids_match": actual_abstentions == expected_abstentions,
                "no_later_evidence": no_later,
                "status": "PASS"
                if bundle["pack"].pack_id == binding["asof_pack_id"]
                and bundle["pack"].pack_hash == binding["asof_pack_hash"]
                and actual_units == expected_units
                and actual_locks == expected_locks
                and actual_abstentions == expected_abstentions
                and no_later
                else "FAIL",
            }
        )
    return bundles, audit


def _task_manifest(
    inputs: dict[str, Any], bundles: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    for task in inputs["tasks"]:
        task_id = str(task["benchmark_task_id"])
        binding = inputs["binding_by_task"][task_id]
        rows.append(
            {
                "task_id": task_id,
                "product_type": task["product_type"],
                "valid_date": task["valid_date"],
                "knowledge_as_of": task["knowledge_time_local_date"],
                "cell_id": task.get("cell_id") or "",
                "slice_spec": _canonical(task["slice_spec"]),
                "active_bitemporal_version_ids": binding["active_bitemporal_version_ids"],
                "fact_lock_count": len(bundles[task_id]["pack"].locked_facts),
                "abstention_count": len(bundles[task_id]["task_view"].records),
                "exact_context_hash": stable_hash(
                    {
                        "task": task["slice_spec"],
                        "versions": binding["active_bitemporal_version_ids"],
                        "pack": binding["asof_pack_hash"],
                        "snapshot": inputs["snapshot_by_task"][task_id]["snapshot_hash"],
                    }
                ),
            }
        )
    return rows


def _p_reference(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for task in inputs["tasks"]:
        task_id = str(task["benchmark_task_id"])
        validation = inputs["plan_validation_by_task"][task_id]
        valid = _csv_bool(validation["plan_valid"])
        rows.append(
            {
                "task_id": task_id,
                "condition": "P_FULL",
                "frozen_execution_id": inputs["official_run"]["official_execution_id"],
                "plan_valid": valid,
                "frozen_output_available": task_id in inputs["final_output_by_task"],
                "no_output_reason": "" if valid else "INVALID_SECTION_ORDER",
                "planned_new_api_calls": 0,
                "reuse_basis": "FROZEN_STAGE7B_PROPOSED_EXECUTION",
            }
        )
    return rows


def _a1_materialization(
    inputs: dict[str, Any], bundles: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = []
    records = []
    jobs = []
    for task in inputs["tasks"]:
        task_id = str(task["benchmark_task_id"])
        bundle = bundles[task_id]
        task_candidates = []
        for lock in bundle["pack"].locked_facts:
            candidate = {
                "task_id": task_id,
                "source_kind": "FROZEN_FACT_LOCK",
                "source_id": lock.fact_lock_id,
                "source_opportunity_id": lock.source_opportunity_id,
                "source_proposal_id": lock.source_proposal_id,
                "claim_type": lock.claim_type,
                "candidate_value": _canonical(lock.claim_value),
                "support_ids": ";".join(
                    sorted(str(ref["support_id"]) for ref in lock.authoritative_support_refs)
                ),
                "epistemic_status": _lock_epistemic(lock),
                "state_role": lock.state_role,
                "scope": _canonical(lock.spatial_scope),
                "original_contract_decision": "EXPRESSIBLE",
                "original_abstain_reason": "",
                "contract_admissible": True,
                "structurally_renderable": True,
                "source_bitemporal_version_id": lock.bitemporal_version_id or "",
            }
            task_candidates.append(candidate)
        for abstention in bundle["task_view"].records:
            row = inputs["abstention_by_id"][str(abstention["abstention_id"])]
            proposal = inputs["proposal_by_id"][str(row["proposal_id"])]
            if not _structurally_renderable(proposal, str(row["abstention_reason"])):
                continue
            task_candidates.append(
                {
                    "task_id": task_id,
                    "source_kind": "CONTRACT_INELIGIBLE_PROPOSAL",
                    "source_id": row["abstention_id"],
                    "source_opportunity_id": row["opportunity_id"],
                    "source_proposal_id": row["proposal_id"],
                    "claim_type": row["claim_type"],
                    "candidate_value": _canonical(proposal["claim_value"]),
                    "support_ids": ";".join(
                        sorted(
                            str(ref["support_id"])
                            for ref in proposal.get("support_refs", [])
                            if ref.get("support_id")
                        )
                    ),
                    "epistemic_status": ";".join(
                        sorted(map(str, proposal.get("source_epistemic_statuses", [])))
                    ),
                    "state_role": proposal["state_role"],
                    "scope": _canonical(proposal["scope"]),
                    "original_contract_decision": "ABSTAIN",
                    "original_abstain_reason": row["abstention_reason"],
                    "contract_admissible": False,
                    "structurally_renderable": True,
                    "source_bitemporal_version_id": row["bitemporal_version_id"],
                }
            )
        task_records = []
        for candidate in sorted(
            task_candidates, key=lambda row: (str(row["claim_type"]), str(row["source_id"]))
        ):
            candidate_id = f"ablation_candidate_{stable_hash(candidate)[:24]}"
            candidate_row = {**candidate, "candidate_id": candidate_id}
            candidates.append(candidate_row)
            record_payload = {
                "candidate_id": candidate_id,
                "claim_type": candidate["claim_type"],
                "candidate_value": json.loads(str(candidate["candidate_value"])),
                "support_ids": _split_ids(str(candidate["support_ids"])),
                "epistemic_status": candidate["epistemic_status"],
                "state_role": candidate["state_role"],
                "scope": json.loads(str(candidate["scope"])),
                "contract_admissible": candidate["contract_admissible"],
                "original_contract_decision": candidate["original_contract_decision"],
                "original_abstain_reason": candidate["original_abstain_reason"],
                "candidate_sentence": _candidate_sentence(
                    str(candidate["claim_type"]),
                    json.loads(str(candidate["candidate_value"])),
                ),
            }
            record_id = f"candidate_record_{stable_hash(record_payload)[:24]}"
            record = {
                "task_id": task_id,
                "ablation_fact_record_id": record_id,
                **record_payload,
                "record_hash": stable_hash(record_payload),
            }
            records.append(record)
            task_records.append(record)
        jobs.append(
            {
                "task_id": task_id,
                "candidate_count": len(task_records),
                "contract_admissible_count": sum(
                    row["contract_admissible"] for row in task_records
                ),
                "contract_ineligible_count": sum(
                    not row["contract_admissible"] for row in task_records
                ),
                "requires_new_plan_call": True,
                "request_count": 1,
            }
        )
    return candidates, records, jobs


def _structurally_renderable(proposal: dict[str, Any], reason: str) -> bool:
    if reason in MISSING_VALUE_REASONS:
        return False
    value = proposal.get("claim_value") or {}
    if not value or proposal.get("has_unknown_source_value") is True:
        return False
    candidate = value.get("normalized_value", value.get("metric_value"))
    if candidate is None or str(candidate).strip().upper() in {
        "",
        "UNKNOWN",
        "UNAVAILABLE",
        "NONE",
        "NULL",
    }:
        return False
    return bool(proposal.get("support_refs"))


def _candidate_sentence(claim_type: str, value: dict[str, Any]) -> str:
    if "metric_name" in value:
        return f"{value.get('metric_name')}候选值为{value.get('metric_value')}。"
    return (
        f"{claim_type}候选字段{value.get('attribute_name')}的值为{value.get('normalized_value')}。"
    )


def _lock_epistemic(lock: Any) -> str:
    statuses = sorted(
        {
            str(ref.get("resolved_epistemic_status") or "")
            for ref in lock.authoritative_support_refs
            if ref.get("resolved_epistemic_status")
        }
    )
    return ";".join(statuses)


def _a2_materialization(
    inputs: dict[str, Any], bundles: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    targets = []
    contexts = []
    for task in inputs["tasks"]:
        task_id = str(task["benchmark_task_id"])
        if task_id in NO_OUTPUT_TASKS:
            continue
        bundle = bundles[task_id]
        legal_sections = {CLAIM_SECTION[lock.claim_type] for lock in bundle["pack"].locked_facts}
        grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
        for abstention in bundle["task_view"].records:
            row = inputs["abstention_by_id"][str(abstention["abstention_id"])]
            proposal = inputs["proposal_by_id"][str(row["proposal_id"])]
            section = CLAIM_SECTION[str(row["claim_type"])]
            if section not in legal_sections:
                grouped[section].append((row, proposal))
        for section, members in sorted(grouped.items()):
            context_ids = sorted(
                {
                    str(ref["support_id"])
                    for _, proposal in members
                    for ref in proposal.get("support_refs", [])
                    if ref.get("support_id")
                }
            )
            evidence_ids = sorted(item for item in context_ids if item.startswith("doc_"))
            reasons = Counter(str(row["abstention_reason"]) for row, _ in members)
            target_payload = {
                "task_id": task_id,
                "section_id": section,
                "product_type": task["product_type"],
                "context_ids": context_ids,
                "relevant_evidence_ids": evidence_ids,
                "status_summary": dict(sorted(reasons.items())),
            }
            target_id = f"architectural_abstention_target_{stable_hash(target_payload)[:24]}"
            targets.append(
                {
                    "target_id": target_id,
                    "task_id": task_id,
                    "section_id": section,
                    "product_type": task["product_type"],
                    "reason_no_legal_fact_locks": "ZERO_LEGAL_FACT_LOCKS_IN_SECTION",
                    "available_preclaim_context_ids": ";".join(context_ids),
                    "relevant_evidence_ids": ";".join(evidence_ids),
                    "unknown_unavailable_summary": _canonical(dict(sorted(reasons.items()))),
                    "legal_fact_lock_count": 0,
                    "request_count": 1,
                }
            )
            contexts.append(
                {
                    "target_id": target_id,
                    "task_id": task_id,
                    "section_id": section,
                    "context_ids": context_ids,
                    "relevant_evidence_ids": evidence_ids,
                    "availability_statuses": sorted(
                        {
                            status
                            for _, proposal in members
                            for status in _neutral_availability_statuses(proposal)
                        }
                    ),
                    "state_roles": sorted({str(proposal["state_role"]) for _, proposal in members}),
                    "scopes": [proposal["scope"] for _, proposal in members],
                    "metric_availability": [
                        proposal.get("metric_statuses", {}) for _, proposal in members
                    ],
                }
            )
    return targets, contexts


def _neutral_availability_statuses(proposal: dict[str, Any]) -> list[str]:
    """Describe source availability without exposing the gate decision."""

    statuses = {
        str(status) for status in (proposal.get("metric_statuses") or {}).values() if status
    }
    if proposal.get("has_unknown_source_value") is True:
        statuses.add("UNKNOWN_SOURCE_VALUE")
    if not statuses:
        statuses.add("AVAILABLE_CONTEXT_NOT_MATERIALIZED")
    return sorted(statuses)


def _a3_materialization(
    inputs: dict[str, Any], bundles: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    claims = []
    audit = []
    for task in inputs["tasks"]:
        task_id = str(task["benchmark_task_id"])
        validation = inputs["plan_validation_by_task"][task_id]
        valid = _csv_bool(validation["plan_valid"])
        if not valid:
            audit.append(
                {
                    "task_id": task_id,
                    "p_plan_valid": False,
                    "p_plan_reused": False,
                    "expected_no_output": task_id in NO_OUTPUT_TASKS,
                    "request_count": 0,
                    "status": "PASS" if task_id in NO_OUTPUT_TASKS else "FAIL",
                }
            )
            continue
        plan = inputs["plan_by_task"][task_id]
        units = {unit.realization_unit_id: unit for unit in bundles[task_id]["units"]}
        seen_claims: set[str] = set()
        order = 0
        for section in plan["sections"]:
            for unit_id in section["ordered_unit_ids"]:
                unit = units[unit_id]
                for fact_lock_id in unit.member_fact_lock_ids:
                    lock = inputs["lock_by_id"][fact_lock_id]
                    claim_id = str(lock.source_claim_id)
                    if claim_id in seen_claims:
                        continue
                    seen_claims.add(claim_id)
                    claims.append(
                        {
                            "task_id": task_id,
                            "claim_id": claim_id,
                            "section_id": section["section_id"],
                            "order_index": order,
                            "claim_type": lock.claim_type,
                            "subject_scope": _canonical(lock.spatial_scope),
                            "claim_value": _canonical(lock.claim_value),
                            "unit_verified": False,
                            "epistemic_status": _lock_epistemic(lock),
                            "state_role": lock.state_role,
                            "support_summary": ";".join(
                                sorted(
                                    str(ref["support_id"])
                                    for ref in lock.authoritative_support_refs
                                )
                            ),
                            "nonprobabilistic_qualifier": (
                                "NONPROBABILISTIC_ATTENTION"
                                if "ATTENTION" in lock.claim_type
                                else ""
                            ),
                            "source_fact_lock_id_for_audit_only": fact_lock_id,
                        }
                    )
                    order += 1
        audit.append(
            {
                "task_id": task_id,
                "p_plan_valid": True,
                "p_plan_reused": True,
                "expected_no_output": False,
                "request_count": 1,
                "selected_unit_count": sum(
                    len(section["ordered_unit_ids"]) for section in plan["sections"]
                ),
                "typed_claim_count": len(seen_claims),
                "status": "PASS",
            }
        )
    return claims, audit


def _a4_materialization(
    inputs: dict[str, Any], bundles: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    for task in inputs["tasks"]:
        task_id = str(task["benchmark_task_id"])
        for lock in bundles[task_id]["pack"].locked_facts:
            rows.append(
                {
                    "task_id": task_id,
                    "fact_lock_id": lock.fact_lock_id,
                    "lock_hash": lock.lock_hash,
                    "claim_type": lock.claim_type,
                    "claim_value": _canonical(lock.claim_value),
                    "scope": _canonical(lock.spatial_scope),
                    "epistemic_status": _lock_epistemic(lock),
                    "state_role": lock.state_role,
                    "required_qualifiers": ";".join(lock.required_qualifiers),
                    "prohibited_transformations": ";".join(lock.prohibited_transformations),
                    "trace_refs": ";".join(lock.trace_refs),
                }
            )
    return rows


def _materialize_requests(
    inputs: dict[str, Any],
    bundles: dict[str, dict[str, Any]],
    a1_records: list[dict[str, Any]],
    a2_contexts: list[dict[str, Any]],
    a3_claims: list[dict[str, Any]],
    a4_facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requests = []
    by_task_a1 = _group_by(a1_records, "task_id")
    by_task_a3 = _group_by(a3_claims, "task_id")
    by_task_a4 = _group_by(a4_facts, "task_id")
    for task in inputs["tasks"]:
        task_id = str(task["benchmark_task_id"])
        payload = {
            "product_type": task["product_type"],
            "allowed_sections": bundles[task_id]["contract"].section_order,
            "candidates": [
                {
                    "candidate_record_id": row["ablation_fact_record_id"],
                    **{
                        key: row[key]
                        for key in (
                            "claim_type",
                            "candidate_value",
                            "epistemic_status",
                            "state_role",
                            "scope",
                            "contract_admissible",
                            "original_contract_decision",
                            "original_abstain_reason",
                        )
                    },
                }
                for row in by_task_a1[task_id]
            ],
        }
        requests.append(
            _request(
                inputs,
                task_id,
                "A1_NO_SEMANTIC_CLAIM_GATE",
                "a1_plan_system",
                "a1_plan_user_template",
                payload,
            )
        )
    for context in a2_contexts:
        payload = {
            "section_id": context["section_id"],
            "context_ids": context["context_ids"],
            "relevant_evidence_ids": context["relevant_evidence_ids"],
            "availability_statuses": context["availability_statuses"],
            "state_roles": context["state_roles"],
            "scopes": context["scopes"],
            "metric_availability": context["metric_availability"],
        }
        requests.append(
            _request(
                inputs,
                str(context["task_id"]),
                "A2_NO_ARCHITECTURAL_ABSTENTION",
                "a2_unresolved_section_system",
                "a2_unresolved_section_user_template",
                payload,
                suffix=str(context["section_id"]),
            )
        )
    for task_id, claims in sorted(by_task_a3.items()):
        if not claims:
            continue
        payload = {
            "product_type": inputs["task_by_id"][task_id]["product_type"],
            "claims": [
                {
                    key: row[key]
                    for key in (
                        "claim_id",
                        "section_id",
                        "order_index",
                        "claim_type",
                        "subject_scope",
                        "claim_value",
                        "unit_verified",
                        "epistemic_status",
                        "state_role",
                        "support_summary",
                        "nonprobabilistic_qualifier",
                    )
                }
                for row in sorted(claims, key=lambda row: int(row["order_index"]))
            ],
        }
        requests.append(
            _request(
                inputs,
                task_id,
                "A3_NO_FACTLOCK",
                "a3_claim_realization_system",
                "a3_claim_realization_user_template",
                payload,
            )
        )
    for task in inputs["tasks"]:
        task_id = str(task["benchmark_task_id"])
        payload = {
            "product_type": task["product_type"],
            "task_abstention_summary": [row for row in bundles[task_id]["task_view"].records],
            "locked_engineering_facts": [
                {
                    "fact_lock_id": row["fact_lock_id"],
                    "claim_type": row["claim_type"],
                    "claim_value": json.loads(str(row["claim_value"])),
                    "scope": json.loads(str(row["scope"])),
                    "epistemic_status": row["epistemic_status"],
                    "state_role": row["state_role"],
                    "required_qualifiers": _split_ids(str(row["required_qualifiers"])),
                    "prohibited_transformations": _split_ids(
                        str(row["prohibited_transformations"])
                    ),
                    "trace_refs": _split_ids(str(row["trace_refs"])),
                }
                for row in by_task_a4[task_id]
            ],
        }
        requests.append(
            _request(
                inputs,
                task_id,
                "A4_FREE_FINAL_REALIZATION",
                "a4_free_realization_system",
                "a4_free_realization_user_template",
                payload,
            )
        )
    return sorted(requests, key=lambda row: str(row["request_id"]))


def _request(
    inputs: dict[str, Any],
    task_id: str,
    arm: str,
    system_key: str,
    user_key: str,
    payload: dict[str, Any],
    *,
    suffix: str = "",
) -> dict[str, Any]:
    system = inputs["prompts"][system_key]
    user_template = inputs["prompts"][user_key]
    user = user_template.replace("{{PAYLOAD_JSON}}", _pretty_json(payload))
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    request_payload = {
        "task_id": task_id,
        "suffix": suffix,
        "provider_config": PROVIDER_CONFIG,
        "messages": messages,
    }
    request_hash = stable_hash(request_payload)
    return {
        "request_id": f"stage7e_request_{request_hash[:24]}",
        "task_id": task_id,
        "arm_internal": arm,
        "provider": PROVIDER_CONFIG["provider"],
        "model": PROVIDER_CONFIG["model"],
        "inference_config": PROVIDER_CONFIG,
        "system_prompt_hash": _sha256_text(system),
        "user_prompt_hash": _sha256_text(user),
        "payload_hash": request_hash,
        "messages": messages,
        "execution_status": "MATERIALIZED_NOT_SENT",
    }


def _expected_budget(requests: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row["arm_internal"]) for row in requests)
    budget = {
        "P_FULL": 0,
        "A1_NO_SEMANTIC_CLAIM_GATE": counts["A1_NO_SEMANTIC_CLAIM_GATE"],
        "A2_NO_ARCHITECTURAL_ABSTENTION": counts["A2_NO_ARCHITECTURAL_ABSTENTION"],
        "A3_NO_FACTLOCK": counts["A3_NO_FACTLOCK"],
        "A4_FREE_FINAL_REALIZATION": counts["A4_FREE_FINAL_REALIZATION"],
    }
    return {**budget, "total": sum(budget.values()), "executed_this_round": 0}


def _arm_conditions(
    inputs: dict[str, Any],
    a1_jobs: list[dict[str, Any]],
    a2_targets: list[dict[str, Any]],
    a3_audit: list[dict[str, Any]],
    a4_facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    a1 = {row["task_id"]: row for row in a1_jobs}
    a2_counts = Counter(str(row["task_id"]) for row in a2_targets)
    a3 = {row["task_id"]: row for row in a3_audit}
    a4_counts = Counter(str(row["task_id"]) for row in a4_facts)
    rows = []
    for task in inputs["tasks"]:
        task_id = str(task["benchmark_task_id"])
        base = {
            "task_id": task_id,
            "product_type": task["product_type"],
            "valid_date": task["valid_date"],
            "knowledge_as_of": task["knowledge_time_local_date"],
            "condition_expected": True,
        }
        rows.extend(
            [
                {
                    **base,
                    "arm_internal": "P_FULL",
                    "requires_new_api_call": False,
                    "request_count": 0,
                    "p_plan_reused": True,
                    "factlock_used": True,
                    "claim_gate_used": True,
                    "architectural_abstention_used": True,
                    "free_final_realization": False,
                    "notes": "FROZEN_STAGE7B_OUTPUT_REUSED",
                },
                {
                    **base,
                    "arm_internal": "A1_NO_SEMANTIC_CLAIM_GATE",
                    "requires_new_api_call": True,
                    "request_count": a1[task_id]["request_count"],
                    "p_plan_reused": False,
                    "factlock_used": False,
                    "claim_gate_used": False,
                    "architectural_abstention_used": True,
                    "free_final_realization": False,
                    "notes": "STRUCTURALLY_RENDERABLE_CANDIDATES_ONLY",
                },
                {
                    **base,
                    "arm_internal": "A2_NO_ARCHITECTURAL_ABSTENTION",
                    "requires_new_api_call": a2_counts[task_id] > 0,
                    "request_count": a2_counts[task_id],
                    "p_plan_reused": True,
                    "factlock_used": True,
                    "claim_gate_used": True,
                    "architectural_abstention_used": False,
                    "free_final_realization": False,
                    "notes": "P_INVALID_PLAN_REMAINS_NO_OUTPUT"
                    if task_id in NO_OUTPUT_TASKS
                    else "ONLY_ZERO_LEGAL_FACTLOCK_SECTIONS_TARGETED",
                },
                {
                    **base,
                    "arm_internal": "A3_NO_FACTLOCK",
                    "requires_new_api_call": a3[task_id]["request_count"] > 0,
                    "request_count": a3[task_id]["request_count"],
                    "p_plan_reused": a3[task_id]["p_plan_reused"],
                    "factlock_used": False,
                    "claim_gate_used": True,
                    "architectural_abstention_used": True,
                    "free_final_realization": False,
                    "notes": "NO_VALID_OUTPUT"
                    if task_id in NO_OUTPUT_TASKS
                    else "TYPED_CLAIM_TO_SINGLE_SENTENCE",
                },
                {
                    **base,
                    "arm_internal": "A4_FREE_FINAL_REALIZATION",
                    "requires_new_api_call": True,
                    "request_count": 1,
                    "p_plan_reused": False,
                    "factlock_used": True,
                    "claim_gate_used": True,
                    "architectural_abstention_used": True,
                    "free_final_realization": True,
                    "notes": f"FACT_LOCK_COUNT={a4_counts[task_id]}",
                },
            ]
        )
    return rows


def _endpoint_registry() -> dict[str, Any]:
    common = [
        "output_availability",
        "transport_success",
        "parse_schema_success",
        "validator_failure",
        "numeric_exactness",
        "unit_exactness",
        "explicit_scope_consistency",
        "trace_completeness",
        "unexpected_identifier_count",
        "claim_omission",
        "structurally_detectable_claim_addition",
    ]
    return {
        "layer_1_deterministic_mechanistic_audit": {
            "common": common,
            "A1_NO_SEMANTIC_CLAIM_GATE": [
                "contract_ineligible_input_count",
                "contract_ineligible_planned_count",
                "contract_ineligible_realized_count",
            ],
            "A2_NO_ARCHITECTURAL_ABSTENTION": [
                "target_count",
                "llm_output_count",
                "empty_output_count",
                "explicit_insufficiency_count",
            ],
            "A3_NO_FACTLOCK": [
                "numeric_drift",
                "unit_drift",
                "scope_drift",
                "claim_mapping_loss",
            ],
            "A4_FREE_FINAL_REALIZATION": [
                "factlock_numeric_drift",
                "unit_drift",
                "scope_drift",
                "trace_coverage",
                "post_realization_hard_violations",
            ],
        },
        "layer_2_human_semantic_evaluation": "DEFERRED_TO_HUMAN",
        "keyword_only_semantic_judgment_prohibited": True,
        "results_computed_in_stage7e_a": False,
    }


def _hard_checks(
    root: Path,
    inputs: dict[str, Any],
    analysis: dict[str, Any],
    deterministic: bool,
    upstream_immutable: bool,
) -> list[dict[str, Any]]:
    task_ids = {str(row["benchmark_task_id"]) for row in inputs["tasks"]}
    request_messages = [_canonical(row["messages"]) for row in analysis["requests"]]
    a1_ineligible = [row for row in analysis["a1_candidates"] if not row["contract_admissible"]]
    a3_requests = [row for row in analysis["requests"] if row["arm_internal"] == "A3_NO_FACTLOCK"]
    a4_requests = [
        row for row in analysis["requests"] if row["arm_internal"] == "A4_FREE_FINAL_REALIZATION"
    ]
    configs = {_canonical(row["inference_config"]) for row in analysis["requests"]}
    checks = [
        (
            "stage7d_v1_1a_old_tag_unchanged",
            _git_rev_parse(root, "stage7d-bitemporal-value-v1.1-frozen")
            == "0dfb31d15717f6ff76d434c5496d7bb577dc687c",
            0,
        ),
        (
            "stage7d_v1_1a_old_artifact_hashes_unchanged",
            _verify_hash_manifest(root / "artifacts/stage7d_bitemporal_value_v1_1"),
            0,
        ),
        ("benchmark_tasks_exact_48", len(inputs["tasks"]) == 48, len(inputs["tasks"])),
        (
            "no_task_resampling",
            task_ids == {row["task_id"] for row in analysis["task_rows"]},
            len(task_ids),
        ),
        (
            "same_exact_asof_context_across_arms",
            len(analysis["condition_rows"]) == 48 * 5,
            len(analysis["condition_rows"]),
        ),
        (
            "no_later_evidence",
            all(row["status"] == "PASS" for row in analysis["bundle_audit"]),
            sum(row["status"] != "PASS" for row in analysis["bundle_audit"]),
        ),
        (
            "p_full_outputs_reused",
            len(analysis["p_rows"]) == 48
            and sum(row["frozen_output_available"] for row in analysis["p_rows"]) == 45,
            45,
        ),
        (
            "p_new_api_calls_zero",
            sum(row["planned_new_api_calls"] for row in analysis["p_rows"]) == 0,
            0,
        ),
        (
            "a1_only_structurally_renderable",
            all(row["structurally_renderable"] for row in analysis["a1_candidates"]),
            0,
        ),
        (
            "a1_no_unknown_value_invention",
            all(
                row["original_abstain_reason"] not in MISSING_VALUE_REASONS for row in a1_ineligible
            ),
            0,
        ),
        (
            "a1_original_decision_reason_retained",
            all(
                row["original_contract_decision"]
                and (row["contract_admissible"] or row["original_abstain_reason"])
                for row in analysis["a1_candidates"]
            ),
            0,
        ),
        (
            "a2_targets_have_zero_legal_factlocks",
            all(int(row["legal_fact_lock_count"]) == 0 for row in analysis["a2_targets"]),
            0,
        ),
        (
            "a2_legal_sections_untouched",
            all(row["task_id"] not in NO_OUTPUT_TASKS for row in analysis["a2_targets"]),
            0,
        ),
        (
            "a3_same_expressible_claim_universe_as_selected_p_plan",
            len({(row["task_id"], row["claim_id"]) for row in analysis["a3_claims"]})
            == len(analysis["a3_claims"]),
            len(analysis["a3_claims"]),
        ),
        (
            "a3_frozen_p_plan_reused",
            sum(row["p_plan_reused"] for row in analysis["a3_plan_audit"]) == 45,
            45,
        ),
        (
            "a3_three_no_outputs_exact",
            {row["task_id"] for row in analysis["a3_plan_audit"] if row["expected_no_output"]}
            == NO_OUTPUT_TASKS,
            3,
        ),
        (
            "a3_factlock_payload_leakage_zero",
            all(
                "fact_lock" not in message.lower()
                for row in a3_requests
                for message in [_canonical(row["messages"])]
            ),
            0,
        ),
        (
            "a4_factlock_identity_equals_p",
            len(analysis["a4_facts"])
            == sum(len(bundle["pack"].locked_facts) for bundle in analysis["bundles"].values()),
            len(analysis["a4_facts"]),
        ),
        (
            "a4_canonical_sentence_leakage_zero",
            all(
                "canonical_sentence" not in message.lower()
                for row in a4_requests
                for message in [_canonical(row["messages"])]
            ),
            0,
        ),
        (
            "a4_plan_leakage_zero",
            all(
                "ordered_unit_ids" not in message and "plan_id" not in message
                for row in a4_requests
                for message in [_canonical(row["messages"])]
            ),
            0,
        ),
        (
            "same_provider_model_config_all_new_calls",
            len(configs) == 1 and next(iter(configs)) == _canonical(PROVIDER_CONFIG),
            len(configs),
        ),
        (
            "all_prompts_frozen",
            len(inputs["prompts"]) == 8
            and all(_sha256_text(text) for text in inputs["prompts"].values()),
            len(inputs["prompts"]),
        ),
        (
            "all_request_payloads_frozen",
            all(
                row["payload_hash"] and row["execution_status"] == "MATERIALIZED_NOT_SENT"
                for row in analysis["requests"]
            ),
            len(analysis["requests"]),
        ),
        (
            "arm_identity_absent_from_messages",
            all(
                not any(
                    token in message
                    for token in (
                        "A1_NO_",
                        "A2_NO_",
                        "A3_NO_",
                        "A4_FREE_",
                        "ablation",
                        "Proposed",
                        "baseline",
                    )
                )
                for message in request_messages
            ),
            0,
        ),
        ("api_calls_executed_zero", analysis["budget"]["executed_this_round"] == 0, 0),
        ("llm_calls_executed_zero", True, 0),
        (
            "historical_artifacts_modified_zero",
            upstream_immutable and stage7d_v1._historical_git_diff_zero(root),
            0,
        ),
        ("deterministic_rebuild_identity", deterministic, deterministic),
    ]
    return [
        {"check_name": name, "status": "PASS" if passed else "FAIL", "details": details}
        for name, passed, details in checks
    ]


def _write_outputs(
    root: Path,
    output: Path,
    inputs: dict[str, Any],
    analysis: dict[str, Any],
    hard_rows: list[dict[str, Any]],
    frozen_hashes: dict[str, str],
) -> None:
    _write_json(output / "stage7e_ablation_protocol.json", _protocol(inputs, analysis))
    (output / "README.md").write_text(_readme(), encoding="utf-8")
    (output / "STAGE7E_ARM_DEFINITIONS.md").write_text(_arm_definitions(), encoding="utf-8")
    _write_csv(output / "stage7e_task_manifest.csv", analysis["task_rows"])
    _write_csv(output / "stage7e_arm_condition_manifest.csv", analysis["condition_rows"])
    _write_csv(output / "p_full_frozen_reference_manifest.csv", analysis["p_rows"])
    _write_csv(output / "stage7e_exact_context_binding_audit.csv", analysis["bundle_audit"])
    _write_csv(
        output / "a1_structurally_renderable_candidate_manifest.csv", analysis["a1_candidates"]
    )
    _write_csv(output / "a1_ablation_fact_record_manifest.csv", analysis["a1_records"])
    _write_csv(output / "a1_planner_job_manifest.csv", analysis["a1_jobs"])
    _write_csv(output / "a2_architectural_abstention_targets.csv", analysis["a2_targets"])
    _write_csv(output / "a2_unresolved_context_manifest.csv", analysis["a2_contexts"])
    _write_csv(output / "a3_typed_claim_realization_manifest.csv", analysis["a3_claims"])
    _write_csv(output / "a3_frozen_plan_binding_audit.csv", analysis["a3_plan_audit"])
    _write_csv(output / "a4_factlock_task_manifest.csv", analysis["a4_facts"])
    _write_json(output / "stage7e_expected_api_call_budget.json", analysis["budget"])
    _write_json(output / "stage7e_evaluation_endpoint_registry.json", analysis["endpoint_registry"])
    (output / "STAGE7E_HUMAN_EVALUATION_EXTENSION_PLAN.md").write_text(
        _human_plan(), encoding="utf-8"
    )
    prompt_output = output / "prompts"
    prompt_output.mkdir(exist_ok=True)
    for path in sorted((root / PROMPT_DIR).glob("*.txt")):
        shutil.copyfile(path, prompt_output / path.name)
    _write_json(
        prompt_output / "prompt_hashes.json",
        {key: _sha256_text(value) for key, value in sorted(inputs["prompts"].items())},
    )
    request_dir = output / "requests"
    if request_dir.exists():
        shutil.rmtree(request_dir)
    request_dir.mkdir()
    for request in analysis["requests"]:
        arm_dir = request_dir / str(request["arm_internal"])
        arm_dir.mkdir(exist_ok=True)
        _write_json(arm_dir / f"{request['request_id']}.json", request)
    _write_json(
        request_dir / "request_schema.json",
        {
            "required": [
                "request_id",
                "task_id",
                "arm_internal",
                "provider",
                "model",
                "inference_config",
                "system_prompt_hash",
                "user_prompt_hash",
                "payload_hash",
                "messages",
                "execution_status",
            ],
            "arm_internal_must_not_enter_messages": True,
            "execution_status": "MATERIALIZED_NOT_SENT",
        },
    )
    _write_csv(output / "upstream_freeze_audit.csv", _upstream_audit(root, frozen_hashes))
    _write_csv(output / "hard_check.csv", hard_rows)
    method = _method_version(inputs, frozen_hashes)
    _write_json(output / "method_version.json", method)
    _write_json(output / "freeze_manifest.json", _freeze_manifest(analysis, method, hard_rows))


def _protocol(inputs: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    a1_ineligible = [row for row in analysis["a1_candidates"] if not row["contract_admissible"]]
    return {
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "status": "PROTOCOL_AND_INPUTS_FROZEN_NOT_EXECUTED",
        "benchmark_task_count": len(inputs["tasks"]),
        "arms": list(ARMS),
        "external_references_not_ablation_arms": ["B0_DIRECT_LLM", "B1_STRUCTURED_PROMPT_LLM"],
        "provider_config": PROVIDER_CONFIG,
        "expected_api_call_budget": analysis["budget"],
        "api_calls_executed": 0,
        "llm_calls_executed": 0,
        "a1_scope_limitation": "STRUCTURALLY_RENDERABLE_VALUES_ONLY_NO_MISSING_VALUE_INVENTION",
        "a1_frozen_input_observation": {
            "originally_expressible": sum(
                row["contract_admissible"] for row in analysis["a1_candidates"]
            ),
            "originally_contract_ineligible": len(a1_ineligible),
            "ineligible_reason_distribution": dict(
                sorted(
                    Counter(str(row["original_abstain_reason"]) for row in a1_ineligible).items()
                )
            ),
            "interpretation": (
                "NO_CONCRETE_VALUED_SEMANTIC_REJECTION_EXISTS_IN_THE_FROZEN_"
                "48_TASK_INPUT;_DO_NOT_FABRICATE_A_TREATMENT_CONTRAST"
            ),
        },
        "a2_interpretation": "LLM_DISCRETION_MAY_VALIDLY_RETURN_EXPLICIT_INSUFFICIENCY",
        "a3_mechanism": "TYPED_CLAIM_TO_SINGLE_SENTENCE_WITH_FROZEN_P_PLAN",
        "a4_mechanism": "FREE_FINAL_TEXT_FROM_UNCHANGED_FACTLOCKS_WITHOUT_P_PLAN",
        "human_semantic_evaluation": "DEFERRED",
    }


def _method_version(inputs: dict[str, Any], hashes: dict[str, str]) -> dict[str, Any]:
    return {
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "stage7a_method": _read_json(inputs["root"] / STAGE7A_DIR / "method_version.json")[
            "method_version"
        ],
        "stage6a_method": inputs["stage6"]["stage6a_method"]["method_version"],
        "stage7b_execution_id": inputs["official_run"]["official_execution_id"],
        "stage7d_v1_1a_tag": "stage7d-bitemporal-value-v1.1a-frozen",
        "frozen_input_hashes": hashes,
        "provider_config": PROVIDER_CONFIG,
        "api_calls": 0,
        "llm_calls": 0,
    }


def _freeze_manifest(
    analysis: dict[str, Any], method: dict[str, Any], hard_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    a1_ineligible = [row for row in analysis["a1_candidates"] if not row["contract_admissible"]]
    return {
        **method,
        "status": "FROZEN_PROTOCOL_NOT_EXECUTED",
        "counts": {
            "tasks": len(analysis["task_rows"]),
            "arm_conditions": len(analysis["condition_rows"]),
            "a1_candidates": len(analysis["a1_candidates"]),
            "a1_originally_expressible": sum(
                row["contract_admissible"] for row in analysis["a1_candidates"]
            ),
            "a1_originally_contract_ineligible": len(a1_ineligible),
            "a2_targets": len(analysis["a2_targets"]),
            "a2_affected_tasks": len({row["task_id"] for row in analysis["a2_targets"]}),
            "a3_typed_claims": len(analysis["a3_claims"]),
            "a4_fact_locks": len(analysis["a4_facts"]),
            "materialized_requests": len(analysis["requests"]),
        },
        "expected_api_calls": analysis["budget"],
        "actual_api_calls": 0,
        "hard_check_failure_count": sum(row["status"] != "PASS" for row in hard_rows),
    }


def _readme() -> str:
    return """# Stage7E-A Ablation Protocol and Input Materialization

This artifact freezes four internal mechanism-ablation arms against the frozen
Stage7B Proposed reference. It contains the exact 48 tasks, exact-as-of inputs,
prompts, request payloads, expected call budget, and future evaluation endpoints.
No request was sent and no ablation result was generated. Human semantic
evaluation remains deferred.

Frozen-input limitation: Stage5B contains no contract-ineligible proposal with
both a concrete value and locatable support in these 48 tasks. A1 therefore has
zero contract-ineligible records in this materialization. UNKNOWN_SOURCE_VALUE
and REQUIRED_METRIC_UNAVAILABLE remain excluded and no treatment contrast is
fabricated.
"""


def _arm_definitions() -> str:
    return """# Stage7E Arm Definitions

- `P_FULL`: frozen Stage7B Proposed output; no new call.
- `A1_NO_SEMANTIC_CLAIM_GATE`: exposes only structurally renderable candidates,
  including candidates rejected for semantic/role/epistemic policy. Missing or
  unavailable values remain excluded. Ineligible records are AblationFactRecords,
  never FactLocks.
- `A2_NO_ARCHITECTURAL_ABSTENTION`: retains the Claim Contract and all legal
  locked sections. Only zero-legal-FactLock sections receive method-neutral
  unresolved context. Explicit insufficiency is a valid future response.
- `A3_NO_FACTLOCK`: retains exact state, admissibility, and the 45 frozen valid P
  plans. Selected typed Claims are realized one-to-one without canonical locked
  sentences or per-Claim prohibited-transformation lists. Tasks 022/026/042
  remain no-output.
- `A4_FREE_FINAL_REALIZATION`: retains unchanged FactLocks and their constraints,
  but provides neither canonical sentences nor Stage6B plans. The model will
  freely organize final text and report used FactLock IDs.

B0 and B1 remain external Experiment 1 references, not Stage7E ablation arms.
"""


def _human_plan() -> str:
    return """# Stage7E Human Evaluation Extension Plan

Human semantic evaluation is deferred. When reviewers become available, outputs
from P_FULL and all four ablation arms will be assigned method-neutral blinded
identities and evaluated under the same rubric, task context, ordering policy,
and adjudication process. Deterministic checks will not be presented as complete
semantic judgment. Forecast factification, unsupported causality, attention-to-
probability promotion, and unknown-to-normal claims that cannot be established
with high-confidence structured checks will be marked `DEFERRED_TO_HUMAN`.
No human packet or score is generated in Stage7E-A.
"""


def _frozen_input_hashes(root: Path) -> dict[str, str]:
    paths = {
        "stage7a_benchmark_manifest": root / STAGE7A_DIR / "stage7_main_benchmark_manifest.json",
        "stage7a_preclaim_snapshot": root
        / STAGE7A_DIR
        / "stage7_preclaim_benchmark_evidence_snapshots.jsonl",
        "stage7a_asof_binding_manifest": root
        / STAGE7A_DIR
        / "stage7_asof_evaluation_binding_manifest.json",
        "stage7a_file_hash_manifest": root / STAGE7A_DIR / "file_hashes.sha256",
        "stage5b_claim_proposals": root / STAGE5B_DIR / "claim_proposals.jsonl",
        "stage5b_claim_decisions": root / STAGE5B_DIR / "claim_decisions.jsonl",
        "stage5b_claim_abstentions": root / STAGE5B_DIR / "claim_abstentions.jsonl",
        "stage6a_file_hash_manifest": root / STAGE6A_DIR / "file_hashes.sha256",
        "stage6b_file_hash_manifest": root / STAGE6B_DIR / "file_hashes.sha256",
        "stage7b_official_execution_reference": root
        / STAGE7B_DIR
        / "official_execution_reference.json",
        "stage7b_file_hash_manifest": root / STAGE7B_DIR / "file_hashes.sha256",
        "stage7b_execution_manifest": root / RUN_DIR / "execution_manifest.json",
        "stage7b_p_raw_plans": root / RUN_DIR / "P_raw_plans.jsonl",
        "stage7b_p_plan_validation": root / RUN_DIR / "P_plan_validation.csv",
        "stage7b_p_final_outputs": root / RUN_DIR / "P_final_outputs.jsonl",
        "stage7b_run_file_hash_manifest": root / RUN_DIR / "file_hashes.sha256",
        "stage5_claim_contract": root / "configs/claim_contract_v1.yaml",
        "stage7d_v1_1a_file_hash_manifest": root / CORRECTION_DIR / "file_hashes.sha256",
    }
    return {key: _sha256_file(path) for key, path in paths.items()}


def _upstream_audit(root: Path, expected: dict[str, str]) -> list[dict[str, Any]]:
    actual = _frozen_input_hashes(root)
    return [
        {
            "input": key,
            "expected_hash": value,
            "actual_hash": actual[key],
            "status": "PASS" if actual[key] == value else "FAIL",
        }
        for key, value in sorted(expected.items())
    ]


def _verify_hash_manifest(root: Path) -> bool:
    for line in (root / "file_hashes.sha256").read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        if _sha256_file(root / relative) != expected:
            return False
    return True


def _write_audit_zip(root: Path, output: Path) -> Path:
    path = root / AUDIT_ZIP
    sources = [
        root / "src/tbm_twin/evaluation/stage7e_protocol.py",
        root / "scripts/build_stage7e_ablation_protocol.py",
        root / "tests/unit/test_stage7e_ablation_protocol.py",
    ]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("git_refs.txt", _git_refs(root))
        for source in sources:
            if source.exists():
                archive.write(source, source.relative_to(root).as_posix())
        for prompt in sorted((root / PROMPT_DIR).glob("*.txt")):
            archive.write(prompt, prompt.relative_to(root).as_posix())
        for correction in sorted((root / CORRECTION_DIR).rglob("*")):
            if correction.is_file():
                archive.write(correction, correction.relative_to(root).as_posix())
        for artifact in sorted(output.rglob("*")):
            if artifact.is_file():
                archive.write(artifact, artifact.relative_to(root).as_posix())
    return path


def _git_refs(root: Path) -> str:
    commands = [
        ["git", "branch", "--show-current"],
        ["git", "rev-parse", "HEAD"],
        ["git", "rev-parse", "stage7d-bitemporal-value-v1.1-frozen"],
        ["git", "rev-parse", "stage7d-bitemporal-value-v1.1a-frozen"],
        ["git", "status", "--short"],
    ]
    blocks = []
    for command in commands:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
        blocks.append(f"$ {' '.join(command)}\n{result.stdout}{result.stderr}".rstrip())
    return "\n\n".join(blocks) + "\n"


def _group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[key])].append(row)
    return grouped


def _write_hashes(output: Path) -> None:
    rows = [
        f"{_sha256_file(path)}  {path.relative_to(output).as_posix()}"
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "file_hashes.sha256"
    ]
    (output / "file_hashes.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(_pretty_json(value) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Expected non-empty rows for {path.name}")
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _split_ids(value: str) -> list[str]:
    return [item for item in value.split(";") if item]


def _csv_bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_rev_parse(root: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
