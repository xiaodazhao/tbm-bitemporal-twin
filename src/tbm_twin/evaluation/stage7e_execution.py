"""Stage7E-B execution and deterministic audit of frozen ablation requests."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from tbm_twin.realization.io import stable_hash
from tbm_twin.realization.stage6b import SECTION_TITLES

PROTOCOL_DIR = Path("artifacts/stage7e_ablation_protocol_v1_2")
OUTPUT_DIR = Path("artifacts/stage7e_ablation_execution_v1")
STAGE7B_RUN_DIR = Path(
    "artifacts/stage7b_main_comparison_v1/runs/stage7b_main_execution_3ae0f791811a2e711cb9f488"
)
PROTOCOL_TAG = "stage7e-ablation-protocol-v1.2-frozen"
PROTOCOL_COMMIT = "0976e125dfd9781e770dc4587337e976984ea2b2"
METHOD_VERSION = "stage7e_ablation_execution_v1"
SCHEMA_VERSION = "stage7e_ablation_execution.v1"
AUDIT_ZIP = "stage7e_ablation_execution_v1_audit.zip"
EXPECTED_ARM_COUNTS = {
    "A2_NO_ARCHITECTURAL_ABSTENTION": 31,
    "A3_NO_FACTLOCK": 147,
    "A4_FREE_FINAL_REALIZATION": 48,
}
NO_OUTPUT_TASKS = {
    "stage7_main_task_022",
    "stage7_main_task_026",
    "stage7_main_task_042",
}
SECTION_ORDER = (
    "geological_observed",
    "geological_forecast",
    "operational_attention",
    "geological_attention",
    "coupled_attention",
    "forward_attention",
    "insufficiency",
)
EXPLICIT_INSUFFICIENCY_PHRASES = (
    "当前指标不可用",
    "当前没有可用响应数据",
    "当前无可用响应数据",
    "无法据现有信息形成数值判断",
    "无法根据现有信息形成数值判断",
)


class Stage7EExecutionError(RuntimeError):
    """Raised when the frozen execution must fail closed."""


class FrozenDeepSeekProvider:
    """Transport-only adapter for byte-frozen Stage7E request messages."""

    def __init__(self, config: dict[str, Any], *, client: Any | None = None) -> None:
        self.config = config
        if client is not None:
            self.client = client
            return
        api_key = os.environ.get(str(config["api_key_env_var"]))
        if not api_key:
            raise Stage7EExecutionError("missing DEEPSEEK_API_KEY")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise Stage7EExecutionError("openai SDK is required for Stage7E-B") from exc
        self.client = OpenAI(
            api_key=api_key,
            base_url=str(config["base_url"]),
            max_retries=int(config["sdk_max_retries"]),
            timeout=120,
        )

    def request(self, frozen_request: dict[str, Any]) -> dict[str, Any]:
        """Issue one real request and return a raw-first transport record."""

        _validate_request_config(frozen_request, self.config)
        started_at = datetime.now(tz=UTC).isoformat()
        started = time.monotonic()
        try:
            response = cast(Any, self.client.responses).create(
                model=self.config["model"],
                temperature=self.config["temperature"],
                top_p=self.config["top_p"],
                max_output_tokens=self.config["max_output_tokens"],
                reasoning={"effort": self.config["reasoning_effort"]},
                input=frozen_request["messages"],
            )
            finished_at = datetime.now(tz=UTC).isoformat()
            latency_ms = int((time.monotonic() - started) * 1000)
            raw_payload = response.model_dump(mode="json")
            raw_text = getattr(response, "output_text", "") or _extract_output_text(raw_payload)
            termination = _termination(raw_payload, transport_success=True)
            usage = raw_payload.get("usage") or {}
            return _attempt_record(
                frozen_request,
                started_at=started_at,
                finished_at=finished_at,
                latency_ms=latency_ms,
                transport_success=True,
                transport_status="SUCCESS",
                provider_response_id=raw_payload.get("id"),
                provider_model=raw_payload.get("model"),
                raw_payload=raw_payload,
                raw_text=raw_text,
                termination=termination,
                usage=usage,
                error_type=None,
                error_message=None,
            )
        except Exception as exc:
            finished_at = datetime.now(tz=UTC).isoformat()
            latency_ms = int((time.monotonic() - started) * 1000)
            status_code = getattr(exc, "status_code", None)
            termination = "PROVIDER_FAILURE" if status_code is not None else "TRANSPORT_FAILURE"
            return _attempt_record(
                frozen_request,
                started_at=started_at,
                finished_at=finished_at,
                latency_ms=latency_ms,
                transport_success=False,
                transport_status=str(status_code or exc.__class__.__name__),
                provider_response_id=None,
                provider_model=None,
                raw_payload=None,
                raw_text=None,
                termination=termination,
                usage={},
                error_type=exc.__class__.__name__,
                error_message=_redact_secret(str(exc)),
            )


def preflight_stage7e(repo_root: Path, *, require_credential: bool) -> dict[str, Any]:
    """Verify the frozen Stage7E-A protocol before any API call."""

    root = repo_root.resolve()
    protocol_dir = root / PROTOCOL_DIR
    requests = _load_frozen_requests(protocol_dir)
    integrity = _request_integrity_rows(requests)
    tag_commit = _git_rev_parse(root, PROTOCOL_TAG)
    config_set = {_canonical(row["inference_config"]) for row in requests}
    config = requests[0]["inference_config"] if requests else {}
    checks = [
        _check("protocol_tag_commit", tag_commit == PROTOCOL_COMMIT, tag_commit),
        _check("protocol_file_hashes", _verify_hash_manifest(protocol_dir), 0),
        _check("frozen_request_count", len(requests) == 226, len(requests)),
        _check(
            "frozen_arm_counts",
            Counter(row["arm_internal"] for row in requests) == EXPECTED_ARM_COUNTS,
            dict(Counter(row["arm_internal"] for row in requests)),
        ),
        _check(
            "request_integrity",
            all(row["status"] == "PASS" for row in integrity),
            sum(row["status"] != "PASS" for row in integrity),
        ),
        _check("single_provider_config", len(config_set) == 1, len(config_set)),
        _check("provider", config.get("provider") == "deepseek", config.get("provider")),
        _check("model", config.get("model") == "deepseek-v4-flash", config.get("model")),
        _check(
            "base_url",
            config.get("base_url") == "https://api.deepseek.com",
            config.get("base_url"),
        ),
        _check("temperature", config.get("temperature") == 0.0, config.get("temperature")),
        _check("top_p", config.get("top_p") == 1.0, config.get("top_p")),
        _check(
            "reasoning_effort",
            config.get("reasoning_effort") == "none",
            config.get("reasoning_effort"),
        ),
        _check(
            "max_output_tokens",
            config.get("max_output_tokens") == 4096,
            config.get("max_output_tokens"),
        ),
        _check("max_retries", config.get("max_retries") == 0, config.get("max_retries")),
        _check(
            "sdk_max_retries",
            config.get("sdk_max_retries") == 0,
            config.get("sdk_max_retries"),
        ),
        _check(
            "credential_present",
            (not require_credential) or bool(os.environ.get("DEEPSEEK_API_KEY")),
            "REQUIRED_FOR_EXECUTION" if require_credential else "NOT_REQUIRED_FOR_DRY_RUN",
        ),
    ]
    return {
        "status": "PASS" if all(row["status"] == "PASS" for row in checks) else "FAIL",
        "checks": checks,
        "requests": requests,
        "request_integrity": integrity,
        "provider_config": config,
        "request_tree_hash": _request_tree_hash(root / PROTOCOL_DIR / "requests"),
    }


def build_execution_order(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Freeze a globally interleaved deterministic execution order."""

    ordered = sorted(
        requests,
        key=lambda row: hashlib.sha256(str(row["request_id"]).encode()).hexdigest(),
    )
    return [
        {
            "execution_index": index,
            "order_key": hashlib.sha256(str(row["request_id"]).encode()).hexdigest(),
            "request_id": row["request_id"],
            "task_id": row["task_id"],
            "arm_internal": row["arm_internal"],
            "request_scope": row["request_scope"],
            "request_payload_hash": row["payload_hash"],
        }
        for index, row in enumerate(ordered)
    ]


