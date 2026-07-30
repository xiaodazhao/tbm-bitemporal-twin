"""SourceSpan utilities for Parser V2."""

from __future__ import annotations

import hashlib
import re

from tbm_twin.geology.document_models import PdfPageText
from tbm_twin.geology.parsers_v2.models import SourceSpan


def normalize_text(text: str) -> str:
    """Compact text while preserving source text elsewhere."""

    return re.sub(r"\s+", "", text.replace("\uff5e", "~"))


def stable_id(*parts: object) -> str:
    """Short stable identifier for V2 design artifacts."""

    return hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:24]


def make_span(
    *,
    document_id: str,
    page: PdfPageText,
    raw_text: str,
    source_role: str,
    occurrence: int = 0,
    extraction_method: str | None = None,
) -> SourceSpan:
    """Create a span from a page text occurrence.

    PyMuPDF text extraction does not provide a reliable table-cell bbox here, so
    text_start/text_end are the explicit extraction location when bbox is absent.
    """

    start = page.page_text.find(raw_text)
    if start < 0:
        start = 0
        end = 0
    else:
        end = start + len(raw_text)
    method = extraction_method or page.extraction_method
    span_id = stable_id(document_id, page.page_number, source_role, occurrence, raw_text[:80])
    return SourceSpan(
        span_id=span_id,
        page_number=page.page_number,
        extraction_method=method,
        bbox=None,
        text_start=start,
        text_end=end,
        raw_text=raw_text,
        normalized_text=normalize_text(raw_text),
        source_role=source_role,
    )


def page_for_text(pages: list[PdfPageText], token: str) -> PdfPageText:
    """Return the first page containing a token."""

    for page in pages:
        if token in page.page_text:
            return page
    return pages[0]
