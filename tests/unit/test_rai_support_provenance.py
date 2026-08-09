from tbm_twin.metrics.rai import build_rai_by_base_state


def _component(response_id: str, channel: str, abs_z: float | None) -> dict:
    return {
        "response_evidence_id": response_id,
        "channel_name": channel,
        "absolute_robust_z": abs_z,
        "episode_id": f"episode-{response_id}",
    }


def test_rpm_is_diagnostic_not_scalar_support() -> None:
    profile = {
        "base_stage3a_state_version_id": "s1",
        "response_profile_id": "p1",
        "valid_date": "2023-01-01",
        "cell_id": "c1",
        "response_evidence_ids": ["load1", "load2", "kin1", "kin2", "rpm1"],
    }
    rai_by_base, _, audit = build_rai_by_base_state(
        [profile],
        {
            "load1": _component("load1", "total_thrust", 1.0),
            "load2": _component("load2", "cutterhead_torque", 1.0),
            "kin1": _component("kin1", "advance_speed", 1.0),
            "kin2": _component("kin2", "penetration", 1.0),
            "rpm1": _component("rpm1", "cutterhead_rpm", 100.0),
        },
    )
    rai = rai_by_base["s1"]
    assert "rpm1" not in rai["scalar_support_response_evidence_ids"]
    assert "rpm1" not in rai["support_response_evidence_ids"]
    assert rai["diagnostic_response_evidence_ids"] == ["rpm1"]
    assert rai["excluded_scalar_response_reasons"]["rpm1"] == (
        "DIAGNOSTIC_ONLY_UNRESOLVED_MEASUREMENT_REGIME"
    )
    assert audit[0]["rpm_scalar_support_count"] == 0
