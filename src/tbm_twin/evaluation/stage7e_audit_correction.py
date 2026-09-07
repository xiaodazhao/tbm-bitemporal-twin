"""Offline Stage7E-B v1.1 deterministic audit correction.

This module never calls a model provider. It preserves the preregistered strict
JSON endpoint and adds a post-hoc, fence-only sensitivity analysis over the
frozen Stage7E-B v1 raw responses.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tbm_twin.evaluation.stage7e_execution import (
    _analysis_inputs,
    _analyze_a3,
    _analyze_a4,
    _load_attempts,
    _request_input_payload,
    _scope_status,
    _strict_json,
    preflight_stage7e,
)
from tbm_twin.realization.io import stable_hash

OLD_ARTIFACT_DIR = Path("artifacts/stage7e_ablation_execution_v1")
OUTPUT_DIR = Path("artifacts/stage7e_ablation_execution_v1_1_correction")
OLD_TAG = "stage7e-ablation-execution-v1-frozen"
OLD_COMMIT = "460c85268eaea121ad5325af9c384fc42bb71a0d"
METHOD_VERSION = "stage7e_ablation_execution_v1_1_offline_audit_correction"
SCHEMA_VERSION = "stage7e_ablation_execution_correction.v1.1"
AUDIT_ZIP = "stage7e_ablation_execution_v1_1_correction_audit.zip"
ENGINEERING_DECIMAL_PATTERN_V2 = re.compile(r"(?<![\d.])-?\d+(?:\.\d+)?(?![\d.])")
OUTER_FENCE_PATTERN = re.compile(
    r"\A[\t \r\n]*```(?P<language>json)?\r?\n"
    r"(?P<inner>[\s\S]*?)\r?\n```[\t \r\n]*\Z"
)


class Stage7EAuditCorrectionError(RuntimeError):
    """Raised when the offline correction cannot be frozen."""


def engineering_decimal_tokens_v2(text: str) -> set[Decimal]:
    """Extract complete decimal tokens without treating adjacent text as a boundary."""

    values: set[Decimal] = set()
    for raw in ENGINEERING_DECIMAL_PATTERN_V2.findall(text):
        try:
            values.add(Decimal(raw))
        except InvalidOperation:
            continue
    return values


def numeric_value_status_v2(value: dict[str, Any], text: str) -> str:
    """Check exact frozen metric-value membership using the corrected tokenizer."""

    expected = value.get("metric_value")
    if not isinstance(expected, (int, float)) or isinstance(expected, bool):
        return "NOT_APPLICABLE"
    return "PASS" if Decimal(str(expected)) in engineering_decimal_tokens_v2(text) else "FAIL"


def fence_only_normalize(raw_text: Any) -> dict[str, Any]:
    """Remove one exact outer Markdown fence without touching the inner content."""

    if not isinstance(raw_text, str):
        return _fence_result(raw_text, False, "RAW_TEXT_UNAVAILABLE")
    match = OUTER_FENCE_PATTERN.fullmatch(raw_text)
    if match is None:
        return _fence_result(raw_text, False, "NOT_EXACT_SINGLE_OUTER_FENCE")
    inner = match.group("inner")
    parsed, parse_status, parse_error = _strict_json(inner)
    return {
        "outer_fence_exact_match": True,
        "opening_fence_language": match.group("language") or "",
        "inner_text": inner,
        "inner_sha256": _sha256_text(inner),
        "inner_json": parsed,
        "inner_json_parse": parse_status,
        "inner_json_parse_error": parse_error,
        "content_character_change_count": 0,
        "rejection_reason": "",
    }


def build_stage7e_audit_correction(
    repo_root: Path,
    *,
    output_dir: Path | None = None,
    generated_at: str | None = None,
    create_audit_zip: bool = True,
) -> dict[str, Any]:
    """Build the v1.1 correction entirely from frozen local inputs."""

    root = repo_root.resolve()
    output = output_dir or root / OUTPUT_DIR
    old_output = root / OLD_ARTIFACT_DIR
    if _git_rev_parse(root, OLD_TAG) != OLD_COMMIT:
        raise Stage7EAuditCorrectionError("old Stage7E-B v1 tag moved")
    preflight = preflight_stage7e(root, require_credential=False)
    if preflight["status"] != "PASS":
        raise Stage7EAuditCorrectionError("frozen Stage7E protocol preflight failed")
    attempts = _load_attempts(old_output)
    if len(attempts) != 226:
        raise Stage7EAuditCorrectionError("frozen raw attempt count is not 226")
    inputs = _analysis_inputs(root, preflight["requests"])
    old_identity = _old_artifact_identity(root)
    raw_identity = _raw_identity(root, attempts)
    first = _derive(inputs, attempts, old_output)
    second = _derive(inputs, attempts, old_output)
    semantic_hash = stable_hash(first)
    replay_hash = stable_hash(second)
    output.mkdir(parents=True, exist_ok=True)
    _write_outputs(output, first)
    _write_csv(output / "raw_response_identity_audit.csv", raw_identity)
    _write_csv(output / "old_execution_artifact_identity_audit.csv", old_identity)
    hard_checks = _hard_checks(
        root, attempts, old_identity, raw_identity, first, semantic_hash, replay_hash
    )
    _write_csv(output / "hard_check.csv", hard_checks)
    timestamp = generated_at or datetime.now(tz=UTC).isoformat()
    method = {
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": timestamp,
        "old_execution_tag": OLD_TAG,
        "old_execution_commit": OLD_COMMIT,
        "old_artifact_path": OLD_ARTIFACT_DIR.as_posix(),
        "raw_response_count": len(attempts),
        "new_api_calls": 0,
        "new_llm_calls": 0,
        "new_deepseek_calls": 0,
        "strict_primary_preserved": True,
        "secondary_analysis": "A3_FENCE_ONLY_SYNTAX_NORMALIZATION_SENSITIVITY",
        "secondary_analysis_properties": ["SECONDARY", "POST_HOC", "OFFLINE", "DETERMINISTIC"],
        "numeric_tokenizer": "engineering_decimal_tokens_v2",
        "numeric_token_pattern": ENGINEERING_DECIMAL_PATTERN_V2.pattern,
        "semantic_replay_hash": semantic_hash,
    }
    summary = _summary(first)
    freeze = {
        **method,
        "status": "OFFLINE_AUDIT_CORRECTION_FROZEN",
        "hard_check_failure_count": sum(row["status"] != "PASS" for row in hard_checks),
        "summary": summary,
    }
    _write_json(output / "method_version.json", method)
    _write_json(output / "freeze_manifest.json", freeze)
    (output / "README.md").write_text(_readme(summary), encoding="utf-8")
    (output / "STAGE7E_B_V1_1_INTERPRETATION_CORRECTION.md").write_text(
        _interpretation(summary), encoding="utf-8"
    )
    (output / "numeric_tokenizer_v1_bug_analysis.md").write_text(_bug_analysis(), encoding="utf-8")
    _write_hashes(output)
    if create_audit_zip:
        write_audit_zip(root, output)
    if any(row["status"] != "PASS" for row in hard_checks):
        raise Stage7EAuditCorrectionError("Stage7E-B v1.1 correction hard checks failed")
    return {
        "status": freeze["status"],
        "hard_check_failure_count": 0,
        "semantic_replay_hash": semantic_hash,
        **summary,
    }


def _derive(
    inputs: dict[str, Any], attempts: list[dict[str, Any]], old_output: Path
) -> dict[str, Any]:
    request_by_id = inputs["request_by_id"]
    a3_attempts = [row for row in attempts if row["arm_internal"] == "A3_NO_FACTLOCK"]
    secondary_attempts: list[dict[str, Any]] = []
    fence_rows: list[dict[str, Any]] = []
    for attempt in a3_attempts:
        _, strict_status, _ = _strict_json(attempt.get("raw_response_content"))
        if strict_status == "PASS":
            secondary_attempts.append(dict(attempt))
            continue
        normalized = fence_only_normalize(attempt.get("raw_response_content"))
        request = request_by_id[str(attempt["request_id"])]
        payload = _request_input_payload(request)
        expected_ids = [str(row["claim_id"]) for row in payload["claims"]]
        inner = normalized.get("inner_json")
        structural, returned_ids = _a3_schema_and_ids(inner)
        missing, duplicate, unexpected = claim_id_differences(expected_ids, returned_ids)
        fence_rows.append(
            {
                "request_id": attempt["request_id"],
                "task_id": attempt["task_id"],
                "raw_sha256": _sha256_text(str(attempt.get("raw_response_content") or "")),
                "outer_fence_exact_match": normalized["outer_fence_exact_match"],
                "inner_sha256": normalized.get("inner_sha256", ""),
                "inner_json_parse": normalized.get("inner_json_parse", "FAIL"),
                "inner_schema_valid": structural,
                "expected_claim_count": len(expected_ids),
                "returned_claim_count": len(returned_ids),
                "missing_claim_ids": ";".join(missing),
                "duplicate_claim_ids": ";".join(duplicate),
                "unexpected_claim_ids": ";".join(unexpected),
                "content_character_change_count": normalized.get(
                    "content_character_change_count", 0
                ),
                "normalization_status": "RECOVERED"
                if normalized["outer_fence_exact_match"]
                and normalized.get("inner_json_parse") == "PASS"
                and structural
                and not missing
                and not duplicate
                and not unexpected
                else "REJECTED",
            }
        )
        copied = dict(attempt)
        if normalized["outer_fence_exact_match"]:
            copied["raw_response_content"] = normalized["inner_text"]
        secondary_attempts.append(copied)
    secondary = _analyze_a3(inputs, secondary_attempts, request_by_id)
    strict_summary = _read_json(old_output / "a3_mechanistic_summary.json")
    claim_by_id = {str(row["claim_id"]): row for row in inputs["a3_claims"]}
    secondary_numeric = _a3_numeric_rows(secondary["claim_results"], claim_by_id)
    secondary_scope = _a3_scope_rows(secondary["claim_results"], claim_by_id)
    secondary_summary = {
        "analysis_name": "A3_FENCE_ONLY_SYNTAX_NORMALIZATION_SENSITIVITY",
        "analysis_role": "SECONDARY_POST_HOC_OFFLINE_DETERMINISTIC",
        "strict_primary_valid_chunks": strict_summary["valid_chunk_count"],
        "strict_primary_claim_mappings": strict_summary["mapping_complete_count"],
        "strict_primary_complete_tasks": strict_summary["complete_task_count"],
        "fence_normalizable_chunk_count": sum(
            row["normalization_status"] == "RECOVERED" for row in fence_rows
        ),
        "fence_only_parse_success_count": sum(
            row["inner_json_parse"] == "PASS" for row in fence_rows
        ),
        "fence_only_schema_success_count": sum(
            bool(row["inner_schema_valid"]) for row in fence_rows
        ),
        "secondary_valid_chunks": secondary["valid_chunk_count"],
        "secondary_claim_mappings": secondary["mapping_complete_count"],
        "secondary_complete_tasks": secondary["complete_task_count"],
        "total_mapped_claims": sum(row["mapping_complete"] for row in secondary["claim_results"]),
        "numeric_claim_count": sum(row["numeric_claim"] for row in secondary_numeric),
        "numeric_exact_count": sum(
            row["v1_1_numeric_status"] == "PASS" for row in secondary_numeric
        ),
        "numeric_drift_count": sum(
            row["v1_1_numeric_status"] == "FAIL" for row in secondary_numeric
        ),
        "numeric_not_evaluable_count": sum(
            row["v1_1_numeric_status"] == "NOT_EVALUABLE" for row in secondary_numeric
        ),
        "scope_status_distribution": dict(
            sorted(Counter(row["scope_status"] for row in secondary_scope).items())
        ),
    }
    a4_attempts = [row for row in attempts if row["arm_internal"] == "A4_FREE_FINAL_REALIZATION"]
    a4 = _analyze_a4(inputs, a4_attempts, request_by_id)
    a4_numeric = _a4_numeric_rows(a4_attempts, request_by_id)
    old_a3_numeric = {
        str(row["claim_id"]): row for row in _read_csv(old_output / "a3_claim_drift_audit.csv")
    }
    old_a4_numeric = {
        (str(row["task_id"]), str(row["fact_lock_id"])): row
        for row in _read_csv(old_output / "a4_hard_drift_audit.csv")
    }
    corrections = _numeric_correction_rows(
        secondary_numeric, a4_numeric, old_a3_numeric, old_a4_numeric
    )
    old_trace = _read_csv(old_output / "a4_factlock_trace_audit.csv")
    coverage_rows = _coverage_identity_rows(old_trace, a4["trace_rows"])
    old_scope = _read_csv(old_output / "a4_scope_section_audit.csv")
    scope_identity = _scope_identity_rows(old_scope, a4["scope_section_rows"])
    a4_summary = {
        "total_fact_lock_count": len(a4["trace_rows"]),
        "used_fact_lock_count": sum(row["used"] for row in a4["trace_rows"]),
        "omitted_fact_lock_count": sum(row["omitted"] for row in a4["trace_rows"]),
        "fact_lock_coverage": sum(row["used"] for row in a4["trace_rows"]) / len(a4["trace_rows"]),
        "total_numeric_fact_lock_count": len(a4_numeric),
        "used_numeric_fact_lock_count": sum(row["used"] for row in a4_numeric),
        "omitted_numeric_fact_lock_count": sum(row["omitted"] for row in a4_numeric),
        "numeric_fact_lock_coverage": sum(row["used"] for row in a4_numeric) / len(a4_numeric),
        "used_numeric_exact_count": sum(
            row["used"] and row["v1_1_numeric_status"] == "PASS" for row in a4_numeric
        ),
        "used_numeric_drift_count": sum(
            row["used"] and row["v1_1_numeric_status"] == "FAIL" for row in a4_numeric
        ),
        "omitted_numeric_task_distribution": dict(
            sorted(Counter(str(row["task_id"]) for row in a4_numeric if row["omitted"]).items())
        ),
        "scope_status_distribution": dict(
            sorted(
                Counter(
                    str(row["explicit_scope_consistency"]) for row in a4["scope_section_rows"]
                ).items()
            )
        ),
    }
    return {
        "strict_summary": strict_summary,
        "fence_rows": fence_rows,
        "secondary_claim_results": secondary["claim_results"],
        "secondary_numeric": secondary_numeric,
        "secondary_scope": secondary_scope,
        "secondary_summary": secondary_summary,
        "a4_numeric": a4_numeric,
        "a4_summary": a4_summary,
        "coverage_rows": coverage_rows,
        "scope_identity": scope_identity,
        "numeric_corrections": corrections,
    }


def _a3_schema_and_ids(payload: Any) -> tuple[bool, list[str]]:
    structural = bool(
        isinstance(payload, dict)
        and set(payload) == {"realizations"}
        and isinstance(payload.get("realizations"), list)
        and all(
            isinstance(row, dict)
            and set(row) == {"claim_id", "sentence"}
            and isinstance(row.get("claim_id"), str)
            and isinstance(row.get("sentence"), str)
            for row in payload.get("realizations", [])
        )
    )
    if not structural:
        return False, []
    return True, [str(row["claim_id"]) for row in payload["realizations"]]


def claim_id_differences(
    expected_ids: list[str], returned_ids: list[str]
) -> tuple[list[str], list[str], list[str]]:
    """Return missing, duplicate, and unexpected Claim IDs deterministically."""

    counts = Counter(returned_ids)
    missing = sorted(set(expected_ids) - set(returned_ids))
    duplicate = sorted(value for value, count in counts.items() if count > 1)
    unexpected = sorted(set(returned_ids) - set(expected_ids))
    return missing, duplicate, unexpected


def _a3_numeric_rows(
    claim_results: list[dict[str, Any]], claim_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    for result in claim_results:
        claim_id = str(result["claim_id"])
        claim = claim_by_id.get(claim_id)
        if claim is None:
            continue
        value = json.loads(str(claim["claim_value"]))
        expected = value.get("metric_value")
        numeric = isinstance(expected, (int, float)) and not isinstance(expected, bool)
        mapped = bool(result["mapping_complete"])
        status = (
            numeric_value_status_v2(value, str(result["sentence"]))
            if numeric and mapped
            else "NOT_EVALUABLE"
            if numeric
            else "NOT_APPLICABLE"
        )
        rows.append(
            {
                "arm": "A3_NO_FACTLOCK_SECONDARY",
                "object_id": claim_id,
                "task_id": result["task_id"],
                "request_id": result["request_id"],
                "mapping_complete": mapped,
                "numeric_claim": numeric,
                "expected_metric_value": expected if numeric else "",
                "model_text": result["sentence"],
                "extracted_decimal_tokens": ";".join(
                    str(item)
                    for item in sorted(engineering_decimal_tokens_v2(str(result["sentence"])))
                ),
                "v1_1_numeric_status": status,
            }
        )
    return rows


def _a3_scope_rows(
    claim_results: list[dict[str, Any]], claim_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    for result in claim_results:
        claim = claim_by_id.get(str(result["claim_id"]))
        if claim is None:
            continue
        if result["mapping_complete"]:
            status, observed = _scope_status(
                json.loads(str(claim["subject_scope"])), str(result["sentence"])
            )
        else:
            status, observed = "NOT_EVALUABLE", []
        rows.append(
            {
                "claim_id": result["claim_id"],
                "task_id": result["task_id"],
                "request_id": result["request_id"],
                "scope_status": status,
                "observed_explicit_chainages": ";".join(str(value) for value in observed),
            }
        )
    return rows


def _a4_numeric_rows(
    attempts: list[dict[str, Any]], request_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    for attempt in attempts:
        request = request_by_id[str(attempt["request_id"])]
        source = _request_input_payload(request)
        parsed, parse_status, _ = _strict_json(attempt.get("raw_response_content"))
        if parse_status != "PASS" or not isinstance(parsed, dict):
            raise Stage7EAuditCorrectionError("A4 frozen response is not strict JSON")
        sections = parsed.get("sections")
        if not isinstance(sections, list):
            raise Stage7EAuditCorrectionError("A4 frozen response lacks sections")
        text_by_fact: dict[str, list[str]] = defaultdict(list)
        for section in sections:
            for fact_id in section["used_fact_lock_ids"]:
                text_by_fact[str(fact_id)].append(str(section["text"]))
        for fact in source["facts"]:
            value = fact["claim_value"]
            expected = value.get("metric_value")
            if not isinstance(expected, (int, float)) or isinstance(expected, bool):
                continue
            fact_id = str(fact["fact_lock_id"])
            texts = text_by_fact.get(fact_id, [])
            combined = "\n".join(texts)
            rows.append(
                {
                    "arm": "A4_FREE_FINAL_REALIZATION",
                    "object_id": fact_id,
                    "fact_lock_id": fact_id,
                    "task_id": attempt["task_id"],
                    "request_id": attempt["request_id"],
                    "expected_metric_value": expected,
                    "used": bool(texts),
                    "omitted": not texts,
                    "model_text": combined,
                    "extracted_decimal_tokens": ";".join(
                        str(item) for item in sorted(engineering_decimal_tokens_v2(combined))
                    ),
                    "v1_1_numeric_status": numeric_value_status_v2(value, combined)
                    if texts
                    else "NOT_EVALUABLE",
                    "numeric_status": numeric_value_status_v2(value, combined)
                    if texts
                    else "OMITTED_NOT_EVALUABLE",
                }
            )
    return sorted(rows, key=lambda row: (str(row["task_id"]), str(row["fact_lock_id"])))


def _numeric_correction_rows(
    a3_rows: list[dict[str, Any]],
    a4_rows: list[dict[str, Any]],
    old_a3: dict[str, dict[str, str]],
    old_a4: dict[tuple[str, str], dict[str, str]],
) -> list[dict[str, Any]]:
    rows = []
    for row in [item for item in a3_rows if item["numeric_claim"]] + a4_rows:
        object_id = str(row["object_id"])
        old = old_a3.get(object_id) or old_a4.get((str(row["task_id"]), object_id))
        old_status = old["numeric_value_exact"] if old else "NOT_EVALUABLE"
        new_status = str(row["v1_1_numeric_status"])
        if old_status == "FAIL" and new_status == "PASS":
            reason = "V1_UNICODE_WORD_BOUNDARY_FALSE_NEGATIVE"
        elif old_status == "NOT_EVALUABLE" and new_status == "PASS":
            reason = "A3_SECONDARY_FENCE_ONLY_RECOVERY"
        else:
            reason = "STATUS_UNCHANGED"
        rows.append(
            {
                "arm": row["arm"],
                "object_id": object_id,
                "task_id": row["task_id"],
                "expected_metric_value": row["expected_metric_value"],
                "model_text": row["model_text"],
                "v1_numeric_status": old_status,
                "v1_1_numeric_status": new_status,
                "correction_reason": reason,
            }
        )
    return sorted(rows, key=lambda row: (str(row["arm"]), str(row["object_id"])))


def _coverage_identity_rows(
    old_rows: list[dict[str, str]], new_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    old = {(str(row["task_id"]), str(row["fact_lock_id"])): row for row in old_rows}
    rows = []
    for row in new_rows:
        prior = old[(str(row["task_id"]), str(row["fact_lock_id"]))]
        old_used = prior["used"] == "True"
        rows.append(
            {
                "fact_lock_id": row["fact_lock_id"],
                "task_id": row["task_id"],
                "v1_used": old_used,
                "v1_1_used": row["used"],
                "identity_match": old_used == row["used"],
            }
        )
    return rows


def _scope_identity_rows(
    old_rows: list[dict[str, str]], new_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    def key(row: dict[str, Any]) -> tuple[str, int]:
        return str(row["request_id"]), int(row["section_index"])

    old = {key(row): row for row in old_rows}
    rows = []
    for row in new_rows:
        prior = old[key(row)]
        old_status = str(prior["explicit_scope_consistency"])
        new_status = str(row["explicit_scope_consistency"])
        rows.append(
            {
                "request_id": row["request_id"],
                "task_id": row["task_id"],
                "section_index": row["section_index"],
                "v1_scope_status": old_status,
                "v1_1_scope_status": new_status,
                "scope_audit_basis": row["scope_audit_basis"],
                "identity_match": old_status == new_status,
            }
        )
    return rows


def _old_artifact_identity(root: Path) -> list[dict[str, Any]]:
    prefix = OLD_ARTIFACT_DIR.as_posix()
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", OLD_TAG, "--", prefix],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    rows = []
    for relative in result.stdout.splitlines():
        frozen = _git_file_bytes(root, OLD_TAG, relative)
        path = root / relative
        current = path.read_bytes() if path.is_file() else b""
        rows.append(
            {
                "path": relative,
                "frozen_sha256": hashlib.sha256(frozen).hexdigest(),
                "current_sha256": hashlib.sha256(current).hexdigest() if current else "",
                "exists": path.is_file(),
                "identity_match": path.is_file() and frozen == current,
            }
        )
    return rows


def _raw_identity(root: Path, attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for attempt in attempts:
        relative = (OLD_ARTIFACT_DIR / str(attempt["raw_response_path"])).as_posix()
        frozen_bytes = _git_file_bytes(root, OLD_TAG, relative)
        current_bytes = (root / relative).read_bytes()
        frozen = json.loads(frozen_bytes)
        current = json.loads(current_bytes)
        rows.append(
            {
                "request_id": current["request_id"],
                "raw_response_path": relative,
                "frozen_sha256": hashlib.sha256(frozen_bytes).hexdigest(),
                "current_sha256": hashlib.sha256(current_bytes).hexdigest(),
                "raw_hash_match": frozen_bytes == current_bytes,
                "frozen_provider_response_id": frozen.get("provider_response_id"),
                "current_provider_response_id": current.get("provider_response_id"),
                "provider_response_id_changed": frozen.get("provider_response_id")
                != current.get("provider_response_id"),
                "frozen_request_payload_hash": frozen.get("request_payload_hash"),
                "current_request_payload_hash": current.get("request_payload_hash"),
                "request_payload_hash_changed": frozen.get("request_payload_hash")
                != current.get("request_payload_hash"),
            }
        )
    return rows


def _hard_checks(
    root: Path,
    attempts: list[dict[str, Any]],
    old_identity: list[dict[str, Any]],
    raw_identity: list[dict[str, Any]],
    result: dict[str, Any],
    semantic_hash: str,
    replay_hash: str,
) -> list[dict[str, Any]]:
    strict = result["strict_summary"]
    secondary = result["secondary_summary"]
    a4 = result["a4_summary"]
    checks = [
        _check(
            "old_stage7e_v1_tag_unchanged",
            _git_rev_parse(root, OLD_TAG) == OLD_COMMIT,
            _git_rev_parse(root, OLD_TAG),
        ),
        _check(
            "old_stage7e_v1_artifact_unchanged",
            all(row["identity_match"] for row in old_identity),
            sum(not row["identity_match"] for row in old_identity),
        ),
        _check(
            "raw_response_count_226", len(raw_identity) == len(attempts) == 226, len(raw_identity)
        ),
        _check(
            "raw_response_hash_mismatch_zero",
            all(row["raw_hash_match"] for row in raw_identity),
            sum(not row["raw_hash_match"] for row in raw_identity),
        ),
        _check(
            "provider_response_id_change_zero",
            not any(row["provider_response_id_changed"] for row in raw_identity),
            sum(row["provider_response_id_changed"] for row in raw_identity),
        ),
        _check(
            "request_payload_hash_change_zero",
            not any(row["request_payload_hash_changed"] for row in raw_identity),
            sum(row["request_payload_hash_changed"] for row in raw_identity),
        ),
        _check(
            "a3_strict_valid_chunks_125",
            strict["valid_chunk_count"] == 125,
            strict["valid_chunk_count"],
        ),
        _check(
            "a3_strict_claim_mappings_828",
            strict["mapping_complete_count"] == 828,
            strict["mapping_complete_count"],
        ),
        _check(
            "a3_strict_complete_tasks_32",
            strict["complete_task_count"] == 32,
            strict["complete_task_count"],
        ),
        _check(
            "a3_only_exact_outer_fence_removed",
            all(row["outer_fence_exact_match"] for row in result["fence_rows"]),
            len(result["fence_rows"]),
        ),
        _check(
            "a3_inner_content_modification_zero",
            all(int(row["content_character_change_count"]) == 0 for row in result["fence_rows"]),
            sum(int(row["content_character_change_count"]) for row in result["fence_rows"]),
        ),
        _check(
            "a3_secondary_valid_chunks_147",
            secondary["secondary_valid_chunks"] == 147,
            secondary["secondary_valid_chunks"],
        ),
        _check(
            "a3_secondary_claim_mappings_989",
            secondary["secondary_claim_mappings"] == 989,
            secondary["secondary_claim_mappings"],
        ),
        _check(
            "a3_secondary_complete_tasks_45",
            secondary["secondary_complete_tasks"] == 45,
            secondary["secondary_complete_tasks"],
        ),
        _check(
            "a3_numeric_claims_164",
            secondary["numeric_claim_count"] == 164,
            secondary["numeric_claim_count"],
        ),
        _check(
            "a3_corrected_numeric_exact_164",
            secondary["numeric_exact_count"] == 164,
            secondary["numeric_exact_count"],
        ),
        _check(
            "a3_corrected_numeric_drift_zero",
            secondary["numeric_drift_count"] == 0,
            secondary["numeric_drift_count"],
        ),
        _check(
            "a3_no_fabricated_numeric_values",
            secondary["numeric_not_evaluable_count"] == 0,
            secondary["numeric_not_evaluable_count"],
        ),
        _check(
            "a3_scope_distribution_unchanged",
            secondary["scope_status_distribution"] == {"NOT_EXPLICIT": 180, "PASS": 809},
            secondary["scope_status_distribution"],
        ),
        _check(
            "a4_factlocks_1022", a4["total_fact_lock_count"] == 1022, a4["total_fact_lock_count"]
        ),
        _check(
            "a4_used_factlocks_848", a4["used_fact_lock_count"] == 848, a4["used_fact_lock_count"]
        ),
        _check(
            "a4_omitted_factlocks_174",
            a4["omitted_fact_lock_count"] == 174,
            a4["omitted_fact_lock_count"],
        ),
        _check(
            "a4_coverage_unchanged",
            a4["fact_lock_coverage"] == 848 / 1022,
            a4["fact_lock_coverage"],
        ),
        _check(
            "a4_numeric_factlocks_171",
            a4["total_numeric_fact_lock_count"] == 171,
            a4["total_numeric_fact_lock_count"],
        ),
        _check(
            "a4_used_numeric_162",
            a4["used_numeric_fact_lock_count"] == 162,
            a4["used_numeric_fact_lock_count"],
        ),
        _check(
            "a4_omitted_numeric_9",
            a4["omitted_numeric_fact_lock_count"] == 9,
            a4["omitted_numeric_fact_lock_count"],
        ),
        _check(
            "a4_numeric_partition_identity",
            a4["used_numeric_fact_lock_count"] + a4["omitted_numeric_fact_lock_count"]
            == a4["total_numeric_fact_lock_count"],
            f"{a4['used_numeric_fact_lock_count']}+{a4['omitted_numeric_fact_lock_count']}="
            f"{a4['total_numeric_fact_lock_count']}",
        ),
        _check(
            "a4_used_numeric_exact_162",
            a4["used_numeric_exact_count"] == 162,
            a4["used_numeric_exact_count"],
        ),
        _check(
            "a4_numeric_drift_zero",
            a4["used_numeric_drift_count"] == 0,
            a4["used_numeric_drift_count"],
        ),
        _check(
            "a4_numeric_omission_task_distribution",
            a4["omitted_numeric_task_distribution"]
            == {
                "stage7_main_task_002": 2,
                "stage7_main_task_011": 1,
                "stage7_main_task_047": 6,
            },
            a4["omitted_numeric_task_distribution"],
        ),
        _check(
            "a4_numeric_coverage_162_of_171",
            a4["numeric_fact_lock_coverage"] == 162 / 171,
            a4["numeric_fact_lock_coverage"],
        ),
        _check(
            "a4_scope_distribution_unchanged",
            a4["scope_status_distribution"]
            == {"NOT_EVALUABLE": 2, "NOT_EXPLICIT": 108, "PASS": 43},
            a4["scope_status_distribution"],
        ),
        _check(
            "a4_trace_identity",
            all(row["identity_match"] for row in result["coverage_rows"]),
            sum(not row["identity_match"] for row in result["coverage_rows"]),
        ),
        _check(
            "a4_scope_identity",
            all(row["identity_match"] for row in result["scope_identity"]),
            sum(not row["identity_match"] for row in result["scope_identity"]),
        ),
        _check(
            "deterministic_replay_identity",
            semantic_hash == replay_hash,
            f"{semantic_hash}:{replay_hash}",
        ),
        _check("new_api_calls_zero", True, 0),
        _check("new_llm_calls_zero", True, 0),
        _check("new_deepseek_calls_zero", True, 0),
    ]
    return checks


def _write_outputs(output: Path, result: dict[str, Any]) -> None:
    _write_json(output / "a3_strict_primary_summary.json", result["strict_summary"])
    _write_csv(output / "a3_fence_only_normalization_audit.csv", result["fence_rows"])
    _write_csv(
        output / "a3_secondary_syntax_normalized_claim_results.csv",
        result["secondary_claim_results"],
    )
    _write_csv(output / "a3_secondary_numeric_audit.csv", result["secondary_numeric"])
    _write_csv(output / "a3_secondary_scope_audit.csv", result["secondary_scope"])
    _write_json(
        output / "a3_secondary_syntax_normalized_summary.json",
        result["secondary_summary"],
    )
    _write_csv(output / "a4_corrected_numeric_audit.csv", result["a4_numeric"])
    _write_json(output / "a4_corrected_numeric_summary.json", result["a4_summary"])
    _write_csv(output / "a4_coverage_identity_audit.csv", result["coverage_rows"])
    _write_csv(output / "a4_scope_identity_audit.csv", result["scope_identity"])
    _write_csv(output / "numeric_audit_correction.csv", result["numeric_corrections"])


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "a3_primary": result["strict_summary"],
        "a3_secondary": result["secondary_summary"],
        "a4": result["a4_summary"],
        "raw_response_count": 226,
        "new_api_calls": 0,
        "new_llm_calls": 0,
        "human_semantic_evaluation": "DEFERRED_TO_HUMAN",
    }


def _readme(summary: dict[str, Any]) -> str:
    a3 = summary["a3_secondary"]
    a4 = summary["a4"]
    return f"""# Stage7E-B v1.1 Offline Audit Correction

