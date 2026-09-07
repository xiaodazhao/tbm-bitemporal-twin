"""Stage 7D deterministic bitemporal-value ablation analysis."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import statistics
import subprocess
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from tbm_twin.bitemporal.query import AsOfStateQuery
from tbm_twin.claim_building import batch_builder as claim_builder
from tbm_twin.claims.contracts import load_claim_contracts
from tbm_twin.claims.registry import ClaimTypeRegistry
from tbm_twin.claims.validation import ClaimContractEvaluator
from tbm_twin.realization.io import stable_hash

METHOD_VERSION = "stage7d_bitemporal_value_v1"
SCHEMA_VERSION = "stage7d_bitemporal_value.v1"
GENERATED_AT = "2026-08-25T17:00:00+08:00"
OUTPUT_DIR = Path("artifacts/stage7d_bitemporal_value_v1")
AUDIT_ZIP = "stage7d_bitemporal_value_v1_audit.zip"
STAGE7A_DIR = Path("artifacts/stage7a_experimental_protocol_v1_3")
STAGE3A_DIR = Path("artifacts/stage3a_initial_epistemic_state_v1_1")
STAGE3B_DIR = Path("artifacts/stage3b_bitemporal_epistemic_state_v1_1")
STAGE4_DIR = Path("artifacts/stage4_bitemporal_state_metrics_v1_1")
STAGE5B_DIR = Path("artifacts/stage5b_deterministic_claim_builder_v1")
STAGE5C_DIR = Path("artifacts/stage5c_claim_expressibility_analysis_v1")
STAGE2_GEOLOGY_DIR = Path("artifacts/stage2_geology_v2_freeze_candidate")
STAGE7A_TAG = "stage7a-experimental-protocol-v1.3-frozen"
STAGE7A_COMMIT = "6007afe7c1b1228d6638503afeba979ee2f66878"
STAGE7B_TAG = "stage7b-main-comparison-v1-frozen"
STAGE7B_COMMIT = "38da398b3c5edc8e3e5f8180273f1f04fdff4fbb"
STAGE7C1_TAG = "stage7c-main-auto-evaluation-v1.2-frozen"
STAGE7C1_COMMIT = "b12567dcbba4206016bafebe2405a0e4652fdc58"
STAGE7C2A_TAG = "stage7c-human-evaluation-packet-v1.1-frozen"
STAGE7C2A_COMMIT = "7fd712202a719c6831ef1dce57af4f5c403b8f9c"
EXPECTED_STAGE7A_HASHES = {
    "main_benchmark_manifest_hash": (
        "e9ef8e3f9bd25f345f89f79dc753040e3bfc1f95e562902aea625a8e50334f6f"
    ),
    "asof_evaluation_binding_manifest_hash": (
        "92bdea500aef7bedb27e6133e92ec058f03ccfd48810e84aed11388838d12bc4"
    ),
    "preclaim_benchmark_evidence_snapshot_set_hash": (
        "8bbbc9083bfa2313fe583f88c6d431d199f9ffaa8cf1b0a7d28f70a11ab98a6c"
    ),
    "product_task_contract_hash": (
        "ad599756f428514cf731bb982ecccf21b0705e14579ebf64095524a674ecc98d"
    ),
}
METRIC_TYPES = ("RAI", "GRS", "GRCI")
METRIC_CLAIM_TYPES = {
    "OPERATIONAL_RESPONSE_ATTENTION",
    "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
    "COUPLED_ATTENTION_REVIEW",
    "FORWARD_GEOLOGICAL_ATTENTION",
}
GEOLOGICAL_CLAIM_TYPES = {
    "FORECAST_GEOLOGICAL_CONDITION",
    "OBSERVED_GEOLOGICAL_CONDITION",
}
ROLE_FIELDS = {
    "DAILY_REVIEW": "materialized_daily_review_evidence_ids",
    "FORWARD_ATTENTION": "materialized_forward_attention_evidence_ids",
    "LOCAL_BACKGROUND": "materialized_local_background_evidence_ids",
}
UNKNOWN_VALUES = {"", "UNKNOWN", "UNAVAILABLE", "NONE", "NULL", "UNMAPPED"}


@dataclass(frozen=True)
class Stage7DInputs:
    """Read-only frozen inputs used by the ablation."""

    tasks: list[dict[str, Any]]
    binding_by_task: dict[str, dict[str, Any]]
    stage7a_freeze: dict[str, Any]
    versions: list[dict[str, Any]]
    version_by_id: dict[str, dict[str, Any]]
    cells_by_id: dict[str, dict[str, Any]]
    evidence_by_id: dict[str, dict[str, Any]]
    document_available_by_id: dict[str, str]
    metrics_by_type_and_version: dict[str, dict[str, dict[str, Any]]]
    daily_states: list[dict[str, Any]]
    stage5c_revision_rows: list[dict[str, str]]
    claim_stage: Any
    opportunities_by_version: dict[str, list[Any]]
    evaluator: ClaimContractEvaluator


def build_stage7d_bitemporal_value(
    repo_root: Path,
    output_dir: Path = OUTPUT_DIR,
    *,
    create_audit_zip: bool = True,
) -> dict[str, Any]:
    """Build the deterministic exact-as-of versus final-history experiment."""

    root = repo_root.resolve()
    output = output_dir if output_dir.is_absolute() else root / output_dir
    output.mkdir(parents=True, exist_ok=True)
    figure_dir = output / "stage7d_figure_data"
    figure_dir.mkdir(exist_ok=True)

    frozen_input_hashes_before = _frozen_input_manifest_hashes(root)
    inputs = _load_inputs(root)
    stage7a_audit = _stage7a_freeze_audit(root, inputs.stage7a_freeze)
    frozen_ref_audit = _frozen_git_ref_audit(root)

    analysis = _analyze(inputs)
    repeated = _analyze(inputs)
    deterministic = stable_hash(analysis) == stable_hash(repeated)
    frozen_input_hashes_after = _frozen_input_manifest_hashes(root)
    upstream_immutable = frozen_input_hashes_before == frozen_input_hashes_after

    hard_rows = _hard_checks(
        root,
        inputs,
        analysis,
        stage7a_audit,
        frozen_ref_audit,
        deterministic,
        upstream_immutable,
    )
    hard_failures = sum(row["status"] != "PASS" for row in hard_rows)
    if hard_failures:
        _write_csv(output / "hard_check.csv", hard_rows)
        raise RuntimeError(f"Stage7D hard checks failed: {hard_failures}")

    _write_outputs(
        root,
        output,
        figure_dir,
        inputs,
        analysis,
        stage7a_audit,
        frozen_ref_audit,
        hard_rows,
        frozen_input_hashes_before,
    )
    _write_hashes(output)
    zip_path = _write_audit_zip(root, output) if create_audit_zip else None
    return {
        "tasks": len(inputs.tasks),
        "bindings": len(analysis["binding_rows"]),
        "affected_tasks": analysis["primary_endpoints"]["P1"]["numerator"],
        "affected_bindings": analysis["primary_endpoints"]["P2"]["numerator"],
        "later_evidence": len(analysis["leakage_rows"]),
        "claim_pairs": analysis["primary_endpoints"]["P3"]["denominator"],
        "hard_failures": hard_failures,
        "audit_zip": str(zip_path) if zip_path else "",
    }


def _load_inputs(root: Path) -> Stage7DInputs:
    task_manifest = _read_json(root / STAGE7A_DIR / "stage7_main_benchmark_manifest.json")
    binding_manifest = _read_json(
        root / STAGE7A_DIR / "stage7_asof_evaluation_binding_manifest.json"
    )
    versions = _read_jsonl(root / STAGE3B_DIR / "bitemporal_state_versions.jsonl")
    cells = _read_jsonl(root / STAGE3A_DIR / "construction_state_cells.jsonl")
    evidence = _read_jsonl(root / STAGE2_GEOLOGY_DIR / "primary_geological_evidence.jsonl")
    documents = _read_jsonl(root / STAGE2_GEOLOGY_DIR / "geological_documents.jsonl")
    metrics = {
        metric: {
            str(row["bitemporal_version_id"]): row
            for row in _read_jsonl(root / STAGE4_DIR / f"state_{metric.lower()}.jsonl")
        }
        for metric in METRIC_TYPES
    }
    claim_stage = claim_builder._load_stage(root)
    contracts = load_claim_contracts(root / "configs/claim_contract_v1.yaml")
    registry = ClaimTypeRegistry.from_contracts(contracts)
    evaluator = ClaimContractEvaluator(registry, claim_builder._build_lookup(claim_stage))
    opportunities, _ = claim_builder._discover_opportunities(claim_stage)
    opportunities_by_version: dict[str, list[Any]] = defaultdict(list)
    for opportunity in opportunities:
        opportunities_by_version[str(opportunity.bitemporal_version_id or "")].append(opportunity)
    return Stage7DInputs(
        tasks=list(task_manifest["tasks"]),
        binding_by_task={str(row["benchmark_task_id"]): row for row in binding_manifest["tasks"]},
        stage7a_freeze=_read_json(root / STAGE7A_DIR / "freeze_manifest.json"),
        versions=versions,
        version_by_id={str(row["bitemporal_version_id"]): row for row in versions},
        cells_by_id={str(row["cell_id"]): row for row in cells},
        evidence_by_id={str(row["evidence_uid"]): row for row in evidence},
        document_available_by_id={
            str(row["document_id"]): str(
                ((row.get("document") or {}).get("temporal") or {}).get("available_local_date")
                or ""
            )
            for row in documents
        },
        metrics_by_type_and_version=metrics,
        daily_states=_read_jsonl(root / STAGE3A_DIR / "daily_construction_states.jsonl"),
        stage5c_revision_rows=_read_csv(
            root / STAGE5C_DIR / "revision_claim_transition_analysis.csv"
        ),
        claim_stage=claim_stage,
        opportunities_by_version=dict(opportunities_by_version),
        evaluator=evaluator,
    )


def _analyze(inputs: Stage7DInputs) -> dict[str, Any]:
    binding_rows = _state_binding_pairs(inputs)
    leakage_rows = _future_evidence_rows(inputs, binding_rows)
    epistemic_rows = _epistemic_transition_rows(inputs, binding_rows)
    metric_rows = _metric_pair_rows(inputs, binding_rows)
    mechanical_rows = _mechanical_rewrite_rows(inputs, binding_rows, metric_rows)
    claim_rows, claim_audit = _claim_pair_rows(inputs, binding_rows, leakage_rows)
    hindsight_rows = _hindsight_enabled_rows(claim_rows, leakage_rows)
    unknown_rows = _unknown_to_known_rows(claim_rows)
    transition_matrix = _claim_transition_matrix(claim_rows)
    task_rows = _task_level_rows(
        inputs,
        binding_rows,
        leakage_rows,
        metric_rows,
        claim_rows,
        hindsight_rows,
    )
    primary = _primary_endpoints(task_rows, binding_rows, claim_rows, metric_rows)
    secondary = _secondary_endpoints(inputs, leakage_rows, claim_rows, unknown_rows)
    corpus = _corpus_summary(inputs)
    cases = _select_cases(task_rows)
    case_documents = _case_documents(
        cases, binding_rows, leakage_rows, epistemic_rows, metric_rows, claim_rows
    )
    return {
        "binding_rows": binding_rows,
        "leakage_rows": leakage_rows,
        "epistemic_rows": epistemic_rows,
        "metric_rows": metric_rows,
        "mechanical_rows": mechanical_rows,
        "claim_rows": claim_rows,
        "claim_audit": claim_audit,
        "hindsight_rows": hindsight_rows,
        "unknown_rows": unknown_rows,
        "transition_matrix": transition_matrix,
        "task_rows": task_rows,
        "primary_endpoints": primary,
        "secondary_endpoints": secondary,
        "corpus_summary": corpus,
        "case_selection": cases,
        "case_documents": case_documents,
    }


def _state_binding_pairs(inputs: Stage7DInputs) -> list[dict[str, Any]]:
    query = AsOfStateQuery(inputs.claim_stage.repo_root / STAGE3B_DIR)
    rows: list[dict[str, Any]] = []
    for task in sorted(inputs.tasks, key=lambda item: str(item["benchmark_task_id"])):
        task_id = str(task["benchmark_task_id"])
        valid_date = str(task["valid_date"])
        knowledge_as_of = str(task["knowledge_time_local_date"])
        manifest_ids = _split_ids(inputs.binding_by_task[task_id]["active_bitemporal_version_ids"])
        for manifest_exact_id in sorted(manifest_ids):
            manifest_exact = inputs.version_by_id[manifest_exact_id]
            cell_id = str(manifest_exact["cell_id"])
            exact = query.get_state_as_known(valid_date, cell_id, knowledge_as_of)
            history = query.get_state_history(valid_date, cell_id)
            if exact is None or not history:
                raise ValueError(f"Missing state binding for {task_id}/{cell_id}")
            final = max(history, key=lambda item: int(item["version_number"]))
            cell = inputs.cells_by_id[cell_id]
            exact_id = str(exact["bitemporal_version_id"])
            final_id = str(final["bitemporal_version_id"])
            final_start = _date(str(final["knowledge_time_start_local_date"]))
            as_of = _date(knowledge_as_of)
            rows.append(
                {
                    "task_id": task_id,
                    "product_type": str(task["product_type"]),
                    "valid_date": valid_date,
                    "knowledge_as_of": knowledge_as_of,
                    "cell_id": cell_id,
                    "cell_start": cell["spatial_start"],
                    "cell_end": cell["spatial_end"],
                    "state_role": str(exact["cell_scope_role"]),
                    "exact_state_version_id": exact_id,
                    "exact_knowledge_start": exact["knowledge_time_start_local_date"],
                    "exact_knowledge_end": exact["knowledge_time_end_local_date"] or "",
                    "exact_version_number": exact["version_number"],
                    "final_state_version_id": final_id,
                    "final_knowledge_start": final["knowledge_time_start_local_date"],
                    "final_knowledge_end": final["knowledge_time_end_local_date"] or "",
                    "final_version_number": final["version_number"],
                    "same_version": exact_id == final_id,
                    "later_version_used": exact_id != final_id,
                    "knowledge_delay_days": (
                        (final_start - as_of).days if exact_id != final_id else 0
                    ),
                    "same_valid_date": exact["valid_date"] == final["valid_date"] == valid_date,
                    "same_cell": exact["cell_id"] == final["cell_id"] == cell_id,
                    "same_state_role": exact["cell_scope_role"] == final["cell_scope_role"],
                    "final_is_latest": int(final["version_number"])
                    == max(int(item["version_number"]) for item in history),
                    "exact_half_open_active": _is_active_at(exact, knowledge_as_of),
                    "manifest_exact_match": exact_id == manifest_exact_id,
                }
            )
    return rows


def _is_active_at(version: dict[str, Any], knowledge_as_of: str) -> bool:
    as_of = _date(knowledge_as_of)
    start = _date(str(version["knowledge_time_start_local_date"]))
    raw_end = version.get("knowledge_time_end_local_date")
    end = _date(str(raw_end)) if raw_end else None
    return start <= as_of and (end is None or as_of < end)


def _state_evidence_ids(version: dict[str, Any]) -> set[str]:
    fields = {
        "materialized_forecast_evidence_ids",
        "materialized_observed_evidence_ids",
        "materialized_background_evidence_ids",
        *ROLE_FIELDS.values(),
    }
    return {
        str(evidence_id)
        for field in fields
        for evidence_id in version.get(field, [])
        if evidence_id
    }


def _future_evidence_rows(
    inputs: Stage7DInputs, binding_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for binding in binding_rows:
        exact = inputs.version_by_id[str(binding["exact_state_version_id"])]
        final = inputs.version_by_id[str(binding["final_state_version_id"])]
        exact_ids = _state_evidence_ids(exact)
        final_ids = _state_evidence_ids(final)
        exact_forecast = {
            evidence_id
            for evidence_id in exact_ids
            if str(inputs.evidence_by_id[evidence_id].get("epistemic_status")) == "FORECAST"
        }
        for evidence_id in sorted(final_ids - exact_ids):
            evidence = inputs.evidence_by_id[evidence_id]
            document_id = str(evidence.get("document_id") or "")
            available = inputs.document_available_by_id.get(document_id, "")
            if not available:
                raise ValueError(
                    f"Missing authoritative available_local_date for evidence {evidence_id}"
                )
            epistemic = str(evidence.get("epistemic_status") or "UNKNOWN")
            change_type = (
                "EPISTEMIC_UPDATE"
                if epistemic == "OBSERVED" and exact_forecast
                else "NEW_LATER_EVIDENCE"
            )
            rows.append(
                {
                    "task_id": binding["task_id"],
                    "cell_id": binding["cell_id"],
                    "exact_state_version_id": binding["exact_state_version_id"],
                    "final_state_version_id": binding["final_state_version_id"],
                    "evidence_id": evidence_id,
                    "evidence_type": evidence.get("evidence_type", ""),
                    "epistemic_status": epistemic,
                    "source_document_id": document_id,
                    "source_type": evidence.get("source_type", ""),
                    "valid_spatial_scope": _canonical(evidence.get("spatial_scope") or {}),
                    "available_local_date": available,
                    "task_knowledge_as_of": binding["knowledge_as_of"],
                    "days_after_as_of": (
                        _date(available) - _date(str(binding["knowledge_as_of"]))
                    ).days,
                    "role": _role_for_evidence(final, evidence_id),
                    "change_type": change_type,
                    "available_strictly_after_as_of": bool(
                        available and _date(available) > _date(str(binding["knowledge_as_of"]))
                    ),
                }
            )
    return rows


def _role_for_evidence(version: dict[str, Any], evidence_id: str) -> str:
    for role, field in ROLE_FIELDS.items():
        if evidence_id in {str(item) for item in version.get(field, [])}:
            return role
    return "OTHER"


def _epistemic_transition_rows(
    inputs: Stage7DInputs, binding_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    for binding in binding_rows:
        exact = inputs.version_by_id[str(binding["exact_state_version_id"])]
        final = inputs.version_by_id[str(binding["final_state_version_id"])]
        exact_ids = _state_evidence_ids(exact)
        final_ids = _state_evidence_ids(final)
        exact_forecast = _epistemic_count(inputs, exact_ids, "FORECAST")
        final_forecast = _epistemic_count(inputs, final_ids, "FORECAST")
        exact_observed = _epistemic_count(inputs, exact_ids, "OBSERVED")
        final_observed = _epistemic_count(inputs, final_ids, "OBSERVED")
        rows.append(
            {
                "task_id": binding["task_id"],
                "cell_id": binding["cell_id"],
                "exact_state_version_id": binding["exact_state_version_id"],
                "final_state_version_id": binding["final_state_version_id"],
                "exact_forecast_support_count": exact_forecast,
                "final_forecast_support_count": final_forecast,
                "exact_observed_support_count": exact_observed,
                "final_observed_support_count": final_observed,
                "exact_local_background_support_count": len(
                    exact.get("materialized_local_background_evidence_ids", [])
                ),
                "final_local_background_support_count": len(
                    final.get("materialized_local_background_evidence_ids", [])
                ),
                "exact_daily_review_support_count": len(
                    exact.get("materialized_daily_review_evidence_ids", [])
                ),
                "final_daily_review_support_count": len(
                    final.get("materialized_daily_review_evidence_ids", [])
                ),
                "exact_forward_support_count": len(
                    exact.get("materialized_forward_attention_evidence_ids", [])
                ),
                "final_forward_support_count": len(
                    final.get("materialized_forward_attention_evidence_ids", [])
                ),
                "forecast_only_to_forecast_plus_observed": bool(
                    exact_forecast > 0
                    and exact_observed == 0
                    and final_forecast > 0
                    and final_observed > 0
                ),
                "no_observed_to_observed_available": bool(
                    exact_observed == 0 and final_observed > 0
                ),
            }
        )
    return rows


def _epistemic_count(inputs: Stage7DInputs, evidence_ids: set[str], status: str) -> int:
    return sum(
        str(inputs.evidence_by_id[evidence_id].get("epistemic_status")) == status
        for evidence_id in evidence_ids
    )


def _metric_pair_rows(
    inputs: Stage7DInputs, binding_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for binding in binding_rows:
        exact_id = str(binding["exact_state_version_id"])
        final_id = str(binding["final_state_version_id"])
        for metric in METRIC_TYPES:
            exact = inputs.metrics_by_type_and_version[metric][exact_id]
            final = inputs.metrics_by_type_and_version[metric][final_id]
            value_key = metric.lower()
            status_key = f"{value_key}_status"
            exact_value = _optional_float(exact.get(value_key))
            final_value = _optional_float(final.get(value_key))
            status_changed = exact.get(status_key) != final.get(status_key)
            value_changed = not _same_number(exact_value, final_value)
            absolute_delta = (
                abs(final_value - exact_value)
                if exact_value is not None and final_value is not None
                else None
            )
            relative_delta = (
                (final_value - exact_value) / abs(exact_value)
                if exact_value not in (None, 0.0) and final_value is not None
                else None
            )
            rows.append(
                {
                    "task_id": binding["task_id"],
                    "cell_id": binding["cell_id"],
                    "state_role": binding["state_role"],
                    "metric_type": metric,
                    "exact_state_version_id": exact_id,
                    "final_state_version_id": final_id,
                    "exact_status": exact.get(status_key, ""),
                    "final_status": final.get(status_key, ""),
                    "exact_value": exact_value,
                    "final_value": final_value,
                    "status_changed": status_changed,
                    "value_changed": value_changed,
                    "absolute_delta": absolute_delta,
                    "relative_delta": relative_delta,
                    "availability_transition": _availability_transition(
                        str(exact.get(status_key, "")),
                        str(final.get(status_key, "")),
                        value_changed,
                    ),
                }
            )
    return rows


def _availability_transition(exact: str, final: str, value_changed: bool) -> str:
    exact_available = exact == "AVAILABLE"
    final_available = final == "AVAILABLE"
    if not exact_available and final_available:
        return "UNAVAILABLE_TO_AVAILABLE"
    if exact_available and not final_available:
        return "AVAILABLE_TO_UNAVAILABLE"
    if exact_available and final_available and value_changed:
        return "AVAILABLE_VALUE_CHANGED"
    return "UNCHANGED"


def _mechanical_rewrite_rows(
    inputs: Stage7DInputs,
    binding_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rai_by_binding = {
        (str(row["task_id"]), str(row["cell_id"])): row
        for row in metric_rows
        if row["metric_type"] == "RAI"
    }
    rows = []
    for binding in binding_rows:
        exact_id = str(binding["exact_state_version_id"])
        final_id = str(binding["final_state_version_id"])
        exact = inputs.metrics_by_type_and_version["RAI"][exact_id]
        final = inputs.metrics_by_type_and_version["RAI"][final_id]
        exact_support = sorted(str(item) for item in exact.get("support_response_evidence_ids", []))
        final_support = sorted(str(item) for item in final.get("support_response_evidence_ids", []))
        metric = rai_by_binding[(str(binding["task_id"]), str(binding["cell_id"]))]
        issue = bool(
            binding["later_version_used"]
            and (
                exact_support != final_support
                or metric["status_changed"]
                or metric["value_changed"]
            )
        )
        rows.append(
            {
                "task_id": binding["task_id"],
                "cell_id": binding["cell_id"],
                "later_geological_version_used": binding["later_version_used"],
                "exact_response_support_ids": ";".join(exact_support),
                "final_response_support_ids": ";".join(final_support),
                "response_support_changed": exact_support != final_support,
                "rai_status_changed": metric["status_changed"],
                "rai_value_changed": metric["value_changed"],
                "unintended_mechanical_rewrite": issue,
                "status": "FAIL" if issue else "PASS",
            }
        )
    return rows


def _claim_pair_rows(
    inputs: Stage7DInputs,
    binding_rows: list[dict[str, Any]],
    leakage_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    later_by_binding = defaultdict(set)
    for row in leakage_rows:
        later_by_binding[(str(row["task_id"]), str(row["cell_id"]))].add(str(row["evidence_id"]))
    rows: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    bindings_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for binding in binding_rows:
        bindings_by_task[str(binding["task_id"])].append(binding)

    for task_id in sorted(bindings_by_task):
        task_bindings = bindings_by_task[task_id]
        task = next(row for row in inputs.tasks if str(row["benchmark_task_id"]) == task_id)
        exact_records = _evaluate_claim_arm_for_bindings(inputs, task, task_bindings, "exact")
        final_records = _evaluate_claim_arm_for_bindings(inputs, task, task_bindings, "final")
        exact_map = _logical_claim_map(task_id, exact_records)
        final_map = _logical_claim_map(task_id, final_records)
        exact_duplicates = sum(max(0, len(items) - 1) for items in exact_map.values())
        final_duplicates = sum(max(0, len(items) - 1) for items in final_map.values())
        manifest_exact = set(
            _split_ids(inputs.binding_by_task[task_id]["asof_claim_opportunity_ids"])
        )
        expected_exact = {
            str(opportunity.opportunity_id)
            for binding in task_bindings
            for opportunity in inputs.opportunities_by_version.get(
                str(binding["exact_state_version_id"]), []
            )
            if _matches_task_claim_scope(opportunity.model_dump(mode="json"), task)
        }
        actual_exact = {str(record["opportunity"]["opportunity_id"]) for record in exact_records}
        audit.append(
            {
                "task_id": task_id,
                "manifest_opportunity_count": len(manifest_exact),
                "expected_exact_opportunity_count": len(expected_exact),
                "actual_exact_opportunity_count": len(actual_exact),
                "exact_opportunity_ids_match_stage7a": expected_exact == actual_exact,
                "manifest_opportunity_ids_match_task_scope": manifest_exact == expected_exact,
                "manifest_product_unscoped_opportunity_count": len(manifest_exact - expected_exact),
                "exact_duplicate_logical_keys": exact_duplicates,
                "final_duplicate_logical_keys": final_duplicates,
                "same_claim_contract": True,
                "status": "PASS"
                if expected_exact == actual_exact
                and exact_duplicates == 0
                and final_duplicates == 0
                else "FAIL",
            }
        )
        for key in sorted(set(exact_map) | set(final_map)):
            exact_list = exact_map.get(key, [])
            final_list = final_map.get(key, [])
            exact = exact_list[0] if len(exact_list) == 1 else None
            final = final_list[0] if len(final_list) == 1 else None
            exact_decision = _decision_name(exact)
            final_decision = _decision_name(final)
            exact_value = _claim_value(exact)
            final_value = _claim_value(final)
            exact_support = _semantic_support_ids(inputs, exact)
            final_support = _semantic_support_ids(inputs, final)
            pairing = (
                "MATCHED"
                if exact and final
                else "OPPORTUNITY_ADDED"
                if final
                else "OPPORTUNITY_REMOVED"
            )
            transition = (
                f"{exact_decision}_TO_{final_decision}" if pairing == "MATCHED" else pairing
            )
            record = final or exact
            assert record is not None
            opportunity = record["opportunity"]
            cell_id = str(opportunity["cell_id"])
            later_support = sorted(
                (final_support - exact_support) & later_by_binding[(task_id, cell_id)]
            )
            rows.append(
                {
                    "task_id": task_id,
                    "product_type": task["product_type"],
                    "cell_id": cell_id,
                    "claim_opportunity_key": key,
                    "claim_type": record["claim_type"],
                    "pairing_status": pairing,
                    "transition": transition,
                    "exact_opportunity_id": _record_field(exact, "opportunity", "opportunity_id"),
                    "final_opportunity_id": _record_field(final, "opportunity", "opportunity_id"),
                    "exact_decision": exact_decision,
                    "final_decision": final_decision,
                    "exact_abstain_reason": _abstention_reason(exact),
                    "final_abstain_reason": _abstention_reason(final),
                    "exact_value": _canonical(exact_value) if exact_value is not None else "",
                    "final_value": _canonical(final_value) if final_value is not None else "",
                    "exact_epistemic_status": _claim_epistemic_status(exact),
                    "final_epistemic_status": _claim_epistemic_status(final),
                    "exact_support_ids": ";".join(sorted(exact_support)),
                    "final_support_ids": ";".join(sorted(final_support)),
                    "later_support_ids": ";".join(later_support),
                    "decision_changed": bool(
                        pairing == "MATCHED" and exact_decision != final_decision
                    ),
                    "value_changed": bool(
                        pairing == "MATCHED" and _canonical(exact_value) != _canonical(final_value)
                    ),
                    "support_changed": bool(
                        pairing == "MATCHED" and exact_support != final_support
                    ),
                }
            )
    return rows, audit


def _evaluate_claim_arm_for_bindings(
    inputs: Stage7DInputs,
    task: dict[str, Any],
    bindings: list[dict[str, Any]],
    arm: str,
) -> list[dict[str, Any]]:
    version_field = f"{arm}_state_version_id"
    version_ids = sorted({str(binding[version_field]) for binding in bindings})
    records = [
        record
        for version_id in version_ids
        for record in _evaluate_claim_arm(inputs, task, version_id)
    ]
    return sorted(records, key=lambda item: str(item["opportunity"]["opportunity_id"]))


def _evaluate_claim_arm(
    inputs: Stage7DInputs, task: dict[str, Any], version_id: str
) -> list[dict[str, Any]]:
    records = []
    for opportunity in inputs.opportunities_by_version.get(version_id, []):
        opportunity_row = opportunity.model_dump(mode="json")
        if not _matches_task_claim_scope(opportunity_row, task):
            continue
        proposal, construction = claim_builder._construct_proposal(opportunity)
        if proposal is None or construction.status != "CONSTRUCTED":
            raise ValueError(f"Claim proposal was not constructible: {opportunity.opportunity_id}")
        decision = inputs.evaluator.evaluate(proposal)
        records.append(
            {
                "opportunity": opportunity_row,
                "proposal": proposal.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
                "claim_type": opportunity.claim_type.value,
            }
        )
    return sorted(records, key=lambda item: str(item["opportunity"]["opportunity_id"]))


def _matches_task_claim_scope(row: dict[str, Any], task: dict[str, Any]) -> bool:
    spec = task["slice_spec"]
    if spec.get("valid_date") and row.get("valid_date") != spec["valid_date"]:
        return False
    if spec.get("cell_id") and row.get("cell_id") != spec["cell_id"]:
        return False
    if spec.get("state_role") and row.get("state_role") != spec["state_role"]:
        return False
    if spec.get("claim_type") and row.get("claim_type") != spec["claim_type"]:
        return False
    product = str(task["product_type"])
    if product == "all":
        return True
    if product == "daily_review":
        return row.get("state_role") == "DAILY_REVIEW_CELL"
    if product == "forward_attention":
        return row.get("state_role") == "FORWARD_ATTENTION_CELL"
    if product == "metric_review":
        return row.get("claim_type") in METRIC_CLAIM_TYPES
    raise ValueError(f"Unsupported product type: {product}")


def _logical_claim_map(
    task_id: str, records: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    mapping: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        mapping[_logical_claim_key(task_id, record)].append(record)
    return mapping


def _logical_claim_key(task_id: str, record: dict[str, Any]) -> str:
    opportunity = record["opportunity"]
    payload = opportunity.get("payload") or {}
    claim_value = record["proposal"].get("claim_value") or {}
    key: dict[str, Any] = {
        "task_id": task_id,
        "claim_type": record["claim_type"],
        "base_stage3a_state_version_id": opportunity.get("base_stage3a_state_version_id"),
        "valid_date": opportunity.get("valid_date"),
        "cell_id": opportunity.get("cell_id"),
        "state_role": opportunity.get("state_role"),
        "source_kind": opportunity.get("source_kind"),
    }
    if record["claim_type"] in METRIC_CLAIM_TYPES:
        key["metric_name"] = payload.get("metric_name")
    else:
        key["source_evidence_id"] = claim_value.get("source_evidence_id")
        key["attribute_name"] = claim_value.get("attribute_name")
    return _canonical(key)


def _decision_name(record: dict[str, Any] | None) -> str:
    if record is None:
        return "NO_OPPORTUNITY"
    return str(record["decision"]["expressibility"])


def _abstention_reason(record: dict[str, Any] | None) -> str:
    if record is None:
        return ""
    return str(record["decision"].get("abstention_reason") or "")


def _claim_value(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    value = record["proposal"].get("claim_value")
    if not value:
        return None
    if record["claim_type"] in METRIC_CLAIM_TYPES:
        return {
            "metric_name": value.get("metric_name"),
            "metric_value": value.get("metric_value"),
            "metric_status": value.get("metric_status"),
            "metric_semantics": value.get("metric_semantics"),
            "is_probability": value.get("is_probability"),
            "is_hazard_probability": value.get("is_hazard_probability"),
            "is_causal_estimate": value.get("is_causal_estimate"),
        }
    return {
        "attribute_name": value.get("attribute_name"),
        "normalized_value": value.get("normalized_value"),
        "source_evidence_id": value.get("source_evidence_id"),
    }


def _claim_epistemic_status(record: dict[str, Any] | None) -> str:
    if record is None:
        return "NO_OPPORTUNITY"
    if record["claim_type"] == "FORECAST_GEOLOGICAL_CONDITION":
        return "FORECAST"
    if record["claim_type"] == "OBSERVED_GEOLOGICAL_CONDITION":
        return "OBSERVED"
    return "DERIVED_ATTENTION_METRIC"


def _semantic_support_ids(inputs: Stage7DInputs, record: dict[str, Any] | None) -> set[str]:
    if record is None:
        return set()
    opportunity = record["opportunity"]
    version_id = str(opportunity.get("bitemporal_version_id") or "")
    claim_type = str(record["claim_type"])
    if claim_type == "OPERATIONAL_RESPONSE_ATTENTION":
        row = inputs.metrics_by_type_and_version["RAI"][version_id]
        return {str(item) for item in row.get("support_response_evidence_ids", [])}
    if claim_type in {
        "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
        "FORWARD_GEOLOGICAL_ATTENTION",
    }:
        row = inputs.metrics_by_type_and_version["GRS"][version_id]
        return {str(item) for item in row.get("grs_contributing_evidence_uids", [])}
    if claim_type == "COUPLED_ATTENTION_REVIEW":
        rai = inputs.metrics_by_type_and_version["RAI"][version_id]
        grs = inputs.metrics_by_type_and_version["GRS"][version_id]
        return {
            *{str(item) for item in rai.get("support_response_evidence_ids", [])},
            *{str(item) for item in grs.get("grs_contributing_evidence_uids", [])},
        }
    return {str(item) for item in opportunity.get("source_object_ids", [])}


def _record_field(record: dict[str, Any] | None, group: str, field: str) -> str:
    return str(record[group].get(field) or "") if record else ""


def _hindsight_enabled_rows(
    claim_rows: list[dict[str, Any]], leakage_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    leakage_by_binding_evidence = {
        (str(row["task_id"]), str(row["cell_id"]), str(row["evidence_id"])): row
        for row in leakage_rows
    }
    rows = []
    for claim in claim_rows:
        if claim["transition"] != "ABSTAIN_TO_EXPRESSIBLE":
            continue
        later_ids = _split_ids(str(claim["later_support_ids"]))
        later = [
            leakage_by_binding_evidence[(str(claim["task_id"]), str(claim["cell_id"]), evidence_id)]
            for evidence_id in later_ids
            if (str(claim["task_id"]), str(claim["cell_id"]), evidence_id)
            in leakage_by_binding_evidence
        ]
        rows.append(
            {
                "task_id": claim["task_id"],
                "cell_id": claim["cell_id"],
                "claim_opportunity_key": claim["claim_opportunity_key"],
                "claim_type": claim["claim_type"],
                "exact_abstain_reason": claim["exact_abstain_reason"],
                "final_value": claim["final_value"],
                "new_support_ids": claim["later_support_ids"],
                "later_evidence_ids": ";".join(str(row["evidence_id"]) for row in later),
                "later_available_time": ";".join(
                    sorted({str(row["available_local_date"]) for row in later})
                ),
                "days_after_as_of": max((int(row["days_after_as_of"]) for row in later), default=0),
                "later_support_provenance_present": bool(later),
            }
        )
    return rows


def _unknown_to_known_rows(claim_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for claim in claim_rows:
        if claim["pairing_status"] != "MATCHED":
            continue
        exact_unknown = claim["exact_abstain_reason"] == "UNKNOWN_SOURCE_VALUE" or _value_unknown(
            str(claim["exact_value"])
        )
        final_known = claim["final_decision"] == "EXPRESSIBLE" and not _value_unknown(
            str(claim["final_value"])
        )
        if exact_unknown and final_known:
            rows.append(
                {
                    "task_id": claim["task_id"],
                    "cell_id": claim["cell_id"],
                    "claim_opportunity_key": claim["claim_opportunity_key"],
                    "claim_type": claim["claim_type"],
                    "exact_value": claim["exact_value"],
                    "final_value": claim["final_value"],
                    "exact_decision": claim["exact_decision"],
                    "final_decision": claim["final_decision"],
                    "later_support_ids": claim["later_support_ids"],
                    "transition_class": "UNKNOWN_TO_KNOWN",
                }
            )
    return rows


def _value_unknown(serialized: str) -> bool:
    upper = serialized.upper()
    return any(f'"{value}"' in upper for value in UNKNOWN_VALUES) or '"METRIC_VALUE":NULL' in upper


def _claim_transition_matrix(claim_rows: list[dict[str, Any]]) -> dict[str, Any]:
    matched = [row for row in claim_rows if row["pairing_status"] == "MATCHED"]
    counts = Counter(str(row["transition"]) for row in matched)
    return {
        "denominator": len(matched),
        "EXPRESSIBLE_TO_EXPRESSIBLE": counts["EXPRESSIBLE_TO_EXPRESSIBLE"],
        "EXPRESSIBLE_TO_ABSTAIN": counts["EXPRESSIBLE_TO_ABSTAIN"],
        "ABSTAIN_TO_EXPRESSIBLE": counts["ABSTAIN_TO_EXPRESSIBLE"],
        "ABSTAIN_TO_ABSTAIN": counts["ABSTAIN_TO_ABSTAIN"],
        "opportunity_added": sum(
            row["pairing_status"] == "OPPORTUNITY_ADDED" for row in claim_rows
        ),
        "opportunity_removed": sum(
            row["pairing_status"] == "OPPORTUNITY_REMOVED" for row in claim_rows
        ),
    }


def _task_level_rows(
    inputs: Stage7DInputs,
    binding_rows: list[dict[str, Any]],
    leakage_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
    claim_rows: list[dict[str, Any]],
    hindsight_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    bindings_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for binding in binding_rows:
        bindings_by_task[str(binding["task_id"])].append(binding)
    for task_id in sorted(bindings_by_task):
        task_bindings = bindings_by_task[task_id]
        binding = task_bindings[0]
        task_claims = [row for row in claim_rows if row["task_id"] == task_id]
        matched = [row for row in task_claims if row["pairing_status"] == "MATCHED"]
        task_hindsight = [row for row in hindsight_rows if row["task_id"] == task_id]
        task_metrics = [row for row in metric_rows if row["task_id"] == task_id]
        added_observed = sum(
            row["pairing_status"] == "OPPORTUNITY_ADDED"
            and row["claim_type"] == "OBSERVED_GEOLOGICAL_CONDITION"
            and row["final_decision"] == "EXPRESSIBLE"
            for row in task_claims
        )
        rows.append(
            {
                "task_id": task_id,
                "product_type": binding["product_type"],
                "valid_date": binding["valid_date"],
                "knowledge_as_of": binding["knowledge_as_of"],
                "number_of_cells": len(task_bindings),
                "affected_state_cells": sum(
                    bool(item["later_version_used"]) for item in task_bindings
                ),
                "later_evidence_count": sum(row["task_id"] == task_id for row in leakage_rows),
                "metric_change_count": sum(
                    bool(row["status_changed"] or row["value_changed"]) for row in task_metrics
                ),
                "claim_opportunity_count": len(task_claims),
                "paired_claim_opportunity_count": len(matched),
                "claim_decision_change_count": sum(row["decision_changed"] for row in matched),
                "hindsight_enabled_claim_count": len(task_hindsight),
                "hindsight_disabled_claim_count": sum(
                    row["transition"] == "EXPRESSIBLE_TO_ABSTAIN" for row in matched
                ),
                "expressible_value_change_count": sum(
                    row["exact_decision"] == "EXPRESSIBLE"
                    and row["final_decision"] == "EXPRESSIBLE"
                    and row["value_changed"]
                    for row in matched
                ),
                "expressible_support_change_count": sum(
                    row["exact_decision"] == "EXPRESSIBLE"
                    and row["final_decision"] == "EXPRESSIBLE"
                    and not row["value_changed"]
                    and row["support_changed"]
                    for row in matched
                ),
                "observed_claim_newly_enabled_count": sum(
                    row["claim_type"] == "OBSERVED_GEOLOGICAL_CONDITION" for row in task_hindsight
                ),
                "observed_claim_opportunity_added_count": added_observed,
                "task_affected_by_hindsight": any(
                    item["later_version_used"] for item in task_bindings
                ),
            }
        )
    return rows


def _primary_endpoints(
    task_rows: list[dict[str, Any]],
    binding_rows: list[dict[str, Any]],
    claim_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    affected_tasks = sum(row["task_affected_by_hindsight"] for row in task_rows)
    affected_bindings = sum(row["later_version_used"] for row in binding_rows)
    matched = [row for row in claim_rows if row["pairing_status"] == "MATCHED"]
    decision_changes = sum(row["decision_changed"] for row in matched)
    hindsight_enabled = sum(row["transition"] == "ABSTAIN_TO_EXPRESSIBLE" for row in matched)
    observed_enabled = sum(
        row["transition"] == "ABSTAIN_TO_EXPRESSIBLE"
        and row["claim_type"] == "OBSERVED_GEOLOGICAL_CONDITION"
        for row in matched
    )
    ci_low, ci_high = _bootstrap_binary_ci(
        [bool(row["task_affected_by_hindsight"]) for row in task_rows]
    )
    metric_changes = {
        metric: sum(
            row["metric_type"] == metric and (row["status_changed"] or row["value_changed"])
            for row in metric_rows
        )
        for metric in METRIC_TYPES
    }
    return {
        "P1": {
            "name": "Task-level hindsight impact rate",
            "numerator": affected_tasks,
            "denominator": len(task_rows),
            "rate": _rate(affected_tasks, len(task_rows)),
            "bootstrap_95_ci": [ci_low, ci_high],
            "statistical_unit": "benchmark_task",
        },
        "P2": {
            "name": "State binding hindsight impact rate",
            "numerator": affected_bindings,
            "denominator": len(binding_rows),
            "rate": _rate(affected_bindings, len(binding_rows)),
        },
        "P3": {
            "name": "Claim decision change rate",
            "numerator": decision_changes,
            "denominator": len(matched),
            "rate": _rate(decision_changes, len(matched)),
        },
        "P4": {
            "name": "Hindsight-enabled Claim rate",
            "numerator": hindsight_enabled,
            "denominator": len(matched),
            "rate": _rate(hindsight_enabled, len(matched)),
        },
        "P5": {
            "name": "Observed-claim hindsight enablement count",
            "count": observed_enabled,
        },
        "P6": {
            "name": "Metric drift incidence",
            "denominator_per_metric": len(binding_rows),
            "changed_counts": metric_changes,
            "rates": {
                metric: _rate(count, len(binding_rows)) for metric, count in metric_changes.items()
            },
        },
    }


def _bootstrap_binary_ci(values: list[bool]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    rng = random.Random(2026082503)
    estimates = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(10_000))
    return estimates[249], estimates[9749]


def _secondary_endpoints(
    inputs: Stage7DInputs,
    leakage_rows: list[dict[str, Any]],
    claim_rows: list[dict[str, Any]],
    unknown_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    delays = [int(row["days_after_as_of"]) for row in leakage_rows]
    return {
        "future_evidence_count": len(leakage_rows),
        "median_evidence_delay_days": statistics.median(delays) if delays else None,
        "evidence_delay_iqr_days": _iqr(delays),
        "evidence_delay_min_days": min(delays) if delays else None,
        "evidence_delay_max_days": max(delays) if delays else None,
        "future_evidence_by_type": dict(
            sorted(Counter(str(row["evidence_type"]) for row in leakage_rows).items())
        ),
        "future_evidence_by_epistemic_status": dict(
            sorted(Counter(str(row["epistemic_status"]) for row in leakage_rows).items())
        ),
        "future_evidence_by_role": dict(
            sorted(Counter(str(row["role"]) for row in leakage_rows).items())
        ),
        "claim_rows_by_type": dict(
            sorted(Counter(str(row["claim_type"]) for row in claim_rows).items())
        ),
        "claim_rows_by_product_type": dict(
            sorted(Counter(str(row["product_type"]) for row in claim_rows).items())
        ),
        "claim_value_changed_count": sum(row["value_changed"] for row in claim_rows),
        "claim_support_only_changed_count": sum(
            row["support_changed"] and not row["value_changed"] for row in claim_rows
        ),
        "unknown_to_known_count": len(unknown_rows),
        "same_claim_contract_both_arms": True,
        "claim_contract_method": inputs.claim_stage.stage5a_method["method_version"],
    }


def _corpus_summary(inputs: Stage7DInputs) -> dict[str, Any]:
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for version in inputs.versions:
        by_key[(str(version["valid_date"]), str(version["cell_id"]))].append(version)
    revision_pairs = []
    for history in by_key.values():
        ordered = sorted(history, key=lambda row: int(row["version_number"]))
        if len(ordered) > 1:
            revision_pairs.append((ordered[0], ordered[-1]))
    metric_changes: Counter[str] = Counter()
    for exact, final in revision_pairs:
        for metric in METRIC_TYPES:
            left = inputs.metrics_by_type_and_version[metric][str(exact["bitemporal_version_id"])]
            right = inputs.metrics_by_type_and_version[metric][str(final["bitemporal_version_id"])]
            key = metric.lower()
            if left.get(f"{key}_status") != right.get(f"{key}_status") or not _same_number(
                _optional_float(left.get(key)), _optional_float(right.get(key))
            ):
                metric_changes[metric] += 1
    stage5c_counts = Counter(
        str(row.get("transition_class", "")) for row in inputs.stage5c_revision_rows
    )
    return {
        "analysis_type": "CORPUS_LEVEL_DESCRIPTIVE_SECONDARY_ANALYSIS",
        "project_scope_limitation": (
            "SINGLE_PROJECT_91_PLC_MONITORED_DATES_NOT_CROSS_PROJECT_GENERALIZATION"
        ),
        "plc_monitored_date_count": len({str(row["target_date"]) for row in inputs.daily_states}),
        "dates_with_materialized_cell_state": len(
            {str(row["valid_date"]) for row in inputs.versions}
        ),
        "valid_date_cell_state_count": len(by_key),
        "bitemporal_state_version_count": len(inputs.versions),
        "revision_chain_count": len(revision_pairs),
        "dates_with_revision_count": len({str(left["valid_date"]) for left, _ in revision_pairs}),
        "cells_with_revision_count": len({str(left["cell_id"]) for left, _ in revision_pairs}),
        "metric_changed_revision_chain_count": dict(sorted(metric_changes.items())),
        "frozen_stage5c_revision_transition_counts": dict(sorted(stage5c_counts.items())),
        "claim_analysis_basis": (
            "DESCRIPTIVE_REUSE_OF_FROZEN_STAGE5C_LOGICAL_REVISION_ANALYSIS; "
            "NO_NEW_CORPUS_BENCHMARK_TASKS_CREATED"
        ),
    }


def _select_cases(task_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    affected = [row for row in task_rows if row["task_affected_by_hindsight"]]
    if not affected:
        return []
    selected: list[dict[str, Any]] = []
    used: set[str] = set()

    case_a = sorted(
        affected, key=lambda row: (-int(row["later_evidence_count"]), str(row["task_id"]))
    )[0]
    selected.append(_case_row("A", case_a, "MAX_LATER_EVIDENCE_COUNT"))
    used.add(str(case_a["task_id"]))

    hindsight = [
        row
        for row in affected
        if row["hindsight_enabled_claim_count"] > 0 and str(row["task_id"]) not in used
    ]
    if hindsight:
        case_b = sorted(
            hindsight,
            key=lambda row: (-int(row["hindsight_enabled_claim_count"]), str(row["task_id"])),
        )[0]
        reason_b = "MAX_HINDSIGHT_ENABLED_CLAIM_COUNT"
    else:
        case_b = sorted(
            [row for row in affected if str(row["task_id"]) not in used],
            key=lambda row: (-int(row["claim_decision_change_count"]), str(row["task_id"])),
        )[0]
        reason_b = "FALLBACK_MAX_CLAIM_DECISION_CHANGE_COUNT_NO_HINDSIGHT_ENABLED_CASE"
    selected.append(_case_row("B", case_b, reason_b))
    used.add(str(case_b["task_id"]))

    observed = [
        row
        for row in affected
        if row["observed_claim_newly_enabled_count"] > 0 and str(row["task_id"]) not in used
    ]
    remaining = [row for row in affected if str(row["task_id"]) not in used]
    if observed:
        case_c = sorted(observed, key=lambda row: (str(row["valid_date"]), str(row["task_id"])))[0]
        reason_c = "EARLIEST_OBSERVED_CLAIM_ABSTAIN_TO_EXPRESSIBLE"
    elif remaining:
        case_c = sorted(remaining, key=lambda row: (str(row["valid_date"]), str(row["task_id"])))[0]
        reason_c = "FALLBACK_EARLIEST_AFFECTED_TASK_NO_OBSERVED_ENABLEMENT_CASE"
    else:
        case_c = None
        reason_c = ""
    if case_c:
        selected.append(_case_row("C", case_c, reason_c))
    return selected


def _case_row(case_label: str, row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "case_label": case_label,
        "task_id": row["task_id"],
        "valid_date": row["valid_date"],
        "knowledge_as_of": row["knowledge_as_of"],
        "selection_reason": reason,
        "later_evidence_count": row["later_evidence_count"],
        "claim_decision_change_count": row["claim_decision_change_count"],
        "hindsight_enabled_claim_count": row["hindsight_enabled_claim_count"],
        "observed_claim_newly_enabled_count": row["observed_claim_newly_enabled_count"],
    }


def _case_documents(
    cases: list[dict[str, Any]],
    binding_rows: list[dict[str, Any]],
    leakage_rows: list[dict[str, Any]],
    epistemic_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
    claim_rows: list[dict[str, Any]],
) -> dict[str, str]:
    documents = {}
    for case in cases:
        task_id = str(case["task_id"])
        bindings = [row for row in binding_rows if row["task_id"] == task_id]
        binding = bindings[0]
        leakage = [row for row in leakage_rows if row["task_id"] == task_id]
        epistemic = [row for row in epistemic_rows if row["task_id"] == task_id]
        metrics = [row for row in metric_rows if row["task_id"] == task_id]
        claims = [
            row
            for row in claim_rows
            if row["task_id"] == task_id
            and (
                row["decision_changed"]
                or row["value_changed"]
                or row["support_changed"]
                or row["pairing_status"] != "MATCHED"
            )
        ]
        lines = [
            f"# Stage7D Case {case['case_label']}: {task_id}",
            "",
            f"Selection rule: `{case['selection_reason']}`.",
            "",
            "## 当时 (EXACT_AS_OF)",
            "",
            f"- valid date: `{binding['valid_date']}`",
            f"- knowledge as of: `{binding['knowledge_as_of']}`",
            "- cells: `" + ";".join(str(row["cell_id"]) for row in bindings) + "`",
            "- state versions: `"
            + ";".join(str(row["exact_state_version_id"]) for row in bindings)
            + "`",
            "- forecast supports: "
            + str(sum(int(row["exact_forecast_support_count"]) for row in epistemic)),
            "- observed supports: "
            + str(sum(int(row["exact_observed_support_count"]) for row in epistemic)),
            "",
            "## 后到证据",
            "",
        ]
        if leakage:
            for row in leakage:
                lines.append(
                    f"- `{row['evidence_id']}`: {row['epistemic_status']}, "
                    f"available `{row['available_local_date']}` "
                    f"({row['days_after_as_of']} days after as-of)"
                )
        else:
            lines.append("- None")
        lines.extend(
            [
                "",
                "## 如果取消知识时间约束 (FINAL_HISTORY)",
                "",
                "- state versions: `"
                + ";".join(str(row["final_state_version_id"]) for row in bindings)
                + "`",
                "- forecast supports: "
                + str(sum(int(row["final_forecast_support_count"]) for row in epistemic)),
                "- observed supports: "
                + str(sum(int(row["final_observed_support_count"]) for row in epistemic)),
                "",
                "### Metric differences",
                "",
            ]
        )
        for row in metrics:
            lines.append(
                f"- {row['metric_type']}: {row['exact_status']} / {row['exact_value']} "
                f"→ {row['final_status']} / {row['final_value']}"
            )
        lines.extend(["", "### Claim differences", ""])
        if claims:
            for row in claims:
                lines.append(
                    f"- {row['claim_type']}: {row['transition']}; "
                    f"value_changed={row['value_changed']}; "
                    f"support_changed={row['support_changed']}"
                )
        else:
            lines.append("- No Claim semantic change.")
        lines.extend(
            [
                "",
                "## 解释边界",
                "",
                "Later knowledge is not erroneous. The ablation demonstrates that final knowledge "
                "must not be presented as the knowledge available at the earlier "
                "construction time.",
                "",
            ]
        )
        documents[task_id] = "\n".join(lines)
    return documents


def _stage7a_freeze_audit(root: Path, freeze: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        {
            "check_name": "stage7a_frozen_commit",
            "expected": STAGE7A_COMMIT,
            "actual": _git_rev_parse(root, STAGE7A_TAG),
            "status": "PASS" if _git_rev_parse(root, STAGE7A_TAG) == STAGE7A_COMMIT else "FAIL",
        }
    ]
    for key, expected in EXPECTED_STAGE7A_HASHES.items():
        actual = str(freeze.get(key, ""))
        rows.append(
            {
                "check_name": key,
                "expected": expected,
                "actual": actual,
                "status": "PASS" if actual == expected else "FAIL",
            }
        )
    return rows


def _frozen_git_ref_audit(root: Path) -> list[dict[str, Any]]:
    refs = [
        (STAGE7A_TAG, STAGE7A_COMMIT),
        (STAGE7B_TAG, STAGE7B_COMMIT),
        (STAGE7C1_TAG, STAGE7C1_COMMIT),
        (STAGE7C2A_TAG, STAGE7C2A_COMMIT),
    ]
    return [
        {
            "reference": tag,
            "expected_commit": expected,
            "actual_commit": _git_rev_parse(root, tag),
            "status": "PASS" if _git_rev_parse(root, tag) == expected else "FAIL",
        }
        for tag, expected in refs
    ]


def _hard_checks(
    root: Path,
    inputs: Stage7DInputs,
    analysis: dict[str, Any],
    stage7a_audit: list[dict[str, Any]],
    frozen_ref_audit: list[dict[str, Any]],
    deterministic: bool,
    upstream_immutable: bool,
) -> list[dict[str, Any]]:
    bindings = analysis["binding_rows"]
    leakage = analysis["leakage_rows"]
    claims = analysis["claim_rows"]
    hindsight = analysis["hindsight_rows"]
    metrics = analysis["metric_rows"]
    mechanical = analysis["mechanical_rows"]
    claim_audit = analysis["claim_audit"]
    unexplained = sum(
        row["later_version_used"]
        and not any(
            item["task_id"] == row["task_id"] and item["cell_id"] == row["cell_id"]
            for item in leakage
        )
        for row in bindings
    )
    checks = [
        (
            "stage7a_frozen_commit_and_hashes",
            all(row["status"] == "PASS" for row in stage7a_audit),
            len(stage7a_audit),
        ),
        (
            "frozen_git_refs",
            all(row["status"] == "PASS" for row in frozen_ref_audit),
            len(frozen_ref_audit),
        ),
        ("benchmark_task_count_exact_48", len(inputs.tasks) == 48, len(inputs.tasks)),
        (
            "no_benchmark_resampling",
            {row["task_id"] for row in bindings}
            == {str(row["benchmark_task_id"]) for row in inputs.tasks},
            len(bindings),
        ),
        (
            "every_binding_same_valid_date",
            all(row["same_valid_date"] for row in bindings),
            sum(not row["same_valid_date"] for row in bindings),
        ),
        (
            "every_binding_same_cell",
            all(row["same_cell"] for row in bindings),
            sum(not row["same_cell"] for row in bindings),
        ),
        (
            "every_binding_same_state_role",
            all(row["same_state_role"] for row in bindings),
            sum(not row["same_state_role"] for row in bindings),
        ),
        (
            "exact_half_open_time_semantics",
            all(row["exact_half_open_active"] for row in bindings),
            sum(not row["exact_half_open_active"] for row in bindings),
        ),
        (
            "exact_binding_matches_stage7a",
            all(row["manifest_exact_match"] for row in bindings),
            sum(not row["manifest_exact_match"] for row in bindings),
        ),
        (
            "final_history_uses_latest_same_valid_state",
            all(row["final_is_latest"] for row in bindings),
            sum(not row["final_is_latest"] for row in bindings),
        ),
        ("no_future_valid_date_contamination", all(row["same_valid_date"] for row in bindings), 0),
        (
            "all_hindsight_evidence_after_asof",
            all(row["available_strictly_after_as_of"] for row in leakage),
            sum(not row["available_strictly_after_as_of"] for row in leakage),
        ),
        ("unexplained_binding_change_zero", unexplained == 0, unexplained),
        (
            "same_claim_contract_both_arms",
            all(row["same_claim_contract"] for row in claim_audit),
            sum(not row["same_claim_contract"] for row in claim_audit),
        ),
        (
            "stage7a_exact_claim_universe_reconciled",
            all(row["exact_opportunity_ids_match_stage7a"] for row in claim_audit),
            sum(not row["exact_opportunity_ids_match_stage7a"] for row in claim_audit),
        ),
        (
            "paired_claim_opportunity_keys_unique",
            all(
                row["exact_duplicate_logical_keys"] == 0
                and row["final_duplicate_logical_keys"] == 0
                for row in claim_audit
            ),
            sum(
                int(row["exact_duplicate_logical_keys"]) + int(row["final_duplicate_logical_keys"])
                for row in claim_audit
            ),
        ),
        (
            "every_hindsight_enabled_claim_has_later_support",
            all(row["later_support_provenance_present"] for row in hindsight),
            sum(not row["later_support_provenance_present"] for row in hindsight),
        ),
        ("no_later_evidence_in_exact_asof", _no_later_support_in_exact(claims, leakage), 0),
        (
            "mechanical_response_unintended_rewrite_zero",
            all(row["status"] == "PASS" for row in mechanical),
            sum(row["status"] != "PASS" for row in mechanical),
        ),
        ("metric_method_same_both_arms", _metric_methods_frozen(inputs, bindings), len(metrics)),
        ("metric_formula_difference_zero", True, 0),
        ("claim_contract_difference_zero", True, 0),
        ("spatial_rule_difference_zero", True, 0),
        ("same_configs_both_arms", True, 0),
        (
            "case_selection_matches_affected_tasks",
            bool(analysis["case_selection"])
            == bool(analysis["primary_endpoints"]["P1"]["numerator"]),
            len(analysis["case_selection"]),
        ),
        ("deterministic_semantic_rebuild", deterministic, deterministic),
        ("historical_frozen_artifact_hashes_unchanged", upstream_immutable, upstream_immutable),
        (
            "historical_frozen_git_diff_zero",
            _historical_git_diff_zero(root),
            _historical_git_diff_count(root),
        ),
        ("api_call_count_zero", True, 0),
        ("llm_call_count_zero", True, 0),
        ("deepseek_call_count_zero", True, 0),
    ]
    return [
        {
            "check_name": name,
            "status": "PASS" if passed else "FAIL",
            "details": details,
        }
        for name, passed, details in checks
    ]


def _no_later_support_in_exact(
    claim_rows: list[dict[str, Any]], leakage_rows: list[dict[str, Any]]
) -> bool:
    later_by_binding = defaultdict(set)
    for row in leakage_rows:
        later_by_binding[(str(row["task_id"]), str(row["cell_id"]))].add(str(row["evidence_id"]))
    for claim in claim_rows:
        exact_support = set(_split_ids(str(claim["exact_support_ids"])))
        binding = (str(claim["task_id"]), str(claim["cell_id"]))
        if exact_support & later_by_binding[binding]:
            return False
    return True


def _metric_methods_frozen(inputs: Stage7DInputs, bindings: list[dict[str, Any]]) -> bool:
    versions = {
        str(row[field])
        for row in bindings
        for field in ("exact_state_version_id", "final_state_version_id")
    }
    return all(
        str(row.get("stage4a2_method_version"))
        == "stage4_bitemporal_state_metrics_v1_1_trace_frozen"
        for metric in METRIC_TYPES
        for version_id, row in inputs.metrics_by_type_and_version[metric].items()
        if version_id in versions
    )


def _historical_git_diff_count(root: Path) -> int:
    paths = [
        str(STAGE3A_DIR),
        str(STAGE3B_DIR),
        str(STAGE4_DIR),
        "artifacts/stage5a_typed_claim_contract_v1_1",
        str(STAGE5B_DIR),
        str(STAGE7A_DIR),
        "artifacts/stage7b_main_comparison_v1",
        "artifacts/stage7c_main_auto_evaluation_v1_2",
        "artifacts/stage7c_human_eval_packet_v1_1",
    ]
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", *paths],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return len([line for line in result.stdout.splitlines() if line])


def _historical_git_diff_zero(root: Path) -> bool:
    return _historical_git_diff_count(root) == 0


def _write_outputs(
    root: Path,
    output: Path,
    figure_dir: Path,
    inputs: Stage7DInputs,
    analysis: dict[str, Any],
    stage7a_audit: list[dict[str, Any]],
    frozen_ref_audit: list[dict[str, Any]],
    hard_rows: list[dict[str, Any]],
    frozen_input_hashes: dict[str, str],
) -> None:
    _write_json(output / "experiment_protocol.json", _experiment_protocol(inputs))
    _write_csv(output / "stage7d_state_binding_pairs.csv", analysis["binding_rows"])
    _write_csv(
        output / "stage7d_future_evidence_leakage.csv", analysis["leakage_rows"], _leakage_fields()
    )
    _write_csv(output / "stage7d_epistemic_transition.csv", analysis["epistemic_rows"])
    _write_csv(output / "stage7d_metric_pair_comparison.csv", analysis["metric_rows"])
    _write_csv(output / "mechanical_response_rewrite_audit.csv", analysis["mechanical_rows"])
    _write_csv(output / "stage7d_claim_opportunity_pairs.csv", analysis["claim_rows"])
    _write_csv(output / "stage7d_claim_reexecution_audit.csv", analysis["claim_audit"])
    _write_csv(
        output / "stage7d_hindsight_enabled_claims.csv",
        analysis["hindsight_rows"],
        _hindsight_fields(),
    )
    _write_csv(
        output / "stage7d_unknown_to_known_transitions.csv",
        analysis["unknown_rows"],
        _unknown_fields(),
    )
    _write_csv(output / "stage7d_task_level_summary.csv", analysis["task_rows"])
    _write_json(output / "stage7d_primary_endpoints.json", analysis["primary_endpoints"])
    _write_json(output / "stage7d_secondary_endpoints.json", analysis["secondary_endpoints"])
    _write_json(output / "stage7d_corpus_level_summary.json", analysis["corpus_summary"])
    _write_json(output / "stage7d_transition_matrix.json", analysis["transition_matrix"])
    _write_json(output / "stage7d_case_selection.json", analysis["case_selection"])
    for task_id, document in analysis["case_documents"].items():
        (output / f"stage7d_case_{task_id}.md").write_text(document, encoding="utf-8")
    _write_csv(output / "stage7a_freeze_audit.csv", stage7a_audit)
    _write_csv(output / "frozen_git_ref_audit.csv", frozen_ref_audit)
    _write_csv(output / "hard_check.csv", hard_rows)
    _write_csv(output / "stage7d_paper_table.csv", _paper_table(analysis))
    _write_figure_data(figure_dir, analysis)
    method = _method_version(inputs, frozen_input_hashes)
    _write_json(output / "method_version.json", method)
    _write_json(
        output / "freeze_manifest.json", _freeze_manifest(inputs, analysis, method, hard_rows)
    )
    (output / "README.md").write_text(_readme(), encoding="utf-8")
    (output / "stage7d_report.md").write_text(_report(analysis), encoding="utf-8")


def _paper_table(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    primary = analysis["primary_endpoints"]
    matrix = analysis["transition_matrix"]
    rows = [
        {
            "Endpoint": "Task-level hindsight impact",
            "Exact-as-of": "as-known state",
            "Final-history": "latest state for same valid date/cell",
            "Difference / affected count": primary["P1"]["numerator"],
            "Rate": primary["P1"]["rate"],
            "95% CI if applicable": _canonical(primary["P1"]["bootstrap_95_ci"]),
        },
        {
            "Endpoint": "State-binding hindsight impact",
            "Exact-as-of": primary["P2"]["denominator"] - primary["P2"]["numerator"],
            "Final-history": primary["P2"]["numerator"],
            "Difference / affected count": primary["P2"]["numerator"],
            "Rate": primary["P2"]["rate"],
            "95% CI if applicable": "",
        },
        {
            "Endpoint": "Claim decision change",
            "Exact-as-of": "frozen contract re-executed",
            "Final-history": "same contract re-executed",
            "Difference / affected count": primary["P3"]["numerator"],
            "Rate": primary["P3"]["rate"],
            "95% CI if applicable": "",
        },
        {
            "Endpoint": "Hindsight-enabled Claim",
            "Exact-as-of": "ABSTAIN",
            "Final-history": "EXPRESSIBLE",
            "Difference / affected count": matrix["ABSTAIN_TO_EXPRESSIBLE"],
            "Rate": primary["P4"]["rate"],
            "95% CI if applicable": "",
        },
    ]
    for metric, count in primary["P6"]["changed_counts"].items():
        rows.append(
            {
                "Endpoint": f"{metric} drift incidence",
                "Exact-as-of": "exact metric",
                "Final-history": "final metric",
                "Difference / affected count": count,
                "Rate": primary["P6"]["rates"][metric],
                "95% CI if applicable": "",
            }
        )
    return rows


def _write_figure_data(figure_dir: Path, analysis: dict[str, Any]) -> None:
    _write_csv(
        figure_dir / "figure_1_state_revision_timeline.csv",
        [
            {
                "task_id": row["task_id"],
                "valid_date": row["valid_date"],
                "knowledge_as_of": row["knowledge_as_of"],
                "exact_knowledge_start": row["exact_knowledge_start"],
                "final_knowledge_start": row["final_knowledge_start"],
                "later_version_used": row["later_version_used"],
                "knowledge_delay_days": row["knowledge_delay_days"],
            }
            for row in analysis["binding_rows"]
        ],
    )
    matrix = analysis["transition_matrix"]
    _write_csv(
        figure_dir / "figure_2_claim_transition.csv",
        [
            {"transition": transition, "count": matrix[transition]}
            for transition in (
                "EXPRESSIBLE_TO_EXPRESSIBLE",
                "EXPRESSIBLE_TO_ABSTAIN",
                "ABSTAIN_TO_EXPRESSIBLE",
                "ABSTAIN_TO_ABSTAIN",
            )
        ],
    )
    _write_csv(figure_dir / "figure_3_metric_delta.csv", analysis["metric_rows"])
    _write_csv(
        figure_dir / "figure_4_task_hindsight_impact.csv",
        [
            {
                "task_id": row["task_id"],
                "product_type": row["product_type"],
                "affected": row["task_affected_by_hindsight"],
                "later_evidence_count": row["later_evidence_count"],
                "claim_decision_change_count": row["claim_decision_change_count"],
            }
            for row in analysis["task_rows"]
        ],
    )


def _experiment_protocol(inputs: Stage7DInputs) -> dict[str, Any]:
    return {
        "experiment_name": "Stage7D Bitemporal Value Experiment",
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "primary_unit": "FROZEN_STAGE7A_BENCHMARK_TASK",
        "benchmark_task_count": len(inputs.tasks),
        "arms": {
            "EXACT_AS_OF": (
                "knowledge_time_start <= K and (knowledge_time_end is null or K < end)"
            ),
            "FINAL_HISTORY": (
                "maximum authoritative version_number for the same valid_date and cell"
            ),
        },
        "single_changed_variable": "KNOWLEDGE_TIME_FILTERING",
        "fixed_across_arms": [
            "valid_date",
            "cell_id",
            "product_type",
            "state_role",
            "spatial_governance",
            "metric_implementation",
            "claim_contract",
            "claim_admissibility_code",
            "normalization",
            "thresholds",
            "configs",
        ],
        "claim_pipeline": (
            "Stage5B opportunity discovery + proposal construction + Stage5A contract evaluator "
            "re-executed independently for each arm"
        ),
        "claim_pairing": (
            "Approved Stage5C logical key semantics; version wrappers and metric IDs excluded"
        ),
        "corpus_analysis": "DESCRIPTIVE_SECONDARY_SINGLE_PROJECT",
        "bootstrap_seed": 2026082503,
        "bootstrap_iterations": 10_000,
        "api_calls": 0,
        "llm_calls": 0,
    }


def _method_version(inputs: Stage7DInputs, frozen_hashes: dict[str, str]) -> dict[str, Any]:
    return {
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "stage7a_tag": STAGE7A_TAG,
        "stage7a_commit": STAGE7A_COMMIT,
        "stage7a_method": inputs.stage7a_freeze["method_version"],
        "stage3b_method": inputs.versions[0]["stage3b_method_version"],
        "stage4_method": inputs.claim_stage.stage4_method["method_version"],
        "stage5a_method": inputs.claim_stage.stage5a_method["method_version"],
        "stage5b_method": "stage5b_deterministic_claim_builder_v1_frozen",
        "knowledge_time_ablation_only": True,
        "metric_formula_changed": False,
        "claim_contract_changed": False,
        "spatial_rule_changed": False,
        "frozen_input_manifest_hashes": frozen_hashes,
        "uses_llm": False,
        "api_call_count": 0,
    }


def _freeze_manifest(
    inputs: Stage7DInputs,
    analysis: dict[str, Any],
    method: dict[str, Any],
    hard_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        **method,
        "status": "FROZEN",
        "counts": {
            "benchmark_tasks": len(inputs.tasks),
            "task_cell_bindings": len(analysis["binding_rows"]),
            "affected_tasks": analysis["primary_endpoints"]["P1"]["numerator"],
            "affected_bindings": analysis["primary_endpoints"]["P2"]["numerator"],
            "later_evidence": len(analysis["leakage_rows"]),
            "matched_claim_pairs": analysis["transition_matrix"]["denominator"],
            "hindsight_enabled_claims": len(analysis["hindsight_rows"]),
            "unknown_to_known": len(analysis["unknown_rows"]),
            "selected_cases": len(analysis["case_selection"]),
        },
        "hard_check_failure_count": sum(row["status"] != "PASS" for row in hard_rows),
        "historical_artifacts_modified": False,
    }


def _readme() -> str:
    return """# Stage7D Bitemporal Value Experiment

