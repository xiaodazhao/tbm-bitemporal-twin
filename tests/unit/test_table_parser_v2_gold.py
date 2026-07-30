# ruff: noqa: RUF001
from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pdfplumber

from tbm_twin.geology.table_parser_v2 import parse_pdf_v2
from tbm_twin.geology.table_parser_v2.models import PrimaryEvidenceType
from tbm_twin.geology.table_parser_v2.text_utils import compact_text

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "geology_pdfs"
MANUAL_GOLD = Path(__file__).resolve().parents[1] / "manual_gold" / "geology"
FIXED_SKETCH_FIXTURES = {
    "1014+675": FIXTURES / "sketch_dyk1014_675.pdf",
    "1015+655": FIXTURES / "sketch_dyk1015_655.pdf",
    "1017+049": FIXTURES / "sketch_dyk1017_049.pdf",
}


def _load_gold(name: str) -> dict[str, Any]:
    return json.loads((MANUAL_GOLD / name).read_text(encoding="utf-8"))


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _forecast_segments(result: Any) -> list[Any]:
    return [
        item
        for item in result.primary_evidence
        if item.evidence_type == PrimaryEvidenceType.FORECAST_SEGMENT
    ]


def _face_points(result: Any) -> list[Any]:
    return [
        item
        for item in result.primary_evidence
        if item.evidence_type == PrimaryEvidenceType.FACE_OBSERVATION
        and item.spatial_scope.kind == "POINT"
    ]


def _observed_intervals(result: Any) -> list[Any]:
    return [
        item
        for item in result.primary_evidence
        if item.evidence_type == PrimaryEvidenceType.FACE_OBSERVATION
        and item.spatial_scope.kind == "INTERVAL"
    ]


def _real_sketch_pdf(token: str) -> Path:
    path = FIXED_SKETCH_FIXTURES.get(token)
    if path is not None and path.exists():
        return path
    raise AssertionError(f"Missing real FaceSketch PDF for {token}")


def _ranges(result: Any) -> list[list[float]]:
    return [
        [item.spatial_scope.start_chainage, item.spatial_scope.end_chainage]
        for item in _forecast_segments(result)
    ]


def _assert_document_metadata(result: Any, gold: dict[str, Any]) -> None:
    metadata = gold["document_metadata"]
    assert result.document.face_chainage == metadata["face_chainage"]
    assert result.document.temporal.observed_local_date == metadata["observed_local_date"]
    assert result.document.temporal.document_local_date == metadata["document_local_date"]
    assert result.document.temporal.submitted_local_date == metadata["submitted_local_date"]
    assert result.document.temporal.available_local_date == metadata["available_local_date"]
    assert result.document.temporal.available_basis == metadata["available_basis"]
    scope = result.document.document_spatial_scope
    assert scope is not None
    assert [scope.start_chainage, scope.end_chainage] == metadata["document_scope"]


def _all_source_text(result: Any) -> str:
    return compact_text(
        " ".join(
            span.raw_text
            for record in [*result.primary_evidence, *result.report_assertions]
            for span in record.source_spans
        )
    )


def _all_source_pages(result: Any) -> set[int]:
    return {
        span.page_number
        for record in [*result.primary_evidence, *result.report_assertions]
        for span in record.source_spans
    }


def _assert_required_source_refs(result: Any, gold: dict[str, Any]) -> None:
    assert set(gold["must_include_source_pages"]).issubset(_all_source_pages(result))
    all_text = _all_source_text(result)
    for expected in gold["must_include_source_cell_text"]:
        assert compact_text(expected) in all_text


def test_manual_gold_files_are_not_written_by_parser() -> None:
    gold_paths = sorted(MANUAL_GOLD.glob("*.json"))
    before = {path: (path.stat().st_mtime_ns, _hash(path)) for path in gold_paths}
    for fixture in [
        FIXTURES / "sketch_dyk1013_184_2.pdf",
        FIXTURES / "hsp_dyk1013_190_2.pdf",
        FIXTURES / "tsp_dyk1013_080_2.pdf",
    ]:
        parse_pdf_v2(fixture)
    after = {path: (path.stat().st_mtime_ns, _hash(path)) for path in gold_paths}
    assert after == before


