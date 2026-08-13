"""Configured real-model provider boundary for Stage6B smoke.

This module intentionally does not import vendor SDKs. Real smoke execution must
inject an external callable adapter after deterministic pre-smoke checks pass.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict

STRICT = ConfigDict(frozen=True, extra="forbid")


class LLMProviderConfig(BaseModel):
    """Smoke-time model parameters recorded without secrets."""

    model_provider: str
    model_name: str
    temperature: float
    top_p: float
    seed: int | None = None
    reasoning_effort: str = "none"
    max_output_tokens: int
    timeout_seconds: int
    max_retries: int
    retry_causes: list[str]
    api_key_env_var: str
    base_url: str | None = None


class ProviderAttempt(BaseModel):
    """Raw provider response envelope for permanent smoke audit."""

    attempt_index: int
    attempt_number: int
    provider_kind: str
    provider: str
    request_id: str
    model_name: str
    request_timestamp: str
    pack_id: str
    contract_hash: str
    task_scope: dict[str, Any]
    input_unit_ids: list[str]
    provider_attempted: bool = True
    transport_success: bool
    real_api_attempted: bool
    real_api_transport_success: bool
    raw_response_available: bool
    raw_response_text: str | None
    raw_response_payload: dict[str, Any] | None
    raw_response: str | None
    parse_status: str
    parsed_payload: dict[str, Any] | None
    schema_valid: bool
    validation_violations: list[str]
    provider_error_type: str
    provider_error_message: str
    latency_ms: int | None
    token_usage: dict[str, Any] | None


class ConfiguredLLMProvider:
    """Adapter shell; cannot call a model without explicit injected transport."""

    def __init__(
        self,
        config: LLMProviderConfig,
        transport: Callable[[dict[str, Any]], ProviderAttempt] | None = None,
    ) -> None:
        self.config = config
        self._transport = transport

    @property
    def provider_name(self) -> str:
        """Return configured provider label."""

        return self.config.model_provider

    def request_plan(self, payload: dict[str, Any]) -> ProviderAttempt:
        """Request a plan through injected transport; fail closed otherwise."""

        if self._transport is None:
            msg = "real LLM transport is not configured; smoke must be run explicitly"
            raise RuntimeError(msg)
        return self._transport(payload)
