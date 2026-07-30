"""SourceSpan constructors with strict provenance checks."""

from __future__ import annotations

import hashlib

from tbm_twin.geology.table_parser_v2.models import SourceSpan, SourceSpanError
from tbm_twin.geology.table_parser_v2.pdf_tables import ExtractedCell
from tbm_twin.geology.table_parser_v2.text_utils import normalize_text


def _span_id(parts: list[object]) -> str:
    digest = hashlib.sha1("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return f"span_{digest[:16]}"


def make_table_cell_span(cell: ExtractedCell, source_role: str) -> SourceSpan:
    """Create a SourceSpan from a real pdfplumber table cell."""

    x0, y0, x1, y1 = cell.bbox
    if x1 <= x0 or y1 <= y0 or cell.bbox == (0.0, 0.0, 0.0, 0.0):
        raise SourceSpanError("INVALID_SOURCE_SPAN: table cell bbox is missing or zero")
    raw_text = normalize_text(cell.text)
    if not raw_text:
        raise SourceSpanError("INVALID_SOURCE_SPAN: table cell text is empty")
    return SourceSpan(
        span_id=_span_id(
            [
                cell.page_number,
                cell.table_index,
                cell.row_index,
                cell.column_index,
                cell.bbox,
                raw_text,
                source_role,
            ]
        ),
        page_number=cell.page_number,
        bbox=cell.bbox,
        raw_text=raw_text,
        normalized_text=raw_text,
        extraction_method="pdfplumber_table_cell",
        source_role=source_role,
        table_index=cell.table_index,
        row_index=cell.row_index,
        column_index=cell.column_index,
    )


def make_text_block_span(
    *,
    page_number: int,
    page_text: str,
    raw_text: str,
    source_role: str,
) -> SourceSpan:
    """Create a text block span only if the source text is present on that page."""

    normalized_page = normalize_text(page_text)
    normalized_raw = normalize_text(raw_text)
    if not normalized_raw or normalized_raw not in normalized_page:
        raise SourceSpanError("INVALID_SOURCE_SPAN: text block was not found on the source page")
    return SourceSpan(
        span_id=_span_id([page_number, normalized_raw, source_role]),
        page_number=page_number,
        bbox=None,
        raw_text=normalized_raw,
        normalized_text=normalized_raw,
        extraction_method="pymupdf_page_text",
        source_role=source_role,
    )
