"""Provider interface for Stage6B real-model smoke."""

from __future__ import annotations

from typing import Protocol

from tbm_twin.realization.providers.configured_llm import ProviderAttempt
from tbm_twin.realization.stage6b_smoke import SmokeRealizationRequest


class RealizationPlanProvider(Protocol):
    """A provider only returns raw plan attempts; validation stays deterministic."""

    provider_name: str

    def request_plan(self, request: SmokeRealizationRequest) -> ProviderAttempt:
        """Return one raw provider attempt for a smoke request."""
