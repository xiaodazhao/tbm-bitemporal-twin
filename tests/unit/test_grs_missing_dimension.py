from tbm_twin.metrics.grs import build_grs_for_snapshots


def test_missing_dimension_is_not_zero_filled() -> None:
    snapshots = [
        {
            "bitemporal_version_id": "b1",
            "base_stage3a_state_version_id": "s1",
            "valid_date": "2023-01-01",
            "knowledge_time_start_local_date": "2023-01-01",
            "cell_id": "c1",
            "cell_scope_role": "DAILY_REVIEW_CELL",
            "materialized_daily_review_evidence_ids": [],
        }
    ]
    _, state_rows, _, _ = build_grs_for_snapshots(snapshots, {}, {})
    assert state_rows[0]["grs"] is None
    assert state_rows[0]["grs_status"] == "NO_MAPPED_GEOLOGICAL_ATTENTION_DIMENSION"
