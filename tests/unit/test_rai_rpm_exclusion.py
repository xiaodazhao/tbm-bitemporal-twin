from tbm_twin.metrics.rai import build_rai_by_base_state


def test_rpm_component_is_not_read_for_scalar_rai() -> None:
    profile = {
        "base_stage3a_state_version_id": "s1",
        "response_profile_id": "p1",
        "valid_date": "2023-12-01",
        "cell_id": "c1",
        "response_evidence_ids": ["rpm"],
    }
    components = {
        "rpm": {
            "response_evidence_id": "rpm",
            "channel_name": "cutterhead_rpm",
            "absolute_robust_z": 200.0,
            "episode_id": "e1",
        }
    }
    rai_by_base, family_rows, _ = build_rai_by_base_state([profile], components)
    assert all(row["response_family"] != "ROTATION_DIAGNOSTIC" for row in family_rows)
    assert rai_by_base["s1"]["rai"] is None
