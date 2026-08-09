from datetime import date

from tbm_twin.metrics.operational_baseline import build_causal_baselines


def test_same_day_response_is_not_baseline_history() -> None:
    baselines, _, leakage = build_causal_baselines(
        valid_dates=[date(2023, 1, 1)],
        responses=[
            {
                "evidence_id": "r1",
                "episode_id": "e1",
                "target_date": "2023-01-01",
                "channel_name": "advance_speed",
                "statistics": {"median": 10.0, "sample_count": 1},
            }
        ],
        eligibility={"r1": True},
        channels=["advance_speed"],
        min_sample_count=1,
        mad_scale_factor=1.4826,
        iqr_scale_divisor=1.349,
        alignment_id="test",
    )
    assert baselines[0]["sample_count"] == 0
    assert baselines[0]["baseline_status"] == "INSUFFICIENT_CAUSAL_HISTORY"
    assert leakage == []
