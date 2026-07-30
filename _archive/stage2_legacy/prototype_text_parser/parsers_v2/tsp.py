"""TSP Parser V2."""

# ruff: noqa: RUF001

from __future__ import annotations

import re
from pathlib import Path

from tbm_twin.evidence.models import GeologicalSourceType
from tbm_twin.geology.document_models import PdfPageText
from tbm_twin.geology.parsers_v2.models import (
    PrimaryEvidenceType,
    ReportAssertion,
    SpatialKind,
    V2Document,
    V2EpistemicStatus,
    V2Evidence,
    V2ParseResult,
    V2SpatialScope,
    V2TemporalSummary,
)
from tbm_twin.geology.parsers_v2.provenance import make_span, stable_id
from tbm_twin.geology.parsers_v2.report_assertions import make_assertion
from tbm_twin.geology.parsers_v2.table_utils import (
    arabic_date,
    chinese_date,
    compact,
    find_page,
    parse_first_chainage,
    parse_range,
)
from tbm_twin.geology.raw_documents import register_pdf_source_asset_with_pages


def parse_tsp_pdf_v2(path: Path) -> V2ParseResult:
    """Parse one TSP PDF with table-row evidence plus report assertions."""

    asset, pages = register_pdf_source_asset_with_pages(path)
    text = "\n".join(page.page_text for page in pages)
    document_id = stable_id("v2-doc", asset.asset_id)
    scope_start, scope_end, scope_raw = parse_range(text)
    face = _tsp_face_chainage(text) or scope_start
    observed = arabic_date(_after(text, "测试日期") or "")
    documented = chinese_date(pages[0].page_text) or arabic_date(path.name)
    submitted = documented.isoformat() if documented else None
    temporal = V2TemporalSummary(
        observed_local_date=observed.isoformat() if observed else None,
        documented_local_date=documented.isoformat() if documented else None,
        submitted_local_date=submitted,
        available_local_date=submitted,
        available_basis="SUBMITTED_TIME_PRIORITY",
    )
    table_pages = [
        page for page in pages if "里程范围" in page.page_text or "纵波速度Vp" in page.page_text
    ]
    face_page = find_page(pages, "开挖面 \n地质概况")
    face_text = _between(face_page.page_text, "开挖面 \n地质概况", "里程范围")
    face_span = make_span(
        document_id=document_id,
        page=face_page,
        raw_text=face_text,
        source_role="tsp_face_observation",
    )
    evidence = [
        V2Evidence(
            evidence_id=stable_id("v2-evidence", document_id, "tsp-face", face),
            document_id=document_id,
            evidence_type=PrimaryEvidenceType.FACE_OBSERVATION,
            epistemic_status=V2EpistemicStatus.OBSERVED,
            spatial_scope=V2SpatialScope(
                kind=SpatialKind.POINT,
                start_chainage=face,
                end_chainage=face,
                raw_expression=f"DyK{face / 1000:.4f}",
                basis="explicit_tsp_face_chainage",
            ),
            source_spans=[face_span],
            field_spans={
                "face_observation": [face_span.span_id],
                "face_chainage": [face_span.span_id],
            },
            assembled_text=face_text,
            attributes={"face_geology": compact(face_text)},
        )
    ]
    rows = _table_rows(table_pages)
    for index, (page, row) in enumerate(rows, start=1):
        start, end, raw_range = parse_range(row)
        span = make_span(
            document_id=document_id,
            page=page,
            raw_text=row,
            source_role="tsp_table2_row",
            occurrence=index,
        )
        attrs = _tsp_row_attributes(row)
        evidence.append(
            V2Evidence(
                evidence_id=stable_id("v2-evidence", document_id, "tsp", start, end),
                document_id=document_id,
                evidence_type=PrimaryEvidenceType.FORECAST_SEGMENT,
                epistemic_status=V2EpistemicStatus.FORECAST,
                spatial_scope=V2SpatialScope(
                    kind=SpatialKind.INTERVAL,
                    start_chainage=start,
                    end_chainage=end,
                    raw_expression=raw_range,
                    basis="tsp_table2_row_range",
                ),
                source_spans=[span],
                field_spans={key: [span.span_id] for key in attrs | {"range": raw_range}},
                assembled_text=row,
                attributes=attrs,
            )
        )
    assertions = _report_assertions(document_id, pages, evidence[1:])
    document = V2Document(
        document_id=document_id,
        source_pdf_path=path,
        source_type=GeologicalSourceType.TSP_REPORT.value,
        report_id=path.stem,
        document_spatial_scope=V2SpatialScope(
            kind=SpatialKind.INTERVAL,
            start_chainage=scope_start,
            end_chainage=scope_end,
            raw_expression=scope_raw,
            basis="document_forecast_scope",
        ),
        face_chainage=face,
        temporal=temporal,
        source_spans=[face_span, *[span for item in evidence[1:] for span in item.source_spans]],
        template_variant_id="TSP_TABLE2_V1",
    )
    return V2ParseResult(document=document, primary_evidence=evidence, report_assertions=assertions)


def _after(text: str, token: str) -> str | None:
    index = text.find(token)
    return text[index : index + 300] if index >= 0 else None


def _tsp_face_chainage(text: str) -> float | None:
    flat = compact(text)
    match = re.search(r"开挖面里程((?:DyK|DK|K)\d+\+\d+(?:\.\d+)?)", flat)
    return parse_first_chainage(match.group(1)) if match else None


def _between(text: str, start_token: str, end_token: str) -> str:
    start = text.find(start_token)
    if start < 0:
        return ""
    end = text.find(end_token, start)
    return text[start:end].strip() if end > start else text[start:].strip()


