"""State metric summary construction for Stage 4A2."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from tbm_twin.metrics.grci import GRCI_OPERATOR
from tbm_twin.metrics.io import stable_id
from tbm_twin.metrics.state_metric_models import STAGE4A2_METHOD_VERSION, StateMetricSummary


def build_state_metric_summaries(
    bitemporal_versions: list[dict[str, Any]],
    rai_by_version: dict[str, dict[str, Any]],
    grs_by_version: dict[str, dict[str, Any]],
    grci_by_version: dict[str, dict[str, Any]],
    reconstructed_at: datetime,
    metric_method_contract_hash: str = "",
) -> list[dict[str, Any]]:
    """Build one StateMetricSummary per bitemporal state version."""

    rows: list[dict[str, Any]] = []
    for version in bitemporal_versions:
        version_id = str(version["bitemporal_version_id"])
        rai = rai_by_version[version_id]
        grs = grs_by_version[version_id]
        grci = grci_by_version[version_id]
        reason_codes = sorted(
            set(rai.get("reason_codes", []))
            | set(grs.get("reason_codes", []))
            | set(grci.get("reason_codes", []))
        )
        quality_flags = sorted(
            set(rai.get("quality_flags", [])) | set(grs.get("quality_flags", []))
        )
        model = StateMetricSummary(
            state_metric_summary_id="state_metric_summary_"
            + stable_id(version_id, STAGE4A2_METHOD_VERSION),
            bitemporal_version_id=version_id,
            base_stage3a_state_version_id=str(version["base_stage3a_state_version_id"]),
            valid_date=version["valid_date"],
            knowledge_time_start_local_date=version["knowledge_time_start_local_date"],
            version_number=int(version["version_number"]),
            cell_id=str(version["cell_id"]),
            cell_scope_role=str(version["cell_scope_role"]),
            state_rai_id=str(
                rai.get(
                    "state_rai_id",
                    "state_rai_" + stable_id(version_id, STAGE4A2_METHOD_VERSION),
                )
            ),
            rai=rai["rai"],
            rai_status=rai["rai_status"],
            rai_raw_deviation=rai.get("rai_raw_deviation"),
            co_dominant_response_families=rai.get(
                "co_dominant_response_families",
                [rai["dominant_response_family"]] if rai["dominant_response_family"] else [],
            ),
            response_family_attention_tie=bool(rai.get("response_family_attention_tie", False)),
            raw_deviation_dominant_family=rai.get(
                "raw_deviation_dominant_family", rai["dominant_response_family"]
            ),
            state_grs_id=str(
                grs.get(
                    "state_grs_id",
                    "state_grs_" + stable_id(version_id, STAGE4A2_METHOD_VERSION),
                )
            ),
            grs=grs["grs"],
            grs_status=grs["grs_status"],
            grs_dimension_coverage_count=int(grs["available_dimension_count"]),
            grs_dimension_coverage_ratio=float(grs["dimension_coverage_ratio"]),
            grci=grci["grci"],
            grci_status=grci["grci_status"],
            grci_operator=str(grci.get("operator_name", GRCI_OPERATOR)),
            grci_is_probability=bool(grci.get("is_probability", False)),
            state_grci_id=str(
                grci.get(
                    "state_grci_id",
                    "state_grci_" + stable_id(version_id, STAGE4A2_METHOD_VERSION),
                )
            ),
            dominant_response_family=rai["dominant_response_family"],
            dominant_geological_dimension=grs["dominant_geological_dimension"],
            co_dominant_geological_dimensions=grs.get(
                "co_dominant_geological_dimensions",
                [grs["dominant_geological_dimension"]]
                if grs["dominant_geological_dimension"]
                else [],
            ),
            geological_dimension_attention_tie=bool(
                grs.get("geological_dimension_attention_tie", False)
            ),
            role_geological_evidence_count=len(
                grs.get("role_evidence_uids", grs.get("support_evidence_uids", []))
            ),
            mapped_geological_evidence_count=len(
                grs.get(
                    "mapped_geological_evidence_uids",
                    grs.get("support_evidence_uids", []),
                )
            ),
            grs_contributing_evidence_count=len(
                grs.get(
                    "grs_contributing_evidence_uids",
                    grs.get("support_evidence_uids", []),
                )
            ),
            role_observed_evidence_count=int(
                grs.get("role_observed_evidence_count", grs["observed_support_count"])
            ),
            role_forecast_evidence_count=int(
                grs.get("role_forecast_evidence_count", grs["forecast_support_count"])
            ),
            grs_contributing_observed_evidence_count=int(
                grs.get(
                    "grs_contributing_observed_evidence_count",
                    grs["observed_support_count"],
                )
            ),
            grs_contributing_forecast_evidence_count=int(
                grs.get(
                    "grs_contributing_forecast_evidence_count",
                    grs["forecast_support_count"],
                )
            ),
            observed_geological_support_count=int(
                grs.get("role_observed_evidence_count", grs["observed_support_count"])
            ),
            forecast_geological_support_count=int(
                grs.get("role_forecast_evidence_count", grs["forecast_support_count"])
            ),
            metric_method_contract_hash=metric_method_contract_hash,
            metric_quality_flags=quality_flags,
            metric_reason_codes=reason_codes,
            reconstructed_at=reconstructed_at,
            stage4a2_method_version=STAGE4A2_METHOD_VERSION,
        )
        rows.append(model.model_dump(mode="json"))
    return rows
