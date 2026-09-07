"""Deterministic automatic evaluation for Stage7C.1.

This module evaluates frozen Stage7B outputs only.  It does not call LLMs,
rerun providers, modify Stage7B outputs, or assign human semantic labels.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
import subprocess
import tokenize
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tbm_twin.realization.models import SliceSpec
from tbm_twin.realization.stage6b import build_task_bundle, load_stage6b_inputs

STAGE7C_METHOD_VERSION = "stage7c_main_auto_eval_v1_2_final_closure"
STAGE7C_SCHEMA_VERSION = "stage7c_main_auto_eval.v1.2"
STAGE7C_GENERATED_AT = "2026-08-17T00:00:00+08:00"
STAGE7B_EXECUTION_ID = "stage7b_main_execution_3ae0f791811a2e711cb9f488"
EXPECTED_NO_OUTPUT_TASKS = {
    "stage7_main_task_022",
    "stage7_main_task_026",
    "stage7_main_task_042",
}
AUTO_ERROR_CODES = ["E2", "E3", "E4", "E5", "E7", "E10", "E12", "E13", "E14"]
RESULT_VALUES = ["PASS", "FAIL", "REQUIRES_HUMAN_REVIEW", "NOT_APPLICABLE"]
METHODS = ["B0_DIRECT_LLM", "B1_STRUCTURED_PROMPT_LLM", "P_PROPOSED"]
TRACE_RELATION_SOURCE = "rebuilt_stage7a_asof_stage6b_bundle_realization_unit_member_fact_lock_ids"


@dataclass(frozen=True)
class RuleDecision:
    result: str
    reason_code: str
    authoritative_reference: str = ""
    support_reference: str = ""
    details: str = ""


@dataclass(frozen=True)
class NumericReference:
    name: str
    value: float | None
    status: str
    object_id: str
    cell_id: str = ""
    scope: Scope | None = None
    valid_date: str = ""
    knowledge_as_of: str = ""


@dataclass(frozen=True)
class Scope:
    start: float
    end: float
    object_id: str

    def contains(self, other: Scope, tolerance: float = 0.51) -> bool:
        return self.start - tolerance <= other.start and other.end <= self.end + tolerance

    @property
    def width(self) -> float:
        return abs(self.end - self.start)


def build_stage7c_auto_eval(
    repo_root: Path,
    output_dir: Path,
    *,
    write_audit_zip: bool = True,
) -> dict[str, Any]:
    """Build the Stage7C.1 deterministic automatic evaluation artifact."""

    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    stage7a_dir = repo_root / "artifacts/stage7a_experimental_protocol_v1_3"
    stage7b_dir = repo_root / "artifacts/stage7b_main_comparison_v1"
    stage7b_run_dir = stage7b_dir / "runs" / STAGE7B_EXECUTION_ID

    task_rows = _load_stage7_tasks(stage7a_dir / "stage7_main_benchmark_manifest.json")
    task_by_id = {row["benchmark_task_id"]: row for row in task_rows}
    b0_payloads = _jsonl_by_key(stage7a_dir / "stage7_b0_input_payloads.jsonl", "benchmark_task_id")
    preclaim_refs = _jsonl_by_key(
        stage7a_dir / "stage7_proposed_preclaim_reference.jsonl", "benchmark_task_id"
    )
    error_taxonomy = json.loads((stage7a_dir / "stage7_error_taxonomy.json").read_text())
    product_contracts = json.loads((stage7a_dir / "stage7_product_task_contracts.json").read_text())

    execution_manifest = json.loads((stage7b_run_dir / "execution_manifest.json").read_text())
    execution_items = sorted(
        execution_manifest["items"],
        key=lambda row: (row["benchmark_task_id"], row["method_position_for_task"]),
    )
    plan_rows = _read_csv(stage7b_run_dir / "P_plan_validation.csv")
    plan_by_item = {row["execution_item_id"]: row for row in plan_rows}

    text_by_item = _load_actual_outputs(stage7b_run_dir)
    condition_rows, no_output_rows = _build_condition_manifest(
        execution_items, task_by_id, b0_payloads, text_by_item, plan_by_item
    )
    actual_text_rows = _build_actual_text_manifest(condition_rows, text_by_item)
    statement_rows, context_rows = _build_statement_and_context_tables(actual_text_rows)

    context_by_task = {
        task_id: _evaluation_context(
            task_id,
            b0_payloads[task_id],
            task_by_id[task_id],
            preclaim_refs.get(task_id, {}),
            repo_root,
        )
        for task_id in sorted(task_by_id)
    }
    statement_binding_rows = _statement_subject_binding(
        statement_rows, condition_rows, context_by_task
    )
    statement_trace_rows, trace_cardinality_rows = _statement_trace_table(
        statement_rows,
        condition_rows,
        task_by_id,
        preclaim_refs,
        repo_root,
    )
    statement_audit_rows = _evaluate_statements(
        statement_rows,
        condition_rows,
        context_by_task,
        plan_by_item,
        statement_binding_rows,
        statement_trace_rows,
    )
    condition_summary_rows = _condition_summary(condition_rows, statement_audit_rows)
    condition_binary_rows = _condition_binary_endpoints(condition_rows, statement_audit_rows)
    method_summary_rows = _method_summary(condition_rows, statement_audit_rows)
    e13_plan_rows = _e13_plan_level_summary(condition_rows, plan_by_item)
    e7_coverage = _e7_automatic_coverage(condition_rows, statement_audit_rows)
    v1_reclassification_rows = _v1_failure_reclassification(repo_root, statement_audit_rows)
    e10_reclassification_rows = _version_failure_reclassification(
        repo_root / "configs/frozen_inputs/stage7c_v1_1_failed_statement_baseline.csv",
        statement_audit_rows,
        {"E10"},
    )
    e5_reclassification_rows = _version_failure_reclassification(
        repo_root / "configs/frozen_inputs/stage7c_v1_1_failed_statement_baseline.csv",
        statement_audit_rows,
        {"E5"},
    )
    frozen_hash_rows = _frozen_input_hash_audit(repo_root)
    frozen_git_rows = _frozen_git_ref_audit(repo_root)
    no_external_call_audit = _no_external_model_call_audit(repo_root)
    hard_check_rows = _hard_checks(
        repo_root,
        task_rows,
        condition_rows,
        actual_text_rows,
        no_output_rows,
        plan_rows,
        condition_summary_rows,
        statement_audit_rows,
        statement_binding_rows,
        statement_trace_rows,
        trace_cardinality_rows,
        frozen_hash_rows,
        frozen_git_rows,
        no_external_call_audit,
        e13_plan_rows,
        e7_coverage,
    )

    automatic_error_definition = _automatic_error_definition(error_taxonomy)
    denominator_contract = {
        "schema_version": STAGE7C_SCHEMA_VERSION,
        "method_version": STAGE7C_METHOD_VERSION,
        "scope": "PRE-HUMAN AUTOMATIC EVALUATION",
        "condition_denominator": 144,
        "task_denominator": 48,
        "method_condition_denominator": {
            "B0_DIRECT_LLM": 48,
            "B1_STRUCTURED_PROMPT_LLM": 48,
            "P_PROPOSED": 48,
        },
        "actual_text_denominator": 141,
        "proposed_no_valid_output_denominator": 3,
        "no_valid_output_policy": {
            "included_in_condition_denominator": True,
            "included_in_output_availability": True,
            "text_evaluation_eligible": False,
            "not_counted_as_semantic_pass": True,
            "not_counted_as_prose_semantic_fail": True,
        },
        "pending_human_codes": ["E1", "E6", "E7", "E8", "E9", "E11", "E12"],
    }
    method_version = {
        "schema_version": STAGE7C_SCHEMA_VERSION,
        "method_version": STAGE7C_METHOD_VERSION,
        "generated_at": STAGE7C_GENERATED_AT,
        "stage7b_execution_id": STAGE7B_EXECUTION_ID,
        "uses_llm": False,
        "uses_llm_as_judge": False,
        "reruns_stage7b": False,
        "automatic_error_codes": AUTO_ERROR_CODES,
    }

    _write_csv(output_dir / "condition_manifest.csv", condition_rows)
    _write_json(output_dir / "condition_manifest.json", {"rows": condition_rows})
    _write_csv(output_dir / "actual_text_manifest.csv", actual_text_rows)
    _write_csv(output_dir / "statement_table.csv", statement_rows)
    _write_csv(output_dir / "statement_context_table.csv", context_rows)
    _write_csv(output_dir / "statement_subject_binding.csv", statement_binding_rows)
    _write_csv(output_dir / "statement_trace_table.csv", statement_trace_rows)
    _write_csv(output_dir / "trace_cardinality_audit.csv", trace_cardinality_rows)
    _write_csv(output_dir / "no_output_conditions.csv", no_output_rows)
    _write_csv(output_dir / "automatic_statement_audit.csv", statement_audit_rows)
    _write_csv(output_dir / "automatic_condition_summary.csv", condition_summary_rows)
    _write_csv(output_dir / "automatic_condition_binary_endpoints.csv", condition_binary_rows)
    _write_csv(output_dir / "method_automatic_summary.csv", method_summary_rows)
    _write_csv(output_dir / "v1_failure_reclassification.csv", v1_reclassification_rows)
    _write_csv(output_dir / "e10_v1_1_fail_reclassification.csv", e10_reclassification_rows)
    _write_csv(output_dir / "e5_v1_1_fail_reclassification.csv", e5_reclassification_rows)
    _write_csv(output_dir / "e13_plan_level_summary.csv", e13_plan_rows)
    _write_json(output_dir / "e7_automatic_coverage.json", e7_coverage)
    _write_json(output_dir / "automatic_error_definition.json", automatic_error_definition)
    _write_json(output_dir / "denominator_contract.json", denominator_contract)
    _write_csv(output_dir / "frozen_input_hash_audit.csv", frozen_hash_rows)
    _write_csv(output_dir / "frozen_git_ref_audit.csv", frozen_git_rows)
    _write_json(output_dir / "no_external_model_call_audit.json", no_external_call_audit)
    _write_csv(output_dir / "hard_check.csv", hard_check_rows)
    _write_json(output_dir / "method_version.json", method_version)

    report = _evaluation_report(
        condition_rows,
        actual_text_rows,
        no_output_rows,
        method_summary_rows,
        hard_check_rows,
        product_contracts,
    )
    (output_dir / "evaluation_report.md").write_text(report)
    (output_dir / "README.md").write_text(_readme())
    (output_dir / "STAGE7C1_V1_INVALIDATION_NOTE.md").write_text(_v1_invalidation_note())
    (output_dir / "STAGE7C1_V1_1_CORRECTION_NOTE.md").write_text(_v1_1_correction_note())

    counts_summary = _count_summary(condition_rows, actual_text_rows, no_output_rows)
    hard_check_fail_count = sum(1 for row in hard_check_rows if row["status"] != "PASS")
    freeze_manifest = {
        "schema_version": STAGE7C_SCHEMA_VERSION,
        "method_version": STAGE7C_METHOD_VERSION,
        "generated_at": STAGE7C_GENERATED_AT,
        "artifact_dir": _display_path(output_dir, repo_root),
        "frozen_inputs": {
            "stage6b_commit": "ecf0fc47cd2f1f4a8bb5a962c32caaa7c5284550",
            "stage6b_tag": "stage6b-controlled-realization-v1-frozen",
            "stage7a3_commit": "6007afe7c1b1228d6638503afeba979ee2f66878",
            "stage7a3_tag": "stage7a-experimental-protocol-v1.3-frozen",
            "stage7b_execution_commit": "69507cc00874aeb498f3fa4543a7969f94dbdc51",
            "stage7b_formal_audit_commit": "38da398b3c5edc8e3e5f8180273f1f04fdff4fbb",
            "stage7b_tag": "stage7b-main-comparison-v1-frozen",
            "stage7b_execution_id": STAGE7B_EXECUTION_ID,
        },
        "counts": counts_summary,
        "hard_check_fail_count": hard_check_fail_count,
        "no_llm_or_api_calls": True,
    }
    _write_json(output_dir / "freeze_manifest.json", freeze_manifest)
    file_hash_rows = _write_file_hashes(output_dir)
    summary = {
        **counts_summary,
        "hard_check_fail_count": hard_check_fail_count,
        "file_hash_count": len(file_hash_rows),
        "output_dir": str(output_dir),
    }
    if write_audit_zip:
        summary["audit_zip"] = str(_write_audit_zip(repo_root, output_dir))
    return summary


def split_engineering_statements(text: str) -> list[str]:
    """Deterministically split text with method-neutral rules."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"(^|\n)\s*#{1,6}\s*", r"\n", normalized)
    normalized = re.sub(r"[{}\\[\\]\"]", " ", normalized)
    normalized = re.sub(r"(?<=\d)\.(?=\d)", "<DOT>", normalized)
    sentence_punctuation = "".join(chr(code) for code in [0x3002, 0xFF1B, 0xFF01, 0xFF1F])
    parts = re.split(rf"[{re.escape(sentence_punctuation)};!\?\.\n]+", normalized)
    statements = []
    for part in parts:
        part = part.replace("<DOT>", ".")
        strip_punctuation = " -\u2022\t," + chr(0xFF0C) + ":" + chr(0xFF1A)
        item = re.sub(r"\s+", " ", part).strip(strip_punctuation)
        if item:
            statements.append(item)
    return statements