def test_sketch_manual_gold_from_real_pdf() -> None:
    gold = _load_gold("sketch_dyk1013_184_2.json")
    result = parse_pdf_v2(FIXTURES / "sketch_dyk1013_184_2.pdf")

    assert result.document.source_type == gold["source_type"]
    _assert_document_metadata(result, gold)
    assert len(result.primary_evidence) == 1
    evidence = result.primary_evidence[0]
    assert evidence.evidence_type == gold["primary_evidence"][0]["type"]
    assert evidence.epistemic_status == gold["primary_evidence"][0]["epistemic_status"]
    assert (
        evidence.spatial_scope.start_chainage
        == gold["primary_evidence"][0]["spatial_scope"]["start_chainage"]
    )
    for key, expected in gold["primary_evidence"][0]["expected_attributes"].items():
        assert evidence.attributes[key] == expected
    _assert_required_source_refs(result, gold["primary_evidence"][0])


def test_hsp_manual_gold_from_real_pdf() -> None:
    gold = _load_gold("hsp_dyk1013_190_2.json")
    result = parse_pdf_v2(FIXTURES / "hsp_dyk1013_190_2.pdf")

    assert result.document.source_type == gold["source_type"]
    _assert_document_metadata(result, gold)
    assert len(result.primary_evidence) == gold["primary_evidence_count"]
    face = result.primary_evidence[0]
    assert face.evidence_type == gold["face_observation"]["type"]
    assert face.epistemic_status == gold["face_observation"]["epistemic_status"]
    for key, expected in gold["face_observation"]["expected_attributes"].items():
        assert face.attributes[key] == expected
    assert _ranges(result) == [item["range"] for item in gold["forecast_segments"]]
    for evidence, expected in zip(
        _forecast_segments(result), gold["forecast_segments"], strict=True
    ):
        assert evidence.evidence_type == expected["type"]
        assert evidence.epistemic_status == expected["epistemic_status"]
        assert evidence.attributes["anomaly_level"] == expected["anomaly_level"]
        assert evidence.attributes["suggested_grade"] == expected["suggested_grade"]
        if "risk_points" in expected:
            assert evidence.attributes["risk_points"] == expected["risk_points"]
    _assert_required_source_refs(result, gold)


def test_tsp_manual_gold_from_real_pdf() -> None:
    gold = _load_gold("tsp_dyk1013_080_2.json")
    result = parse_pdf_v2(FIXTURES / "tsp_dyk1013_080_2.pdf")

    assert result.document.source_type == gold["source_type"]
    _assert_document_metadata(result, gold)
    assert len(result.primary_evidence) == gold["primary_evidence_count"]
    assert _ranges(result) == [item["range"] for item in gold["forecast_segments"]]
    for evidence, expected in zip(
        _forecast_segments(result), gold["forecast_segments"], strict=True
    ):
        assert evidence.evidence_type == expected["type"]
        assert evidence.epistemic_status == expected["epistemic_status"]
        for key, value in expected.items():
            if key not in {"range", "type", "epistemic_status"}:
                assert evidence.attributes[key] == value
    assert len(result.report_assertions) == gold["report_assertion_count"]
    _assert_report_assertions(result, gold["report_assertions"])
    _assert_required_source_refs(result, gold)


def _assert_report_assertions(result: Any, expected_assertions: list[dict[str, Any]]) -> None:
    actual = {
        (
            assertion.assertion_type,
            assertion.spatial_scope.start_chainage,
            assertion.spatial_scope.end_chainage,
        ): assertion
        for assertion in result.report_assertions
    }
    assert len(actual) == len(expected_assertions)
    for expected in expected_assertions:
        assertion = actual[(expected["type"], expected["range"][0], expected["range"][1])]
        assert assertion.consistency_status == expected["consistency_status"]
        for key, value in expected.items():
            if key in {"type", "range", "consistency_status", "conflict_contains"}:
                continue
            assert assertion.attributes[key] == value
        if "conflict_contains" in expected:
            assert expected["conflict_contains"] in assertion.conflict_details
        assert assertion.source_spans


def test_source_spans_have_real_bbox_and_crop_text() -> None:
    for fixture in [
        FIXTURES / "sketch_dyk1013_184_2.pdf",
        FIXTURES / "hsp_dyk1013_190_2.pdf",
        FIXTURES / "tsp_dyk1013_080_2.pdf",
    ]:
        result = parse_pdf_v2(fixture)
        with pdfplumber.open(fixture) as pdf:
            for record in [*result.primary_evidence, *result.report_assertions]:
                for span in record.source_spans:
                    assert span.bbox != (0.0, 0.0, 0.0, 0.0)
                    if span.extraction_method != "pdfplumber_table_cell":
                        continue
                    assert span.has_real_bbox
                    assert span.bbox is not None
                    crop_text = pdf.pages[span.page_number - 1].crop(span.bbox).extract_text() or ""
                    assert compact_text(crop_text)
                    assert _has_text_overlap(crop_text, span.raw_text)


