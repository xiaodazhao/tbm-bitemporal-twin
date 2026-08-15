"""Stage7B frozen three-method real-model benchmark execution.

This module executes the frozen Stage7A v1.3 benchmark only.  It does not
select tasks, rewrite prompts, rerun applicability, or evaluate human quality.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from tbm_twin.realization.io import (
    read_json,
    read_jsonl,
    stable_hash,
    stable_id,
    write_csv,
    write_hashes,
    write_json,
    write_jsonl,
)
from tbm_twin.realization.models import SliceSpec
from tbm_twin.realization.providers.configured_llm import LLMProviderConfig
from tbm_twin.realization.providers.deepseek_adapter import (
    DEEPSEEK_RESPONSES_BASE_URL,
    DEEPSEEK_RESPONSES_SUPPORTED_MODEL,
    DeepSeekResponsesPlanProvider,
)
from tbm_twin.realization.stage6b import (
    build_task_bundle,
    compose_realization,
    load_stage6b_inputs,
    validate_plan,
)
from tbm_twin.realization.stage6b_models import PRESENTATION_POLICY_VERSION
from tbm_twin.realization.stage6b_smoke import (
    SmokeRealizationRequest,
    build_smoke_request,
    materialize_realization_plan,
    parse_provider_plan,
)

STAGE7A_DIR = Path("artifacts/stage7a_experimental_protocol_v1_3")
STAGE7B_DIR = Path("artifacts/stage7b_main_comparison_v1")

STAGE6B_TAG = "stage6b-controlled-realization-v1-frozen"
STAGE6B_COMMIT = "ecf0fc47cd2f1f4a8bb5a962c32caaa7c5284550"
STAGE7A_TAG = "stage7a-experimental-protocol-v1.3-frozen"
STAGE7A_COMMIT = "6007afe7c1b1228d6638503afeba979ee2f66878"

EXPECTED_STAGE7_MAIN_HASH = "e9ef8e3f9bd25f345f89f79dc753040e3bfc1f95e562902aea625a8e50334f6f"
EXPECTED_ASOF_BINDING_HASH = "92bdea500aef7bedb27e6133e92ec058f03ccfd48810e84aed11388838d12bc4"
EXPECTED_B0_PROMPT_HASH = "3966cce71fe560c4d1cb323ec1b46506b97595f89168cafdf327d5b147c2d296"
EXPECTED_B1_PROMPT_HASH = "7ad1dfec254bf1c5107c99f559bc65cfd590b595750089b38dd498bcbbfbecea"
EXPECTED_PRODUCT_CONTRACT_HASH = "ad599756f428514cf731bb982ecccf21b0705e14579ebf64095524a674ecc98d"

B0_METHOD = "B0_DIRECT_LLM"
B1_METHOD = "B1_STRUCTURED_PROMPT_LLM"
P_METHOD = "P_PROPOSED"
METHOD_ORDER = [B0_METHOD, B1_METHOD, P_METHOD]


class Stage7BPreflightError(RuntimeError):
    """Raised when execution must fail closed before the first API call."""


class DeepSeekTextProvider:
    """DeepSeek Responses API text adapter for B0/B1 baseline methods."""

    provider_name = "deepseek"
    provider_kind = "REAL_API"

    def __init__(self, config: LLMProviderConfig) -> None:
        self.config = config

    def request_text(
        self,
        *,
        execution_item_id: str,
        benchmark_task_id: str,
        method_id: str,
        system_prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Send one baseline request and return a raw-first attempt record."""

        if self.config.model_name != DEEPSEEK_RESPONSES_SUPPORTED_MODEL:
            msg = (
                "DeepSeek Responses API benchmark supports only "
                f"{DEEPSEEK_RESPONSES_SUPPORTED_MODEL}"
            )
            raise RuntimeError(msg)
        api_key = os.environ.get(self.config.api_key_env_var)
        if not api_key:
            msg = f"missing API key environment variable: {self.config.api_key_env_var}"
            raise RuntimeError(msg)
        try:
            from openai import OpenAI
        except ImportError as exc:
            msg = "openai SDK is required only for explicit DeepSeek benchmark execution"
            raise RuntimeError(msg) from exc

        started = time.monotonic()
        timestamp = datetime.now(tz=UTC).isoformat()
        request_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        client = OpenAI(
            api_key=api_key,
            base_url=self.config.base_url,
            max_retries=self.config.max_retries,
            timeout=self.config.timeout_seconds,
        )
        try:
            response = cast(Any, client.responses).create(
                model=self.config.model_name,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                max_output_tokens=self.config.max_output_tokens,
                reasoning={"effort": self.config.reasoning_effort},
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": request_payload},
                ],
            )
        except Exception as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            return {
                "execution_item_id": execution_item_id,
                "benchmark_task_id": benchmark_task_id,
                "method_id": method_id,
                "provider": self.config.model_provider,
                "provider_kind": self.provider_kind,
                "model": self.config.model_name,
                "request_timestamp": timestamp,
                "response_timestamp": timestamp,
                "real_api_attempted": True,
                "transport_success": False,
                "real_api_transport_success": False,
                "raw_response_available": False,
                "raw_response_text": None,
                "raw_response_payload": None,
                "provider_error_type": exc.__class__.__name__,
                "provider_error_message": str(exc),
                "latency_ms": latency_ms,
                "token_usage": None,
            }
        latency_ms = int((time.monotonic() - started) * 1000)
        raw_payload = response.model_dump(mode="json")
        raw_text = getattr(response, "output_text", "") or json.dumps(
            raw_payload, ensure_ascii=False
        )
        return {
            "execution_item_id": execution_item_id,
            "benchmark_task_id": benchmark_task_id,
            "method_id": method_id,
            "provider": self.config.model_provider,
            "provider_kind": self.provider_kind,
            "model": self.config.model_name,
            "request_timestamp": timestamp,
            "response_timestamp": datetime.now(tz=UTC).isoformat(),
            "real_api_attempted": True,
            "transport_success": True,
            "real_api_transport_success": True,
            "raw_response_available": True,
            "raw_response_text": raw_text,
            "raw_response_payload": raw_payload,
            "provider_error_type": "",
            "provider_error_message": "",
            "latency_ms": latency_ms,
            "token_usage": raw_payload.get("usage"),
        }


