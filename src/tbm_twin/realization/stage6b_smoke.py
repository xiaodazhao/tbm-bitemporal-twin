"""Stage6B real-model smoke preparation utilities.

The smoke layer prepares deterministic plan-selection prompts only. It never
creates engineering facts and never composes engineering prose from model text.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from tbm_twin.realization.io import stable_hash, stable_id, write_csv, write_json, write_jsonl
from tbm_twin.realization.models import SliceSpec
from tbm_twin.realization.providers.configured_llm import ProviderAttempt
from tbm_twin.realization.stage6b import (
    audit_post_realization,
    build_task_bundle,
    compose_realization,
    validate_plan,
)
from tbm_twin.realization.stage6b_models import (
    PRESENTATION_POLICY_VERSION,
    ComposedRealization,
    ProductType,
    RealizationPlan,
    RealizationPlanSection,
    RealizationUnit,
)

STRICT = ConfigDict(frozen=True, extra="forbid")

SMOKE_PROTOCOL_VERSION = "stage6b_real_model_smoke_protocol_v1_candidate"
SMOKE_RETRY_POLICY = {
    "max_retries": 0,
    "retry_on_parse_failure": False,
    "retry_on_schema_failure": False,
    "retry_on_plan_validation_failure": False,
}
SMOKE_EVALUATION_METRICS = [
    "first_attempt_parse_valid_rate",
    "first_attempt_schema_valid_rate",
    "first_attempt_plan_acceptance_rate",
    "final_plan_acceptance_rate",
    "unknown_unit_reference_rate",
    "out_of_task_unit_reference_rate",
    "duplicate_unit_rate",
    "required_unit_omission_rate",
    "invalid_section_rate",
    "validator_interception_count",
    "final_post_audit_violation_count",
    "final_trace_coverage",
]


class SmokeRealizationRequest(BaseModel):
    """Stable request payload given to a plan provider."""

    model_config = STRICT

    request_id: str
    task_id: str
    task_manifest_hash: str
    product_type: str
    slice_spec: dict[str, Any]
    pack_id: str
    pack_hash: str
    contract_hash: str
    presentation_policy_version: str
    allowed_section_ids: list[str]
    section_claim_type_map: dict[str, list[str]]
    required_unit_policy: str
    omitted_optional_unit_ids_allowed: list[str]
    units: list[dict[str, Any]]
    task_abstention_summary: dict[str, Any]
    output_schema: dict[str, Any]
    instructions: list[str]
    prompt_hash: str


class MinimalProviderPlanSection(BaseModel):
    """One section controlled by the model in a minimal provider plan."""

    model_config = STRICT

    section_id: str
    ordered_unit_ids: list[str]


class MinimalProviderPlan(BaseModel):
    """Strict planner-only payload returned by a model."""

    model_config = STRICT

    product_type: ProductType
    sections: list[MinimalProviderPlanSection]
    omitted_optional_unit_ids: list[str]


class SmokeAttemptResult(BaseModel):
    """Downstream execution result derived from a raw provider attempt."""

    model_config = STRICT

    execution_id: str
    task_id: str
    attempt_number: int
    raw_attempt_ref: str
    provider_kind: str
    provider_attempted: bool
    transport_success: bool
    real_api_attempted: bool
    real_api_transport_success: bool
    raw_response_available: bool
    parse_valid: bool
    schema_valid: bool
    domain_plan_valid: bool
    parse_error: str
    schema_error_codes: list[str]
    plan_violation_codes: list[str]
    materialized_plan_id: str | None
    materialized_plan_hash: str | None
    composition_status: str
    composed_realization_id: str | None
    post_audit_status: str
    post_audit_issue_codes: list[str]


class MockPlanProvider:
    """Deterministic local provider used only for execution-layer tests."""

    provider_name = "mock"
    timestamp = "2026-08-12T00:00:00+00:00"

    def __init__(self, mode: str = "success") -> None:
        self.mode = mode

    def request_plan(self, request: SmokeRealizationRequest) -> ProviderAttempt:
        """Return one deterministic raw response without network access."""

        if self.mode == "transport_failure":
            msg = "deterministic mock transport failure"
            raise RuntimeError(msg)
        if self.mode == "malformed_json":
            raw_text = "Here is your JSON:\n{broken..."
        elif self.mode == "schema_invalid":
            raw_text = json.dumps(
                {
                    "product_type": request.product_type,
                    "sections": [],
                    "omitted_optional_unit_ids": [],
                    "generated_text": "not allowed",
                },
                ensure_ascii=False,
            )
        elif self.mode == "plan_invalid":
            raw_text = json.dumps(
                {
                    "product_type": request.product_type,
                    "sections": [
                        {
                            "section_id": request.allowed_section_ids[0],
                            "ordered_unit_ids": ["unknown_unit"],
                        }
                    ],
                    "omitted_optional_unit_ids": [],
                },
                ensure_ascii=False,
            )
        else:
            raw_text = json.dumps(_legal_minimal_plan_payload(request), ensure_ascii=False)
        return ProviderAttempt(
            attempt_index=0,
            attempt_number=1,
            provider_kind="MOCK",
            provider=self.provider_name,
            request_id=request.request_id,
            model_name=f"mock-stage6b-{self.mode}",
            request_timestamp=self.timestamp,
            pack_id=request.pack_id,
            contract_hash=request.contract_hash,
            task_scope=request.slice_spec,
            input_unit_ids=[unit["unit_id"] for unit in request.units],
            provider_attempted=True,
            transport_success=True,
            real_api_attempted=False,
            real_api_transport_success=False,
            raw_response_available=True,
            raw_response_text=raw_text,
            raw_response_payload={"mock_mode": self.mode, "response_timestamp": self.timestamp},
            raw_response=raw_text,
            parse_status="RAW_RETURNED_NOT_PARSED_BY_PROVIDER",
            parsed_payload=None,
            schema_valid=False,
            validation_violations=[],
            provider_error_type="",
            provider_error_message="",
            latency_ms=0,
            token_usage=None,
        )


def smoke_manifest_hash(tasks: list[dict[str, Any]]) -> str:
    """Hash the manifest fields that freeze task identity before API calls."""

    frozen_payload = []
    for task in tasks:
        frozen_payload.append(
            {
                "task_id": task["task_id"],
                "slice_spec": task["slice_spec"],
                "valid_date": task["valid_date"],
                "product_type": task["product_type"],
                "cell_id": task.get("cell_id"),
                "realization_unit_ids": task["realization_unit_ids"],
                "product_contract_hash": task["product_contract_hash"],
                "presentation_policy_version": task["presentation_policy_version"],
                "pack_id": task["pack_id"],
                "pack_hash": task["pack_hash"],
            }
        )
    return stable_hash(frozen_payload)


def build_smoke_request(
    task: dict[str, Any],
    units: list[RealizationUnit],
    contract: Any,
    task_view: Any,
    task_manifest_hash: str,
) -> SmokeRealizationRequest:
    """Build deterministic safe prompt payload for a smoke task."""

    public_units = [
        {
            "unit_id": unit.realization_unit_id,
            "claim_type": unit.claim_type,
            "canonical_safe_text": task["canonical_sentences_by_unit"][unit.realization_unit_id],
            "allowed_section_ids": [
                section_id
                for section_id, claim_types in contract.section_claim_type_map.items()
                if unit.claim_type in claim_types
            ],
        }
        for unit in sorted(units, key=lambda item: item.realization_unit_id)
    ]
    payload_without_hash = {
        "task_id": task["task_id"],
        "task_manifest_hash": task_manifest_hash,
        "product_type": task["product_type"],
        "slice_spec": task["slice_spec"],
        "pack_id": task["pack_id"],
        "pack_hash": task["pack_hash"],
        "contract_hash": contract.contract_hash,
        "presentation_policy_version": PRESENTATION_POLICY_VERSION,
        "allowed_section_ids": contract.section_order,
        "section_claim_type_map": contract.section_claim_type_map,
        "required_unit_policy": contract.required_unit_policy,
        "omitted_optional_unit_ids_allowed": contract.optional_families,
        "units": public_units,
        "task_abstention_summary": {
            "task_abstention_view_id": task_view.task_abstention_view_id,
            "abstention_count": task_view.abstention_count,
            "counts_by_reason": task_view.counts_by_reason,
            "counts_by_claim_type": task_view.counts_by_claim_type,
        },
        "output_schema": realization_plan_output_schema(),
        "instructions": smoke_prompt_instructions(),
    }
    prompt_hash = stable_hash(payload_without_hash)
    request_payload = {**payload_without_hash, "prompt_hash": prompt_hash}
    return SmokeRealizationRequest(
        request_id=f"smoke_request_{prompt_hash[:24]}",
        **request_payload,
    )


def smoke_prompt_instructions() -> list[str]:
    """Return the deterministic plan-only prompt instructions."""

    return [
        "You are not writing the engineering report.",
        "Return only a RealizationPlan JSON object matching the schema.",
        "Use only provided unit IDs.",
        "Do not generate engineering prose, recommendations, causes, risks, or interpretations.",
        "Do not create, delete, or rewrite canonical facts.",
        "All task units are required unless the contract explicitly allows omission.",
        "Your freedom is limited to valid section placement and deterministic ordering.",
    ]


def realization_plan_output_schema() -> dict[str, Any]:
    """Return the strict JSON object shape requested from a model."""

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["product_type", "sections", "omitted_optional_unit_ids"],
        "properties": {
            "product_type": {"type": "string"},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["section_id", "ordered_unit_ids"],
                    "properties": {
                        "section_id": {"type": "string"},
                        "ordered_unit_ids": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "omitted_optional_unit_ids": {"type": "array", "items": {"type": "string"}},
        },
    }


def smoke_protocol(provider_config: dict[str, Any]) -> dict[str, Any]:
    """Return protocol frozen before true smoke execution."""

    return {
        "protocol_version": SMOKE_PROTOCOL_VERSION,
        "real_model_smoke_status": "NOT_RUN",
        "model_task": "RealizationPlan selection and ordering only",
        "model_must_not_generate_engineering_text": True,
        "canonical_correctness_is_not_llm_accuracy": True,
        "retry_policy": SMOKE_RETRY_POLICY,
        "evaluation_metrics": SMOKE_EVALUATION_METRICS,
        "provider_config_public": provider_config,
        "raw_response_capture_order": [
            "save_raw_attempt",
            "parse",
            "schema_validate",
            "domain_validate_plan",
            "compose_if_accepted",
            "post_audit",
        ],
    }


def default_provider_config_public(
    *, provider: str = "openai", model: str = "UNSET_REAL_MODEL"
) -> dict[str, Any]:
    """Return public provider parameters without credentials."""

    base_url = None
    api_key_env_var = "STAGE6B_REAL_MODEL_API_KEY"
    if provider == "deepseek":
        base_url = "https://api.deepseek.com"
        api_key_env_var = "DEEPSEEK_API_KEY"
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "temperature": 0.0,
        "top_p": 1.0,
        "seed": 0,
        "reasoning_effort": "none",
        "max_output_tokens": 4096,
        "timeout_seconds": 120,
        "max_retries": SMOKE_RETRY_POLICY["max_retries"],
        "retry_on_parse_failure": SMOKE_RETRY_POLICY["retry_on_parse_failure"],
        "retry_on_schema_failure": SMOKE_RETRY_POLICY["retry_on_schema_failure"],
        "retry_on_plan_validation_failure": SMOKE_RETRY_POLICY["retry_on_plan_validation_failure"],
        "api_key_env_var": api_key_env_var,
    }


def smoke_task_valid_date_audit(task_bundles: list[dict[str, Any]]) -> list[dict[str, object]]:
    """Audit every smoke task is a single-valid-date task."""

    rows = []
    for bundle in task_bundles:
        task = bundle["smoke_task"]
        observed_dates = sorted(
            {str(lock.valid_date) for lock in bundle["pack"].locked_facts if lock.valid_date}
        )
        declared = task.get("valid_date") or ""
        rows.append(
            {
                "task_id": task["task_id"],
                "product_type": task["product_type"],
                "declared_valid_date": declared,
                "observed_valid_dates": ";".join(observed_dates),
                "distinct_count": len(observed_dates),
                "status": "PASS"
                if len(observed_dates) == 1 and declared in observed_dates
                else "FAIL",
            }
        )
    return rows


def smoke_manifest_coverage_audit(tasks: list[dict[str, Any]]) -> list[dict[str, object]]:
    """Audit smoke manifest architecture coverage before model execution."""

    product_types = {task["product_type"] for task in tasks}
    claim_types = Counter(
        claim_type
        for task in tasks
        for claim_type, count in task["claim_type_distribution"].items()
        if count
    )
    categories = {task["selection_category"] for task in tasks}
    rows = [
        _coverage("daily_review", "daily_review" in product_types),
        _coverage("forward_attention", "forward_attention" in product_types),
        _coverage("metric_review", "metric_review" in product_types),
        _coverage("forecast", claim_types["FORECAST_GEOLOGICAL_CONDITION"] > 0),
        _coverage("observed", claim_types["OBSERVED_GEOLOGICAL_CONDITION"] > 0),
        _coverage("rai", claim_types["OPERATIONAL_RESPONSE_ATTENTION"] > 0),
        _coverage("grs", claim_types["GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW"] > 0),
        _coverage("grci", claim_types["COUPLED_ATTENTION_REVIEW"] > 0),
        _coverage("forward_geological_attention", claim_types["FORWARD_GEOLOGICAL_ATTENTION"] > 0),
        _coverage("abstention", any(task["abstention_count"] > 0 for task in tasks)),
        _coverage("high_unit_task", "HIGH_UNIT_DAILY_REVIEW" in categories),
        _coverage("medium_unit_task", "MEDIUM_UNIT_DAILY_REVIEW" in categories),
        _coverage("low_unit_task", "LOW_UNIT_DAILY_REVIEW" in categories),
        _coverage("revision_representative", "REVISION_REPRESENTATIVE_CASE" in categories),
        _coverage("risk_or_anomaly", "RISK_OR_ANOMALY_SOURCE_FIELD_CASE" in categories),
        _coverage(
            "forecast_observed_coexistence",
            "OBSERVED_AND_FORECAST_COEXISTENCE" in categories,
        ),
    ]
    return rows


def dry_run_smoke(
    task_manifest: list[dict[str, Any]],
    requests: list[SmokeRealizationRequest],
    output_dir: Path,
) -> dict[str, Any]:
    """Prepare smoke execution paths without sending any API request."""

    output_dir.mkdir(parents=True, exist_ok=True)
    failures = []
    task_ids = {task["task_id"] for task in task_manifest}
    request_ids = {request.task_id for request in requests}
    if task_ids != request_ids:
        failures.append("TASK_REQUEST_MISMATCH")
    if not requests:
        failures.append("NO_REQUESTS_PREPARED")
    for request in requests:
        if not request.prompt_hash or request.prompt_hash != stable_hash(
            {
                k: v
                for k, v in request.model_dump(mode="json").items()
                if k not in {"request_id", "prompt_hash"}
            }
        ):
            failures.append("PROMPT_HASH_INVALID")
        if not request.units:
            failures.append("NO_UNITS_FOR_TASK")
    return {
        "dry_run_status": "PASS" if not failures else "FAIL",
        "api_call_count": 0,
        "tasks_loaded": len(task_manifest),
        "requests_prepared": len(requests),
        "prompt_preparation_failure": len(failures),
        "unit_resolution_failure": 0,
        "contract_resolution_failure": 0,
        "output_dir_writable": output_dir.exists(),
        "failure_codes": sorted(set(failures)),
    }


def build_manifest_bound_task_bundles(
    locks: list[Any],
    abstentions: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    task_manifest: list[dict[str, Any]],
    requests: list[SmokeRealizationRequest],
) -> tuple[list[dict[str, Any]], list[dict[str, object]]]:
    """Rebuild execution bundles from frozen manifest rows, not generated specs."""

    manifest_hash_value = smoke_manifest_hash(task_manifest)
    requests_by_task = {request.task_id: request for request in requests}
    bundles = []
    audit_rows: list[dict[str, object]] = []
    for task in task_manifest:
        task_id = str(task["task_id"])
        request = requests_by_task.get(task_id)
        bundle = build_task_bundle(
            locks,
            abstentions,
            cells,
            SliceSpec(**task["slice_spec"]),
        )
        bundle["smoke_task"] = task
        bundle_unit_ids = [unit.realization_unit_id for unit in bundle["units"]]
        request_unit_ids = [] if request is None else [unit["unit_id"] for unit in request.units]
        manifest_unit_ids = list(task["realization_unit_ids"])
        issue_codes = []
        if request is None:
            issue_codes.append("REQUEST_MISSING")
        else:
            if request.task_id != task_id:
                issue_codes.append("REQUEST_TASK_ID_MISMATCH")
            if request.task_manifest_hash != manifest_hash_value:
                issue_codes.append("REQUEST_MANIFEST_HASH_MISMATCH")
            if request.slice_spec != task["slice_spec"]:
                issue_codes.append("REQUEST_SLICE_SPEC_MISMATCH")
            if request.product_type != task["product_type"]:
                issue_codes.append("REQUEST_PRODUCT_TYPE_MISMATCH")
            if request.pack_id != task["pack_id"]:
                issue_codes.append("REQUEST_PACK_ID_MISMATCH")
            if request.pack_hash != task["pack_hash"]:
                issue_codes.append("REQUEST_PACK_HASH_MISMATCH")
            if request.presentation_policy_version != task["presentation_policy_version"]:
                issue_codes.append("REQUEST_PRESENTATION_POLICY_MISMATCH")
            if request_unit_ids != manifest_unit_ids:
                issue_codes.append("REQUEST_UNIT_IDS_MISMATCH")
        if bundle_unit_ids != manifest_unit_ids:
            issue_codes.append("REBUNDLED_UNIT_IDS_MISMATCH")
        if bundle["pack"].pack_id != task["pack_id"]:
            issue_codes.append("REBUNDLED_PACK_ID_MISMATCH")
        if bundle["pack"].pack_hash != task["pack_hash"]:
            issue_codes.append("REBUNDLED_PACK_HASH_MISMATCH")
        audit_rows.append(
            {
                "task_id": task_id,
                "issue_codes": ";".join(sorted(set(issue_codes))),
                "issue_count": len(set(issue_codes)),
                "provider_call_allowed": str(not issue_codes).lower(),
                "status": "PASS" if not issue_codes else "FAIL",
            }
        )
        bundles.append(bundle)
    return bundles, audit_rows


def parse_provider_plan(raw_text: str) -> tuple[MinimalProviderPlan | None, list[str], str]:
    """Parse pure JSON provider payload without repair or markdown extraction."""

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return None, ["PARSE_FAILURE"], str(exc)
    if not isinstance(payload, dict):
        return None, ["SCHEMA_NOT_OBJECT"], ""
    try:
        return MinimalProviderPlan(**payload), [], ""
    except ValidationError as exc:
        return None, ["SCHEMA_VALIDATION_FAILURE"], str(exc)


def materialize_realization_plan(
    minimal_plan: MinimalProviderPlan,
    pack: Any,
    task_view: Any,
    contract: Any,
    *,
    provider_name: str,
) -> RealizationPlan:
    """Inject authoritative metadata into a model-supplied minimal plan."""

    sections = [
        RealizationPlanSection(
            section_id=section.section_id,
            ordered_unit_ids=section.ordered_unit_ids,
        )
        for section in minimal_plan.sections
    ]
    payload = {
        "pack_id": pack.pack_id,
        "task_abstention_view_id": task_view.task_abstention_view_id,
        "product_type": minimal_plan.product_type,
        "sections": [section.model_dump(mode="json") for section in sections],
        "omitted_optional_unit_ids": minimal_plan.omitted_optional_unit_ids,
        "contract_hash": contract.contract_hash,
        "pack_hash": pack.pack_hash,
        "presentation_policy_version": PRESENTATION_POLICY_VERSION,
        "provider_name": provider_name,
    }
    return RealizationPlan(
        plan_id=stable_id("realization_plan", payload),
        pack_id=pack.pack_id,
        task_abstention_view_id=task_view.task_abstention_view_id,
        product_type=minimal_plan.product_type,
        sections=sections,
        omitted_optional_unit_ids=minimal_plan.omitted_optional_unit_ids,
        contract_hash=contract.contract_hash,
        pack_hash=pack.pack_hash,
        presentation_policy_version=PRESENTATION_POLICY_VERSION,
        provider_name=provider_name,
        plan_hash=stable_hash(payload),
    )


def execution_protocol(
    task_manifest_hash_value: str,
    provider_config: dict[str, Any],
) -> dict[str, Any]:
    """Return execution protocol locked before the first provider call."""

    prompt_template = {
        "instructions": smoke_prompt_instructions(),
        "output_schema": realization_plan_output_schema(),
    }
    protocol = {
        "protocol_version": f"{SMOKE_PROTOCOL_VERSION}_execution",
        "task_manifest_hash": task_manifest_hash_value,
        "provider": provider_config["provider"],
        "model": provider_config["model"],
        "base_url": {
            "requested": provider_config.get("base_url"),
            "applied": provider_config.get("base_url"),
            "supported": provider_config.get("base_url") is not None,
        },
        "temperature": {
            "requested": provider_config["temperature"],
            "applied": provider_config["temperature"],
            "supported": True,
        },
        "top_p": {
            "requested": provider_config["top_p"],
            "applied": provider_config["top_p"],
            "supported": True,
        },
        "max_output_tokens": {
            "requested": provider_config["max_output_tokens"],
            "applied": provider_config["max_output_tokens"],
            "supported": True,
        },
        "seed": {"requested": provider_config["seed"], "applied": None, "supported": False},
        "reasoning_effort": {
            "requested": provider_config["reasoning_effort"],
            "applied": provider_config["reasoning_effort"],
            "supported": True,
        },
        "timeout_seconds": {
            "requested": provider_config["timeout_seconds"],
            "applied": None,
            "supported": False,
        },
        "max_retries": SMOKE_RETRY_POLICY["max_retries"],
        "parse_policy": "STRICT_PURE_JSON_NO_REPAIR",
        "schema_policy": "MINIMAL_PROVIDER_PLAN_EXTRA_FORBID",
        "validation_policy": "DETERMINISTIC_VALIDATE_PLAN_NO_AUTOCORRECTION",
        "composition_policy": "COMPOSE_ONLY_PARSE_SCHEMA_DOMAIN_VALID",
        "prompt_template_hash": stable_hash(prompt_template),
    }
    return {**protocol, "execution_protocol_hash": stable_hash(protocol)}


def execution_protocol_file_sha256(protocol_path: Path) -> str:
    """Return byte SHA-256 for a written execution protocol artifact."""

    import hashlib

    return hashlib.sha256(protocol_path.read_bytes()).hexdigest()


def execute_smoke_tasks(
    task_bundles: list[dict[str, Any]],
    requests: list[SmokeRealizationRequest],
    provider: Any,
    output_dir: Path,
    protocol: dict[str, Any],
    *,
    execution_manifest_binding_rows: list[dict[str, object]] | None = None,
    execution_id: str | None = None,
    composer_tamper_text: str | None = None,
    allow_overwrite: bool = False,
) -> dict[str, Any]:
    """Execute smoke tasks through a provider with raw-first persistence."""

    if execution_manifest_binding_rows and any(
        row.get("status") != "PASS" for row in execution_manifest_binding_rows
    ):
        msg = "execution manifest binding failed before provider call"
        raise RuntimeError(msg)
    execution_id = execution_id or stable_id(
        "stage6b_smoke_execution",
        {
            "task_manifest_hash": protocol["task_manifest_hash"],
            "execution_protocol_hash": protocol["execution_protocol_hash"],
            "provider": protocol["provider"],
            "model": protocol["model"],
        },
    )
    run_dir = output_dir / "runs" / execution_id
    if run_dir.exists() and allow_overwrite:
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json(run_dir / "execution_protocol.json", protocol)
    write_jsonl(run_dir / "materialized_plans.jsonl", [])
    write_jsonl(run_dir / "composition_results.jsonl", [])
    write_jsonl(run_dir / "parsed_plans.jsonl", [])
    write_csv(run_dir / "plan_validation_results.csv", [])
    write_csv(run_dir / "post_realization_results.csv", [])
    raw_path = run_dir / "raw_model_outputs.jsonl"
    failure_path = run_dir / "provider_failure_records.jsonl"
    raw_path.write_text("", encoding="utf-8")
    failure_path.write_text("", encoding="utf-8")
    parsed_rows: list[dict[str, Any]] = []
    materialized_rows: list[dict[str, Any]] = []
    validation_rows: list[dict[str, object]] = []
    composition_rows: list[dict[str, Any]] = []
    post_rows: list[dict[str, object]] = []
    attempt_results: list[SmokeAttemptResult] = []
    bundles_by_task = {bundle["smoke_task"]["task_id"]: bundle for bundle in task_bundles}
    for request in requests:
        bundle = bundles_by_task[request.task_id]
        raw_ref = ""
        try:
            attempt = provider.request_plan(request)
            raw_record = _raw_attempt_record(execution_id, request, attempt, protocol)
            raw_ref = raw_record["raw_attempt_id"]
            _append_jsonl(raw_path, raw_record)
            if not attempt.transport_success:
                _append_jsonl(failure_path, raw_record)
                result = _attempt_result(
                    execution_id,
                    request.task_id,
                    raw_ref,
                    provider_kind=attempt.provider_kind,
                    provider_attempted=attempt.provider_attempted,
                    transport_success=False,
                    real_api_attempted=attempt.real_api_attempted,
                    real_api_transport_success=attempt.real_api_transport_success,
                    raw_response_available=False,
                    parse_valid=False,
                    schema_valid=False,
                    domain_plan_valid=False,
                    parse_error=attempt.provider_error_type or "PROVIDER_TRANSPORT_FAILURE",
                    schema_error_codes=[],
                    plan_violation_codes=["PROVIDER_TRANSPORT_FAILURE"],
                )
                attempt_results.append(result)
                continue
        except Exception as exc:
            raw_record = _provider_error_record(execution_id, request, exc, protocol, provider)
            raw_ref = raw_record["raw_attempt_id"]
            _append_jsonl(raw_path, raw_record)
            _append_jsonl(failure_path, raw_record)
            result = _attempt_result(
                execution_id,
                request.task_id,
                raw_ref,
                provider_kind=str(raw_record["provider_kind"]),
                provider_attempted=True,
                transport_success=False,
                real_api_attempted=bool(raw_record["real_api_attempted"]),
                real_api_transport_success=False,
                raw_response_available=False,
                parse_valid=False,
                schema_valid=False,
                domain_plan_valid=False,
                parse_error=raw_record["provider_error_type"],
                schema_error_codes=[],
                plan_violation_codes=["PROVIDER_TRANSPORT_FAILURE"],
            )
            attempt_results.append(result)
            continue
        if attempt.raw_response_text is None:
            result = _attempt_result(
                execution_id,
                request.task_id,
                raw_ref,
                provider_kind=attempt.provider_kind,
                provider_attempted=attempt.provider_attempted,
                transport_success=False,
                real_api_attempted=attempt.real_api_attempted,
                real_api_transport_success=attempt.real_api_transport_success,
                raw_response_available=False,
                parse_valid=False,
                schema_valid=False,
                domain_plan_valid=False,
                parse_error=attempt.provider_error_type or "PROVIDER_TRANSPORT_FAILURE",
                schema_error_codes=[],
                plan_violation_codes=["PROVIDER_TRANSPORT_FAILURE"],
            )
            attempt_results.append(result)
            continue
        minimal, error_codes, parse_error = parse_provider_plan(attempt.raw_response_text)
        parse_valid = minimal is not None or error_codes == ["SCHEMA_VALIDATION_FAILURE"]
        schema_valid = minimal is not None
        parsed_rows.append(
            {
                "execution_id": execution_id,
                "task_id": request.task_id,
                "raw_attempt_id": raw_ref,
                "parse_valid": parse_valid,
                "schema_valid": schema_valid,
                "schema_error_codes": error_codes,
                "parse_error": parse_error,
                "minimal_plan": None if minimal is None else minimal.model_dump(mode="json"),
            }
        )
        if minimal is None:
            result = _attempt_result(
                execution_id,
                request.task_id,
                raw_ref,
                provider_kind=attempt.provider_kind,
                provider_attempted=attempt.provider_attempted,
                transport_success=attempt.transport_success,
                real_api_attempted=attempt.real_api_attempted,
                real_api_transport_success=attempt.real_api_transport_success,
                raw_response_available=attempt.raw_response_available,
                parse_valid=parse_valid,
                schema_valid=False,
                domain_plan_valid=False,
                parse_error=parse_error,
                schema_error_codes=error_codes,
                plan_violation_codes=[],
            )
            attempt_results.append(result)
            continue
        plan = materialize_realization_plan(
            minimal,
            bundle["pack"],
            bundle["task_view"],
            bundle["contract"],
            provider_name=attempt.provider,
        )
        materialized_rows.append(plan.model_dump(mode="json"))
        issues = validate_plan(
            plan,
            bundle["units"],
            bundle["contract"],
            bundle["pack"].pack_id,
            bundle["pack"].pack_hash,
            bundle["task_view"].task_abstention_view_id,
        )
        domain_valid = not issues
        validation_rows.append(
            {
                "execution_id": execution_id,
                "task_id": request.task_id,
                "plan_id": plan.plan_id,
                "plan_hash": plan.plan_hash,
                "plan_valid": str(domain_valid).lower(),
                "violation_codes": ";".join(issues),
            }
        )
        if not domain_valid:
            result = _attempt_result(
                execution_id,
                request.task_id,
                raw_ref,
                provider_kind=attempt.provider_kind,
                provider_attempted=attempt.provider_attempted,
                transport_success=attempt.transport_success,
                real_api_attempted=attempt.real_api_attempted,
                real_api_transport_success=attempt.real_api_transport_success,
                raw_response_available=attempt.raw_response_available,
                parse_valid=True,
                schema_valid=True,
                domain_plan_valid=False,
                parse_error="",
                schema_error_codes=[],
                plan_violation_codes=issues,
                materialized_plan_id=plan.plan_id,
                materialized_plan_hash=plan.plan_hash,
            )
            attempt_results.append(result)
            continue
        sentences_by_unit = {
            sentence.realization_unit_id: sentence for sentence in bundle["sentences"]
        }
        composed = compose_realization(
            plan,
            sentences_by_unit,
            bundle["task_view"],
            bundle["contract"],
        )
        if composer_tamper_text:
            composed = ComposedRealization(
                **{
                    **composed.model_dump(mode="json"),
                    "text": composed.text + "\n" + composer_tamper_text,
                    "realization_hash": "tampered_for_execution_layer_test",
                }
            )
        post_issues = audit_post_realization(composed, bundle["sentences"])
        composition_rows.append(composed.model_dump(mode="json"))
        post_rows.append(
            {
                "execution_id": execution_id,
                "task_id": request.task_id,
                "composed_realization_id": composed.composed_realization_id,
                "post_audit_issue_codes": ";".join(post_issues),
                "post_audit_status": "PASS" if not post_issues else "FAIL",
            }
        )
        result = _attempt_result(
            execution_id,
            request.task_id,
            raw_ref,
            provider_kind=attempt.provider_kind,
            provider_attempted=attempt.provider_attempted,
            transport_success=attempt.transport_success,
            real_api_attempted=attempt.real_api_attempted,
            real_api_transport_success=attempt.real_api_transport_success,
            raw_response_available=attempt.raw_response_available,
            parse_valid=True,
            schema_valid=True,
            domain_plan_valid=True,
            parse_error="",
            schema_error_codes=[],
            plan_violation_codes=[],
            materialized_plan_id=plan.plan_id,
            materialized_plan_hash=plan.plan_hash,
            composition_status="RUN",
            composed_realization_id=composed.composed_realization_id,
            post_audit_status="PASS" if not post_issues else "FAIL",
            post_audit_issue_codes=post_issues,
        )
        attempt_results.append(result)
    write_jsonl(run_dir / "parsed_plans.jsonl", parsed_rows)
    write_jsonl(run_dir / "materialized_plans.jsonl", materialized_rows)
    write_csv(run_dir / "plan_validation_results.csv", validation_rows)
    write_jsonl(run_dir / "composition_results.jsonl", composition_rows)
    write_csv(run_dir / "post_realization_results.csv", post_rows)
    write_jsonl(
        run_dir / "attempt_results.jsonl",
        [row.model_dump(mode="json") for row in attempt_results],
    )
    summary = smoke_execution_summary(execution_id, attempt_results, len(requests))
    write_csv(run_dir / "smoke_summary.csv", [summary])
    write_csv(run_dir / "accounting_audit.csv", accounting_audit_rows(summary, attempt_results))
    write_json(run_dir / "status.json", summary)
    return {"execution_id": execution_id, "run_dir": run_dir.as_posix(), **summary}


def smoke_execution_summary(
    execution_id: str, attempt_results: list[Any], task_count: int
) -> dict[str, object]:
    """Compute smoke metrics from persisted execution result rows."""

    provider_request_attempt_count = sum(row.provider_attempted for row in attempt_results)
    provider_transport_success_count = sum(row.transport_success for row in attempt_results)
    provider_transport_failure_count = sum(
        row.provider_attempted and not row.transport_success for row in attempt_results
    )
    real_api_request_attempt_count = sum(row.real_api_attempted for row in attempt_results)
    real_api_transport_success_count = sum(
        row.real_api_attempted and row.real_api_transport_success for row in attempt_results
    )
    real_api_transport_failure_count = sum(
        row.real_api_attempted and not row.real_api_transport_success for row in attempt_results
    )
    parse_valid = sum(row.parse_valid for row in attempt_results if row.transport_success)
    schema_valid = sum(row.schema_valid for row in attempt_results)
    plan_valid = sum(row.domain_plan_valid for row in attempt_results)
    composition_count = sum(row.composition_status == "RUN" for row in attempt_results)
    post_pass = sum(row.post_audit_status == "PASS" for row in attempt_results)
    plan_codes = Counter(code for row in attempt_results for code in row.plan_violation_codes)
    return {
        "execution_id": execution_id,
        "task_count": task_count,
        "provider_attempt_count": provider_request_attempt_count,
        "provider_request_attempt_count": provider_request_attempt_count,
        "provider_transport_success_count": provider_transport_success_count,
        "provider_transport_failure_count": provider_transport_failure_count,
        "real_api_call_count": real_api_request_attempt_count,
        "real_api_request_attempt_count": real_api_request_attempt_count,
        "real_api_transport_success_count": real_api_transport_success_count,
        "real_api_transport_failure_count": real_api_transport_failure_count,
        "provider_transport_success_rate_n": provider_request_attempt_count,
        "provider_transport_success_rate": _rate(
            provider_transport_success_count, provider_request_attempt_count
        ),
        "real_api_transport_success_rate_n": real_api_request_attempt_count,
        "real_api_transport_success_rate": _rate(
            real_api_transport_success_count, real_api_request_attempt_count
        ),
        "first_attempt_parse_valid_rate_n": provider_transport_success_count,
        "first_attempt_parse_valid_rate": _rate(parse_valid, provider_transport_success_count),
        "first_attempt_schema_valid_rate_n": provider_transport_success_count,
        "first_attempt_schema_valid_rate": _rate(schema_valid, provider_transport_success_count),
        "first_attempt_plan_acceptance_rate_n": provider_transport_success_count,
        "first_attempt_plan_acceptance_rate": _rate(plan_valid, provider_transport_success_count),
        "plan_acceptance_rate_over_schema_valid_n": schema_valid,
        "plan_acceptance_rate_over_schema_valid": _rate(plan_valid, schema_valid),
        "final_plan_acceptance_rate": _rate(plan_valid, provider_transport_success_count),
        "unknown_unit_reference_rate": _rate(
            plan_codes["UNKNOWN_UNIT"], provider_transport_success_count
        ),
        "out_of_task_unit_reference_rate": _rate(
            plan_codes["OUT_OF_TASK_UNIT"], provider_transport_success_count
        ),
        "duplicate_unit_rate": _rate(
            plan_codes["DUPLICATE_UNIT_REFERENCE"], provider_transport_success_count
        ),
        "required_unit_omission_rate": _rate(
            plan_codes["REQUIRED_UNIT_OMISSION"], provider_transport_success_count
        ),
        "invalid_section_rate": _rate(
            plan_codes["INVALID_SECTION"], provider_transport_success_count
        ),
        "product_mismatch_rate": _rate(
            plan_codes["PRODUCT_TYPE_MISMATCH"], provider_transport_success_count
        ),
        "validator_interception_count": sum(
            bool(row.plan_violation_codes) for row in attempt_results
        ),
        "composition_count": composition_count,
        "post_audit_pass_rate": _rate(post_pass, composition_count),
        "post_audit_violation_count": sum(
            bool(row.post_audit_issue_codes) for row in attempt_results
        ),
        "trace_coverage": _rate(post_pass, composition_count),
    }


def accounting_audit_rows(
    summary: dict[str, object], attempt_results: list[Any]
) -> list[dict[str, object]]:
    """Recompute smoke accounting metrics from attempt records."""

    recomputed: dict[str, object] = smoke_execution_summary(
        str(summary["execution_id"]),
        attempt_results,
        _object_to_int(summary["task_count"]),
    )
    metrics = [
        "provider_request_attempt_count",
        "provider_transport_success_count",
        "provider_transport_failure_count",
        "provider_transport_success_rate",
        "provider_transport_success_rate_n",
        "real_api_request_attempt_count",
        "real_api_transport_success_count",
        "real_api_transport_failure_count",
        "real_api_transport_success_rate",
        "real_api_transport_success_rate_n",
        "first_attempt_parse_valid_rate",
        "first_attempt_parse_valid_rate_n",
        "first_attempt_schema_valid_rate",
        "first_attempt_schema_valid_rate_n",
        "first_attempt_plan_acceptance_rate",
        "first_attempt_plan_acceptance_rate_n",
        "plan_acceptance_rate_over_schema_valid",
        "plan_acceptance_rate_over_schema_valid_n",
        "composition_count",
        "post_audit_violation_count",
    ]
    rows = []
    for metric in metrics:
        reported = summary.get(metric)
        value = recomputed.get(metric)
        diff = _metric_diff(reported, value)
        rows.append(
            {
                "metric": metric,
                "reported_value": "" if reported is None else reported,
                "recomputed_value": "" if value is None else value,
                "diff": diff,
                "status": "PASS" if diff == 0.0 else "FAIL",
            }
        )
    return rows


def credential_literal_audit(paths: list[Path]) -> list[dict[str, object]]:
    """Scan Stage6B files for obvious committed credential literals."""

    forbidden_patterns = [
        r"sk-[A-Za-z0-9_-]{20,}",
        r"api_key\s*=\s*['\"][^'\"]{8,}",
        r"OPENAI_API_KEY\s*=\s*['\"][^'\"]{8,}",
        r"STAGE6B_REAL_MODEL_API_KEY\s*=\s*['\"][^'\"]{8,}",
    ]
    rows: list[dict[str, object]] = []
    for path in sorted(paths):
        if not path.exists() or path.is_dir():
            continue
        text = path.read_text(encoding="utf-8")
        matches = [pattern for pattern in forbidden_patterns if re.search(pattern, text)]
        rows.append(
            {
                "path": path.as_posix(),
                "matched_tokens": ";".join(matches),
                "status": "PASS" if not matches else "FAIL",
            }
        )
    return rows


def group_member_semantic_equivalence_audit(
    task_bundles: list[dict[str, Any]],
) -> list[dict[str, object]]:
    """Check multi-member geological units group only semantically identical facts."""

    rows = []
    for bundle in task_bundles:
        locks_by_id = {lock.fact_lock_id: lock for lock in bundle["pack"].locked_facts}
        for unit in bundle["units"]:
            if len(unit.member_fact_lock_ids) <= 1:
                continue
            if unit.claim_type not in {
                "FORECAST_GEOLOGICAL_CONDITION",
                "OBSERVED_GEOLOGICAL_CONDITION",
            }:
                continue
            members = [locks_by_id[fact_id] for fact_id in unit.member_fact_lock_ids]
            first = members[0]
            expected = {
                "claim_type": first.claim_type,
                "claim_modality": first.claim_modality,
                "source_evidence_id": first.claim_value.get("source_evidence_id"),
                "attribute_name": first.claim_value.get("attribute_name"),
                "normalized_value": first.claim_value.get("normalized_value"),
                "required_qualifiers": sorted(first.required_qualifiers),
                "allowed_rendering_semantics": first.allowed_rendering_semantics,
                "prohibited_transformations": first.prohibited_transformations,
            }
            mismatches = 0
            for member in members[1:]:
                current = {
                    "claim_type": member.claim_type,
                    "claim_modality": member.claim_modality,
                    "source_evidence_id": member.claim_value.get("source_evidence_id"),
                    "attribute_name": member.claim_value.get("attribute_name"),
                    "normalized_value": member.claim_value.get("normalized_value"),
                    "required_qualifiers": sorted(member.required_qualifiers),
                    "allowed_rendering_semantics": member.allowed_rendering_semantics,
                    "prohibited_transformations": member.prohibited_transformations,
                }
                mismatches += int(current != expected)
            rows.append(
                {
                    "task_id": bundle["smoke_task"]["task_id"],
                    "realization_unit_id": unit.realization_unit_id,
                    "member_count": len(unit.member_fact_lock_ids),
                    "mismatch_count": mismatches,
                    "status": "PASS" if mismatches == 0 else "FAIL",
                }
            )
    return rows


def _legal_minimal_plan_payload(request: SmokeRealizationRequest) -> dict[str, Any]:
    sections = []
    for section_id in request.allowed_section_ids:
        claim_types = set(request.section_claim_type_map.get(section_id, []))
        ordered_unit_ids = sorted(
            unit["unit_id"] for unit in request.units if unit["claim_type"] in claim_types
        )
        if ordered_unit_ids:
            sections.append({"section_id": section_id, "ordered_unit_ids": ordered_unit_ids})
    return {
        "product_type": request.product_type,
        "sections": sections,
        "omitted_optional_unit_ids": [],
    }


def _raw_attempt_record(
    execution_id: str,
    request: SmokeRealizationRequest,
    attempt: ProviderAttempt,
    protocol: dict[str, Any],
) -> dict[str, Any]:
    raw_attempt_id = stable_id(
        "raw_provider_attempt",
        {
            "execution_id": execution_id,
            "task_id": request.task_id,
            "attempt_number": attempt.attempt_number,
            "request_id": request.request_id,
            "prompt_hash": request.prompt_hash,
            "raw_response_text": attempt.raw_response_text,
        },
    )
    response_timestamp = datetime.now(tz=UTC).isoformat()
    if attempt.raw_response_payload and attempt.raw_response_payload.get("response_timestamp"):
        response_timestamp = str(attempt.raw_response_payload["response_timestamp"])
    if not attempt.transport_success:
        response_timestamp = attempt.request_timestamp
    return {
        "raw_attempt_id": raw_attempt_id,
        "execution_id": execution_id,
        "task_id": request.task_id,
        "attempt_number": attempt.attempt_number,
        "provider_kind": attempt.provider_kind,
        "provider": attempt.provider,
        "model": attempt.model_name,
        "request_id": request.request_id,
        "request_timestamp": attempt.request_timestamp,
        "response_timestamp": response_timestamp,
        "prompt_hash": request.prompt_hash,
        "task_manifest_hash": request.task_manifest_hash,
        "execution_protocol_hash": protocol["execution_protocol_hash"],
        "raw_response_available": attempt.raw_response_available,
        "provider_attempted": attempt.provider_attempted,
        "transport_success": attempt.transport_success,
        "real_api_attempted": attempt.real_api_attempted,
        "real_api_transport_success": attempt.real_api_transport_success,
        "raw_response_text": attempt.raw_response_text,
        "raw_response_payload": attempt.raw_response_payload,
        "latency_ms": attempt.latency_ms,
        "token_usage": attempt.token_usage,
        "provider_status": "SUCCESS" if attempt.transport_success else "TRANSPORT_ERROR",
        "provider_error_type": attempt.provider_error_type,
        "provider_error_message": attempt.provider_error_message,
    }


def _provider_error_record(
    execution_id: str,
    request: SmokeRealizationRequest,
    exc: Exception,
    protocol: dict[str, Any],
    provider: Any,
) -> dict[str, Any]:
    provider_kind = provider_kind_for_provider(provider)
    provider_name = str(getattr(provider, "provider_name", "unknown"))
    model_name = str(getattr(provider, "model_name", ""))
    config = getattr(provider, "config", None)
    if config is not None:
        provider_name = str(getattr(config, "model_provider", provider_name))
        model_name = str(getattr(config, "model_name", model_name))
    timestamp = str(getattr(provider, "timestamp", datetime.now(tz=UTC).isoformat()))
    raw_attempt_id = stable_id(
        "raw_provider_attempt",
        {
            "execution_id": execution_id,
            "task_id": request.task_id,
            "attempt_number": 1,
            "request_id": request.request_id,
            "provider_error_type": exc.__class__.__name__,
            "provider_error_message": str(exc),
        },
    )
    return {
        "raw_attempt_id": raw_attempt_id,
        "execution_id": execution_id,
        "task_id": request.task_id,
        "attempt_number": 1,
        "provider_kind": provider_kind,
        "provider": provider_name,
        "model": model_name,
        "request_id": request.request_id,
        "request_timestamp": timestamp,
        "response_timestamp": timestamp,
        "prompt_hash": request.prompt_hash,
        "task_manifest_hash": request.task_manifest_hash,
        "execution_protocol_hash": protocol["execution_protocol_hash"],
        "provider_attempted": True,
        "transport_success": False,
        "real_api_attempted": provider_kind == "REAL_API",
        "real_api_transport_success": False,
        "raw_response_available": False,
        "raw_response_text": None,
        "raw_response_payload": None,
        "latency_ms": None,
        "token_usage": None,
        "provider_status": "TRANSPORT_ERROR",
        "provider_error_type": exc.__class__.__name__,
        "provider_error_message": str(exc),
    }


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _attempt_result(
    execution_id: str,
    task_id: str,
    raw_ref: str,
    *,
    provider_kind: str,
    provider_attempted: bool,
    transport_success: bool,
    real_api_attempted: bool,
    real_api_transport_success: bool,
    raw_response_available: bool,
    parse_valid: bool,
    schema_valid: bool,
    domain_plan_valid: bool,
    parse_error: str,
    schema_error_codes: list[str],
    plan_violation_codes: list[str],
    materialized_plan_id: str | None = None,
    materialized_plan_hash: str | None = None,
    composition_status: str = "NOT_RUN",
    composed_realization_id: str | None = None,
    post_audit_status: str = "NOT_RUN",
    post_audit_issue_codes: list[str] | None = None,
) -> SmokeAttemptResult:
    return SmokeAttemptResult(
        execution_id=execution_id,
        task_id=task_id,
        attempt_number=1,
        raw_attempt_ref=raw_ref,
        provider_kind=provider_kind,
        provider_attempted=provider_attempted,
        transport_success=transport_success,
        real_api_attempted=real_api_attempted,
        real_api_transport_success=real_api_transport_success,
        raw_response_available=raw_response_available,
        parse_valid=parse_valid,
        schema_valid=schema_valid,
        domain_plan_valid=domain_plan_valid,
        parse_error=parse_error,
        schema_error_codes=schema_error_codes,
        plan_violation_codes=plan_violation_codes,
        materialized_plan_id=materialized_plan_id,
        materialized_plan_hash=materialized_plan_hash,
        composition_status=composition_status,
        composed_realization_id=composed_realization_id,
        post_audit_status=post_audit_status,
        post_audit_issue_codes=post_audit_issue_codes or [],
    )


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _metric_diff(reported: object, recomputed: object) -> float:
    if reported is None and recomputed is None:
        return 0.0
    try:
        return abs(_object_to_float(reported) - _object_to_float(recomputed))
    except (TypeError, ValueError):
        return 0.0 if reported == recomputed else 1.0


def _object_to_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    msg = f"cannot convert {type(value).__name__} to int"
    raise TypeError(msg)


def _object_to_float(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        return float(value)
    msg = f"cannot convert {type(value).__name__} to float"
    raise TypeError(msg)


def provider_kind_for_provider(provider: Any) -> str:
    """Return deterministic accounting kind for a smoke provider."""

    kind = getattr(provider, "provider_kind", None)
    if kind in {"MOCK", "REAL_API"}:
        return str(kind)
    config = getattr(provider, "config", None)
    if config is not None and getattr(config, "model_provider", None) in {"openai", "deepseek"}:
        return "REAL_API"
    if getattr(provider, "provider_name", "") == "mock":
        return "MOCK"
    return "REAL_API"


def _coverage(check_name: str, passed: bool) -> dict[str, object]:
    return {
        "check_name": check_name,
        "actual": int(passed),
        "expected": 1,
        "status": "PASS" if passed else "FAIL",
    }
