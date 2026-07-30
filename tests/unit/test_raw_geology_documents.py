from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import fitz

from tbm_twin.evidence.applicability import assign_evidence_to_episode
from tbm_twin.evidence.models import (
    ApplicabilityResult,
    GeologicalSourceType,
    TemporalApplicabilityStatus,
    TemporalRole,
)
from tbm_twin.evidence.temporal_rules import evaluate_temporal_availability
from tbm_twin.geology.document_models import GeologicalPdfSourceAsset, PdfPageText
from tbm_twin.geology.document_parsers import (
    SonicDocumentParser,
    day_extent,
    extract_spatial_candidates,
    extract_temporal_candidates,
    parser_for_source,
)
from tbm_twin.geology.raw_documents import (
    extract_pdf_page_text,
    infer_source_type_from_path,
    register_pdf_source_asset,
)
from tbm_twin.process.episode_builder import build_excavation_episodes
from tbm_twin.process.weak_labels import label_operation_phases
from tbm_twin.trajectory.footprint_builder import build_spatial_footprints
from tests.conftest import base_rows, normalize_rows


def _page(text: str, *, page_number: int = 1) -> PdfPageText:
    return PdfPageText(
        asset_id="asset-test",
        page_number=page_number,
        page_text=text,
        extraction_method="fixture",
        text_length=len(text.strip()),
        extraction_warnings=[],
    )


def _asset(source_type: GeologicalSourceType = GeologicalSourceType.SONIC_FORECAST):
    return GeologicalPdfSourceAsset(
        asset_id="asset-test",
        source_path=Path("/tmp/HSP/report.pdf"),
        source_filename="report.pdf",
        source_type=source_type,
        sha256="0" * 64,
        file_size=10,
        page_count=1,
        text_layer_available=True,
        ingested_time=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_source_asset_and_page_text_are_per_pdf_and_per_page(tmp_path) -> None:
    pdf_path = tmp_path / "HSP" / "sonic-report.pdf"
    pdf_path.parent.mkdir()
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "检测日期\uff1a2023年9月13日\nDK0+090-DK0+120")
    doc.save(pdf_path)
    doc.close()

    asset = register_pdf_source_asset(pdf_path)
    pages = extract_pdf_page_text(asset.asset_id, pdf_path)

    assert asset.source_type == GeologicalSourceType.SONIC_FORECAST
    assert asset.page_count == 1
    assert asset.text_layer_available is True
    assert pages[0].asset_id == asset.asset_id
    assert pages[0].page_number == 1
    assert "2023" in pages[0].page_text


def test_blank_pdf_is_unavailable_text_layer_not_fabricated(tmp_path) -> None:
    pdf_path = tmp_path / "SKETCH" / "blank.pdf"
    pdf_path.parent.mkdir()
    doc = fitz.open()
    doc.new_page()
    doc.save(pdf_path)
    doc.close()

    asset = register_pdf_source_asset(pdf_path)
    pages = extract_pdf_page_text(asset.asset_id, pdf_path)

    assert asset.source_type == GeologicalSourceType.FACE_SKETCH
    assert asset.text_layer_available is False
    assert pages[0].extraction_warnings == ["PDF_TEXT_LAYER_UNAVAILABLE"]


def test_source_type_is_inferred_from_raw_pdf_path() -> None:
    assert infer_source_type_from_path(Path("/raw/TSP/a.pdf")) == GeologicalSourceType.TSP_REPORT
    assert (
        infer_source_type_from_path(Path("/raw/HSP/a.pdf")) == GeologicalSourceType.SONIC_FORECAST
    )
    assert (
        infer_source_type_from_path(Path("/raw/SKETCH/a.pdf")) == GeologicalSourceType.FACE_SKETCH
    )


def test_temporal_candidates_distinguish_detection_submission_and_irrelevant_dates() -> None:
    text = (
        "检测日期\uff1a2023年9月13日\n"
        "2023年9月14日提交预报结果\n"
        "仪器检定有效期\uff1a2023年6月5日至2024年6月4日\n"
    )

    candidates = extract_temporal_candidates(
        [_page(text)],
        GeologicalSourceType.SONIC_FORECAST,
        "HSP-20230914.pdf",
    )

    roles = [candidate.semantic_role for candidate in candidates]
    assert TemporalRole.OBSERVED in roles
    assert TemporalRole.SUBMITTED in roles
    assert TemporalRole.IRRELEVANT in roles


