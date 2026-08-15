"""Claim type registry for Stage 5A."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from tbm_twin.claims.models import ClaimContract, ClaimType


class ClaimTypeRegistry(BaseModel):
    """Lookup registry for claim contracts."""

    model_config = ConfigDict(frozen=True)

    contracts: dict[ClaimType, ClaimContract]

    @classmethod
    def from_contracts(cls, contracts: list[ClaimContract]) -> ClaimTypeRegistry:
        """Create a registry, rejecting duplicate claim types."""

        indexed: dict[ClaimType, ClaimContract] = {}
        for contract in contracts:
            if contract.claim_type in indexed:
                msg = f"Duplicate claim type contract: {contract.claim_type}"
                raise ValueError(msg)
            indexed[contract.claim_type] = contract
        return cls(contracts=indexed)

    def contract_for(self, claim_type: ClaimType) -> ClaimContract | None:
        """Return contract for a claim type if configured."""

        return self.contracts.get(claim_type)

    def to_registry_rows(self) -> list[dict[str, object]]:
        """Serialize a compact JSON-friendly registry."""

        rows: list[dict[str, object]] = []
        for claim_type in sorted(self.contracts, key=str):
            contract = self.contracts[claim_type]
            rows.append(
                {
                    "claim_type": claim_type.value,
                    "contract_id": contract.contract_id,
                    "generation_eligible": contract.generation_eligible,
                    "required_metric": contract.required_metric,
                    "allowed_state_roles": contract.allowed_state_roles,
                    "required_support_kinds": [
                        kind.value for kind in contract.required_support_kinds
                    ],
                    "allowed_modalities": [
                        modality.value for modality in contract.allowed_modalities
                    ],
                    "allowed_semantic_interpretations": [
                        semantic.value for semantic in contract.allowed_semantic_interpretations
                    ],
                }
            )
        return rows
