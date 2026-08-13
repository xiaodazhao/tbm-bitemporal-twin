"""Prepare or run Stage6B real-model smoke.

This entrypoint defaults to fail-closed. Use --dry-run for the current
pre-smoke preparation; real API execution must be invoked explicitly later.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from tbm_twin.realization.io import read_jsonl, write_csv, write_json
from tbm_twin.realization.providers.configured_llm import LLMProviderConfig
from tbm_twin.realization.providers.deepseek_adapter import (
    DEEPSEEK_RESPONSES_SUPPORTED_MODEL,
    DeepSeekResponsesPlanProvider,
)
from tbm_twin.realization.providers.openai_adapter import OpenAIPlanProvider
from tbm_twin.realization.stage6b import load_stage6b_inputs
from tbm_twin.realization.stage6b_smoke import (
    MockPlanProvider,
    SmokeRealizationRequest,
    build_manifest_bound_task_bundles,
    default_provider_config_public,
    dry_run_smoke,
    execute_smoke_tasks,
    execution_protocol,
    smoke_manifest_hash,
)


def main() -> None:
    """CLI wrapper for Stage6B smoke preparation."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model", default="UNSET_REAL_MODEL")
    parser.add_argument(
        "--task-manifest",
        default="artifacts/stage6b_controlled_realization_v1_candidate/real_model_smoke/task_manifest.json",
    )
    parser.add_argument(
        "--prompt-payloads",
        default="artifacts/stage6b_controlled_realization_v1_candidate/real_model_smoke/prompt_payloads.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/stage6b_controlled_realization_v1_candidate/real_model_smoke",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--mock-mode",
        choices=["success", "malformed_json", "schema_invalid", "plan_invalid"],
        default="success",
    )
    args = parser.parse_args()

    task_manifest_path = Path(args.task_manifest)
    prompt_payload_path = Path(args.prompt_payloads)
    output_dir = Path(args.output_dir)
    tasks = _read_json_array(task_manifest_path)
    requests = [SmokeRealizationRequest(**row) for row in read_jsonl(prompt_payload_path)]
    provider_config = default_provider_config_public(provider=args.provider, model=args.model)
    if args.dry_run:
        result = dry_run_smoke(tasks, requests, output_dir)
        protocol = execution_protocol(smoke_manifest_hash(tasks), provider_config)
        write_json(output_dir / "provider_config_public.json", provider_config)
        write_json(output_dir / "execution_protocol.json", protocol)
        status_path = output_dir / "dry_run_status.json"
        write_json(
            status_path,
            {
                **result,
                "provider": args.provider,
                "model": args.model,
                "task_manifest_hash": smoke_manifest_hash(tasks),
                "api_request_sent": False,
            },
        )
        if result["dry_run_status"] != "PASS":
            raise SystemExit(1)
        print("REAL_MODEL_SMOKE_DRY_RUN_PASS")
        return
    if not args.execute:
        write_json(
            output_dir / "no_execute_status.json",
            {
                "real_model_smoke_status": "NOT_RUN",
                "execution_layer_status": "READY",
                "api_call_count": 0,
                "reason": "explicit --execute not provided",
            },
        )
        print("REAL_MODEL_SMOKE_EXECUTE_NOT_REQUESTED")
        return

    repo_root = Path(__file__).resolve().parents[1]
    inputs = load_stage6b_inputs(repo_root)
    task_bundles, binding_rows = build_manifest_bound_task_bundles(
        inputs["stage6a_locks"],
        inputs["stage5b_abstentions"],
        inputs["stage3a_cells"],
        tasks,
        requests,
    )
    write_csv(output_dir / "execution_manifest_binding_audit.csv", binding_rows)
    if any(row["status"] != "PASS" for row in binding_rows):
        _write_preflight_failure(
            output_dir,
            "MANIFEST_BINDING_FAILED",
            args.provider,
            args.model,
            smoke_manifest_hash(tasks),
        )
        print("REAL_MODEL_SMOKE_PREFLIGHT_FAILED MANIFEST_BINDING_FAILED")
        raise SystemExit(1)
    if args.provider == "openai" and args.model == "UNSET_REAL_MODEL":
        _write_preflight_failure(
            output_dir,
            "UNSET_REAL_MODEL",
            args.provider,
            args.model,
            smoke_manifest_hash(tasks),
        )
        print("REAL_MODEL_SMOKE_PREFLIGHT_FAILED UNSET_REAL_MODEL")
        raise SystemExit(1)
    protocol = execution_protocol(smoke_manifest_hash(tasks), provider_config)
    preflight = _provider_preflight(args.provider, args.model, provider_config, protocol)
    if preflight["status"] != "PASS":
        _write_preflight_failure(
            output_dir,
            str(preflight["failure_code"]),
            args.provider,
            args.model,
            smoke_manifest_hash(tasks),
            details=preflight,
        )
        print(f"REAL_MODEL_SMOKE_PREFLIGHT_FAILED {preflight['failure_code']}")
        raise SystemExit(1)
    if args.provider == "mock":
        provider = MockPlanProvider(args.mock_mode)
    elif args.provider == "openai":
        provider = OpenAIPlanProvider(
            LLMProviderConfig(
                model_provider=args.provider,
                model_name=args.model,
                temperature=provider_config["temperature"],
                top_p=provider_config["top_p"],
                seed=provider_config["seed"],
                reasoning_effort=provider_config["reasoning_effort"],
                max_output_tokens=provider_config["max_output_tokens"],
                timeout_seconds=provider_config["timeout_seconds"],
                max_retries=provider_config["max_retries"],
                retry_causes=[],
                api_key_env_var=provider_config["api_key_env_var"],
                base_url=provider_config["base_url"],
            )
        )
    elif args.provider == "deepseek":
        provider = DeepSeekResponsesPlanProvider(
            LLMProviderConfig(
                model_provider=args.provider,
                model_name=args.model,
                temperature=provider_config["temperature"],
                top_p=provider_config["top_p"],
                seed=provider_config["seed"],
                reasoning_effort=provider_config["reasoning_effort"],
                max_output_tokens=provider_config["max_output_tokens"],
                timeout_seconds=provider_config["timeout_seconds"],
                max_retries=provider_config["max_retries"],
                retry_causes=[],
                api_key_env_var=provider_config["api_key_env_var"],
                base_url=provider_config["base_url"],
            )
        )
    else:
        msg = f"unsupported provider: {args.provider}"
        raise SystemExit(msg)
    result = execute_smoke_tasks(
        task_bundles,
        requests,
        provider,
        output_dir,
        protocol,
        execution_manifest_binding_rows=binding_rows,
    )
    print(f"REAL_MODEL_SMOKE_EXECUTION_COMPLETE {result['execution_id']}")