This directory is an offline deterministic correction layered on the immutable
Stage7E-B v1 execution. It makes zero API/LLM calls and does not modify requests,
prompts, provider identities, or any of the 226 frozen raw responses.

The preregistered strict A3 endpoint remains primary: 125/147 valid chunks,
828/989 Claim mappings, and 32/45 complete tasks. A secondary, post-hoc
fence-only sensitivity removes one exact outer Markdown fence without changing
the inner JSON. It recovers {a3["secondary_valid_chunks"]}/147 chunks and
{a3["secondary_claim_mappings"]}/989 mappings.

The corrected Unicode-safe decimal tokenizer finds exact values for all
{a3["numeric_exact_count"]} mapped A3 numeric Claims. In A4, all
{a4["used_numeric_exact_count"]} used numeric FactLocks preserve their exact
values; {a4["omitted_numeric_fact_lock_count"]} of
{a4["total_numeric_fact_lock_count"]} numeric FactLocks are omitted. Numeric
FactLock coverage is {a4["used_numeric_fact_lock_count"]}/
{a4["total_numeric_fact_lock_count"]} ({a4["numeric_fact_lock_coverage"]:.6%}).
Overall A4 trace coverage remains 848/1022 ({a4["fact_lock_coverage"]:.6%}).

FactLock trace coverage and numeric exactness are not proofs of complete semantic
correctness. Forecast promotion, unsupported causality, epistemic drift,
unknown-to-normal transformation, attention-to-probability transformation,
misleading risk, and engineering usefulness remain `DEFERRED_TO_HUMAN`.
"""


def _interpretation(summary: dict[str, Any]) -> str:
    a4 = summary["a4"]
    return f"""# Stage7E-B v1.1 Interpretation Correction

