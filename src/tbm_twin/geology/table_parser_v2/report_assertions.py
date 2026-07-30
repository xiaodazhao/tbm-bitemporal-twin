# ruff: noqa: RUF001
"""Generic TSP report assertion parsing and conflict checks."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from tbm_twin.geology.table_parser_v2.models import (
    ReportAssertion,
    SourceSpan,
    SpatialKind,
    SpatialScope,
    TableParserEvidence,
)
from tbm_twin.geology.table_parser_v2.provenance import make_text_block_span
from tbm_twin.geology.table_parser_v2.text_utils import (
    compact_text,
    normalize_text,
    parse_all_chainage_intervals,
)


def parse_tsp_report_assertions(
    pdf_path: Path,
    page_texts: list[str],
    table_evidence: list[TableParserEvidence],
) -> list[ReportAssertion]:
    """Parse report-level assertions from chapter 7 page blocks."""

    assertions: list[ReportAssertion] = []
    for page_number, block in _chapter_7_blocks(page_texts):
        page_text = page_texts[page_number - 1]
        assertions.extend(
            _grade_assertions(pdf_path, page_number, page_text, block, table_evidence)
        )
        assertions.extend(
            _block_fall_assertions(pdf_path, page_number, page_text, block, table_evidence)
        )
        assertions.extend(
            _water_assertions(pdf_path, page_number, page_text, block, table_evidence)
        )
        assertions.extend(_risk_assertions(pdf_path, page_number, page_text, block, table_evidence))
    return _deduplicate_assertions(assertions)


def _chapter_7_blocks(page_texts: list[str]) -> list[tuple[int, str]]:
    blocks: list[tuple[int, str]] = []
    collecting = False
    for index, page_text in enumerate(page_texts, start=1):
        raw = normalize_text(page_text)
        compact = compact_text(page_text)
        if not collecting:
            if "7结论" not in compact or "得出以下结论" not in compact:
                continue
            marker_index = raw.find("7 结论")
            raw = raw[marker_index if marker_index >= 0 else 0 :]
            collecting = True
        raw = _truncate_chapter_boundary(raw)
        if raw:
            blocks.append((index, raw))
        if _chapter_boundary_reached(page_text):
            break
    return blocks


def _chapter_7_text(page_texts: list[str]) -> tuple[int | None, str | None]:
    blocks = _chapter_7_blocks(page_texts)
    if not blocks:
        return None, None
    return blocks[0][0], " ".join(block for _, block in blocks)


def _truncate_chapter_boundary(text: str) -> str:
    boundary = re.search(
        r"本次.*?超前预报结果详见表\s*2|表\s*2\s+隧道超前地质预报报表|附图及附表",
        text,
    )
    return text[: boundary.start()] if boundary else text


def _chapter_boundary_reached(text: str) -> bool:
    return bool(
        re.search(
            r"本次.*?超前预报结果详见表\s*2|表\s*2\s+隧道超前地质预报报表|附图及附表",
            text,
        )
    )


def _grade_assertions(
    pdf_path: Path,
    page_number: int,
    page_text: str,
    text: str,
    table_evidence: list[TableParserEvidence],
) -> list[ReportAssertion]:
    assertions = []
    for sentence in _sentences(text):
        if "建议按" not in sentence or "围岩施工" not in sentence:
            continue
        intervals = parse_all_chainage_intervals(sentence)
        for index, (raw, start, end) in enumerate(intervals):
            current_start = sentence.find(raw)
            next_start = (
                sentence.find(intervals[index + 1][0])
                if index + 1 < len(intervals)
                else len(sentence)
            )
            local_text = sentence[current_start:next_start]
            match = re.search(r"建议按\s*([ⅠⅡⅢⅣⅤVI]+)\s*级围岩施工", local_text)
            if match is None:
                continue
            assertions.append(
                _assertion(
                    pdf_path,
                    "GRADE_SUMMARY",
                    raw,
                    start,
                    end,
                    local_text,
                    _assertion_spans(page_number, page_text, local_text),
                    {"suggested_grade": f"{match.group(1)}级"},
                    table_evidence,
                )
            )
    return assertions


def _block_fall_assertions(
    pdf_path: Path,
    page_number: int,
    page_text: str,
    text: str,
    table_evidence: list[TableParserEvidence],
) -> list[ReportAssertion]:
    assertions = []
    for paragraph in _numbered_paragraphs(text):
        if not any(term in paragraph for term in ["掉块", "溜坍", "坍塌"]):
            continue
        for raw, start, end in parse_all_chainage_intervals(paragraph):
            assertions.append(
                _assertion(
                    pdf_path,
                    "BLOCK_FALL_SUMMARY",
                    raw,
                    start,
                    end,
                    paragraph,
                    _assertion_spans(page_number, page_text, paragraph),
                    {"block_fall_or_collapse": "掉块风险"},
                    table_evidence,
                )
            )
    return assertions


def _water_assertions(
    pdf_path: Path,
    page_number: int,
    page_text: str,
    text: str,
    table_evidence: list[TableParserEvidence],
) -> list[ReportAssertion]:
    assertions = []
    for sentence in _sentences(text):
        if "出水" not in sentence and "渗水" not in sentence:
            continue
        intervals = parse_all_chainage_intervals(sentence)
        for index, (raw, start, end) in enumerate(intervals):
            next_start = (
                sentence.find(intervals[index + 1][0])
                if index + 1 < len(intervals)
                else len(sentence)
            )
            local_text = sentence[sentence.find(raw) : next_start]
            water = _water_type(local_text) or _water_type(sentence)
            if water is None:
                continue
            assertions.append(
                _assertion(
                    pdf_path,
                    "WATER_SUMMARY",
                    raw,
                    start,
                    end,
                    sentence,
                    _assertion_spans(page_number, page_text, sentence),
                    {"water_type": water},
                    table_evidence,
                )
            )
    return assertions


def _risk_assertions(
    pdf_path: Path,
    page_number: int,
    page_text: str,
    text: str,
    table_evidence: list[TableParserEvidence],
) -> list[ReportAssertion]:
    assertions = []
    for sentence in _sentences(text):
        categories = [
            term for term in ("掉块", "坍塌", "出水", "卡机", "突涌水") if term in sentence
        ]
        if not categories or not any(term in categories for term in ["坍塌", "卡机", "突涌水"]):
            continue
        for raw, start, end in parse_all_chainage_intervals(sentence):
            assertions.append(
                _assertion(
                    pdf_path,
                    "RISK_SUMMARY",
                    raw,
                    start,
                    end,
                    sentence,
                    _assertion_spans(page_number, page_text, sentence),
                    {
                        "risk_categories": categories,
                        "source_risk_text": normalize_text(sentence),
                    },
                    table_evidence,
                )
            )
    return assertions


def _assertion_spans(page_number: int, page_text: str, raw_text: str) -> list[SourceSpan]:
    try:
        return [
            make_text_block_span(
                page_number=page_number,
                page_text=page_text,
                raw_text=raw_text,
                source_role="chapter_7_assertion",
            )
        ]
    except Exception:
        return [
            make_text_block_span(
                page_number=page_number,
                page_text=compact_text(page_text),
                raw_text=compact_text(raw_text),
                source_role="chapter_7_assertion",
            )
        ]


def _assertion(
    pdf_path: Path,
    assertion_type: str,
    raw_scope: str,
    start: float,
    end: float,
    raw_text: str,
    spans: list[SourceSpan],
    attributes: dict[str, Any],
    table_evidence: list[TableParserEvidence],
) -> ReportAssertion:
    scope = SpatialScope(
        kind=SpatialKind.INTERVAL,
        start_chainage=start,
        end_chainage=end,
        raw_expression=raw_scope,
        basis="tsp_chapter_7_assertion",
    )
    derived = [item.evidence_id for item in table_evidence if _overlaps(item.spatial_scope, scope)]
    status, details = _consistency(attributes, derived, table_evidence)
    return ReportAssertion(
        assertion_id=_assertion_id(pdf_path, assertion_type, raw_scope, raw_text),
        assertion_type=assertion_type,
        spatial_scope=scope,
        raw_text=normalize_text(raw_text),
        source_spans=spans,
        attributes=attributes,
        derived_from_evidence_ids=derived,
        consistency_status=status,
        conflict_details=details,
    )


def _consistency(
    attributes: dict[str, Any],
    evidence_ids: list[str],
    table_evidence: list[TableParserEvidence],
) -> tuple[str, list[str]]:
    evidence_by_id = {item.evidence_id: item for item in table_evidence}
    details: list[str] = []
    for evidence_id in evidence_ids:
        evidence = evidence_by_id[evidence_id]
        for key, value in attributes.items():
            table_value = evidence.attributes.get(key)
            if table_value is not None and value is not None and table_value != value:
                details.append(f"table {key}={table_value}; summary {key}={value}")
    if details:
        return "CONFLICT", details
    if evidence_ids:
        return "CONSISTENT", details
    return "NO_TABLE_COVERAGE", details


def _overlaps(source: SpatialScope, target: SpatialScope) -> bool:
    return (
        source.start_chainage <= target.end_chainage - 0.2
        and source.end_chainage >= target.start_chainage + 0.2
    )


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[。；;]", normalize_text(text)) if part.strip()]


def _numbered_paragraphs(text: str) -> list[str]:
    parts = re.split(r"(?=（\d+）)", normalize_text(text))
    return [part.strip() for part in parts if part.strip()]


def _water_type(text: str) -> str | None:
    terms = (
        "滴渗水-线状出水",
        "线-股状出水",
        "线状出水",
        "股状出水",
        "突涌水",
        "滴渗水",
        "偶有渗水",
    )
    compact = compact_text(text)
    for term in terms:
        if compact_text(term) in compact:
            return term
    return None


def _deduplicate_assertions(assertions: list[ReportAssertion]) -> list[ReportAssertion]:
    seen: set[tuple[str, float, float, str]] = set()
    unique: list[ReportAssertion] = []
    for assertion in assertions:
        key = (
            assertion.assertion_type,
            assertion.spatial_scope.start_chainage,
            assertion.spatial_scope.end_chainage,
            normalize_text(str(assertion.attributes)),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(assertion)
    return unique


def _assertion_id(pdf_path: Path, assertion_type: str, raw_scope: str, raw_text: str) -> str:
    digest = hashlib.sha1(
        f"{pdf_path.name}|{assertion_type}|{raw_scope}|{raw_text}".encode()
    ).hexdigest()
    return f"assert_{digest[:16]}"
