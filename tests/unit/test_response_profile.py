from tbm_twin.metrics.response_profile import build_response_profiles


def test_response_profile_uses_only_stage3a_cell_links() -> None:
    profiles, _, coverage_audit, _ = build_response_profiles(
        state_versions=[
            {
                "state_version_id": "s1",
                "daily_state_id": "d1",
                "cell_id": "c1",
                "cell_scope_role": "DAILY_REVIEW_CELL",
                "valid_date": "2023-01-02",
                "episode_ids": ["e1"],
            }
        ],
        response_links=[
            {
                "state_version_id": "s1",
                "response_evidence_id": "r1",
                "link_id": "l1",
                "cell_id": "c1",
                "response_stat_scope": "EPISODE_LEVEL_SHARED",
                "trusted_overlap_kind": "INTERVAL",
            }
        ],
        components_by_response_id={
            "r1": {
                "component_id": "dc1",
                "response_evidence_id": "r1",
                "episode_id": "e1",
                "channel_name": "advance_speed",
                "robust_z": 1.0,
                "absolute_robust_z": 1.0,
                "component_status": "AVAILABLE",
            },
            "r_daily_only": {
                "component_id": "dc2",
                "response_evidence_id": "r_daily_only",
                "episode_id": "e2",
                "channel_name": "advance_speed",
                "robust_z": 3.0,
                "absolute_robust_z": 3.0,
                "component_status": "AVAILABLE",
            },
        },
        channels=["advance_speed", "total_thrust"],
        coverage_by_response_id={"r1": "CELL_LINKED", "r_daily_only": "LOCATED_POINT_DAILY_ONLY"},
        source_stage3a_manifest_hash="s3a",
        source_operational_manifest_hash="op",
    )
    assert profiles[0]["response_evidence_ids"] == ["r1"]
    assert profiles[0]["available_channel_count"] == 1
    assert coverage_audit[0]["status"] == "PASS"
