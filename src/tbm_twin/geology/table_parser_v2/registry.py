"""Parser registry for the pdfplumber-backed table parser V2."""

from __future__ import annotations

from pathlib import Path

from tbm_twin.geology.table_parser_v2.face_sketch import parse_face_sketch
from tbm_twin.geology.table_parser_v2.hsp import parse_hsp
from tbm_twin.geology.table_parser_v2.models import (
    ParsedDocument,
    SourceType,
    TableParserResult,
    TemplateStatus,
    TemporalMetadata,
)
from tbm_twin.geology.table_parser_v2.pdf_tables import load_pdf_pages
from tbm_twin.geology.table_parser_v2.source_detection import detect_source_type, extract_page_texts
from tbm_twin.geology.table_parser_v2.template_signatures import detect_template_variant
from tbm_twin.geology.table_parser_v2.tsp import parse_tsp


def parse_pdf_v2(pdf_path: str | Path) -> TableParserResult:
    """Parse a geological PDF using the formal table parser V2."""

    path = Path(pdf_path)
    page_texts = extract_page_texts(path)
    source_type = detect_source_type(path, page_texts)
    pages = load_pdf_pages(path)
    signature = detect_template_variant(source_type, pages)
    if signature.status == TemplateStatus.UNSUPPORTED_TEMPLATE:
        return TableParserResult(
            document=ParsedDocument(
                source_pdf_path=path,
                source_type=source_type,
                report_id=None,
                document_spatial_scope=None,
                face_chainage=None,
                temporal=TemporalMetadata(),
                template_signature=signature,
                parse_warnings=["UNSUPPORTED_TEMPLATE"],
            ),
            primary_evidence=[],
        )
    if source_type == SourceType.FACE_SKETCH:
        return parse_face_sketch(path, pages, signature)
    if source_type == SourceType.SONIC_FORECAST:
        return parse_hsp(path, pages, signature)
    if source_type == SourceType.TSP_REPORT:
        return parse_tsp(path, pages, page_texts, signature)
    return TableParserResult(
        document=ParsedDocument(
            source_pdf_path=path,
            source_type=source_type,
            report_id=None,
            document_spatial_scope=None,
            face_chainage=None,
            temporal=TemporalMetadata(),
            template_signature=signature,
            parse_warnings=["UNSUPPORTED_SOURCE_TYPE"],
        ),
        primary_evidence=[],
    )
