"""Strict models for Stage 4A1 metric foundation artifacts."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

STAGE4A1_METHOD_VERSION = "stage4a1_metric_foundation_v1_causal_response_inventory"
STAGE4A1_SCHEMA_VERSION = "stage4a1_metric_foundation.v1"
STRICT_MODEL_CONFIG = ConfigDict(frozen=True, extra="forbid")


class Stage4A1Config(BaseModel):
    """Filesystem and parameter configuration for Stage 4A1."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo_root: Path
    output_dir: Path = Path("artifacts/stage4a1_metric_foundation_v1")
    config_path: Path = Path("configs/metric_foundation.yaml")
    stage3b_dir: Path = Path("artifacts/stage3b_bitemporal_epistemic_state_v1_1")
    stage3a_dir: Path = Path("artifacts/stage3a_initial_epistemic_state_v1_1")
    operational_freeze_dir: Path = Path("artifacts/stage2_plc_operational_freeze_v2")
    geology_freeze_dir: Path = Path("artifacts/stage2_geology_v2_freeze_candidate")
    generated_at: datetime
    overwrite: bool = False

    @field_validator("generated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Require explicit timezone-aware offline reconstruction time."""

        if value.tzinfo is None:
            msg = "generated_at must be timezone-aware"
            raise ValueError(msg)
        return value

    def resolve(self, path: Path) -> Path:
        """Resolve repo-relative paths."""

        return path if path.is_absolute() else self.repo_root / path


class CausalOperationalBaseline(BaseModel):
    """Historical causal baseline for one valid date and channel."""

    model_config = STRICT_MODEL_CONFIG

    baseline_id: str
    valid_date: date
    channel_name: str
    alignment_id: str
    sample_count: int
    unique_episode_count: int
    source_date_count: int
    earliest_source_date: date | None
    latest_source_date: date | None
    median: float | None
    mad: float | None
    iqr: float | None
    q1: float | None
    q3: float | None
    mad_scaled: float | None
    iqr_scaled: float | None
    robust_scale: float | None
    robust_scale_basis: str | None
    baseline_status: str
    reason_codes: list[str]
    source_response_evidence_ids: list[str]
    baseline_method_version: str


class ResponseDeviationComponent(BaseModel):
    """Deviation of one ResponseEvidence from its causal historical baseline."""

    model_config = STRICT_MODEL_CONFIG

    component_id: str
    response_evidence_id: str
    episode_id: str
    target_date: date
    channel_name: str
    baseline_id: str
    baseline_valid_date: date
    baseline_sample_count: int
    baseline_median: float | None
    baseline_mad: float | None
    baseline_iqr: float | None
    baseline_scale: float | None
    baseline_scale_basis: str | None
    baseline_status: str
    response_value: float | None
    signed_deviation: float | None
    robust_z: float | None
    absolute_robust_z: float | None
    deviation_direction: str
    component_status: str
    response_quality_grade: str
    response_quality_flags: list[str]
    spatial_scope_usable: bool
    response_coverage_class: str
    source_operational_manifest_hash: str
    metric_foundation_method_version: str


class ChannelDeviationSummary(BaseModel):
    """Descriptive-only per-channel deviation summary."""

    model_config = STRICT_MODEL_CONFIG

    channel_name: str
    summary_status: str
    unique_response_evidence_count: int
    unique_episode_count: int
    robust_z_min: float | None
    robust_z_max: float | None
    robust_z_median: float | None
    robust_z_mean: float | None
    robust_z_q25: float | None
    robust_z_q75: float | None
    absolute_robust_z_max: float | None
    absolute_robust_z_median: float | None
    absolute_robust_z_mean: float | None
    baseline_available_count: int
    baseline_unavailable_count: int
    descriptive_status: str


class CellOperationalResponseProfile(BaseModel):
    """Cell-local operational response profile from Stage 3A response links."""

    model_config = STRICT_MODEL_CONFIG

    response_profile_id: str
    base_stage3a_state_version_id: str
    daily_state_id: str
    cell_id: str
    cell_scope_role: str
    valid_date: date
    episode_ids: list[str]
    response_evidence_ids: list[str]
    response_link_ids: list[str]
    response_component_ids: list[str]
    channel_names_present: list[str]
    available_channel_count: int
    unavailable_channel_count: int
    per_channel_summary: list[ChannelDeviationSummary]
    shared_episode_statistic_present: bool
    point_response_present: bool
    response_stat_scopes: list[str]
    profile_status: str
    profile_reason_codes: list[str]
    source_stage3a_manifest_hash: str
    source_operational_manifest_hash: str
    metric_foundation_method_version: str


class BitemporalResponseProfileBinding(BaseModel):
    """Binding from one bitemporal state version to a stable response profile."""

    model_config = STRICT_MODEL_CONFIG

    binding_id: str
    bitemporal_version_id: str
    base_stage3a_state_version_id: str
    response_profile_id: str
    valid_date: date
    knowledge_time_start_local_date: date
    version_number: int
    response_evidence_ids: list[str]
    response_component_ids: list[str]
    metric_foundation_method_version: str


class GeologicalAttributeInventoryRecord(BaseModel):
    """Inventory row for one structured geological attribute value."""

    model_config = STRICT_MODEL_CONFIG

    attribute_name: str
    raw_value: str
    normalized_serialization: str
    value_type: str
    source_type: str
    evidence_type: str
    epistemic_status: str
    evidence_count: int
    unique_document_count: int
    unique_source_span_count: int
    used_in_stage3b_snapshot_count: int
    used_in_daily_review_count: int
    used_in_forward_attention_count: int
    used_in_local_background_count: int
    first_observed_date: date | None
    last_observed_date: date | None
    normalization_status: str
    inventory_reason_codes: list[str]


class GeologicalAttentionMappingTemplateEntry(BaseModel):
    """Manual mapping template entry for geological attention values."""

    model_config = STRICT_MODEL_CONFIG

    mapping_id: str
    attribute_name: str
    source_value: str
    normalized_serialization: str
    source_type_scope: list[str]
    evidence_type_scope: list[str]
    attention_value: None
    review_status: str
    mapping_basis: None
    reviewer: None
    reviewed_at: None
    notes: None


class OperationalMeasurementRegime(BaseModel):
    """Operational channel measurement regime for scalar metric governance."""

    model_config = STRICT_MODEL_CONFIG

    regime_id: str
    channel_name: str
    start_date: date
    end_date: date
    regime_status: str
    raw_value_median_range: dict[str, float | None]
    consistency_ratio_range: dict[str, float | None]
    unit_verified: bool
    scale_verified: bool
    usable_for_scalar_attention: bool
    reason_codes: list[str]
    supporting_response_evidence_ids: list[str]
    method_version: str
