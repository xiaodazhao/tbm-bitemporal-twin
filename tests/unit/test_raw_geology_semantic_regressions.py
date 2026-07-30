# ruff: noqa: RUF001
from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import fitz
import pytest

from scripts.validate_stage2_raw_geology import parse_raw_geology
from tbm_twin.evidence.applicability import assign_evidence_to_episode
from tbm_twin.evidence.models import (
    ApplicabilityResult,
    EvidenceType,
    GeologicalSourceType,
    TemporalApplicabilityStatus,
)
from tbm_twin.geology.chainage import ChainageValidationConfig, parse_chainage_interval
from tbm_twin.geology.document_models import GeologicalPdfSourceAsset, PdfPageText
from tbm_twin.geology.document_parsers import (
    SOURCE_TIMEZONE,
    FaceSketchDocumentParser,
    SonicDocumentParser,
    TSPDocumentParser,
    day_extent,
    extract_structured_attributes,
)
from tbm_twin.geology.raw_documents import extract_pdf_page_text, register_pdf_source_asset
from tbm_twin.process.episode_builder import build_excavation_episodes
from tbm_twin.process.weak_labels import label_operation_phases
from tbm_twin.trajectory.footprint_builder import build_spatial_footprints
from tests.conftest import base_rows, normalize_rows

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "geology_pdfs"
REAL_PDF_FIXTURES = {
    "DyK1014+019.00_": FIXTURES / "raw_hsp_dyk1014_019.pdf",
    "DyK1017+215.00_": FIXTURES / "raw_tsp_dyk1017_215.pdf",
    "DyK1013+184.20_": FIXTURES / "sketch_dyk1013_184_2.pdf",
}


def _page(text: str, page_number: int = 1) -> PdfPageText:
    return PdfPageText(
        asset_id="asset-test",
        page_number=page_number,
        page_text=text,
        extraction_method="fixture",
        text_length=len(text.strip()),
    )