def _read_json_array(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        msg = f"expected JSON array at {path}"
        raise ValueError(msg)
    return [row for row in raw if isinstance(row, dict)]


def _provider_preflight(
    provider: str,
    model: str,
    provider_config: dict[str, Any],
    protocol: dict[str, Any],
) -> dict[str, object]:
    if provider not in {"mock", "openai", "deepseek"}:
        return _preflight("UNSUPPORTED_PROVIDER")
    if model == "UNSET_REAL_MODEL" and provider in {"openai", "deepseek"}:
        return _preflight("UNSET_REAL_MODEL")
    if provider == "deepseek":
        if model != DEEPSEEK_RESPONSES_SUPPORTED_MODEL:
            return _preflight("UNSUPPORTED_DEEPSEEK_RESPONSES_MODEL")
        if provider_config.get("base_url") != "https://api.deepseek.com":
            return _preflight("INVALID_DEEPSEEK_BASE_URL")
        if not os.environ.get(str(provider_config["api_key_env_var"])):
            return _preflight("MISSING_DEEPSEEK_API_KEY")
        try:
            import openai
        except ImportError:
            return _preflight("OPENAI_SDK_MISSING")
        _ = openai
    if provider == "openai":
        if not os.environ.get(str(provider_config["api_key_env_var"])):
            return _preflight("MISSING_OPENAI_API_KEY")
        try:
            import openai
        except ImportError:
            return _preflight("OPENAI_SDK_MISSING")
        _ = openai
    if protocol.get("max_retries") != 0:
        return _preflight("INVALID_PROTOCOL_RETRY_POLICY")
    return {"status": "PASS", "failure_code": ""}


def _preflight(code: str) -> dict[str, object]:
    return {
        "status": "FAIL",
        "failure_code": code,
        "provider_request_attempt_count": 0,
        "real_api_request_attempt_count": 0,
        "real_api_transport_success_count": 0,
        "real_api_transport_failure_count": 0,
    }


def _write_preflight_failure(
    output_dir: Path,
    failure_code: str,
    provider: str,
    model: str,
    task_manifest_hash: str,
    *,
    details: dict[str, object] | None = None,
) -> None:
    failure_dir = output_dir / "preflight_failures"
    failure_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        failure_dir / f"{failure_code.lower()}_status.json",
        {
            "real_model_smoke_status": "NOT_RUN",
            "execution_layer_status": "FAIL_CLOSED_BEFORE_API_CALL",
            "provider": provider,
            "model": model,
            "task_manifest_hash": task_manifest_hash,
            "provider_request_attempt_count": 0,
            "real_api_request_attempt_count": 0,
            "real_api_transport_success_count": 0,
            "real_api_transport_failure_count": 0,
            "formal_run_directory_created": False,
            "execution_complete_printed": False,
            "failure_code": failure_code,
            "details": details or {},
        },
    )


if __name__ == "__main__":
    main()