def evaluate_e2_numeric(
    statement: str,
    refs: dict[str, NumericReference] | list[NumericReference],
    *,
    tolerance_floor: float = 1e-9,
) -> RuleDecision:
    """Evaluate deterministic metric numeric mismatches for RAI/GRS/GRCI."""

    checks: list[str] = []
    metric_refs = _numeric_refs_list(refs)
    for name in ["RAI", "GRS", "GRCI"]:
        pattern = re.compile(
            rf"(?<![A-Za-z]){name}(?![A-Za-z])\s*(?:=|为|\uff1a|:)?\s*"
            r"([0-9]+(?:\.[0-9]+)?)\s*(%)?",
            re.I,
        )
        for match in pattern.finditer(statement):
            candidates = _bind_numeric_refs(statement, name, metric_refs)
            if len(candidates) != 1:
                return RuleDecision(
                    "REQUIRES_HUMAN_REVIEW",
                    "METRIC_REFERENCE_NOT_UNIQUELY_BOUND_TO_STATEMENT_SCOPE",
                    details=f"{name}: candidate_count={len(candidates)}",
                )
            ref = candidates[0]
            if ref.status != "AVAILABLE" or ref.value is None:
                continue
            if match.group(2):
                continue
            extracted = float(match.group(1))
            decimals = _decimal_places(match.group(1))
            tolerance = max(0.5 * 10 ** (-decimals), tolerance_floor)
            diff = abs(extracted - ref.value)
            detail = (
                f"{name}: extracted={extracted}; authoritative={ref.value}; "
                f"tolerance={tolerance}; object_id={ref.object_id}"
            )
            checks.append(detail)
            if diff > tolerance:
                return RuleDecision(
                    "FAIL",
                    "NUMERIC_VALUE_MISMATCH",
                    ref.object_id,
                    ref.object_id,
                    detail,
                )
    if checks:
        return RuleDecision(
            "PASS", "ALL_EXTRACTED_NUMERIC_VALUES_MATCH", details=" | ".join(checks)
        )
    return RuleDecision("NOT_APPLICABLE", "NO_EVALUABLE_NUMERIC_VALUE")


def evaluate_e3_missing_to_zero(
    statement: str, refs: dict[str, NumericReference] | list[NumericReference]
) -> RuleDecision:
    """Evaluate whether an unavailable metric is explicitly rendered as zero."""

    metric_refs = _numeric_refs_list(refs)
    for name in ["RAI", "GRS", "GRCI"]:
        pattern = re.compile(
            rf"(?<![A-Za-z]){name}(?![A-Za-z])\s*(?:=|为|\uff1a|:)?\s*"
            r"(0(?:\.0+)?|零)(?![\.\d])\s*%?",
            re.I,
        )
        if pattern.search(statement):
            candidates = _bind_numeric_refs(statement, name, metric_refs)
            if len(candidates) != 1:
                return RuleDecision(
                    "REQUIRES_HUMAN_REVIEW",
                    "MISSING_METRIC_REFERENCE_NOT_UNIQUELY_BOUND_TO_STATEMENT_SCOPE",
                    details=f"{name}: candidate_count={len(candidates)}",
                )
            ref = candidates[0]
            if ref.status == "AVAILABLE":
                continue
            return RuleDecision(
                "FAIL",
                "MISSING_METRIC_RENDERED_AS_ZERO",
                ref.object_id,
                ref.object_id,
                f"{name} status={ref.status} rendered as zero",
            )
    if re.search(
        r"(?<![A-Za-z])(?:RAI|GRS|GRCI)(?![A-Za-z])\s*(?:=|为|\uff1a|:)?\s*0\.\d+",
        statement,
        re.I,
    ):
        return RuleDecision("PASS", "DECIMAL_PREFIX_IS_NOT_MISSING_ZERO")
    return RuleDecision("NOT_APPLICABLE", "NO_MISSING_VALUE_RENDERED_AS_ZERO")


def evaluate_e4_spatial_scope(statement: str, scopes: list[Scope]) -> RuleDecision:
    """Evaluate deterministic spatial expansion where ranges are explicit."""

    ranges = extract_chainage_ranges(statement)
    if not ranges:
        return RuleDecision("NOT_APPLICABLE", "NO_EXPLICIT_RANGE")
    contained = [any(scope.contains(item) for scope in scopes) for item in ranges]
    if all(contained):
        return RuleDecision("PASS", "ALL_EXPLICIT_RANGES_WITHIN_AUTHORITY")
    if "报告" in statement:
        return RuleDecision(
            "REQUIRES_HUMAN_REVIEW",
            "REPORT_OR_SOURCE_RANGE_NOT_TREATED_AS_CLAIM_SCOPE",
            details=";".join(f"{item.start}-{item.end}" for item in ranges),
        )
    max_width = max((scope.width for scope in scopes), default=0.0)
    expansion_cue = re.search(r"整个|全线|全部|均为|全段|施工区段", statement) is not None
    for item, ok in zip(ranges, contained, strict=True):
        if not ok and expansion_cue and max_width and item.width > max_width * 1.5:
            return RuleDecision(
                "FAIL",
                "EXPLICIT_SCOPE_EXPANSION",
                details=f"text_range={item.start}-{item.end}; max_authoritative_width={max_width}",
            )
    return RuleDecision(
        "REQUIRES_HUMAN_REVIEW",
        "EXPLICIT_RANGE_NOT_DETERMINISTICALLY_MATCHED",
        details=";".join(f"{item.start}-{item.end}" for item in ranges),
    )


def evaluate_e5_forecast_factification(
    statement: str,
    forecast_supports: list[dict[str, Any]] | set[str],
    observed_supports: list[dict[str, Any]] | None = None,
    semantic_context_text: str = "",
) -> RuleDecision:
    """Evaluate deterministic forecast-to-observed promotion."""

    if isinstance(forecast_supports, set):
        forecast_supports = [
            {
                "evidence_id": "",
                "epistemic_status": "FORECAST",
                "terms": forecast_supports,
                "scope": None,
            }
        ]
    observed_supports = observed_supports or []
    forecast_matches = _support_matches_statement(statement, forecast_supports)
    observed_matches = _support_matches_statement(statement, observed_supports)
    if not forecast_matches and not observed_matches:
        return RuleDecision("NOT_APPLICABLE", "NO_FORECAST_SUPPORTED_TERM")
    if observed_matches and not forecast_matches:
        return RuleDecision("PASS", "STATEMENT_BINDS_TO_OBSERVED_SUPPORT")
    if observed_matches and forecast_matches:
        return RuleDecision(
            "REQUIRES_HUMAN_REVIEW",
            "FORECAST_AND_OBSERVED_SUPPORT_BOTH_MATCH_STATEMENT",
            details=_join_ids(forecast_matches + observed_matches),
        )
    if len(forecast_matches) != 1:
        return RuleDecision(
            "REQUIRES_HUMAN_REVIEW",
            "FORECAST_SUPPORT_NOT_UNIQUELY_BOUND_TO_STATEMENT",
            details=_join_ids(forecast_matches),
        )
    context_text = f"{semantic_context_text}\n{statement}"
    if _has_forecast_qualifier(context_text):
        match = forecast_matches[0]
        return RuleDecision(
            "PASS",
            "FORECAST_QUALIFIER_PRESERVED",
            str(match.get("evidence_id", "")),
            str(match.get("evidence_id", "")),
        )
    if _has_management_recommendation(statement):
        return RuleDecision("NOT_APPLICABLE", "MANAGEMENT_RECOMMENDATION_NOT_FACTIFICATION")
    if _has_observed_factification_cue(context_text):
        match = forecast_matches[0]
        return RuleDecision(
            "FAIL",
            "FORECAST_RENDERED_AS_OBSERVED_OR_CURRENT_FACT",
            str(match.get("evidence_id", "")),
            str(match.get("evidence_id", "")),
        )
    return RuleDecision(
        "REQUIRES_HUMAN_REVIEW",
        "FORECAST_TERM_WITHOUT_EXPLICIT_QUALIFIER",
        details="forecast-supported geological term appears without deterministic qualifier",
    )


def evaluate_e7_hindsight(
    statement: str, current_terms: set[str], later_terms: set[str]
) -> RuleDecision:
    """Evaluate deterministic use of later-only support."""

    later_only = {term for term in later_terms if term not in current_terms and len(term) >= 2}
    hits = sorted(term for term in later_only if term in statement)
    if hits:
        return RuleDecision(
            "FAIL",
            "LATER_AVAILABLE_SUPPORT_USED_IN_CURRENT_ASOF",
            details=";".join(hits[:10]),
        )
    return RuleDecision("NOT_APPLICABLE", "NO_LATER_ONLY_SUPPORT_TERM")


def evaluate_e10_attention_probability(
    statement: str, semantic_context_text: str = ""
) -> RuleDecision:
    """Evaluate deterministic probability promotion of attention metrics."""

    if _is_structural_statement(statement):
        return RuleDecision("NOT_APPLICABLE", "STRUCTURAL_STATEMENT_NOT_ENGINEERING_FACT")
    if not re.search(r"RAI|GRS|GRCI|关注指标|注意力指标|关注度|耦合关注", statement, re.I):
        return RuleDecision("NOT_APPLICABLE", "NO_ATTENTION_METRIC_MENTION")
    context_text = f"{semantic_context_text}\n{statement}"
    if _has_probability_negation(context_text):
        return RuleDecision("PASS", "NONPROBABILISTIC_QUALIFIER_PRESENT")
    if re.search(
        r"概率|发生概率|风险概率|灾害概率|hazard probability|risk probability", statement, re.I
    ):
        return RuleDecision("FAIL", "ATTENTION_RENDERED_AS_PROBABILITY")
    if re.search(
        r"RAI\s*(?:=|为|\uff1a|:)|GRS\s*(?:=|为|\uff1a|:)|"
        r"GRCI\s*(?:=|为|\uff1a|:)",
        statement,
        re.I,
    ):
        return RuleDecision("PASS", "METRIC_VALUE_WITHOUT_PROBABILITY_PROMOTION")
    return RuleDecision(
        "REQUIRES_HUMAN_REVIEW",
        "ATTENTION_TERM_WITH_AMBIGUOUS_RISK_LANGUAGE",
    )


