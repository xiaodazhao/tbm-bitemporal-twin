from tbm_twin.metrics.grs import build_grs_for_snapshots


def test_grs_contributing_evidence_is_dimension_winner_subset() -> None:
    snapshot = {
        "bitemporal_version_id": "b1",
        "base_stage3a_state_version_id": "s1",
        "valid_date": "2023-01-01",
        "knowledge_time_start_local_date": "2023-01-01",
        "cell_id": "c1",
        "cell_scope_role": "DAILY_REVIEW_CELL",
        "materialized_daily_review_evidence_ids": ["low", "high"],
    }
    evidence = {
        "low": {
            "evidence_uid": "low",
            "document_id": "d1",
            "source_type": "TSP_REPORT",
            "epistemic_status": "FORECAST",
            "attributes": {"rock_mass_state": "岩体较破碎"},
        },
        "high": {
            "evidence_uid": "high",
            "document_id": "d2",
            "source_type": "TSP_REPORT",
            "epistemic_status": "FORECAST",
            "attributes": {"rock_mass_state": "岩体破碎"},
        },
    }
    mapping = {
        ("rock_mass_state", "岩体较破碎"): {
            "dimension_name": "ROCK_MASS_INTEGRITY",
            "attention_value": 0.25,
            "mapping_id": "m_low",
        },
        ("rock_mass_state", "岩体破碎"): {
            "dimension_name": "ROCK_MASS_INTEGRITY",
            "attention_value": 0.75,
            "mapping_id": "m_high",
        },
    }
    _, state_rows, _, _ = build_grs_for_snapshots([snapshot], evidence, mapping)
    row = state_rows[0]
    assert row["role_evidence_uids"] == ["high", "low"]
    assert row["mapped_geological_evidence_uids"] == ["high", "low"]
    assert row["grs_contributing_evidence_uids"] == ["high"]
