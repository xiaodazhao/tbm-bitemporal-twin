"""Formal GRS computation for Stage 4A2."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from tbm_twin.metrics.geological_mapping import normalize_value
from tbm_twin.metrics.io import stable_id
from tbm_twin.metrics.state_metric_models import (
    STAGE4A2_METHOD_VERSION,
    GRSDimensionComponent,
    StateGRS,
)

DIMENSIONS = [
    "EXPLICIT_ANOMALY",
    "SURROUNDING_ROCK_GRADE",
    "ROCK_MASS_INTEGRITY",
    "JOINT_DEVELOPMENT",
    "STABILITY_BLOCK",
    "WATER_ATTENTION",
]


def evidence_ids_for_role(snapshot: dict[str, Any]) -> tuple[str, list[str]]:
    """Return the role-specific materialized geological evidence IDs."""

    role = str(snapshot["cell_scope_role"])
    if role == "DAILY_REVIEW_CELL":
        return "DAILY_REVIEW", [
            str(item) for item in snapshot["materialized_daily_review_evidence_ids"]
        ]
    if role == "FORWARD_ATTENTION_CELL":
        return "FORWARD_ATTENTION", [
            str(item) for item in snapshot["materialized_forward_attention_evidence_ids"]
        ]
    if role == "LOCAL_BACKGROUND_CELL":
        return "LOCAL_BACKGROUND", [
            str(item) for item in snapshot["materialized_local_background_evidence_ids"]
        ]
    return "UNKNOWN", []


def build_grs_for_snapshots(
    snapshots: list[dict[str, Any]],
    evidence_by_uid: dict[str, dict[str, Any]],
    mapping_by_key: dict[tuple[str, str], dict[str, Any]],
) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]
]:
    """Build GRS dimension components and one StateGRS per bitemporal snapshot."""

    dimension_rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    state_by_bitemporal_id: dict[str, dict[str, Any]] = {}
    support_audit: list[dict[str, Any]] = []
    for snapshot in snapshots:
        role_name, evidence_ids = evidence_ids_for_role(snapshot)
        evidences = [evidence_by_uid[eid] for eid in evidence_ids if eid in evidence_by_uid]
        component_rows = [
            _dimension_component(snapshot, role_name, dimension, evidences, mapping_by_key)
            for dimension in DIMENSIONS
        ]
        dimension_rows.extend(component_rows)
        state_row = _state_grs(snapshot, role_name, evidences, component_rows)
        state_rows.append(state_row)
        state_by_bitemporal_id[str(snapshot["bitemporal_version_id"])] = state_row
        support_audit.append(
            {
                "bitemporal_version_id": snapshot["bitemporal_version_id"],
                "cell_scope_role": snapshot["cell_scope_role"],
                "evidence_role": role_name,
                "role_evidence_count": len(evidence_ids),
                "closed_evidence_count": len(evidences),
                "missing_evidence_count": len(set(evidence_ids) - set(evidence_by_uid)),
                "grs_status": state_row["grs_status"],
                "available_dimension_count": state_row["available_dimension_count"],
            }
        )
    return dimension_rows, state_rows, state_by_bitemporal_id, support_audit


def _dimension_component(
    snapshot: dict[str, Any],
    role_name: str,
    dimension: str,
    evidences: list[dict[str, Any]],
    mapping_by_key: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    mapped: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    numeric_mapped: list[tuple[dict[str, Any], dict[str, Any]]] = []
    unmapped_count = 0
    for evidence in evidences:
        raw_attrs = evidence.get("attributes")
        attrs: dict[str, Any] = raw_attrs if isinstance(raw_attrs, dict) else {}
        for attribute_name, value in attrs.items():
            key = (str(attribute_name), normalize_value(value))
            mapping = mapping_by_key.get(key)
            if not mapping or mapping["dimension_name"] != dimension:
                continue
            if mapping["attention_value"] is None:
                unmapped_count += 1
                continue
            numeric_mapped.append((mapping, evidence))
            mapped.append((float(mapping["attention_value"]), mapping, evidence))
    if mapped:
        max_value = max(item[0] for item in mapped)
        winners = [item for item in mapped if item[0] == max_value]
        status = "AVAILABLE"
    else:
        max_value = None
        winners = []
        status = "NO_MAPPED_DIMENSION_ATTRIBUTE"
    return GRSDimensionComponent(
        grs_dimension_component_id="grs_dimension_component_"
        + stable_id(
            str(snapshot["bitemporal_version_id"]),
            dimension,
            STAGE4A2_METHOD_VERSION,
        ),
        bitemporal_version_id=str(snapshot["bitemporal_version_id"]),
        base_stage3a_state_version_id=str(snapshot["base_stage3a_state_version_id"]),
        valid_date=date.fromisoformat(str(snapshot["valid_date"])),
        knowledge_time_start_local_date=date.fromisoformat(
            str(snapshot["knowledge_time_start_local_date"])
        ),
        cell_id=str(snapshot["cell_id"]),
        cell_scope_role=str(snapshot["cell_scope_role"]),
        evidence_role=role_name,
        dimension_name=dimension,
        dimension_attention=max_value,
        supporting_evidence_uids=sorted(
            {str(evidence["evidence_uid"]) for _, _, evidence in winners}
        ),
        supporting_document_ids=sorted(
            {str(evidence["document_id"]) for _, _, evidence in winners}
        ),
        supporting_source_types=sorted(
            {str(evidence["source_type"]) for _, _, evidence in winners}
        ),
        supporting_epistemic_statuses=sorted(
            {str(evidence["epistemic_status"]) for _, _, evidence in winners}
        ),
        supporting_mapping_ids=sorted({str(mapping["mapping_id"]) for _, mapping, _ in winners}),
        mapped_evidence_uids=sorted(
            {str(evidence["evidence_uid"]) for _, evidence in numeric_mapped}
        ),
        mapped_document_ids=sorted(
            {str(evidence["document_id"]) for _, evidence in numeric_mapped}
        ),
        mapped_mapping_ids=sorted({str(mapping["mapping_id"]) for mapping, _ in numeric_mapped}),
        mapped_attribute_count=len(mapped),
        unmapped_attribute_count=unmapped_count,
        component_status=status,
        stage4a2_method_version=STAGE4A2_METHOD_VERSION,
    ).model_dump(mode="json")


def _state_grs(
    snapshot: dict[str, Any],
    role_name: str,
    evidences: list[dict[str, Any]],
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    available = [
        float(component["dimension_attention"])
        for component in components
        if component["dimension_attention"] is not None
    ]
    if not available:
        grs = None
        status = "NO_MAPPED_GEOLOGICAL_ATTENTION_DIMENSION"
        reasons = ["NO_MAPPED_GEOLOGICAL_ATTENTION_DIMENSION"]
        dominant = None
        co_dominant: list[str] = []
        tie = False
    else:
        grs = sum(available) / len(available)
        status = "AVAILABLE"
        reasons = []
        if len(available) == 1:
            reasons.append("LOW_DIMENSION_COVERAGE")
        max_attention = max(available)
        co_dominant = sorted(
            str(component["dimension_name"])
            for component in components
            if component["dimension_attention"] is not None
            and float(component["dimension_attention"]) == max_attention
        )
        tie = len(co_dominant) > 1
        dominant = co_dominant[0] if not tie else None
    observed = sum(1 for evidence in evidences if evidence.get("epistemic_status") == "OBSERVED")
    forecast = sum(1 for evidence in evidences if evidence.get("epistemic_status") == "FORECAST")
    role_evidence_uids = sorted({str(evidence["evidence_uid"]) for evidence in evidences})
    role_document_ids = sorted({str(evidence["document_id"]) for evidence in evidences})
    mapped_evidence_uids = sorted(
        {
            evidence_uid
            for component in components
            for evidence_uid in component["mapped_evidence_uids"]
        }
    )
    mapped_document_ids = sorted(
        {
            document_id
            for component in components
            for document_id in component["mapped_document_ids"]
        }
    )
    contributing_evidence_uids = sorted(
        {
            evidence_uid
            for component in components
            for evidence_uid in component["supporting_evidence_uids"]
        }
    )
    contributing_document_ids = sorted(
        {
            document_id
            for component in components
            for document_id in component["supporting_document_ids"]
        }
    )
    evidence_by_uid = {str(evidence["evidence_uid"]): evidence for evidence in evidences}
    contributing_observed = sum(
        1
        for evidence_uid in contributing_evidence_uids
        if evidence_by_uid.get(evidence_uid, {}).get("epistemic_status") == "OBSERVED"
    )
    contributing_forecast = sum(
        1
        for evidence_uid in contributing_evidence_uids
        if evidence_by_uid.get(evidence_uid, {}).get("epistemic_status") == "FORECAST"
    )
    return StateGRS(
        state_grs_id="state_grs_"
        + stable_id(str(snapshot["bitemporal_version_id"]), STAGE4A2_METHOD_VERSION),
        bitemporal_version_id=str(snapshot["bitemporal_version_id"]),
        base_stage3a_state_version_id=str(snapshot["base_stage3a_state_version_id"]),
        valid_date=date.fromisoformat(str(snapshot["valid_date"])),
        knowledge_time_start_local_date=date.fromisoformat(
            str(snapshot["knowledge_time_start_local_date"])
        ),
        cell_id=str(snapshot["cell_id"]),
        cell_scope_role=str(snapshot["cell_scope_role"]),
        evidence_role=role_name,
        grs=grs,
        grs_status=status,
        dimension_attention_values={
            str(component["dimension_name"]): component["dimension_attention"]
            for component in components
        },
        available_dimension_count=len(available),
        dimension_coverage_ratio=len(available) / len(DIMENSIONS),
        dominant_geological_dimension=dominant,
        co_dominant_geological_dimensions=co_dominant,
        geological_dimension_attention_tie=tie,
        role_observed_evidence_count=observed,
        role_forecast_evidence_count=forecast,
        grs_contributing_observed_evidence_count=contributing_observed,
        grs_contributing_forecast_evidence_count=contributing_forecast,
        observed_support_count=observed,
        forecast_support_count=forecast,
        support_evidence_uids=role_evidence_uids,
        role_evidence_uids=role_evidence_uids,
        mapped_geological_evidence_uids=mapped_evidence_uids,
        grs_contributing_evidence_uids=contributing_evidence_uids,
        role_document_ids=role_document_ids,
        mapped_document_ids=mapped_document_ids,
        grs_contributing_document_ids=contributing_document_ids,
        quality_flags=[],
        reason_codes=reasons,
        is_probability=False,
        is_causal_estimate=False,
        stage4a2_method_version=STAGE4A2_METHOD_VERSION,
    ).model_dump(mode="json")


def build_aggregation_comparison(
    dimension_components: list[dict[str, Any]],
    state_grs_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare official dimension mean with descriptive overall max only."""

    components_by_state: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for component in dimension_components:
        components_by_state[str(component["bitemporal_version_id"])].append(component)
    grs_by_state = {str(row["bitemporal_version_id"]): row for row in state_grs_rows}
    rows: list[dict[str, Any]] = []
    for state_id, components in sorted(components_by_state.items()):
        values = [
            float(component["dimension_attention"])
            for component in components
            if component["dimension_attention"] is not None
        ]
        rows.append(
            {
                "bitemporal_version_id": state_id,
                "official_dimension_mean": grs_by_state[state_id]["grs"],
                "descriptive_overall_max_only": max(values) if values else None,
                "official_saturated_at_one": grs_by_state[state_id]["grs"] == 1.0,
                "overall_max_saturated_at_one": max(values) == 1.0 if values else False,
                "available_dimension_count": len(values),
            }
        )
    return rows