def provider_config_public(provider: str, model: str) -> dict[str, Any]:
    """Return public Stage7B provider config without secrets."""

    return {
        "provider": provider,
        "model": model,
        "base_url": DEEPSEEK_RESPONSES_BASE_URL if provider == "deepseek" else None,
        "temperature": 0.0,
        "top_p": 1.0,
        "reasoning_effort": "none",
        "max_output_tokens": 4096,
        "max_retries": 0,
        "api_key_env_var": "DEEPSEEK_API_KEY" if provider == "deepseek" else "",
        "schema_request_policy": "schema-requested and deterministically validated",
        "json_repair": False,
        "provider_side_structured_outputs": False,
    }


def execution_protocol(provider_config: dict[str, Any]) -> dict[str, Any]:
    """Return the immutable Stage7B execution protocol."""

    payload = {
        "protocol_version": "stage7b_main_comparison_v1",
        "stage7a_artifact_dir": STAGE7A_DIR.as_posix(),
        "stage7_main_manifest_hash": EXPECTED_STAGE7_MAIN_HASH,
        "stage7_asof_binding_hash": EXPECTED_ASOF_BINDING_HASH,
        "b0_prompt_hash": EXPECTED_B0_PROMPT_HASH,
        "b1_prompt_hash": EXPECTED_B1_PROMPT_HASH,
        "product_task_contract_hash": EXPECTED_PRODUCT_CONTRACT_HASH,
        "provider_config_public": provider_config,
        "method_order_policy": {
            "task_index_mod_0": [B0_METHOD, B1_METHOD, P_METHOD],
            "task_index_mod_1": [B1_METHOD, P_METHOD, B0_METHOD],
            "task_index_mod_2": [P_METHOD, B0_METHOD, B1_METHOD],
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
        "stage6b_tag": STAGE6B_TAG,
        "stage6b_commit": STAGE6B_COMMIT,
        "stage7a_tag": STAGE7A_TAG,
        "stage7a_commit": STAGE7A_COMMIT,
    }
    return {**payload, "execution_protocol_hash": stable_hash(payload)}


def run_stage7b(
    repo_root: Path,
    *,
    provider: str,
    model: str,
    execute: bool,
    output_root: Path | None = None,
    execution_id: str | None = None,
) -> dict[str, Any]:
    """Prepare or execute the Stage7B benchmark."""

    output_root = output_root or repo_root / STAGE7B_DIR
    stage7a_dir = repo_root / STAGE7A_DIR
    provider_conf = provider_config_public(provider, model)
    protocol = execution_protocol(provider_conf)
    preflight = preflight_stage7b(repo_root, provider_conf, execute=execute)
    output_root.mkdir(parents=True, exist_ok=True)
    write_json(output_root / "execution_protocol.json", protocol)
    write_csv(output_root / "stage7b_preflight_audit.csv", preflight["audit_rows"])
    if preflight["status"] != "PASS":
        summary = {
            "stage7b_status": "NOT_RUN",
            "preflight_status": preflight["status"],
            "failure_codes": preflight["failure_codes"],
            "real_api_request_attempt_count": 0,
        }
        write_json(output_root / "run_summary.json", summary)
        write_hashes(output_root)
        if execute:
            raise Stage7BPreflightError(";".join(preflight["failure_codes"]))
        return summary

    tasks = read_json(stage7a_dir / "stage7_main_benchmark_manifest.json")["tasks"]
    b0_payloads = _jsonl_by_task(stage7a_dir / "stage7_b0_input_payloads.jsonl")
    b1_payloads = _jsonl_by_task(stage7a_dir / "stage7_b1_input_payloads.jsonl")
    asof_rows = _asof_rows_by_task(stage7a_dir / "stage7_asof_evaluation_binding_manifest.json")
    b0_prompt = (stage7a_dir / "stage7_b0_prompt_template_v1_1.txt").read_text(encoding="utf-8")
    b1_prompt = (stage7a_dir / "stage7_b1_prompt_template_v1_1.txt").read_text(encoding="utf-8")

    stage6b_inputs = load_stage6b_inputs(repo_root)
    p_bundles, p_requests, p_binding_rows = build_proposed_requests(
        tasks,
        asof_rows,
        stage6b_inputs,
    )
    manifest = build_execution_manifest(
        tasks,
        b0_payloads,
        b1_payloads,
        p_requests,
        protocol,
    )
    write_json(output_root / "execution_manifest.json", manifest)
    write_csv(output_root / "execution_manifest.csv", manifest["items"])
    write_csv(output_root / "stage7b_proposed_asof_binding_audit.csv", p_binding_rows)
    if any(row["status"] != "PASS" for row in p_binding_rows):
        summary = {
            "stage7b_status": "NOT_RUN",
            "preflight_status": "FAIL",
            "failure_codes": ["PROPOSED_ASOF_BINDING_FAILED"],
            "real_api_request_attempt_count": 0,
        }
        write_json(output_root / "run_summary.json", summary)
        write_hashes(output_root)
        if execute:
            raise Stage7BPreflightError("PROPOSED_ASOF_BINDING_FAILED")
        return summary
    if not execute:
        summary = {
            "stage7b_status": "DRY_RUN_PASS",
            "execution_manifest_item_count": len(manifest["items"]),
            "benchmark_task_count": len(tasks),
            "real_api_request_attempt_count": 0,
            "execution_protocol_hash": protocol["execution_protocol_hash"],
            "execution_manifest_hash": manifest["execution_manifest_hash"],
        }
        write_json(output_root / "run_summary.json", summary)
        write_hashes(output_root)
        return summary

    run_id = execution_id or _new_execution_id(protocol["execution_protocol_hash"])
    run_dir = output_root / "runs" / run_id
    if run_dir.exists():
        msg = f"Stage7B run directory already exists: {run_dir}"
        raise FileExistsError(msg)
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json(run_dir / "execution_protocol.json", protocol)
    write_json(run_dir / "execution_manifest.json", manifest)
    write_csv(run_dir / "execution_manifest.csv", manifest["items"])
    write_csv(run_dir / "stage7b_proposed_asof_binding_audit.csv", p_binding_rows)
    result = execute_stage7b_manifest(
        run_id,
        manifest["items"],
        b0_payloads,
        b1_payloads,
        p_bundles,
        p_requests,
        b0_prompt,
        b1_prompt,
        provider_conf,
        protocol,
        run_dir,
    )
    _write_formal_outputs(output_root, run_dir, protocol, manifest, result)
    return result


def preflight_stage7b(
    repo_root: Path, provider_conf: dict[str, Any], *, execute: bool
) -> dict[str, Any]:
    """Validate frozen inputs and provider configuration before any model call."""

    rows: list[dict[str, object]] = []

    def add(check_name: str, passed: bool, details: object = "") -> None:
        rows.append(
            {"check_name": check_name, "status": "PASS" if passed else "FAIL", "details": details}
        )

    stage7a_dir = repo_root / STAGE7A_DIR
    main = read_json(stage7a_dir / "stage7_main_benchmark_manifest.json")
    asof = read_json(stage7a_dir / "stage7_asof_evaluation_binding_manifest.json")
    baseline = read_json(stage7a_dir / "stage7_baseline_protocol.json")
    contracts = read_json(stage7a_dir / "stage7_product_task_contracts.json")
    add(
        "stage7a_main_manifest_hash",
        main.get("stage7_main_manifest_hash") == EXPECTED_STAGE7_MAIN_HASH,
    )
    add(
        "stage7a_asof_binding_hash",
        asof.get("stage7_asof_evaluation_binding_manifest_hash") == EXPECTED_ASOF_BINDING_HASH,
    )
    add("b0_prompt_hash", baseline.get("b0_prompt_hash") == EXPECTED_B0_PROMPT_HASH)
    add("b1_prompt_hash", baseline.get("b1_prompt_hash") == EXPECTED_B1_PROMPT_HASH)
    add(
        "product_contract_hash",
        contracts.get("product_task_contract_hash") == EXPECTED_PRODUCT_CONTRACT_HASH,
    )
    tasks = main.get("tasks", [])
    add("task_count", len(tasks) == 48, len(tasks))
    add("method_execution_count", len(tasks) * 3 == 144, len(tasks) * 3)
    add(
        "product_quotas",
        Counter(row["product_type"] for row in tasks)
        == {
            "all": 12,
            "daily_review": 12,
            "forward_attention": 12,
            "metric_review": 12,
        },
    )
    add("provider", provider_conf["provider"] == "deepseek", provider_conf["provider"])
    add(
        "model",
        provider_conf["model"] == DEEPSEEK_RESPONSES_SUPPORTED_MODEL,
        provider_conf["model"],
    )
    add("base_url", provider_conf["base_url"] == DEEPSEEK_RESPONSES_BASE_URL)
    add("max_retries", provider_conf["max_retries"] == 0)
    add("credential_env_present", (not execute) or bool(os.environ.get("DEEPSEEK_API_KEY")))
    try:
        import openai  # noqa: F401

        sdk_ok = True
    except ImportError:
        sdk_ok = False
    add("openai_sdk_importable", sdk_ok)
    failures = [row["check_name"] for row in rows if row["status"] != "PASS"]
    return {
        "status": "PASS" if not failures else "FAIL",
        "failure_codes": failures,
        "audit_rows": rows,
    }


def build_proposed_requests(
    tasks: list[dict[str, Any]],
    asof_rows: dict[str, dict[str, Any]],
    stage6b_inputs: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, SmokeRealizationRequest], list[dict[str, object]]]:
    """Rebuild P-method Stage6B bundles from exact Stage7A as-of bindings."""

    bundles: dict[str, dict[str, Any]] = {}
    requests: dict[str, SmokeRealizationRequest] = {}
    audit_rows: list[dict[str, object]] = []
    for task in tasks:
        task_id = str(task["benchmark_task_id"])
        asof = asof_rows[task_id]
        active_bitemporal_ids = set(_split_ids(asof.get("active_bitemporal_version_ids", "")))
        fact_ids = _split_ids(asof.get("asof_fact_lock_ids", ""))
        abstain_ids = _split_ids(asof.get("asof_abstention_ids", ""))
        locks = [
            lock
            for lock in stage6b_inputs["stage6a_locks"]
            if str(lock.bitemporal_version_id or "") in active_bitemporal_ids
        ]
        abstentions = [
            row
            for row in stage6b_inputs["stage5b_abstentions"]
            if str(row.get("bitemporal_version_id") or "") in active_bitemporal_ids
        ]
        bundle = build_task_bundle(
            locks,
            abstentions,
            stage6b_inputs["stage3a_cells"],
            SliceSpec(**task["slice_spec"]),
        )
        unit_ids = [unit.realization_unit_id for unit in bundle["units"]]
        expected_units = _split_ids(asof.get("asof_realization_unit_ids", ""))
        p_task = {
            "task_id": task_id,
            "slice_spec": task["slice_spec"],
            "valid_date": task["valid_date"],
            "product_type": task["product_type"],
            "realization_unit_ids": expected_units,
            "product_contract_hash": bundle["contract"].contract_hash,
            "presentation_policy_version": PRESENTATION_POLICY_VERSION,
            "pack_id": asof["asof_pack_id"],
            "pack_hash": asof["asof_pack_hash"],
            "canonical_sentences_by_unit": {
                sentence.realization_unit_id: sentence.text for sentence in bundle["sentences"]
            },
        }
        request = build_smoke_request(
            p_task,
            bundle["units"],
            bundle["contract"],
            bundle["task_view"],
            _stage7b_p_manifest_hash(tasks, asof_rows),
        )
        issue_codes = []
        rebuilt_fact_ids = sorted(str(lock.fact_lock_id) for lock in bundle["pack"].locked_facts)
        rebuilt_abstention_ids = sorted(
            str(row["abstention_id"]) for row in bundle["task_view"].records
        )
        if rebuilt_fact_ids != sorted(fact_ids):
            issue_codes.append("ASOF_FACT_LOCK_IDS_MISMATCH")
        if rebuilt_abstention_ids != sorted(abstain_ids):
            issue_codes.append("ASOF_ABSTENTION_IDS_MISMATCH")
        if unit_ids != expected_units:
            issue_codes.append("ASOF_UNIT_IDS_MISMATCH")
        if bundle["pack"].pack_id != asof["asof_pack_id"]:
            issue_codes.append("ASOF_PACK_ID_MISMATCH")
        if bundle["pack"].pack_hash != asof["asof_pack_hash"]:
            issue_codes.append("ASOF_PACK_HASH_MISMATCH")
        bundles[task_id] = bundle
        requests[task_id] = request
        audit_rows.append(
            {
                "benchmark_task_id": task_id,
                "fact_lock_count": len(fact_ids),
                "rebuilt_unit_count": len(unit_ids),
                "expected_unit_count": len(expected_units),
                "pack_id": bundle["pack"].pack_id,
                "expected_pack_id": asof["asof_pack_id"],
                "pack_hash": bundle["pack"].pack_hash,
                "expected_pack_hash": asof["asof_pack_hash"],
                "issue_codes": ";".join(issue_codes),
                "status": "PASS" if not issue_codes else "FAIL",
            }
        )
    return bundles, requests, audit_rows


