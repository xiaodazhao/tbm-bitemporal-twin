"""Models for Stage 3B knowledge-availability revisions."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

STAGE3B_METHOD_VERSION = "stage3b_bitemporal_epistemic_state_v1_1_strict_trace"
STAGE3B_SCHEMA_VERSION = "stage3b_bitemporal_epistemic_state.v1.1"
STAGE3A_FORMAL_METHOD_VERSION = "stage3a_initial_epistemic_state_v1_1_point_response_complete"


STRICT_MODEL_CONFIG = ConfigDict(frozen=True, extra="forbid")


class KnowledgeTimeBasis(StrEnum):
    """Knowledge-time basis used by Stage 3B."""

    TARGET_DATE_END_OF_DAY_AS_KNOWN_INITIAL_STATE = "TARGET_DATE_END_OF_DAY_AS_KNOWN_INITIAL_STATE"
    PRIMARY_GEOLOGICAL_EVIDENCE_AVAILABLE_LOCAL_DATE = (
        "PRIMARY_GEOLOGICAL_EVIDENCE_AVAILABLE_LOCAL_DATE"
    )


class RevisionOperation(StrEnum):
    """Supported revision operations."""

    ADD_PRIMARY_GEOLOGICAL_EVIDENCE = "ADD_PRIMARY_GEOLOGICAL_EVIDENCE"


class RevisionRole(StrEnum):
    """Cell-local revision role."""

    DAILY_REVIEW = "DAILY_REVIEW"
    FORWARD_ATTENTION = "FORWARD_ATTENTION"
    LOCAL_BACKGROUND = "LOCAL_BACKGROUND"
    UNKNOWN = "UNKNOWN"


class Stage3BConfig(BaseModel):
    """Filesystem and time configuration for Stage 3B."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo_root: Path
    output_dir: Path = Path("artifacts/stage3b_bitemporal_epistemic_state_v1_1")
    stage3a_dir: Path = Path("artifacts/stage3a_initial_epistemic_state_v1_1")
    geology_freeze_dir: Path = Path("artifacts/stage2_geology_v2_freeze_candidate")
    applicability_dir: Path = Path("artifacts/stage2d_applicability_v2_1")
    operational_freeze_dir: Path = Path("artifacts/stage2_plc_operational_freeze_v2")
    generated_at: datetime
    knowledge_cutoff_date: date
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


class BitemporalEpistemicStateVersion(BaseModel):
    """One materialized as-known state version for a valid-date cell."""

    model_config = STRICT_MODEL_CONFIG

    bitemporal_version_id: str
    base_stage3a_state_version_id: str
    daily_state_id: str
    cell_id: str
    cell_scope_role: str
    valid_date: date
    knowledge_time_start_local_date: date
    knowledge_time_end_local_date: date | None
    knowledge_time_precision: str
    knowledge_time_basis: str
    knowledge_boundary_semantics: str
    historical_database_transaction_time: datetime | None
    historical_database_transaction_time_known: bool
    database_transaction_time_basis: str
    reconstructed_at: datetime
    version_number: int
    supersedes_bitemporal_version_id: str | None
    is_current_as_of_cutoff: bool
    revision_event_ids: list[str]
    added_geological_evidence_ids: list[str]
    added_revision_link_ids: list[str]
    materialized_daily_review_evidence_ids: list[str]
    materialized_forward_attention_evidence_ids: list[str]
    materialized_local_background_evidence_ids: list[str]
    materialized_observed_evidence_ids: list[str]
    materialized_forecast_evidence_ids: list[str]
    materialized_background_evidence_ids: list[str]
    materialized_source_assignment_ids: list[str]
    inherited_stage3a_geological_link_ids: list[str]
    materialized_revision_geological_link_ids: list[str]
    materialized_episode_ids: list[str]
    materialized_response_evidence_ids: list[str]
    materialized_response_link_ids: list[str]
    state_quality_flags: list[str]
    state_reason_codes: list[str]
    source_stage3a_manifest_hash: str
    source_geology_manifest_hash: str
    source_applicability_manifest_hash: str
    source_operational_manifest_hash: str
    stage3b_method_version: str


