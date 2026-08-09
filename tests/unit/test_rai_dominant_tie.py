from tbm_twin.metrics.rai import build_rai_by_base_state


def _component(response_id: str, channel: str, abs_z: float) -> dict:
    return {
        "response_evidence_id": response_id,
        "channel_name": channel,
        "absolute_robust_z": abs_z,
        "episode_id": f"episode-{response_id}",
    }


def test_rai_attention_tie_is_not_order_resolved() -> None:
    profile = {
        "base_stage3a_state_version_id": "s1",
        "response_profile_id": "p1",
        "valid_date": "2023-01-01",
        "cell_id": "c1",
        "response_evidence_ids": ["r1", "r2", "r3", "r4"],
    }
    rai_by_base, _, _ = build_rai_by_base_state(
        [profile],
        {
            "r1": _component("r1", "total_thrust", 3.5),
            "r2": _component("r2", "cutterhead_torque", 3.5),
            "r3": _component("r3", "advance_speed", 4.0),
            "r4": _component("r4", "penetration", 4.0),
        },
    )
    rai = rai_by_base["s1"]
    assert rai["rai"] == 1.0
    assert rai["dominant_response_family"] is None
    assert rai["response_family_attention_tie"] is True
    assert rai["co_dominant_response_families"] == [
        "ADVANCE_KINEMATIC_RESPONSE",
        "LOAD_RESPONSE",
    ]
    assert rai["raw_deviation_dominant_family"] == "ADVANCE_KINEMATIC_RESPONSE"