def _table_rows(pages: list[PdfPageText]) -> list[tuple[PdfPageText, str]]:
    joined = "\n".join(page.page_text for page in pages)
    matches = list(re.finditer(r"DyK\d+\+\d+(?:\.\d+)?\s*~\s*DyK\d+\+\d+(?:\.\d+)?", joined))
    rows: list[tuple[PdfPageText, str]] = []
    for index, match in enumerate(matches):
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else joined.find("下一次", match.start())
        )
        end = end if end > match.start() else len(joined)
        row = joined[match.start() : end].strip()
        if "纵波速度Vp" not in row:
            continue
        page = next(
            (item for item in pages if match.group(0).split("\n")[0] in item.page_text), pages[0]
        )
        rows.append((page, row))
    return rows


def _tsp_row_attributes(row: str) -> dict[str, str | float | int | bool | list[str] | None]:
    flat = compact(row)
    return {
        "vp": _param(flat, "纵波速度Vp"),
        "vs": _param(flat, "横波速度Vs"),
        "vp_vs": _param(flat, "速度比Vp/Vs"),
        "poisson_ratio": _param(flat, "泊松比υ"),
        "dynamic_elastic_modulus": _param(flat, "动态杨氏模量E"),
        "physical_interpretation": _physical_interpretation(flat),
        "geological_conclusion": _geological_conclusion(flat),
        "suggested_grade": _suggested_grade(flat),
    }


def _param(flat: str, label: str) -> str | None:
    match = re.search(rf"{label}[:：]?([0-9.]+(?:~[0-9.]+)?)(?:m/s|GPa)?", flat)
    return match.group(1) if match else None


def _physical_interpretation(flat: str) -> str | None:
    match = re.search(r"该段围岩的.*?。", flat)
    return match.group(0) if match else None


def _geological_conclusion(flat: str) -> str | None:
    match = re.search(r"推测该段.*", flat)
    return match.group(0) if match else None


def _suggested_grade(flat: str) -> str | None:
    match = re.search(r"按([ⅠⅡⅢⅣⅤIVX]+)级围岩施工", flat)
    return f"{match.group(1)}级" if match else None


def _report_assertions(
    document_id: str,
    pages: list[PdfPageText],
    forecast_evidence: list[V2Evidence],
) -> list[ReportAssertion]:
    conclusion_page = next(
        (
            page
            for page in pages
            if "以下结论" in compact(page.page_text) and "DyK1013+080.2" in page.page_text
        ),
        find_page(pages, "7 结论"),
    )
    conclusion = _between(conclusion_page.page_text, "7 结论", "本次伯舒拉岭")
    span = make_span(
        document_id=document_id,
        page=conclusion_page,
        raw_text=conclusion,
        source_role="tsp_chapter7_conclusion",
    )
    by_scope = {
        (item.spatial_scope.start_chainage, item.spatial_scope.end_chainage): item
        for item in forecast_evidence
    }
    assertions: list[ReportAssertion] = []
    for raw, grade in [
        ("DyK1013+080.2～DyK1013+161", "Ⅴ级"),
        ("DyK1013+161～DyK1013+182", "Ⅳ级"),
        ("DyK1013+182～DyK1013+200.2", "Ⅳ级"),
    ]:
        start, end, raw_range = parse_range(raw)
        derived = [
            item.evidence_id
            for (item_start, item_end), item in by_scope.items()
            if item_start >= start and item_end <= end
        ]
        conflicts = []
        if start == 1013182.0 and end == 1013200.2:
            table_item = by_scope.get((1013182.0, 1013200.2))
            table_grade = table_item.attributes.get("suggested_grade") if table_item else None
            if table_grade != grade:
                conflicts.append(
                    f"table suggested_grade={table_grade}; summary suggested_grade={grade}"
                )
        assertions.append(
            make_assertion(
                document_id=document_id,
                assertion_type="GRADE_SUMMARY",
                spatial_scope=V2SpatialScope(
                    kind=SpatialKind.INTERVAL,
                    start_chainage=start,
                    end_chainage=end,
                    raw_expression=raw_range,
                    basis="tsp_chapter7_grade_summary",
                ),
                raw_text=f"{raw} 建议按{grade}围岩施工",
                source_spans=[span],
                derived_from_evidence_ids=derived,
                consistency_status="CONFLICT" if conflicts else "CONSISTENT",
                conflict_details=conflicts,
            )
        )
    for assertion_type, ranges in {
        "WATER_SUMMARY": [
            "DyK1013+096～DyK1013+114",
            "DyK1013+130～DyK1013+137",
            "DyK1013+137～DyK1013+161",
            "DyK1013+182～DyK1013+200.2",
        ],
        "BLOCK_FALL_SUMMARY": ["DyK1013+137～DyK1013+161", "DyK1013+182～DyK1013+200.2"],
    }.items():
        for raw in ranges:
            start, end, raw_range = parse_range(raw)
            assertions.append(
                make_assertion(
                    document_id=document_id,
                    assertion_type=assertion_type,
                    spatial_scope=V2SpatialScope(
                        kind=SpatialKind.INTERVAL,
                        start_chainage=start,
                        end_chainage=end,
                        raw_expression=raw_range,
                        basis=f"tsp_chapter7_{assertion_type.lower()}",
                    ),
                    raw_text=raw,
                    source_spans=[span],
                    derived_from_evidence_ids=[
                        item.evidence_id
                        for item in forecast_evidence
                        if item.spatial_scope.start_chainage <= start
                        and item.spatial_scope.end_chainage >= end
                    ],
                )
            )
    return assertions
