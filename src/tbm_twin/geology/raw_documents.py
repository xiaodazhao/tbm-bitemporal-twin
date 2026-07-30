"""Raw geological PDF ingestion utilities."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import fitz

from tbm_twin.evidence.models import GeologicalSourceType
from tbm_twin.geology.document_models import GeologicalPdfSourceAsset, PdfPageText


def infer_source_type_from_path(path: Path) -> GeologicalSourceType:
    """Infer source type from the containing folder and filename."""

    text = f"{path.parent.name} {path.name}".lower()
    if "sketch" in text or "素描" in text:
        return GeologicalSourceType.FACE_SKETCH
    if "hsp" in text or "声波" in text or "sonic" in text:
        return GeologicalSourceType.SONIC_FORECAST
    if "tsp" in text:
        return GeologicalSourceType.TSP_REPORT
    return GeologicalSourceType.OTHER


def register_pdf_source_asset(path: Path) -> GeologicalPdfSourceAsset:
    """Register one raw geological PDF."""

    asset, _pages = register_pdf_source_asset_with_pages(path)
    return asset


def register_pdf_source_asset_with_pages(
    path: Path,
) -> tuple[GeologicalPdfSourceAsset, list[PdfPageText]]:
    """Register one raw geological PDF and return extracted page text."""

    resolved = path.resolve()
    digest = _sha256_file(resolved)
    page_count = 0
    try:
        with fitz.open(resolved) as doc:
            page_count = doc.page_count
    except Exception:
        page_count = 0
    source_type = infer_source_type_from_path(resolved)
    asset_id = _stable_id("pdf", source_type.value, digest, str(resolved))
    content_id = _stable_id("pdf-content", source_type.value, digest)
    pages = extract_pdf_page_text(asset_id, resolved)
    scope, scope_reason = _research_scope(resolved)
    return (
        GeologicalPdfSourceAsset(
            asset_id=asset_id,
            source_path=resolved,
            source_filename=resolved.name,
            source_type=source_type,
            sha256=digest,
            content_id=content_id,
            research_scope=scope,
            scope_reason=scope_reason,
            canonical_asset_id=asset_id,
            file_size=resolved.stat().st_size,
            page_count=page_count,
            text_layer_available=any(page.text_length > 0 for page in pages),
            ingested_time=datetime.now(UTC),
        ),
        pages,
    )


def extract_pdf_page_text(asset_id: str, path: Path) -> list[PdfPageText]:
    """Extract text from each PDF page while preserving page numbers."""

    pages: list[PdfPageText] = []
    try:
        with fitz.open(path) as doc:
            for index, page in enumerate(doc, start=1):
                text = page.get_text("text") or ""
                warnings = [] if text.strip() else ["PDF_TEXT_LAYER_UNAVAILABLE"]
                pages.append(
                    PdfPageText(
                        asset_id=asset_id,
                        page_number=index,
                        page_text=text,
                        extraction_method="pymupdf_text_layer",
                        text_length=len(text.strip()),
                        extraction_warnings=warnings,
                    )
                )
    except Exception as exc:
        pages.append(
            PdfPageText(
                asset_id=asset_id,
                page_number=1,
                page_text="",
                extraction_method="pymupdf_text_layer",
                text_length=0,
                extraction_warnings=["PDF_TEXT_EXTRACTION_FAILED", type(exc).__name__],
            )
        )
    return pages


def collect_pdf_paths(*directories: Path) -> list[Path]:
    """Collect PDF paths from explicit directories."""

    paths: list[Path] = []
    for directory in directories:
        if not directory.exists():
            continue
        paths.extend(sorted(path for path in directory.glob("*.pdf") if path.is_file()))
    return sorted(paths)


def _research_scope(path: Path) -> tuple[str, str | None]:
    text = path.name
    if "左线" in text:
        return "OUT_OF_SCOPE", "LEFT_LINE_NOT_IMPORT_RIGHT_LINE"
    return "IN_SCOPE", "IMPORT_RIGHT_LINE_SCOPE"


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
