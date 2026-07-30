"""FaceSketch Parser V2."""

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
    all_text,
    arabic_date,
    compact,
    parse_first_chainage,
)
from tbm_twin.geology.raw_documents import register_pdf_source_asset_with_pages


def parse_face_sketch_pdf(path: Path) -> V2ParseResult:
    """Parse one FaceSketch PDF into exactly one face observation."""

    asset, pages = register_pdf_source_asset_with_pages(path)
    text = all_text(pages)
    document_id = stable_id("v2-doc", asset.asset_id)
    face_chainage = parse_first_chainage(text)
    if face_chainage is None:
        msg = f"FaceSketch has no face chainage: {path}"
        raise ValueError(msg)
    date_value = arabic_date(text)
    local_date = date_value.isoformat() if date_value else None
    document = V2Document(
        document_id=document_id,
        source_pdf_path=path,
        source_type=GeologicalSourceType.FACE_SKETCH.value,
        report_id=path.stem,
        document_spatial_scope=V2SpatialScope(
            kind=SpatialKind.POINT,
            start_chainage=face_chainage,
            end_chainage=face_chainage,
            raw_expression=f"DyK{face_chainage / 1000:.4f}",
            basis="explicit_face_sketch_header_chainage",
        ),
        face_chainage=face_chainage,
        temporal=V2TemporalSummary(
            observed_local_date=local_date,
            documented_local_date=local_date,
            available_local_date=local_date,
            available_basis="FACE_SKETCH_SIGNED_DATE",
        ),
        source_spans=[],
        template_variant_id="FACE_SKETCH_FORM_V1",
    )
    page = pages[0]
    form_text = _form_text(page.page_text)
    narrative = _narrative_text(page.page_text)
    joints_text = _joint_attitude_text(narrative)
    form_span = make_span(
        document_id=document_id,
        page=page,
        raw_text=form_text,
        source_role="face_form",
    )
    narrative_span = make_span(
        document_id=document_id,
        page=page,
        raw_text=narrative,
        source_role="face_narrative",
        occurrence=1,
    )
    joint_span = make_span(
        document_id=document_id,
        page=page,
        raw_text=joints_text,
        source_role="joint_attitudes",
        occurrence=2,
    )
    source_spans = [form_span, narrative_span, joint_span]
    evidence = V2Evidence(
        evidence_id=stable_id("v2-evidence", document_id, "face", face_chainage),
        document_id=document_id,
        evidence_type=PrimaryEvidenceType.FACE_OBSERVATION,
        epistemic_status=V2EpistemicStatus.OBSERVED,
        spatial_scope=V2SpatialScope(
            kind=SpatialKind.POINT,
            start_chainage=face_chainage,
            end_chainage=face_chainage,
            raw_expression=_first_chainage_text(text),
            basis="explicit_face_sketch_header_chainage",
        ),
        source_spans=source_spans,
        field_spans={
            "face_chainage": [form_span.span_id],
            "form_attributes": [form_span.span_id],
            "narrative_attributes": [narrative_span.span_id],
            "joint_attitudes_raw_text": [joint_span.span_id],
        },
        assembled_text=f"{form_text}\n{narrative}",
        attributes={
            **_checkbox_attributes(page.page_text),
            **_narrative_attributes(narrative),
            "joint_attitudes_raw_text": joints_text,
        },
    )
    document = document.model_copy(update={"source_spans": source_spans})
    return V2ParseResult(document=document, primary_evidence=[evidence], report_assertions=[])


def _first_chainage_text(text: str) -> str:
    match = re.search(r"(?:DyK|DK|K)\s*\d+\s*\+\s*\d+(?:\.\d+)?", text, re.IGNORECASE)
    return match.group(0) if match else ""


def _form_text(text: str) -> str:
    marker = "地\n质\n描\n述"
    return text[: text.find(marker)] if marker in text else text[:1200]


def _narrative_text(text: str) -> str:
    start = text.find("地\n质\n描\n述")
    if start < 0:
        return ""
    end = text.find("示\n意\n图", start)
    return text[start:end].strip() if end > start else text[start:].strip()


def _joint_attitude_text(text: str) -> str:
    start = text.find("板理产状")
    end = text.find("综上所述", start)
    return text[start:end].strip() if start >= 0 and end > start else ""


def _checkbox_attributes(text: str) -> dict[str, str | None]:
    flat = compact(text)
    return {
        "face_state": _checked(flat, ["稳定", "正面掉块", "正面挤出", "正面不能自稳"]),
        "excavated_face_state": _checked(
            flat, ["自稳", "随时间松弛、掉块", "自稳困难、要及时支护", "要超前支护"]
        ),
        "rock_strength_interval": _checked(
            flat, ["R＞60", "30＜R≤60", "15＜R≤30", "5＜R≤15", "R＜5"]
        ),
        "weathering": _checked(flat, ["未风化", "微风化", "弱风化", "强风化", "全风化"]),
        "structure_spacing": _checked(
            flat, ["＞1.5", "0.6~1.5", "0.2~0.6", "0.06~0.2", "＜0.06", "不易测取"]
        ),
        "extension": _checked(flat, ["极差", "差", "中等", "好", "极好"]),
        "roughness": _checked(
            flat, ["明显台阶状", "粗糙波纹状", "平整光滑有擦痕", "平整光滑", "不易测取"]
        ),
        "openness": _checked(
            flat, ["密闭＜0.1", "部分张开0.1~0.5", "张开0.5~1.0", "无充填张开＞1.0", "黏土充填"]
        ),
        "form_water_selected_option": _checked(flat, ["无水", "湿润", "偶有渗水", "涌出或喷出"]),
        "form_water_other_raw": "500" if "其它500" in flat else None,
        "karst_development": _checked(flat, ["无", "弱", "中等", "强烈"]),
        "design_grade": _grade_after(flat, "设计围岩级别"),
        "suggested_grade": _grade_after(flat, "建议围岩级别"),
    }


def _checked(flat: str, options: list[str]) -> str | None:
    for option in options:
        token = option.replace("\uff5e", "~")
        if f"{token}√" in flat:
            return option.replace("＞", ">").replace("＜", "<").replace("~", "-")
    return None


def _grade_after(flat: str, label: str) -> str | None:
    match = re.search(rf"{label}([ⅠⅡⅢⅣⅤIVX]+)", flat)
    return match.group(1) if match else None


def _narrative_attributes(text: str) -> dict[str, str | bool | None]:
    flat = compact(text)
    return {
        "lithology": "板岩夹变质砂岩" if "板岩夹变质砂岩" in flat else None,
        "narrative_weathering": "弱风化" if "弱风化" in flat else None,
        "joint_development": "节理裂隙发育" if "节理裂隙发育" in flat else None,
        "rock_mass_state": "岩体破碎" if "岩体破碎" in flat else None,
        "block_fall": "轻微掉块" if "轻微掉块" in flat else None,
        "narrative_water": "渗滴水；线状出水" if "渗滴水" in flat and "线状出水" in flat else None,
        "stability": "自稳性较差" if "自稳性较差" in flat else None,
        "observed_grade": _grade_after(flat, "判定洞身围岩为"),
        "creates_local_interval_evidence": False,
    }
