"""Tests for Stage 5A claim contract registry."""

from __future__ import annotations

from pathlib import Path

from tbm_twin.claims.contracts import contract_file_hash, load_claim_contracts
from tbm_twin.claims.models import ClaimModality, ClaimType
from tbm_twin.claims.registry import ClaimTypeRegistry


def test_claim_contract_registry_loads_six_core_types() -> None:
    contracts = load_claim_contracts()
    registry = ClaimTypeRegistry.from_contracts(contracts)

    assert len(contracts) == 6
    assert set(registry.contracts) == set(ClaimType)
    assert registry.contract_for(ClaimType.COUPLED_ATTENTION_REVIEW) is not None
    assert contract_file_hash(Path("configs/claim_contract_v1.yaml"))


def test_contract_config_has_no_documentation_only_required_state_roles() -> None:
    contract_text = Path("configs/claim_contract_v1.yaml").read_text(encoding="utf-8")
    forward_contract = ClaimTypeRegistry.from_contracts(load_claim_contracts()).contract_for(
        ClaimType.FORWARD_GEOLOGICAL_ATTENTION
    )

    assert "required_state_roles" not in contract_text
    assert forward_contract is not None
    assert forward_contract.allowed_modalities == [ClaimModality.DERIVED_ATTENTION]
