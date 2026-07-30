"""Models for raw geological PDF ingestion and canonical documents."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tbm_twin.evidence.models import (
    GeologicalSourceType,
    SpatialScope,
    TemporalCandidate,
    TemporalExtent,
)

RAW_GEOLOGY_METHOD_VERSION = "raw_geological_document_parser_v1"


class GeologicalPdfSourceAsset(BaseModel):
    """One SourceAsset-like record per raw geological PDF."""

    model_config = ConfigDict(frozen=True)

    asset_id: str
    source_path: Path
    source_filename: str
    source_type: GeologicalSourceType
    sha256: str
    content_id: str | None = None
    research_scope: str = "IN_SCOPE"
    scope_reason: str | None = None
    duplicate_of_asset_id: str | None = None
    canonical_asset_id: str | None = None
    file_size: int
    page_count: int
    text_layer_available: bool
    ingested_time: datetime
    method_version: str = RAW_GEOLOGY_METHOD_VERSION

    @field_validator("ingested_time")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            msg = "ingested_time must be timezone-aware"
            raise ValueError(msg)
        return value


class PdfPageText(BaseModel):
    """Extracted text for one PDF page."""

    model_config = ConfigDict(frozen=True)

    asset_id: str
    page_number: int
    page_text: str
    extraction_method: str
    text_length: int
    extraction_warnings: list[str] = Field(default_factory=list)


class SpatialCandidate(BaseModel):
    """Spatial candidate extracted from PDF text."""

    model_config = ConfigDict(frozen=True)

    candidate_id: str
    role: str
    raw_expression: str
    start_chainage: float | None
    end_chainage: float | None
    source_page: int | None
    source_context: str
    extraction_rule: str
    confidence: str
    validation_flags: list[str] = Field(default_factory=list)


class GeologicalDocument(BaseModel):
    """Canonical document parsed from one raw geological PDF."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    source_asset_id: str
    source_type: GeologicalSourceType
    report_id: str
    title: str | None
    tunnel_name: str | None
    face_chainage: float | None
    face_chainage_basis: str | None = None
    face_chainage_source_page: int | None = None
    face_chainage_validation_status: str | None = None
    document_spatial_scope: SpatialScope | None
    observed_time_extent: TemporalExtent | None
    document_time_extent: TemporalExtent | None
    issued_time_extent: TemporalExtent | None
    submitted_time_extent: TemporalExtent | None
    available_time_extent: TemporalExtent | None
    temporal_candidates: list[TemporalCandidate]
    spatial_candidates: list[SpatialCandidate]
    document_warnings: list[str] = Field(default_factory=list)
    method_version: str = RAW_GEOLOGY_METHOD_VERSION