def test_field_span_semantic_validation_from_bbox() -> None:
    result = parse_pdf_v2(FIXTURES / "sketch_dyk1013_184_2.pdf")
    evidence = result.primary_evidence[0]
    spans = {span.span_id: span for span in evidence.source_spans}
    expected_basis = {
        "rock_strength": "30＜R≤60√",
        "joint_spacing": "0.2～0.6√",
        "joint_extension": "中等√",
        "joint_roughness": "平整光滑有擦痕√",
        "joint_aperture": "部分张开0.1～0.5√",
        "karst_development": "无√",
        "design_surrounding_rock_grade": "Ⅴ",
        "suggested_surrounding_rock_grade": "Ⅴ",
        "form_water_status": "25～125涌出或喷出√",
        "form_water_other_raw": "其它500",
        "lithology": "板岩夹变质砂岩",
    }
    with pdfplumber.open(FIXTURES / "sketch_dyk1013_184_2.pdf") as pdf:
        for field, expected in expected_basis.items():
            assert field in evidence.field_spans
            crop_text = _field_crop_text(
                pdf, [spans[span_id] for span_id in evidence.field_spans[field]]
            )
            assert compact_text(expected) in compact_text(crop_text)
        for field, value in evidence.attributes.items():
            if value is not None:
                assert field in evidence.field_spans
                assert evidence.field_spans[field]
                assert all(span_id in spans for span_id in evidence.field_spans[field])


def _field_crop_text(pdf: Any, spans: list[Any]) -> str:
    values = []
    for span in spans:
        assert span.bbox is not None
        values.append(pdf.pages[span.page_number - 1].crop(span.bbox).extract_text() or "")
    return " ".join(values)


def test_content_detection_survives_copy_to_arbitrary_folder(tmp_path: Path) -> None:
    for fixture in [
        FIXTURES / "sketch_dyk1013_184_2.pdf",
        FIXTURES / "hsp_dyk1013_190_2.pdf",
        FIXTURES / "tsp_dyk1013_080_2.pdf",
    ]:
        copied = tmp_path / f"renamed_{fixture.name}"
        shutil.copy2(fixture, copied)
        result = parse_pdf_v2(copied)
        assert result.document.source_type != "UNSUPPORTED"
        assert result.primary_evidence


def test_src_has_no_sample_hardcoding_or_gold_dependency() -> None:
    src_root = Path("src/tbm_twin/geology/table_parser_v2")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in src_root.glob("*.py"))
    assert "tests/manual_gold" not in combined
    assert "tests/gold" not in combined
    forbidden = ["DyK1013+184.2", "DyK1013+080.2", "DyK1013+190.2", "1013182.0"]
    assert not any(token in combined for token in forbidden)


def test_non_gold_generalization_real_pdfs() -> None:
    samples = [
        FIXTURES / "blank_trailing_page_sketch.pdf",
        FIXTURES / "non_gold_hsp_13_page.pdf",
        FIXTURES / "non_gold_tsp_21_page.pdf",
        FIXTURES / "non_gold_hsp_non1013.pdf",
    ]
    for sample in samples:
        result = parse_pdf_v2(sample)
        assert not result.document.parse_warnings
        assert result.document.template_signature.status == "SUPPORTED"
        assert result.primary_evidence
        assert not _has_header_evidence(result)
        for evidence in result.primary_evidence:
            assert evidence.source_spans
            for span in evidence.source_spans:
                if span.extraction_method == "pdfplumber_table_cell":
                    assert span.has_real_bbox
        ranges = _ranges(result)
        if ranges:
            assert all(start < end for start, end in ranges)
            assert ranges == sorted(ranges)


def test_blank_trailing_page_sketch_support_boundary() -> None:
    result = parse_pdf_v2(FIXTURES / "blank_trailing_page_sketch.pdf")
    assert result.document.source_type == "FACE_SKETCH"
    assert result.primary_evidence
    assert {span.page_number for span in result.primary_evidence[0].source_spans} == {1}


def test_fixed_sketch_dyk1014_675_splits_forecast_from_face_point() -> None:
    result = parse_pdf_v2(_real_sketch_pdf("1014+675"))
    point = _face_points(result)[0]
    forecast = _forecast_segments(result)[0]

    assert point.spatial_scope.start_chainage == 1014675.0
    assert point.attributes["observation_scope"] == "FACE_POINT"
    assert point.attributes["joint_roughness"] == "平整光滑有擦痕"
    assert point.attributes["lithology"] is None
    assert forecast.epistemic_status == "FORECAST"
    assert [forecast.spatial_scope.start_chainage, forecast.spatial_scope.end_chainage] == [
        1014675.0,
        1014705.0,
    ]
    assert forecast.attributes["lithology"] == "板岩夹变质砂岩"