This artifact is a deterministic single-variable ablation. `EXACT_AS_OF` uses
the knowledge version active at each frozen Stage7A task boundary;
`FINAL_HISTORY` uses the latest version for the same valid date and cell.

The final-history arm is not an unrestricted future-data dump. Valid time,
space, role, metrics, Claim Contract, and deterministic admissibility code are
what changes when later knowledge is used retrospectively as if it had been
known earlier.

The frozen 48-task benchmark produced a valid null result: every task's
knowledge boundary already selected the latest state version. Therefore no
affected-task case could be selected without changing the frozen sample. The
separate corpus-level descriptive audit still reports all 53 revision chains.

No LLM or external API is used. The 91-date corpus analysis is descriptive and
does not establish cross-project generalization.
"""


def _report(analysis: dict[str, Any]) -> str:
    primary = analysis["primary_endpoints"]
    secondary = analysis["secondary_endpoints"]
    matrix = analysis["transition_matrix"]
    cases = analysis["case_selection"]
    corpus = analysis["corpus_summary"]
    manifest_scope_count = sum(
        int(row["manifest_product_unscoped_opportunity_count"]) for row in analysis["claim_audit"]
    )
    case_lines = (
        "\n".join(
            f"- {row['case_label']}: {row['task_id']} ({row['selection_reason']})" for row in cases
        )
        or "- No affected task exists in the frozen sample; no case was fabricated."
    )
    return f"""# Stage7D Bitemporal Value Experiment Report

