"""pdfplumber table extraction utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from tbm_twin.geology.table_parser_v2.text_utils import normalize_text


def _bbox_tuple(value: tuple[float, ...]) -> tuple[float, float, float, float]:
    if len(value) != 4:
        raise ValueError("pdfplumber returned a non-rectangular bbox")
    return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))


@dataclass(frozen=True)
class ExtractedCell:
    """One pdfplumber table cell with its real page bbox."""

    page_number: int
    table_index: int
    row_index: int
    column_index: int
    bbox: tuple[float, float, float, float]
    text: str


@dataclass(frozen=True)
class ExtractedTable:
    """One extracted table."""

    page_number: int
    table_index: int
    bbox: tuple[float, float, float, float]
    rows: list[list[ExtractedCell | None]]

    @property
    def shape(self) -> tuple[int, int]:
        """Return row and max-column count."""

        return len(self.rows), max((len(row) for row in self.rows), default=0)

    def joined_text(self) -> str:
        """Return normalized table text for template detection."""

        return normalize_text(
            " ".join(cell.text for row in self.rows for cell in row if cell is not None)
        )


@dataclass(frozen=True)
class ExtractedPage:
    """Page text plus extracted tables."""

    page_number: int
    text: str
    tables: list[ExtractedTable]


def load_pdf_pages(pdf_path: Path) -> list[ExtractedPage]:
    """Load page text and real pdfplumber table cells."""

    pages: list[ExtractedPage] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_tables: list[ExtractedTable] = []
            for table_index, table in enumerate(page.find_tables()):
                extracted = table.extract()
                table_rows = table.rows
                rows: list[list[ExtractedCell | None]] = []
                for row_index, row_values in enumerate(extracted):
                    bbox_row = table_rows[row_index].cells if row_index < len(table_rows) else []
                    cells: list[ExtractedCell | None] = []
                    for column_index, value in enumerate(row_values):
                        bbox = bbox_row[column_index] if column_index < len(bbox_row) else None
                        text = normalize_text(value or "")
                        if bbox is None:
                            cells.append(None)
                            continue
                        raw_from_bbox = page.crop(bbox).extract_text() or text
                        cells.append(
                            ExtractedCell(
                                page_number=page_number,
                                table_index=table_index,
                                row_index=row_index,
                                column_index=column_index,
                                bbox=_bbox_tuple(tuple(float(part) for part in bbox)),
                                text=normalize_text(raw_from_bbox or text),
                            )
                        )
                    rows.append(cells)
                page_tables.append(
                    ExtractedTable(
                        page_number=page_number,
                        table_index=table_index,
                        bbox=_bbox_tuple(tuple(float(part) for part in table.bbox)),
                        rows=rows,
                    )
                )
            pages.append(
                ExtractedPage(
                    page_number=page_number,
                    text=page.extract_text() or "",
                    tables=page_tables,
                )
            )
    return pages
