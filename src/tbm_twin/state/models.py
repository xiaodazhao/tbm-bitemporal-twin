"""Models for Stage 3A initial epistemic construction state."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator


class ChainageDirection(StrEnum):
    """Supported chainage direction."""

    INCREASING = "INCREASING"


class PointBoundaryPolicy(StrEnum):
    """How point evidence on grid boundaries maps to cells."""

    RIGHT_CLOSED_PREVIOUS_CELL = "RIGHT_CLOSED_PREVIOUS_CELL"


class CellScopeRole(StrEnum):
    """Daily role assigned to one state cell."""

    DAILY_REVIEW_CELL = "DAILY_REVIEW_CELL"
    FORWARD_ATTENTION_CELL = "FORWARD_ATTENTION_CELL"
    LOCAL_BACKGROUND_CELL = "LOCAL_BACKGROUND_CELL"


class ConstructionStateConfig(BaseModel):
    """Configuration for the static 10m construction-state grid."""

    model_config = ConfigDict(frozen=True)

    alignment_id: str
    chainage_direction: ChainageDirection
    cell_size_m: float
    grid_origin_m: float
    point_boundary_policy: PointBoundaryPolicy
    state_method_version: str


class Stage3AStateConfig(BaseModel):
    """Filesystem and time configuration for a Stage 3A build."""

    model_config = ConfigDict(frozen=True)

    repo_root: Path
    output_dir: Path
    generated_at: datetime
    construction_state_config_path: Path = Path("configs/construction_state.yaml")
    geology_freeze_dir: Path = Path("artifacts/stage2_geology_v2_freeze_candidate")
    applicability_dir: Path = Path("artifacts/stage2d_applicability_v2_1")
    operational_freeze_dir: Path = Path("artifacts/stage2_plc_operational_freeze_v2")
    overwrite: bool = False

    @field_validator("generated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Require explicit timezone-aware reconstruction time."""

        if value.tzinfo is None:
            msg = "generated_at must be timezone-aware"
            raise ValueError(msg)
        return value

    def resolve(self, path: Path) -> Path:
        """Resolve repo-relative paths."""

        return path if path.is_absolute() else self.repo_root / path


class ConstructionStateCell(BaseModel):
    """A static 10m chainage cell."""

    model_config = ConfigDict(frozen=True)

    cell_id: str
    alignment_id: str
    cell_index: int
    spatial_start: float
    spatial_end: float
    cell_size_m: float
    grid_origin_m: float
    chainage_direction: str
    interval_convention: str
    point_boundary_policy: str
    cell_method_version: str


class DailyConstructionState(BaseModel):
    """One target-date end-of-day state envelope."""

    model_config = ConfigDict(frozen=True)

    daily_state_id: str
    target_date: date
    daily_scope_reference_id: str
    spatial_scope_status: str
    regime_statuses: list[str]
    raw_daily_plc_range: dict[str, object] | None
    trusted_daily_plc_range: dict[str, object] | None
    daily_excavated_scope: dict[str, object] | None
    forward_scope: dict[str, object] | None
    local_background_scope: dict[str, object] | None
    current_chainage: float | None
    raw_plc_range_span_m: float | None
    trusted_plc_range_span_m: float | None
    source_asset_ids: list[str]
    phase_interval_ids: list[str]
    episode_ids: list[str]
    spatially_usable_episode_ids: list[str]
    spatially_unusable_episode_ids: list[str]
    response_evidence_ids: list[str]
    knowledge_as_of_local_date: date
    knowledge_precision: str
    knowledge_cutoff_basis: str
    source_stage2e_manifest_hash: str
    source_applicability_manifest_hash: str
    state_method_version: str


class InitialConstructionStateVersion(BaseModel):
    """Initial daily as-known version for one cell."""

    model_config = ConfigDict(frozen=True)

    state_version_id: str
    daily_state_id: str
    cell_id: str
    target_date: date
    valid_date: date
    valid_time_precision: str
    knowledge_as_of_local_date: date
    knowledge_precision: str
    historical_transaction_time: datetime | None
    historical_transaction_time_known: bool
    transaction_time_basis: str
    reconstructed_at: datetime
    version_number: int
    supersedes_version_id: str | None
    is_current_version: bool
    cell_scope_role: CellScopeRole
    episode_ids: list[str]
    response_evidence_ids: list[str]
    daily_review_evidence_ids: list[str]
    forward_attention_evidence_ids: list[str]
    local_background_evidence_ids: list[str]
    observed_geological_evidence_ids: list[str]
    forecast_geological_evidence_ids: list[str]
    background_geological_evidence_ids: list[str]
    source_assignment_ids: list[str]
    geological_link_ids: list[str]
    response_link_ids: list[str]
    state_quality_flags: list[str]
    state_reason_codes: list[str]
    source_geology_manifest_hash: str
    source_applicability_manifest_hash: str
    source_operational_manifest_hash: str
    state_method_version: str


class StateGeologicalEvidenceLink(BaseModel):
    """Cell-level link to one primary geological evidence assignment."""

    model_config = ConfigDict(frozen=True)

    link_id: str
    state_version_id: str
    daily_state_id: str
    cell_id: str
    target_date: date
    assignment_id: str
    evidence_id: str
    document_id: str
    asset_id: str
    source_type: str
    evidence_type: str
    epistemic_status: str
    applicability_role: str
    overlap_kind: str
    overlap_start: float
    overlap_end: float
    overlap_length_m: float
    source_span_ids: list[str]
    assignment_reason_codes: list[str]
    link_reason_codes: list[str]
    source_geology_manifest_hash: str
    source_applicability_manifest_hash: str
    link_method_version: str


class StateResponseEvidenceLink(BaseModel):
    """Cell-level link to one operational response evidence record."""

    model_config = ConfigDict(frozen=True)

    link_id: str
    state_version_id: str
    daily_state_id: str
    cell_id: str
    target_date: date
    episode_id: str
    footprint_id: str
    response_evidence_id: str
    channel_name: str
    valid_time_start: datetime | None
    valid_time_end: datetime | None
    available_time: datetime | None
    trusted_overlap_start: float
    trusted_overlap_end: float
    trusted_overlap_length_m: float
    trusted_overlap_kind: str
    spatial_relation: str
    response_stat_scope: str
    spatial_scope_usable: bool
    chainage_regime_status: str
    response_quality_grade: str
    response_quality_flags: list[str]
    source_asset_ids: list[str]
    core_observation_refs: list[str]
    link_reason_codes: list[str]
    source_operational_manifest_hash: str
    link_method_version: str
