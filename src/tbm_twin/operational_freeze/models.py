"""Strict models for the Stage 2E PLC operational freeze."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tbm_twin.assets.models import SourceAsset
from tbm_twin.evidence.models import ResponseEvidence

STAGE2E_METHOD_NAME = "stage2e_plc_operational_freeze"
STAGE2E_METHOD_VERSION = "stage2e_plc_operational_freeze_v2_chainage_regime"


class OperationalFreezeConfig(BaseModel):
    """Filesystem and temporal configuration for one Stage 2E freeze run."""

    model_config = ConfigDict(frozen=True)

    repo_root: Path
    output_dir: Path
    plc_data_dir: Path | None = None
    reconstruction_time: datetime
    overwrite: bool = False
    applicability_dir: Path = Path("artifacts/stage2d_applicability_v2")
    geology_freeze_dir: Path = Path("artifacts/stage2_geology_v2_freeze_candidate")
    stage1_validation_dir: Path = Path("artifacts/stage1_validation")
    channel_catalog_path: Path = Path("configs/plc_channels.yaml")
    episode_config_path: Path = Path("configs/episode_detection.yaml")
    response_config_path: Path = Path("configs/response_evidence.yaml")

    @field_validator("reconstruction_time")
    @classmethod
    def require_reconstruction_timezone(cls, value: datetime) -> datetime:
        """Require explicit timezone-aware reconstruction time."""

        if value.tzinfo is None:
            msg = "reconstruction_time must be timezone-aware"
            raise ValueError(msg)
        return value

    def resolve(self, path: Path) -> Path:
        """Resolve repo-relative paths without changing already absolute paths."""

        return path if path.is_absolute() else self.repo_root / path


class TargetDateSet(BaseModel):
    """The unique PLC dates authorized by frozen Applicability V2."""

    model_config = ConfigDict(frozen=True)

    dates: list[date]
    source_file: Path
    assignment_date_count: int


class PlcInputAssetAuditRow(BaseModel):
    """Audit row for one raw PLC CSV asset."""

    model_config = ConfigDict(frozen=True)

    target_date: date
    raw_filename: str
    resolved_local_path: Path
    file_exists: bool
    file_size: int | None
    sha256: str | None
    encoding: str | None
    row_count: int | None
    column_count: int | None
    source_asset_id: str | None
    status: str
    warning_codes: list[str] = Field(default_factory=list)


class OperationalSourceAssetRecord(SourceAsset):
    """SourceAsset plus explicit offline reconstruction semantics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_date: date
    reconstructed_at: datetime
    historical_ingestion_time: datetime | None = None
    ingestion_time_known: bool
    ingestion_time_basis: str


class OperationalResponseEvidenceRecord(ResponseEvidence):
    """ResponseEvidence plus explicit Stage 2E freeze time semantics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_date: date
    available_time_basis: str
    baseline_method: str
    raw_spatial_scope: dict[str, object] | None
    trusted_spatial_scope: dict[str, object] | None
    spatial_scope_usable: bool
    chainage_regime_status: str
    chainage_regime_reason_codes: list[str]
    reconstructed_at: datetime
    historical_ingestion_time: datetime | None = None
    ingestion_time_known: bool
    ingestion_time_basis: str


class DailyScopeReference(BaseModel):
    """Frozen Applicability daily scope copied for independent PLC comparison."""

    model_config = ConfigDict(frozen=True)

    daily_scope_reference_id: str
    target_date: date
    daily_plc_range: dict[str, object]
    daily_excavated_scope: dict[str, object]
    forward_scope: dict[str, object]
    local_background_scope: dict[str, object]
    raw_min_chainage: float | None
    raw_max_chainage: float | None
    method_version: str


class DateBuildResult(BaseModel):
    """In-memory result for one PLC date."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    target_date: date
    source_asset_id: str
    normalized_row_count: int
    phase_interval_count: int
    episode_count: int
    footprint_count: int
    response_evidence_count: int
    raw_min_chainage: float | None
    raw_max_chainage: float | None


class OperationalFreezeResult(BaseModel):
    """High-level result returned by the Stage 2E builder."""

    model_config = ConfigDict(frozen=True)

    output_dir: Path
    target_date_count: int
    source_asset_count: int
    normalized_observation_count: int
    phase_interval_count: int
    episode_count: int
    footprint_count: int
    response_evidence_count: int
    scope_exact_match_count: int
    cross_file_candidate_count: int
    hard_check_issue_count: int
    baseline_mode: str
    reconstruction_time: datetime
