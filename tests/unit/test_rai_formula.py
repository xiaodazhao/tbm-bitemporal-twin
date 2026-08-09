from tbm_twin.metrics.rai import RAI_SATURATION_ROBUST_Z, build_rai_by_base_state


def _component(response_id: str, channel: str, abs_z: float | None) -> dict:
    return {
        "response_evidence_id": response_id,
        "channel_name": channel,
        "absolute_robust_z": abs_z,
        "episode_id": f"episode-{response_id}",
    }


def test_rai_uses_family_max_and_exact_saturation() -> None:
    profile = {
        "base_stage3a_state_version_id": "s1",
        "response_profile_id": "p1",
        "valid_date": "2023-01-01",
        "cell_id": "c1",
        "response_evidence_ids": ["r1", "r2", "r3", "r4"],
    }
    components = {
        "r1": _component("r1", "total_thrust", 1.0),
        "r2": _component("r2", "cutterhead_torque", 4.0),
        "r3": _component("r3", "advance_speed", 0.5),
        "r4": _component("r4", "penetration", 0.7),
    }
    rai_by_base, family_rows, _ = build_rai_by_base_state([profile], components)
    assert RAI_SATURATION_ROBUST_Z == 3.0
    assert rai_by_base["s1"]["rai"] == 1.0
    assert rai_by_base["s1"]["rai_raw_deviation"] == 4.0
    assert rai_by_base["s1"]["dominant_response_family"] == "LOAD_RESPONSE"
    assert {row["response_family"] for row in family_rows} == {
        "LOAD_RESPONSE",
        "ADVANCE_KINEMATIC_RESPONSE",
    }