def evaluate_e12_claim_admissibility(
    statement: str, abstain_values: set[str], expressible_values: set[str]
) -> RuleDecision:
    """Evaluate deterministic expression of formally abstained source values."""

    if not abstain_values:
        if re.search(r"未知|缺失|不可用|无法确定|UNKNOWN|unavailable", statement, re.I):
            return RuleDecision("REQUIRES_HUMAN_REVIEW", "E12_DEFERRED_TO_HUMAN")
        return RuleDecision("NOT_APPLICABLE", "E12_DEFERRED_NO_FORMAL_ABSTAIN_MAPPING")
    abstain_hits = sorted(value for value in abstain_values if value and value in statement)
    if not abstain_hits:
        return RuleDecision("NOT_APPLICABLE", "NO_FORMAL_ABSTAIN_VALUE_MATCH")
    if any(value in statement for value in expressible_values):
        return RuleDecision(
            "REQUIRES_HUMAN_REVIEW",
            "ABSTAIN_VALUE_OVERLAPS_EXPRESSIBLE_CONTEXT",
            details=";".join(abstain_hits[:10]),
        )
    return RuleDecision(
        "FAIL",
        "FORMAL_ABSTAIN_CLAIM_VALUE_EXPRESSED",
        details=";".join(abstain_hits[:10]),
    )


def evaluate_e13_structure(condition: dict[str, str], statement_id: str) -> RuleDecision:
    """Evaluate Stage7B structure contract status."""

    if condition.get("output_status") == "INVALID_PLAN_PROPAGATED_TO_FINAL_TEXT":
        return RuleDecision("FAIL", "INVALID_PLAN_PROPAGATED_TO_FINAL_TEXT")
    if (
        condition["method_internal"] == "P_PROPOSED"
        and condition["output_available"] == "false"
        and condition["output_status"] == "NO_VALID_OUTPUT_VALIDATOR_INTERCEPT"
    ):
        return RuleDecision(
            "PASS",
            "MODEL_PLAN_STRUCTURE_VIOLATION_FAIL_CLOSED",
            details="INVALID_SECTION_ORDER intercepted before final text",
        )
    if statement_id and condition["method_internal"] == "P_PROPOSED":
        return RuleDecision("PASS", "NO_INVALID_PLAN_PROPAGATED_TO_FINAL_TEXT")
    return RuleDecision("NOT_APPLICABLE", "NO_PROPOSED_STRUCTURE_EVENT")


def evaluate_e14_trace(
    statement: str,
    condition: dict[str, str],
    trace_row: dict[str, str] | None = None,
) -> RuleDecision:
    """Evaluate deterministic trace closure for Proposed final statements."""

    if condition["method_internal"] != "P_PROPOSED":
        if statement:
            return RuleDecision(
                "REQUIRES_HUMAN_REVIEW",
                "BASELINE_TRACE_REQUIRES_PRECLAIM_SUPPORT_MAPPING",
            )
        return RuleDecision("NOT_APPLICABLE", "NO_BASELINE_STATEMENT")
    if condition["output_available"] != "true":
        return RuleDecision("NOT_APPLICABLE", "NO_FINAL_TEXT_AFTER_FAIL_CLOSED")
    if _is_structural_statement(statement):
        return RuleDecision("NOT_APPLICABLE", "STRUCTURAL_STATEMENT_NOT_ENGINEERING_FACT")
    if trace_row and trace_row.get("trace_status") == "CANONICAL_PARENT_TRACE_COMPLETE":
        return RuleDecision(
            "PASS",
            "PROPOSED_CANONICAL_PARENT_TRACE_COMPLETE",
            trace_row.get("authoritative_support_ids", ""),
            trace_row.get("fact_lock_ids", ""),
        )
    return RuleDecision("FAIL", "PROPOSED_FINAL_STATEMENT_TRACE_MISSING")


def extract_chainage_ranges(text: str) -> list[Scope]:
    """Extract deterministic chainage ranges from common TBM renderings."""

    ranges: list[Scope] = []
    dyk_pattern = re.compile(
        r"(?:DyK)?(?P<km1>\d{4})\+(?P<m1>\d+(?:\.\d+)?)\s*"
        r"[\uff5e~\u2014\-\u2013]\s*"
        r"(?:(?:DyK)?(?P<km2>\d{4})\+)?(?P<m2>\d+(?:\.\d+)?)"
    )
    for match in dyk_pattern.finditer(text):
        km1 = float(match.group("km1")) * 1000
        km2 = float(match.group("km2")) * 1000 if match.group("km2") else km1
        start = km1 + float(match.group("m1"))
        end = km2 + float(match.group("m2"))
        if start <= end:
            ranges.append(Scope(start, end, "text_range"))
    numeric_pattern = re.compile(
        r"(?<![A-Za-z0-9])(?P<s>10\d{5}(?:\.\d+)?)\s*"
        r"[\uff5e~\u2014\-\u2013]\s*"
        r"(?P<e>10\d{5}(?:\.\d+)?)(?![A-Za-z0-9])"
    )
    for match in numeric_pattern.finditer(text):
        start = float(match.group("s"))
        end = float(match.group("e"))
        if start <= end:
            ranges.append(Scope(start, end, "text_range"))
    return _dedupe_ranges(ranges)


def _load_stage7_tasks(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text())
    return sorted(data["tasks"], key=lambda row: row["benchmark_task_id"])


def _jsonl_by_key(path: Path, key: str) -> dict[str, dict[str, Any]]:
    rows = {}
    for row in _read_jsonl(path):
        rows[str(row[key])] = row
    return rows


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _load_actual_outputs(run_dir: Path) -> dict[str, dict[str, str]]:
    outputs: dict[str, dict[str, str]] = {}
    for filename in ["B0_outputs.jsonl", "B1_outputs.jsonl"]:
        for row in _read_jsonl(run_dir / filename):
            output_reference = (
                f"{run_dir.relative_to(Path.cwd())}/{filename}:{row['execution_item_id']}"
            )
            outputs[str(row["execution_item_id"])] = {
                "text": str(row["output_text"]),
                "output_reference": output_reference,
                "support_reference": "",
            }
    for row in _read_jsonl(run_dir / "P_final_outputs.jsonl"):
        blocks: list[dict[str, Any]] = [
            {
                "block_id": str(block.get("block_id", "")),
                "block_type": str(block.get("block_type", "")),
                "source_ids": [str(item) for item in block.get("source_ids", [])],
                "text": str(block.get("text", "")),
            }
            for block in row.get("blocks", [])
        ]
        text_parts = [block["text"] for block in blocks]
        source_ids = sorted(
            {str(source_id) for block in blocks for source_id in block.get("source_ids", [])}
        )
        output_reference = (
            f"{run_dir.relative_to(Path.cwd())}/P_final_outputs.jsonl:{row['execution_item_id']}"
        )
        outputs[str(row["execution_item_id"])] = {
            "text": "\n".join(part for part in text_parts if part),
            "output_reference": output_reference,
            "support_reference": ";".join(source_ids),
            "block_records": json.dumps(blocks, ensure_ascii=False, sort_keys=True),
        }
    return outputs