class KnowledgeRevisionEvent(BaseModel):
    """Event recording new knowledge that revises one valid-date cell state."""

    model_config = STRICT_MODEL_CONFIG

    revision_event_id: str
    bitemporal_version_id: str
    previous_bitemporal_version_id: str | None
    valid_date: date
    knowledge_available_local_date: date
    knowledge_time_precision: str
    document_id: str
    asset_id: str
    source_type: str
    observed_local_date: date
    available_local_date: date
    available_basis: str
    added_evidence_ids: list[str]
    added_revision_link_ids: list[str]
    affected_cell_id: str
    revision_operation: str
    revision_reason_codes: list[str]
    source_span_ids: list[str]
    stage3b_method_version: str


class RevisionGeologicalEvidenceLink(BaseModel):
    """Cell-local link created by a Stage 3B revision."""

    model_config = STRICT_MODEL_CONFIG

    revision_link_id: str
    revision_applicability_id: str
    bitemporal_version_id: str
    base_stage3a_state_version_id: str
    valid_date: date
    knowledge_available_local_date: date
    cell_id: str
    cell_scope_role: str
    evidence_id: str
    document_id: str
    asset_id: str
    source_type: str
    evidence_type: str
    epistemic_status: str
    revision_role: str
    observed_local_date: date
    available_local_date: date
    available_basis: str
    overlap_kind: str
    overlap_start: float
    overlap_end: float
    overlap_length_m: float
    source_span_ids: list[str]
    revision_reason_codes: list[str]
    source_geology_manifest_hash: str
    source_stage3a_manifest_hash: str
    link_method_version: str


class HistoricalRevisionApplicability(BaseModel):
    """Temporal/spatial revision eligibility row for one valid-date cell."""

    model_config = STRICT_MODEL_CONFIG

    revision_applicability_id: str
    valid_date: date
    knowledge_available_local_date: date
    base_stage3a_state_version_id: str
    daily_state_id: str
    cell_id: str
    cell_scope_role: str
    evidence_id: str
    document_id: str
    asset_id: str
    source_type: str
    evidence_type: str
    epistemic_status: str
    observed_local_date: date
    available_local_date: date
    available_basis: str
    evidence_spatial_scope: dict[str, object]
    cell_overlap_kind: str
    cell_overlap_start: float | None
    cell_overlap_end: float | None
    cell_overlap_length_m: float
    revision_role: str
    temporally_eligible: bool
    spatially_eligible: bool
    revision_eligible: bool
    reason_codes: list[str]
    revision_applicability_method_version: str


class StateVersionLineage(BaseModel):
    """One edge in a Stage 3B bitemporal version chain."""

    model_config = STRICT_MODEL_CONFIG

    bitemporal_version_id: str
    base_stage3a_state_version_id: str
    previous_bitemporal_version_id: str | None
    valid_date: date
    cell_id: str
    version_number: int
    knowledge_time_start_local_date: date
    knowledge_time_end_local_date: date | None
    lineage_method_version: str


class MaterializedStateSnapshot(BaseModel):
    """Standalone materialized snapshot for one bitemporal version."""

    model_config = STRICT_MODEL_CONFIG

    snapshot_id: str
    bitemporal_version_id: str
    base_stage3a_state_version_id: str
    daily_state_id: str
    cell_id: str
    cell_scope_role: str
    valid_date: date
    knowledge_time_start_local_date: date
    knowledge_time_end_local_date: date | None
    version_number: int
    is_current_as_of_cutoff: bool
    materialized_daily_review_evidence_ids: list[str]
    materialized_forward_attention_evidence_ids: list[str]
    materialized_local_background_evidence_ids: list[str]
    materialized_observed_evidence_ids: list[str]
    materialized_forecast_evidence_ids: list[str]
    materialized_background_evidence_ids: list[str]
    materialized_source_assignment_ids: list[str]
    inherited_stage3a_geological_link_ids: list[str]
    materialized_revision_geological_link_ids: list[str]
    materialized_episode_ids: list[str]
    materialized_response_evidence_ids: list[str]
    materialized_response_link_ids: list[str]
    state_quality_flags: list[str]
    state_reason_codes: list[str]
    stage3b_method_version: str
