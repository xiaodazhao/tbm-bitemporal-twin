from tbm_twin.metrics.rai import bind_rai_to_bitemporal_versions


def test_same_base_state_versions_share_rai() -> None:
    rows = bind_rai_to_bitemporal_versions(
        [
            {
                "bitemporal_version_id": "b1",
                "base_stage3a_state_version_id": "s1",
                "valid_date": "2023-01-01",
                "knowledge_time_start_local_date": "2023-01-01",
                "cell_id": "c1",
                "cell_scope_role": "DAILY_REVIEW_CELL",
            },
            {
                "bitemporal_version_id": "b2",
                "base_stage3a_state_version_id": "s1",
                "valid_date": "2023-01-01",
                "knowledge_time_start_local_date": "2023-01-02",
                "cell_id": "c1",
                "cell_scope_role": "DAILY_REVIEW_CELL",
            },
        ],
        {
            "s1": {
                "response_profile_id": "p1",
                "rai": 0.5,
                "rai_status": "AVAILABLE",
                "rai_raw_deviation": 1.5,
                "dominant_response_family": "LOAD_RESPONSE",
                "family_attention_values": {"LOAD_RESPONSE": 0.5},
                "support_episode_count": 1,
                "support_response_evidence_count": 4,
                "support_response_evidence_ids": ["r1"],
                "quality_flags": [],
                "reason_codes": [],
            }
        },
    )
    assert rows[0]["rai"] == rows[1]["rai"] == 0.5
