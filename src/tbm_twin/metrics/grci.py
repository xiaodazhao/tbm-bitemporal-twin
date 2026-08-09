"""Formal GRCI computation for Stage 4A2."""

from __future__ import annotations

from datetime import date
from typing import Any

from tbm_twin.metrics.io import stable_id
from tbm_twin.metrics.state_metric_models import STAGE4A2_METHOD_VERSION, StateGRCI

GRCI_OPERATOR = "NONPROBABILISTIC_CONJUNCTIVE_PRODUCT"


def build_grci(
    bitemporal_versions: list[dict[str, Any]],
    rai_by_version: dict[str, dict[str, Any]],
    grs_by_version: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build GRCI only for DAILY_REVIEW_CELL versions with available RAI and GRS."""

    rows: list[dict[str, Any]] = []
    scope_audit: list[dict[str, Any]] = []
    for version in bitemporal_versions:
        version_id = str(version["bitemporal_version_id"])
        rai = rai_by_version[version_id]
        grs = grs_by_version[version_id]
        role = str(version["cell_scope_role"])
        reason_codes: list[str] = []
        if role == "FORWARD_ATTENTION_CELL":
            value = None
            status = "GRCI_NOT_DEFINED_FOR_FORWARD_ATTENTION"
            reason_codes.append(status)
        elif role == "LOCAL_BACKGROUND_CELL":
            value = None
            status = "GRCI_NOT_DEFINED_FOR_LOCAL_BACKGROUND"
            reason_codes.append(status)
        elif rai["rai"] is None:
            value = None
            status = "RAI_UNAVAILABLE"
            reason_codes.append(status)
        elif grs["grs"] is None:
            value = None
            status = "GRS_UNAVAILABLE"
            reason_codes.append(status)
        else:
            value = float(rai["rai"]) * float(grs["grs"])
            status = "AVAILABLE"
        model = StateGRCI(
            state_grci_id="state_grci_" + stable_id(version_id, STAGE4A2_METHOD_VERSION),
            bitemporal_version_id=version_id,
            base_stage3a_state_version_id=str(version["base_stage3a_state_version_id"]),
            valid_date=date.fromisoformat(str(version["valid_date"])),
            knowledge_time_start_local_date=date.fromisoformat(
                str(version["knowledge_time_start_local_date"])
            ),
            cell_id=str(version["cell_id"]),
            cell_scope_role=role,
            grci=value,
            grci_status=status,
            rai=rai["rai"],
            grs=grs["grs"],
            operator_name=GRCI_OPERATOR,
            is_probability=False,
            is_causal_estimate=False,
            is_hazard_probability=False,
            reason_codes=reason_codes,
            stage4a2_method_version=STAGE4A2_METHOD_VERSION,
        )
        row = model.model_dump(mode="json")
        rows.append(row)
        scope_audit.append(
            {
                "bitemporal_version_id": version_id,
                "cell_scope_role": role,
                "grci_status": status,
                "grci_available": value is not None,
                "status": "PASS" if (role == "DAILY_REVIEW_CELL" or value is None) else "FAIL",
            }
        )
    return rows, scope_audit
