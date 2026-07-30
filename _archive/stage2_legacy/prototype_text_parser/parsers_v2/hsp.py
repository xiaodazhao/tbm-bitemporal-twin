"""HSP Parser V2."""

# ruff: noqa: RUF001

from __future__ import annotations

import re
from pathlib import Path

from tbm_twin.evidence.models import GeologicalSourceType
from tbm_twin.geology.parsers_v2.models import (
    PrimaryEvidenceType,
    SpatialKind,
    V2Document,
    V2EpistemicStatus,
    V2Evidence,
    V2ParseResult,
    V2SpatialScope,
    V2TemporalSummary,
)
from tbm_twin.geology.parsers_v2.provenance import make_span, stable_id
from tbm_twin.geology.parsers_v2.table_utils import (
    arabic_date,
    chinese_date,
    compact,
    find_page,
    parse_first_chainage,
    parse_range,
)
from tbm_twin.geology.raw_documents import register_pdf_source_asset_with_pages


def parse_hsp_pdf_v2(path: Path) -> V2ParseResult:
    """Parse one HSP PDF with table-row primary evidence."""

    asset, pages = register_pdf_source_asset_with_pages(path)
    text = "\n".join(page.page_text for page in pages)
    document_id = stable_id("v2-doc", asset.asset_id)
    scope_raw = _after_label_range(text, "预报范围")
    start, end, raw_scope = parse_range(scope_raw or path.name)
    face = _hsp_face_chainage(text) or start
    observed = arabic_date(_after_label_text(text, "测试日期") or "")
    documented = chinese_date(pages[0].page_text)
    submitted = _submitted_date(text, documented.year if documented else None)
    temporal = V2TemporalSummary(
        observed_local_date=observed.isoformat() if observed else None,
        documented_local_date=documented.isoformat() if documented else None,
        submitted_local_date=submitted,
        available_local_date=submitted,
        available_basis="SUBMITTED_TIME_PRIORITY",
    )
    page = find_page(pages, "表1  隧道超前地质预报报表")
    face_text = _between(page.page_text, "开挖面 \n地质概况", "里程范围")
    face_span = make_span(
        document_id=document_id,
        page=page,
        raw_text=face_text,
        source_role="hsp_face_observation",
    )
    document_scope = V2SpatialScope(
        kind=SpatialKind.INTERVAL,
        start_chainage=start,
        end_chainage=end,
        raw_expression=raw_scope,
        basis="document_forecast_scope",
    )
    face_evidence = V2Evidence(
        evidence_id=stable_id("v2-evidence", document_id, "hsp-face", face),
        document_id=document_id,
        evidence_type=PrimaryEvidenceType.FACE_OBSERVATION,
        epistemic_status=V2EpistemicStatus.OBSERVED,
        spatial_scope=V2SpatialScope(
            kind=SpatialKind.POINT,
            start_chainage=face or start,
            end_chainage=face or start,
            raw_expression=f"DyK{(face or start) / 1000:.4f}",
            basis="explicit_hsp_face_chainage",
        ),
        source_spans=[face_span],
        field_spans={"face_observation": [face_span.span_id], "face_chainage": [face_span.span_id]},
        assembled_text=face_text,
        attributes={"face_geology": compact(face_text)},
    )
    rows = _hsp_rows(page.page_text)
    evidence = [face_evidence]
    for index, row in enumerate(rows, start=1):
        row_start, row_end, row_raw = parse_range(row)
        span = make_span(
            document_id=document_id,
            page=page,
            raw_text=row,
            source_role="hsp_forecast_table_row",
            occurrence=index,
        )
        anomaly = _first_present(row, ["未见明显反射异常", "较明显反射异常", "明显反射异常"])
        risk = _risk_hint(row)
        grade = _grade(row)
        conclusion = _hsp_conclusion(row, anomaly, risk, grade)
        evidence.append(
            V2Evidence(
                evidence_id=stable_id("v2-evidence", document_id, "hsp", row_start, row_end),
                document_id=document_id,
                evidence_type=PrimaryEvidenceType.FORECAST_SEGMENT,
                epistemic_status=V2EpistemicStatus.FORECAST,
                spatial_scope=V2SpatialScope(
                    kind=SpatialKind.INTERVAL,
                    start_chainage=row_start,
                    end_chainage=row_end,
                    raw_expression=row_raw,
                    basis="hsp_table_row_range",
                ),
                source_spans=[span],
                field_spans={
                    "range": [span.span_id],
                    "anomaly_raw_text": [span.span_id],
                    "geological_conclusion": [span.span_id],
                    "risk_hint": [span.span_id],
                    "suggested_grade": [span.span_id],
                },
                assembled_text=row,
                attributes={
                    "anomaly_raw_text": anomaly,
                    "geological_conclusion": conclusion,
                    "risk_hint": risk,
                    "suggested_grade": grade,
                },
            )
        )
    document = V2Document(
        document_id=document_id,
        source_pdf_path=path,
        source_type=GeologicalSourceType.SONIC_FORECAST.value,
        report_id=path.stem,
        document_spatial_scope=document_scope,
        face_chainage=face,
        temporal=temporal,
        source_spans=[face_span, *[span for item in evidence[1:] for span in item.source_spans]],
        template_variant_id="HSP_TABLE_V1",
    )
    return V2ParseResult(document=document, primary_evidence=evidence, report_assertions=[])


def _after_label_text(text: str, label: str) -> str | None:
    index = text.find(label)
    return text[index : index + 300] if index >= 0 else None


def _after_label_range(text: str, label: str) -> str | None:
    value = _after_label_text(text, label)
    return value


def _hsp_face_chainage(text: str) -> float | None:
    flat = compact(text)
    match = re.search(r"开挖面里程((?:DyK|DK|K)\d+\+\d+(?:\.\d+)?)", flat)
    return parse_first_chainage(match.group(1)) if match else None


def _submitted_date(text: str, year: int | None) -> str | None:
    match = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日提交", text)
    if match and year:
        return f"{year:04d}-{int(match.group(1)):02d}-{int(match.group(2)):02d}"
    return None


def _between(text: str, start_token: str, end_token: str) -> str:
    start = text.find(start_token)
    if start < 0:
        return ""
    end = text.find(end_token, start)
    return text[start:end].strip() if end > start else text[start:].strip()


def _hsp_rows(text: str) -> list[str]:
    table = _between(text, "里程范围", "下一次")
    matches = list(re.finditer(r"DyK\d+\+\d+(?:\.\d+)?\s*~\s*DyK\d+\+\d+(?:\.\d+)?", table))
    rows: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(table)
        rows.append(table[match.start() : end].strip())
    return rows


def _first_present(text: str, candidates: list[str]) -> str | None:
    flat = compact(text)
    for candidate in candidates:
        if candidate in flat:
            return candidate
    return None


def _risk_hint(text: str) -> str | None:
    flat = compact(text)
    match = re.search(r"里程\+\d+(?:、\+\d+)*(?:、\+\d+)?附近有掉块风险", flat)
    if not match:
        return None
    return match.group(0).replace("里程+", "里程1013+")


def _grade(text: str) -> str | None:
    match = re.search(r"([ⅠⅡⅢⅣⅤIVX]+)级围岩", compact(text))
    return f"{match.group(1)}级" if match else None


def _hsp_conclusion(text: str, anomaly: str | None, risk: str | None, grade: str | None) -> str:
    flat = compact(text)
    if anomaly:
        flat = flat.split(anomaly, 1)[-1]
    if risk and "里程+" in flat:
        flat = flat.split("里程+", 1)[0]
    if grade:
        flat = flat.split(grade, 1)[0]
    return flat.strip()
