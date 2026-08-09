from __future__ import annotations

from tbm_twin.bitemporal.materialization import materialized_snapshot


def test_materialized_snapshot_contains_delta_and_inherited_references() -> None:
    version = {
        "bitemporal_version_id": "bitemporal_version_abc",
        "base_stage3a_state_version_id": "state_version_a",
        "daily_state_id": "daily_a",
        "cell_id": "cell_a",
        "cell_scope_role": "DAILY_REVIEW_CELL",
        "valid_date": "2023-09-22",
        "knowledge_time_start_local_date": "2023-09-23",
        "knowledge_time_end_local_date": None,
        "version_number": 2,
        "is_current_as_of_cutoff": True,
        "materialized_daily_review_evidence_ids": ["e1", "e2"],
        "materialized_forward_attention_evidence_ids": [],
        "materialized_local_background_evidence_ids": [],
        "materialized_observed_evidence_ids": ["e1"],
        "materialized_forecast_evidence_ids": ["e2"],
        "materialized_background_evidence_ids": [],
        "materialized_source_assignment_ids": ["a1"],
        "inherited_stage3a_geological_link_ids": ["l1"],
        "materialized_revision_geological_link_ids": ["rl1"],
        "materialized_episode_ids": ["episode1"],
        "materialized_response_evidence_ids": ["response1"],
        "materialized_response_link_ids": ["response_link1"],
        "state_quality_flags": [],
        "state_reason_codes": ["ADD_PRIMARY_GEOLOGICAL_EVIDENCE"],
        "stage3b_method_version": "method",
    }
    snapshot = materialized_snapshot(version)
    assert snapshot["snapshot_id"] == "snapshot_abc"
    assert snapshot["inherited_stage3a_geological_link_ids"] == ["l1"]
    assert snapshot["materialized_revision_geological_link_ids"] == ["rl1"]
    assert snapshot["materialized_response_evidence_ids"] == ["response1"]
