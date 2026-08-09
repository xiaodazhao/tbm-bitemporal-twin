from datetime import date

from tbm_twin.metrics.operational_baseline import (
    assess_mechanical_eligibility,
    build_causal_baselines,
)


def _response(response_id: str, target_date: str, channel: str, median: float) -> dict:
    return {
        "evidence_id": response_id,
        "episode_id": f"episode-{response_id}",
        "target_date": target_date,
        "channel_name": channel,
        "statistics": {"median": median, "sample_count": 10},
        "core_observation_refs": ["obs-1"],
        "quality_flags": [],
        "quality_components": {},
        "spatial_scope_usable": False,
    }


def test_causal_baseline_uses_prior_samples_and_robust_stats() -> None:
    responses = [
        _response("r1", "2023-01-01", "advance_speed", 10.0),
        _response("r2", "2023-01-02", "advance_speed", 12.0),
        _response("r3", "2023-01-03", "advance_speed", 14.0),
    ]
    eligibility, audit, _ = assess_mechanical_eligibility(
        responses, {"advance_speed"}, set(), set()
    )
    baselines, sample_audit, leakage = build_causal_baselines(
        valid_dates=[date(2023, 1, 1), date(2023, 1, 2), date(2023, 1, 3)],
        responses=responses,
        eligibility=eligibility,
        channels=["advance_speed"],
        min_sample_count=1,
        mad_scale_factor=1.4826,
        iqr_scale_divisor=1.349,
        alignment_id="test_alignment",
    )
    assert all(row["mechanically_eligible"] for row in audit)
    assert leakage == []
    assert [row["sample_count"] for row in baselines] == [0, 1, 2]
    assert baselines[1]["median"] == 10.0
    assert sample_audit[2]["latest_source_date"] == "2023-01-02"


def test_spatially_unusable_response_can_remain_mechanically_eligible() -> None:
    responses = [_response("r1", "2023-01-01", "advance_speed", 10.0)]
    responses[0]["spatial_scope_usable"] = False
    eligibility, audit, _ = assess_mechanical_eligibility(
        responses, {"advance_speed"}, set(), set()
    )
    assert eligibility["r1"] is True
    assert audit[0]["spatial_scope_usable"] is False