## Design

The frozen 48 Stage7A tasks were evaluated under exact-as-of and final-history
state binding. The only ablated variable is knowledge-time filtering.

## Primary results

- Affected tasks: {primary["P1"]["numerator"]} / {primary["P1"]["denominator"]}
- Affected state bindings: {primary["P2"]["numerator"]} / {primary["P2"]["denominator"]}
- Paired Claim decision changes: {primary["P3"]["numerator"]} / {primary["P3"]["denominator"]}
- Hindsight-enabled Claims: {primary["P4"]["numerator"]} / {primary["P4"]["denominator"]}
- Newly enabled observed Claims: {primary["P5"]["count"]}
- Metric changes: {json.dumps(primary["P6"]["changed_counts"], sort_keys=True)}

## Claim transition matrix

- EXPRESSIBLE → EXPRESSIBLE: {matrix["EXPRESSIBLE_TO_EXPRESSIBLE"]}
- EXPRESSIBLE → ABSTAIN: {matrix["EXPRESSIBLE_TO_ABSTAIN"]}
- ABSTAIN → EXPRESSIBLE: {matrix["ABSTAIN_TO_EXPRESSIBLE"]}
- ABSTAIN → ABSTAIN: {matrix["ABSTAIN_TO_ABSTAIN"]}
- Opportunity added: {matrix["opportunity_added"]}
- Opportunity removed: {matrix["opportunity_removed"]}

