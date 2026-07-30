# ruff: noqa: RUF001
"""FaceSketch table parser."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
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
from tbm_twin.geology.table_parser_v2.provenance import make_table_cell_span, make_text_block_span
from tbm_twin.geology.table_parser_v2.text_utils import (
    CHAINAGE_RE,
    compact_text,
    first_local_date,
    first_match,
    normalize_text,
    parse_all_chainage_intervals,
    parse_chainage_value,
)

CHECK_MARK = "√"
GEOLOGY_ROW_LABEL = "地质描述"

LITHOLOGY_TERMS = (
    "板岩夹变质砂岩",
    "板岩夹砂岩",
    "板岩",
    "变质砂岩",
)
WEATHERING_TERMS = ("弱风化", "微风化", "强风化", "全风化", "未风化")
JOINT_TERMS = ("节理裂隙发育密集", "节理裂隙较发育", "节理裂隙发育", "节理发育")
ROCK_MASS_TERMS = ("岩体破碎-极破碎", "岩体较破碎", "岩体破碎", "岩体极破碎")
STABILITY_TERMS = ("自稳性较差", "稳定性较差", "稳定性一般", "稳定性差")
WATER_TERMS = (
    "滴渗水-线状出水",
    "线-股状出水",
    "渗滴水",
    "线状出水",
    "股状出水",
    "突涌水",
    "喷出",
    "滴渗水",
    "偶有渗水",
    "湿润",
    "无水",
)
BLOCK_FALL_TERMS = ("轻微掉块", "掉块", "坍塌", "溜坍")
RISK_TERMS = ("掉块", "坍塌", "失稳", "变形", "出水", "卡机")


@dataclass(frozen=True)
class _CheckedOption:
    label: str
    option: ExtractedCell
    mark_cell: ExtractedCell
    selected_text: str
    marker_position: str
    selection_rule: str


@dataclass(frozen=True)
class _HeaderChainage:
    value: float | None
    raw_text: str
    span_id: str | None


def parse_face_sketch(
    pdf_path: Path,
    pages: list[ExtractedPage],
    template_signature: TemplateSignature,
) -> TableParserResult:
    """Parse a FaceSketch PDF from its main pdfplumber table."""

    main_table = _find_main_table(pages)
    if main_table is None:
        document = ParsedDocument(
            source_pdf_path=pdf_path,
            source_type=SourceType.FACE_SKETCH,
            report_id=None,
            document_spatial_scope=None,
            face_chainage=None,
            temporal=TemporalMetadata(),
            template_signature=template_signature,
            parse_warnings=["UNSUPPORTED_TEMPLATE"],
        )
        return TableParserResult(document=document, primary_evidence=[])
    if _has_nonblank_continuation_page(pages, main_table.page_number):
        document = ParsedDocument(
            source_pdf_path=pdf_path,
            source_type=SourceType.FACE_SKETCH,
            report_id=None,
            document_spatial_scope=None,
            face_chainage=None,
            temporal=TemporalMetadata(),
            template_signature=template_signature,
            parse_warnings=["UNSUPPORTED_TEMPLATE", "NONBLANK_SKETCH_CONTINUATION_PAGE"],
        )
        return TableParserResult(document=document, primary_evidence=[])

    table_text = main_table.joined_text()
    row_by_label = _rows_by_label(main_table)
    description_cells = _description_value_cells(row_by_label.get(GEOLOGY_ROW_LABEL, []))
    description = " ".join(cell.text for cell in description_cells)
    scope = SpatialScope(
        kind=SpatialKind.POINT,
        start_chainage=0.0,
        end_chainage=0.0,
        raw_expression="",
        basis="header_face_chainage",
    )
    audit_rows: list[dict[str, Any]] = []
    span_by_cell: dict[tuple[int, int, int], str] = {}
    spans = []

    def use_cell(cell: ExtractedCell, role: str) -> str:
        key = (cell.page_number, cell.row_index, cell.column_index)
        if key not in span_by_cell:
            span = make_table_cell_span(cell, role)
            spans.append(span)
            span_by_cell[key] = span.span_id
        return span_by_cell[key]

    header_chainage = _header_face_chainage(pages, pdf_path, audit_rows)
    filename_chainage = parse_chainage_value(pdf_path.name)
    face_chainage = header_chainage.value or filename_chainage
    parse_warnings = []
    if header_chainage.value is None:
        parse_warnings.append("FACE_CHAINAGE_HEADER_MISSING")
    if (
        header_chainage.value is not None
        and filename_chainage is not None
        and abs(header_chainage.value - filename_chainage) > 1.0
    ):
        parse_warnings.append("SOURCE_CHAINAGE_CONFLICT")
    scope = SpatialScope(
        kind=SpatialKind.POINT,
        start_chainage=face_chainage or 0.0,
        end_chainage=face_chainage or 0.0,
        raw_expression=header_chainage.raw_text or _first_chainage_raw(pdf_path.name),
        basis="header_face_chainage" if header_chainage.value is not None else "filename_fallback",
    )
    checked = _checked_options(main_table, audit_rows)
    form_water = _water_from_form(checked)
    design_grade_cell = _grade_cell(row_by_label.get("设计围岩级别", []), 1)
    suggested_grade_cell = _grade_cell(row_by_label.get("设计围岩级别", []), -1)
    water_other_cell = _water_other_cell(row_by_label.get("涌水状态", []))
    description_span_ids = [use_cell(cell, GEOLOGY_ROW_LABEL) for cell in description_cells]
    header_span = None
    if header_chainage.raw_text:
        header_span = make_text_block_span(
            page_number=1,
            page_text=pages[0].text,
            raw_text=header_chainage.raw_text,
            source_role="face_chainage_header",
        )
        spans.append(header_span)
    classified = _classify_description(description, audit_rows, description_span_ids)
    point_text = " ".join(classified["point_texts"])
    recommendations = classified["recommendations"]
    local_unlocated = classified["local_unlocated"]
    narrative_water = _extract_water_observation(point_text)
    attributes: dict[str, Any] = {
        "observation_scope": "FACE_POINT",
        "face_chainage_source_span": header_span.span_id if header_span else None,
        "face_chainage_source_text": header_chainage.raw_text or None,
        "face_state": _first_checked(checked, "掌子面状态"),
        "excavated_face_state": _first_checked(checked, "毛开挖面状态"),
        "rock_strength": _first_checked(checked, "岩石强度"),
        "weathering": _first_checked(checked, "风化程度")
        or first_match(WEATHERING_TERMS, point_text),
        "joint_spacing": _first_checked(checked, "间距"),
        "joint_extension": _first_checked(checked, "延伸性"),
        "joint_roughness": _first_checked(checked, "粗糙度"),
        "joint_aperture": _first_checked(checked, "张开性"),
        "karst_development": _first_checked(checked, "岩溶发育程度"),
        "design_surrounding_rock_grade": _grade_from_cell(design_grade_cell),
        "suggested_surrounding_rock_grade": _grade_from_cell(suggested_grade_cell),
        "lithology": _geology_match(LITHOLOGY_TERMS, point_text),
        "joint_development": first_match(JOINT_TERMS, point_text),
        "rock_mass_state": first_match(ROCK_MASS_TERMS, point_text),
        "stability": first_match(STABILITY_TERMS, point_text),
        "block_fall_or_collapse": first_match(BLOCK_FALL_TERMS, point_text),
        "form_water_status": form_water["selected"],
        "form_water_other_raw": _water_other(water_other_cell),
        "narrative_water_observation": narrative_water,
        "water_type": narrative_water or form_water["selected"],
        "water_status_conflict": bool(
            form_water["selected"] and narrative_water and form_water["selected"] != narrative_water
        ),
        "anomaly_level": _actual_anomaly_level(point_text),
        "source_risk_text": _risk_sentences(point_text),
        "forecast_qualifiers": None,
        "local_unlocated_observations": local_unlocated,
        "recommendations": recommendations,
        "statement_role": "RECOMMENDATION" if recommendations else None,
    }
    field_spans = _field_spans(
        attributes=attributes,
        checked=checked,
        description_span_ids=description_span_ids,
        design_grade_cell=design_grade_cell,
        suggested_grade_cell=suggested_grade_cell,
        water_other_cell=water_other_cell,
        use_cell=use_cell,
    )
    if header_span is not None:
        field_spans["face_chainage"] = [header_span.span_id]
        field_spans["face_chainage_source_span"] = [header_span.span_id]
        field_spans["face_chainage_source_text"] = [header_span.span_id]
        field_spans["observation_scope"] = [header_span.span_id]
    elif description_span_ids:
        field_spans["observation_scope"] = description_span_ids
    for narrative_field in ["local_unlocated_observations", "recommendations", "statement_role"]:
        if attributes.get(narrative_field) not in (None, "", [], {}, False):
            field_spans[narrative_field] = description_span_ids
    evidence = TableParserEvidence(
        evidence_id=_evidence_id(pdf_path, "face", scope.raw_expression),
        evidence_type=PrimaryEvidenceType.FACE_OBSERVATION,
        epistemic_status=EpistemicStatus.OBSERVED,
        spatial_scope=scope,
        source_spans=spans,
        field_spans=field_spans,
        assembled_text=point_text,
        attributes=attributes,
    )
    evidence_items = [evidence]
    for index, clause in enumerate(classified["interval_clauses"], start=1):
        interval_evidence = _interval_evidence(
            pdf_path=pdf_path,
            clause=clause,
            index=index,
            description_span_ids=description_span_ids,
            description_spans=[span for span in spans if span.span_id in set(description_span_ids)],
        )
        if interval_evidence is not None:
            evidence_items.append(interval_evidence)
    temporal = TemporalMetadata(
        observed_local_date=first_local_date(table_text),
        document_local_date=first_local_date(table_text),
        available_local_date=first_local_date(table_text),
        available_basis="form_date",
    )
    document = ParsedDocument(
        source_pdf_path=pdf_path,
        source_type=SourceType.FACE_SKETCH,
        report_id=_report_id(pdf_path.name),
        document_spatial_scope=scope,
        face_chainage=face_chainage,
        temporal=temporal,
        template_signature=template_signature,
        parse_warnings=parse_warnings,
    )
    return TableParserResult(
        document=document,
        primary_evidence=evidence_items,
        audit_rows=audit_rows,
    )


def _find_main_table(pages: list[ExtractedPage]) -> ExtractedTable | None:
    for page in pages:
        for table in page.tables:
            text = compact_text(table.joined_text())
            if "掌子面状态" in text and "地质描述" in text:
                return table
    return None


def _has_nonblank_continuation_page(pages: list[ExtractedPage], main_page_number: int) -> bool:
    for page in pages:
        if page.page_number <= main_page_number:
            continue
        if compact_text(page.text) or page.tables:
            return True
    return False


def _row_text(row: list[ExtractedCell | None]) -> str:
    return normalize_text(" ".join(cell.text for cell in row if cell is not None))


def _rows_by_label(table: ExtractedTable) -> dict[str, list[ExtractedCell | None]]:
    labels: dict[str, list[ExtractedCell | None]] = {}
    active_structure = False
    for row in table.rows:
        text = compact_text(_row_text(row))
        if "地质结构面" in text:
            active_structure = True
        if text.startswith("7") or "涌水状态" in text:
            active_structure = False
        if "掌子面状态" in text:
            labels["掌子面状态"] = row
        elif "毛开挖面状态" in text:
            labels["毛开挖面状态"] = row
        elif "岩石强度" in text:
            labels["岩石强度"] = row
        elif "风化程度" in text:
            labels["风化程度"] = row
        elif "涌水状态" in text:
            labels["涌水状态"] = row
        elif "岩溶发育程度" in text:
            labels["岩溶发育程度"] = row
        elif "设计围岩级别" in text:
            labels["设计围岩级别"] = row
        elif "地质描述" in text:
            labels[GEOLOGY_ROW_LABEL] = row
        elif active_structure and "间距" in text:
            labels["间距"] = row
        elif active_structure and "延伸性" in text:
            labels["延伸性"] = row
        elif active_structure and "粗糙度" in text:
            labels["粗糙度"] = row
        elif active_structure and "张开性" in text:
            labels["张开性"] = row
    return labels


def _header_face_chainage(
    pages: list[ExtractedPage],
    pdf_path: Path,
    audit_rows: list[dict[str, Any]],
) -> _HeaderChainage:
    for page in pages:
        for line in page.text.splitlines():
            normalized = normalize_text(line)
            if "里程" not in normalized:
                continue
            match = re.search(r"里程\s*[:：]\s*(" + CHAINAGE_RE.pattern + ")", normalized, re.I)
            if match:
                value = parse_chainage_value(match.group(1))
                audit_rows.append(
                    {
                        "audit_type": "FACE_CHAINAGE",
                        "status": "HEADER_CHAINAGE_FOUND",
                        "raw_text": normalized,
                        "value": value,
                        "filename_value": parse_chainage_value(pdf_path.name),
                    }
                )
                return _HeaderChainage(value=value, raw_text=normalized, span_id=None)
    filename_value = parse_chainage_value(pdf_path.name)
    audit_rows.append(
        {
            "audit_type": "FACE_CHAINAGE",
            "status": "HEADER_CHAINAGE_MISSING_FILENAME_FALLBACK",
            "raw_text": pdf_path.name,
            "value": filename_value,
            "filename_value": filename_value,
        }
    )
    return _HeaderChainage(value=filename_value, raw_text="", span_id=None)


def _checked_options(
    table: ExtractedTable, audit_rows: list[dict[str, Any]]
) -> dict[str, list[_CheckedOption]]:
    labels = _rows_by_label(table)
    checked: dict[str, list[_CheckedOption]] = {}
    for label, row in labels.items():
        selected = _selected_options_for_row(label, row, audit_rows)
        if selected:
            checked[label] = selected
    return checked


def _selected_options_for_row(
    label: str,
    row: list[ExtractedCell | None],
    audit_rows: list[dict[str, Any]],
) -> list[_CheckedOption]:
    cells = [cell for cell in row if cell is not None and normalize_text(cell.text)]
    mark_cells = [cell for cell in cells if CHECK_MARK in cell.text]
    if not mark_cells:
        return []
    suffix_or_mid = [
        cell for cell in mark_cells if not compact_text(cell.text).startswith(CHECK_MARK)
    ]
    if suffix_or_mid:
        selected_cell = suffix_or_mid[0]
        for prefix_cell in [
            cell for cell in mark_cells if compact_text(cell.text).startswith(CHECK_MARK)
        ]:
            audit_rows.append(
                {
                    "audit_type": "CHECKBOX_POSITION",
                    "label": label,
                    "marker_position": "PREFIX",
                    "selection_rule": "ignored_prefix_mark_because_suffix_cell_present",
                    "mark_cell_text": normalize_text(prefix_cell.text),
                    "selected_cell_text": normalize_text(selected_cell.text),
                    "mark_bbox": prefix_cell.bbox,
                    "selected_bbox": selected_cell.bbox,
                    "prefix_checkmark": True,
                }
            )
    selected_mark_cells = suffix_or_mid or mark_cells
    selected: list[_CheckedOption] = []
    for mark_cell in selected_mark_cells:
        marker_position = (
            "PREFIX" if compact_text(mark_cell.text).startswith(CHECK_MARK) else "INLINE_OR_SUFFIX"
        )
        option_cell = (
            _right_neighbor_option(mark_cell, cells) if marker_position == "PREFIX" else mark_cell
        )
        selection_rule = (
            "prefix_checkmark_right_neighbor"
            if marker_position == "PREFIX" and option_cell != mark_cell
            else "same_cell_mark"
        )
        checked_option = _CheckedOption(
            label=label,
            option=option_cell,
            mark_cell=mark_cell,
            selected_text=_clean_option(option_cell.text),
            marker_position=marker_position,
            selection_rule=selection_rule,
        )
        audit_rows.append(
            {
                "audit_type": "CHECKBOX_POSITION",
                "label": label,
                "marker_position": marker_position,
                "selection_rule": selection_rule,
                "mark_cell_text": normalize_text(mark_cell.text),
                "selected_cell_text": normalize_text(option_cell.text),
                "mark_bbox": mark_cell.bbox,
                "selected_bbox": option_cell.bbox,
                "prefix_checkmark": compact_text(mark_cell.text).startswith(CHECK_MARK),
            }
        )
        selected.append(checked_option)
    return selected


def _right_neighbor_option(mark_cell: ExtractedCell, cells: list[ExtractedCell]) -> ExtractedCell:
    right = [
        cell
        for cell in cells
        if cell.row_index == mark_cell.row_index
        and cell.bbox[0] >= mark_cell.bbox[2] - 1
        and compact_text(cell.text) not in {"其它", "其它：", "其它；"}
    ]
    return min(right, key=lambda cell: cell.bbox[0], default=mark_cell)


def _clean_option(text: str) -> str:
    return compact_text(normalize_text(text).replace(CHECK_MARK, ""))


def _first_checked(checked: dict[str, list[_CheckedOption]], label: str) -> str | None:
    cells = checked.get(label, [])
    return cells[0].selected_text if cells else None


def _water_from_form(checked: dict[str, list[_CheckedOption]]) -> dict[str, str | None]:
    value = _first_checked(checked, "涌水状态")
    other = None
    for option in checked.get("涌水状态", []):
        match = re.search(r"其它\s*[:：]?\s*(\S+)", option.option.text)
        if match:
            other = match.group(1)
    return {"selected": value, "other": other}


def _water_other(cell: ExtractedCell | None) -> str | None:
    if cell is None:
        return None
    match = re.search(r"其它\s*[:：；;]?\s*([0-9][0-9A-Za-z³/·.％%]*)", normalize_text(cell.text))
    if match:
        return match.group(1)
    return None


def _water_other_cell(row: list[ExtractedCell | None]) -> ExtractedCell | None:
    for cell in row:
        if cell is not None and "其它" in cell.text:
            return cell
    return None


def _row_cells(row: list[ExtractedCell | None]) -> list[ExtractedCell]:
    return [cell for cell in row if cell is not None and normalize_text(cell.text)]


def _description_value_cells(row: list[ExtractedCell | None]) -> list[ExtractedCell]:
    cells = _row_cells(row)
    return [cell for cell in cells if compact_text(cell.text) != GEOLOGY_ROW_LABEL]


def _classify_description(
    description: str,
    audit_rows: list[dict[str, Any]],
    description_span_ids: list[str],
) -> dict[str, Any]:
    text = normalize_text(description)
    recommendations = _recommendations(text)
    analysis_text = text
    for recommendation in recommendations:
        analysis_text = analysis_text.replace(recommendation, " ")
        audit_rows.append(
            {
                "audit_type": "CLAUSE_ROLE",
                "clause_role": "RECOMMENDATION",
                "raw_text": recommendation,
                "source_span_ids": ";".join(description_span_ids),
            }
        )
    intervals = _sketch_intervals(analysis_text)
    interval_clauses: list[dict[str, Any]] = []
    consumed_ranges: list[tuple[int, int]] = []
    for index, (raw, start, end, raw_start, raw_end) in enumerate(intervals):
        next_start = intervals[index + 1][3] if index + 1 < len(intervals) else len(analysis_text)
        clause_start = _clause_start(analysis_text, raw_start)
        role = _clause_role(normalize_text(analysis_text[clause_start:next_start]))
        if role is None:
            continue
        clause_end = _clause_end(analysis_text, raw_end, next_start, role)
        clause_text = normalize_text(analysis_text[clause_start:clause_end])
        consumed_ranges.append((clause_start, clause_end))
        status = "OK"
        if start > end:
            status = "INVALID_SOURCE_INTERVAL"
            audit_rows.append(
                {
                    "audit_type": "INVALID_SOURCE_INTERVAL",
                    "clause_role": role,
                    "raw_interval": raw,
                    "start_chainage": start,
                    "end_chainage": end,
                    "raw_text": clause_text,
                    "source_span_ids": ";".join(description_span_ids),
                }
            )
        else:
            interval_clauses.append(
                {
                    "role": role,
                    "raw_interval": raw,
                    "start_chainage": start,
                    "end_chainage": end,
                    "raw_text": clause_text,
                    "source_span_ids": description_span_ids,
                }
            )
        audit_rows.append(
            {
                "audit_type": "CLAUSE_ROLE",
                "clause_role": role,
                "status": status,
                "raw_interval": raw,
                "start_chainage": start,
                "end_chainage": end,
                "raw_text": clause_text,
                "source_span_ids": ";".join(description_span_ids),
            }
        )
    point_parts = _remove_ranges(analysis_text, consumed_ranges)
    local_unlocated = _local_unlocated_observations(point_parts)
    for item in local_unlocated:
        audit_rows.append(
            {
                "audit_type": "CLAUSE_ROLE",
                "clause_role": "LOCAL_UNLOCATED",
                "raw_text": item,
                "source_span_ids": ";".join(description_span_ids),
            }
        )
    return {
        "point_texts": [part for part in point_parts if part],
        "interval_clauses": interval_clauses,
        "recommendations": recommendations,
        "local_unlocated": local_unlocated,
    }


def _sketch_intervals(text: str) -> list[tuple[str, float, float, int, int]]:
    intervals: list[tuple[str, float, float, int, int]] = []
    direct_pattern = re.compile(
        r"((?:D\s*y\s*K|D\s*K|K)?\s*\d{4}\s*\+\s*\d+(?:\.\d+)?"
        r"\s*[~～—－-]\s*(?:D\s*y\s*K|D\s*K|K)?\s*\d{4}\s*\+\s*\d+(?:\.\d+)?)",
        re.I,
    )
    for match in direct_pattern.finditer(text):
        parsed = parse_all_chainage_intervals(match.group(1))
        if not parsed:
            continue
        raw, start, end = parsed[0]
        intervals.append((raw, start, end, match.start(), match.end()))
    fallback_pattern = re.compile(
        r"((?:D\s*y\s*K|D\s*K|K)?\s*(\d{4})\s*[ⅠⅡⅢⅣⅤVI]*\s*\+\s*(\d+(?:\.\d+)?)"
        r"\s*[~～—－-]\s*(?:D\s*y\s*K|D\s*K|K)?\s*(\d{4})\s*\+\s*(\d+(?:\.\d+)?))",
        re.I,
    )
    occupied = [(start, end) for _, _, _, start, end in intervals]
    for match in fallback_pattern.finditer(text):
        if any(not (match.end() <= start or match.start() >= end) for start, end in occupied):
            continue
        raw = normalize_text(match.group(1))
        start = float(match.group(2)) * 1000.0 + float(match.group(3))
        end = float(match.group(4)) * 1000.0 + float(match.group(5))
        intervals.append((raw, start, end, match.start(), match.end()))
    return sorted(intervals, key=lambda item: item[3])


def _recommendations(text: str) -> list[str]:
    matches = []
    for match in re.finditer(r"建议[:：]?.*?(?=(?:当前开挖段落|目前处于|$))", text):
        value = normalize_text(match.group(0))
        if value:
            matches.append(value)
    return matches


def _clause_role(text: str) -> str | None:
    compact = compact_text(text)
    if any(token in compact for token in ["洞身推测岩性", "段推测", "前方预计", "推测进入"]):
        return "FORECAST_SEGMENT"
    if "当前开挖段落" in compact:
        return "CURRENT_EXCAVATED_INTERVAL"
    return None


def _clause_start(text: str, interval_start: int) -> int:
    boundary = max(text.rfind("。", 0, interval_start), text.rfind("；", 0, interval_start))
    return 0 if boundary < 0 else boundary + 1


def _clause_end(text: str, interval_end: int, next_interval_start: int, role: str) -> int:
    punctuation = []
    if role == "CURRENT_EXCAVATED_INTERVAL":
        punctuation = [
            pos + 1
            for pos in [text.find("。", interval_end), text.find("；", interval_end)]
            if pos >= 0
        ]
    role_boundaries = [
        pos
        for pos in [
            text.find("当前开挖段落", interval_end),
            text.find("建议", interval_end),
            text.find("目前处于", interval_end),
            next_interval_start,
        ]
        if pos >= 0
    ]
    candidates = punctuation + role_boundaries
    return min(candidates) if candidates else len(text)


def _remove_ranges(text: str, ranges: list[tuple[int, int]]) -> list[str]:
    if not ranges:
        return [text]
    parts = []
    cursor = 0
    for start, end in sorted(ranges):
        if start > cursor:
            parts.append(normalize_text(text[cursor:start]))
        cursor = max(cursor, end)
    if cursor < len(text):
        parts.append(normalize_text(text[cursor:]))
    return [part for part in parts if part]


def _local_unlocated_observations(parts: list[str]) -> list[str]:
    observations = []
    for sentence in re.split(r"[。；;]", " ".join(parts)):
        normalized = normalize_text(sentence)
        if "当前开挖段落" in compact_text(normalized) and not parse_all_chainage_intervals(
            normalized
        ):
            observations.append(normalized)
    return observations


def _interval_evidence(
    *,
    pdf_path: Path,
    clause: dict[str, Any],
    index: int,
    description_span_ids: list[str],
    description_spans: list[Any],
) -> TableParserEvidence | None:
    role = clause["role"]
    evidence_type = (
        PrimaryEvidenceType.FORECAST_SEGMENT
        if role == "FORECAST_SEGMENT"
        else PrimaryEvidenceType.FACE_OBSERVATION
    )
    epistemic_status = (
        EpistemicStatus.FORECAST if role == "FORECAST_SEGMENT" else EpistemicStatus.OBSERVED
    )
    scope = SpatialScope(
        kind=SpatialKind.INTERVAL,
        start_chainage=clause["start_chainage"],
        end_chainage=clause["end_chainage"],
        raw_expression=clause["raw_interval"],
        basis=role.lower(),
    )
    text = clause["raw_text"]
    attrs = _geological_attributes(text)
    attrs["observation_scope"] = role
    attrs["source_clause_role"] = role
    field_spans = {
        field: description_span_ids
        for field, value in attrs.items()
        if value not in (None, "", [], {}, False)
    }
    return TableParserEvidence(
        evidence_id=_evidence_id(pdf_path, f"{role.lower()}_{index}", scope.raw_expression),
        evidence_type=evidence_type,
        epistemic_status=epistemic_status,
        spatial_scope=scope,
        source_spans=description_spans,
        field_spans=field_spans,
        assembled_text=text,
        attributes=attrs,
    )


def _geological_attributes(text: str) -> dict[str, Any]:
    return {
        "lithology": _geology_match(LITHOLOGY_TERMS, text),
        "weathering": first_match(WEATHERING_TERMS, text),
        "joint_development": first_match(JOINT_TERMS, text),
        "rock_mass_state": first_match(ROCK_MASS_TERMS, text),
        "stability": first_match(STABILITY_TERMS, text),
        "block_fall_or_collapse": first_match(BLOCK_FALL_TERMS, text),
        "narrative_water_observation": _extract_water_observation(text),
        "water_type": _extract_water_observation(text),
        "source_risk_text": _risk_sentences(text),
        "anomaly_level": _actual_anomaly_level(text),
    }


def _geology_match(candidates: tuple[str, ...], text: str) -> str | None:
    cleaned = re.sub(r"(?<=[\u4e00-\u9fff])[ⅠⅡⅢⅣⅤVI]+(?=[\u4e00-\u9fff])", "", text)
    return first_match(candidates, cleaned)


def _field_spans(
    *,
    attributes: dict[str, Any],
    checked: dict[str, list[_CheckedOption]],
    description_span_ids: list[str],
    design_grade_cell: ExtractedCell | None,
    suggested_grade_cell: ExtractedCell | None,
    water_other_cell: ExtractedCell | None,
    use_cell: Any,
) -> dict[str, list[str]]:
    field_to_label = {
        "face_state": "掌子面状态",
        "excavated_face_state": "毛开挖面状态",
        "rock_strength": "岩石强度",
        "weathering": "风化程度",
        "joint_spacing": "间距",
        "joint_extension": "延伸性",
        "joint_roughness": "粗糙度",
        "joint_aperture": "张开性",
        "karst_development": "岩溶发育程度",
        "form_water_status": "涌水状态",
    }
    narrative_fields = {
        "lithology",
        "joint_development",
        "rock_mass_state",
        "stability",
        "block_fall_or_collapse",
        "narrative_water_observation",
        "water_type",
        "anomaly_level",
        "source_risk_text",
    }
    field_spans: dict[str, list[str]] = {}
    for field, label in field_to_label.items():
        if attributes.get(field) is not None and checked.get(label):
            field_spans[field] = [use_cell(checked[label][0].option, label)]
    if (
        attributes.get("design_surrounding_rock_grade") is not None
        and design_grade_cell is not None
    ):
        field_spans["design_surrounding_rock_grade"] = [use_cell(design_grade_cell, "design_grade")]
    if (
        attributes.get("suggested_surrounding_rock_grade") is not None
        and suggested_grade_cell is not None
    ):
        field_spans["suggested_surrounding_rock_grade"] = [
            use_cell(suggested_grade_cell, "suggested_grade")
        ]
    if attributes.get("form_water_other_raw") is not None and water_other_cell is not None:
        field_spans["form_water_other_raw"] = [use_cell(water_other_cell, "form_water_other")]
    for field in narrative_fields:
        if attributes.get(field) is not None:
            field_spans[field] = description_span_ids
    if attributes.get("water_status_conflict") is not None:
        ids = []
        if checked.get("涌水状态"):
            ids.append(use_cell(checked["涌水状态"][0].option, "涌水状态"))
        ids.extend(description_span_ids)
        field_spans["water_status_conflict"] = ids
    return field_spans


def _cell_role(cell: ExtractedCell, rows_by_label: dict[str, list[ExtractedCell | None]]) -> str:
    for label, row in rows_by_label.items():
        if cell in row:
            return label
    return "table_cell"


def _grade_cell(row: list[ExtractedCell | None], direction: int) -> ExtractedCell | None:
    candidates = [
        cell
        for cell in row
        if cell is not None and re.fullmatch(r"[ⅠⅡⅢⅣⅤVI]+", normalize_text(cell.text))
    ]
    if not candidates:
        return None
    return candidates[0] if direction > 0 else candidates[-1]


def _grade_from_cell(cell: ExtractedCell | None) -> str | None:
    if cell is None:
        return None
    return f"{normalize_text(cell.text)}级"


def _extract_water_observation(text: str) -> str | None:
    matches = []
    compact = compact_text(text)
    for term in WATER_TERMS:
        if compact_text(term) in compact:
            matches.append(term)
    if not matches:
        return None
    return "；".join(sorted(set(matches), key=lambda value: compact.find(compact_text(value))))


def _actual_anomaly_level(text: str) -> str:
    compact = compact_text(text)
    advisory_only = "如有异常及时上报" in compact and not re.search(
        r"异常[带区体]|反射异常", compact
    )
    if advisory_only:
        return "NONE"
    if re.search(r"(发现|存在|见).{0,12}异常[带区体状态]", compact):
        return "PRESENT"
    return "NONE"


def _risk_sentences(text: str) -> list[str]:
    sentences = re.split(r"[。；;]", normalize_text(text))
    return [
        sentence.strip()
        for sentence in sentences
        if any(term in sentence for term in RISK_TERMS) and "如有异常及时上报" not in sentence
    ]


def _first_chainage_raw(text: str) -> str:
    match = re.search(CHAINAGE_RE, text)
    return match.group(0) if match else ""


def _report_id(filename: str) -> str | None:
    return filename.rsplit(".", maxsplit=1)[0] or None


def _evidence_id(path: Path, kind: str, raw_scope: str) -> str:
    digest = hashlib.sha1(f"{path.name}|{kind}|{raw_scope}".encode()).hexdigest()
    return f"tblv2_{digest[:16]}"