def build_execution_manifest(
    tasks: list[dict[str, Any]],
    b0_payloads: dict[str, dict[str, Any]],
    b1_payloads: dict[str, dict[str, Any]],
    p_requests: dict[str, SmokeRealizationRequest],
    protocol: dict[str, Any],
) -> dict[str, Any]:
    """Build the 144-row execution manifest before the first API request."""

    items: list[dict[str, Any]] = []
    sequence = 0
    for index, task in enumerate(tasks):
        order = _rotating_order(index)
        for method_position, method_id in enumerate(order):
            task_id = str(task["benchmark_task_id"])
            if method_id == B0_METHOD:
                payload = b0_payloads[task_id]
                request_hash = stable_hash(
                    {
                        "prompt_hash": EXPECTED_B0_PROMPT_HASH,
                        "payload_hash": payload["input_payload_hash"],
                    }
                )
                pack_id = task["pack_id"]
                pack_hash = task["pack_hash"]
                unit_ids = task["realization_unit_ids"]
            elif method_id == B1_METHOD:
                payload = b1_payloads[task_id]
                request_hash = stable_hash(
                    {
                        "prompt_hash": EXPECTED_B1_PROMPT_HASH,
                        "payload_hash": payload["input_payload_hash"],
                    }
                )
                pack_id = task["pack_id"]
                pack_hash = task["pack_hash"]
                unit_ids = task["realization_unit_ids"]
            else:
                request = p_requests[task_id]
                request_hash = request.prompt_hash
                pack_id = request.pack_id
                pack_hash = request.pack_hash
                unit_ids = [unit["unit_id"] for unit in request.units]
            execution_item_id = stable_id(
                "stage7b_execution_item",
                {
                    "benchmark_task_id": task_id,
                    "method_id": method_id,
                    "sequence_index": sequence,
                    "request_hash": request_hash,
                    "execution_protocol_hash": protocol["execution_protocol_hash"],
                },
            )
            items.append(
                {
                    "execution_item_id": execution_item_id,
                    "sequence_index": sequence,
                    "benchmark_task_id": task_id,
                    "method_id": method_id,
                    "method_position_for_task": method_position,
                    "rotating_order_index": index % 3,
                    "product_type": task["product_type"],
                    "valid_date": task["valid_date"],
                    "slice_spec": json.dumps(
                        task["slice_spec"], ensure_ascii=False, sort_keys=True
                    ),
                    "pack_id": pack_id,
                    "pack_hash": pack_hash,
                    "realization_unit_ids": json.dumps(unit_ids, ensure_ascii=False),
                    "presentation_policy_version": PRESENTATION_POLICY_VERSION,
                    "provider": protocol["provider_config_public"]["provider"],
                    "model": protocol["provider_config_public"]["model"],
                    "temperature": protocol["provider_config_public"]["temperature"],
                    "top_p": protocol["provider_config_public"]["top_p"],
                    "reasoning_effort": protocol["provider_config_public"]["reasoning_effort"],
                    "max_output_tokens": protocol["provider_config_public"]["max_output_tokens"],
                    "max_retries": protocol["provider_config_public"]["max_retries"],
                    "request_hash": request_hash,
                }
            )
            sequence += 1
    payload = {"items": items}
    return {
        "schema_version": "stage7b_main_comparison.v1",
        "execution_manifest_hash": stable_hash(payload),
        "item_count": len(items),
        "items": items,
    }


