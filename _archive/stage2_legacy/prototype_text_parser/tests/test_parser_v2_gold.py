from __future__ import annotations

# ruff: noqa: RUF001
from pathlib import Path

from tbm_twin.geology.parsers_v2 import parse_pdf_v2
from tbm_twin.geology.parsers_v2.models import PrimaryEvidenceType

TBM9 = (
    Path("/Users/zhaoxiaoda/Library/CloudStorage/GoogleDrive-xiaodazhao0608@gmail.com")
    / "我的云端硬盘"
    / "TBM9"
)
SKETCH_SAMPLE = TBM9 / "SKETCH" / "DyK1013+184.20_伯舒拉岭进口右线DyK1013+184.2洞身素描记录表.pdf"
HSP_SAMPLE = sorted((TBM9 / "HSP").glob("DyK1013+190.20_*.pdf"))[0]
TSP_SAMPLE = sorted((TBM9 / "TSP").glob("DyK1013+124.20_*.pdf"))[0]


def test_v2_sketch_gold_from_real_pdf() -> None:
    assert SKETCH_SAMPLE.exists()
    result = parse_pdf_v2(SKETCH_SAMPLE)
    evidence = result.primary_evidence

    assert len(evidence) == 1
    assert evidence[0].evidence_type == PrimaryEvidenceType.FACE_OBSERVATION
    assert evidence[0].spatial_scope.start_chainage == 1013184.2
    assert result.document.temporal.observed_local_date == "2023-09-09"
    attrs = evidence[0].attributes
    assert attrs["face_state"] == "正面掉块"
    assert attrs["excavated_face_state"] == "随时间松弛、掉块"
    assert attrs["form_water_selected_option"] == "涌出或喷出"
    assert attrs["form_water_other_raw"] == "500"
    assert attrs["lithology"] == "板岩夹变质砂岩"
    assert attrs["narrative_water"] == "渗滴水；线状出水"
    assert attrs["creates_local_interval_evidence"] is False


def test_v2_hsp_gold_from_real_pdf() -> None:
    assert HSP_SAMPLE.exists()
    result = parse_pdf_v2(HSP_SAMPLE)
    evidence = result.primary_evidence

    assert len(evidence) == 5
    assert result.document.face_chainage == 1013190.2
    assert result.document.temporal.observed_local_date == "2023-09-13"
    assert result.document.temporal.documented_local_date == "2023-09-14"
    assert result.document.temporal.submitted_local_date == "2023-09-14"
    ranges = [
        (item.spatial_scope.start_chainage, item.spatial_scope.end_chainage)
        for item in evidence[1:]
    ]
    assert ranges == [
        (1013190.2, 1013224.0),
        (1013224.0, 1013238.0),
        (1013238.0, 1013265.0),
        (1013265.0, 1013290.2),
    ]
    assert [item.attributes["anomaly_raw_text"] for item in evidence[1:]] == [
        "未见明显反射异常",
        "较明显反射异常",
        "未见明显反射异常",
        "明显反射异常",
    ]
    assert all(item.attributes["suggested_grade"] == "Ⅴ级" for item in evidence[1:])


def test_v2_tsp_gold_from_real_pdf() -> None:
    assert TSP_SAMPLE.exists()
    result = parse_pdf_v2(TSP_SAMPLE)
    evidence = result.primary_evidence

    assert len(evidence) == 8
    assert result.document.face_chainage == 1013080.2
    assert result.document.temporal.observed_local_date == "2023-06-02"
    assert result.document.temporal.documented_local_date == "2023-06-03"
    assert result.document.temporal.submitted_local_date == "2023-06-03"
    ranges = [
        (item.spatial_scope.start_chainage, item.spatial_scope.end_chainage)
        for item in evidence[1:]
    ]
    assert ranges == [
        (1013080.2, 1013096.0),
        (1013096.0, 1013114.0),
        (1013114.0, 1013120.0),
        (1013120.0, 1013137.0),
        (1013137.0, 1013161.0),
        (1013161.0, 1013182.0),
        (1013182.0, 1013200.2),
    ]
    first_row = evidence[1].attributes
    assert first_row["vp"] == "4871"
    assert first_row["vs"] == "2752"
    assert first_row["vp_vs"] == "1.77"
    assert first_row["poisson_ratio"] == "0.27"
    assert first_row["dynamic_elastic_modulus"] == "50"
    conflict = next(
        item
        for item in result.report_assertions
        if item.assertion_type == "GRADE_SUMMARY"
        and item.spatial_scope.start_chainage == 1013182.0
        and item.spatial_scope.end_chainage == 1013200.2
    )
    assert conflict.consistency_status == "CONFLICT"
    assert "table suggested_grade=Ⅴ级; summary suggested_grade=Ⅳ级" in conflict.conflict_details


def test_report_assertions_are_not_primary_evidence() -> None:
    result = parse_pdf_v2(TSP_SAMPLE)
    primary_ids = {item.evidence_id for item in result.primary_evidence}

    assert result.report_assertions
    assert not any(assertion.assertion_id in primary_ids for assertion in result.report_assertions)


def test_v2_source_spans_have_page_and_text_location() -> None:
    for path in [SKETCH_SAMPLE, HSP_SAMPLE, TSP_SAMPLE]:
        result = parse_pdf_v2(path)
        records = [*result.primary_evidence, *result.report_assertions]
        for record in records:
            assert record.source_spans
            for span in record.source_spans:
                assert span.page_number >= 1
                assert span.bbox is not None or (
                    span.text_start is not None and span.text_end is not None
                )
            if hasattr(record, "field_spans"):
                assert record.field_spans


def test_v1_parser_and_applicability_are_not_rewired() -> None:
    document_parsers = Path("src/tbm_twin/geology/document_parsers.py")
    applicability = Path("src/tbm_twin/evidence/applicability.py")

    assert document_parsers.exists()
    assert sum(1 for _ in document_parsers.open(encoding="utf-8")) >= 2000
    assert "parsers_v2" not in applicability.read_text(encoding="utf-8")
