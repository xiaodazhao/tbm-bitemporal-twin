from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tbm_twin.evidence.geology_normalizer import normalize_geological_evidence
from tbm_twin.evidence.models import EvidenceBase, EvidenceType, GeologicalEpistemicStatus


def test_evidence_base_rejects_naive_evidence_times() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        EvidenceBase(
            evidence_id="evidence-1",
            evidence_type=EvidenceType.GEOLOGICAL_UNKNOWN,
            source_asset_ids=["asset-1"],
            valid_time=None,
            available_time=datetime(2026, 1, 1),
            ingested_time=datetime(2026, 1, 2, tzinfo=UTC),
            spatial_scope=None,
            quality_grade="C",
            quality_flags=[],
            method_version="test",
            provenance_refs=[],
        )


def test_unknown_geological_record_remains_explicitly_unknown(tmp_path) -> None:
    path = tmp_path / "geology.csv"
    path.write_text("id,text\n1,unclear note without time or chainage\n", encoding="utf-8")

    records = normalize_geological_evidence(path)

    assert records[0].evidence_type == EvidenceType.GEOLOGICAL_UNKNOWN
    assert records[0].epistemic_status == GeologicalEpistemicStatus.UNKNOWN
    assert "AVAILABLE_TIME_UNKNOWN" in records[0].quality_flags
    assert "SPATIAL_SCOPE_UNKNOWN" in records[0].quality_flags


def test_source_type_mapping_defaults_tsp_to_forecast(tmp_path) -> None:
    path = tmp_path / "geology.csv"
    path.write_text(
        "id,source_type,raw_text,start_num,end_num\n1,tsp,TSP forecast note,100.0,120.0\n",
        encoding="utf-8",
    )

    record = normalize_geological_evidence(path)[0]

    assert record.epistemic_status == GeologicalEpistemicStatus.FORECAST
    assert record.evidence_type == EvidenceType.GEOLOGICAL_FORECAST


def test_source_type_mapping_defaults_field_observation_to_observed(tmp_path) -> None:
    path = tmp_path / "geology.csv"
    path.write_text(
        "id,source_type,raw_text,start_num,end_num\n1,sketch,face sketch note,100.0,100.0\n",
        encoding="utf-8",
    )

    record = normalize_geological_evidence(path)[0]

    assert record.epistemic_status == GeologicalEpistemicStatus.OBSERVED
    assert record.evidence_type == EvidenceType.GEOLOGICAL_OBSERVATION


def test_source_type_mapping_defaults_design_background_to_background(tmp_path) -> None:
    path = tmp_path / "geology.csv"
    path.write_text(
        "id,source_type,raw_text,start_num,end_num\n"
        "1,DESIGN_BACKGROUND,regional design context,100.0,120.0\n",
        encoding="utf-8",
    )

    record = normalize_geological_evidence(path)[0]

    assert record.epistemic_status == GeologicalEpistemicStatus.BACKGROUND
    assert record.evidence_type == EvidenceType.GEOLOGICAL_BACKGROUND


def test_source_type_text_conflict_is_warned_and_downgraded(tmp_path) -> None:
    path = tmp_path / "geology.csv"
    path.write_text(
        "id,source_type,report_id,raw_text,start_num,end_num\n"
        "1,sketch,TSP_REPORT_001,face sketch note,100.0,100.0\n",
        encoding="utf-8",
    )

    record = normalize_geological_evidence(path)[0]

    assert record.epistemic_status == GeologicalEpistemicStatus.UNKNOWN
    assert "EPISTEMIC_SOURCE_CONFLICT" in record.quality_flags
