"""Response deviation components for Stage 4A1."""

from __future__ import annotations

from datetime import date
from typing import Any

from tbm_twin.metrics.io import stable_id
from tbm_twin.metrics.models import STAGE4A1_METHOD_VERSION, ResponseDeviationComponent
from tbm_twin.metrics.operational_baseline import median_from_response, parse_date


def build_response_deviation_components(
    responses: list[dict[str, Any]],
    baselines: list[dict[str, Any]],
    eligibility: dict[str, bool],
    coverage_by_response_id: dict[str, str],
    source_operational_manifest_hash: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Build one descriptive deviation component per ResponseEvidence."""

    baseline_by_key = {
        (date.fromisoformat(str(row["valid_date"])), str(row["channel_name"])): row
        for row in baselines
    }
    components: list[dict[str, Any]] = []
    component_by_response_id: dict[str, dict[str, Any]] = {}
    reference_audit: list[dict[str, Any]] = []
    for response in responses:
        response_id = str(response["evidence_id"])
        target_date = parse_date(str(response["target_date"]))
        channel = str(response["channel_name"])
        baseline = baseline_by_key[(target_date, channel)]
        response_value = median_from_response(response)
        scale = baseline.get("robust_scale")
        scale_value = float(scale) if scale is not None else None
        baseline_median = baseline.get("median")
        baseline_available = (
            baseline.get("baseline_status") == "AVAILABLE"
            and scale_value is not None
            and scale_value > 0
        )
        response_eligible = eligibility.get(response_id, False)
        signed_deviation: float | None = None
        robust_z: float | None = None
        abs_robust_z: float | None = None
        direction = "UNKNOWN"
        if response_value is not None and baseline_median is not None:
            signed_deviation = response_value - float(baseline_median)
            if signed_deviation > 0:
                direction = "ABOVE_BASELINE"
            elif signed_deviation < 0:
                direction = "BELOW_BASELINE"
            else:
                direction = "AT_BASELINE"
        if response_eligible and baseline_available and signed_deviation is not None:
            assert scale_value is not None
            robust_z = signed_deviation / scale_value
            abs_robust_z = abs(robust_z)
            status = "AVAILABLE"
        elif not response_eligible:
            status = "RESPONSE_MECHANICALLY_INELIGIBLE"
        else:
            status = "BASELINE_UNAVAILABLE"
        component_id = "response_deviation_" + stable_id(
            response_id, str(baseline["baseline_id"]), STAGE4A1_METHOD_VERSION
        )
        model = ResponseDeviationComponent(
            component_id=component_id,
            response_evidence_id=response_id,
            episode_id=str(response.get("episode_id") or ""),
            target_date=target_date,
            channel_name=channel,
            baseline_id=str(baseline["baseline_id"]),
            baseline_valid_date=date.fromisoformat(str(baseline["valid_date"])),
            baseline_sample_count=int(baseline["sample_count"]),
            baseline_median=baseline_median,
            baseline_mad=baseline.get("mad"),
            baseline_iqr=baseline.get("iqr"),
            baseline_scale=scale_value,
            baseline_scale_basis=baseline.get("robust_scale_basis"),
            baseline_status=str(baseline["baseline_status"]),
            response_value=response_value,
            signed_deviation=signed_deviation,
            robust_z=robust_z,
            absolute_robust_z=abs_robust_z,
            deviation_direction=direction,
            component_status=status,
            response_quality_grade=str(response.get("quality_grade") or "UNKNOWN"),
            response_quality_flags=[str(item) for item in response.get("quality_flags", [])],
            spatial_scope_usable=bool(response.get("spatial_scope_usable")),
            response_coverage_class=coverage_by_response_id.get(response_id, "UNKNOWN"),
            source_operational_manifest_hash=source_operational_manifest_hash,
            metric_foundation_method_version=STAGE4A1_METHOD_VERSION,
        )
        row = model.model_dump(mode="json")
        components.append(row)
        component_by_response_id[response_id] = row
        reference_audit.append(
            {
                "response_evidence_id": response_id,
                "component_id": component_id,
                "baseline_id": baseline["baseline_id"],
                "component_status": status,
                "response_coverage_class": coverage_by_response_id.get(response_id, "UNKNOWN"),
                "status": "PASS",
            }
        )
    return components, component_by_response_id, reference_audit
