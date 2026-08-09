"""Strict Stage 4A2 state metric models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

STAGE4A2_METHOD_VERSION = "stage4_bitemporal_state_metrics_v1_1_trace_frozen"
STAGE4A2_SCHEMA_VERSION = "stage4_bitemporal_state_metrics.v1.1"
STRICT = ConfigDict(frozen=True, extra="forbid")


class RAIFamilyComponent(BaseModel):
    model_config = STRICT

    rai_component_id: str
    base_stage3a_state_version_id: str
    response_profile_id: str
    valid_date: date
    cell_id: str
    response_family: str
    family_raw_deviation: float | None
    family_attention: float | None
    family_support_channel_count: int
    family_support_episode_count: int
    family_support_response_evidence_ids: list[str]
    dominant_channel: str | None
    component_status: str
    reason_codes: list[str]
    stage4a2_method_version: str


class StateRAI(BaseModel):
    model_config = STRICT

    state_rai_id: str
    bitemporal_version_id: str
    base_stage3a_state_version_id: str
    response_profile_id: str | None
    valid_date: date
    knowledge_time_start_local_date: date
    cell_id: str
    cell_scope_role: str
    rai: float | None
    rai_status: str
    rai_raw_deviation: float | None
    dominant_response_family: str | None
    co_dominant_response_families: list[str]
    response_family_attention_tie: bool
    raw_deviation_dominant_family: str | None
    raw_deviation_dominant_value: float | None
    family_attention_values: dict[str, float | None]
    support_episode_count: int
    support_response_evidence_count: int
    support_response_evidence_ids: list[str]
    scalar_support_response_evidence_ids: list[str]
    diagnostic_response_evidence_ids: list[str]
    excluded_scalar_response_evidence_ids: list[str]
    excluded_scalar_response_reasons: dict[str, str]
    quality_flags: list[str]
    reason_codes: list[str]
    is_probability: bool
    is_causal_estimate: bool
    stage4a2_method_version: str


class GeologicalAttentionMapping(BaseModel):
    model_config = STRICT

    mapping_id: str
    dimension_name: str
    attribute_name: str
    normalized_serialization: str
    ordinal_rank: int | None
    ordinal_scale_max: int | None
    attention_value: float | None
    mapping_basis: str
    review_status: str
    reviewer: str
    reviewed_at: datetime
    engineering_ordering_rationale: str
    approval_basis: str
    source_review_mapping_id: str
    stage4a2_method_version: str


class GRSDimensionComponent(BaseModel):
    model_config = STRICT

    grs_dimension_component_id: str
    bitemporal_version_id: str
    base_stage3a_state_version_id: str
    valid_date: date
    knowledge_time_start_local_date: date
    cell_id: str
    cell_scope_role: str
    evidence_role: str
    dimension_name: str
    dimension_attention: float | None
    supporting_evidence_uids: list[str]
    supporting_document_ids: list[str]
    supporting_source_types: list[str]
    supporting_epistemic_statuses: list[str]
    supporting_mapping_ids: list[str]
    mapped_evidence_uids: list[str]
    mapped_document_ids: list[str]
    mapped_mapping_ids: list[str]
    mapped_attribute_count: int
    unmapped_attribute_count: int
    component_status: str
    stage4a2_method_version: str


class StateGRS(BaseModel):
    model_config = STRICT

    state_grs_id: str
    bitemporal_version_id: str
    base_stage3a_state_version_id: str
    valid_date: date
    knowledge_time_start_local_date: date
    cell_id: str
    cell_scope_role: str
    evidence_role: str
    grs: float | None
    grs_status: str
    dimension_attention_values: dict[str, float | None]
    available_dimension_count: int
    dimension_coverage_ratio: float
    dominant_geological_dimension: str | None
    co_dominant_geological_dimensions: list[str]
    geological_dimension_attention_tie: bool
    role_observed_evidence_count: int
    role_forecast_evidence_count: int
    grs_contributing_observed_evidence_count: int
    grs_contributing_forecast_evidence_count: int
    observed_support_count: int
    forecast_support_count: int
    support_evidence_uids: list[str]
    role_evidence_uids: list[str]
    mapped_geological_evidence_uids: list[str]
    grs_contributing_evidence_uids: list[str]
    role_document_ids: list[str]
    mapped_document_ids: list[str]
    grs_contributing_document_ids: list[str]
    quality_flags: list[str]
    reason_codes: list[str]
    is_probability: bool
    is_causal_estimate: bool
    stage4a2_method_version: str


class StateGRCI(BaseModel):
    model_config = STRICT

    state_grci_id: str
    bitemporal_version_id: str
    base_stage3a_state_version_id: str
    valid_date: date
    knowledge_time_start_local_date: date
    cell_id: str
    cell_scope_role: str
    grci: float | None
    grci_status: str
    rai: float | None
    grs: float | None
    operator_name: str
    is_probability: bool
    is_causal_estimate: bool
    is_hazard_probability: bool
    reason_codes: list[str]
    stage4a2_method_version: str


class StateMetricSummary(BaseModel):
    model_config = STRICT

    state_metric_summary_id: str
    bitemporal_version_id: str
    base_stage3a_state_version_id: str
    valid_date: date
    knowledge_time_start_local_date: date
    version_number: int
    cell_id: str
    cell_scope_role: str
    state_rai_id: str
    rai: float | None
    rai_status: str
    rai_raw_deviation: float | None
    co_dominant_response_families: list[str]
    response_family_attention_tie: bool
    raw_deviation_dominant_family: str | None
    state_grs_id: str
    grs: float | None
    grs_status: str
    grs_dimension_coverage_count: int
    grs_dimension_coverage_ratio: float
    grci: float | None
    grci_status: str
    grci_operator: str
    grci_is_probability: bool
    state_grci_id: str
    dominant_response_family: str | None
    dominant_geological_dimension: str | None
    co_dominant_geological_dimensions: list[str]
    geological_dimension_attention_tie: bool
    role_geological_evidence_count: int
    mapped_geological_evidence_count: int
    grs_contributing_evidence_count: int
    role_observed_evidence_count: int
    role_forecast_evidence_count: int
    grs_contributing_observed_evidence_count: int
    grs_contributing_forecast_evidence_count: int
    observed_geological_support_count: int
    forecast_geological_support_count: int
    metric_method_contract_hash: str
    metric_quality_flags: list[str]
    metric_reason_codes: list[str]
    reconstructed_at: datetime
    stage4a2_method_version: str


def validate_rows(model: type[BaseModel], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and serialize rows through a strict Pydantic model."""

    return [model.model_validate(row).model_dump(mode="json") for row in rows]