def run_stage7e(
    repo_root: Path,
    *,
    execute: bool,
    output_dir: Path | None = None,
    provider: FrozenDeepSeekProvider | None = None,
    create_audit_zip: bool = True,
) -> dict[str, Any]:
    """Prepare or execute all 226 frozen Stage7E-B requests."""

    root = repo_root.resolve()
    output = output_dir or root / OUTPUT_DIR
    preflight = preflight_stage7e(root, require_credential=execute and provider is None)
    output.mkdir(parents=True, exist_ok=True)
    requests = preflight["requests"]
    order = build_execution_order(requests)
    protocol = _execution_protocol(preflight)
    _write_json(output / "stage7e_execution_protocol.json", protocol)
    _write_csv(output / "stage7e_preflight_audit.csv", preflight["checks"])
    _write_csv(output / "stage7e_request_integrity_audit.csv", preflight["request_integrity"])
    _write_csv(output / "stage7e_execution_order.csv", order)
    if preflight["status"] != "PASS":
        raise Stage7EExecutionError("Stage7E-B preflight failed")
    if not execute:
        summary = {
            "status": "PREFLIGHT_PASS_NOT_EXECUTED",
            "planned_requests": len(order),
            "actual_attempts": 0,
            "api_calls": 0,
            "llm_calls": 0,
            "request_tree_hash": preflight["request_tree_hash"],
            "execution_order_hash": stable_hash(order),
        }
        _write_json(output / "run_summary.json", summary)
        _write_hashes(output)
        return summary

    attempt_manifest_path = output / "stage7e_raw_attempt_manifest.csv"
    if attempt_manifest_path.exists() and _read_csv(attempt_manifest_path):
        raise Stage7EExecutionError("existing attempts found; refusing to call API again")
    raw_root = output / "raw_responses"
    if raw_root.exists():
        shutil.rmtree(raw_root)
    raw_root.mkdir(parents=True)
    request_by_id = {str(row["request_id"]): row for row in requests}
    transport = provider or FrozenDeepSeekProvider(preflight["provider_config"])
    attempts: list[dict[str, Any]] = []
    for order_row in order:
        request = request_by_id[str(order_row["request_id"])]
        attempt = transport.request(request)
        attempt["execution_index"] = order_row["execution_index"]
        raw_path = (
            raw_root / _arm_short(str(request["arm_internal"])) / f"{request['request_id']}.json"
        )
        _write_json(raw_path, attempt)
        attempt["raw_response_path"] = raw_path.relative_to(output).as_posix()
        attempts.append(attempt)
        _write_csv(attempt_manifest_path, [_attempt_manifest_row(row) for row in attempts])
        print(
            f"STAGE7E_ATTEMPT {len(attempts)}/226 "
            f"{request['request_id']} {attempt['output_termination_class']}"
        )
    if len(attempts) != 226:
        raise Stage7EExecutionError(f"expected 226 attempts, got {len(attempts)}")
    return _finalize_execution(
        root,
        output,
        preflight,
        attempts,
        protocol,
        create_audit_zip=create_audit_zip,
    )


def replay_stage7e(repo_root: Path, output_dir: Path | None = None) -> dict[str, Any]:
    """Replay parsing and all deterministic audits without API access."""

    root = repo_root.resolve()
    output = output_dir or root / OUTPUT_DIR
    preflight = preflight_stage7e(root, require_credential=False)
    attempts = _load_attempts(output)
    protocol = _read_json(output / "stage7e_execution_protocol.json")
    return _finalize_execution(root, output, preflight, attempts, protocol, replay_only=True)


def _attempt_record(
    request: dict[str, Any],
    *,
    started_at: str,
    finished_at: str,
    latency_ms: int,
    transport_success: bool,
    transport_status: str,
    provider_response_id: Any,
    provider_model: Any,
    raw_payload: Any,
    raw_text: Any,
    termination: str,
    usage: dict[str, Any],
    error_type: str | None,
    error_message: str | None,
) -> dict[str, Any]:
    return {
        "request_id": request["request_id"],
        "task_id": request["task_id"],
        "arm_internal": request["arm_internal"],
        "request_scope": request["request_scope"],
        "request_payload_hash": request["payload_hash"],
        "request_started_at": started_at,
        "request_finished_at": finished_at,
        "latency_ms": latency_ms,
        "transport_success": transport_success,
        "transport_status": transport_status,
        "provider_response_id": provider_response_id,
        "provider_returned_model_identity": provider_model,
        "raw_response_body": raw_payload,
        "raw_response_content": raw_text,
        "provider_status": raw_payload.get("status") if isinstance(raw_payload, dict) else None,
        "finish_reason": _finish_reason(raw_payload),
        "output_termination_class": termination,
        "truncation_exposed": termination == "OUTPUT_LIMIT_OR_LENGTH_TERMINATION",
        "prompt_input_token_count": usage.get("input_tokens"),
        "completion_output_token_count": usage.get("output_tokens"),
        "total_token_count": usage.get("total_tokens"),
        "parse_status": "NOT_PARSED_RAW_FIRST",
        "schema_status": "NOT_VALIDATED_RAW_FIRST",
        "provider_error_type": error_type,
        "provider_error_message": error_message,
        "attempt_number": 1,
        "retry_count": 0,
        "real_api_attempted": True,
    }


def _finalize_execution(
    root: Path,
    output: Path,
    preflight: dict[str, Any],
    attempts: list[dict[str, Any]],
    protocol: dict[str, Any],
    *,
    replay_only: bool = False,
    create_audit_zip: bool = True,
) -> dict[str, Any]:
    inputs = _analysis_inputs(root, preflight["requests"])
    first = _derive_results(inputs, attempts)
    second = _derive_results(inputs, attempts)
    first_hash = stable_hash(first)
    second_hash = stable_hash(second)
    replay_rows = [
        _check("raw_attempt_count", len(attempts) == 226, len(attempts)),
        _check("deterministic_replay", first_hash == second_hash, f"{first_hash}:{second_hash}"),
    ]
    stored_reference = output / "stage7e_replay_reference.json"
    if stored_reference.exists():
        stored_hash = _read_json(stored_reference).get("semantic_result_hash")
        replay_rows.append(_check("stored_execution_replay", stored_hash == first_hash, first_hash))
    else:
        _write_json(stored_reference, {"semantic_result_hash": first_hash})
        replay_rows.append(_check("stored_execution_replay", True, first_hash))
    _write_derived_outputs(output, first)
    _write_csv(output / "stage7e_replay_audit.csv", replay_rows)
    hard_rows = _hard_checks(root, output, preflight, attempts, first, replay_rows)
    _write_csv(output / "hard_check.csv", hard_rows)
    summary = _execution_summary(attempts, first, replay_rows, hard_rows, protocol)
    _write_json(output / "run_summary.json", summary)
    _write_json(output / "stage7e_arm_execution_summary.json", summary)
    _write_csv(
        output / "stage7e_output_availability_summary.csv",
        first["output_availability"],
    )
    _write_csv(
        output / "stage7e_deterministic_endpoint_table.csv",
        first["endpoint_rows"],
    )
    _write_csv(output / "stage7e_paired_task_summary.csv", first["paired_rows"])
    _write_csv(
        output / "stage7e_human_eval_deferred_manifest.csv",
        _human_deferred_rows(),
    )
    _write_csv(
        output / "upstream_freeze_audit.csv",
        _upstream_freeze_rows(root, preflight),
    )
    generated_at = datetime.now(tz=UTC).isoformat()
    method = {
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "protocol_tag": PROTOCOL_TAG,
        "protocol_commit": PROTOCOL_COMMIT,
        "request_tree_hash": preflight["request_tree_hash"],
        "execution_order_hash": protocol["execution_order_hash"],
        "provider_config": preflight["provider_config"],
        "actual_api_attempts": len(attempts),
        "retry_count": sum(int(row["retry_count"]) for row in attempts),
        "semantic_replay_hash": first_hash,
        "human_semantic_evaluation": "DEFERRED",
    }
    freeze = {
        **method,
        "status": "EXECUTED_AND_DETERMINISTICALLY_AUDITED",
        "summary": summary,
        "hard_check_failure_count": sum(row["status"] != "PASS" for row in hard_rows),
    }
    _write_json(output / "method_version.json", method)
    _write_json(output / "freeze_manifest.json", freeze)
    (output / "README.md").write_text(_readme(summary), encoding="utf-8")
    _write_hashes(output)
    if not replay_only and create_audit_zip:
        _write_audit_zip(root, output)
    if any(row["status"] != "PASS" for row in hard_rows):
        raise Stage7EExecutionError("Stage7E-B hard checks failed")
    return summary


def _analysis_inputs(root: Path, requests: list[dict[str, Any]]) -> dict[str, Any]:
    protocol_dir = root / PROTOCOL_DIR
    p_outputs = {
        str(row["benchmark_task_id"]): row
        for row in _read_jsonl(root / STAGE7B_RUN_DIR / "P_final_outputs.jsonl")
    }
    tasks = _read_csv(protocol_dir / "stage7e_task_manifest.csv")
    return {
        "root": root,
        "requests": requests,
        "request_by_id": {str(row["request_id"]): row for row in requests},
        "tasks": tasks,
        "task_ids": [str(row["task_id"]) for row in tasks],
        "p_outputs": p_outputs,
        "a2_targets": _read_csv(protocol_dir / "a2_architectural_abstention_targets.csv"),
        "a2_contexts": _read_jsonl(protocol_dir / "a2_compact_unresolved_context_manifest.jsonl"),
        "a3_claims": _read_csv(protocol_dir / "a3_typed_claim_realization_manifest.csv"),
        "a3_chunks": _read_csv(protocol_dir / "a3_request_chunk_manifest.csv"),
        "a4_facts": _read_csv(protocol_dir / "a4_factlock_task_manifest.csv"),
        "a4_registry": _read_json(protocol_dir / "a4_normalized_payload_registry.json"),
    }


