"""Parser V2 registry."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tbm_twin.evidence.models import GeologicalSourceType
from tbm_twin.geology.parsers_v2.face_sketch import parse_face_sketch_pdf
from tbm_twin.geology.parsers_v2.hsp import parse_hsp_pdf_v2
from tbm_twin.geology.parsers_v2.models import V2ParseResult
from tbm_twin.geology.parsers_v2.tsp import parse_tsp_pdf_v2
from tbm_twin.geology.raw_documents import infer_source_type_from_path


def parser_for_source(source_type: GeologicalSourceType) -> Callable[[Path], V2ParseResult]:
    """Return a source-specific Parser V2 callable."""

    if source_type == GeologicalSourceType.FACE_SKETCH:
        return parse_face_sketch_pdf
    if source_type == GeologicalSourceType.SONIC_FORECAST:
        return parse_hsp_pdf_v2
    if source_type == GeologicalSourceType.TSP_REPORT:
        return parse_tsp_pdf_v2
    msg = f"Parser V2 does not support source type: {source_type}"
    raise ValueError(msg)


def parse_pdf_v2(path: Path) -> V2ParseResult:
    """Parse one PDF with the V2 source-specific registry."""

    source_type = infer_source_type_from_path(path)
    return parser_for_source(source_type)(path)