def test_fixed_sketch_dyk1015_655_separates_three_spatial_objects() -> None:
    result = parse_pdf_v2(_real_sketch_pdf("1015+655"))
    point = _face_points(result)[0]
    forecast = _forecast_segments(result)[0]
    observed = _observed_intervals(result)[0]

    assert point.spatial_scope.start_chainage == 1015655.0
    assert point.attributes["form_water_status"] == "25～125经常渗水"
    assert point.attributes["lithology"] is None
    assert point.attributes["rock_mass_state"] is None
    assert [forecast.spatial_scope.start_chainage, forecast.spatial_scope.end_chainage] == [
        1015625.0,
        1015655.0,
    ]
    assert forecast.attributes["lithology"] == "板岩夹变质砂岩"
    assert forecast.attributes["water_type"] is None
    assert [observed.spatial_scope.start_chainage, observed.spatial_scope.end_chainage] == [
        1015610.0,
        1015625.0,
    ]
    assert observed.attributes["observation_scope"] == "CURRENT_EXCAVATED_INTERVAL"
    assert observed.attributes["water_type"] == "线状出水"


def test_fixed_sketch_dyk1017_049_invalid_interval_is_audited_only() -> None:
    result = parse_pdf_v2(_real_sketch_pdf("1017+049"))
    point = _face_points(result)[0]
    forecast = _forecast_segments(result)[0]

    assert point.spatial_scope.start_chainage == 1017049.0
    assert point.attributes["form_water_other_raw"] == "96m³/h"
    assert [forecast.spatial_scope.start_chainage, forecast.spatial_scope.end_chainage] == [
        1017049.0,
        1017079.0,
    ]
    assert not _observed_intervals(result)
    invalid = [
        row for row in result.audit_rows if row.get("audit_type") == "INVALID_SOURCE_INTERVAL"
    ]
    assert invalid
    assert invalid[0]["raw_interval"] == "DyK1017+019~DyK1016+049"


def test_fixed_sketch_dyk1013_184_2_does_not_invent_unlocated_interval() -> None:
    result = parse_pdf_v2(FIXTURES / "sketch_dyk1013_184_2.pdf")

    assert len(result.primary_evidence) == 1
    point = _face_points(result)[0]
    assert point.spatial_scope.start_chainage == 1013184.2
    assert not _forecast_segments(result)
    assert not _observed_intervals(result)
    assert point.attributes["local_unlocated_observations"] == ["当前开挖段落存在线状出水，"]


def test_non_gold_tsp_21_page_cross_page_assertions_and_ed() -> None:
    result = parse_pdf_v2(FIXTURES / "non_gold_tsp_21_page.pdf")
    segments = _forecast_segments(result)
    assert segments[0].attributes["dynamic_elastic_modulus"] == "88~95"
    assertion_pages = {
        span.page_number
        for assertion in result.report_assertions
        for span in assertion.source_spans
    }
    assert {10, 11}.issubset(assertion_pages)
    risk_text = compact_text(" ".join(assertion.raw_text for assertion in result.report_assertions))
    for token in ["掉块", "坍塌", "出水", "卡机", "突涌水"]:
        assert token in risk_text
    assert any(
        assertion.assertion_type == "RISK_SUMMARY"
        and assertion.source_spans[0].page_number == 11
        and "卡机" in assertion.raw_text
        for assertion in result.report_assertions
    )


def test_non_gold_hsp_non1013_risk_prefix_and_ranges() -> None:
    result = parse_pdf_v2(FIXTURES / "non_gold_hsp_non1013.pdf")
    segments = _forecast_segments(result)
    assert len(segments) == 8
    assert segments[0].attributes["risk_hint"] is None
    assert segments[-1].spatial_scope.start_chainage == 1014115.0
    assert segments[-1].attributes["risk_points"] == [1014115.0]


def _has_text_overlap(left: str, right: str) -> bool:
    left_compact = compact_text(left)
    right_compact = compact_text(right)
    if left_compact in right_compact or right_compact in left_compact:
        return True
    left_tokens = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9.]+", left_compact))
    right_tokens = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9.]+", right_compact))
    return bool(left_tokens & right_tokens)


def _has_header_evidence(result: Any) -> bool:
    dumped = json.dumps([asdict(item) for item in result.primary_evidence], ensure_ascii=False)
    return "里程范围、本次预报结论、物探探测结果、风险提示、建议围岩等级" in dumped