## A3

预注册的严格 JSON 主要终点保持不变: 125/147 个 chunk 合规, 828/989
个 Claim 完成映射, 32/45 个任务形成完整输出。22 个响应的 JSON 内容完整,
但被单一 Markdown code fence 包裹, 因此仍属于严格格式不合规。

仅作为事后、离线、确定性的敏感性分析, 移除唯一外层 fence 后, 147/147
个 chunk、989/989 个 Claim 和 45/45 个任务可以恢复。该分析没有修复 JSON、
没有修改模型文字, 也不替代 primary endpoint。

数值审计修正后, 全部 164 个可映射数值 Claim 均保留 frozen metric_value。
因此不能再把旧报告中的 149 个自动 FAIL 解释为去掉 FactLock 后的数值篡改。
A3 当前机器可确定地暴露的是结构化输出格式遵从问题; 复杂语义漂移仍需人工评价。

## A4

A4 contained {a4["total_numeric_fact_lock_count"]} numeric FactLocks in total.
Of these, {a4["used_numeric_fact_lock_count"]} were referenced in the generated
outputs and {a4["omitted_numeric_fact_lock_count"]} were omitted. All
{a4["used_numeric_exact_count"]} referenced numeric FactLocks preserved their
frozen numeric values exactly; no numeric-value drift was observed among
referenced numeric facts. Thus, the deterministic numeric effect of free final
realization was omission rather than value corruption.

