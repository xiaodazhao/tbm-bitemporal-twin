"""Models for quality-aware spatial footprints."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ConsistencyStatus(StrEnum):
    """Consistency of spatial evidence sources."""

    MULTI_CHANNEL_CONSISTENT = "MULTI_CHANNEL_CONSISTENT"
    PRIMARY_CHANNEL_ONLY = "PRIMARY_CHANNEL_ONLY"
    PARTIALLY_CONSISTENT = "PARTIALLY_CONSISTENT"
    INCONSISTENT = "INCONSISTENT"
    INSUFFICIENT = "INSUFFICIENT"


class ConsistencyCheckResult(BaseModel):
    """Result of one supporting-source consistency check."""

    model_config = ConfigDict(frozen=True)

    source: str
    performed: bool
    reference_advance_m: float | None
    support_advance_m: float | None
    tolerance_m: float
    status: str
    reason: str


class SpatialFootprint(BaseModel):
    """Quality-aware estimate of an episode's spatial range."""

    model_config = ConfigDict(frozen=True)

    footprint_id: str
    episode_id: str
    start_chainage: float | None
    end_chainage: float | None
    estimated_advance_m: float | None
    primary_source: str | None
    supporting_sources: list[str]
    source_asset_count: int
    channel_count: int
    independent_source_count: int
    supporting_channel_names: list[str]
    supporting_source_count: int
    consistency_checks_performed: int
    consistency_check_results: list[ConsistencyCheckResult]
    primary_observation_count: int
    consistency_status: ConsistencyStatus
    uncertainty_m: float | None
    quality_grade: str
    quality_flags: list[str]
    method_version: str
