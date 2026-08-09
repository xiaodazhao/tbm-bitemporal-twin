from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from tbm_twin.bitemporal.models import Stage3BConfig
from tbm_twin.bitemporal.revision_builder import Stage3BRevisionBuilder, _Candidate


def test_version_lineage_is_contiguous_and_right_open() -> None:
    chain = [
        {
            "version_number": 1,
            "knowledge_time_start_local_date": "2023-09-22",
            "knowledge_time_end_local_date": "2023-09-23",
        },
        {
            "version_number": 2,
            "knowledge_time_start_local_date": "2023-09-23",
            "knowledge_time_end_local_date": None,
        },
    ]
    assert [row["version_number"] for row in chain] == [1, 2]
    assert chain[0]["knowledge_time_end_local_date"] == chain[1]["knowledge_time_start_local_date"]
    assert chain[-1]["knowledge_time_end_local_date"] is None


def test_synthetic_same_day_evidence_merges_and_later_day_creates_v3(tmp_path: Path) -> None:
    builder = Stage3BRevisionBuilder(
        Stage3BConfig(
            repo_root=Path.cwd(),
            output_dir=tmp_path,
            generated_at=datetime.fromisoformat("2026-07-30T14:30:00+08:00"),
            knowledge_cutoff_date=date(2024, 11, 17),
            overwrite=True,
        )
    )
    base = {
        "state_version_id": "state_version_base",
        "daily_state_id": "daily_state_a",
        "cell_id": "cell_a",
        "cell_scope_role": "DAILY_REVIEW_CELL",
        "valid_date": "2023-09-22",
        "episode_ids": ["episode_a"],
        "response_evidence_ids": ["response_a"],
        "response_link_ids": ["response_link_a"],
        "daily_review_evidence_ids": [],
        "forward_attention_evidence_ids": [],
        "local_background_evidence_ids": [],
        "observed_geological_evidence_ids": [],
        "forecast_geological_evidence_ids": [],
        "background_geological_evidence_ids": [],
        "source_assignment_ids": [],
        "geological_link_ids": [],
        "state_quality_flags": [],
        "state_reason_codes": [],
    }
    candidates = [
        _candidate("app1", "doc1", "e1", date(2023, 9, 23)),
        _candidate("app2", "doc2", "e2", date(2023, 9, 23)),
        _candidate("app3", "doc3", "e3", date(2023, 9, 25)),
    ]
    versions, events, links, _ = builder._build_versions(
        base_versions=[base],
        candidates_by_base={"state_version_base": candidates},
        stage3a={
            "file_hash_manifest_hash": "stage3a_hash",
            "manifest": {
                "source_geology_manifest_hash": "geology_hash",
                "source_applicability_manifest_hash": "app_hash",
                "source_operational_manifest_hash": "op_hash",
            },
        },
    )
    assert [row["version_number"] for row in versions] == [1, 2, 3]
    assert versions[0]["knowledge_time_end_local_date"] == date(2023, 9, 23)
    assert versions[1]["knowledge_time_end_local_date"] == date(2023, 9, 25)
    assert len([row for row in versions if row["version_number"] == 2]) == 1
    assert len(events) == 3
    assert len(links) == 3
    assert set(versions[1]["materialized_daily_review_evidence_ids"]) == {"e1", "e2"}
    assert set(versions[2]["materialized_daily_review_evidence_ids"]) == {"e1", "e2", "e3"}


def _candidate(
    app_id: str,
    document_id: str,
    evidence_id: str,
    available: date,
) -> _Candidate:
    return _Candidate(
        revision_applicability_id=app_id,
        base_state_version_id="state_version_base",
        valid_date=date(2023, 9, 22),
        available_local_date=available,
        observed_local_date=date(2023, 9, 22),
        daily_state_id="daily_state_a",
        cell_id="cell_a",
        cell_scope_role="DAILY_REVIEW_CELL",
        evidence_id=evidence_id,
        document_id=document_id,
        asset_id=f"asset_{document_id}",
        source_type="SONIC_FORECAST",
        evidence_type="FORECAST_SEGMENT",
        epistemic_status="FORECAST",
        available_basis="submitted_time",
        revision_role="DAILY_REVIEW",
        overlap={
            "cell_overlap_kind": "INTERVAL",
            "cell_overlap_start": 1.0,
            "cell_overlap_end": 2.0,
            "cell_overlap_length_m": 1.0,
        },
        source_span_ids=[f"span_{evidence_id}"],
        reason_codes=["LATE_AVAILABLE_PRIMARY_EVIDENCE"],
    )
