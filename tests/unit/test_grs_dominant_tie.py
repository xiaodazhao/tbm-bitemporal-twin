from tbm_twin.metrics.grs import build_grs_for_snapshots


def test_grs_dimension_tie_is_not_order_resolved() -> None:
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
            "attributes": {"anomaly_level": "HIGH"},
        },
        "g2": {
            "evidence_uid": "g2",
            "document_id": "d2",
            "source_type": "FACE_SKETCH",
            "epistemic_status": "OBSERVED",
            "attributes": {"rock_mass_state": "岩体破碎-极破碎"},
        },
    }
    mapping = {
        ("anomaly_level", "HIGH"): {
            "dimension_name": "EXPLICIT_ANOMALY",
            "attention_value": 1.0,
            "mapping_id": "m1",
        },
        ("rock_mass_state", "岩体破碎-极破碎"): {
            "dimension_name": "ROCK_MASS_INTEGRITY",
            "attention_value": 1.0,
            "mapping_id": "m2",
        },
    }
    _, state_rows, _, _ = build_grs_for_snapshots(snapshots, evidence, mapping)
    grs = state_rows[0]
    assert grs["dominant_geological_dimension"] is None
    assert grs["geological_dimension_attention_tie"] is True
    assert grs["co_dominant_geological_dimensions"] == [
        "EXPLICIT_ANOMALY",
        "ROCK_MASS_INTEGRITY",
    ]