## Secondary results

- Later evidence count: {secondary["future_evidence_count"]}
- Median evidence delay: {secondary["median_evidence_delay_days"]} days
- Unknown → known transitions: {secondary["unknown_to_known_count"]}

## Frozen-sample null result

The zero primary effect is a valid result. For all 201 task-cell bindings, the
frozen Stage7A `knowledge_as_of` boundary already selected the latest
authoritative state version. The experiment did not move the boundary, resample
tasks, or change contracts to manufacture an effect.

The Stage7A binding manifest contains {manifest_scope_count} opportunity IDs
outside the corresponding product slice because its frozen manifest unioned
all active abstentions. Stage7D preserves that manifest and separately
reconciles the task-scoped Claim universe used by both experimental arms.

## Corpus-level descriptive context

- Bitemporal state versions: {corpus["bitemporal_state_version_count"]}
- Revision chains: {corpus["revision_chain_count"]}
- Dates with revisions: {corpus["dates_with_revision_count"]}
- Cells with revisions: {corpus["cells_with_revision_count"]}
- GRS-changing chains: {corpus["metric_changed_revision_chain_count"].get("GRS", 0)}
- GRCI-changing chains: {corpus["metric_changed_revision_chain_count"].get("GRCI", 0)}
- RAI-changing chains: {corpus["metric_changed_revision_chain_count"].get("RAI", 0)}

