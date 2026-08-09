from tbm_twin.metrics.grs import build_grs_for_snapshots


def test_grs_dimension_max_then_dimension_mean() -> None:
    snapshots = [
        {
            "bitemporal_version_id": "b1",
            "base_stage3a_state_version_id": "s1",
            "valid_date": "2023-01-01",
            "knowledge_time_start_local_date": "2023-01-01",
            "cell_id": "c1",
            "cell_scope_role": "DAILY_REVIEW_CELL",
            "materialized_daily_review_evidence_ids": ["g1", "g2"],
        }
    ]
    evidence = {
        "g1": {
            "evidence_uid": "g1",
            "document_id": "d1",
            "source_type": "TSP_REPORT",
            "epistemic_status": "FORECAST",
            "attributes": {"anomaly_level": "NONE", "rock_mass_state": "岩体较破碎"},
        },
        "g2": {
            "evidence_uid": "g2",
            "document_id": "d2",
            "source_type": "TSP_REPORT",
            "epistemic_status": "FORECAST",
            "attributes": {"rock_mass_state": "岩体破碎"},
        },
    }
    mapping = {
        ("anomaly_level", "NONE"): {
            "dimension_name": "EXPLICIT_ANOMALY",
            "attention_value": 0.0,
            "mapping_id": "m1",
        },
        ("rock_mass_state", "岩体较破碎"): {
            "dimension_name": "ROCK_MASS_INTEGRITY",
            "attention_value": 0.25,
            "mapping_id": "m2",
        },
        ("rock_mass_state", "岩体破碎"): {
            "dimension_name": "ROCK_MASS_INTEGRITY",
            "attention_value": 0.75,
            "mapping_id": "m3",
        },
    }
    _, state_rows, _, _ = build_grs_for_snapshots(snapshots, evidence, mapping)
    assert state_rows[0]["grs"] == 0.375
    assert state_rows[0]["available_dimension_count"] == 2
