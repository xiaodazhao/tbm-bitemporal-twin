"""Content-based geological PDF source detection."""

from __future__ import annotations

from pathlib import Path

import fitz

from tbm_twin.geology.table_parser_v2.models import SourceType
from tbm_twin.geology.table_parser_v2.text_utils import compact_text


def extract_page_texts(pdf_path: Path) -> list[str]:
    """Extract paginated text with PyMuPDF for non-table source detection."""

    with fitz.open(pdf_path) as doc:
        return [page.get_text("text") for page in doc]


def detect_source_type(pdf_path: Path, page_texts: list[str] | None = None) -> SourceType:
    """Detect source type from PDF content; paths are not required."""

    texts = page_texts if page_texts is not None else extract_page_texts(pdf_path)
    joined = compact_text("\n".join(texts[:5]))
    if (
        "洞身段地质素描记录表" in joined
        or "洞身素描记录表" in joined
        or all(token in joined for token in ("掌子面状态", "地质描述", "围岩级别"))
    ):
        return SourceType.FACE_SKETCH
    if "水平声波剖面法" in joined:
        return SourceType.SONIC_FORECAST
    if "地震波反射法超前地质预报报告" in joined or "TSP法" in joined:
        return SourceType.TSP_REPORT
    return SourceType.UNSUPPORTED
