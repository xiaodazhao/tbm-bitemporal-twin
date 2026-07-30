"""Template inventory for raw geological PDFs."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import fitz

from tbm_twin.geology.parsers_v2.table_utils import compact
from tbm_twin.geology.raw_documents import register_pdf_source_asset_with_pages

pdfplumber_module: Any | None
try:  # pragma: no cover - depends on optional runtime environment
    import pdfplumber as _pdfplumber_module

    pdfplumber_module = _pdfplumber_module
except Exception:  # pragma: no cover
    pdfplumber_module = None


def inventory_pdf(path: Path) -> dict[str, Any]:
    """Inventory one PDF template without producing Evidence."""

    asset, pages = register_pdf_source_asset_with_pages(path)
    dimensions = _page_dimensions(path)
    table_info = _pdfplumber_table_info(path)
    text = "\n".join(page.page_text for page in pages)
    header = _header_fingerprint(text)
    sections = _section_fingerprint(text)
    variant_basis = f"{asset.source_type.value}|{asset.page_count}|{header}|{sections}"
    variant_id = hashlib.sha256(variant_basis.encode("utf-8")).hexdigest()[:12]
    return {
        "asset_id": asset.asset_id,
        "source_path": str(path),
        "source_type": asset.source_type.value,
        "page_count": asset.page_count,
        "page_dimensions": json.dumps(dimensions, ensure_ascii=False),
        "pdfplumber_table_count": table_info["table_count"],
        "table_shapes": json.dumps(table_info["table_shapes"], ensure_ascii=False),
        "header_fingerprint": header,
        "cross_page_table_likely": _cross_page_table_likely(text),
        "section_fingerprint": sections,
        "template_variant_id": variant_id,
        "classification_basis": variant_basis,
        "inventory_warnings": ";".join(table_info["warnings"]),
    }


def build_template_variants(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Group inventory rows by template variant."""

    variants: dict[str, Any] = {}
    for row in rows:
        item = variants.setdefault(
            row["template_variant_id"],
            {
                "source_type": row["source_type"],
                "page_count_values": set(),
                "asset_count": 0,
                "header_fingerprint": row["header_fingerprint"],
                "section_fingerprint": row["section_fingerprint"],
                "classification_basis": row["classification_basis"],
            },
        )
        item["asset_count"] += 1
        item["page_count_values"].add(row["page_count"])
    for item in variants.values():
        item["page_count_values"] = sorted(item["page_count_values"])
    return variants


def unclassified_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows with weak template evidence."""

    out: list[dict[str, Any]] = []
    for row in rows:
        if not row["header_fingerprint"] and not row["section_fingerprint"]:
            out.append({**row, "reason": "NO_HEADER_OR_SECTION_FINGERPRINT"})
    return out


def _page_dimensions(path: Path) -> list[dict[str, float | int]]:
    dimensions: list[dict[str, float | int]] = []
    with fitz.open(path) as doc:
        for index, page in enumerate(doc, start=1):
            rect = page.rect
            dimensions.append(
                {
                    "page": index,
                    "width": round(rect.width, 2),
                    "height": round(rect.height, 2),
                }
            )
    return dimensions


def _pdfplumber_table_info(path: Path) -> dict[str, Any]:
    if pdfplumber_module is None:
        return {
            "table_count": "",
            "table_shapes": [],
            "warnings": ["PDFPLUMBER_UNAVAILABLE"],
        }
    table_count = 0
    shapes: list[dict[str, int]] = []
    with pdfplumber_module.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables() or []:
                table_count += 1
                rows = len(table)
                cols = max((len(row) for row in table), default=0)
                shapes.append({"page": page_number, "rows": rows, "cols": cols})
    return {"table_count": table_count, "table_shapes": shapes, "warnings": []}


def _header_fingerprint(text: str) -> str:
    flat = compact(text)
    candidates = [
        "里程范围本次预报结论物探探测结果预报结论风险提示建议围岩等级",
        "里程范围物性参数物探分析预报结论",
        "掌子面尺寸掌子面状态毛开挖面状态岩石强度风化程度",
    ]
    found = [item for item in candidates if item in flat]
    return "|".join(found)


def _section_fingerprint(text: str) -> str:
    sections = re.findall(r"(?:^|\n)\s*(\d+(?:\.\d+)?\s*[\u4e00-\u9fffA-Za-z].{0,24})", text)
    return "|".join(compact(item)[:24] for item in sections[:12])


def _cross_page_table_likely(text: str) -> bool:
    flat = compact(text)
    return ("表2隧道超前地质预报报表" in flat and flat.count("纵波速度Vp") >= 5) or (
        "表1隧道超前地质预报报表" in flat and flat.count("里程范围") > 1
    )
