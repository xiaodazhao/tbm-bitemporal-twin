"""Stage7E-A v1.2 executable ablation protocol materialization."""

from __future__ import annotations

import csv
import json
import shutil
import statistics
import subprocess
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from tbm_twin.evaluation.stage7e_protocol import (
    NO_OUTPUT_TASKS,
    PROVIDER_CONFIG,
    STAGE7A_DIR,
    _a2_materialization,
    _a3_materialization,
    _a4_materialization,
    _canonical,
    _frozen_input_hashes,
    _load_inputs,
    _p_reference,
    _pretty_json,
    _read_json,
    _sha256_file,
    _sha256_text,
    _split_ids,
    _task_bundles,
    _task_manifest,
    _write_csv,
    _write_json,
)
from tbm_twin.realization.io import stable_hash

METHOD_VERSION = "stage7e_ablation_protocol_v1_2"
SCHEMA_VERSION = "stage7e_ablation_protocol.v1.2"
GENERATED_AT = "2026-08-25T23:00:00+08:00"
OUTPUT_DIR = Path("artifacts/stage7e_ablation_protocol_v1_2")
AUDIT_ZIP = "stage7e_ablation_protocol_v1_2_audit.zip"
PROMPT_DIR = Path("prompts/stage7e_v1_2")
OLD_V1_BASELINE_DIR = Path("configs/frozen_inputs")
OLD_V1_MANIFEST_SHA256 = "4a9efebfeca24c00cf9fb66aec37ace448e3aff94d5557ce6f360ac22330deb8"
STAGE4_DIR = Path("artifacts/stage4_bitemporal_state_metrics_v1_1")
EXECUTABLE_ARMS = (
    "A2_NO_ARCHITECTURAL_ABSTENTION",
    "A3_NO_FACTLOCK",
    "A4_FREE_FINAL_REALIZATION",
)
ALL_CONDITIONS = (
    "P_FULL",
    "A1_NO_SEMANTIC_CLAIM_GATE",
    *EXECUTABLE_ARMS,
)
A1_TARGET_REASONS = {
    "CONTEXT_ONLY_ROLE",
    "STATE_ROLE_NOT_ALLOWED",
    "REQUIRED_EPISTEMIC_STATUS_MISSING",
}
A3_MAX_CLAIMS = 20
A3_MAX_ESTIMATED_RESPONSE_CHARACTERS = 3000


def build_stage7e_v1_2(
    repo_root: Path,
    output_dir: Path = OUTPUT_DIR,
    *,
    create_audit_zip: bool = True,
) -> dict[str, Any]:
    """Freeze executable A2/A3/A4 requests without sending them."""

    root = repo_root.resolve()
    output = root / output_dir
    output.mkdir(parents=True, exist_ok=True)
    inputs = _load_v1_2_inputs(root)
    hashes_before = _frozen_hashes(root)
    analysis = _analyze(inputs)
    deterministic = stable_hash(_semantic_analysis(analysis)) == stable_hash(
        _semantic_analysis(_analyze(inputs))
    )
    hashes_after = _frozen_hashes(root)
    hard_rows = _hard_checks(
        root,
        inputs,
        analysis,
        deterministic=deterministic,
        upstream_immutable=hashes_before == hashes_after,
    )
    _write_outputs(root, output, inputs, analysis, hard_rows, hashes_before)
    failures = sum(row["status"] != "PASS" for row in hard_rows)
    if failures:
        raise RuntimeError(f"Stage7E-A v1.2 hard checks failed: {failures}")
    _write_hashes(output)
    zip_path = _write_audit_zip(root, output) if create_audit_zip else None
    return {
        "tasks": len(inputs["tasks"]),
        "a1_feasibility_instances": len(analysis["a1_feasibility"]),
        "a1_gate_bypass_candidates": analysis["a1_gate_bypass_count"],
        "a2_targets": len(analysis["a2_targets"]),
        "a3_claims": len(analysis["a3_claims"]),
        "a3_chunks": len(analysis["a3_chunks"]),
        "a4_fact_locks": len(analysis["a4_facts"]),
        "expected_api_calls": analysis["budget"]["total"],
        "hard_failures": failures,
        "audit_zip": str(zip_path) if zip_path else "",
    }


def _load_v1_2_inputs(root: Path) -> dict[str, Any]:
    inputs = _load_inputs(root)
    metric_by_id: dict[str, dict[str, Any]] = {}
    for filename, id_field in (
        ("state_rai.jsonl", "state_rai_id"),
        ("state_grs.jsonl", "state_grs_id"),
        ("state_grci.jsonl", "state_grci_id"),
    ):
        for row in _read_jsonl(root / STAGE4_DIR / filename):
            metric_by_id[str(row[id_field])] = {
                **row,
                "_source_artifact": str(STAGE4_DIR / filename),
            }
    inputs["metric_by_id"] = metric_by_id
    inputs["prompts_v1_2"] = {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted((root / PROMPT_DIR).glob("*.txt"))
    }
    return inputs


def _analyze(inputs: dict[str, Any]) -> dict[str, Any]:
    bundles, bundle_audit = _task_bundles(inputs)
    task_rows = _task_manifest(inputs, bundles)
    p_rows = _p_reference(inputs)
    a1_feasibility = _a1_feasibility(inputs, bundles)
    a2_targets, legacy_contexts = _a2_materialization(inputs, bundles)
    a2_contexts, a2_resolution = _resolve_a2_contexts(inputs, a2_targets, legacy_contexts)
    a3_claims, a3_plan_audit = _a3_materialization(inputs, bundles)
    a3_chunks = _chunk_a3_claims(a3_claims)
    a4_facts = _a4_materialization(inputs, bundles)
    a4_registry, a4_roundtrip = _normalize_a4_payloads(a4_facts)
    requests = _materialize_requests(
        inputs,
        a2_contexts,
        a3_chunks,
        a4_registry,
        bundles,
    )
    a3_chunk_rows, a3_budget_rows = _finalize_a3_chunk_audits(a3_chunks, requests)
    a4_size = _a4_size_comparison(inputs["root"], requests)
    leak_rows = _message_leak_audit(requests)
    budget = _expected_budget(requests)
    condition_rows = _condition_manifest(
        inputs,
        a2_targets,
        a3_plan_audit,
        a3_chunk_rows,
        a4_facts,
    )
    return {
        "bundles": bundles,
        "bundle_audit": bundle_audit,
        "task_rows": task_rows,
        "p_rows": p_rows,
        "a1_feasibility": a1_feasibility,
        "a1_gate_bypass_count": sum(row["gate_bypass_candidate"] for row in a1_feasibility),
        "a2_targets": a2_targets,
        "a2_contexts": a2_contexts,
        "a2_resolution": a2_resolution,
        "a3_claims": a3_claims,
        "a3_plan_audit": a3_plan_audit,
        "a3_chunks": a3_chunks,
        "a3_chunk_rows": a3_chunk_rows,
        "a3_budget_rows": a3_budget_rows,
        "a4_facts": a4_facts,
        "a4_registry": a4_registry,
        "a4_roundtrip": a4_roundtrip,
        "a4_size": a4_size,
        "requests": requests,
        "leak_rows": leak_rows,
        "budget": budget,
        "condition_rows": condition_rows,
    }


