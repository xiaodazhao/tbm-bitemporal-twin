"""Claim contract loading and serialization."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from tbm_twin.claims.models import STAGE5A_CONTRACT_VERSION, ClaimContract


def load_claim_contracts(
    path: Path = Path("configs/claim_contract_v1.yaml"),
) -> list[ClaimContract]:
    """Load Stage 5A claim contracts from YAML."""

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    schema_version = str(raw["schema_version"])
    contract_version = str(raw.get("contract_version", STAGE5A_CONTRACT_VERSION))
    contracts: list[ClaimContract] = []
    for item in raw.get("claim_types", []):
        payload: dict[str, Any] = {
            "schema_version": schema_version,
            "contract_version": contract_version,
            **item,
        }
        contracts.append(ClaimContract.model_validate(payload))
    return contracts


def contract_file_hash(path: Path = Path("configs/claim_contract_v1.yaml")) -> str:
    """Return SHA256 for the claim contract YAML."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