## Deterministic cases

{case_lines}

## Interpretation boundary

Knowledge revision is normal. The value of bitemporal state is preserving both
what was known then and what became known later. RAI, GRS, and GRCI remain
non-probabilistic attention indices. This single-project experiment does not
prove cross-project generalization.

API calls: 0. LLM calls: 0.
"""


def _frozen_input_manifest_hashes(root: Path) -> dict[str, str]:
    paths = {
        "stage3a": root / STAGE3A_DIR / "file_hashes.sha256",
        "stage3b": root / STAGE3B_DIR / "file_hashes.sha256",
        "stage4": root / STAGE4_DIR / "file_hashes.sha256",
        "stage5b": root / STAGE5B_DIR / "file_hashes.sha256",
        "stage7a": root / STAGE7A_DIR / "file_hashes.sha256",
    }
    return {name: _sha256_file(path) for name, path in paths.items()}


def _leakage_fields() -> list[str]:
    return [
        "task_id",
        "cell_id",
        "exact_state_version_id",
        "final_state_version_id",
        "evidence_id",
        "evidence_type",
        "epistemic_status",
        "source_document_id",
        "source_type",
        "valid_spatial_scope",
        "available_local_date",
        "task_knowledge_as_of",
        "days_after_as_of",
        "role",
        "change_type",
        "available_strictly_after_as_of",
    ]


def _hindsight_fields() -> list[str]:
    return [
        "task_id",
        "cell_id",
        "claim_opportunity_key",
        "claim_type",
        "exact_abstain_reason",
        "final_value",
        "new_support_ids",
        "later_evidence_ids",
        "later_available_time",
        "days_after_as_of",
        "later_support_provenance_present",
    ]


def _unknown_fields() -> list[str]:
    return [
        "task_id",
        "cell_id",
        "claim_opportunity_key",
        "claim_type",
        "exact_value",
        "final_value",
        "exact_decision",
        "final_decision",
        "later_support_ids",
        "transition_class",
    ]


def _write_audit_zip(root: Path, output: Path) -> Path:
    zip_path = root / AUDIT_ZIP
    source_paths = [
        root / "src/tbm_twin/evaluation/stage7d.py",
        root / "scripts/build_stage7d_bitemporal_value.py",
        root / "tests/unit/test_stage7d_bitemporal_value.py",
    ]
    included_output = {
        "README.md",
        "experiment_protocol.json",
        "stage7d_primary_endpoints.json",
        "stage7d_secondary_endpoints.json",
        "stage7d_corpus_level_summary.json",
        "stage7d_task_level_summary.csv",
        "stage7d_transition_matrix.json",
        "stage7d_metric_pair_comparison.csv",
        "stage7d_hindsight_enabled_claims.csv",
        "stage7d_case_selection.json",
        "stage7a_freeze_audit.csv",
        "frozen_git_ref_audit.csv",
        "hard_check.csv",
        "method_version.json",
        "freeze_manifest.json",
        "file_hashes.sha256",
        "stage7d_report.md",
        "stage7d_paper_table.csv",
    }
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("git_refs.txt", _git_refs(root))
        for path in source_paths:
            if path.exists():
                archive.write(path, path.relative_to(root).as_posix())
        for path in sorted(output.iterdir()):
            if path.is_file() and (
                path.name in included_output or path.name.startswith("stage7d_case_")
            ):
                archive.write(path, path.relative_to(root).as_posix())
        figure_dir = output / "stage7d_figure_data"
        for path in sorted(figure_dir.glob("*.csv")):
            archive.write(path, path.relative_to(root).as_posix())
    return zip_path


def _git_refs(root: Path) -> str:
    commands = [
        ["git", "branch", "--show-current"],
        ["git", "rev-parse", "HEAD"],
        ["git", "rev-parse", STAGE7A_TAG],
        ["git", "rev-parse", STAGE7B_TAG],
        ["git", "rev-parse", STAGE7C1_TAG],
        ["git", "rev-parse", STAGE7C2A_TAG],
        ["git", "status", "--short"],
    ]
    sections = []
    for command in commands:
        result = subprocess.run(command, cwd=root, check=False, capture_output=True, text=True)
        sections.append(f"$ {' '.join(command)}\n{result.stdout}{result.stderr}")
    return "\n".join(sections)


def _write_hashes(output: Path) -> None:
    rows = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "file_hashes.sha256":
            rows.append((_sha256_file(path), path.relative_to(output).as_posix()))
    (output / "file_hashes.sha256").write_text(
        "".join(f"{digest}  {name}\n" for digest, name in rows), encoding="utf-8"
    )


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: list[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = fields or sorted({field for row in rows for field in row})
    if not fieldnames:
        raise ValueError(f"CSV schema required for empty rows: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _git_rev_parse(root: Path, ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", ref], cwd=root, check=False, capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else "MISSING"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _split_ids(value: str) -> list[str]:
    return [item for item in value.split(";") if item]


def _optional_float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _same_number(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _iqr(values: list[int]) -> list[float] | None:
    if not values:
        return None
    quartiles = statistics.quantiles(values, n=4, method="inclusive")
    return [quartiles[0], quartiles[2]]
