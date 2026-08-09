from tbm_twin.metrics.rai import build_rai_by_base_state


def test_rai_requires_both_channels_in_each_scalar_family() -> None:
    profile = {
        "base_stage3a_state_version_id": "s1",
        "response_profile_id": "p1",
        "valid_date": "2023-01-01",
        "cell_id": "c1",
        "response_evidence_ids": ["r1", "r3", "r4"],
    }
    components = {
        "r1": {
            "response_evidence_id": "r1",
            "channel_name": "total_thrust",
            "absolute_robust_z": 1.0,
            "episode_id": "e1",
        },
        "r3": {
            "response_evidence_id": "r3",
            "channel_name": "advance_speed",
            "absolute_robust_z": 1.0,
            "episode_id": "e1",
        },
        "r4": {
            "response_evidence_id": "r4",
            "channel_name": "penetration",
            "absolute_robust_z": 1.0,
            "episode_id": "e1",
        },
    }
    rai_by_base, family_rows, _ = build_rai_by_base_state([profile], components)
    load = next(row for row in family_rows if row["response_family"] == "LOAD_RESPONSE")
    assert load["component_status"] == "INCOMPLETE_RESPONSE_FAMILY_SUPPORT"
    assert rai_by_base["s1"]["rai"] is None
    assert rai_by_base["s1"]["rai_status"] == "INCOMPLETE_RESPONSE_FAMILY_SUPPORT"
