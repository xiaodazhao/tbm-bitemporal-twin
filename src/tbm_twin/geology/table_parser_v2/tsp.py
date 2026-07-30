# ruff: noqa: RUF001
"""TSP forecast table parser."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from tbm_twin.geology.table_parser_v2.models import (
    EpistemicStatus,
    ParsedDocument,
    PrimaryEvidenceType,
    SourceType,
    SpatialKind,
    SpatialScope,
    TableParserEvidence,
    TableParserResult,
    TemplateSignature,
    TemporalMetadata,
)
from tbm_twin.geology.table_parser_v2.pdf_tables import ExtractedCell, ExtractedPage, ExtractedTable
from tbm_twin.geology.table_parser_v2.provenance import make_table_cell_span
from tbm_twin.geology.table_parser_v2.report_assertions import parse_tsp_report_assertions
from tbm_twin.geology.table_parser_v2.text_utils import (
    compact_text,
    first_local_date,
    normalize_text,
    parse_chainage_interval,
    parse_chainage_value,
    parse_submitted_local_date,
    raw_chainage_interval,
)


def parse_tsp(
    pdf_path: Path,
    pages: list[ExtractedPage],
    page_texts: list[str],
    template_signature: TemplateSignature,
) -> TableParserResult:
    """Parse TSP face observation, table rows, and report assertions."""

    forecast_tables = _forecast_tables(pages)
    document_text = "\n".join(page_texts)
    document_scope = _document_scope(pdf_path, document_text)
    face_chainage = _face_chainage(forecast_tables, document_text)
    evidence: list[TableParserEvidence] = []
    face = _face_observation(pdf_path, forecast_tables, face_chainage)
    if face is not None:
        evidence.append(face)
    table_evidence = []
    for index, row in enumerate(_forecast_rows(forecast_tables), start=1):
        parsed = _row_to_evidence(pdf_path, row, index)
        if parsed is not None:
            evidence.append(parsed)
            table_evidence.append(parsed)
    assertions = parse_tsp_report_assertions(pdf_path, page_texts, table_evidence)
    document = ParsedDocument(
        source_pdf_path=pdf_path,
        source_type=SourceType.TSP_REPORT,
        report_id=_report_id(document_text),
        document_spatial_scope=document_scope,
        face_chainage=face_chainage,
        temporal=_temporal(document_text, forecast_tables),
        template_signature=template_signature,
    )
    return TableParserResult(
        document=document, primary_evidence=evidence, report_assertions=assertions
    )


def _forecast_tables(pages: list[ExtractedPage]) -> list[ExtractedTable]:
    selected: list[ExtractedTable] = []
    active = False
    for page in pages:
        for table in page.tables:
            text = compact_text(table.joined_text())
            is_header = "里程范围" in text and "物性参数" in text and "预报结论" in text
            has_data = any(_row_interval(row) is not None for row in table.rows)
            if is_header:
                active = True
                selected.append(table)
            elif active and has_data:
                selected.append(table)
            elif active and "下一次超前预报里程" in text:
                selected.append(table)
                active = False
    return selected


def _forecast_rows(tables: list[ExtractedTable]) -> list[list[ExtractedCell | None]]:
    rows: list[list[ExtractedCell | None]] = []
    for table in tables:
        for row in table.rows:
            text = _row_text(row)
            if _row_interval(row) is not None and "下一次" not in compact_text(text):
                rows.append(row)
    return rows


def _row_interval(row: list[ExtractedCell | None]) -> tuple[float, float] | None:
    first = next((cell.text for cell in row if cell is not None and normalize_text(cell.text)), "")
    return parse_chainage_interval(first)


def _row_text(row: list[ExtractedCell | None]) -> str:
    return normalize_text(" ".join(cell.text for cell in row if cell is not None))


def _row_to_evidence(
    pdf_path: Path,
    row: list[ExtractedCell | None],
    index: int,
) -> TableParserEvidence | None:
    interval = _row_interval(row)
    if interval is None:
        return None
    start, end = interval
    row_text = _row_text(row)
    scope = SpatialScope(
        kind=SpatialKind.INTERVAL,
        start_chainage=start,
        end_chainage=end,
        raw_expression=raw_chainage_interval(row_text),
        basis="tsp_forecast_table_row",
    )
    cells = _non_empty_cells(row)
    spans = [make_table_cell_span(cell, _tsp_role(cell, row)) for cell in cells]
    attrs = _attributes(row)
    return TableParserEvidence(
        evidence_id=_evidence_id(pdf_path, f"tsp_row_{index}", scope.raw_expression),
        evidence_type=PrimaryEvidenceType.FORECAST_SEGMENT,
        epistemic_status=EpistemicStatus.FORECAST,
        spatial_scope=scope,
        source_spans=spans,
        field_spans=_field_spans(spans),
        assembled_text=row_text,
        attributes=attrs,
    )


def _attributes(row: list[ExtractedCell | None]) -> dict[str, Any]:
    cells = _cell_texts(row)
    params = cells[1] if len(cells) > 1 else ""
    interpretation = cells[2] if len(cells) > 2 else ""
    conclusion = cells[4] if len(cells) >= 6 else (cells[3] if len(cells) > 3 else "")
    return {
        "vp": _parameter(params, r"纵波速度Vp[:：]\s*([0-9~～.]+)"),
        "vs": _parameter(params, r"横波速度Vs[:：]\s*([0-9~～.]+)"),
        "vp_vs": _parameter(params, r"速度比Vp/Vs[:：]\s*([0-9~～.]+)"),
        "poisson_ratio": _parameter(params, r"泊松比υ[:：]\s*([0-9~～.]+)"),
        "dynamic_elastic_modulus": _parameter(params, r"动态杨氏模量E(?:d)?[:：]\s*([0-9~～.]+)"),
        "physical_parameters": params,
        "physical_interpretation": interpretation,
        "geological_conclusion": conclusion,
        "suggested_grade": _grade(conclusion),
        "lithology": _match_first(("板岩夹变质砂岩", "板岩夹砂岩", "板岩", "变质砂岩"), conclusion),
        "weathering": _match_first(("弱风化", "微风化", "强风化", "全风化"), conclusion),
        "joint_development": _match_first(
            ("节理裂隙极发育", "节理裂隙发育密集", "节理裂隙较发育", "节理裂隙发育"), conclusion
        ),
        "rock_mass_state": _match_first(
            ("岩体破碎-极破碎", "岩体较破碎", "岩体破碎", "岩体极破碎"), conclusion
        ),
        "water_type": _match_first(
            ("滴渗水-线状出水", "线-股状出水", "线状出水", "股状出水", "滴渗水"), conclusion
        ),
        "block_fall_or_collapse": "掉块风险" if "掉块" in conclusion else None,
    }


def _face_observation(
    pdf_path: Path,
    tables: list[ExtractedTable],
    face_chainage: float | None,
) -> TableParserEvidence | None:
    for table in tables:
        for row in table.rows:
            text = _row_text(row)
            if "开挖面" in compact_text(text) and "地质概况" in compact_text(text):
                spans = [
                    make_table_cell_span(cell, "face_geology") for cell in _non_empty_cells(row)
                ]
                scope = SpatialScope(
                    kind=SpatialKind.POINT,
                    start_chainage=face_chainage or 0.0,
                    end_chainage=face_chainage or 0.0,
                    raw_expression=str(face_chainage or ""),
                    basis="tsp_face_chainage_cell",
                )
                return TableParserEvidence(
                    evidence_id=_evidence_id(pdf_path, "tsp_face", text),
                    evidence_type=PrimaryEvidenceType.FACE_OBSERVATION,
                    epistemic_status=EpistemicStatus.OBSERVED,
                    spatial_scope=scope,
                    source_spans=spans,
                    field_spans=_field_spans(spans),
                    assembled_text=text,
                    attributes={
                        "geological_description": text,
                        "lithology": _match_first(("板岩夹变质砂岩", "板岩夹砂岩", "板岩"), text),
                        "weathering": _match_first(("弱风化", "微风化", "强风化"), text),
                        "water_type": _match_first(
                            ("滴渗水-线状出水", "线-股状出水", "线状出水", "股状出水", "滴渗水"),
                            text,
                        ),
                    },
                )
    return None


def _cell_texts(row: list[ExtractedCell | None]) -> list[str]:
    return [normalize_text(cell.text) if cell is not None else "" for cell in row]


def _non_empty_cells(row: list[ExtractedCell | None]) -> list[ExtractedCell]:
    return [cell for cell in row if cell is not None and normalize_text(cell.text)]


def _tsp_role(cell: ExtractedCell, row: list[ExtractedCell | None]) -> str:
    columns = len(row)
    if cell.column_index == 0:
        return "range"
    if cell.column_index == 1:
        return "physical_parameters"
    if cell.column_index == 2:
        return "physical_interpretation"
    if columns >= 6 and cell.column_index == 4:
        return "geological_conclusion"
    if columns < 6 and cell.column_index == 3:
        return "geological_conclusion"
    return "forecast_table_cell"


def _field_spans(spans: list[Any]) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for span in spans:
        fields.setdefault(span.source_role, []).append(span.span_id)
    return fields


def _document_scope(pdf_path: Path, text: str) -> SpatialScope | None:
    filename_interval = parse_chainage_interval(pdf_path.name)
    interval = filename_interval or parse_chainage_interval(text)
    if interval is None:
        return None
    return SpatialScope(
        kind=SpatialKind.INTERVAL,
        start_chainage=interval[0],
        end_chainage=interval[1],
        raw_expression=raw_chainage_interval(pdf_path.name)
        if filename_interval
        else raw_chainage_interval(text),
        basis="filename_forecast_scope" if filename_interval else "cover_forecast_scope",
    )


def _face_chainage(tables: list[ExtractedTable], document_text: str) -> float | None:
    for table in tables:
        for row in table.rows:
            text = _row_text(row)
            if "开挖面里程" in compact_text(text):
                value = parse_chainage_value(text)
                if value is not None:
                    return value
    return parse_chainage_value(document_text)


def _temporal(text: str, tables: list[ExtractedTable]) -> TemporalMetadata:
    observed = None
    for table in tables:
        for row in table.rows:
            row_text = _row_text(row)
            if "测试日期" in row_text:
                observed = _date(row_text)
    document = first_local_date(text)
    submitted = _submitted_date(text, observed or document)
    return TemporalMetadata(
        observed_local_date=observed,
        document_local_date=document,
        submitted_local_date=submitted,
        available_local_date=submitted or document,
        available_basis="submitted_time" if submitted is not None else "document_time",
    )


def _date(text: str) -> str | None:
    return first_local_date(text)


def _submitted_date(text: str, reference_date: str | None) -> str | None:
    return parse_submitted_local_date(text, reference_date)


def _report_id(text: str) -> str | None:
    match = re.search(r"报告编号[:：]\s*([^\n]+)", text)
    return normalize_text(match.group(1)) if match else None


def _parameter(text: str, pattern: str) -> str | None:
    match = re.search(pattern, compact_text(text))
    return match.group(1).replace("～", "~") if match else None


def _grade(text: str) -> str | None:
    match = re.search(r"([ⅠⅡⅢⅣⅤVI]+)\s*级围岩", text)
    return f"{match.group(1)}级" if match else None


def _match_first(candidates: tuple[str, ...], text: str) -> str | None:
    compact = compact_text(text)
    for candidate in sorted(candidates, key=len, reverse=True):
        if compact_text(candidate) in compact:
            return candidate
    return None


def _evidence_id(path: Path, kind: str, raw_scope: str) -> str:
    digest = hashlib.sha1(f"{path.name}|{kind}|{raw_scope}".encode()).hexdigest()
    return f"tblv2_{digest[:16]}"