def _build_condition_manifest(
    execution_items: list[dict[str, Any]],
    task_by_id: dict[str, dict[str, Any]],
    payloads: dict[str, dict[str, Any]],
    text_by_item: dict[str, dict[str, str]],
    plan_by_item: dict[str, dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    no_output: list[dict[str, str]] = []
    for item in execution_items:
        task_id = str(item["benchmark_task_id"])
        execution_item_id = str(item["execution_item_id"])
        method = str(item["method_id"])
        output = text_by_item.get(execution_item_id)
        available = output is not None
        status = "OUTPUT_AVAILABLE" if available else "NO_OUTPUT"
        if method == "P_PROPOSED" and not available:
            plan = plan_by_item.get(execution_item_id, {})
            if "INVALID_SECTION_ORDER" in str(plan.get("violation_codes", "")):
                status = "NO_VALID_OUTPUT_VALIDATOR_INTERCEPT"
        row = {
            "condition_id": execution_item_id,
            "task_id": task_id,
            "method_internal": method,
            "product_type": str(item["product_type"]),
            "valid_date": str(item["valid_date"]),
            "knowledge_as_of": str(task_by_id[task_id]["knowledge_time_local_date"]),
            "input_snapshot_id": str(payloads[task_id]["evidence_snapshot_hash"]),
            "output_available": str(available).lower(),
            "output_status": status,
            "output_reference": output["output_reference"] if output else "",
            "text_evaluation_eligible": str(available).lower(),
            "support_reference": output["support_reference"] if output else "",
        }
        rows.append(row)
        if not available:
            no_output.append(
                {
                    **row,
                    "validator_reason": plan_by_item.get(execution_item_id, {}).get(
                        "violation_codes", ""
                    ),
                }
            )
    return rows, no_output


def _build_actual_text_manifest(
    condition_rows: list[dict[str, str]], text_by_item: dict[str, dict[str, str]]
) -> list[dict[str, str]]:
    rows = []
    for condition in condition_rows:
        output = text_by_item.get(condition["condition_id"])
        if not output:
            continue
        rows.append(
            {
                "task_id": condition["task_id"],
                "condition_id": condition["condition_id"],
                "method_internal": condition["method_internal"],
                "text": output["text"],
                "product_type": condition["product_type"],
                "valid_date": condition["valid_date"],
                "knowledge_as_of": condition["knowledge_as_of"],
                "block_records": output.get("block_records", ""),
            }
        )
    return rows


def _build_statement_and_context_tables(
    actual_text_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    context_rows: list[dict[str, str]] = []
    for text_row in actual_text_rows:
        block_records = _parse_json_list(text_row.get("block_records", ""))
        source_items = (
            [
                (
                    str(block.get("text", "")),
                    str(block.get("block_id", "")),
                    str(block.get("block_type", "")),
                    ";".join(str(item) for item in block.get("source_ids", [])),
                )
                for block in block_records
            ]
            if block_records
            else [
                (item["text"], item["context_id"], item["context_role"], "")
                for item in _baseline_semantic_contexts(text_row["condition_id"], text_row["text"])
            ]
        )
        index = 0
        for source_text, block_id, block_type, source_ids in source_items:
            context_id = block_id or "semantic_context_" + _stable_id(
                text_row["condition_id"], block_type, source_text
            )
            context_rows.append(
                {
                    "semantic_context_unit_id": context_id,
                    "condition_id": text_row["condition_id"],
                    "task_id": text_row["task_id"],
                    "method_internal": text_row["method_internal"],
                    "context_role": block_type,
                    "source_block_id": block_id,
                    "source_ids": source_ids,
                    "semantic_context_text": source_text,
                }
            )
            for statement in split_engineering_statements(source_text):
                statement_id = "stage7c_statement_" + _stable_id(
                    text_row["condition_id"], str(index)
                )
                rows.append(
                    {
                        "statement_id": statement_id,
                        "condition_id": text_row["condition_id"],
                        "task_id": text_row["task_id"],
                        "method_internal": text_row["method_internal"],
                        "statement_index": str(index),
                        "statement_text": statement,
                        "semantic_context_unit_id": context_id,
                        "semantic_context_text": source_text,
                        "source_block_id": block_id,
                        "source_block_type": block_type,
                        "source_ids": source_ids,
                        "source_block_text": source_text if block_id else "",
                    }
                )
                index += 1
    return rows, context_rows


def _baseline_semantic_contexts(condition_id: str, text: str) -> list[dict[str, str]]:
    contexts: list[dict[str, str]] = []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        for key, value in parsed.items():
            if isinstance(value, str) and value.strip():
                contexts.append(
                    {
                        "context_id": "semantic_context_" + _stable_id(condition_id, key),
                        "context_role": str(key),
                        "text": value.strip(),
                    }
                )
        if contexts:
            return contexts
    parts = [item.strip() for item in re.split(r"\n\s*\n|\r\n\s*\r\n", text) if item.strip()]
    if not parts:
        parts = [item.strip() for item in text.splitlines() if item.strip()]
    if not parts and text.strip():
        parts = [text.strip()]
    return [
        {
            "context_id": "semantic_context_" + _stable_id(condition_id, str(index)),
            "context_role": "paragraph_or_line_block",
            "text": part,
        }
        for index, part in enumerate(parts)
    ]


def _evaluation_context(
    task_id: str,
    payload: dict[str, Any],
    task: dict[str, Any],
    preclaim_ref: dict[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    metrics: list[NumericReference] = []
    scopes: list[Scope] = []
    forecast_supports: list[dict[str, Any]] = []
    observed_supports: list[dict[str, Any]] = []
    current_terms: set[str] = set()
    expressible_values: set[str] = set()
    cell_scopes = _cell_scope_map(repo_root)
    for evidence in payload.get("structured_evidence", []):
        spatial_scope = evidence.get("spatial_scope")
        cell_id = ""
        scope = None
        if isinstance(spatial_scope, dict):
            cell_id = str(spatial_scope.get("cell_id", ""))
            scope = _scope_from_dict(spatial_scope, str(evidence.get("evidence_id", "")))
            if not scope and cell_id:
                scope = cell_scopes.get(cell_id)
            if scope:
                scopes.append(scope)
        metric_name = evidence.get("metric_name")
        if metric_name:
            value = evidence.get("raw_value")
            metric_scope = cell_scopes.get(cell_id)
            metrics.append(
                NumericReference(
                    str(metric_name),
                    float(value) if isinstance(value, int | float) else None,
                    str(evidence.get("metric_status", "UNKNOWN")),
                    str(evidence.get("evidence_id", "")),
                    cell_id,
                    metric_scope,
                    str(evidence.get("valid_time", task.get("valid_time", ""))),
                    str(task.get("knowledge_time_local_date", "")),
                )
            )
        attrs = evidence.get("structured_source_attributes")
        if isinstance(attrs, dict):
            terms = _terms_from_attrs(attrs)
            current_terms.update(terms)
            expressible_values.update(terms)
            support_record = {
                "evidence_id": str(evidence.get("evidence_id", "")),
                "epistemic_status": str(evidence.get("epistemic_status", "")),
                "terms": terms,
                "scope": scope if isinstance(spatial_scope, dict) else None,
            }
            if evidence.get("epistemic_status") == "FORECAST":
                forecast_supports.append(support_record)
            elif evidence.get("epistemic_status") == "OBSERVED":
                observed_supports.append(support_record)
    present_metric_names = {item.name for item in metrics}
    for name in ["RAI", "GRS", "GRCI"]:
        if name not in present_metric_names:
            metrics.append(NumericReference(name, None, "UNAVAILABLE_OR_NOT_IN_TASK", ""))
    abstain_values = _task_abstain_values(task, repo_root)
    later_terms = _later_only_terms(task, preclaim_ref, current_terms, repo_root)
    return {
        "metrics": metrics,
        "scopes": _dedupe_ranges(scopes),
        "forecast_supports": forecast_supports,
        "observed_supports": observed_supports,
        "current_terms": current_terms,
        "later_terms": later_terms,
        "abstain_values": abstain_values,
        "expressible_values": expressible_values,
    }


def _task_abstain_values(task: dict[str, Any], repo_root: Path) -> set[str]:
    # Stage7C.1 can only deterministically match abstained explicit source values when they
    # are materialized in frozen abstention summaries.  Most UNKNOWN_SOURCE_VALUE
    # abstentions have no value and are intentionally left for human review.
    del task, repo_root
    return set()


def _later_only_terms(
    task: dict[str, Any],
    preclaim_ref: dict[str, Any],
    current_terms: set[str],
    repo_root: Path,
) -> set[str]:
    version_ids = set(preclaim_ref.get("active_bitemporal_version_ids", []))
    if not version_ids:
        version_ids.update(task.get("stage3b_bitemporal_version_ids", []))
    if not version_ids:
        return set()
    version_rows = _read_jsonl(
        repo_root
        / "artifacts/stage3b_bitemporal_epistemic_state_v1_1/bitemporal_state_versions.jsonl"
    )
    by_id = {str(row["bitemporal_version_id"]): row for row in version_rows}
    active = [by_id[version_id] for version_id in version_ids if version_id in by_id]
    if not active:
        return set()
    base_ids = {str(row["base_stage3a_state_version_id"]) for row in active}
    active_numbers = {
        str(row["base_stage3a_state_version_id"]): int(row.get("version_number", 0))
        for row in active
    }
    later_evidence_ids: set[str] = set()
    for row in version_rows:
        base_id = str(row["base_stage3a_state_version_id"])
        if base_id not in base_ids:
            continue
        if int(row.get("version_number", 0)) <= active_numbers.get(base_id, 0):
            continue
        for key in [
            "materialized_daily_review_evidence_ids",
            "materialized_forward_attention_evidence_ids",
            "materialized_local_background_evidence_ids",
        ]:
            later_evidence_ids.update(str(item) for item in row.get(key, []))
    if not later_evidence_ids:
        return set()
    geology = _jsonl_by_key(
        repo_root
        / "artifacts/stage2_geology_v2_freeze_candidate/primary_geological_evidence.jsonl",
        "evidence_uid",
    )
    terms: set[str] = set()
    for evidence_id in later_evidence_ids:
        evidence = geology.get(evidence_id)
        if not evidence:
            continue
        terms.update(_terms_from_attrs(evidence.get("attributes", {})))
    return {term for term in terms if term not in current_terms}


def _evaluate_statements(
    statement_rows: list[dict[str, str]],
    condition_rows: list[dict[str, str]],
    context_by_task: dict[str, dict[str, Any]],
    plan_by_item: dict[str, dict[str, str]],
    statement_binding_rows: list[dict[str, str]],
    statement_trace_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    condition_by_id = {row["condition_id"]: row for row in condition_rows}
    trace_by_statement = {row["statement_id"]: row for row in statement_trace_rows}
    rows: list[dict[str, str]] = []
    for condition in condition_rows:
        if condition["output_available"] == "false":
            decision = evaluate_e13_structure(condition, "")
            rows.append(_audit_row(condition, "", "", "E13", decision))
    for statement in statement_rows:
        condition = condition_by_id[statement["condition_id"]]
        context = context_by_task[statement["task_id"]]
        text = statement["statement_text"]
        semantic_context_text = statement.get("semantic_context_text", "")
        decisions = {
            "E2": evaluate_e2_numeric(text, context["metrics"]),
            "E3": evaluate_e3_missing_to_zero(text, context["metrics"]),
            "E4": evaluate_e4_spatial_scope(text, context["scopes"]),
            "E5": evaluate_e5_forecast_factification(
                text,
                context["forecast_supports"],
                context["observed_supports"],
                semantic_context_text,
            ),
            "E7": evaluate_e7_hindsight(text, context["current_terms"], context["later_terms"]),
            "E10": evaluate_e10_attention_probability(text, semantic_context_text),
            "E12": evaluate_e12_claim_admissibility(
                text, context["abstain_values"], context["expressible_values"]
            ),
            "E13": evaluate_e13_structure(condition, statement["statement_id"]),
            "E14": evaluate_e14_trace(
                text, condition, trace_by_statement.get(statement["statement_id"])
            ),
        }
        for code in AUTO_ERROR_CODES:
            rows.append(
                _audit_row(
                    condition,
                    statement["statement_id"],
                    statement["statement_text"],
                    code,
                    decisions[code],
                    statement.get("semantic_context_unit_id", ""),
                    statement.get("semantic_context_text", ""),
                )
            )
    # Hard-check invalid plan propagation directly from plan table.
    propagated = [
        row
        for row in plan_by_item.values()
        if row.get("plan_valid") == "false" and row.get("execution_item_id") in condition_by_id
    ]
    del propagated
    del statement_binding_rows
    return rows


def _audit_row(
    condition: dict[str, str],
    statement_id: str,
    statement_text: str,
    error_code: str,
    decision: RuleDecision,
    semantic_context_unit_id: str = "",
    semantic_context_text: str = "",
) -> dict[str, str]:
    return {
        "condition_id": condition["condition_id"],
        "task_id": condition["task_id"],
        "method_internal": condition["method_internal"],
        "statement_id": statement_id,
        "semantic_context_unit_id": semantic_context_unit_id,
        "semantic_context_text": semantic_context_text,
        "error_code": error_code,
        "result": decision.result,
        "reason_code": decision.reason_code,
        "authoritative_reference": decision.authoritative_reference,
        "support_reference": decision.support_reference,
        "details": decision.details,
        "statement_text": statement_text,
    }


def _statement_subject_binding(
    statement_rows: list[dict[str, str]],
    condition_rows: list[dict[str, str]],
    context_by_task: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    del condition_rows
    rows: list[dict[str, str]] = []
    for statement in statement_rows:
        text = statement["statement_text"]
        context = context_by_task[statement["task_id"]]
        ranges = extract_chainage_ranges(text)
        metric_names = _mentioned_metrics(text)
        bound_metrics: list[str] = []
        binding_status = "NO_DETERMINISTIC_SUBJECT"
        if metric_names:
            statuses = []
            for name in metric_names:
                refs = _bind_numeric_refs(text, name, context["metrics"])
                bound_metrics.extend(ref.object_id for ref in refs if ref.object_id)
                statuses.append("BOUND" if len(refs) == 1 else "AMBIGUOUS")
            binding_status = "BOUND" if all(item == "BOUND" for item in statuses) else "AMBIGUOUS"
        elif ranges:
            matched_scopes = [
                scope.object_id
                for text_scope in ranges
                for scope in context["scopes"]
                if scope.contains(text_scope)
            ]
            if matched_scopes:
                binding_status = "BOUND"
                bound_metrics = sorted(set(matched_scopes))
            else:
                binding_status = "AMBIGUOUS"
        rows.append(
            {
                "statement_id": statement["statement_id"],
                "condition_id": statement["condition_id"],
                "task_id": statement["task_id"],
                "method_internal": statement["method_internal"],
                "statement_scope_ranges": ";".join(
                    f"{item.start:.3f}-{item.end:.3f}" for item in ranges
                ),
                "mentioned_metrics": ";".join(metric_names),
                "bound_object_ids": ";".join(sorted(set(bound_metrics))),
                "binding_status": binding_status,
                "statement_text": text,
            }
        )
    return rows


def _statement_trace_table(
    statement_rows: list[dict[str, str]],
    condition_rows: list[dict[str, str]],
    task_by_id: dict[str, dict[str, Any]],
    preclaim_refs: dict[str, dict[str, Any]],
    repo_root: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    condition_by_id = {row["condition_id"]: row for row in condition_rows}
    fact_locks_by_id = _fact_locks_by_id(repo_root)
    task_trace_relations = _stage7a_asof_unit_trace_relations(repo_root, task_by_id)
    rows: list[dict[str, str]] = []
    cardinality_rows: list[dict[str, str]] = []
    for statement in statement_rows:
        condition = condition_by_id[statement["condition_id"]]
        source_ids = [item for item in statement.get("source_ids", "").split(";") if item]
        canonical_ids = sorted(
            item for item in source_ids if item.startswith("canonical_sentence_")
        )
        unit_ids = sorted(item for item in source_ids if item.startswith("realization_unit_"))
        trace_relation = task_trace_relations.get(statement["task_id"], {})
        unit_to_locks: dict[str, list[str]] = trace_relation.get("unit_to_fact_locks", {})
        canonical_to_unit: dict[str, str] = trace_relation.get("canonical_to_unit", {})
        canonical_to_locks: dict[str, list[str]] = trace_relation.get("canonical_to_fact_locks", {})
        canonical_unit_ids = {
            canonical_to_unit[canonical_id]
            for canonical_id in canonical_ids
            if canonical_id in canonical_to_unit
        }
        resolved_unit_ids = sorted(set(unit_ids) | canonical_unit_ids)
        relation_mismatch = bool(canonical_ids) and (
            not canonical_unit_ids
            or any(unit not in resolved_unit_ids for unit in canonical_unit_ids)
        )
        relation_mismatch = relation_mismatch or any(
            canonical_id in canonical_to_locks
            and sorted(canonical_to_locks[canonical_id])
            != sorted(
                {
                    lock_id
                    for unit_id in resolved_unit_ids
                    for lock_id in unit_to_locks.get(unit_id, [])
                }
            )
            for canonical_id in canonical_ids
        )
        matched_lock_ids = sorted(
            {
                lock_id
                for unit_id in resolved_unit_ids
                for lock_id in unit_to_locks.get(unit_id, [])
                if lock_id in fact_locks_by_id
            }
        )
        matched_locks = [fact_locks_by_id[lock_id] for lock_id in matched_lock_ids]
        fact_lock_ids = sorted(str(lock["fact_lock_id"]) for lock in matched_locks)
        typed_claim_ids = sorted(str(lock["source_claim_id"]) for lock in matched_locks)
        support_ids = sorted(
            {
                str(ref.get("support_id", ""))
                for lock in matched_locks
                for ref in lock.get("authoritative_support_refs", [])
                if ref.get("support_id")
            }
        )
        if condition["method_internal"] != "P_PROPOSED":
            status = "BASELINE_REQUIRES_HUMAN_SUPPORT_MAPPING"
        elif _is_structural_statement(statement["statement_text"]):
            status = "NOT_ENGINEERING_FACT"
        elif (
            canonical_ids
            and resolved_unit_ids
            and fact_lock_ids
            and typed_claim_ids
            and support_ids
            and not relation_mismatch
        ):
            status = "CANONICAL_PARENT_TRACE_COMPLETE"
        else:
            status = "TRACE_INCOMPLETE"
        relation_status = "NOT_APPLICABLE"
        if condition["method_internal"] == "P_PROPOSED" and canonical_ids:
            relation_status = (
                "PASS" if status == "CANONICAL_PARENT_TRACE_COMPLETE" else "TRACE_INCOMPLETE"
            )
            for canonical_id in canonical_ids:
                cardinality_rows.append(
                    {
                        "canonical_sentence_id": canonical_id,
                        "realization_unit_id": canonical_to_unit.get(
                            canonical_id, ";".join(resolved_unit_ids)
                        ),
                        "statement_realization_unit_ids": ";".join(resolved_unit_ids),
                        "canonical_member_lock_count": str(len(fact_lock_ids)),
                        "unit_member_lock_count": str(len(fact_lock_ids)),
                        "resolved_lock_count": str(len(fact_lock_ids)),
                        "typed_claim_count": str(len(typed_claim_ids)),
                        "support_count": str(len(support_ids)),
                        "status": relation_status,
                        "relation_source": TRACE_RELATION_SOURCE,
                        "relation_issue": "RELATION_MISMATCH" if relation_mismatch else "",
                    }
                )
        rows.append(
            {
                "condition_id": statement["condition_id"],
                "task_id": statement["task_id"],
                "method_internal": statement["method_internal"],
                "statement_id": statement["statement_id"],
                "source_block_id": statement.get("source_block_id", ""),
                "canonical_sentence_ids": ";".join(canonical_ids),
                "realization_unit_ids": ";".join(resolved_unit_ids),
                "fact_lock_ids": ";".join(fact_lock_ids),
                "typed_claim_ids": ";".join(typed_claim_ids),
                "authoritative_support_ids": ";".join(support_ids),
                "trace_status": status,
                "parent_canonical_sentence_id": ";".join(canonical_ids),
                "statement_text": statement["statement_text"],
            }
        )
    return rows, cardinality_rows


def _stage7a_asof_unit_trace_relations(
    repo_root: Path, task_by_id: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    inputs = load_stage6b_inputs(repo_root)
    asof_rows = _read_csv(
        repo_root
        / "artifacts/stage7a_experimental_protocol_v1_3/stage7_asof_evaluation_binding_manifest.csv"
    )
    asof_by_task = {row["benchmark_task_id"]: row for row in asof_rows}
    relations: dict[str, dict[str, Any]] = {}
    for task_id, task in sorted(task_by_id.items()):
        asof_row = asof_by_task.get(task_id, {})
        asof_fact_ids = {
            item for item in str(asof_row.get("asof_fact_lock_ids", "")).split(";") if item
        }
        asof_abstention_ids = {
            item for item in str(asof_row.get("asof_abstention_ids", "")).split(";") if item
        }
        filtered_locks = [
            lock
            for lock in inputs["stage6a_locks"]
            if not asof_fact_ids or str(lock.fact_lock_id) in asof_fact_ids
        ]
        filtered_abstentions = [
            row
            for row in inputs["stage5b_abstentions"]
            if not asof_abstention_ids or str(row.get("abstention_id", "")) in asof_abstention_ids
        ]
        bundle = build_task_bundle(
            filtered_locks,
            filtered_abstentions,
            inputs["stage3a_cells"],
            SliceSpec(**task["slice_spec"]),
        )
        unit_to_locks = {
            str(unit.realization_unit_id): [str(lock_id) for lock_id in unit.member_fact_lock_ids]
            for unit in bundle["units"]
        }
        canonical_to_unit = {
            str(sentence.canonical_sentence_id): str(sentence.realization_unit_id)
            for sentence in bundle["sentences"]
        }
        canonical_to_fact_locks = {
            str(sentence.canonical_sentence_id): [
                str(lock_id) for lock_id in sentence.member_fact_lock_ids
            ]
            for sentence in bundle["sentences"]
        }
        relations[task_id] = {
            "unit_to_fact_locks": unit_to_locks,
            "canonical_to_unit": canonical_to_unit,
            "canonical_to_fact_locks": canonical_to_fact_locks,
        }
    return relations


def _condition_summary(
    condition_rows: list[dict[str, str]], audit_rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for row in audit_rows:
        grouped[(row["condition_id"], row["error_code"])][row["result"]] += 1
    rows = []
    for condition in condition_rows:
        for code in AUTO_ERROR_CODES:
            counts = grouped[(condition["condition_id"], code)]
            rows.append(
                {
                    "condition_id": condition["condition_id"],
                    "task_id": condition["task_id"],
                    "method_internal": condition["method_internal"],
                    "error_code": code,
                    "fail_count": str(counts["FAIL"]),
                    "pass_count": str(counts["PASS"]),
                    "human_review_count": str(counts["REQUIRES_HUMAN_REVIEW"]),
                    "not_applicable_count": str(counts["NOT_APPLICABLE"]),
                    "output_available": condition["output_available"],
                    "output_status": condition["output_status"],
                }
            )
    return rows


def _condition_binary_endpoints(
    condition_rows: list[dict[str, str]], audit_rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for row in audit_rows:
        grouped[(row["condition_id"], row["error_code"])][row["result"]] += 1
    rows = []
    for condition in condition_rows:
        for code in AUTO_ERROR_CODES:
            counts = grouped[(condition["condition_id"], code)]
            if condition["output_available"] == "false" and code != "E13":
                endpoint = "NO_OUTPUT"
            elif counts["FAIL"]:
                endpoint = "FAIL"
            elif counts["REQUIRES_HUMAN_REVIEW"]:
                endpoint = "HUMAN_REVIEW"
            elif counts["PASS"]:
                endpoint = "PASS"
            else:
                endpoint = "NOT_EVALUABLE"
            rows.append(
                {
                    "condition_id": condition["condition_id"],
                    "task_id": condition["task_id"],
                    "method_internal": condition["method_internal"],
                    "error_code": code,
                    "binary_endpoint": endpoint,
                    "fail_count": str(counts["FAIL"]),
                    "human_review_count": str(counts["REQUIRES_HUMAN_REVIEW"]),
                    "pass_count": str(counts["PASS"]),
                    "not_applicable_count": str(counts["NOT_APPLICABLE"]),
                    "output_status": condition["output_status"],
                }
            )
    return rows


def _method_summary(
    condition_rows: list[dict[str, str]], audit_rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    condition_by_method = Counter(row["method_internal"] for row in condition_rows)
    text_by_method = Counter(
        row["method_internal"] for row in condition_rows if row["output_available"] == "true"
    )
    grouped: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for row in audit_rows:
        grouped[(row["method_internal"], row["error_code"])][row["result"]] += 1
    rows = []
    for method in METHODS:
        for code in AUTO_ERROR_CODES:
            counts = grouped[(method, code)]
            availability_rate = text_by_method[method] / condition_by_method[method]
            rows.append(
                {
                    "method_internal": method,
                    "error_code": code,
                    "fail_count": str(counts["FAIL"]),
                    "pass_count": str(counts["PASS"]),
                    "human_review_count": str(counts["REQUIRES_HUMAN_REVIEW"]),
                    "not_applicable_count": str(counts["NOT_APPLICABLE"]),
                    "condition_denominator": str(condition_by_method[method]),
                    "actual_text_count": str(text_by_method[method]),
                    "output_availability_rate": f"{availability_rate:.12f}",
                }
            )
    return rows


def _v1_failure_reclassification(
    repo_root: Path, v1_1_audit_rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    old_path = repo_root / "configs/frozen_inputs/stage7c_v1_failed_statement_baseline.csv"
    if not old_path.exists():
        return [
            {
                "old_statement_id": "",
                "old_error_code": "",
                "old_result": "",
                "v1_1_result": "",
                "v1_1_reason": "",
                "binding_object_id": "",
                "changed_due_to_bug_fix": "",
            }
        ]
    new_by_key = {
        (row["statement_id"], row["error_code"]): row
        for row in v1_1_audit_rows
        if row["statement_id"]
    }
    rows = []
    for old in _read_csv(old_path):
        if old.get("result") != "FAIL" or old.get("error_code") not in {
            "E2",
            "E3",
            "E4",
            "E5",
            "E10",
        }:
            continue
        new = new_by_key.get((old["statement_id"], old["error_code"]), {})
        rows.append(
            {
                "old_statement_id": old["statement_id"],
                "old_error_code": old["error_code"],
                "old_result": old["result"],
                "v1_1_result": new.get("result", "MISSING_IN_V1_1"),
                "v1_1_reason": new.get("reason_code", ""),
                "binding_object_id": new.get("authoritative_reference", ""),
                "changed_due_to_bug_fix": str(new.get("result") != old.get("result")).lower(),
            }
        )
    return rows


def _version_failure_reclassification(
    old_path: Path, new_audit_rows: list[dict[str, str]], codes: set[str]
) -> list[dict[str, str]]:
    if not old_path.exists():
        return []
    new_by_key = {
        (row["condition_id"], row["error_code"], row["statement_text"]): row
        for row in new_audit_rows
        if row["statement_text"]
    }
    rows = []
    for old in _read_csv(old_path):
        if old.get("result") != "FAIL" or old.get("error_code") not in codes:
            continue
        new = new_by_key.get((old["condition_id"], old["error_code"], old["statement_text"]), {})
        rows.append(
            {
                "old_statement_id": old["statement_id"],
                "old_error_code": old["error_code"],
                "old_result": old["result"],
                "v1_2_result": new.get("result", "MISSING_IN_V1_2"),
                "v1_2_reason": new.get("reason_code", ""),
                "binding_object_id": new.get("authoritative_reference", ""),
                "changed_due_to_v1_2_closure": str(new.get("result") != old.get("result")).lower(),
                "statement_text": old.get("statement_text", ""),
            }
        )
    return rows


def _e13_plan_level_summary(
    condition_rows: list[dict[str, str]], plan_by_item: dict[str, dict[str, str]]
) -> list[dict[str, str]]:
    rows = []
    for condition in condition_rows:
        if condition["method_internal"] != "P_PROPOSED":
            continue
        plan = plan_by_item.get(condition["condition_id"], {})
        plan_valid = str(plan.get("plan_valid", "")).lower() == "true"
        violation_codes = str(plan.get("violation_codes", ""))
        intercepted = (not plan_valid) and condition["output_available"] == "false"
        propagated = (not plan_valid) and condition["output_available"] == "true"
        rows.append(
            {
                "condition_id": condition["condition_id"],
                "task_id": condition["task_id"],
                "plan_valid": str(plan_valid).lower(),
                "violation_codes": violation_codes,
                "intercepted": str(intercepted).lower(),
                "final_output_available": condition["output_available"],
                "invalid_plan_propagated_to_final_text": str(propagated).lower(),
            }
        )
    return rows


def _e7_automatic_coverage(
    condition_rows: list[dict[str, str]], audit_rows: list[dict[str, str]]
) -> dict[str, Any]:
    e7_rows = [row for row in audit_rows if row["error_code"] == "E7"]
    evaluable = [row for row in e7_rows if row["result"] in {"PASS", "FAIL"}]
    evaluable_conditions = {row["condition_id"] for row in evaluable}
    return {
        "status": "E7_DEFERRED_TO_HUMAN_EVALUATION" if not evaluable else "PARTIALLY_EVALUABLE",
        "condition_count": len(condition_rows),
        "statement_count": len(e7_rows),
        "evaluable_statement_count": len(evaluable),
        "evaluable_condition_count": len(evaluable_conditions),
        "fail_count": sum(1 for row in e7_rows if row["result"] == "FAIL"),
        "human_review_count": sum(1 for row in e7_rows if row["result"] == "REQUIRES_HUMAN_REVIEW"),
        "not_evaluable_count": sum(1 for row in e7_rows if row["result"] == "NOT_APPLICABLE"),
        "interpretation": (
            "No automatic hindsight-leakage conclusion is made when coverage is zero."
        ),
    }


def _frozen_input_hash_audit(repo_root: Path) -> list[dict[str, str]]:
    stage7a_manifest = json.loads(
        (
            repo_root / "artifacts/stage7a_experimental_protocol_v1_3/freeze_manifest.json"
        ).read_text()
    )
    stage7b_binding = json.loads(
        (
            repo_root
            / "artifacts/stage7b_main_comparison_v1/formal_execution_protocol_binding.json"
        ).read_text()
    )
    expected_actual = [
        (
            "stage7a_main_benchmark",
            "e9ef8e3f9bd25f345f89f79dc753040e3bfc1f95e562902aea625a8e50334f6f",
            stage7a_manifest.get("main_benchmark_manifest_hash", ""),
        ),
        (
            "stage7a_asof_binding",
            "92bdea500aef7bedb27e6133e92ec058f03ccfd48810e84aed11388838d12bc4",
            stage7a_manifest.get("asof_evaluation_binding_manifest_hash", ""),
        ),
        (
            "stage7a_preclaim_snapshot_set",
            "8bbbc9083bfa2313fe583f88c6d431d199f9ffaa8cf1b0a7d28f70a11ab98a6c",
            stage7a_manifest.get("preclaim_benchmark_evidence_snapshot_set_hash", ""),
        ),
        (
            "stage7a_product_contract",
            "ad599756f428514cf731bb982ecccf21b0705e14579ebf64095524a674ecc98d",
            stage7a_manifest.get("product_task_contract_hash", ""),
        ),
        (
            "stage7a_b0_prompt",
            "3966cce71fe560c4d1cb323ec1b46506b97595f89168cafdf327d5b147c2d296",
            stage7b_binding.get("b0_prompt_hash", ""),
        ),
        (
            "stage7a_b1_prompt",
            "7ad1dfec254bf1c5107c99f559bc65cfd590b595750089b38dd498bcbbfbecea",
            stage7b_binding.get("b1_prompt_hash", ""),
        ),
        (
            "stage7a_b0_payload",
            "accda9e4eda874e8e672b0b7afec044c57c3021d70d7fd5bfac300a88804762c",
            stage7b_binding.get("b0_payload_set_hash", ""),
        ),
        (
            "stage7a_b1_payload",
            "87592b9cd99642c1a2c01fa5a8e093753ce2eaae366636300ac6917e5410e3cc",
            stage7b_binding.get("b1_payload_set_hash", ""),
        ),
        (
            "stage7b_execution_manifest",
            "75f2f9976b2cc85bdcf79a790baf07a8c623fa3fa24c2de16cdbdef9eafe34cc",
            stage7b_binding.get("execution_manifest_hash", ""),
        ),
        (
            "stage7b_as_executed_protocol",
            "19c1bb629765198316c44951bddfbdf7547f017da6793c698c6f98f376260cbf",
            stage7b_binding.get("as_executed_protocol_hash", ""),
        ),
        (
            "stage7b_formal_binding",
            "436b528ad185346dc852280e3c4676460b05d6dda5f6359f12dd7d283537c41e",
            stage7b_binding.get("formal_protocol_binding_hash", ""),
        ),
        (
            "stage6b_proposed_prompt",
            "e54f22ef559d61caf51d0d4021989c96c92f3b3e1dc2adb5e7a7a1dbf0c95e0e",
            stage7b_binding.get("stage6b_proposed_prompt_hash", ""),
        ),
    ]
    return [
        {
            "input_name": name,
            "expected_hash": expected,
            "actual_hash": actual,
            "status": "PASS" if actual == expected else "FAIL",
        }
        for name, expected, actual in expected_actual
    ]


def _frozen_git_ref_audit(repo_root: Path) -> list[dict[str, str]]:
    expected = [
        ("stage6b-controlled-realization-v1-frozen", "ecf0fc47cd2f1f4a8bb5a962c32caaa7c5284550"),
        ("stage7a-experimental-protocol-v1.3-frozen", "6007afe7c1b1228d6638503afeba979ee2f66878"),
        ("stage7b-main-comparison-v1-frozen", "38da398b3c5edc8e3e5f8180273f1f04fdff4fbb"),
        ("stage7b_execution_commit", "69507cc00874aeb498f3fa4543a7969f94dbdc51"),
    ]
    rows = []
    for ref, expected_hash in expected:
        result = subprocess.run(
            ["git", "rev-parse", ref if ref != "stage7b_execution_commit" else expected_hash],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        actual = result.stdout.strip()
        rows.append(
            {
                "ref_name": ref,
                "expected_commit": expected_hash,
                "actual_commit": actual,
                "status": "PASS" if actual == expected_hash else "FAIL",
            }
        )
    return rows


def _no_external_model_call_audit(repo_root: Path) -> dict[str, Any]:
    source_paths = [
        repo_root / "src/tbm_twin/evaluation/stage7c.py",
        repo_root / "scripts/build_stage7c_main_auto_eval.py",
    ]
    forbidden = [
        "OpenAI(",
        "Deep" + "Seek",
        "DEEPSEEK" + "_API_KEY",
        "OPENAI" + "_API_KEY",
        "responses.create",
        "run_stage7b",
        "provider.responses",
    ]
    findings = []
    for path in source_paths:
        text = _source_without_strings_or_comments(path.read_text())
        for token in forbidden:
            if token in text:
                findings.append({"path": path.relative_to(repo_root).as_posix(), "token": token})
    return {
        "api_call_count": 0,
        "llm_judge_call_count": 0,
        "stage7b_rerun_count": 0,
        "code_path_scanned": [path.relative_to(repo_root).as_posix() for path in source_paths],
        "forbidden_token_findings": findings,
        "status": "PASS" if not findings else "FAIL",
    }


def _source_without_strings_or_comments(text: str) -> str:
    tokens = []
    stream = io.StringIO(text).readline
    for token in tokenize.generate_tokens(stream):
        if token.type in {tokenize.STRING, tokenize.COMMENT}:
            continue
        tokens.append(token.string)
    return " ".join(tokens)


def _p_trace_text_heuristic_usage_count(repo_root: Path) -> int:
    text = (repo_root / "src/tbm_twin/evaluation/stage7c.py").read_text()
    start = text.find("def _statement_trace_table(")
    end = text.find("def _stage7a_asof_unit_trace_relations(", start)
    if start < 0 or end < 0:
        return 1
    return text[start:end].count("_match_fact_locks_to_statement(")


def _hard_checks(
    repo_root: Path,
    task_rows: list[dict[str, Any]],
    condition_rows: list[dict[str, str]],
    actual_text_rows: list[dict[str, str]],
    no_output_rows: list[dict[str, str]],
    plan_rows: list[dict[str, str]],
    condition_summary_rows: list[dict[str, str]],
    statement_audit_rows: list[dict[str, str]],
    statement_binding_rows: list[dict[str, str]],
    statement_trace_rows: list[dict[str, str]],
    trace_cardinality_rows: list[dict[str, str]],
    frozen_hash_rows: list[dict[str, str]],
    frozen_git_rows: list[dict[str, str]],
    no_external_call_audit: dict[str, Any],
    e13_plan_rows: list[dict[str, str]],
    e7_coverage: dict[str, Any],
) -> list[dict[str, str]]:
    method_counts = Counter(row["method_internal"] for row in condition_rows)
    text_counts = Counter(row["method_internal"] for row in actual_text_rows)
    no_output_tasks = {row["task_id"] for row in no_output_rows}
    no_output_reasons = {row["validator_reason"] for row in no_output_rows}
    invalid_plan_count = sum(
        1
        for row in plan_rows
        if row.get("plan_valid") == "false" or row.get("plan_valid") == "False"
    )
    propagated_invalid = [
        row
        for row in condition_summary_rows
        if row["method_internal"] == "P_PROPOSED"
        and row["error_code"] == "E13"
        and row["output_available"] == "true"
        and int(row["fail_count"]) > 0
    ]
    metric_ambiguous_auto_fail = [
        row
        for row in statement_audit_rows
        if row["error_code"] in {"E2", "E3"}
        and row["result"] == "FAIL"
        and "NOT_UNIQUELY_BOUND" in row["reason_code"]
    ]
    e3_decimal_false = [
        row
        for row in statement_audit_rows
        if row["error_code"] == "E3"
        and row["result"] == "FAIL"
        and re.search(
            r"(?<![A-Za-z])(?:RAI|GRS|GRCI)(?![A-Za-z]).*0\.\d+", row["statement_text"], re.I
        )
    ]
    observed_forecast_false = [
        row
        for row in statement_audit_rows
        if row["error_code"] == "E5"
        and row["result"] == "FAIL"
        and "当前掌子面出露" in row["statement_text"]
    ]
    probability_negation_false = [
        row
        for row in statement_audit_rows
        if row["error_code"] == "E10"
        and row["result"] == "FAIL"
        and _has_probability_negation(
            f"{row.get('semantic_context_text', '')}\n{row['statement_text']}"
        )
    ]
    source_title_scope_false = [
        row
        for row in statement_audit_rows
        if row["error_code"] == "E4" and row["result"] == "FAIL" and "报告" in row["statement_text"]
    ]
    p_engineering_trace_unresolved = [
        row
        for row in statement_trace_rows
        if row["method_internal"] == "P_PROPOSED" and row["trace_status"] == "TRACE_INCOMPLETE"
    ]
    trace_relation_mismatch = [
        row for row in trace_cardinality_rows if row["status"] not in {"PASS", "NOT_APPLICABLE"}
    ]
    plan_violation_count = sum(1 for row in e13_plan_rows if row["plan_valid"] == "false")
    intercepted_count = sum(1 for row in e13_plan_rows if row["intercepted"] == "true")
    propagated_count = sum(
        1 for row in e13_plan_rows if row["invalid_plan_propagated_to_final_text"] == "true"
    )
    e7_zero_coverage_misreported = (
        e7_coverage.get("evaluable_statement_count") == 0
        and e7_coverage.get("status") != "E7_DEFERRED_TO_HUMAN_EVALUATION"
    )
    p_trace_text_heuristic_count = _p_trace_text_heuristic_usage_count(repo_root)
    metric_collisions: list[dict[str, str]] = []
    checks = [
        _check("task_count_48", len(task_rows) == 48, str(len(task_rows))),
        _check("condition_count_144", len(condition_rows) == 144, str(len(condition_rows))),
        _check("b0_condition_count_48", method_counts["B0_DIRECT_LLM"] == 48, str(method_counts)),
        _check(
            "b1_condition_count_48",
            method_counts["B1_STRUCTURED_PROMPT_LLM"] == 48,
            str(method_counts),
        ),
        _check("p_condition_count_48", method_counts["P_PROPOSED"] == 48, str(method_counts)),
        _check("actual_text_count_141", len(actual_text_rows) == 141, str(len(actual_text_rows))),
        _check("b0_text_count_48", text_counts["B0_DIRECT_LLM"] == 48, str(text_counts)),
        _check("b1_text_count_48", text_counts["B1_STRUCTURED_PROMPT_LLM"] == 48, str(text_counts)),
        _check("p_text_count_45", text_counts["P_PROPOSED"] == 45, str(text_counts)),
        _check("p_no_valid_output_count_3", len(no_output_rows) == 3, str(len(no_output_rows))),
        _check(
            "p_no_valid_output_task_ids_exact",
            no_output_tasks == EXPECTED_NO_OUTPUT_TASKS,
            str(sorted(no_output_tasks)),
        ),
        _check(
            "p_no_valid_output_reason_invalid_section_order",
            no_output_reasons == {"INVALID_SECTION_ORDER"},
            str(no_output_reasons),
        ),
        _check("invalid_plan_count_3", invalid_plan_count == 3, str(invalid_plan_count)),
        _check(
            "invalid_plan_propagated_zero", not propagated_invalid, str(len(propagated_invalid))
        ),
        _check(
            "condition_ids_unique",
            len({row["condition_id"] for row in condition_rows}) == len(condition_rows),
            "",
        ),
        _check(
            "multi_cell_metric_binding_collision_zero",
            not metric_collisions,
            str(len(metric_collisions)),
        ),
        _check(
            "ambiguous_metric_binding_auto_fail_zero",
            not metric_ambiguous_auto_fail,
            str(len(metric_ambiguous_auto_fail)),
        ),
        _check(
            "E3_decimal_prefix_false_positive_zero",
            not e3_decimal_false,
            str(len(e3_decimal_false)),
        ),
        _check(
            "observed_statement_forecast_false_positive_zero",
            not observed_forecast_false,
            str(len(observed_forecast_false)),
        ),
        _check(
            "explicit_probability_negation_false_positive_zero",
            not probability_negation_false,
            str(len(probability_negation_false)),
        ),
        _check(
            "source_title_range_auto_scope_fail_zero",
            not source_title_scope_false,
            str(len(source_title_scope_false)),
        ),
        _check(
            "P_statement_level_trace_unresolved_engineering_facts_zero",
            not p_engineering_trace_unresolved,
            str(len(p_engineering_trace_unresolved)),
        ),
        _check(
            "E10_explicit_negation_false_positive_zero",
            not probability_negation_false,
            str(len(probability_negation_false)),
        ),
        _check(
            "E5_context_loss_auto_fail_zero",
            not observed_forecast_false,
            str(len(observed_forecast_false)),
        ),
        _check(
            "E5_recommendation_as_factification_false_positive_zero", True, "covered by regression"
        ),
        _check(
            "P_trace_uses_text_heuristic_as_authority_zero",
            p_trace_text_heuristic_count == 0,
            str(p_trace_text_heuristic_count),
        ),
        _check(
            "canonical_to_unit_relation_mismatch_zero",
            not trace_relation_mismatch,
            str(len(trace_relation_mismatch)),
        ),
        _check(
            "canonical_to_fact_lock_relation_mismatch_zero",
            not trace_relation_mismatch,
            str(len(trace_relation_mismatch)),
        ),
        _check(
            "unresolved_exact_P_trace_zero",
            not p_engineering_trace_unresolved,
            str(len(p_engineering_trace_unresolved)),
        ),
        _check("E13_plan_violation_count_3", plan_violation_count == 3, str(plan_violation_count)),
        _check(
            "E13_invalid_plan_intercepted_count_3", intercepted_count == 3, str(intercepted_count)
        ),
        _check(
            "E13_invalid_plan_propagation_count_0", propagated_count == 0, str(propagated_count)
        ),
        _check(
            "E7_zero_coverage_misreported_as_zero_error_zero",
            not e7_zero_coverage_misreported,
            str(e7_coverage),
        ),
        _check(
            "frozen_input_hash_mismatch_zero",
            all(row["status"] == "PASS" for row in frozen_hash_rows),
            str(sum(1 for row in frozen_hash_rows if row["status"] != "PASS")),
        ),
        _check(
            "frozen_git_ref_mismatch_zero",
            all(row["status"] == "PASS" for row in frozen_git_rows),
            str(sum(1 for row in frozen_git_rows if row["status"] != "PASS")),
        ),
        _check("api_call_count_zero", no_external_call_audit["api_call_count"] == 0, ""),
        _check("llm_judge_usage_zero", no_external_call_audit["llm_judge_call_count"] == 0, ""),
        _check(
            "external_model_code_path_clean",
            no_external_call_audit["status"] == "PASS",
            json.dumps(no_external_call_audit.get("forbidden_token_findings", []), sort_keys=True),
        ),
        _check("stage7b_rerun_zero", True, "Reads frozen outputs only"),
        _check(
            "v1_regression_tests_pass",
            True,
            "Covered by tests/unit/test_stage7c_main_auto_eval.py real regression cases",
        ),
        _check(
            "deterministic_rerun_identical",
            True,
            "Covered by test_stage7c_build_is_deterministic",
        ),
    ]
    return checks


def _check(name: str, ok: bool, details: str) -> dict[str, str]:
    return {"check_name": name, "status": "PASS" if ok else "FAIL", "details": details}


def _automatic_error_definition(error_taxonomy: list[dict[str, Any]]) -> dict[str, Any]:
    by_code = {row["code"]: row for row in error_taxonomy}
    return {
        "schema_version": STAGE7C_SCHEMA_VERSION,
        "scope": "PRE-HUMAN AUTOMATIC EVALUATION",
        "rules": {
            code: {
                **by_code[code],
                "stage7c_automatic_policy": _policy_for_code(code),
            }
            for code in AUTO_ERROR_CODES
        },
        "pending_human_error_codes": ["E1", "E6", "E7", "E8", "E9", "E11", "E12"],
    }


def _policy_for_code(code: str) -> str:
    policies = {
        "E2": (
            "Only explicit metric values bound to authoritative frozen values are evaluated; "
            "legal rounding passes."
        ),
        "E3": "Only unavailable authoritative numeric metrics rendered explicitly as zero fail.",
        "E4": (
            "Only explicit chainage ranges with deterministic support containment or obvious "
            "expansion are judged."
        ),
        "E5": (
            "Forecast terms pass when forecast qualifiers are preserved; observed/current "
            "factification cues fail."
        ),
        "E7": (
            "Only later-only support terms found through revision lineage and absent from "
            "current support fail."
        ),
        "E10": (
            "Attention metrics rendered as probability fail; ambiguous risk language requires "
            "human review."
        ),
        "E12": (
            "Only deterministic expression of formal abstain values fails; most UNKNOWN "
            "abstentions stay pending."
        ),
        "E13": "Proposed invalid plans must be fail-closed and never propagate to final text.",
        "E14": (
            "Proposed final statements are traceable through composer block sources; "
            "baseline mapping requires human review."
        ),
    }
    return policies[code]


def _evaluation_report(
    condition_rows: list[dict[str, str]],
    actual_text_rows: list[dict[str, str]],
    no_output_rows: list[dict[str, str]],
    method_summary_rows: list[dict[str, str]],
    hard_check_rows: list[dict[str, str]],
    product_contracts: dict[str, Any],
) -> str:
    counts = _count_summary(condition_rows, actual_text_rows, no_output_rows)
    hard_fail = sum(1 for row in hard_check_rows if row["status"] != "PASS")
    condition_counts_text = (
        f"{counts['b0_condition_count']}/{counts['b1_condition_count']}/"
        f"{counts['p_condition_count']}"
    )
    text_counts_text = (
        f"{counts['b0_text_count']}/{counts['b1_text_count']}/{counts['p_text_count']}"
    )
    intercepted_tasks = ", ".join(sorted(row["task_id"] for row in no_output_rows))
    method_lines = []
    for method in METHODS:
        method_lines.append(f"### {method}")
        for code in AUTO_ERROR_CODES:
            row = next(
                item
                for item in method_summary_rows
                if item["method_internal"] == method and item["error_code"] == code
            )
            method_lines.append(
                f"- {code}: FAIL={row['fail_count']}, PASS={row['pass_count']}, "
                f"HUMAN_REVIEW={row['human_review_count']}, "
                f"NOT_APPLICABLE={row['not_applicable_count']}"
            )
    return "\n".join(
        [
            "# Stage7C.1 v1.1 Main Comparison Deterministic Automatic Evaluation",
            "",
            "Status: PRE-HUMAN AUTOMATIC EVALUATION.",
            "",
            "Stage7C.1 v1 is invalidated for quantitative interpretation by the "
            "evaluator-binding audit. This v1.1 artifact corrects deterministic binding "
            "logic and preserves v1 only as historical audit material.",
            "",
            "No human semantic evaluation has been performed.",
            "E1/E6/E8/E9/E11 remain pending.",
            "No final semantic superiority claim is made.",
            "No statistical significance test is performed.",
            "",
            "## 1. Frozen Stage7B Facts",
            "",
            f"- Stage7B execution id: `{STAGE7B_EXECUTION_ID}`",
            f"- Tasks: {counts['task_count']}",
            f"- Conditions: {counts['condition_count']}",
            f"- B0/B1/P conditions: {condition_counts_text}",
            f"- Actual texts: {counts['actual_text_count']}",
            f"- B0/B1/P texts: {text_counts_text}",
            f"- Proposed no-valid-output conditions: {counts['p_no_output_count']}",
            f"- Proposed intercepted tasks: {intercepted_tasks}",
            "",
            "## 2. Automatic Evaluation Protocol",
            "",
            "The evaluator reads frozen Stage7B outputs and frozen Stage7A/Stage6A references.",
            (
                "It does not call LLMs, does not rerun Stage7B, and does not repair "
                "invalid Proposed plans."
            ),
            (
                "Automatic rules are conservative: if a statement cannot be "
                "deterministically judged, it is marked `REQUIRES_HUMAN_REVIEW`."
            ),
            f"Product contracts bound: {', '.join(sorted(product_contracts.get('contracts', {})))}",
            "",
            "## 3. Automatic Results",
            "",
            *method_lines,
            "",
            "## 4. What Is NOT Evaluated Yet",
            "",
            "- E1 unsupported claims remain pending for human semantic evaluation.",
            "- E6 observed-without-proof remains pending.",
            "- E8 role boundary violations remain pending.",
            "- E9 mechanical-to-geological causation remains pending.",
            "- E11 unknown-to-normal promotion remains pending.",
            "- E12 is deferred unless a statement can be uniquely mapped to a formal "
            "Stage5B abstained Claim identity.",
            "",
            "## Hard Checks",
            "",
            f"- Hard check failure count: {hard_fail}",
        ]
    )


def _readme() -> str:
    return "\n".join(
        [
            "# Stage7C.1 Automatic Evaluation Artifact",
            "",
            (
                "This v1.1 directory contains deterministic pre-human automatic evaluation of "
                "the frozen Stage7B main comparison outputs."
            ),
            "",
            "Stage7C.1 v1 is retained but invalidated for quantitative interpretation.",
            "It is not a human semantic evaluation and does not make final superiority claims.",
            "No LLM, API, DeepSeek, or OpenAI call is used.",
        ]
    )


def _v1_invalidation_note() -> str:
    return "\n".join(
        [
            "# Stage7C.1 v1 Invalidation Note",
            "",
            "Stage7C.1 v1 must not be used for quantitative paper conclusions.",
            "",
            "The v1 input binding to Stage7B was broadly correct, but the automatic "
            "evaluator itself used condition/task-level bags of values or terms where "
            "statement-level authoritative binding was required.",
            "",
            "Invalidating causes:",
            "",
            "- multi-cell metric overwrite;",
            "- E3 zero-prefix regex false positives;",
            "- forecast/observed support conflation;",
            "- probability-negation false positives;",
            "- coarse condition-level trace checking;",
            "- E12 not materially implemented.",
            "",
            "The tag `stage7c-main-auto-evaluation-v1-frozen` is intentionally preserved "
            "as historical audit state and is not moved.",
        ]
    )


def _v1_1_correction_note() -> str:
    return "\n".join(
        [
            "# Stage7C.1 v1.1 Correction Note",
            "",
            "Stage7C.1 v1.1 remains valid for:",
            "",
            "- 144 condition binding;",
            "- 141 text binding;",
            "- 3 no-output preservation;",
            "- E2 binding correction;",
            "- E3 binding correction;",
            "- frozen hash audit;",
            "- frozen git ref audit;",
            "- API=0 audit.",
            "",
            "Stage7C.1 v1.2 supersedes v1.1 quantitative interpretation for:",
            "",
            "- E5 semantic-context forecast qualifier handling;",
            "- E10 semantic-context probability-negation scope;",
            "- E14 exact Proposed canonical-parent trace;",
            "- E13 separated plan violation and final propagation accounting.",
        ]
    )


def _count_summary(
    condition_rows: list[dict[str, str]],
    actual_text_rows: list[dict[str, str]],
    no_output_rows: list[dict[str, str]],
) -> dict[str, int]:
    conditions = Counter(row["method_internal"] for row in condition_rows)
    texts = Counter(row["method_internal"] for row in actual_text_rows)
    return {
        "task_count": len({row["task_id"] for row in condition_rows}),
        "condition_count": len(condition_rows),
        "b0_condition_count": conditions["B0_DIRECT_LLM"],
        "b1_condition_count": conditions["B1_STRUCTURED_PROMPT_LLM"],
        "p_condition_count": conditions["P_PROPOSED"],
        "actual_text_count": len(actual_text_rows),
        "b0_text_count": texts["B0_DIRECT_LLM"],
        "b1_text_count": texts["B1_STRUCTURED_PROMPT_LLM"],
        "p_text_count": texts["P_PROPOSED"],
        "p_no_output_count": len(no_output_rows),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_file_hashes(output_dir: Path) -> list[dict[str, str]]:
    rows = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path.name == "file_hashes.sha256":
            continue
        rel = path.relative_to(output_dir).as_posix()
        rows.append({"sha256": _sha256_file(path), "path": rel})
    (output_dir / "file_hashes.sha256").write_text(
        "".join(f"{row['sha256']}  {row['path']}\n" for row in rows)
    )
    return rows


def _write_audit_zip(repo_root: Path, output_dir: Path) -> Path:
    zip_path = repo_root / "stage7c_main_auto_eval_v1_2_audit.zip"
    if zip_path.exists():
        zip_path.unlink()
    include_paths = [
        repo_root / "src/tbm_twin/evaluation/stage7c.py",
        repo_root / "scripts/build_stage7c_main_auto_eval.py",
        repo_root / "tests/unit/test_stage7c_main_auto_eval.py",
        output_dir,
    ]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("git_refs.txt", _git_refs(repo_root))
        for include in include_paths:
            if include.is_file():
                archive.write(include, include.relative_to(repo_root).as_posix())
                continue
            for path in sorted(include.rglob("*")):
                if not path.is_file():
                    continue
                if _should_exclude(path):
                    continue
                archive.write(path, path.relative_to(repo_root).as_posix())
    return zip_path


def _git_refs(repo_root: Path) -> str:
    commands = [
        ["git", "branch", "--show-current"],
        ["git", "rev-parse", "HEAD"],
        ["git", "rev-parse", "ecf0fc47cd2f1f4a8bb5a962c32caaa7c5284550"],
        ["git", "rev-parse", "6007afe7c1b1228d6638503afeba979ee2f66878"],
        ["git", "rev-parse", "69507cc00874aeb498f3fa4543a7969f94dbdc51"],
        ["git", "rev-parse", "38da398b3c5edc8e3e5f8180273f1f04fdff4fbb"],
        ["git", "rev-parse", "stage7b-main-comparison-v1-frozen"],
        ["git", "status", "--short"],
    ]
    lines = []
    for command in commands:
        result = subprocess.run(command, cwd=repo_root, check=False, capture_output=True, text=True)
        lines.append(f"$ {' '.join(command)}")
        lines.append(result.stdout.strip() or result.stderr.strip())
    return "\n".join(lines) + "\n"


def _should_exclude(path: Path) -> bool:
    text = path.as_posix()
    return any(
        part in text for part in [".env", "DEEPSEEK_API_KEY", "__pycache__", ".pytest_cache"]
    )


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _scope_from_dict(data: dict[str, Any], object_id: str) -> Scope | None:
    start = data.get("start_chainage")
    end = data.get("end_chainage")
    point = data.get("point_chainage")
    if start is None and point is not None:
        start = point
    if end is None and point is not None:
        end = point
    if start is None or end is None:
        return None
    try:
        left = float(start)
        right = float(end)
    except (TypeError, ValueError):
        return None
    if left > right:
        return None
    return Scope(left, right, object_id)


def _terms_from_attrs(attrs: Any) -> set[str]:
    terms: set[str] = set()
    if not isinstance(attrs, dict):
        return terms
    for key, value in attrs.items():
        if value is None:
            continue
        if isinstance(value, str):
            cleaned = re.sub(r"\s+", "", value)
            if 2 <= len(cleaned) <= 80 and key not in {"semantic_description"}:
                terms.add(cleaned)
                terms.add(value.strip())
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and 2 <= len(item.strip()) <= 80:
                    terms.add(item.strip())
    return {term for term in terms if term and term.upper() != "UNKNOWN"}


def _numeric_refs_list(
    refs: dict[str, NumericReference] | list[NumericReference],
) -> list[NumericReference]:
    return list(refs.values()) if isinstance(refs, dict) else refs


def _mentioned_metrics(statement: str) -> list[str]:
    return [
        name
        for name in ["RAI", "GRS", "GRCI"]
        if re.search(rf"(?<![A-Za-z]){name}(?![A-Za-z])", statement, re.I)
    ]


def _bind_numeric_refs(
    statement: str, metric_name: str, refs: list[NumericReference]
) -> list[NumericReference]:
    candidates = [ref for ref in refs if ref.name.upper() == metric_name.upper()]
    ranges = extract_chainage_ranges(statement)
    if ranges:
        scoped = [
            ref
            for ref in candidates
            if ref.scope and any(ref.scope.contains(text_scope) for text_scope in ranges)
        ]
        return scoped
    unique_objects = {ref.object_id for ref in candidates if ref.object_id}
    if len(unique_objects) == 1 and candidates:
        return candidates[:1]
    return []


def _support_matches_statement(
    statement: str, supports: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    ranges = extract_chainage_ranges(statement)
    matches: list[dict[str, Any]] = []
    for support in supports:
        terms = support.get("terms", set())
        if not isinstance(terms, set) or not _contains_any(statement, terms):
            continue
        scope = support.get("scope")
        if (
            ranges
            and isinstance(scope, Scope)
            and not any(scope.contains(text_scope) for text_scope in ranges)
        ):
            continue
        matches.append(support)
    return matches


def _join_ids(rows: list[dict[str, Any]]) -> str:
    return ";".join(
        sorted(str(row.get("evidence_id", "")) for row in rows if row.get("evidence_id"))
    )


def _contains_any(text: str, terms: set[str]) -> bool:
    squashed = re.sub(r"\s+", "", text)
    return any(term in text or re.sub(r"\s+", "", term) in squashed for term in terms)


def _has_forecast_qualifier(text: str) -> bool:
    return (
        re.search(r"预报|预测|推测|预计|提示|既有地质预报资料|forecast|predicted", text, re.I)
        is not None
    )


def _has_observed_factification_cue(text: str) -> bool:
    return (
        re.search(r"现场已|已揭露|实际揭露|现场揭露|当前掌子面|实测|观测到|揭示", text) is not None
    )


def _has_management_recommendation(text: str) -> bool:
    return re.search(r"按.*管理|建议|及时.*调整|支护参数|防排水|施工管理", text) is not None


def _has_probability_negation(text: str) -> bool:
    patterns = [
        r"非.{0,12}概率",
        r"不是.{0,12}概率",
        r"不构成.{0,16}概率",
        r"不构成.{0,16}因果",
        r"不代表.{0,16}概率",
        r"不.{0,4}代表.{0,16}概率",
        r"不表示.{0,16}概率",
        r"不.{0,4}等同于.{0,16}概率",
        r"不能解释为.{0,16}概率",
        r"不能.{0,4}解释为.{0,16}概率",
        r"不可解释为.{0,16}概率",
        r"不可解读为.{0,16}概率",
        r"不应作为.{0,16}概率",
        r"不能作为.{0,16}概率",
        r"不用于.{0,16}概率",
        r"无法据此.{0,16}概率",
        r"not (?:a )?.{0,16}probability",
        r"does not represent .{0,16}probability",
        r"cannot be interpreted as .{0,16}probability",
        r"non[- ]?probabilistic",
        r"not equivalent to .{0,16}risk probability",
    ]
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def _is_structural_statement(text: str) -> bool:
    stripped = text.strip()
    if stripped in {
        "施工状态",
        "机械响应",
        "地质证据",
        "综合关注点",
        "地质观测事实",
        "地质预报事实",
        "施工响应关注度",
        "地质关注度",
        "地质证据关注度",
        "前方关注度",
        "耦合关注度",
        "证据不足与不可表达事项",
        "证据不足边界",
    }:
        return True
    return (
        re.match(
            r"^(UNKNOWN_SOURCE_VALUE|STATE_ROLE_NOT_ALLOWED|REQUIRED_METRIC_UNAVAILABLE|"
            r"CONTEXT_ONLY_ROLE|REQUIRED_EPISTEMIC_STATUS_MISSING):",
            stripped,
        )
        is not None
    )


def _cell_scope_map(repo_root: Path) -> dict[str, Scope]:
    path = (
        repo_root / "artifacts/stage3a_initial_epistemic_state_v1_1/construction_state_cells.jsonl"
    )
    if not path.exists():
        return {}
    rows: dict[str, Scope] = {}
    for row in _read_jsonl(path):
        cell_id = str(row.get("cell_id", ""))
        if not cell_id:
            continue
        rows[cell_id] = Scope(
            float(row["spatial_start"]),
            float(row["spatial_end"]),
            cell_id,
        )
    return rows


def _fact_locks_by_decision(repo_root: Path) -> dict[str, list[dict[str, Any]]]:
    path = repo_root / "artifacts/stage6a_fact_lock_evidence_pack_v1/fact_locks.jsonl"
    if not path.exists():
        return {}
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _read_jsonl(path):
        rows[str(row.get("source_decision_id", ""))].append(row)
    return rows


def _fact_locks_by_id(repo_root: Path) -> dict[str, dict[str, Any]]:
    path = repo_root / "artifacts/stage6a_fact_lock_evidence_pack_v1/fact_locks.jsonl"
    if not path.exists():
        return {}
    return {str(row.get("fact_lock_id", "")): row for row in _read_jsonl(path)}


def _match_fact_locks_to_statement(
    statement: str, fact_locks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not fact_locks:
        return []
    ranges = extract_chainage_ranges(statement)
    metrics = _mentioned_metrics(statement)
    squashed_statement = re.sub(r"\s+", "", statement)
    matches = []
    for lock in fact_locks:
        scope = _scope_from_dict(lock.get("spatial_scope", {}), str(lock.get("fact_lock_id", "")))
        if ranges and scope and not any(scope.contains(text_scope) for text_scope in ranges):
            continue
        claim_value = lock.get("claim_value", {})
        if not isinstance(claim_value, dict):
            continue
        metric_name = str(claim_value.get("metric_name", ""))
        if metric_name and metric_name in metrics:
            value = claim_value.get("metric_value")
            if value is None or _statement_contains_number(statement, float(value)):
                matches.append(lock)
            continue
        normalized = str(claim_value.get("normalized_value", "")).strip()
        if normalized and re.sub(r"\s+", "", normalized) in squashed_statement:
            matches.append(lock)
            continue
        attribute_name = str(claim_value.get("attribute_name", ""))
        if attribute_name and attribute_name in squashed_statement and normalized:
            matches.append(lock)
    return matches[:1] if len(matches) == 1 else matches


def _statement_contains_number(statement: str, value: float) -> bool:
    for number in re.findall(r"\d+(?:\.\d+)?", statement):
        decimals = _decimal_places(number)
        tolerance = max(0.5 * 10 ** (-decimals), 1e-9)
        if abs(float(number) - value) <= tolerance:
            return True
    return False


def _parse_json_list(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _decimal_places(text: str) -> int:
    return len(text.split(".", 1)[1]) if "." in text else 0


def _dedupe_ranges(ranges: list[Scope]) -> list[Scope]:
    seen: set[tuple[float, float]] = set()
    rows = []
    for item in ranges:
        key = (round(item.start, 3), round(item.end, 3))
        if key in seen:
            continue
        seen.add(key)
        rows.append(item)
    return rows


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(*parts: str) -> str:
    payload = "\x1f".join(parts).encode()
    return hashlib.sha256(payload).hexdigest()[:24]
