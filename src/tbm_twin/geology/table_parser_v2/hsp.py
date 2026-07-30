# ruff: noqa: RUF001
"""HSP forecast table parser."""

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
from tbm_twin.geology.table_parser_v2.text_utils import (
    PLUS_RE,
    compact_text,
    complete_plus_chainage,
    first_local_date,
    normalize_text,
    parse_chainage_interval,
    parse_chainage_value,
    parse_submitted_local_date,
    raw_chainage_interval,
)


def parse_hsp(
    pdf_path: Path,
    pages: list[ExtractedPage],
    template_signature: TemplateSignature,
) -> TableParserResult:
    """Parse HSP face observation and forecast rows."""

    forecast_tables = _forecast_tables(pages)
    document_text = "\n".join(page.text for page in pages)
    document_scope = _document_scope(pdf_path, document_text)
    face_chainage = _face_chainage(forecast_tables, document_text)
    temporal = _temporal(document_text, forecast_tables)
    evidence: list[TableParserEvidence] = []
    face = _face_observation(pdf_path, forecast_tables, face_chainage)
    if face is not None:
        evidence.append(face)
    for index, row in enumerate(_forecast_rows(forecast_tables), start=1):
        parsed = _row_to_evidence(pdf_path, row, index)
        if parsed is not None:
            evidence.append(parsed)
    document = ParsedDocument(
        source_pdf_path=pdf_path,
        source_type=SourceType.SONIC_FORECAST,
        report_id=_report_id(document_text),
        document_spatial_scope=document_scope,
        face_chainage=face_chainage,
        temporal=temporal,
        template_signature=template_signature,
    )
    return TableParserResult(document=document, primary_evidence=evidence)


def _forecast_tables(pages: list[ExtractedPage]) -> list[ExtractedTable]:
    selected: list[ExtractedTable] = []
    active = False
    for page in pages:
        for table in page.tables:
            text = compact_text(table.joined_text())
            is_header = "里程范围" in text and "本次预报结论" in text
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


def _row_text(row: list[ExtractedCell | None]) -> str:
    return normalize_text(" ".join(cell.text for cell in row if cell is not None))


def _row_interval(row: list[ExtractedCell | None]) -> tuple[float, float] | None:
    first = next((cell.text for cell in row if cell is not None and normalize_text(cell.text)), "")
    return parse_chainage_interval(first)


def _forecast_rows(tables: list[ExtractedTable]) -> list[list[ExtractedCell | None]]:
    rows: list[list[ExtractedCell | None]] = []
    for table in tables:
        for row in table.rows:
            if _row_interval(row) is not None:
                rows.append(row)
    return rows


def _row_to_evidence(
    pdf_path: Path,
    row: list[ExtractedCell | None],
    index: int,
) -> TableParserEvidence | None:
    interval = _row_interval(row)
    if interval is None:
        return None
    start, end = interval
    cells = _non_empty_cells(row)
    row_text = _row_text(row)
    scope = SpatialScope(
        kind=SpatialKind.INTERVAL,
        start_chainage=start,
        end_chainage=end,
        raw_expression=raw_chainage_interval(row_text),
        basis="hsp_forecast_table_row",
    )
    spans = [make_table_cell_span(cell, _hsp_role(cell, row)) for cell in cells]
    attributes = _hsp_attributes(row, start, end)
    return TableParserEvidence(
        evidence_id=_evidence_id(pdf_path, f"hsp_row_{index}", scope.raw_expression),
        evidence_type=PrimaryEvidenceType.FORECAST_SEGMENT,
        epistemic_status=EpistemicStatus.FORECAST,
        spatial_scope=scope,
        source_spans=spans,
        field_spans=_field_spans(spans),
        assembled_text=row_text,
        attributes=attributes,
    )