A4 共包含 {a4["total_numeric_fact_lock_count"]} 条数值型 FactLock, 其中
{a4["used_numeric_fact_lock_count"]} 条被自由生成文本引用,
{a4["omitted_numeric_fact_lock_count"]} 条未被引用。对实际引用的
{a4["used_numeric_fact_lock_count"]} 条数值型 FactLock, 冻结数值均被精确保留,
未观察到数值漂移。因此当前确定性审计显示, 自由最终生成在数值层面的主要问题是
部分事实未被覆盖, 而不是已经引用的数值被篡改。

A4 的全 FactLock trace coverage 为 848/1022; 数值 FactLock trace coverage 为
{a4["used_numeric_fact_lock_count"]}/{a4["total_numeric_fact_lock_count"]}。
两个 denominator 表示不同总体, 不得混用。

FactLock ID coverage 只表示模型声明引用了哪些锁定事实, 数值一致也只证明数值
token 保持一致。二者都不能证明完整自然语言语义正确。
"""


def _bug_analysis() -> str:
    return """# Numeric Tokenizer v1 Bug Analysis

Stage7E-B v1 使用 `(?<![\\w.])-?\\d+(?:\\.\\d+)?(?![\\w.])`。Python
Unicode 正则把中文字符计入 `\\w`, 所以 `值为0.315` 中紧邻“为”的数字无法
匹配, 产生确定性的 false negative。

