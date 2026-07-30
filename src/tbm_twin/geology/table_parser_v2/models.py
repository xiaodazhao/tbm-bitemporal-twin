"""Models for the pdfplumber-backed geological table parser."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class SourceType(StrEnum):
    """Content-based source type."""

    FACE_SKETCH = "FACE_SKETCH"
    SONIC_FORECAST = "SONIC_FORECAST"
    TSP_REPORT = "TSP_REPORT"
    UNSUPPORTED = "UNSUPPORTED"


class PrimaryEvidenceType(StrEnum):
    """Formal primary evidence units emitted by the table parser."""

    FACE_OBSERVATION = "FACE_OBSERVATION"
    FORECAST_SEGMENT = "FORECAST_SEGMENT"
    DESIGN_BACKGROUND = "DESIGN_BACKGROUND"


class EpistemicStatus(StrEnum):
    """Evidence epistemic status."""

    OBSERVED = "OBSERVED"
    FORECAST = "FORECAST"
    BACKGROUND = "BACKGROUND"


class SpatialKind(StrEnum):
    """Spatial scope geometry."""

    POINT = "POINT"
    INTERVAL = "INTERVAL"


class TemplateStatus(StrEnum):
    """Template matching status."""

    SUPPORTED = "SUPPORTED"
    UNSUPPORTED_TEMPLATE = "UNSUPPORTED_TEMPLATE"


class SourceSpanError(ValueError):
    """Raised when a requested source span cannot be represented honestly."""


@dataclass(frozen=True)
class SourceSpan:
    """A source-local table cell or text block reference."""

    span_id: str
    page_number: int
    bbox: tuple[float, float, float, float] | None
    raw_text: str
    normalized_text: str
    extraction_method: str
    source_role: str
    table_index: int | None = None
    row_index: int | None = None
    column_index: int | None = None

    @property
    def has_real_bbox(self) -> bool:
        """Return True when bbox is present and not a zero placeholder."""

        if self.bbox is None:
            return False
        x0, y0, x1, y1 = self.bbox
        return x1 > x0 and y1 > y0 and self.bbox != (0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class SpatialScope:
    """Spatial point or interval in absolute chainage metres."""

    kind: SpatialKind
    start_chainage: float
    end_chainage: float
    raw_expression: str
    basis: str


@dataclass(frozen=True)
class TemporalMetadata:
    """Local-date temporal metadata extracted from reports."""

    observed_local_date: str | None = None
    document_local_date: str | None = None
    submitted_local_date: str | None = None
    available_local_date: str | None = None
    available_basis: str | None = None


@dataclass(frozen=True)
class TemplateSignature:
    """Template signature actually consumed by a parser."""

    template_variant_id: str
    source_type: SourceType
    status: TemplateStatus
    key_headers: tuple[str, ...]
    semantic_columns: tuple[str, ...]
    table_shape: str
    continuation_pattern: str


@dataclass(frozen=True)
class TableParserEvidence:
    """Primary geological evidence record emitted by the parser."""

    evidence_id: str
    evidence_type: PrimaryEvidenceType
    epistemic_status: EpistemicStatus
    spatial_scope: SpatialScope
    source_spans: list[SourceSpan]
    field_spans: dict[str, list[str]]
    assembled_text: str
    attributes: dict[str, Any]


@dataclass(frozen=True)
class ReportAssertion:
    """Report-level assertion separated from primary evidence."""

    assertion_id: str
    assertion_type: str
    spatial_scope: SpatialScope
    raw_text: str
    source_spans: list[SourceSpan]
    attributes: dict[str, Any]
    derived_from_evidence_ids: list[str]
    consistency_status: str
    conflict_details: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedDocument:
    """Document-level parse metadata."""

    source_pdf_path: Path
    source_type: SourceType
    report_id: str | None
    document_spatial_scope: SpatialScope | None
    face_chainage: float | None
    temporal: TemporalMetadata
    template_signature: TemplateSignature
    parse_warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TableParserResult:
    """Complete parse result for one PDF."""

    document: ParsedDocument
    primary_evidence: list[TableParserEvidence]
    report_assertions: list[ReportAssertion] = field(default_factory=list)
    audit_rows: list[dict[str, Any]] = field(default_factory=list)