def _hsp_attributes(
    row: list[ExtractedCell | None],
    start: float,
    end: float,
) -> dict[str, Any]:
    cells = _cell_texts(row)
    if len(cells) >= 7:
        anomaly = cells[1]
        conclusion = cells[2]
        risk = _meaningful_risk(cells[3])
        grade = cells[5]
    else:
        anomaly = cells[1] if len(cells) > 1 else ""
        conclusion = cells[2] if len(cells) > 2 else ""
        risk = _meaningful_risk(cells[3] if len(cells) > 3 else "")
        grade = cells[4] if len(cells) > 4 else ""
    risk_points = [
        complete_plus_chainage(match.group(0), start, end)
        for match in PLUS_RE.finditer(risk or "")
        if complete_plus_chainage(match.group(0), start, end) is not None
    ]
    return {
        "anomaly_raw_text": _clean_prefix(anomaly),
        "anomaly_level": _anomaly_level(anomaly),
        "geological_conclusion": conclusion,
        "risk_hint": risk,
        "risk_points": risk_points,
        "suggested_grade": _grade(grade),
        "lithology": _match_first(("板岩夹变质砂岩", "板岩夹砂岩", "板岩", "变质砂岩"), conclusion),
        "weathering": _match_first(("弱风化", "微风化", "强风化", "全风化"), conclusion),
        "joint_development": _match_first(
            ("节理裂隙发育密集", "节理裂隙较发育-发育", "节理裂隙较发育", "节理裂隙发育"),
            conclusion,
        ),
        "rock_mass_state": _match_first(
            ("岩体破碎-极破碎", "岩体较破碎-破碎", "岩体较破碎", "岩体破碎"), conclusion
        ),
    }


def _cell_texts(row: list[ExtractedCell | None]) -> list[str]:
    return [normalize_text(cell.text) if cell is not None else "" for cell in row]


def _non_empty_cells(row: list[ExtractedCell | None]) -> list[ExtractedCell]:
    return [cell for cell in row if cell is not None and normalize_text(cell.text)]


def _hsp_role(cell: ExtractedCell, row: list[ExtractedCell | None]) -> str:
    texts = _cell_texts(row)
    columns = len(texts)
    if cell.column_index == 0:
        return "range"
    if cell.column_index == 1:
        return "geophysical_result"
    if cell.column_index == 2:
        return "geological_conclusion"
    if cell.column_index == 3:
        return "risk_hint"
    if columns >= 7 and cell.column_index == 5:
        return "suggested_grade"
    if columns < 7 and cell.column_index == 4:
        return "suggested_grade"
    return "forecast_table_cell"


def _field_spans(spans: list[Any]) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for span in spans:
        fields.setdefault(span.source_role, []).append(span.span_id)
    return fields


def _face_observation(
    pdf_path: Path,
    tables: list[ExtractedTable],
    face_chainage: float | None,
) -> TableParserEvidence | None:
    for table in tables:
        for row in table.rows:
            if "开挖面" in compact_text(_row_text(row)) and "地质概况" in compact_text(
                _row_text(row)
            ):
                cells = _non_empty_cells(row)
                text = _row_text(row)
                spans = [make_table_cell_span(cell, "face_geology") for cell in cells]
                scope = SpatialScope(
                    kind=SpatialKind.POINT,
                    start_chainage=face_chainage or 0.0,
                    end_chainage=face_chainage or 0.0,
                    raw_expression=str(face_chainage or ""),
                    basis="hsp_face_chainage_cell",
                )
                return TableParserEvidence(
                    evidence_id=_evidence_id(pdf_path, "hsp_face", text),
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
                        "rock_mass_state": _match_first(
                            ("岩体破碎-极破碎", "岩体较破碎", "岩体破碎"), text
                        ),
                    },
                )
    return None


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
            if "开挖面" in compact_text(text) and "程" in compact_text(text):
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


def _meaningful_risk(text: str) -> str | None:
    cleaned = normalize_text(text)
    return cleaned if re.search(r"[\u4e00-\u9fffA-Za-z0-9]", cleaned) else None


def _clean_prefix(text: str) -> str:
    return compact_text(text)


def _anomaly_level(text: str) -> str:
    compact = compact_text(text)
    if "未见明显反射异常" in compact or "无明显反射异常" in compact:
        return "NONE"
    if "较明显反射异常" in compact:
        return "MODERATE"
    if "明显反射异常" in compact:
        return "HIGH"
    if "弱反射异常" in compact:
        return "LOW"
    return "UNKNOWN"


def _grade(text: str) -> str | None:
    match = re.search(r"([ⅠⅡⅢⅣⅤVI]+)\s*级", text)
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
