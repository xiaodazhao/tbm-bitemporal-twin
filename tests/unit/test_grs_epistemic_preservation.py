from tbm_twin.metrics.grs import build_grs_for_snapshots


def test_grs_counts_forecast_without_relabeling_epistemic_status() -> None:
    snapshot = {
        "bitemporal_version_id": "b1",
        "base_stage3a_state_version_id": "s1",
        "valid_date": "2023-01-01",
        "knowledge_time_start_local_date": "2023-01-01",
        "cell_id": "c1",
        "cell_scope_role": "DAILY_REVIEW_CELL",
        "materialized_daily_review_evidence_ids": ["g1"],
    }
    evidence = {
        "g1": {
            "evidence_uid": "g1",
            "document_id": "d1",
            "source_type": "SONIC_FORECAST",
            "epistemic_status": "FORECAST",
            "attributes": {"anomaly_level": "NONE"},
        }
    }
    mapping = {
        ("anomaly_level", "NONE"): {
            "dimension_name": "EXPLICIT_ANOMALY",
            "attention_value": 0.0,
            "mapping_id": "m1",
        }
    }
    components, state_rows, _, _ = build_grs_for_snapshots([snapshot], evidence, mapping)
    anomaly = next(row for row in components if row["dimension_name"] == "EXPLICIT_ANOMALY")
    assert anomaly["supporting_epistemic_statuses"] == ["FORECAST"]
    assert state_rows[0]["forecast_support_count"] == 1
    assert state_rows[0]["observed_support_count"] == 0