def _asset(
    source_type: GeologicalSourceType,
    filename: str = "DyK1013+090.00_test(DyK1013+090-DyK1013+120).pdf",
) -> GeologicalPdfSourceAsset:
    return GeologicalPdfSourceAsset(
        asset_id="asset-test",
        source_path=Path("/tmp") / filename,
        source_filename=filename,
        source_type=source_type,
        sha256="0" * 64,
        content_id="content-test",
        file_size=10,
        page_count=1,
        text_layer_available=True,
        ingested_time=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _write_pdf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def _real_pdf_asset(filename_token: str) -> GeologicalPdfSourceAsset:
    path = REAL_PDF_FIXTURES.get(filename_token)
    if path is None or not path.exists():
        pytest.skip(f"real PDF fixture not found for token: {filename_token}")
    return register_pdf_source_asset(path)


def test_date_extent_uses_source_local_date_without_second_timezone_shift() -> None:
    extent = day_extent(datetime(2023, 9, 14).date(), basis="fixture", candidate_ids=["c1"])

    local_start = extent.earliest_possible_time.astimezone(ZoneInfo(SOURCE_TIMEZONE)).date()

    assert local_start.isoformat() == "2023-09-14"


def test_hsp_submission_window_remains_local_september_14() -> None:
    text = (
        "检测日期\uff1a2023年9月13日\n2023年9月14日提交预报结果\n"
        "预报结论\uff1aDK0+090-DK0+120围岩破碎\uff0c存在涌水风险。"
    )
    result = SonicDocumentParser().parse(
        _asset(GeologicalSourceType.SONIC_FORECAST),
        [_page(text)],
    )

    assert result.document is not None
    local_start = result.document.available_time_extent.earliest_possible_time.astimezone(
        ZoneInfo(SOURCE_TIMEZONE)
    )
    assert local_start.date().isoformat() == "2023-09-14"


def test_document_time_is_captured_but_submission_still_controls_available_time() -> None:
    text = (
        "报告编制日期\uff1a2023年9月20日\n"
        "检测日期\uff1a2023年9月13日\n2023年9月14日提交预报结果\n"
        "预报结论\uff1aDK0+090-DK0+120围岩破碎\uff0c存在涌水风险。"
    )

    result = SonicDocumentParser().parse(
        _asset(GeologicalSourceType.SONIC_FORECAST),
        [_page(text)],
    )

    assert result.document is not None
    assert result.document.document_time_extent is not None
    assert result.document.issued_time_extent is None
    documented_start = result.document.document_time_extent.earliest_possible_time.astimezone(
        ZoneInfo(SOURCE_TIMEZONE)
    )
    available_start = result.document.available_time_extent.earliest_possible_time.astimezone(
        ZoneInfo(SOURCE_TIMEZONE)
    )
    assert documented_start.date().isoformat() == "2023-09-20"
    assert available_start.date().isoformat() == "2023-09-14"


def test_sketch_date_window_remains_local_september_9() -> None:
    text = "日期\uff1a2023年9月9日\n掌子面里程\uff1aDK0+090\n围岩破碎\uff0c节理发育。"
    from tbm_twin.geology.document_parsers import FaceSketchDocumentParser

    result = FaceSketchDocumentParser().parse(
        _asset(GeologicalSourceType.FACE_SKETCH),
        [_page(text)],
    )

    assert result.document is not None
    local_start = result.document.available_time_extent.earliest_possible_time.astimezone(
        ZoneInfo(SOURCE_TIMEZONE)
    )
    assert local_start.date().isoformat() == "2023-09-09"


def test_tsp_does_not_select_face_chainage_from_engineering_background() -> None:
    text = "工程地质概况\uff1a既有资料显示掌子面DK0+500附近围岩破碎。"
    result = TSPDocumentParser().parse(
        _asset(GeologicalSourceType.TSP_REPORT),
        [_page(text)],
    )

    assert result.document is not None
    assert result.document.face_chainage != 500.0
    assert result.document.face_chainage_basis == "filename_leading_chainage_face_fallback"


def test_cover_forecast_scope_does_not_generate_forecast_segment() -> None:
    text = "封面\n预报范围 DK0+090-DK0+120\n报告日期\uff1a2023年9月14日"
    result = SonicDocumentParser().parse(
        _asset(GeologicalSourceType.SONIC_FORECAST),
        [_page(text)],
    )

    assert result.document is not None
    assert result.evidence == []


def test_already_excavated_section_is_observed_not_forecast() -> None:
    text = "已开挖洞身揭示 DK0+090-DK0+120 围岩破碎\uff0c节理发育。"
    result = SonicDocumentParser().parse(
        _asset(GeologicalSourceType.SONIC_FORECAST),
        [_page(text)],
    )

    assert result.evidence
    assert result.evidence[0].evidence_type == EvidenceType.GEOLOGICAL_OBSERVATION


def test_valid_segment_does_not_inherit_unrelated_candidate_warning() -> None:
    text = "预报结论\uff1aDK0+090-DK0+120围岩破碎\uff0c存在涌水风险。\n测线布置 DK0+300-DK0+250。"
    result = SonicDocumentParser().parse(
        _asset(GeologicalSourceType.SONIC_FORECAST),
        [_page(text)],
    )

    assert result.document is not None
    assert any("CHAINAGE_DIRECTION_CONFLICT" in flag for flag in result.document.document_warnings)
    assert not any(flag.startswith("CHAINAGE_") for flag in result.evidence[0].quality_flags)


def test_sketch_bad_interval_does_not_invalidate_face_point_observation() -> None:
    from tbm_twin.geology.document_parsers import FaceSketchDocumentParser

    text = (
        "日期\uff1a2023年9月9日\n掌子面里程\uff1aDK0+090\n已开挖洞身揭示 DK0+120-DK0+100 围岩破碎。"
    )
    result = FaceSketchDocumentParser().parse(
        _asset(GeologicalSourceType.FACE_SKETCH),
        [_page(text)],
    )

    face = [record for record in result.evidence if record.source_level == "face_observation"]
    intervals = [
        record for record in result.evidence if record.source_level == "local_interval_observation"
    ]
    assert face
    assert face[0].chainage_interval.spatial_scope_usable is True
    assert intervals
    assert intervals[0].chainage_interval.spatial_scope_usable is False


def test_left_line_asset_and_duplicate_sha_do_not_generate_formal_evidence(tmp_path) -> None:
    hsp_dir = tmp_path / "HSP"
    tsp_dir = tmp_path / "TSP"
    sketch_dir = tmp_path / "SKETCH"
    tsp_dir.mkdir()
    sketch_dir.mkdir()
    text = "预报结论\uff1aDK0+090-DK0+120围岩破碎\uff0c存在涌水风险。"
    original = hsp_dir / "DyK1013+090_伯舒拉岭进口右线报告(DyK1013+090-DyK1013+120).pdf"
    duplicate = hsp_dir / "DyK1013+090_伯舒拉岭进口右线报告_duplicate.pdf"
    left = hsp_dir / "DyK1013+090_伯舒拉岭左线报告(DyK1013+090-DyK1013+120).pdf"
    _write_pdf(original, text)
    shutil.copyfile(original, duplicate)
    _write_pdf(left, text)

    result = parse_raw_geology(tsp_dir=tsp_dir, hsp_dir=hsp_dir, sketch_dir=sketch_dir)

    assert len(result["assets"]) == 3
    assert len(result["duplicate_rows"]) == 1
    assert len(result["out_of_scope_rows"]) == 1
    assert len(result["documents"]) == 1
    assert len(result["evidence"]) <= 1


def test_structured_attributes_and_provenance_are_from_evidence_text() -> None:
    text = (
        "预报结论\uff1aDK0+090-DK0+120围岩破碎\uff0c节理发育\uff0c存在涌水风险\uff0c建议加强支护。"
    )
    result = SonicDocumentParser().parse(
        _asset(GeologicalSourceType.SONIC_FORECAST),
        [_page(text)],
    )

    record = result.evidence[0]
    assert record.structured_attributes["rock_mass_state"] == "破碎"
    assert record.structured_attributes["joint_development"] == "节理发育"
    assert record.structured_attributes["source_risk_text"] != "UNKNOWN"
    assert record.source_page_refs == [1]
    assert record.source_text_refs == [record.raw_text]


def test_stage21_hard_exclusion_priority_is_preserved(catalog, tmp_path) -> None:
    labeled = label_operation_phases(normalize_rows(tmp_path, base_rows(), catalog))
    episode = build_excavation_episodes(labeled)[0]
    footprint = build_spatial_footprints(labeled, [episode])[0]
    text = (
        "检测日期\uff1a2025年12月31日\n2025年12月31日提交预报结果\n"
        "预报结论\uff1aDK0+300-DK0+320围岩破碎\uff0c存在涌水风险。"
    )
    evidence = (
        SonicDocumentParser()
        .parse(
            _asset(GeologicalSourceType.SONIC_FORECAST),
            [_page(text)],
        )
        .evidence[0]
    )

    assignment = assign_evidence_to_episode(
        evidence,
        episode,
        footprint,
        evaluation_time=evidence.available_time_extent.earliest_possible_time,
    )

    assert assignment.result == ApplicabilityResult.NOT_APPLICABLE
    assert assignment.temporal_status == TemporalApplicabilityStatus.UNKNOWN_WITHIN_PRECISION
    assert assignment.dominant_reason_code == "SPATIAL_DISJOINT"


def test_task_requirement_standard_and_method_sections_do_not_generate_evidence() -> None:
    text = (
        "本次超前地质预报工作的任务要求：查明前方地质条件并提交报告。\n\n"
        "执行规范：《铁路隧道超前地质预报技术规程》。\n\n"
        "方法原理：通过震动信号分析推断掌子面前方物性差异。"
    )
    result = TSPDocumentParser().parse(
        _asset(GeologicalSourceType.TSP_REPORT),
        [_page(text)],
    )

    assert result.evidence == []
    assert {row["reason"] for row in result.non_evidence_sections} >= {
        "TASK_OR_WORK_REQUIREMENT",
        "EXECUTION_STANDARD",
        "METHOD_PRINCIPLE",
    }


def test_tsp_hsp_table_row_generates_one_segment_and_risk_inherits_row_range() -> None:
    text = (
        "本次预报结论\n"
        "里程范围 物探参数 地质解释 预报结论 风险提示 建议围岩等级\n"
        "DyK1013+090-DyK1013+120 低速异常 解释为破碎带 "
        "该段围岩破碎，节理裂隙发育 风险提示：可能掉块、涌水 V级\n"
    )
    result = SonicDocumentParser().parse(
        _asset(GeologicalSourceType.SONIC_FORECAST),
        [_page(text)],
    )

    assert len(result.evidence) == 1
    record = result.evidence[0]
    assert record.source_level == "forecast_segment"
    assert record.spatial_scope is not None
    assert record.spatial_scope.start_chainage == 1013090.0
    assert record.spatial_scope.end_chainage == 1013120.0
    assert "风险提示" in record.raw_text
    assert record.structured_attributes["extraction_rule"] == "forecast_table_row_reconstruction"


def test_unassigned_table_or_risk_text_does_not_fallback_to_document_scope() -> None:
    text = "预报范围 DyK1013+090-DyK1013+120\n风险提示：可能掉块、涌水，建议加强支护。"
    result = SonicDocumentParser().parse(
        _asset(GeologicalSourceType.SONIC_FORECAST),
        [_page(text)],
    )

    assert result.evidence == []
    assert result.unresolved_table_cells
    assert result.unresolved_table_cells[0]["status"] == "UNRESOLVED_TABLE_CELL"


def test_dyk1013_1842_sketch_face_observation_has_complete_attributes() -> None:
    text = (
        "掌子面素描表\n"
        "里程：DyK1013+184.2\n"
        "掌子面状态 稳定 正面掉块√ 正面挤出 正面不能自稳\n"
        "毛开挖 自稳 随时间松弛、掉块√ 自稳困难、要及时支护 要超前支护\n"
        "岩石强度 R＞60 30＜R≤60√ 15＜R≤30 5＜R≤15 R＜5\n"
        "风化程度 未风化 微风化 弱风化√ 强风化 全风化\n"
        "间距 ＞1.5 0.6～1.5 0.2～0.6√ 0.06～0.2 ＜0.06\n"
        "延伸性 极差 差 中等√ 好 极好\n"
        "粗糙度 明显台阶状 粗糙波纹状 平整光滑有擦痕√ 平整光滑\n"
        "张开性 密闭＜0.1 部分张开0.1～0.5√ 张开0.5～1.0 无充填张开＞1.0\n"
        "涌水状态 无水 湿润 偶有渗水 涌出或喷出√\n"
        "岩溶发育程度 无√ 弱 中等 强烈\n"
        "设计围岩级别 Ⅴ 建议围岩级别 Ⅴ\n"
        "地质描述：掌子面围岩为板岩夹变质砂岩，弱风化，节理裂隙发育，"
        "岩体破碎，存在轻微掉块现象，见渗滴水，围岩自稳性较差，判定洞身围岩为Ⅴ级。"
    )
    result = FaceSketchDocumentParser().parse(
        _asset(GeologicalSourceType.FACE_SKETCH, "DyK1013+184.2_sketch.pdf"),
        [_page(text)],
    )

    face = next(record for record in result.evidence if record.source_level == "face_observation")
    attrs = face.structured_attributes
    assert face.face_chainage == 1013184.2
    assert attrs["lithology"] == "板岩夹变质砂岩"
    assert attrs["weathering"] == "弱风化"
    assert attrs["joint_development"] == "节理裂隙发育"
    assert attrs["rock_mass_state"] == "破碎"
    assert attrs["block_fall_or_collapse"] is True
    assert attrs["water_state"] == "渗滴水"
    assert attrs["stability"] == "自稳性较差"
    assert attrs["surrounding_rock_grade"] == "Ⅴ级"


def test_checkbox_parser_only_reads_checked_options() -> None:
    attrs = extract_structured_attributes(
        "涌水状态 无水 湿润 偶有渗水√ 涌出或喷出\n设计围岩级别 Ⅳ 建议围岩级别 Ⅴ",
        "face_observation",
    )

    assert attrs["water_state"] == "偶有渗水"
    assert attrs["water_state"] != "涌出或喷出"
    assert attrs["suggested_surrounding_rock_grade"] == "Ⅴ级"


def test_compound_lithology_and_degree_terms_are_not_downgraded() -> None:
    cases = [
        (
            "板岩夹变质砂岩，破碎-极破碎，节理裂隙发育密集，稳定性较差。",
            "板岩夹变质砂岩",
            "破碎-极破碎",
            "节理裂隙发育密集",
            "稳定性较差",
        ),
        (
            "板岩夹砂岩，较破碎，节理裂隙较发育，自稳性较差。",
            "板岩夹砂岩",
            "较破碎",
            "节理裂隙较发育",
            "自稳性较差",
        ),
    ]

    for text, lithology, rock_state, joint, stability in cases:
        attrs = extract_structured_attributes(text, "forecast_segment")
        assert attrs["lithology"] == lithology
        assert attrs["rock_mass_state"] == rock_state
        assert attrs["joint_development"] == joint
        assert attrs["stability"] == stability


def test_negated_reflection_anomaly_outputs_none() -> None:
    attrs = extract_structured_attributes("该段未见明显反射异常，围岩较完整。", "forecast_segment")

    assert attrs["anomaly_level"] == "NONE"


def test_normal_km_boundary_crossing_ranges_are_valid() -> None:
    for raw_text, length in [
        ("DyK1014+984-DyK1015+002，长度18m", 18.0),
        ("DyK1015+978-DyK1016+005，长度27m", 27.0),
        ("DyK1016+998-DyK1017+055，长度57m", 57.0),
    ]:
        interval = parse_chainage_interval({}, raw_text, ChainageValidationConfig())
        assert interval is not None
        assert interval.normalized_end_chainage - interval.normalized_start_chainage == length
        assert "CHAINAGE_PREFIX_MISMATCH" not in interval.validation_flags
        assert interval.spatial_scope_usable is True


def test_exact_duplicate_forecast_evidence_is_not_emitted_twice() -> None:
    sentence = "预报结论：DyK1013+090-DyK1013+120围岩破碎，节理发育，存在涌水风险。"
    result = SonicDocumentParser().parse(
        _asset(GeologicalSourceType.SONIC_FORECAST),
        [_page(f"{sentence}\n\n{sentence}")],
    )

    assert len(result.evidence) == 1


def test_real_hsp_continuation_table_generates_rows_not_header() -> None:
    asset = _real_pdf_asset("DyK1014+019.00_")
    pages = extract_pdf_page_text(asset.asset_id, asset.source_path)

    result = SonicDocumentParser().parse(asset, pages)

    table_rows = [
        record
        for record in result.evidence
        if record.structured_attributes["extraction_rule"] == "forecast_table_row_reconstruction"
    ]
    assert len(table_rows) == 8
    assert not any(
        record.raw_text == "里程范围 （长度） 本次预报结论" for record in result.evidence
    )


def test_real_tsp_continuation_table_generates_all_rows() -> None:
    asset = _real_pdf_asset("DyK1017+215.00_")
    pages = extract_pdf_page_text(asset.asset_id, asset.source_path)

    result = TSPDocumentParser().parse(asset, pages)

    table_rows = [
        record
        for record in result.evidence
        if record.structured_attributes["extraction_rule"] == "forecast_table_row_reconstruction"
    ]
    ranges = [
        (record.spatial_scope.start_chainage, record.spatial_scope.end_chainage)
        for record in table_rows
    ]
    assert ranges == [
        (1017215.0, 1017228.0),
        (1017228.0, 1017245.0),
        (1017245.0, 1017259.0),
        (1017259.0, 1017269.0),
        (1017269.0, 1017289.0),
        (1017289.0, 1017307.0),
        (1017307.0, 1017315.0),
    ]


def test_real_face_sketch_general_advice_does_not_create_anomaly() -> None:
    asset = _real_pdf_asset("DyK1013+184.20_")
    pages = extract_pdf_page_text(asset.asset_id, asset.source_path)

    result = FaceSketchDocumentParser().parse(asset, pages)

    face = next(record for record in result.evidence if record.source_level == "face_observation")
    assert face.structured_attributes["anomaly_level"] == "UNKNOWN"
    assert face.structured_attributes["forecast_qualifiers"] == "UNKNOWN"
    assert "开挖" not in str(face.structured_attributes["source_risk_text"])[:20]


def test_long_km_boundary_crossing_ranges_are_valid_when_length_matches() -> None:
    for raw_text, length in [
        ("DyK1014+117-DyK1015+017（900m）", 900.0),
        ("DyK1015+807-DyK1016+367（560m）", 560.0),
        ("DyK1016+967-DyK1017+277（310m）", 310.0),
        ("DyK1017+477-DyK1018+377（900m）", 900.0),
    ]:
        interval = parse_chainage_interval({}, raw_text, ChainageValidationConfig())
        assert interval is not None
        assert interval.normalized_end_chainage - interval.normalized_start_chainage == length
        assert "CHAINAGE_PREFIX_MISMATCH" not in interval.validation_flags
        assert interval.spatial_scope_usable is True
