"""DeepSeek Responses API adapter boundary for Stage6B smoke.

The adapter uses the OpenAI Python SDK only as an HTTP client for DeepSeek's
OpenAI-compatible Responses API. It performs no engineering validation.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from typing import Any, cast

from tbm_twin.realization.providers.configured_llm import LLMProviderConfig, ProviderAttempt
from tbm_twin.realization.stage6b_smoke import SmokeRealizationRequest

DEEPSEEK_RESPONSES_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_RESPONSES_SUPPORTED_MODEL = "deepseek-v4-flash"


class DeepSeekResponsesPlanProvider:
    """Optional DeepSeek real smoke adapter; never used by dry-run."""

    provider_name = "deepseek"
    provider_kind = "REAL_API"

    def __init__(self, config: LLMProviderConfig) -> None:
        self.config = config
        self.provider_name = config.model_provider

    def request_plan(self, request: SmokeRealizationRequest) -> ProviderAttempt:
        """Send one request through DeepSeek Responses API when explicitly invoked."""

        if self.config.model_name != DEEPSEEK_RESPONSES_SUPPORTED_MODEL:
            msg = f"DeepSeek Responses API smoke supports only {DEEPSEEK_RESPONSES_SUPPORTED_MODEL}"
            raise RuntimeError(msg)
        api_key = os.environ.get(self.config.api_key_env_var)
        if not api_key:
            msg = f"missing API key environment variable: {self.config.api_key_env_var}"
            raise RuntimeError(msg)
        try:
            from openai import OpenAI
        except ImportError as exc:
            msg = "openai SDK is required only for explicit DeepSeek smoke execution"
            raise RuntimeError(msg) from exc

        prompt_payload = request.model_dump(mode="json")
        started = time.monotonic()
        timestamp = datetime.now(tz=UTC).isoformat()
        client = OpenAI(
            api_key=api_key,
            base_url=self.config.base_url,
            max_retries=self.config.max_retries,
        )
        try:
            response = cast(Any, client.responses).create(
                model=self.config.model_name,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                max_output_tokens=self.config.max_output_tokens,
                reasoning={"effort": self.config.reasoning_effort},
                input=[
                    {
                        "role": "system",
                        "content": "Return only the requested RealizationPlan JSON object.",
                    },
                    {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)},
                ],
            )
        except Exception as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            return _attempt(
                request,
                self.config,
                timestamp,
                latency_ms,
                transport_success=False,
                raw_text=None,
                raw_payload=None,
                token_usage=None,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        raw_payload = response.model_dump(mode="json")
        raw_text = getattr(response, "output_text", "") or json.dumps(
            raw_payload, ensure_ascii=False
        )
        token_usage: dict[str, Any] | None = None
        if raw_payload.get("usage"):
            token_usage = raw_payload["usage"]
        return _attempt(
            request,
            self.config,
            timestamp,
            latency_ms,
            transport_success=True,
            raw_text=raw_text,
            raw_payload=raw_payload,
            token_usage=token_usage,
            error_type="",
            error_message="",
        )


def _attempt(
    request: SmokeRealizationRequest,
    config: LLMProviderConfig,
    timestamp: str,
    latency_ms: int,
    *,
    transport_success: bool,
    raw_text: str | None,
    raw_payload: dict[str, Any] | None,
    token_usage: dict[str, Any] | None,
    error_type: str,
    error_message: str,
) -> ProviderAttempt:
    return ProviderAttempt(
        attempt_index=0,
        attempt_number=1,
        provider_kind="REAL_API",
        provider=config.model_provider,
        request_id=request.request_id,
        model_name=config.model_name,
        request_timestamp=timestamp,
        pack_id=request.pack_id,
        contract_hash=request.contract_hash,
        task_scope=request.slice_spec,
        input_unit_ids=[unit["unit_id"] for unit in request.units],
        provider_attempted=True,
        transport_success=transport_success,
        real_api_attempted=True,
        real_api_transport_success=transport_success,
        raw_response_available=transport_success,
        raw_response_text=raw_text,
        raw_response_payload=raw_payload,
        raw_response=raw_text,
        parse_status="NOT_PARSED_BY_PROVIDER_ADAPTER"
        if transport_success
        else "PROVIDER_TRANSPORT_FAILURE",
        parsed_payload=None,
        schema_valid=False,
        validation_violations=[] if transport_success else ["PROVIDER_TRANSPORT_FAILURE"],
        provider_error_type=error_type,
        provider_error_message=error_message,
        latency_ms=latency_ms,
        token_usage=token_usage,
    )
