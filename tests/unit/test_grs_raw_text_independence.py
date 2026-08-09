from tbm_twin.metrics.grs import build_grs_for_snapshots


def test_grs_ignores_raw_text_when_structured_attributes_match() -> None:
    snapshot = {
        "bitemporal_version_id": "b1",
        "base_stage3a_state_version_id": "s1",
        "valid_date": "2023-01-01",
        "knowledge_time_start_local_date": "2023-01-01",
        "cell_id": "c1",
        "cell_scope_role": "DAILY_REVIEW_CELL",
        "materialized_daily_review_evidence_ids": ["g1"],
    }
    base = {
        "evidence_uid": "g1",
        "document_id": "d1",
        "source_type": "TSP_REPORT",
        "epistemic_status": "FORECAST",
        "attributes": {"anomaly_level": "HIGH"},
    }
    mapping = {
        ("anomaly_level", "HIGH"): {
            "dimension_name": "EXPLICIT_ANOMALY",
            "attention_value": 1.0,
            "mapping_id": "m1",
        }
    }
    _, first_rows, _, _ = build_grs_for_snapshots(
        [snapshot], {"g1": {**base, "raw_text": "未见明显反射异常"}}, mapping
    )
    _, second_rows, _, _ = build_grs_for_snapshots(
        [snapshot], {"g1": {**base, "raw_text": "完全不同的自由文本"}}, mapping
    )
    assert first_rows[0]["grs"] == second_rows[0]["grs"]
    assert (
        first_rows[0]["dimension_attention_values"] == second_rows[0]["dimension_attention_values"]
    )
    assert (
        first_rows[0]["grs_contributing_evidence_uids"]
        == second_rows[0]["grs_contributing_evidence_uids"]
    )