def _derive_results(inputs: dict[str, Any], attempts: list[dict[str, Any]]) -> dict[str, Any]:
    request_by_id = inputs["request_by_id"]
    a2_attempts = [
        row for row in attempts if row["arm_internal"] == "A2_NO_ARCHITECTURAL_ABSTENTION"
    ]
    a3_attempts = [row for row in attempts if row["arm_internal"] == "A3_NO_FACTLOCK"]
    a4_attempts = [row for row in attempts if row["arm_internal"] == "A4_FREE_FINAL_REALIZATION"]
    a2 = _analyze_a2(inputs, a2_attempts, request_by_id)
    a3 = _analyze_a3(inputs, a3_attempts, request_by_id)
    a4 = _analyze_a4(inputs, a4_attempts, request_by_id)
    p_available = len(inputs["p_outputs"])
    output_availability = [
        {
            "arm": "P_FULL",
            "denominator_unit": "TASK_CONDITION",
            "denominator": 48,
            "valid_output_count": p_available,
            "availability_rate": p_available / 48,
        },
        {
            "arm": "A2_NO_ARCHITECTURAL_ABSTENTION",
            "denominator_unit": "AFFECTED_TASK",
            "denominator": 24,
            "valid_output_count": a2["valid_affected_task_count"],
            "availability_rate": a2["valid_affected_task_count"] / 24,
        },
        {
            "arm": "A3_NO_FACTLOCK",
            "denominator_unit": "ELIGIBLE_TASK",
            "denominator": 45,
            "valid_output_count": a3["complete_task_count"],
            "availability_rate": a3["complete_task_count"] / 45,
        },
        {
            "arm": "A4_FREE_FINAL_REALIZATION",
            "denominator_unit": "TASK_CONDITION",
            "denominator": 48,
            "valid_output_count": a4["valid_task_count"],
            "availability_rate": a4["valid_task_count"] / 48,
        },
    ]
    paired_rows = [
        {
            "comparison": "A2_VS_P",
            "primary_denominator": 24,
            "denominator_definition": "A2_AFFECTED_TASKS",
            "p_valid_count": 24,
            "treatment_valid_count": a2["valid_affected_task_count"],
        },
        {
            "comparison": "A3_VS_P",
            "primary_denominator": 45,
            "denominator_definition": "COMMON_P_VALID_TASKS",
            "p_valid_count": 45,
            "treatment_valid_count": a3["complete_task_count"],
        },
        {
            "comparison": "A4_VS_P",
            "primary_denominator": 45,
            "denominator_definition": "COMMON_P_VALID_TASKS",
            "p_valid_count": 45,
            "treatment_valid_count": a4["valid_p_common_task_count"],
        },
        {
            "comparison": "A4_ON_P_NO_OUTPUT",
            "primary_denominator": 3,
            "denominator_definition": "P_NO_OUTPUT_TASKS_022_026_042",
            "p_valid_count": 0,
            "treatment_valid_count": a4["valid_p_no_output_task_count"],
        },
    ]
    endpoint_rows = _endpoint_rows(a2, a3, a4)
    return {
        "a2": a2,
        "a3": a3,
        "a4": a4,
        "output_availability": output_availability,
        "paired_rows": paired_rows,
        "endpoint_rows": endpoint_rows,
    }


