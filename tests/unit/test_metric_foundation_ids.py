from datetime import date

from tbm_twin.metrics.operational_baseline import build_causal_baselines


def test_metric_foundation_ids_are_deterministic_without_generated_at() -> None:
    kwargs = {
        "valid_dates": [date(2023, 1, 2)],
        "responses": [
            {
                "evidence_id": "r1",
                "episode_id": "e1",
                "target_date": "2023-01-01",
                "channel_name": "advance_speed",
                "statistics": {"median": 10.0, "sample_count": 1},
            }
        ],
        "eligibility": {"r1": True},
        "channels": ["advance_speed"],
        "min_sample_count": 1,
        "mad_scale_factor": 1.4826,
        "iqr_scale_divisor": 1.349,
        "alignment_id": "alignment",
    }
    first, _, _ = build_causal_baselines(**kwargs)
    second, _, _ = build_causal_baselines(**kwargs)
    assert first[0]["baseline_id"] == second[0]["baseline_id"]
