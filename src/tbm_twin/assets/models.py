"""Models for source assets."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceType(StrEnum):
    """Supported source asset types."""

    PLC_CSV = "PLC_CSV"
    TSP_REPORT = "TSP_REPORT"
    HSP_REPORT = "HSP_REPORT"
    FIELD_OBSERVATION = "FIELD_OBSERVATION"
    OTHER = "OTHER"


class SourceAsset(BaseModel):
    """A stable registry record for a source file."""

    model_config = ConfigDict(frozen=True)

    asset_id: str
    source_type: SourceType
    source_path: Path
    content_hash: str
    observed_time: datetime | None
    available_time: datetime | None
    ingested_time: datetime
    source_timezone: str | None = None
    canonical_timezone: str = "UTC"
    timezone_confidence: str = "UNKNOWN"
    timezone_basis: str = "UNKNOWN"
    timezone_warnings: list[str] = Field(default_factory=list)
    schema_version: str

    @field_validator("observed_time", "available_time", "ingested_time")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        """Require timezone-aware datetimes for temporal provenance."""

        if value is not None and value.tzinfo is None:
            msg = "SourceAsset datetimes must be timezone-aware."
            raise ValueError(msg)
        return value