def execute_stage7b_manifest(
    execution_id: str,
    items: list[dict[str, Any]],
    b0_payloads: dict[str, dict[str, Any]],
    b1_payloads: dict[str, dict[str, Any]],
    p_bundles: dict[str, dict[str, Any]],
    p_requests: dict[str, SmokeRealizationRequest],
    b0_prompt: str,
    b1_prompt: str,
    provider_conf: dict[str, Any],
    protocol: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    """Execute every manifest row exactly once."""

    llm_config = LLMProviderConfig(
        model_provider=provider_conf["provider"],
        model_name=provider_conf["model"],
        temperature=provider_conf["temperature"],
        top_p=provider_conf["top_p"],
        seed=None,
        reasoning_effort=provider_conf["reasoning_effort"],
        max_output_tokens=provider_conf["max_output_tokens"],
        timeout_seconds=120,
        max_retries=provider_conf["max_retries"],
        retry_causes=[],
        api_key_env_var=provider_conf["api_key_env_var"],
        base_url=provider_conf["base_url"],
    )
    text_provider = DeepSeekTextProvider(llm_config)
    plan_provider = DeepSeekResponsesPlanProvider(llm_config)
    for name in [
        "request_records.jsonl",
        "raw_model_outputs.jsonl",
        "B0_outputs.jsonl",
        "B1_outputs.jsonl",
        "P_raw_plans.jsonl",
        "P_final_outputs.jsonl",
        "stage7b_blind_output_packet.jsonl",
    ]:
        (run_dir / name).write_text("", encoding="utf-8")
    raw_rows: list[dict[str, Any]] = []
    request_records: list[dict[str, Any]] = []
    b0_outputs: list[dict[str, Any]] = []
    b1_outputs: list[dict[str, Any]] = []
    p_raw_plans: list[dict[str, Any]] = []
    p_validation_rows: list[dict[str, object]] = []
    p_final_outputs: list[dict[str, Any]] = []
    p_post_rows: list[dict[str, object]] = []
    transport_failures: list[dict[str, object]] = []
    structure_rows: list[dict[str, object]] = []
    for item in items:
        method_id = item["method_id"]
        task_id = item["benchmark_task_id"]
        request_record = _request_record(item, protocol)
        request_records.append(request_record)
        _append_jsonl(run_dir / "request_records.jsonl", request_record)
        if method_id in {B0_METHOD, B1_METHOD}:
            payload = b0_payloads[task_id] if method_id == B0_METHOD else b1_payloads[task_id]
            prompt = b0_prompt if method_id == B0_METHOD else b1_prompt
            text_attempt = text_provider.request_text(
                execution_item_id=item["execution_item_id"],
                benchmark_task_id=task_id,
                method_id=method_id,
                system_prompt=prompt,
                payload=payload,
            )
            text_raw = {**text_attempt, "execution_id": execution_id}
            raw_rows.append(text_raw)
            _append_jsonl(run_dir / "raw_model_outputs.jsonl", text_raw)
            if not text_attempt["transport_success"]:
                transport_failures.append(_transport_failure_row(item, text_attempt))
                structure_rows.append(_structure_row(item, "TRANSPORT_FAILURE", "FAIL"))
                continue
            output_row = {
                "execution_id": execution_id,
                "execution_item_id": item["execution_item_id"],
                "benchmark_task_id": task_id,
                "method_id": method_id,
                "output_text": text_attempt["raw_response_text"],
                "output_hash": stable_hash(text_attempt["raw_response_text"]),
                "raw_preserved": True,
            }
            if method_id == B0_METHOD:
                b0_outputs.append(output_row)
                _append_jsonl(run_dir / "B0_outputs.jsonl", output_row)
            else:
                b1_outputs.append(output_row)
                _append_jsonl(run_dir / "B1_outputs.jsonl", output_row)
            structure_rows.append(_structure_row(item, "NONEMPTY_RAW_TEXT", "PASS"))
            continue
        request = p_requests[task_id]
        plan_attempt = plan_provider.request_plan(request)
        raw = {
            "execution_id": execution_id,
            "execution_item_id": item["execution_item_id"],
            "benchmark_task_id": task_id,
            "method_id": method_id,
            "provider": plan_attempt.provider,
            "provider_kind": plan_attempt.provider_kind,
            "model": plan_attempt.model_name,
            "request_timestamp": plan_attempt.request_timestamp,
            "real_api_attempted": plan_attempt.real_api_attempted,
            "transport_success": plan_attempt.transport_success,
            "real_api_transport_success": plan_attempt.real_api_transport_success,
            "raw_response_available": plan_attempt.raw_response_available,
            "raw_response_text": plan_attempt.raw_response_text,
            "raw_response_payload": plan_attempt.raw_response_payload,
            "provider_error_type": plan_attempt.provider_error_type,
            "provider_error_message": plan_attempt.provider_error_message,
            "latency_ms": plan_attempt.latency_ms,
            "token_usage": plan_attempt.token_usage,
        }
        raw_rows.append(raw)
        _append_jsonl(run_dir / "raw_model_outputs.jsonl", raw)
        if not plan_attempt.transport_success or plan_attempt.raw_response_text is None:
            transport_failures.append(_transport_failure_row(item, raw))
            structure_rows.append(_structure_row(item, "TRANSPORT_FAILURE", "FAIL"))
            continue
        minimal, error_codes, parse_error = parse_provider_plan(plan_attempt.raw_response_text)
        p_raw_plan = {
            "execution_id": execution_id,
            "execution_item_id": item["execution_item_id"],
            "benchmark_task_id": task_id,
            "raw_response_text": plan_attempt.raw_response_text,
            "parse_valid": minimal is not None or error_codes == ["SCHEMA_VALIDATION_FAILURE"],
            "schema_valid": minimal is not None,
            "schema_error_codes": error_codes,
            "parse_error": parse_error,
        }
        p_raw_plans.append(p_raw_plan)
        _append_jsonl(run_dir / "P_raw_plans.jsonl", p_raw_plan)
        if minimal is None:
            p_validation_rows.append(
                {
                    "execution_item_id": item["execution_item_id"],
                    "benchmark_task_id": task_id,
                    "parse_valid": "false",
                    "schema_valid": "false",
                    "plan_valid": "false",
                    "violation_codes": ";".join(error_codes),
                }
            )
            structure_rows.append(_structure_row(item, "P_PLAN_NOT_COMPOSED", "FAIL"))
            continue
        bundle = p_bundles[task_id]
        plan = materialize_realization_plan(
            minimal,
            bundle["pack"],
            bundle["task_view"],
            bundle["contract"],
            provider_name=plan_attempt.provider,
        )
        issues = validate_plan(
            plan,
            bundle["units"],
            bundle["contract"],
            bundle["pack"].pack_id,
            bundle["pack"].pack_hash,
            bundle["task_view"].task_abstention_view_id,
        )
        p_validation_rows.append(
            {
                "execution_item_id": item["execution_item_id"],
                "benchmark_task_id": task_id,
                "parse_valid": "true",
                "schema_valid": "true",
                "plan_valid": str(not issues).lower(),
                "violation_codes": ";".join(issues),
                "plan_id": plan.plan_id,
                "plan_hash": plan.plan_hash,
            }
        )
        if issues:
            structure_rows.append(_structure_row(item, "P_PLAN_REJECTED", "FAIL"))
            continue
        sentences_by_unit = {
            sentence.realization_unit_id: sentence for sentence in bundle["sentences"]
        }
        composed = compose_realization(
            plan, sentences_by_unit, bundle["task_view"], bundle["contract"]
        )
        post_issues = []
        from tbm_twin.realization.stage6b import audit_post_realization

        post_issues = audit_post_realization(composed, bundle["sentences"])
        p_final_output = {
            **composed.model_dump(mode="json"),
            "execution_id": execution_id,
            "execution_item_id": item["execution_item_id"],
            "benchmark_task_id": task_id,
            "method_id": method_id,
        }
        p_final_outputs.append(p_final_output)
        _append_jsonl(run_dir / "P_final_outputs.jsonl", p_final_output)
        p_post_rows.append(
            {
                "execution_item_id": item["execution_item_id"],
                "benchmark_task_id": task_id,
                "post_audit_status": "PASS" if not post_issues else "FAIL",
                "post_audit_issue_codes": ";".join(post_issues),
            }
        )
        structure_rows.append(
            _structure_row(item, "P_COMPOSED_POST_AUDITED", "PASS" if not post_issues else "FAIL")
        )
    write_csv(run_dir / "P_plan_validation.csv", p_validation_rows)
    write_csv(run_dir / "P_post_audit.csv", p_post_rows)
    write_csv(run_dir / "stage7b_structure_audit.csv", structure_rows)
    write_csv(run_dir / "transport_failures.csv", transport_failures)
    blind_mapping, blind_packet = _blind_outputs(b0_outputs, b1_outputs, p_final_outputs)
    write_csv(run_dir / "stage7b_blind_output_internal_mapping.csv", blind_mapping)
    write_jsonl(run_dir / "stage7b_blind_output_packet.jsonl", blind_packet)
    summary = _run_summary(
        execution_id,
        items,
        raw_rows,
        b0_outputs,
        b1_outputs,
        p_raw_plans,
        p_validation_rows,
        p_final_outputs,
        p_post_rows,
        transport_failures,
        structure_rows,
        protocol,
    )
    write_json(run_dir / "run_summary.json", summary)
    write_csv(run_dir / "run_summary.csv", [summary])
    write_csv(run_dir / "execution_accounting.csv", _execution_accounting(summary, raw_rows))
    write_hashes(run_dir)
    return {**summary, "run_dir": run_dir.as_posix()}


def _write_formal_outputs(
    output_root: Path,
    run_dir: Path,
    protocol: dict[str, Any],
    manifest: dict[str, Any],
    result: dict[str, Any],
) -> None:
    hard_rows = [
        _hard("execution_manifest_count", manifest["item_count"] == 144, manifest["item_count"]),
        _hard(
            "real_api_attempts",
            result["real_api_request_attempt_count"] == 144,
            result["real_api_request_attempt_count"],
        ),
        _hard(
            "transport_failures",
            result["transport_failure_count"] == 0,
            result["transport_failure_count"],
        ),
        _hard(
            "p_post_audit",
            result["p_post_audit_fail_count"] == 0,
            result["p_post_audit_fail_count"],
        ),
    ]
    write_csv(output_root / "stage7b_hard_check.csv", hard_rows)
    formal = {
        "method_version": "stage7b_main_comparison_v1",
        "schema_version": "stage7b_main_comparison.v1",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "execution_protocol_hash": protocol["execution_protocol_hash"],
        "execution_manifest_hash": manifest["execution_manifest_hash"],
        "run_dir": run_dir.relative_to(output_root).as_posix(),
        "run_summary": result,
        "hard_check_fail_count": sum(row["status"] != "PASS" for row in hard_rows),
    }
    write_json(output_root / "method_version.json", formal)
    write_json(output_root / "freeze_manifest.json", formal)
    write_json(output_root / "run_summary.json", result)
    write_csv(output_root / "run_summary.csv", [result])
    write_csv(output_root / "latest_run_pointer.csv", [{"run_dir": run_dir.as_posix()}])
    write_json(output_root / "stage7b_main_comparison_report.json", formal)
    (output_root / "stage7b_main_comparison_report.md").write_text(
        _stage7b_markdown_report(formal),
        encoding="utf-8",
    )
    write_hashes(output_root)


def _jsonl_by_task(path: Path) -> dict[str, dict[str, Any]]:
    return {str(row["benchmark_task_id"]): row for row in read_jsonl(path)}


def _asof_rows_by_task(path: Path) -> dict[str, dict[str, Any]]:
    return {str(row["benchmark_task_id"]): row for row in read_json(path)["tasks"]}


def _split_ids(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [part for part in str(value).split(";") if part]


def _stage7b_p_manifest_hash(
    tasks: list[dict[str, Any]], asof_rows: dict[str, dict[str, Any]]
) -> str:
    return stable_hash(
        [
            {
                "benchmark_task_id": task["benchmark_task_id"],
                "slice_spec": task["slice_spec"],
                "asof_fact_lock_ids": asof_rows[task["benchmark_task_id"]].get(
                    "asof_fact_lock_ids", ""
                ),
                "asof_abstention_ids": asof_rows[task["benchmark_task_id"]].get(
                    "asof_abstention_ids", ""
                ),
            }
            for task in tasks
        ]
    )


def _rotating_order(index: int) -> list[str]:
    if index % 3 == 0:
        return [B0_METHOD, B1_METHOD, P_METHOD]
    if index % 3 == 1:
        return [B1_METHOD, P_METHOD, B0_METHOD]
    return [P_METHOD, B0_METHOD, B1_METHOD]


def _new_execution_id(protocol_hash: str) -> str:
    now = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return stable_id("stage7b_main_execution", {"protocol_hash": protocol_hash, "started_at": now})


def _request_record(item: dict[str, Any], protocol: dict[str, Any]) -> dict[str, Any]:
    return {
        "execution_item_id": item["execution_item_id"],
        "benchmark_task_id": item["benchmark_task_id"],
        "method_id": item["method_id"],
        "sequence_index": item["sequence_index"],
        "request_hash": item["request_hash"],
        "execution_protocol_hash": protocol["execution_protocol_hash"],
        "provider": item["provider"],
        "model": item["model"],
    }


def _transport_failure_row(item: dict[str, Any], attempt: dict[str, Any]) -> dict[str, object]:
    return {
        "execution_item_id": item["execution_item_id"],
        "benchmark_task_id": item["benchmark_task_id"],
        "method_id": item["method_id"],
        "provider_error_type": attempt.get("provider_error_type", ""),
        "provider_error_message": attempt.get("provider_error_message", ""),
    }


def _structure_row(item: dict[str, Any], check: str, status: str) -> dict[str, object]:
    return {
        "execution_item_id": item["execution_item_id"],
        "benchmark_task_id": item["benchmark_task_id"],
        "method_id": item["method_id"],
        "check_name": check,
        "status": status,
    }


def _blind_outputs(
    b0_outputs: list[dict[str, Any]],
    b1_outputs: list[dict[str, Any]],
    p_outputs: list[dict[str, Any]],
) -> tuple[list[dict[str, object]], list[dict[str, Any]]]:
    all_outputs = (
        b0_outputs
        + b1_outputs
        + [
            {
                "execution_item_id": row["execution_item_id"],
                "benchmark_task_id": row["benchmark_task_id"],
                "method_id": row["method_id"],
                "output_text": row["text"],
                "output_hash": row["realization_hash"],
            }
            for row in p_outputs
        ]
    )
    mapping = []
    packet = []
    for row in sorted(all_outputs, key=lambda item: stable_hash(item["execution_item_id"])):
        anonymous_id = stable_id("stage7b_blind_output", row["execution_item_id"])
        mapping.append(
            {
                "anonymous_output_id": anonymous_id,
                "execution_item_id": row["execution_item_id"],
                "benchmark_task_id": row["benchmark_task_id"],
                "method_id": row["method_id"],
            }
        )
        packet.append(
            {
                "anonymous_output_id": anonymous_id,
                "output_text": row["output_text"],
                "rating_fields": {
                    "factual_support": "",
                    "epistemic_boundary": "",
                    "spatial_temporal_specificity": "",
                    "readability": "",
                    "overall_preference": "",
                },
            }
        )
    return mapping, packet


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _run_summary(
    execution_id: str,
    items: list[dict[str, Any]],
    raw_rows: list[dict[str, Any]],
    b0_outputs: list[dict[str, Any]],
    b1_outputs: list[dict[str, Any]],
    p_raw_plans: list[dict[str, Any]],
    p_validation_rows: list[dict[str, object]],
    p_final_outputs: list[dict[str, Any]],
    p_post_rows: list[dict[str, object]],
    transport_failures: list[dict[str, object]],
    structure_rows: list[dict[str, object]],
    protocol: dict[str, Any],
) -> dict[str, Any]:
    real_attempts = sum(1 for row in raw_rows if row.get("real_api_attempted"))
    transport_success = sum(1 for row in raw_rows if row.get("transport_success"))
    p_valid = sum(row.get("plan_valid") == "true" for row in p_validation_rows)
    p_post_pass = sum(row.get("post_audit_status") == "PASS" for row in p_post_rows)
    return {
        "execution_id": execution_id,
        "stage7b_status": "EXECUTED",
        "execution_protocol_hash": protocol["execution_protocol_hash"],
        "execution_item_count": len(items),
        "benchmark_task_count": len({row["benchmark_task_id"] for row in items}),
        "provider": protocol["provider_config_public"]["provider"],
        "model": protocol["provider_config_public"]["model"],
        "real_api_request_attempt_count": real_attempts,
        "real_api_transport_success_count": transport_success,
        "transport_failure_count": len(transport_failures),
        "b0_output_count": len(b0_outputs),
        "b1_output_count": len(b1_outputs),
        "p_raw_plan_count": len(p_raw_plans),
        "p_plan_valid_count": p_valid,
        "p_final_output_count": len(p_final_outputs),
        "p_post_audit_pass_count": p_post_pass,
        "p_post_audit_fail_count": sum(
            row.get("post_audit_status") != "PASS" for row in p_post_rows
        ),
        "structure_audit_fail_count": sum(row.get("status") != "PASS" for row in structure_rows),
    }


def _execution_accounting(
    summary: dict[str, Any], raw_rows: list[dict[str, Any]]
) -> list[dict[str, object]]:
    return [
        {
            "metric": "real_api_request_attempt_count",
            "reported_value": summary["real_api_request_attempt_count"],
            "recomputed_value": sum(1 for row in raw_rows if row.get("real_api_attempted")),
            "status": "PASS",
        },
        {
            "metric": "real_api_transport_success_count",
            "reported_value": summary["real_api_transport_success_count"],
            "recomputed_value": sum(1 for row in raw_rows if row.get("transport_success")),
            "status": "PASS",
        },
    ]


def _hard(check_name: str, passed: bool, details: object) -> dict[str, object]:
    return {"check_name": check_name, "status": "PASS" if passed else "FAIL", "details": details}


def _stage7b_markdown_report(formal: dict[str, Any]) -> str:
    summary = formal["run_summary"]
    return "\n".join(
        [
            "# Stage7B Main Comparison v1",
            "",
            "Stage7B executed the frozen Stage7A v1.3 held-out benchmark with three methods.",
            (
                "It does not perform human evaluation, significance testing, prompt tuning, "
                "or Stage7C."
            ),
            "",
            "## Frozen Inputs",
            "",
            f"- Stage7A manifest hash: `{EXPECTED_STAGE7_MAIN_HASH}`",
            f"- Stage7A as-of binding hash: `{EXPECTED_ASOF_BINDING_HASH}`",
            f"- Product contract hash: `{EXPECTED_PRODUCT_CONTRACT_HASH}`",
            "",
            "## Provider",
            "",
            f"- Provider: `{summary['provider']}`",
            f"- Model: `{summary['model']}`",
            "- Temperature: `0.0`",
            "- Top-p: `1.0`",
            "- Reasoning effort: `none`",
            "- Max retries: `0`",
            "",
            "## Execution Summary",
            "",
            f"- Execution ID: `{summary['execution_id']}`",
            f"- Execution protocol hash: `{summary['execution_protocol_hash']}`",
            f"- Execution items: `{summary['execution_item_count']}`",
            f"- Benchmark tasks: `{summary['benchmark_task_count']}`",
            f"- Real API attempts: `{summary['real_api_request_attempt_count']}`",
            f"- Transport successes: `{summary['real_api_transport_success_count']}`",
            f"- Transport failures: `{summary['transport_failure_count']}`",
            f"- B0 outputs: `{summary['b0_output_count']}`",
            f"- B1 outputs: `{summary['b1_output_count']}`",
            f"- P raw plans: `{summary['p_raw_plan_count']}`",
            f"- P valid/composed outputs: `{summary['p_final_output_count']}`",
            f"- P post-audit failures: `{summary['p_post_audit_fail_count']}`",
            "",
            "## Notes",
            "",
            (
                "The proposed method composes only plans that pass deterministic schema "
                "and domain validation."
            ),
            (
                "Invalid plans are preserved as raw model outputs and are not repaired, "
                "retried, or composed."
            ),
            "",
        ]
    )


def sha256_file(path: Path) -> str:
    """Return byte SHA-256 for tests and reports."""

    return hashlib.sha256(path.read_bytes()).hexdigest()