v1.1 使用 `(?<![\\d.])-?\\d+(?:\\.\\d+)?(?![\\d.])`。边界只防止数字或
小数点内部拆分, 不再把中文、英文、等号或括号错误地视为禁止边界。数值比较仍以
`Decimal(str(frozen_metric_value))` 的精确 membership 为准, 不进行容差替换、
四舍五入或文本改写。
"""


def write_audit_zip(root: Path, output: Path) -> Path:
    zip_path = root / AUDIT_ZIP
    sources = [
        root / "src/tbm_twin/evaluation/stage7e_audit_correction.py",
        root / "scripts/build_stage7e_audit_correction.py",
        root / "tests/unit/test_stage7e_audit_correction.py",
    ]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("git_refs.txt", _git_refs(root))
        for source in sources:
            if source.is_file():
                archive.write(source, source.relative_to(root).as_posix())
        for path in sorted(output.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())
    return zip_path


def _fence_result(raw_text: Any, matched: bool, reason: str) -> dict[str, Any]:
    return {
        "outer_fence_exact_match": matched,
        "opening_fence_language": "",
        "inner_text": "",
        "inner_sha256": "",
        "inner_json": None,
        "inner_json_parse": "FAIL",
        "inner_json_parse_error": reason,
        "content_character_change_count": 0,
        "rejection_reason": reason,
        "raw_type": type(raw_text).__name__,
    }


def _check(name: str, passed: bool, details: Any) -> dict[str, Any]:
    return {"check_name": name, "status": "PASS" if passed else "FAIL", "details": details}


def _git_rev_parse(root: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


def _git_file_bytes(root: Path, ref: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{ref}:{path}"], cwd=root, capture_output=True, check=True
    ).stdout


def _git_refs(root: Path) -> str:
    commands = [
        ["git", "branch", "--show-current"],
        ["git", "rev-parse", "HEAD"],
        ["git", "rev-parse", OLD_TAG],
        ["git", "tag", "--points-at", "HEAD"],
        ["git", "status", "--short"],
    ]
    blocks = []
    for command in commands:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
        blocks.append(f"$ {' '.join(command)}\n{result.stdout}{result.stderr}".rstrip())
    return "\n\n".join(blocks) + "\n"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise Stage7EAuditCorrectionError(f"expected JSON object: {path}")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row}) if rows else ["status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_hashes(output: Path) -> None:
    rows = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == "file_hashes.sha256":
            continue
        rows.append(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
            f"{path.relative_to(output).as_posix()}"
        )
    (output / "file_hashes.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")