def test_day_precision_available_time_is_not_second_precision() -> None:
    extent = day_extent(
        datetime(2023, 9, 14, tzinfo=UTC).date(),
        basis="fixture",
        candidate_ids=["candidate-1"],
    )

    assert extent.earliest_possible_time == datetime(2023, 9, 13, 16, tzinfo=UTC)
    assert extent.latest_possible_time == datetime(2023, 9, 14, 16, tzinfo=UTC)
    assert (
        evaluate_temporal_availability(
            available_time=None,
            available_time_extent=extent,
            evaluation_time=datetime(2023, 9, 14, 8, tzinfo=UTC),
        )
        == TemporalApplicabilityStatus.UNKNOWN_WITHIN_PRECISION
    )


def test_sonic_parser_uses_submission_day_as_available_time_not_ingested_mtime() -> None:
    text = (
        "检测日期\uff1a2023年9月13日\n2023年9月14日提交预报结果\n"
        "预报结论\uff1aDK0+090-DK0+120围岩破碎\uff0c存在涌水风险。"
    )

    result = SonicDocumentParser().parse(_asset(), [_page(text)])

    assert result.document is not None
    assert result.evidence
    assert result.document.available_time_extent is not None
    assert result.document.available_time_extent.basis == "SUBMITTED_TIME_DAY_PRECISION"
    assert result.evidence[0].available_time is None
    assert result.evidence[0].available_time_extent == result.document.available_time_extent


def test_unparsed_blank_document_does_not_emit_evidence() -> None:
    result = SonicDocumentParser().parse(_asset(), [_page("")])

    assert result.document is None
    assert result.evidence == []
    assert result.unparsed_reason == "PDF_TEXT_LAYER_UNAVAILABLE"


def test_spatial_candidates_extract_point_and_range() -> None:
    candidates = extract_spatial_candidates(
        [_page("掌子面里程\uff1aDK0+090.5\n预报范围 DK0+090-DK0+120")]
    )

    roles = {candidate.role for candidate in candidates}
    assert "face_chainage_strict" in roles
    assert "document_forecast_scope" in roles


def test_source_specific_parser_dispatch() -> None:
    assert parser_for_source(GeologicalSourceType.SONIC_FORECAST).__class__ is SonicDocumentParser


def test_same_day_unknown_precision_remains_undetermined_when_spatially_usable(
    catalog,
    tmp_path,
) -> None:
    labeled = label_operation_phases(normalize_rows(tmp_path, base_rows(), catalog))
    episode = build_excavation_episodes(labeled)[0]
    footprint = build_spatial_footprints(labeled, [episode])[0]
    text = (
        "检测日期\uff1a2025年12月31日\n2025年12月31日提交预报结果\n"
        "预报结论\uff1aDK0+090-DK0+120围岩破碎\uff0c存在涌水风险。"
    )
    evidence = SonicDocumentParser().parse(_asset(), [_page(text)]).evidence[0]

    assignment = assign_evidence_to_episode(
        evidence,
        episode,
        footprint,
        evaluation_time=evidence.available_time_extent.earliest_possible_time,
    )

    assert assignment.result == ApplicabilityResult.UNDETERMINED
    assert assignment.temporal_status == TemporalApplicabilityStatus.UNKNOWN_WITHIN_PRECISION
    assert assignment.dominant_reason_code == "UNKNOWN_WITHIN_PRECISION"


def test_raw_geology_quality_is_not_default_a_when_metadata_is_missing() -> None:
    result = SonicDocumentParser().parse(
        _asset(),
        [_page("预报结论\uff1a围岩破碎\uff0c节理发育\uff0c存在涌水风险\uff0c建议加强支护。")],
    )

    assert result.evidence == []
    assert result.unresolved_table_cells
    assert result.unresolved_table_cells[0]["status"] == "UNRESOLVED_TABLE_CELL"