def _semantic_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in analysis.items() if key != "bundles"}


def _a1_feasibility(
    inputs: dict[str, Any], bundles: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    for task in inputs["tasks"]:
        task_id = str(task["benchmark_task_id"])
        snapshot_ids = {
            str(item["evidence_id"])
            for item in inputs["snapshot_by_task"][task_id]["preclaim_evidence_items"]
        }
        for task_record in bundles[task_id]["task_view"].records:
            abstention = inputs["abstention_by_id"][str(task_record["abstention_id"])]
            reason = str(abstention["abstention_reason"])
            if reason not in A1_TARGET_REASONS:
                continue
            proposal = inputs["proposal_by_id"][str(abstention["proposal_id"])]
            for support in proposal.get("support_refs", []):
                support_id = str(support["support_id"])
                source = inputs["metric_by_id"].get(support_id)
                status, value = _metric_status_value(source)
                exact_asof = bool(
                    source
                    and str(source.get("bitemporal_version_id"))
                    == str(abstention["bitemporal_version_id"])
                    and support_id in snapshot_ids
                )
                resolvable = bool(
                    source and status == "AVAILABLE" and value is not None and exact_asof
                )
                rows.append(
                    {
                        "task_id": task_id,
                        "abstention_id": abstention["abstention_id"],
                        "opportunity_id": abstention["opportunity_id"],
                        "proposal_id": abstention["proposal_id"],
                        "original_decision": "ABSTAIN",
                        "original_abstain_reason": reason,
                        "claim_type": abstention["claim_type"],
                        "state_role": abstention["state_role"],
                        "support_id": support_id,
                        "support_kind": support["support_kind"],
                        "support_status": status,
                        "resolved_candidate_value": "" if value is None else value,
                        "value_resolution_source_artifact": ""
                        if source is None
                        else source["_source_artifact"],
                        "value_resolution_basis": (
                            "FROZEN_AVAILABLE_STAGE4_SUPPORT_VALUE"
                            if resolvable
                            else "NO_AVAILABLE_CONCRETE_VALUE"
                        ),
                        "bitemporal_version_id": abstention["bitemporal_version_id"],
                        "exact_asof_match": exact_asof,
                        "gate_bypass_candidate": resolvable,
                        "no_value_fabrication": not resolvable,
                        "audit_semantics": "DESIGN_FEASIBILITY_NOT_MODEL_PERFORMANCE",
                    }
                )
    return rows


def _metric_status_value(source: dict[str, Any] | None) -> tuple[str, Any]:
    if source is None:
        return "SUPPORT_NOT_FOUND", None
    for name in ("rai", "grs", "grci"):
        if f"{name}_status" in source:
            return str(source[f"{name}_status"]), source.get(name)
    return "UNSUPPORTED_METRIC_OBJECT", None


def _resolve_a2_contexts(
    inputs: dict[str, Any],
    targets: list[dict[str, Any]],
    legacy_contexts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    target_by_id = {str(row["target_id"]): row for row in targets}
    contexts = []
    audit = []
    for legacy in legacy_contexts:
        task_id = str(legacy["task_id"])
        snapshot = inputs["snapshot_by_task"][task_id]
        snapshot_by_id = {
            str(item["evidence_id"]): item for item in snapshot["preclaim_evidence_items"]
        }
        items = []
        for context_id in legacy["context_ids"]:
            source = snapshot_by_id.get(str(context_id))
            compact = _compact_context_item(str(context_id), source)
            items.append(compact)
            has_semantics = bool(
                compact.get("exact_value") is not None
                or compact.get("unavailable_explanation")
                or compact.get("structured_attributes")
            )
            audit.append(
                {
                    "target_id": legacy["target_id"],
                    "task_id": task_id,
                    "section_id": legacy["section_id"],
                    "context_id": context_id,
                    "resolved_content_type": compact["content_type"],
                    "has_actual_value": compact.get("exact_value") is not None,
                    "explicitly_unavailable": compact["availability"] == "UNAVAILABLE",
                    "source_artifact": compact["source_artifact"],
                    "exact_asof_match": source is not None,
                    "opaque_only": not has_semantics,
                    "status": "PASS" if source is not None and has_semantics else "FAIL",
                }
            )
        contexts.append(
            {
                "target_id": legacy["target_id"],
                "task_id": task_id,
                "section_id": legacy["section_id"],
                "product_type": target_by_id[str(legacy["target_id"])]["product_type"],
                "valid_date": inputs["task_by_id"][task_id]["valid_date"],
                "knowledge_as_of": inputs["task_by_id"][task_id]["knowledge_time_local_date"],
                "engineering_context_items": items,
                "context_resolution_status": (
                    "PASS"
                    if items
                    and all(
                        item.get("exact_value") is not None
                        or item.get("unavailable_explanation")
                        or item.get("structured_attributes")
                        for item in items
                    )
                    else "FAIL"
                ),
            }
        )
    return contexts, audit


def _compact_context_item(context_id: str, source: dict[str, Any] | None) -> dict[str, Any]:
    if source is None:
        return {
            "context_id": context_id,
            "content_type": "MISSING_CONTEXT",
            "availability": "UNAVAILABLE",
            "exact_value": None,
            "unavailable_explanation": "当前冻结快照中没有对应上下文对象。",
            "source_artifact": "",
        }
    family = str(source.get("evidence_family") or "")
    if family == "STAGE4_ATTENTION_METRIC":
        value = source.get("raw_value")
        status = str(source.get("metric_status") or "UNKNOWN")
        return {
            "context_id": context_id,
            "content_type": "NONPROBABILISTIC_ATTENTION_METRIC",
            "metric_name": source.get("metric_name"),
            "availability": "AVAILABLE"
            if status == "AVAILABLE" and value is not None
            else "UNAVAILABLE",
            "metric_status": _public_metric_status(status),
            "exact_value": value,
            "metric_semantics": (source.get("structured_source_attributes") or {}).get(
                "semantic_description"
            )
            or (source.get("structured_source_attributes") or {}).get("operator_name"),
            "state_role": source.get("state_role"),
            "scope": source.get("spatial_scope"),
            "unavailable_explanation": ""
            if status == "AVAILABLE" and value is not None
            else _availability_explanation(status),
            "source_artifact": source.get("source_object"),
            "actual_available_time": source.get("actual_available_time"),
        }
    attributes = {
        key: value
        for key, value in (source.get("structured_source_attributes") or {}).items()
        if value not in (None, "", [], {})
        and key
        in {
            "lithology",
            "weathering",
            "rock_mass_state",
            "joint_development",
            "suggested_grade",
            "risk_hint",
            "water_type",
            "water_state",
            "anomaly_level",
        }
    }
    return {
        "context_id": context_id,
        "content_type": family or "ENGINEERING_CONTEXT",
        "availability": "AVAILABLE" if attributes else "UNAVAILABLE",
        "exact_value": None,
        "source_type": source.get("source_type"),
        "epistemic_status": source.get("epistemic_status"),
        "applicability_role": source.get("applicability_role"),
        "scope": source.get("spatial_scope"),
        "structured_attributes": attributes,
        "unavailable_explanation": "" if attributes else "当前冻结快照没有可表达的结构化工程属性。",
        "source_artifact": source.get("source_object"),
        "actual_available_time": source.get("actual_available_time"),
    }


def _availability_explanation(status: str) -> str:
    explanations = {
        "NO_CELL_LINKED_OPERATIONAL_RESPONSE": (
            "当前空间状态没有可连接的施工机械响应; 指标不可用。"
        ),
        "NO_MAPPED_GEOLOGICAL_ATTENTION_DIMENSION": (
            "当前没有映射为地质关注维度的结构化地质值; 指标不可用。"
        ),
        "RAI_UNAVAILABLE": "施工响应关注指标当前不可用; 耦合关注指标无法计算。",
        "INSUFFICIENT_CAUSAL_BASELINE": "因果参考样本不足; 施工响应关注指标不可用。",
        "GRCI_NOT_DEFINED_FOR_LOCAL_BACKGROUND": ("局部背景角色不定义耦合关注指标。"),
    }
    return explanations.get(status, f"当前指标状态为{status}; 没有可用数值。")


def _public_metric_status(status: str) -> str:
    if status == "INSUFFICIENT_CAUSAL_BASELINE":
        return "UNAVAILABLE_INSUFFICIENT_REFERENCE_DATA"
    return status


def _chunk_a3_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks = []
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        by_task[str(claim["task_id"])].append(claim)
    for task_id, task_claims in sorted(by_task.items()):
        ordered = sorted(task_claims, key=lambda row: int(row["order_index"]))
        current: list[dict[str, Any]] = []
        current_chars = 32
        task_chunks = []
        for claim in ordered:
            estimate = _estimated_claim_response_characters(claim)
            if current and (
                len(current) >= A3_MAX_CLAIMS
                or current_chars + estimate > A3_MAX_ESTIMATED_RESPONSE_CHARACTERS
            ):
                task_chunks.append((current, current_chars))
                current = []
                current_chars = 32
            current.append(claim)
            current_chars += estimate
        if current:
            task_chunks.append((current, current_chars))
        for chunk_index, (members, estimate) in enumerate(task_chunks):
            payload = {
                "task_id": task_id,
                "chunk_index": chunk_index,
                "claim_ids": [row["claim_id"] for row in members],
            }
            chunks.append(
                {
                    "chunk_id": f"a3_chunk_{stable_hash(payload)[:24]}",
                    "task_id": task_id,
                    "chunk_index": chunk_index,
                    "claims": members,
                    "claim_count": len(members),
                    "estimated_minimum_response_characters": estimate,
                    "within_budget": len(members) <= A3_MAX_CLAIMS
                    and estimate <= A3_MAX_ESTIMATED_RESPONSE_CHARACTERS,
                }
            )
    return chunks


def _estimated_claim_response_characters(claim: dict[str, Any]) -> int:
    value = json.loads(str(claim["claim_value"]))
    scope = json.loads(str(claim["subject_scope"]))
    value_text = str(value.get("normalized_value", value.get("metric_value", "")))
    scope_text = _canonical(scope)
    return 96 + len(str(claim["claim_id"])) + len(value_text) + min(len(scope_text), 220)


def _normalize_a4_payloads(
    facts: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    prohibited_sets = {tuple(_split_ids(str(row["prohibited_transformations"]))) for row in facts}
    global_prohibited = list(next(iter(prohibited_sets))) if prohibited_sets else []
    qualifiers = sorted({tuple(_split_ids(str(row["required_qualifiers"]))) for row in facts})
    scopes = sorted({str(row["scope"]) for row in facts})
    qualifier_registry = {
        f"Q{index:03d}": list(value) for index, value in enumerate(qualifiers, start=1)
    }
    scope_registry = {
        f"S{index:03d}": json.loads(value) for index, value in enumerate(scopes, start=1)
    }
    qualifier_id = {tuple(value): key for key, value in qualifier_registry.items()}
    scope_id = {_canonical(value): key for key, value in scope_registry.items()}
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in facts:
        by_task[str(row["task_id"])].append(row)
    tasks = {}
    audit = []
    for task_id, task_facts in sorted(by_task.items()):
        records = []
        used_qualifiers = set()
        used_scopes = set()
        for fact in sorted(task_facts, key=lambda row: str(row["fact_lock_id"])):
            qid = qualifier_id[tuple(_split_ids(str(fact["required_qualifiers"])))]
            sid = scope_id[str(fact["scope"])]
            used_qualifiers.add(qid)
            used_scopes.add(sid)
            record = {
                "fact_lock_id": fact["fact_lock_id"],
                "claim_type": fact["claim_type"],
                "claim_value": json.loads(str(fact["claim_value"])),
                "epistemic_status": fact["epistemic_status"],
                "state_role": fact["state_role"],
                "scope_id": sid,
                "qualifier_set_id": qid,
                "trace_refs": _split_ids(str(fact["trace_refs"])),
            }
            records.append(record)
            expanded = {
                "fact_lock_id": record["fact_lock_id"],
                "claim_type": record["claim_type"],
                "claim_value": record["claim_value"],
                "scope": scope_registry[sid],
                "epistemic_status": record["epistemic_status"],
                "state_role": record["state_role"],
                "required_qualifiers": qualifier_registry[qid],
                "prohibited_transformations": global_prohibited,
                "trace_refs": record["trace_refs"],
            }
            expected = {
                "fact_lock_id": fact["fact_lock_id"],
                "claim_type": fact["claim_type"],
                "claim_value": json.loads(str(fact["claim_value"])),
                "scope": json.loads(str(fact["scope"])),
                "epistemic_status": fact["epistemic_status"],
                "state_role": fact["state_role"],
                "required_qualifiers": _split_ids(str(fact["required_qualifiers"])),
                "prohibited_transformations": _split_ids(str(fact["prohibited_transformations"])),
                "trace_refs": _split_ids(str(fact["trace_refs"])),
            }
            matches = expanded == expected
            audit.append(
                {
                    "task_id": task_id,
                    "fact_lock_id": fact["fact_lock_id"],
                    "roundtrip_semantic_match": matches,
                    "status": "PASS" if matches else "FAIL",
                }
            )
        tasks[task_id] = {
            "global_prohibited_transformations": global_prohibited,
            "qualifier_registry": {key: qualifier_registry[key] for key in sorted(used_qualifiers)},
            "scope_registry": {key: scope_registry[key] for key in sorted(used_scopes)},
            "facts": records,
        }
    return {
        "global_prohibited_transformation_set_count": len(prohibited_sets),
        "global_prohibited_transformations": global_prohibited,
        "qualifier_registry": qualifier_registry,
        "scope_registry": scope_registry,
        "tasks": tasks,
    }, audit


def _materialize_requests(
    inputs: dict[str, Any],
    a2_contexts: list[dict[str, Any]],
    a3_chunks: list[dict[str, Any]],
    a4_registry: dict[str, Any],
    bundles: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    requests = []
    for context in a2_contexts:
        payload = {
            "section_id": context["section_id"],
            "valid_date": context["valid_date"],
            "knowledge_as_of": context["knowledge_as_of"],
            "engineering_context_items": context["engineering_context_items"],
        }
        requests.append(
            _request(
                inputs,
                str(context["task_id"]),
                "A2_NO_ARCHITECTURAL_ABSTENTION",
                "a2_unresolved_section_system",
                "a2_unresolved_section_user_template",
                payload,
                request_scope=str(context["section_id"]),
            )
        )
    for chunk in a3_chunks:
        payload = {
            "product_type": inputs["task_by_id"][chunk["task_id"]]["product_type"],
            "chunk_index": chunk["chunk_index"],
            "claims": [
                {
                    key: claim[key]
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
                for claim in chunk["claims"]
            ],
        }
        request = _request(
            inputs,
            str(chunk["task_id"]),
            "A3_NO_FACTLOCK",
            "a3_claim_realization_system",
            "a3_claim_realization_user_template",
            payload,
            request_scope=f"chunk_{chunk['chunk_index']:03d}",
        )
        request["chunk_id"] = chunk["chunk_id"]
        requests.append(request)
    for task in inputs["tasks"]:
        task_id = str(task["benchmark_task_id"])
        normalized = a4_registry["tasks"][task_id]
        payload = {
            "product_type": task["product_type"],
            "task_context_limit_count": len(bundles[task_id]["task_view"].records),
            **normalized,
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
    request_scope: str = "task",
) -> dict[str, Any]:
    system = inputs["prompts_v1_2"][system_key]
    user_template = inputs["prompts_v1_2"][user_key]
    user = user_template.replace("{{PAYLOAD_JSON}}", _pretty_json(payload))
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    semantic_payload = {
        "task_id": task_id,
        "request_scope": request_scope,
        "provider_config": PROVIDER_CONFIG,
        "messages": messages,
    }
    payload_hash = stable_hash(semantic_payload)
    return {
        "request_id": f"stage7e_v1_2_request_{payload_hash[:24]}",
        "task_id": task_id,
        "request_scope": request_scope,
        "arm_internal": arm,
        "provider": PROVIDER_CONFIG["provider"],
        "model": PROVIDER_CONFIG["model"],
        "inference_config": PROVIDER_CONFIG,
        "system_prompt_hash": _sha256_text(system),
        "user_prompt_hash": _sha256_text(user),
        "payload_hash": payload_hash,
        "messages": messages,
        "execution_status": "MATERIALIZED_NOT_SENT",
    }


def _finalize_a3_chunk_audits(
    chunks: list[dict[str, Any]], requests: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    request_by_chunk = {
        str(row["chunk_id"]): row for row in requests if row["arm_internal"] == "A3_NO_FACTLOCK"
    }
    manifests = []
    budgets = []
    for chunk in chunks:
        request = request_by_chunk[str(chunk["chunk_id"])]
        manifest = {
            "chunk_id": chunk["chunk_id"],
            "request_id": request["request_id"],
            "task_id": chunk["task_id"],
            "chunk_index": chunk["chunk_index"],
            "claim_count": chunk["claim_count"],
            "claim_ids": ";".join(str(row["claim_id"]) for row in chunk["claims"]),
            "first_order_index": min(int(row["order_index"]) for row in chunk["claims"]),
            "last_order_index": max(int(row["order_index"]) for row in chunk["claims"]),
            "estimated_minimum_response_characters": chunk["estimated_minimum_response_characters"],
            "within_budget": chunk["within_budget"],
        }
        manifests.append(manifest)
        budgets.append(
            {
                "request_id": request["request_id"],
                "task_id": chunk["task_id"],
                "chunk_index": chunk["chunk_index"],
                "claim_count": chunk["claim_count"],
                "estimated_minimum_response_characters": chunk[
                    "estimated_minimum_response_characters"
                ],
                "input_message_characters": len(_canonical(request["messages"])),
                "within_budget": "PASS" if chunk["within_budget"] else "FAIL",
            }
        )
    return manifests, budgets


def _a4_size_comparison(root: Path, requests: list[dict[str, Any]]) -> dict[str, Any]:
    old_sizes = [
        int(row["canonical_message_characters"])
        for row in json.loads(
            (root / OLD_V1_BASELINE_DIR / "stage7e_v1_a4_request_message_sizes.json").read_text(
                encoding="utf-8"
            )
        )
    ]
    new_sizes = [
        len(_canonical(row["messages"]))
        for row in requests
        if row["arm_internal"] == "A4_FREE_FINAL_REALIZATION"
    ]
    old_max = max(old_sizes)
    new_max = max(new_sizes)
    return {
        "v1": _size_summary(old_sizes),
        "v1_2": _size_summary(new_sizes),
        "max_character_reduction_percentage": ((old_max - new_max) / old_max * 100.0),
        "fact_deletion_count": 0,
        "comparison_basis": "CANONICAL_JSON_MESSAGES_CHARACTER_COUNT",
    }


def _size_summary(values: list[int]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "minimum": min(values),
        "median": statistics.median(values),
        "maximum": max(values),
    }


def _message_leak_audit(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    common = (
        "a2_no_",
        "a3_no_",
        "a4_free_",
        "ablation",
        "proposed",
        "baseline",
        "experiment",
        "论文",
        "方法比较",
    )
    a2_gate = (
        "expressible",
        "abstain",
        "claim contract",
        "original_abstain_reason",
        "state_role_not_allowed",
        "context_only_role",
        "required_epistemic_status_missing",
        "系统认为这部分不能说",
    )
    rows = []
    for request in requests:
        message = _canonical(request["messages"]).lower()
        forbidden = list(common)
        if request["arm_internal"] == "A2_NO_ARCHITECTURAL_ABSTENTION":
            forbidden.extend(a2_gate)
        hits = sorted(token for token in forbidden if token in message)
        rows.append(
            {
                "request_id": request["request_id"],
                "task_id": request["task_id"],
                "arm_internal": request["arm_internal"],
                "forbidden_token_hits": ";".join(hits),
                "leak_count": len(hits),
                "status": "PASS" if not hits else "FAIL",
            }
        )
    return rows


def _expected_budget(requests: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row["arm_internal"]) for row in requests)
    budget = {
        "P_FULL": 0,
        "A1_NO_SEMANTIC_CLAIM_GATE": 0,
        "A2_NO_ARCHITECTURAL_ABSTENTION": counts["A2_NO_ARCHITECTURAL_ABSTENTION"],
        "A3_NO_FACTLOCK": counts["A3_NO_FACTLOCK"],
        "A4_FREE_FINAL_REALIZATION": counts["A4_FREE_FINAL_REALIZATION"],
    }
    return {**budget, "total": sum(budget.values()), "executed_this_round": 0}


def _condition_manifest(
    inputs: dict[str, Any],
    a2_targets: list[dict[str, Any]],
    a3_audit: list[dict[str, Any]],
    a3_chunks: list[dict[str, Any]],
    a4_facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    a2_counts = Counter(str(row["task_id"]) for row in a2_targets)
    a3_chunk_counts = Counter(str(row["task_id"]) for row in a3_chunks)
    a3_by_task = {str(row["task_id"]): row for row in a3_audit}
    a4_counts = Counter(str(row["task_id"]) for row in a4_facts)
    rows = []
    for task in inputs["tasks"]:
        task_id = str(task["benchmark_task_id"])
        common = {
            "task_id": task_id,
            "product_type": task["product_type"],
            "valid_date": task["valid_date"],
            "knowledge_as_of": task["knowledge_time_local_date"],
        }
        rows.extend(
            [
                {
                    **common,
                    "arm_internal": "P_FULL",
                    "execution_status": "FROZEN_OUTPUT_REUSED",
                    "request_count": 0,
                    "notes": "45_OUTPUTS_AND_3_FROZEN_NO_OUTPUTS",
                },
                {
                    **common,
                    "arm_internal": "A1_NO_SEMANTIC_CLAIM_GATE",
                    "execution_status": "NOT_EXECUTABLE",
                    "request_count": 0,
                    "notes": "NO_CONCRETE_GATE_BYPASS_CANDIDATES",
                },
                {
                    **common,
                    "arm_internal": "A2_NO_ARCHITECTURAL_ABSTENTION",
                    "execution_status": "NO_VALID_OUTPUT"
                    if task_id in NO_OUTPUT_TASKS
                    else "REQUEST_MATERIALIZED"
                    if a2_counts[task_id]
                    else "P_OUTPUT_REUSED",
                    "request_count": a2_counts[task_id],
                    "notes": "ZERO_LEGAL_FACTLOCK_SECTION_ONLY",
                },
                {
                    **common,
                    "arm_internal": "A3_NO_FACTLOCK",
                    "execution_status": "NO_VALID_OUTPUT"
                    if task_id in NO_OUTPUT_TASKS
                    else "REQUESTS_MATERIALIZED",
                    "request_count": a3_chunk_counts[task_id],
                    "notes": "FROZEN_P_PLAN_REUSED"
                    if a3_by_task[task_id]["p_plan_reused"]
                    else "FROZEN_P_PLAN_INVALID",
                },
                {
                    **common,
                    "arm_internal": "A4_FREE_FINAL_REALIZATION",
                    "execution_status": "REQUEST_MATERIALIZED",
                    "request_count": 1,
                    "notes": f"FACT_LOCK_COUNT={a4_counts[task_id]}",
                },
            ]
        )
    return rows


def _hard_checks(
    root: Path,
    inputs: dict[str, Any],
    analysis: dict[str, Any],
    *,
    deterministic: bool,
    upstream_immutable: bool,
) -> list[dict[str, Any]]:
    feasibility = analysis["a1_feasibility"]
    a3_claim_pairs = [(str(row["task_id"]), str(row["claim_id"])) for row in analysis["a3_claims"]]
    chunk_claim_pairs = [
        (str(row["task_id"]), claim_id)
        for row in analysis["a3_chunk_rows"]
        for claim_id in _split_ids(str(row["claim_ids"]))
    ]
    old_targets = {
        (str(row["task_id"]), str(row["section_id"]))
        for row in _read_csv(
            root / OLD_V1_BASELINE_DIR / "stage7e_v1_a2_architectural_abstention_targets.csv"
        )
    }
    new_targets = {(str(row["task_id"]), str(row["section_id"])) for row in analysis["a2_targets"]}
    configs = {_canonical(row["inference_config"]) for row in analysis["requests"]}
    checks = [
        (
            "old_stage7e_v1_tag_unchanged",
            _git_rev_parse(root, "stage7e-ablation-protocol-v1-frozen")
            == "32e387e00fe92a5359144aeb3bb5954fecf4e823",
            0,
        ),
        (
            "old_stage7e_v1_artifacts_unchanged",
            _sha256_file(root / OLD_V1_BASELINE_DIR / "stage7e_v1_file_hashes.sha256")
            == OLD_V1_MANIFEST_SHA256,
            0,
        ),
        ("benchmark_tasks_exact_48", len(inputs["tasks"]) == 48, len(inputs["tasks"])),
        (
            "exact_asof_inputs_match",
            all(row["status"] == "PASS" for row in analysis["bundle_audit"]),
            sum(row["status"] != "PASS" for row in analysis["bundle_audit"]),
        ),
        (
            "future_evidence_leak_zero",
            all(row["no_later_evidence"] for row in analysis["bundle_audit"]),
            sum(not row["no_later_evidence"] for row in analysis["bundle_audit"]),
        ),
        ("a1_feasibility_instances_163", len(feasibility) == 163, len(feasibility)),
        (
            "a1_unique_proposals_145",
            len({row["proposal_id"] for row in feasibility}) == 145,
            len({row["proposal_id"] for row in feasibility}),
        ),
        (
            "a1_gate_bypass_candidates_zero",
            analysis["a1_gate_bypass_count"] == 0,
            analysis["a1_gate_bypass_count"],
        ),
        (
            "a1_no_fabricated_candidates",
            all(row["no_value_fabrication"] for row in feasibility),
            sum(not row["no_value_fabrication"] for row in feasibility),
        ),
        (
            "a1_api_calls_zero",
            analysis["budget"]["A1_NO_SEMANTIC_CLAIM_GATE"] == 0,
            analysis["budget"]["A1_NO_SEMANTIC_CLAIM_GATE"],
        ),
        (
            "a2_target_set_identity",
            old_targets == new_targets and len(new_targets) == 31,
            len(new_targets),
        ),
        (
            "a2_affected_tasks_24",
            len({row["task_id"] for row in analysis["a2_targets"]}) == 24,
            len({row["task_id"] for row in analysis["a2_targets"]}),
        ),
        (
            "a2_opaque_only_context_zero",
            not any(row["opaque_only"] for row in analysis["a2_resolution"]),
            sum(row["opaque_only"] for row in analysis["a2_resolution"]),
        ),
        (
            "a2_context_resolution_failure_zero",
            all(row["status"] == "PASS" for row in analysis["a2_resolution"]),
            sum(row["status"] != "PASS" for row in analysis["a2_resolution"]),
        ),
        (
            "a3_typed_claims_exact",
            len(a3_claim_pairs) == 989 and len(set(a3_claim_pairs)) == 989,
            len(a3_claim_pairs),
        ),
        (
            "a3_text_capable_tasks_45",
            len({row["task_id"] for row in analysis["a3_claims"]}) == 45,
            len({row["task_id"] for row in analysis["a3_claims"]}),
        ),
        (
            "a3_three_no_output_tasks_exact",
            {row["task_id"] for row in analysis["a3_plan_audit"] if row["expected_no_output"]}
            == NO_OUTPUT_TASKS,
            3,
        ),
        (
            "a3_every_claim_exactly_once",
            Counter(a3_claim_pairs) == Counter(chunk_claim_pairs),
            len(chunk_claim_pairs),
        ),
        (
            "a3_chunk_claim_limit",
            all(int(row["claim_count"]) <= A3_MAX_CLAIMS for row in analysis["a3_chunk_rows"]),
            max(int(row["claim_count"]) for row in analysis["a3_chunk_rows"]),
        ),
        (
            "a3_output_budget_pass",
            all(row["within_budget"] == "PASS" for row in analysis["a3_budget_rows"]),
            max(
                int(row["estimated_minimum_response_characters"])
                for row in analysis["a3_budget_rows"]
            ),
        ),
        (
            "a3_frozen_p_plan_identity",
            sum(row["p_plan_reused"] for row in analysis["a3_plan_audit"]) == 45,
            45,
        ),
        (
            "a4_tasks_exact_48",
            len(analysis["a4_registry"]["tasks"]) == 48,
            len(analysis["a4_registry"]["tasks"]),
        ),
        (
            "a4_factlocks_exact_1022",
            len(analysis["a4_facts"]) == 1022,
            len(analysis["a4_facts"]),
        ),
        (
            "a4_roundtrip_mismatch_zero",
            all(row["status"] == "PASS" for row in analysis["a4_roundtrip"]),
            sum(row["status"] != "PASS" for row in analysis["a4_roundtrip"]),
        ),
        (
            "a4_one_global_prohibited_list",
            analysis["a4_registry"]["global_prohibited_transformation_set_count"] == 1,
            analysis["a4_registry"]["global_prohibited_transformation_set_count"],
        ),
        (
            "a4_payload_reduced_without_fact_deletion",
            analysis["a4_size"]["v1_2"]["maximum"] < analysis["a4_size"]["v1"]["maximum"]
            and analysis["a4_size"]["fact_deletion_count"] == 0,
            analysis["a4_size"]["max_character_reduction_percentage"],
        ),
        (
            "model_message_leak_zero",
            all(row["status"] == "PASS" for row in analysis["leak_rows"]),
            sum(row["status"] != "PASS" for row in analysis["leak_rows"]),
        ),
        (
            "a3_factlock_message_leak_zero",
            all(
                "fact_lock" not in _canonical(row["messages"]).lower()
                for row in analysis["requests"]
                if row["arm_internal"] == "A3_NO_FACTLOCK"
            ),
            0,
        ),
        (
            "a4_canonical_and_plan_leak_zero",
            all(
                "canonical_sentence" not in _canonical(row["messages"]).lower()
                and "ordered_unit_ids" not in _canonical(row["messages"]).lower()
                and "plan_id" not in _canonical(row["messages"]).lower()
                for row in analysis["requests"]
                if row["arm_internal"] == "A4_FREE_FINAL_REALIZATION"
            ),
            0,
        ),
        (
            "same_model_config_all_executable_arms",
            len(configs) == 1 and next(iter(configs)) == _canonical(PROVIDER_CONFIG),
            len(configs),
        ),
        (
            "all_prompts_frozen",
            len(inputs["prompts_v1_2"]) == 6,
            len(inputs["prompts_v1_2"]),
        ),
        (
            "all_requests_materialized_not_sent",
            all(
                row["payload_hash"] and row["execution_status"] == "MATERIALIZED_NOT_SENT"
                for row in analysis["requests"]
            ),
            len(analysis["requests"]),
        ),
        (
            "p_new_api_calls_zero",
            analysis["budget"]["P_FULL"] == 0,
            analysis["budget"]["P_FULL"],
        ),
        (
            "api_llm_calls_executed_zero",
            analysis["budget"]["executed_this_round"] == 0,
            0,
        ),
        ("upstream_frozen_inputs_immutable", upstream_immutable, 0),
        ("deterministic_rebuild_identity", deterministic, deterministic),
    ]
    return [
        {
            "check_name": name,
            "status": "PASS" if passed else "FAIL",
            "details": details,
        }
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
    (output / "A1_INFEASIBILITY_INTERPRETATION.md").write_text(
        _a1_interpretation(), encoding="utf-8"
    )
    _write_csv(
        output / "a1_generation_ablation_feasibility_audit.csv",
        analysis["a1_feasibility"],
    )
    _write_csv(output / "stage7e_task_manifest.csv", analysis["task_rows"])
    _write_csv(
        output / "stage7e_arm_condition_manifest.csv",
        analysis["condition_rows"],
    )
    _write_csv(output / "p_full_frozen_reference_manifest.csv", analysis["p_rows"])
    _write_csv(
        output / "a2_architectural_abstention_targets.csv",
        analysis["a2_targets"],
    )
    _write_jsonl(
        output / "a2_compact_unresolved_context_manifest.jsonl",
        analysis["a2_contexts"],
    )
    _write_csv(
        output / "a2_context_resolution_audit.csv",
        analysis["a2_resolution"],
    )
    _write_csv(
        output / "a3_typed_claim_realization_manifest.csv",
        analysis["a3_claims"],
    )
    _write_csv(
        output / "a3_frozen_plan_binding_audit.csv",
        analysis["a3_plan_audit"],
    )
    _write_csv(
        output / "a3_request_chunk_manifest.csv",
        analysis["a3_chunk_rows"],
    )
    _write_csv(
        output / "a3_request_output_budget_audit.csv",
        analysis["a3_budget_rows"],
    )
    _write_csv(output / "a4_factlock_task_manifest.csv", analysis["a4_facts"])
    _write_json(
        output / "a4_normalized_payload_registry.json",
        analysis["a4_registry"],
    )
    _write_csv(
        output / "a4_payload_roundtrip_audit.csv",
        analysis["a4_roundtrip"],
    )
    _write_json(output / "a4_request_size_comparison.json", analysis["a4_size"])
    _write_json(output / "stage7e_expected_api_call_budget.json", analysis["budget"])
    _write_json(
        output / "stage7e_evaluation_endpoint_registry.json",
        _endpoint_registry(),
    )
    (output / "STAGE7E_HUMAN_EVALUATION_EXTENSION_PLAN.md").write_text(
        _human_plan(), encoding="utf-8"
    )
    _write_csv(
        output / "stage7e_model_message_leak_audit.csv",
        analysis["leak_rows"],
    )
    _write_csv(
        output / "stage7e_exact_context_binding_audit.csv",
        analysis["bundle_audit"],
    )
    prompt_output = output / "prompts"
    prompt_output.mkdir(exist_ok=True)
    for path in sorted((root / PROMPT_DIR).glob("*.txt")):
        shutil.copyfile(path, prompt_output / path.name)
    _write_json(
        prompt_output / "prompt_hashes.json",
        {key: _sha256_text(value) for key, value in sorted(inputs["prompts_v1_2"].items())},
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
                "request_scope",
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
            "arm_internal_is_internal_metadata_only": True,
            "execution_status": "MATERIALIZED_NOT_SENT",
        },
    )
    _write_csv(
        output / "upstream_freeze_audit.csv",
        _upstream_audit_v1_2(root, frozen_hashes),
    )
    _write_csv(output / "hard_check.csv", hard_rows)
    method = _method_version(inputs, frozen_hashes)
    _write_json(output / "method_version.json", method)
    _write_json(
        output / "freeze_manifest.json",
        _freeze_manifest(analysis, method, hard_rows),
    )


def _protocol(inputs: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    reasons = Counter(str(row["original_abstain_reason"]) for row in analysis["a1_feasibility"])
    statuses = Counter(str(row["support_status"]) for row in analysis["a1_feasibility"])
    return {
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "status": "EXECUTABLE_PROTOCOL_FROZEN_NOT_EXECUTED",
        "benchmark_task_count": len(inputs["tasks"]),
        "reference": "P_FULL",
        "executable_ablation_arms": list(EXECUTABLE_ARMS),
        "non_executable_arm": {
            "arm": "A1_NO_SEMANTIC_CLAIM_GATE",
            "status": "NOT_EXECUTABLE_ON_FROZEN_48_TASK_BENCHMARK",
            "reason": "NO_CONCRETE_GATE_BYPASS_CANDIDATES",
            "feasibility_instances": len(analysis["a1_feasibility"]),
            "unique_proposals": len({row["proposal_id"] for row in analysis["a1_feasibility"]}),
            "reason_distribution": dict(sorted(reasons.items())),
            "support_status_distribution": dict(sorted(statuses.items())),
            "gate_bypass_candidates": analysis["a1_gate_bypass_count"],
            "interpretation": "DESIGN_FEASIBILITY_AUDIT_NOT_MODEL_PERFORMANCE",
        },
        "primary_mechanistic_questions": {
            "A2_NO_ARCHITECTURAL_ABSTENTION": ("ARCHITECTURAL_ABSTENTION_VS_LLM_DISCRETION"),
            "A3_NO_FACTLOCK": "TYPED_CLAIM_TO_LANGUAGE_DRIFT_WITHOUT_FACTLOCK",
            "A4_FREE_FINAL_REALIZATION": ("FREE_FINAL_LANGUAGE_GENERATION_WITH_FROZEN_FACTLOCKS"),
        },
        "a3_chunking": {
            "order": "TASK_THEN_FROZEN_SECTION_THEN_ORDER_INDEX",
            "maximum_claims_per_request": A3_MAX_CLAIMS,
            "maximum_estimated_response_characters": (A3_MAX_ESTIMATED_RESPONSE_CHARACTERS),
            "formula": (
                "32_JSON_WRAPPER_CHARS_PLUS_SUM_OF_96_PLUS_CLAIM_ID_LENGTH_"
                "PLUS_VALUE_TEXT_LENGTH_PLUS_MIN_SCOPE_JSON_LENGTH_220"
            ),
        },
        "a4_payload": "NORMALIZED_LOSSLESS_FACTLOCK_PAYLOAD",
        "provider_config": PROVIDER_CONFIG,
        "expected_api_call_budget": analysis["budget"],
        "api_calls_executed": 0,
        "llm_calls_executed": 0,
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
        "stage7b_execution_id": inputs["official_run"]["official_execution_id"],
        "stage7e_v1_commit": "32e387e00fe92a5359144aeb3bb5954fecf4e823",
        "stage7e_v1_tag": "stage7e-ablation-protocol-v1-frozen",
        "frozen_input_hashes": hashes,
        "provider_config": PROVIDER_CONFIG,
        "api_calls": 0,
        "llm_calls": 0,
    }


def _freeze_manifest(
    analysis: dict[str, Any],
    method: dict[str, Any],
    hard_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        **method,
        "status": "FROZEN_EXECUTABLE_PROTOCOL_NOT_EXECUTED",
        "counts": {
            "tasks": len(analysis["task_rows"]),
            "conditions": len(analysis["condition_rows"]),
            "a1_feasibility_instances": len(analysis["a1_feasibility"]),
            "a1_gate_bypass_candidates": analysis["a1_gate_bypass_count"],
            "a2_targets": len(analysis["a2_targets"]),
            "a2_affected_tasks": len({row["task_id"] for row in analysis["a2_targets"]}),
            "a3_typed_claims": len(analysis["a3_claims"]),
            "a3_chunks": len(analysis["a3_chunks"]),
            "a4_fact_locks": len(analysis["a4_facts"]),
            "materialized_requests": len(analysis["requests"]),
        },
        "expected_api_calls": analysis["budget"],
        "actual_api_calls": 0,
        "hard_check_failure_count": sum(row["status"] != "PASS" for row in hard_rows),
    }


def _readme() -> str:
    return """# Stage7E-A v1.2 Executable Ablation Protocol

This artifact freezes execution inputs for A2, A3, and A4 against the exact
48-task Stage7A.3 benchmark. P_FULL is reused without a new call. A1 is retained
only as a design-feasibility audit and is not executable because no concrete,
available gate-bypass candidate exists in the frozen benchmark.

All requests are materialized but not sent. The artifact contains no model
outputs and no natural-language semantic evaluation results.
"""


def _arm_definitions() -> str:
    return """# Stage7E-A v1.2 Arm Definitions

- `P_FULL`: frozen Stage7B reference; 45 outputs and three frozen no-output tasks.
- `A1_NO_SEMANTIC_CLAIM_GATE`: not executable on this benchmark. Its 163
  feasibility instances resolve to unavailable Stage4 support states, so no
  concrete gate-bypass candidate can be constructed without fabrication.
- `A2_NO_ARCHITECTURAL_ABSTENTION`: keeps the gate and legal FactLocks; only 31
  zero-legal-FactLock sections receive compact exact-as-of engineering context.
- `A3_NO_FACTLOCK`: keeps the frozen accepted P plan and 989 typed Claims, then
  realizes each Claim once in deterministic output-budget chunks.
- `A4_FREE_FINAL_REALIZATION`: keeps all 1022 frozen FactLocks but removes the P
  plan and deterministic prose composition. Its request payload is normalized
  losslessly to avoid repeated constraints.
"""


def _a1_interpretation() -> str:
    return """# A1 Generation Ablation Infeasibility

The frozen benchmark did not contain any candidate with a concrete available
upstream value that was rejected solely by the semantic admissibility gate.
Therefore, a clean generation-level gate-removal treatment could not be
constructed without fabricating information.

冻结 benchmark 中不存在“上游已有具体可用值、但仅因语义准入规则被拒绝”
的候选; 因此无法在不伪造信息的前提下构造干净的 Claim Gate 生成级消融。

This is a design-feasibility audit, not a zero error rate and not evidence that
the Claim Gate has no effect. Evidence about the gate remains available from
Stage5C admissibility analysis, Stage7D revision-paired transitions, and future
human Claim Gold validation. Those analyses are not relabeled as Stage7E A1.
"""


def _human_plan() -> str:
    return """# Stage7E Human Evaluation Extension Plan

Human semantic evaluation remains deferred. Future outputs from P_FULL and the
three executable ablations will use method-label-blinded evaluation under one
rubric. Deterministic audits cover only high-confidence structural, numeric,
unit, scope, identifier, and trace checks. Forecast factification, unsupported
causality, unknown-to-normal promotion, and epistemic language drift remain
`DEFERRED_TO_HUMAN` unless a violation is structurally explicit.
"""


def _endpoint_registry() -> dict[str, Any]:
    common = [
        "transport_success",
        "parse_schema_success",
        "output_availability",
        "numeric_hard_errors",
        "unit_hard_errors",
        "explicit_scope_hard_errors",
    ]
    return {
        "layer_1_deterministic_audit": {
            "common": common,
            "A2_NO_ARCHITECTURAL_ABSTENTION": [
                "explicit_empty_output",
                "structurally_identifiable_explicit_insufficiency",
            ],
            "A3_NO_FACTLOCK": [
                "claim_mapping_completeness",
                "claim_id_addition_or_omission",
                "numeric_drift",
                "unit_drift",
                "scope_drift",
            ],
            "A4_FREE_FINAL_REALIZATION": [
                "factlock_trace_coverage",
                "factlock_omission_or_addition",
                "unknown_identifier_count",
                "numeric_drift",
                "unit_drift",
                "scope_drift",
                "post_realization_deterministic_hard_violations",
            ],
        },
        "deferred_to_human": [
            "forecast_factification",
            "unsupported_causality",
            "unknown_to_normal",
            "unsupported_semantic_claim",
            "epistemic_language_drift",
        ],
        "keyword_only_semantic_judgment_prohibited": True,
        "results_computed_in_stage7e_a_v1_2": False,
    }


def _frozen_hashes(root: Path) -> dict[str, str]:
    hashes = _frozen_input_hashes(root)
    hashes.update(
        {
            "stage4_file_hash_manifest": _sha256_file(root / STAGE4_DIR / "file_hashes.sha256"),
            "stage4_state_rai": _sha256_file(root / STAGE4_DIR / "state_rai.jsonl"),
            "stage4_state_grs": _sha256_file(root / STAGE4_DIR / "state_grs.jsonl"),
            "stage4_state_grci": _sha256_file(root / STAGE4_DIR / "state_grci.jsonl"),
            "stage7e_v1_file_hash_manifest": _sha256_file(
                root / OLD_V1_BASELINE_DIR / "stage7e_v1_file_hashes.sha256"
            ),
        }
    )
    return hashes


def _upstream_audit_v1_2(root: Path, expected: dict[str, str]) -> list[dict[str, Any]]:
    actual = _frozen_hashes(root)
    return [
        {
            "input": key,
            "expected_hash": value,
            "actual_hash": actual[key],
            "status": "PASS" if actual[key] == value else "FAIL",
        }
        for key, value in sorted(expected.items())
    ]


def _write_hashes(output: Path) -> None:
    rows = [
        f"{_sha256_file(path)}  {path.relative_to(output).as_posix()}"
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "file_hashes.sha256"
    ]
    (output / "file_hashes.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(_canonical(row) + "\n" for row in rows), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_audit_zip(root: Path, output: Path) -> Path:
    path = root / AUDIT_ZIP
    sources = [
        root / "src/tbm_twin/evaluation/stage7e_protocol_v1_2.py",
        root / "scripts/build_stage7e_ablation_protocol_v1_2.py",
        root / "tests/unit/test_stage7e_ablation_protocol_v1_2.py",
    ]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("git_refs.txt", _git_refs(root))
        for source in sources:
            if source.exists():
                archive.write(source, source.relative_to(root).as_posix())
        for prompt in sorted((root / PROMPT_DIR).glob("*.txt")):
            archive.write(prompt, prompt.relative_to(root).as_posix())
        for artifact in sorted(output.rglob("*")):
            if artifact.is_file():
                archive.write(artifact, artifact.relative_to(root).as_posix())
    return path


def _git_refs(root: Path) -> str:
    commands = [
        ["git", "branch", "--show-current"],
        ["git", "rev-parse", "HEAD"],
        ["git", "rev-parse", "stage7e-ablation-protocol-v1-frozen"],
        ["git", "status", "--short"],
    ]
    blocks = []
    for command in commands:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        blocks.append(f"$ {' '.join(command)}\n{result.stdout}{result.stderr}".rstrip())
    return "\n\n".join(blocks) + "\n"


def _git_rev_parse(root: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", ref],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
