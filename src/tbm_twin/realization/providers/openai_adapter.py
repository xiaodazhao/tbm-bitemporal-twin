"""OpenAI transport adapter boundary for Stage6B smoke.

The adapter is intentionally optional. It performs no engineering validation and
imports no vendor SDK at module import time, so deterministic tests remain
network-free.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from typing import Any, cast

from tbm_twin.realization.providers.configured_llm import LLMProviderConfig, ProviderAttempt
from tbm_twin.realization.stage6b_smoke import SmokeRealizationRequest


class OpenAIPlanProvider:
    """Optional real smoke adapter; not used by dry-run or domain correctness."""

    def __init__(self, config: LLMProviderConfig) -> None:
        self.config = config
        self.provider_name = config.model_provider

    def request_plan(self, request: SmokeRealizationRequest) -> ProviderAttempt:
        """Send one request through OpenAI Responses API when explicitly invoked."""

        api_key = os.environ.get(self.config.api_key_env_var)
        if not api_key:
            msg = f"missing API key environment variable: {self.config.api_key_env_var}"
            raise RuntimeError(msg)
        try:
            from openai import OpenAI
        except ImportError as exc:
            msg = "openai SDK is required only for explicit real-model smoke execution"
            raise RuntimeError(msg) from exc

        prompt_payload = request.model_dump(mode="json")
        started = time.monotonic()
        timestamp = datetime.now(tz=UTC).isoformat()
        client = OpenAI(api_key=api_key, max_retries=self.config.max_retries)
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
            return ProviderAttempt(
                attempt_index=0,
                attempt_number=1,
                provider_kind="REAL_API",
                provider=self.config.model_provider,
                request_id=request.request_id,
                model_name=self.config.model_name,
                request_timestamp=timestamp,
                pack_id=request.pack_id,
                contract_hash=request.contract_hash,
                task_scope=request.slice_spec,
                input_unit_ids=[unit["unit_id"] for unit in request.units],
                provider_attempted=True,
                transport_success=False,
                real_api_attempted=True,
                real_api_transport_success=False,
                raw_response_available=False,
                raw_response_text=None,
                raw_response_payload=None,
                raw_response=None,
                parse_status="PROVIDER_TRANSPORT_FAILURE",
                parsed_payload=None,
                schema_valid=False,
                validation_violations=["PROVIDER_TRANSPORT_FAILURE"],
                provider_error_type=exc.__class__.__name__,
                provider_error_message=str(exc),
                latency_ms=latency_ms,
                token_usage=None,
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        raw_payload = response.model_dump(mode="json")
        raw_text = getattr(response, "output_text", "") or json.dumps(
            raw_payload, ensure_ascii=False
        )
        token_usage: dict[str, Any] | None = None
        if raw_payload.get("usage"):
            token_usage = raw_payload["usage"]
        return ProviderAttempt(
            attempt_index=0,
            attempt_number=1,
            provider_kind="REAL_API",
            provider=self.config.model_provider,
            request_id=request.request_id,
            model_name=self.config.model_name,
            request_timestamp=timestamp,
            pack_id=request.pack_id,
            contract_hash=request.contract_hash,
            task_scope=request.slice_spec,
            input_unit_ids=[unit["unit_id"] for unit in request.units],
            provider_attempted=True,
            transport_success=True,
            real_api_attempted=True,
            real_api_transport_success=True,
            raw_response_available=True,
            raw_response_text=raw_text,
            raw_response_payload=raw_payload,
            raw_response=raw_text,
            parse_status="NOT_PARSED_BY_PROVIDER_ADAPTER",
            parsed_payload=None,
            schema_valid=False,
            validation_violations=["NOT_PARSED_BY_PROVIDER_ADAPTER"],
            provider_error_type="",
            provider_error_message="",
            latency_ms=latency_ms,
            token_usage=token_usage,
        )