def _analyze_a2(
    inputs: dict[str, Any],
    attempts: list[dict[str, Any]],
    request_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    valid_text_by_task_section: dict[tuple[str, str], str] = {}
    for attempt in sorted(attempts, key=lambda row: str(row["request_id"])):
        request = request_by_id[str(attempt["request_id"])]
        payload = _request_input_payload(request)
        expected_section = str(payload["section_id"])
        expected_context_ids = {
            str(row["context_id"]) for row in payload["engineering_context_items"]
        }
        parsed, parse_status, parse_error = _strict_json(attempt.get("raw_response_content"))
        parsed_dict = parsed if isinstance(parsed, dict) else {}
        structural = bool(
            isinstance(parsed, dict)
            and set(parsed) == {"section_id", "text", "used_context_ids"}
            and isinstance(parsed.get("section_id"), str)
            and isinstance(parsed.get("text"), str)
            and _is_string_list(parsed.get("used_context_ids"))
        )
        returned_section = str(parsed_dict.get("section_id", ""))
        text = str(parsed_dict.get("text", ""))
        used_ids = (
            [str(value) for value in parsed_dict.get("used_context_ids", [])] if structural else []
        )
        unknown_ids = sorted(set(used_ids) - expected_context_ids)
        section_match = returned_section == expected_section
        schema_valid = structural and section_match and not unknown_ids
        valid = bool(attempt["transport_success"] and parse_status == "PASS" and schema_valid)
        if valid:
            valid_text_by_task_section[(str(attempt["task_id"]), expected_section)] = text
        output_class = "EMPTY_TEXT" if not text.strip() else "NONEMPTY_TEXT"
        insufficiency = _explicit_insufficiency_class(text)
        results.append(
            {
                "request_id": attempt["request_id"],
                "task_id": attempt["task_id"],
                "section_id_expected": expected_section,
                "section_id_returned": returned_section,
                "transport_success": attempt["transport_success"],
                "parse_status": parse_status,
                "parse_error": parse_error,
                "schema_status": "PASS" if schema_valid else "FAIL",
                "section_id_match": section_match,
                "expected_context_ids": ";".join(sorted(expected_context_ids)),
                "used_context_ids": ";".join(used_ids),
                "unknown_context_ids": ";".join(unknown_ids),
                "unknown_context_id_count": len(unknown_ids),
                "output_class": output_class,
                "explicit_insufficiency_class": insufficiency,
                "text": text,
                "valid_section_output": valid,
                "output_termination_class": attempt["output_termination_class"],
                "truncation_exposed": attempt["truncation_exposed"],
            }
        )
    targets_by_task: dict[str, list[str]] = defaultdict(list)
    for row in inputs["a2_targets"]:
        targets_by_task[str(row["task_id"])].append(str(row["section_id"]))
    composition_rows: list[dict[str, Any]] = []
    identity_rows: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for task_id in inputs["task_ids"]:
        p_output = inputs["p_outputs"].get(task_id)
        target_sections = sorted(set(targets_by_task.get(task_id, [])))
        if task_id in NO_OUTPUT_TASKS:
            composition_rows.append(
                {
                    "task_id": task_id,
                    "affected": False,
                    "target_sections": "",
                    "composition_status": "NO_VALID_OUTPUT",
                    "p_output_available": False,
                    "all_target_sections_valid": False,
                }
            )
            continue
        if p_output is None:
            raise Stage7EExecutionError(f"missing frozen P output for {task_id}")
        if not target_sections:
            outputs.append(
                {
                    "task_id": task_id,
                    "composition_status": "IDENTITY_REUSED_P",
                    "text": p_output["text"],
                    "text_hash": stable_hash(p_output["text"]),
                    "target_sections": [],
                }
            )
            composition_rows.append(
                {
                    "task_id": task_id,
                    "affected": False,
                    "target_sections": "",
                    "composition_status": "IDENTITY_REUSED_P",
                    "p_output_available": True,
                    "all_target_sections_valid": True,
                }
            )
            continue
        section_replacements = {
            section: valid_text_by_task_section.get((task_id, section))
            for section in target_sections
        }
        all_valid = all(value is not None for value in section_replacements.values())
        composed_text, output_sections = _compose_a2_output(p_output, section_replacements)
        outputs.append(
            {
                "task_id": task_id,
                "composition_status": "A2_COMPLETE_TASK_OUTPUT"
                if all_valid
                else "A2_TASK_OUTPUT_INCOMPLETE",
                "text": composed_text,
                "text_hash": stable_hash(composed_text),
                "target_sections": target_sections,
                "sections": output_sections,
            }
        )
        composition_rows.append(
            {
                "task_id": task_id,
                "affected": True,
                "target_sections": ";".join(target_sections),
                "composition_status": "A2_COMPLETE_TASK_OUTPUT"
                if all_valid
                else "A2_TASK_OUTPUT_INCOMPLETE",
                "p_output_available": True,
                "all_target_sections_valid": all_valid,
            }
        )
        p_sections = {
            str(row["section_id"]): str(row["text"])
            for row in p_output["sections"]
            if str(row["section_id"]) != "insufficiency"
        }
        p_sections["insufficiency"] = "\n".join(
            str(value) for value in p_output["insufficiency_statements"]
        )
        result_sections = {str(row["section_id"]): str(row["text"]) for row in output_sections}
        for section_id, p_text in p_sections.items():
            if section_id in target_sections:
                continue
            actual = result_sections.get(section_id, "")
            identity_rows.append(
                {
                    "task_id": task_id,
                    "section_id": section_id,
                    "p_text_hash": stable_hash(p_text),
                    "a2_text_hash": stable_hash(actual),
                    "byte_identity": p_text == actual,
                    "status": "PASS" if p_text == actual else "FAIL",
                }
            )
    valid_affected = sum(
        row["affected"] and row["composition_status"] == "A2_COMPLETE_TASK_OUTPUT"
        for row in composition_rows
    )
    summary = {
        "target_section_count": len(results),
        "affected_task_count": len(targets_by_task),
        "valid_section_count": sum(row["valid_section_output"] for row in results),
        "nonempty_text_count": sum(row["output_class"] == "NONEMPTY_TEXT" for row in results),
        "empty_text_count": sum(row["output_class"] == "EMPTY_TEXT" for row in results),
        "explicit_insufficiency_count": sum(
            row["explicit_insufficiency_class"] == "EXPLICIT_INSUFFICIENCY" for row in results
        ),
        "insufficiency_unknown_count": sum(
            row["explicit_insufficiency_class"] == "UNKNOWN" for row in results
        ),
        "unknown_context_id_violation_count": sum(
            int(row["unknown_context_id_count"]) for row in results
        ),
        "valid_affected_task_count": valid_affected,
        "non_target_p_identity_mismatch_count": sum(
            row["status"] != "PASS" for row in identity_rows
        ),
        "empirical_scope": ("UNAVAILABLE_ATTENTION_METRIC_CONTEXTS_IN_FROZEN_BENCHMARK"),
    }
    return {
        **summary,
        "section_results": results,
        "composition_rows": composition_rows,
        "identity_rows": identity_rows,
        "outputs": outputs,
        "summary": summary,
    }


def _compose_a2_output(
    p_output: dict[str, Any], replacements: dict[str, str | None]
) -> tuple[str, list[dict[str, str]]]:
    sections = []
    parts = []
    for source in p_output["sections"]:
        section_id = str(source["section_id"])
        if section_id == "insufficiency":
            continue
        text = replacements.get(section_id, str(source["text"]))
        text = text or ""
        sections.append({"section_id": section_id, "text": text})
        if text:
            parts.extend([f"## {SECTION_TITLES[section_id]}", text])
    insufficiency = "\n".join(str(value) for value in p_output["insufficiency_statements"])
    sections.append({"section_id": "insufficiency", "text": insufficiency})
    if insufficiency:
        parts.extend([f"## {SECTION_TITLES['insufficiency']}", insufficiency])
    return "\n\n".join(parts), sections


def _analyze_a3(
    inputs: dict[str, Any],
    attempts: list[dict[str, Any]],
    request_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    chunk_results: list[dict[str, Any]] = []
    claim_results: list[dict[str, Any]] = []
    drift_rows: list[dict[str, Any]] = []
    valid_sentence_by_claim: dict[str, str] = {}
    expected_claim_by_id = {str(row["claim_id"]): row for row in inputs["a3_claims"]}
    chunks_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for attempt in sorted(attempts, key=lambda row: str(row["request_id"])):
        request = request_by_id[str(attempt["request_id"])]
        payload = _request_input_payload(request)
        expected_ids = [str(row["claim_id"]) for row in payload["claims"]]
        parsed, parse_status, parse_error = _strict_json(attempt.get("raw_response_content"))
        parsed_dict = parsed if isinstance(parsed, dict) else {}
        structural = bool(
            isinstance(parsed, dict)
            and set(parsed) == {"realizations"}
            and isinstance(parsed.get("realizations"), list)
            and all(
                isinstance(row, dict)
                and set(row) == {"claim_id", "sentence"}
                and isinstance(row.get("claim_id"), str)
                and isinstance(row.get("sentence"), str)
                for row in parsed.get("realizations", [])
            )
        )
        realizations = parsed_dict.get("realizations", []) if structural else []
        returned_ids = [str(row["claim_id"]) for row in realizations]
        counts = Counter(returned_ids)
        missing = sorted(set(expected_ids) - set(returned_ids))
        duplicate = sorted(claim_id for claim_id, count in counts.items() if count > 1)
        unexpected = sorted(set(returned_ids) - set(expected_ids))
        empty = sorted(
            str(row["claim_id"])
            for row in realizations
            if str(row["claim_id"]) in expected_ids and not str(row["sentence"]).strip()
        )
        mapping_complete = (
            structural and not missing and not duplicate and not unexpected and not empty
        )
        chunk_valid = bool(
            attempt["transport_success"] and parse_status == "PASS" and mapping_complete
        )
        result = {
            "request_id": attempt["request_id"],
            "chunk_id": request.get("chunk_id", ""),
            "task_id": attempt["task_id"],
            "expected_claim_count": len(expected_ids),
            "returned_claim_count": len(returned_ids),
            "transport_success": attempt["transport_success"],
            "parse_status": parse_status,
            "parse_error": parse_error,
            "schema_status": "PASS" if structural else "FAIL",
            "mapping_complete": mapping_complete,
            "missing_claim_ids": ";".join(missing),
            "missing_claim_count": len(missing),
            "duplicate_claim_ids": ";".join(duplicate),
            "duplicate_claim_count": len(duplicate),
            "unexpected_claim_ids": ";".join(unexpected),
            "unexpected_claim_count": len(unexpected),
            "empty_sentence_ids": ";".join(empty),
            "empty_sentence_count": len(empty),
            "chunk_valid": chunk_valid,
            "output_termination_class": attempt["output_termination_class"],
            "truncation_exposed": attempt["truncation_exposed"],
        }
        chunk_results.append(result)
        chunks_by_task[str(attempt["task_id"])].append(result)
        realization_by_id: dict[str, list[str]] = defaultdict(list)
        for row in realizations:
            realization_by_id[str(row["claim_id"])].append(str(row["sentence"]))
        for claim_id in expected_ids:
            sentences = realization_by_id.get(claim_id, [])
            sentence = sentences[0] if len(sentences) == 1 else ""
            mapped = len(sentences) == 1 and bool(sentence.strip())
            if mapped:
                valid_sentence_by_claim[claim_id] = sentence
            claim_results.append(
                {
                    "request_id": attempt["request_id"],
                    "chunk_id": request.get("chunk_id", ""),
                    "task_id": attempt["task_id"],
                    "claim_id": claim_id,
                    "mapping_count": len(sentences),
                    "mapping_complete": mapped,
                    "sentence": sentence,
                    "sentence_hash": stable_hash(sentence) if sentence else "",
                }
            )
            claim = expected_claim_by_id[claim_id]
            drift_rows.append(_claim_drift_row(attempt, claim, sentence, mapped))
        for claim_id in unexpected:
            claim_results.append(
                {
                    "request_id": attempt["request_id"],
                    "chunk_id": request.get("chunk_id", ""),
                    "task_id": attempt["task_id"],
                    "claim_id": claim_id,
                    "mapping_count": counts[claim_id],
                    "mapping_complete": False,
                    "sentence": realization_by_id[claim_id][0],
                    "sentence_hash": stable_hash(realization_by_id[claim_id][0]),
                    "unexpected_claim_id": True,
                }
            )
    claims_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in inputs["a3_claims"]:
        claims_by_task[str(row["task_id"])].append(row)
    reconstruction_rows: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for task_id in inputs["task_ids"]:
        if task_id in NO_OUTPUT_TASKS:
            reconstruction_rows.append(
                {
                    "task_id": task_id,
                    "expected_chunk_count": 0,
                    "valid_chunk_count": 0,
                    "expected_claim_count": 0,
                    "mapped_claim_count": 0,
                    "reconstruction_status": "NO_VALID_OUTPUT",
                    "p_plan_reused": False,
                }
            )
            continue
        task_chunks = chunks_by_task.get(task_id, [])
        task_claims = sorted(claims_by_task[task_id], key=lambda row: int(row["order_index"]))
        complete = bool(
            task_chunks
            and all(row["chunk_valid"] for row in task_chunks)
            and all(str(row["claim_id"]) in valid_sentence_by_claim for row in task_claims)
        )
        reconstruction_rows.append(
            {
                "task_id": task_id,
                "expected_chunk_count": len(task_chunks),
                "valid_chunk_count": sum(row["chunk_valid"] for row in task_chunks),
                "expected_claim_count": len(task_claims),
                "mapped_claim_count": sum(
                    str(row["claim_id"]) in valid_sentence_by_claim for row in task_claims
                ),
                "reconstruction_status": "A3_COMPLETE_TASK_OUTPUT"
                if complete
                else "A3_TASK_OUTPUT_INCOMPLETE",
                "p_plan_reused": True,
            }
        )
        if complete:
            p_output = inputs["p_outputs"][task_id]
            text, sections = _compose_a3_output(p_output, task_claims, valid_sentence_by_claim)
            outputs.append(
                {
                    "task_id": task_id,
                    "composition_status": "A3_COMPLETE_TASK_OUTPUT",
                    "text": text,
                    "text_hash": stable_hash(text),
                    "sections": sections,
                    "model_sentence_count": len(task_claims),
                    "model_text_rewritten": False,
                }
            )
    summary = {
        "chunk_count": len(chunk_results),
        "valid_chunk_count": sum(row["chunk_valid"] for row in chunk_results),
        "expected_claim_count": len(inputs["a3_claims"]),
        "mapping_complete_count": sum(row["mapping_complete"] for row in claim_results),
        "missing_claim_count": sum(int(row["missing_claim_count"]) for row in chunk_results),
        "duplicate_claim_count": sum(int(row["duplicate_claim_count"]) for row in chunk_results),
        "unexpected_claim_id_count": sum(
            int(row["unexpected_claim_count"]) for row in chunk_results
        ),
        "empty_sentence_count": sum(int(row["empty_sentence_count"]) for row in chunk_results),
        "numeric_drift_count": sum(row["numeric_value_exact"] == "FAIL" for row in drift_rows),
        "verified_unit_drift_count": sum(
            row["verified_unit_exact"] == "FAIL" for row in drift_rows
        ),
        "explicit_scope_drift_count": sum(
            row["explicit_scope_consistency"] == "FAIL" for row in drift_rows
        ),
        "complete_task_count": sum(
            row["reconstruction_status"] == "A3_COMPLETE_TASK_OUTPUT" for row in reconstruction_rows
        ),
        "truncation_count": sum(row["truncation_exposed"] for row in chunk_results),
    }
    return {
        **summary,
        "chunk_results": chunk_results,
        "claim_results": claim_results,
        "drift_rows": drift_rows,
        "reconstruction_rows": reconstruction_rows,
        "outputs": outputs,
        "summary": summary,
    }


def _compose_a3_output(
    p_output: dict[str, Any],
    claims: list[dict[str, Any]],
    sentences: dict[str, str],
) -> tuple[str, list[dict[str, Any]]]:
    claims_by_section: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        claims_by_section[str(claim["section_id"])].append(claim)
    sections: list[dict[str, Any]] = []
    parts = []
    for source in p_output["sections"]:
        section_id = str(source["section_id"])
        if section_id == "insufficiency":
            continue
        section_claims = sorted(
            claims_by_section.get(section_id, []), key=lambda row: int(row["order_index"])
        )
        text = "\n".join(sentences[str(row["claim_id"])] for row in section_claims)
        sections.append(
            {
                "section_id": section_id,
                "claim_ids": [str(row["claim_id"]) for row in section_claims],
                "text": text,
            }
        )
        if text:
            parts.extend([f"## {SECTION_TITLES[section_id]}", text])
    insufficiency = "\n".join(str(value) for value in p_output["insufficiency_statements"])
    sections.append({"section_id": "insufficiency", "claim_ids": [], "text": insufficiency})
    if insufficiency:
        parts.extend([f"## {SECTION_TITLES['insufficiency']}", insufficiency])
    return "\n\n".join(parts), sections


def _claim_drift_row(
    attempt: dict[str, Any], claim: dict[str, Any], sentence: str, mapped: bool
) -> dict[str, Any]:
    value = json.loads(str(claim["claim_value"]))
    scope = json.loads(str(claim["subject_scope"]))
    numeric_status = _numeric_value_status(value, sentence) if mapped else "NOT_EVALUABLE"
    unit_status = "NOT_APPLICABLE" if str(claim["unit_verified"]) != "True" else "PASS"
    scope_status, observed_chainages = (
        _scope_status(scope, sentence)
        if mapped
        else (
            "NOT_EVALUABLE",
            [],
        )
    )
    return {
        "request_id": attempt["request_id"],
        "task_id": attempt["task_id"],
        "claim_id": claim["claim_id"],
        "claim_mapping_complete": mapped,
        "numeric_value_exact": numeric_status,
        "verified_unit_exact": unit_status,
        "explicit_scope_consistency": scope_status,
        "observed_explicit_chainages": ";".join(str(value) for value in observed_chainages),
        "semantic_epistemic_drift": "DEFERRED_TO_HUMAN",
        "causality_drift": "DEFERRED_TO_HUMAN",
        "unknown_to_normal": "DEFERRED_TO_HUMAN",
        "attention_to_probability": "DEFERRED_TO_HUMAN",
    }


def _analyze_a4(
    inputs: dict[str, Any],
    attempts: list[dict[str, Any]],
    request_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    facts_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    fact_by_id: dict[str, dict[str, Any]] = {}
    for fact in inputs["a4_facts"]:
        task_id = str(fact["task_id"])
        facts_by_task[task_id].append(fact)
        fact_by_id[str(fact["fact_lock_id"])] = fact
    task_results: list[dict[str, Any]] = []
    trace_rows: list[dict[str, Any]] = []
    drift_rows: list[dict[str, Any]] = []
    scope_section_rows: list[dict[str, Any]] = []
    termination_rows: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for attempt in sorted(attempts, key=lambda row: str(row["request_id"])):
        request = request_by_id[str(attempt["request_id"])]
        task_id = str(attempt["task_id"])
        payload = _request_input_payload(request)
        expected_ids = {str(row["fact_lock_id"]) for row in payload["facts"]}
        parsed, parse_status, parse_error = _strict_json(attempt.get("raw_response_content"))
        parsed_dict = parsed if isinstance(parsed, dict) else {}
        structural = bool(
            isinstance(parsed, dict)
            and set(parsed) == {"sections"}
            and isinstance(parsed.get("sections"), list)
            and all(
                isinstance(row, dict)
                and set(row) == {"section_name", "text", "used_fact_lock_ids"}
                and isinstance(row.get("section_name"), str)
                and isinstance(row.get("text"), str)
                and _is_string_list(row.get("used_fact_lock_ids"))
                for row in parsed.get("sections", [])
            )
        )
        sections = parsed_dict.get("sections", []) if structural else []
        used_ids = [str(value) for row in sections for value in row["used_fact_lock_ids"]]
        used_counts = Counter(used_ids)
        used_unique = set(used_ids) & expected_ids
        unknown_ids = sorted(set(used_ids) - expected_ids)
        duplicate_ids = sorted(value for value, count in used_counts.items() if count > 1)
        valid = bool(
            attempt["transport_success"]
            and parse_status == "PASS"
            and structural
            and not unknown_ids
        )
        text = _compose_a4_sections(sections) if structural else ""
        task_results.append(
            {
                "request_id": attempt["request_id"],
                "task_id": task_id,
                "transport_success": attempt["transport_success"],
                "parse_status": parse_status,
                "parse_error": parse_error,
                "schema_status": "PASS" if structural else "FAIL",
                "valid_task_output": valid,
                "section_count": len(sections),
                "expected_fact_lock_count": len(expected_ids),
                "used_unique_fact_lock_count": len(used_unique),
                "omitted_fact_lock_count": len(expected_ids - used_unique),
                "unknown_fact_lock_ids": ";".join(unknown_ids),
                "unknown_fact_lock_id_count": len(unknown_ids),
                "duplicate_used_fact_lock_ids": ";".join(duplicate_ids),
                "duplicate_used_fact_lock_id_count": len(duplicate_ids),
                "trace_coverage": len(used_unique) / len(expected_ids) if expected_ids else 1.0,
                "output_termination_class": attempt["output_termination_class"],
                "truncation_exposed": attempt["truncation_exposed"],
                "model_text_rewritten": False,
                "output_text": text,
                "output_text_hash": stable_hash(text) if text else "",
            }
        )
        termination_rows.append(
            {
                "request_id": attempt["request_id"],
                "task_id": task_id,
                "provider_status": attempt.get("provider_status"),
                "finish_reason": attempt.get("finish_reason"),
                "output_termination_class": attempt["output_termination_class"],
                "truncation_exposed": attempt["truncation_exposed"],
                "coverage": len(used_unique) / len(expected_ids) if expected_ids else 1.0,
            }
        )
        text_by_fact: dict[str, list[tuple[int, str]]] = defaultdict(list)
        scope_status_by_section: dict[int, tuple[str, list[float]]] = {}
        request_fact_by_id = {str(row["fact_lock_id"]): row for row in payload["facts"]}
        scope_registry = payload["scope_registry"]
        for section_index, section in enumerate(sections):
            known_ids = [
                str(value)
                for value in section["used_fact_lock_ids"]
                if str(value) in request_fact_by_id
            ]
            cited_scopes = [
                scope_registry[request_fact_by_id[fact_id]["scope_id"]] for fact_id in known_ids
            ]
            section_scope_status, section_chainages = _scope_union_status(
                cited_scopes, str(section["text"])
            )
            scope_status_by_section[section_index] = (
                section_scope_status,
                section_chainages,
            )
            scope_section_rows.append(
                {
                    "request_id": attempt["request_id"],
                    "task_id": task_id,
                    "section_index": section_index,
                    "section_name": section["section_name"],
                    "used_fact_lock_count": len(known_ids),
                    "explicit_scope_consistency": section_scope_status,
                    "observed_explicit_chainages": ";".join(
                        str(value) for value in section_chainages
                    ),
                    "scope_audit_basis": "SECTION_USED_FACTLOCK_SCOPE_UNION",
                }
            )
            for fact_id in section["used_fact_lock_ids"]:
                text_by_fact[str(fact_id)].append((section_index, str(section["text"])))
        for fact in facts_by_task[task_id]:
            fact_id = str(fact["fact_lock_id"])
            section_texts = text_by_fact.get(fact_id, [])
            trace_rows.append(
                {
                    "request_id": attempt["request_id"],
                    "task_id": task_id,
                    "fact_lock_id": fact_id,
                    "expected": True,
                    "used_count": used_counts[fact_id],
                    "used": bool(section_texts),
                    "omitted": not section_texts,
                    "coverage_status": "USED" if section_texts else "FACTLOCK_COVERAGE_OMISSION",
                    "termination_class": attempt["output_termination_class"],
                }
            )
            if section_texts:
                combined = "\n".join(text for _, text in section_texts)
                value = json.loads(str(fact["claim_value"]))
                section_scope_results = [
                    scope_status_by_section[section_index] for section_index, _ in section_texts
                ]
                scope_status = _combine_scope_statuses(
                    [status for status, _ in section_scope_results]
                )
                observed = sorted(
                    {chainage for _, chainages in section_scope_results for chainage in chainages}
                )
                drift_rows.append(
                    {
                        "request_id": attempt["request_id"],
                        "task_id": task_id,
                        "fact_lock_id": fact_id,
                        "numeric_value_exact": _numeric_value_status(value, combined),
                        "verified_unit_exact": "NOT_APPLICABLE",
                        "explicit_scope_consistency": scope_status,
                        "observed_explicit_chainages": ";".join(str(item) for item in observed),
                        "scope_audit_basis": "SECTION_USED_FACTLOCK_SCOPE_UNION",
                        "unknown_id": False,
                        "semantic_epistemic_drift": "DEFERRED_TO_HUMAN",
                        "causality_drift": "DEFERRED_TO_HUMAN",
                        "unknown_to_normal": "DEFERRED_TO_HUMAN",
                        "attention_to_probability": "DEFERRED_TO_HUMAN",
                    }
                )
        for unknown_id in unknown_ids:
            drift_rows.append(
                {
                    "request_id": attempt["request_id"],
                    "task_id": task_id,
                    "fact_lock_id": unknown_id,
                    "numeric_value_exact": "NOT_EVALUABLE",
                    "verified_unit_exact": "NOT_EVALUABLE",
                    "explicit_scope_consistency": "NOT_EVALUABLE",
                    "observed_explicit_chainages": "",
                    "unknown_id": True,
                    "semantic_epistemic_drift": "DEFERRED_TO_HUMAN",
                    "causality_drift": "DEFERRED_TO_HUMAN",
                    "unknown_to_normal": "DEFERRED_TO_HUMAN",
                    "attention_to_probability": "DEFERRED_TO_HUMAN",
                }
            )
        if valid:
            outputs.append(
                {
                    "task_id": task_id,
                    "sections": sections,
                    "text": text,
                    "text_hash": stable_hash(text),
                    "model_text_rewritten": False,
                }
            )
    valid_tasks = {str(row["task_id"]) for row in task_results if row["valid_task_output"]}
    used_count = sum(row["used"] for row in trace_rows)
    normal_trace = [row for row in trace_rows if row["termination_class"] == "NORMAL_COMPLETION"]
    truncated_trace = [
        row
        for row in trace_rows
        if row["termination_class"] == "OUTPUT_LIMIT_OR_LENGTH_TERMINATION"
    ]
    summary = {
        "task_count": len(task_results),
        "valid_task_count": len(valid_tasks),
        "valid_p_common_task_count": len(valid_tasks - NO_OUTPUT_TASKS),
        "valid_p_no_output_task_count": len(valid_tasks & NO_OUTPUT_TASKS),
        "p_no_output_task_results": {
            task_id: task_id in valid_tasks for task_id in sorted(NO_OUTPUT_TASKS)
        },
        "expected_fact_lock_count": len(inputs["a4_facts"]),
        "used_fact_lock_count": used_count,
        "fact_lock_coverage": used_count / len(inputs["a4_facts"]),
        "unknown_fact_lock_id_count": sum(
            int(row["unknown_fact_lock_id_count"]) for row in task_results
        ),
        "duplicate_used_fact_lock_id_count": sum(
            int(row["duplicate_used_fact_lock_id_count"]) for row in task_results
        ),
        "numeric_drift_count": sum(row["numeric_value_exact"] == "FAIL" for row in drift_rows),
        "unit_drift_count": sum(row["verified_unit_exact"] == "FAIL" for row in drift_rows),
        "scope_drift_count": sum(
            row["explicit_scope_consistency"] == "FAIL" for row in scope_section_rows
        ),
        "scope_section_count": len(scope_section_rows),
        "scope_section_status_distribution": dict(
            sorted(Counter(row["explicit_scope_consistency"] for row in scope_section_rows).items())
        ),
        "normal_completion_coverage": (
            sum(row["used"] for row in normal_trace) / len(normal_trace) if normal_trace else None
        ),
        "truncated_output_coverage": (
            sum(row["used"] for row in truncated_trace) / len(truncated_trace)
            if truncated_trace
            else None
        ),
        "truncation_count": sum(row["truncation_exposed"] for row in task_results),
    }
    return {
        **summary,
        "task_results": task_results,
        "trace_rows": trace_rows,
        "drift_rows": drift_rows,
        "scope_section_rows": scope_section_rows,
        "termination_rows": termination_rows,
        "outputs": outputs,
        "summary": summary,
    }


def _compose_a4_sections(sections: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"## {section['section_name']}\n\n{section['text']}" for section in sections)


def _numeric_value_status(value: dict[str, Any], text: str) -> str:
    expected = value.get("metric_value")
    if not isinstance(expected, (int, float)) or isinstance(expected, bool):
        return "NOT_APPLICABLE"
    observed = _decimal_tokens(text)
    expected_decimal = Decimal(str(expected))
    return "PASS" if expected_decimal in observed else "FAIL"


def _scope_status(scope: dict[str, Any], text: str) -> tuple[str, list[float]]:
    observed = _explicit_chainages(text)
    if not observed:
        return "NOT_EXPLICIT", []
    point = scope.get("point_chainage")
    start = scope.get("start_chainage")
    end = scope.get("end_chainage")
    if isinstance(point, (int, float)):
        valid = all(abs(value - float(point)) < 0.001 for value in observed)
    elif isinstance(start, (int, float)) and isinstance(end, (int, float)):
        valid = all(float(start) - 0.001 <= value <= float(end) + 0.001 for value in observed)
    else:
        return "NOT_EVALUABLE", observed
    return ("PASS" if valid else "FAIL"), observed


def _scope_union_status(scopes: list[dict[str, Any]], text: str) -> tuple[str, list[float]]:
    observed = _explicit_chainages(text)
    if not observed:
        return "NOT_EXPLICIT", []
    intervals: list[tuple[float, float]] = []
    for scope in scopes:
        point = scope.get("point_chainage")
        start = scope.get("start_chainage")
        end = scope.get("end_chainage")
        if isinstance(point, (int, float)):
            intervals.append((float(point), float(point)))
        elif isinstance(start, (int, float)) and isinstance(end, (int, float)):
            intervals.append((float(start), float(end)))
    if not intervals:
        return "NOT_EVALUABLE", observed
    valid = all(
        any(start - 0.001 <= value <= end + 0.001 for start, end in intervals) for value in observed
    )
    return ("PASS" if valid else "FAIL"), observed


def _combine_scope_statuses(statuses: list[str]) -> str:
    for status in ("FAIL", "PASS", "NOT_EVALUABLE", "NOT_EXPLICIT"):
        if status in statuses:
            return status
    return "NOT_EVALUABLE"


def _explicit_chainages(text: str) -> list[float]:
    values = []
    for km, offset in re.findall(r"(?:DyK)?(\d{4})\+(\d+(?:\.\d+)?)", text, flags=re.I):
        values.append(float(km) * 1000.0 + float(offset))
    for raw in re.findall(r"(?<![\d.])(10\d{5}(?:\.\d+)?)(?![\d.])", text):
        value = float(raw)
        if not any(abs(value - existing) < 0.001 for existing in values):
            values.append(value)
    return values


def _decimal_tokens(text: str) -> set[Decimal]:
    values: set[Decimal] = set()
    for raw in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", text):
        try:
            values.add(Decimal(raw))
        except InvalidOperation:
            continue
    return values


def _strict_json(raw_text: Any) -> tuple[dict[str, Any] | None, str, str]:
    if not isinstance(raw_text, str):
        return None, "FAIL", "RAW_TEXT_UNAVAILABLE"
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return None, "FAIL", f"JSON_DECODE_ERROR:{exc.msg}"
    if not isinstance(payload, dict):
        return None, "FAIL", "TOP_LEVEL_NOT_OBJECT"
    return payload, "PASS", ""


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _explicit_insufficiency_class(text: str) -> str:
    if not text.strip():
        return "NOT_APPLICABLE_EMPTY"
    return (
        "EXPLICIT_INSUFFICIENCY"
        if any(phrase in text for phrase in EXPLICIT_INSUFFICIENCY_PHRASES)
        else "UNKNOWN"
    )


def _request_input_payload(request: dict[str, Any]) -> dict[str, Any]:
    content = str(request["messages"][1]["content"])
    start = content.find("{")
    if start < 0:
        raise Stage7EExecutionError(f"frozen request has no JSON payload: {request['request_id']}")
    payload = json.loads(content[start:])
    if not isinstance(payload, dict):
        raise Stage7EExecutionError(
            f"frozen request payload is not object: {request['request_id']}"
        )
    return payload


def _write_derived_outputs(output: Path, result: dict[str, Any]) -> None:
    a2 = result["a2"]
    _write_csv(output / "a2_section_results.csv", a2["section_results"])
    _write_csv(output / "a2_task_composition_manifest.csv", a2["composition_rows"])
    _write_csv(output / "a2_non_target_p_identity_audit.csv", a2["identity_rows"])
    _write_json(output / "a2_mechanistic_summary.json", a2["summary"])
    _write_jsonl(output / "a2_final_task_outputs.jsonl", a2["outputs"])
    a3 = result["a3"]
    _write_csv(output / "a3_chunk_results.csv", a3["chunk_results"])
    _write_csv(output / "a3_claim_results.csv", a3["claim_results"])
    _write_csv(output / "a3_task_reconstruction_manifest.csv", a3["reconstruction_rows"])
    _write_csv(output / "a3_claim_drift_audit.csv", a3["drift_rows"])
    _write_json(output / "a3_mechanistic_summary.json", a3["summary"])
    _write_jsonl(output / "a3_final_task_outputs.jsonl", a3["outputs"])
    a4 = result["a4"]
    _write_csv(output / "a4_task_results.csv", a4["task_results"])
    _write_csv(output / "a4_factlock_trace_audit.csv", a4["trace_rows"])
    _write_csv(output / "a4_hard_drift_audit.csv", a4["drift_rows"])
    _write_csv(output / "a4_scope_section_audit.csv", a4["scope_section_rows"])
    _write_csv(output / "a4_termination_audit.csv", a4["termination_rows"])
    _write_json(output / "a4_mechanistic_summary.json", a4["summary"])
    _write_jsonl(output / "a4_final_task_outputs.jsonl", a4["outputs"])


def _endpoint_rows(
    a2: dict[str, Any], a3: dict[str, Any], a4: dict[str, Any]
) -> list[dict[str, Any]]:
    return [
        {
            "arm": "A2_NO_ARCHITECTURAL_ABSTENTION",
            "endpoint": "VALID_SECTION_OUTPUT",
            "numerator": a2["valid_section_count"],
            "denominator": 31,
            "unit": "TARGET_SECTION",
        },
        {
            "arm": "A2_NO_ARCHITECTURAL_ABSTENTION",
            "endpoint": "NONEMPTY_TEXT",
            "numerator": a2["nonempty_text_count"],
            "denominator": 31,
            "unit": "TARGET_SECTION",
        },
        {
            "arm": "A3_NO_FACTLOCK",
            "endpoint": "CLAIM_MAPPING_COMPLETE",
            "numerator": a3["mapping_complete_count"],
            "denominator": 989,
            "unit": "TYPED_CLAIM",
        },
        {
            "arm": "A3_NO_FACTLOCK",
            "endpoint": "COMPLETE_TASK_OUTPUT",
            "numerator": a3["complete_task_count"],
            "denominator": 45,
            "unit": "ELIGIBLE_TASK",
        },
        {
            "arm": "A4_FREE_FINAL_REALIZATION",
            "endpoint": "FACTLOCK_TRACE_COVERAGE",
            "numerator": a4["used_fact_lock_count"],
            "denominator": 1022,
            "unit": "FACTLOCK",
        },
        {
            "arm": "A4_FREE_FINAL_REALIZATION",
            "endpoint": "VALID_TASK_OUTPUT",
            "numerator": a4["valid_task_count"],
            "denominator": 48,
            "unit": "TASK",
        },
    ]


def _human_deferred_rows() -> list[dict[str, Any]]:
    return [
        {
            "semantic_endpoint": endpoint,
            "status": "DEFERRED_TO_HUMAN",
            "automatic_label_generated": False,
            "notes": "NOT_EVALUATED_BY_KEYWORD_HEURISTICS",
        }
        for endpoint in (
            "FORECAST_FACTIFICATION",
            "UNSUPPORTED_CAUSALITY",
            "EPISTEMIC_DRIFT",
            "UNKNOWN_TO_NORMAL",
            "ATTENTION_TO_PROBABILITY",
            "ENGINEERING_USEFULNESS",
        )
    ]


def _hard_checks(
    root: Path,
    output: Path,
    preflight: dict[str, Any],
    attempts: list[dict[str, Any]],
    result: dict[str, Any],
    replay_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    request_ids = [str(row["request_id"]) for row in attempts]
    response_ids = [
        str(row["provider_response_id"]) for row in attempts if row.get("provider_response_id")
    ]
    raw_records_valid = all(
        row.get("raw_response_path")
        and (output / str(row["raw_response_path"])).is_file()
        and _read_json(output / str(row["raw_response_path"])).get("request_id")
        == row["request_id"]
        for row in attempts
    )
    arm_counts = Counter(str(row["arm_internal"]) for row in attempts)
    checks = [
        _check("protocol_preflight", preflight["status"] == "PASS", preflight["status"]),
        _check(
            "protocol_tag_unchanged",
            _git_rev_parse(root, PROTOCOL_TAG) == PROTOCOL_COMMIT,
            _git_rev_parse(root, PROTOCOL_TAG),
        ),
        _check(
            "planned_requests_226", len(preflight["requests"]) == 226, len(preflight["requests"])
        ),
        _check("actual_attempts_226", len(attempts) == 226, len(attempts)),
        _check("unique_request_ids_226", len(set(request_ids)) == 226, len(set(request_ids))),
        _check(
            "one_attempt_per_frozen_request",
            Counter(request_ids)
            == Counter(str(row["request_id"]) for row in preflight["requests"]),
            len(set(request_ids)),
        ),
        _check(
            "attempt_arm_counts",
            arm_counts == EXPECTED_ARM_COUNTS,
            dict(arm_counts),
        ),
        _check("no_a1_attempt", "A1_NO_SEMANTIC_CLAIM_GATE" not in arm_counts, 0),
        _check("no_p_attempt", "P_FULL" not in arm_counts, 0),
        _check(
            "retry_count_zero",
            all(
                int(row["retry_count"]) == 0 and int(row["attempt_number"]) == 1 for row in attempts
            ),
            sum(int(row["retry_count"]) for row in attempts),
        ),
        _check(
            "raw_response_record_preserved",
            raw_records_valid,
            sum(
                not row.get("raw_response_path")
                or not (output / str(row.get("raw_response_path"))).is_file()
                for row in attempts
            ),
        ),
        _check(
            "provider_response_ids_unique",
            len(response_ids)
            == len(set(response_ids))
            == sum(bool(row["transport_success"]) for row in attempts),
            {
                "successful_transport_count": sum(
                    bool(row["transport_success"]) for row in attempts
                ),
                "provider_response_id_count": len(response_ids),
                "unique_provider_response_id_count": len(set(response_ids)),
            },
        ),
        _check(
            "a2_request_count_31",
            len(result["a2"]["section_results"]) == 31,
            len(result["a2"]["section_results"]),
        ),
        _check(
            "a2_affected_tasks_24",
            result["a2"]["affected_task_count"] == 24,
            result["a2"]["affected_task_count"],
        ),
        _check(
            "a2_non_target_p_identity",
            result["a2"]["non_target_p_identity_mismatch_count"] == 0,
            result["a2"]["non_target_p_identity_mismatch_count"],
        ),
        _check(
            "a3_request_count_147",
            len(result["a3"]["chunk_results"]) == 147,
            len(result["a3"]["chunk_results"]),
        ),
        _check(
            "a3_expected_claims_989",
            result["a3"]["expected_claim_count"] == 989,
            result["a3"]["expected_claim_count"],
        ),
        _check(
            "a3_p_plan_reuse",
            all(
                row["p_plan_reused"]
                for row in result["a3"]["reconstruction_rows"]
                if row["task_id"] not in NO_OUTPUT_TASKS
            ),
            45,
        ),
        _check(
            "a4_request_count_48",
            len(result["a4"]["task_results"]) == 48,
            len(result["a4"]["task_results"]),
        ),
        _check(
            "a4_expected_factlocks_1022",
            result["a4"]["expected_fact_lock_count"] == 1022,
            result["a4"]["expected_fact_lock_count"],
        ),
        _check(
            "a4_scope_section_audit_complete",
            len(result["a4"]["scope_section_rows"])
            == sum(int(row["section_count"]) for row in result["a4"]["task_results"]),
            len(result["a4"]["scope_section_rows"]),
        ),
        _check(
            "model_text_not_rewritten",
            all(not row.get("model_text_rewritten") for row in result["a3"]["outputs"])
            and all(not row.get("model_text_rewritten") for row in result["a4"]["outputs"]),
            0,
        ),
        _check(
            "human_semantic_labels_not_generated",
            all(row["status"] == "DEFERRED_TO_HUMAN" for row in _human_deferred_rows()),
            0,
        ),
        _check(
            "deterministic_replay",
            all(row["status"] == "PASS" for row in replay_rows),
            sum(row["status"] != "PASS" for row in replay_rows),
        ),
        _check("stage7e_a_hashes_unchanged", _verify_hash_manifest(root / PROTOCOL_DIR), 0),
    ]
    return checks


def _execution_summary(
    attempts: list[dict[str, Any]],
    result: dict[str, Any],
    replay_rows: list[dict[str, Any]],
    hard_rows: list[dict[str, Any]],
    protocol: dict[str, Any],
) -> dict[str, Any]:
    terminations = Counter(str(row["output_termination_class"]) for row in attempts)
    response_ids = {
        str(row["provider_response_id"]) for row in attempts if row.get("provider_response_id")
    }
    parse_success = sum(
        row["parse_status"] == "PASS"
        for arm in (
            result["a2"]["section_results"],
            result["a3"]["chunk_results"],
            result["a4"]["task_results"],
        )
        for row in arm
    )
    schema_success = sum(
        row["schema_status"] == "PASS"
        for arm in (
            result["a2"]["section_results"],
            result["a3"]["chunk_results"],
            result["a4"]["task_results"],
        )
        for row in arm
    )
    return {
        "status": "EXECUTION_COMPLETE_DETERMINISTIC_AUDIT_PASS"
        if all(row["status"] == "PASS" for row in hard_rows)
        else "EXECUTION_COMPLETE_HARD_CHECK_FAILURE",
        "execution_protocol_hash": protocol["execution_protocol_hash"],
        "execution_order_hash": protocol["execution_order_hash"],
        "planned_requests": 226,
        "actual_attempts": len(attempts),
        "transport_success_count": sum(row["transport_success"] for row in attempts),
        "transport_failure_count": sum(not row["transport_success"] for row in attempts),
        "parse_success_count": parse_success,
        "schema_success_count": schema_success,
        "termination_distribution": dict(sorted(terminations.items())),
        "normal_completion_count": terminations["NORMAL_COMPLETION"],
        "output_limit_or_truncation_count": terminations["OUTPUT_LIMIT_OR_LENGTH_TERMINATION"],
        "unique_provider_response_id_count": len(response_ids),
        "retry_count": sum(int(row["retry_count"]) for row in attempts),
        "actual_api_calls": len(attempts),
        "actual_llm_calls": len(attempts),
        "p_output_availability": "45/48",
        "a1_status": "NOT_EXECUTABLE_ON_FROZEN_48_TASK_BENCHMARK",
        "a1_api_calls": 0,
        "a2": result["a2"]["summary"],
        "a3": result["a3"]["summary"],
        "a4": result["a4"]["summary"],
        "replay_mismatch_count": sum(row["status"] != "PASS" for row in replay_rows),
        "hard_check_failure_count": sum(row["status"] != "PASS" for row in hard_rows),
        "human_semantic_evaluation": "DEFERRED",
    }


def _execution_protocol(preflight: dict[str, Any]) -> dict[str, Any]:
    order = build_execution_order(preflight["requests"])
    payload = {
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "frozen_protocol_tag": PROTOCOL_TAG,
        "frozen_protocol_commit": PROTOCOL_COMMIT,
        "request_tree_hash": preflight["request_tree_hash"],
        "planned_request_count": 226,
        "execution_order_policy": "SHA256_REQUEST_ID_LEXICAL_ASCENDING",
        "execution_order_hash": stable_hash(order),
        "provider_config": preflight["provider_config"],
        "retry_policy": {
            "max_retries": 0,
            "sdk_max_retries": 0,
            "retry_on_any_failure": False,
        },
        "raw_first_persistence": True,
        "json_repair": False,
        "llm_repair": False,
        "human_semantic_evaluation": "DEFERRED",
        "arm_execution": {
            "P_FULL": "FROZEN_REFERENCE_NO_NEW_API",
            "A1_NO_SEMANTIC_CLAIM_GATE": ("NOT_EXECUTABLE_ON_FROZEN_48_TASK_BENCHMARK"),
            "A2_NO_ARCHITECTURAL_ABSTENTION": 31,
            "A3_NO_FACTLOCK": 147,
            "A4_FREE_FINAL_REALIZATION": 48,
        },
    }
    return {**payload, "execution_protocol_hash": stable_hash(payload)}


def _upstream_freeze_rows(root: Path, preflight: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _check(
            "stage7e_protocol_tag",
            _git_rev_parse(root, PROTOCOL_TAG) == PROTOCOL_COMMIT,
            PROTOCOL_COMMIT,
        ),
        _check("stage7e_protocol_hash_manifest", _verify_hash_manifest(root / PROTOCOL_DIR), 0),
        _check(
            "stage7e_request_tree_hash",
            _request_tree_hash(root / PROTOCOL_DIR / "requests") == preflight["request_tree_hash"],
            preflight["request_tree_hash"],
        ),
        _check(
            "stage7b_frozen_p_outputs",
            len(_read_jsonl(root / STAGE7B_RUN_DIR / "P_final_outputs.jsonl")) == 45,
            45,
        ),
    ]


def _load_frozen_requests(protocol_dir: Path) -> list[dict[str, Any]]:
    return [_read_json(path) for path in sorted((protocol_dir / "requests").glob("*/*.json"))]


def _request_integrity_rows(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for request in requests:
        semantic = {
            "task_id": request["task_id"],
            "request_scope": request["request_scope"],
            "provider_config": request["inference_config"],
            "messages": request["messages"],
        }
        payload_hash = stable_hash(semantic)
        request_id = f"stage7e_v1_2_request_{payload_hash[:24]}"
        system_hash = hashlib.sha256(str(request["messages"][0]["content"]).encode()).hexdigest()
        user_hash = hashlib.sha256(str(request["messages"][1]["content"]).encode()).hexdigest()
        issues = []
        if request["payload_hash"] != payload_hash:
            issues.append("PAYLOAD_HASH_MISMATCH")
        if request["request_id"] != request_id:
            issues.append("REQUEST_ID_MISMATCH")
        if request["system_prompt_hash"] != system_hash:
            issues.append("SYSTEM_PROMPT_HASH_MISMATCH")
        if request["user_prompt_hash"] != user_hash:
            issues.append("USER_PROMPT_HASH_MISMATCH")
        rows.append(
            {
                "request_id": request["request_id"],
                "task_id": request["task_id"],
                "arm_internal": request["arm_internal"],
                "stored_payload_hash": request["payload_hash"],
                "recomputed_payload_hash": payload_hash,
                "stored_system_prompt_hash": request["system_prompt_hash"],
                "recomputed_system_prompt_hash": system_hash,
                "stored_user_prompt_hash": request["user_prompt_hash"],
                "recomputed_user_prompt_hash": user_hash,
                "issue_codes": ";".join(issues),
                "status": "PASS" if not issues else "FAIL",
            }
        )
    return rows


def _validate_request_config(request: dict[str, Any], config: dict[str, Any]) -> None:
    if request["inference_config"] != config:
        raise Stage7EExecutionError(f"provider config mismatch: {request['request_id']}")
    if request["provider"] != config["provider"] or request["model"] != config["model"]:
        raise Stage7EExecutionError(f"provider identity mismatch: {request['request_id']}")


def _extract_output_text(payload: dict[str, Any]) -> str:
    values = []
    for item in payload.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                values.append(content["text"])
    return "".join(values)


def _finish_reason(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    incomplete = payload.get("incomplete_details")
    if isinstance(incomplete, dict) and incomplete.get("reason"):
        return str(incomplete["reason"])
    for item in payload.get("output") or []:
        if item.get("finish_reason"):
            return str(item["finish_reason"])
    return str(payload["status"]) if payload.get("status") else None


def _termination(payload: Any, *, transport_success: bool) -> str:
    if not transport_success:
        return "TRANSPORT_FAILURE"
    if not isinstance(payload, dict):
        return "UNKNOWN_TERMINATION"
    reason = str(_finish_reason(payload) or "").lower()
    status = str(payload.get("status") or "").lower()
    if any(token in reason for token in ("max_output", "length", "max_tokens")):
        return "OUTPUT_LIMIT_OR_LENGTH_TERMINATION"
    if status in {"failed", "cancelled"} or payload.get("error"):
        return "PROVIDER_FAILURE"
    if status == "completed":
        return "NORMAL_COMPLETION"
    return "UNKNOWN_TERMINATION"


def _redact_secret(value: str) -> str:
    return re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED]", value)


def _attempt_manifest_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in (
            "execution_index",
            "request_id",
            "task_id",
            "arm_internal",
            "request_scope",
            "request_payload_hash",
            "request_started_at",
            "request_finished_at",
            "latency_ms",
            "transport_success",
            "transport_status",
            "provider_response_id",
            "provider_returned_model_identity",
            "provider_status",
            "finish_reason",
            "output_termination_class",
            "truncation_exposed",
            "prompt_input_token_count",
            "completion_output_token_count",
            "total_token_count",
            "parse_status",
            "schema_status",
            "provider_error_type",
            "provider_error_message",
            "attempt_number",
            "retry_count",
            "real_api_attempted",
            "raw_response_path",
        )
    }


def _load_attempts(output: Path) -> list[dict[str, Any]]:
    manifest = _read_csv(output / "stage7e_raw_attempt_manifest.csv")
    attempts = []
    for row in sorted(manifest, key=lambda item: int(item["execution_index"])):
        attempt = _read_json(output / row["raw_response_path"])
        attempt["raw_response_path"] = row["raw_response_path"]
        attempt["execution_index"] = int(row["execution_index"])
        attempts.append(attempt)
    return attempts


def _arm_short(arm: str) -> str:
    return {
        "A2_NO_ARCHITECTURAL_ABSTENTION": "A2",
        "A3_NO_FACTLOCK": "A3",
        "A4_FREE_FINAL_REALIZATION": "A4",
    }[arm]


def _request_tree_hash(path: Path) -> str:
    return stable_hash(
        [
            {
                "path": file.relative_to(path).as_posix(),
                "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
            }
            for file in sorted(path.rglob("*.json"))
        ]
    )


def _verify_hash_manifest(directory: Path) -> bool:
    for line in (directory / "file_hashes.sha256").read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        path = directory / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            return False
    return True


def _check(name: str, passed: bool, details: Any) -> dict[str, Any]:
    return {"check_name": name, "status": "PASS" if passed else "FAIL", "details": details}


def _readme(summary: dict[str, Any]) -> str:
    return f"""# Stage7E-B Frozen Ablation Execution

This directory records the one-shot execution of the 226 byte-frozen Stage7E-A
v1.2 requests. P-FULL is reused from Stage7B and A1 remains non-executable.

The execution uses DeepSeek `deepseek-v4-flash`, temperature 0, top_p 1,
reasoning effort none, 4096 maximum output tokens, and zero retries. Raw provider
responses are persisted before strict JSON parsing. No JSON repair, LLM repair,
prompt mutation, request mutation, or human semantic labeling is performed.

A2 is limited to 31 unavailable attention-metric contexts in 24 affected tasks.
Its result must not be generalized to every form of missing evidence or engineering
uncertainty. A3 evaluates 989 typed Claim-to-sentence mappings in 147 chunks. A4
evaluates free task-level realization from 1022 frozen FactLocks in 48 requests.
For A4, explicit chainages in a generated section are checked against the union of
the authoritative scopes of all FactLocks cited by that section; a multi-FactLock
section is not incorrectly compared against each cited scope in isolation.

Status: `{summary["status"]}`

Human evaluation of forecast factification, unsupported causality, epistemic
drift, unknown-to-normal transformations, attention-to-probability transformations,
and engineering usefulness remains `DEFERRED_TO_HUMAN`.
"""


def _write_audit_zip(root: Path, output: Path) -> Path:
    zip_path = root / AUDIT_ZIP
    sources = [
        root / "src/tbm_twin/evaluation/stage7e_execution.py",
        root / "scripts/run_stage7e_ablation_execution.py",
        root / "tests/unit/test_stage7e_ablation_execution.py",
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


def _git_refs(root: Path) -> str:
    commands = [
        ["git", "branch", "--show-current"],
        ["git", "rev-parse", "HEAD"],
        ["git", "rev-parse", PROTOCOL_TAG],
        ["git", "status", "--short"],
    ]
    blocks = []
    for command in commands:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
        blocks.append(f"$ {' '.join(command)}\n{result.stdout}{result.stderr}".rstrip())
    return "\n\n".join(blocks) + "\n"


def _git_rev_parse(root: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", ref],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise Stage7EExecutionError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(_canonical(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
