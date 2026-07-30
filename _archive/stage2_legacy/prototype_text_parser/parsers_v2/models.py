"""Parser V2 models for source-spanned geological extraction."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class PrimaryEvidenceType(StrEnum):
    """Only primary evidence types allowed in Parser V2."""

    FACE_OBSERVATION = "FACE_OBSERVATION"
    FORECAST_SEGMENT = "FORECAST_SEGMENT"
    DESIGN_BACKGROUND = "DESIGN_BACKGROUND"


class V2EpistemicStatus(StrEnum):
    """V2 epistemic status."""

    OBSERVED = "OBSERVED"
    FORECAST = "FORECAST"
    BACKGROUND = "BACKGROUND"


class SpatialKind(StrEnum):
    """Spatial geometry carried by a V2 evidence record."""

    POINT = "POINT"
    INTERVAL = "INTERVAL"


class SourceSpan(BaseModel):
    """A source-local span used by one or more extracted fields."""

    model_config = ConfigDict(frozen=True)

    span_id: str
    page_number: int
    extraction_method: str
    bbox: tuple[float, float, float, float] | None = None
    text_start: int | None = None
    text_end: int | None = None
    raw_text: str
    normalized_text: str
    source_role: str


class V2SpatialScope(BaseModel):
    """Spatial point or interval in normalized chainage metres."""

    model_config = ConfigDict(frozen=True)

    kind: SpatialKind
    start_chainage: float
    end_chainage: float
    raw_expression: str
    basis: str


class V2TemporalSummary(BaseModel):
    """Local-date temporal semantics for V2 design validation."""

    model_config = ConfigDict(frozen=True)

    observed_local_date: str | None = None
    documented_local_date: str | None = None
    submitted_local_date: str | None = None
    available_local_date: str | None = None
    available_basis: str | None = None


class V2Evidence(BaseModel):
    """A primary V2 geological evidence record."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    document_id: str
    evidence_type: PrimaryEvidenceType
    epistemic_status: V2EpistemicStatus
    spatial_scope: V2SpatialScope
    source_spans: list[SourceSpan]
    field_spans: dict[str, list[str]]
    assembled_text: str
    attributes: dict[str, str | float | int | bool | list[str] | None]


class ReportAssertion(BaseModel):
    """Report-level assertion separated from primary Evidence."""

    model_config = ConfigDict(frozen=True)

    assertion_id: str
    document_id: str
    assertion_type: str
    spatial_scope: V2SpatialScope
    raw_text: str
    source_spans: list[SourceSpan]
    derived_from_evidence_ids: list[str]
    consistency_status: str
    conflict_details: list[str] = Field(default_factory=list)


class V2Document(BaseModel):
    """Document-level V2 parse result."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    source_pdf_path: Path
    source_type: str
    report_id: str
    document_spatial_scope: V2SpatialScope | None
    face_chainage: float | None
    temporal: V2TemporalSummary
    source_spans: list[SourceSpan]
    template_variant_id: str
    parse_warnings: list[str] = Field(default_factory=list)


class V2ParseResult(BaseModel):
    """Complete V2 result for one PDF."""

    model_config = ConfigDict(frozen=True)

    document: V2Document
    primary_evidence: list[V2Evidence]
    report_assertions: list[ReportAssertion] = Field(default_factory=list)
