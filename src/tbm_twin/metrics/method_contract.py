"""Executable Stage 4 metric method contract validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tbm_twin.metrics.grci import GRCI_OPERATOR
from tbm_twin.metrics.grs import DIMENSIONS
from tbm_twin.metrics.io import read_yaml, sha256_file
from tbm_twin.metrics.rai import RAI_SATURATION_ROBUST_Z, SCALAR_FAMILIES


@dataclass(frozen=True)
class MetricMethodContract:
    """Validated Stage 4 metric method configuration."""

    state_metric_definition: dict[str, Any]
    geological_attention_mapping: dict[str, Any]
    operational_measurement_regime: dict[str, Any]
    audit_rows: list[dict[str, Any]]
    contract_hash: str
    state_metric_definition_sha256: str
    geological_attention_mapping_sha256: str
    operational_measurement_regime_review_sha256: str


def load_and_validate_contract(repo_root: Path) -> MetricMethodContract:
    """Read the three formal method configs and fail on implementation drift."""

    state_path = repo_root / "configs/state_metric_definition_v1.yaml"
    mapping_path = repo_root / "configs/geological_attention_mapping_v1.yaml"
    regime_path = repo_root / "configs/operational_measurement_regime_review.yaml"
    state_config = read_yaml(state_path)
    mapping_config = read_yaml(mapping_path)
    regime_config = read_yaml(regime_path)
    rows: list[dict[str, Any]] = []

    def check(name: str, config_value: Any, implementation_value: Any) -> None:
        match = config_value == implementation_value
        rows.append(
            {
                "contract_name": name,
                "config_value": _display(config_value),
                "implementation_value": _display(implementation_value),
                "match": match,
                "status": "PASS" if match else "FAIL",
            }
        )

    check("rai.saturation_robust_z", state_config["rai"]["saturation_robust_z"], 3.0)
    check("rai.saturation_implementation", RAI_SATURATION_ROBUST_Z, 3.0)
    configured_families = {
        family: payload["channels"]
        for family, payload in state_config["rai"]["scalar_response_families"].items()
    }
    check("rai.scalar_response_families", configured_families, SCALAR_FAMILIES)
    check(
        "rai.family_channel_operator",
        state_config["rai"]["aggregation"]["family_channel_operator"],
        "max_channel_median_abs_z",
    )
    check(
        "rai.rai_operator",
        state_config["rai"]["aggregation"]["rai_operator"],
        "max_scalar_family_attention",
    )
    check("grs.dimensions", state_config["grs"]["dimensions"], DIMENSIONS)
    check(
        "grs.dimension_operator",
        state_config["grs"]["dimension_operator"],
        "max_mapped_attention",
    )
    check(
        "grs.state_operator",
        state_config["grs"]["state_operator"],
        "mean_non_null_dimension_attention",
    )
    check("grci.operator", state_config["grci"]["operator"], GRCI_OPERATOR)
    check("grci.is_probability", state_config["grci"]["is_probability"], False)
    check("grci.is_causal_estimate", state_config["grci"]["is_causal_estimate"], False)
    check("grci.is_hazard_probability", state_config["grci"]["is_hazard_probability"], False)

    rpm = _regime_for(regime_config, "cutterhead_rpm")
    check("rpm.scalar_rai_eligible", rpm.get("scalar_rai_eligible"), False)
    check("rpm.automatic_scale_correction", rpm.get("automatic_scale_correction"), False)
    check("rpm.reviewed_boundary_date", str(rpm.get("reviewed_boundary_date")), "2023-12-01")
    check("mapping.entry_count", len(mapping_config["entries"]), 44)
    check(
        "mapping.numeric_count",
        sum(1 for row in mapping_config["entries"] if row.get("attention_value") is not None),
        36,
    )
    check(
        "mapping.unmappable_count",
        sum(1 for row in mapping_config["entries"] if row.get("attention_value") is None),
        8,
    )

    if any(row["status"] != "PASS" for row in rows):
        failed = [row["contract_name"] for row in rows if row["status"] != "PASS"]
        msg = f"Stage4 method contract mismatch: {failed}"
        raise ValueError(msg)

    digest = hashlib.sha256(
        json.dumps(
            {
                "state_metric_definition": state_config,
                "geological_attention_mapping": mapping_config,
                "operational_measurement_regime": regime_config,
            },
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return MetricMethodContract(
        state_metric_definition=state_config,
        geological_attention_mapping=mapping_config,
        operational_measurement_regime=regime_config,
        audit_rows=rows,
        contract_hash=digest,
        state_metric_definition_sha256=sha256_file(state_path),
        geological_attention_mapping_sha256=sha256_file(mapping_path),
        operational_measurement_regime_review_sha256=sha256_file(regime_path),
    )


def _regime_for(config: dict[str, Any], channel: str) -> dict[str, Any]:
    for row in config.get("reviewed_channel_regimes", []):
        if isinstance(row, dict) and row.get("channel_name") == channel:
            return row
    msg = f"Missing measurement regime for {channel}"
    raise ValueError(msg)


def _display(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
