from tbm_twin.metrics.response_deviation import build_response_deviation_components


def test_response_deviation_uses_robust_scale_and_direction() -> None:
    components, by_response, _ = build_response_deviation_components(
        responses=[
            {
                "evidence_id": "r1",
                "episode_id": "e1",
                "target_date": "2023-01-02",
                "channel_name": "advance_speed",
                "statistics": {"median": 14.0, "sample_count": 2},
                "quality_grade": "A",
                "quality_flags": [],
                "spatial_scope_usable": True,
            }
        ],
        baselines=[
            {
                "baseline_id": "b1",
                "valid_date": "2023-01-02",
                "channel_name": "advance_speed",
                "sample_count": 30,
                "median": 10.0,
                "mad": 1.0,
                "iqr": 2.0,
                "robust_scale": 2.0,
                "robust_scale_basis": "MAD",
                "baseline_status": "AVAILABLE",
            }
        ],
        eligibility={"r1": True},
        coverage_by_response_id={"r1": "CELL_LINKED"},
        source_operational_manifest_hash="hash",
    )
    assert len(components) == 1
    assert by_response["r1"]["robust_z"] == 2.0
    assert by_response["r1"]["absolute_robust_z"] == 2.0
    assert by_response["r1"]["deviation_direction"] == "ABOVE_BASELINE"


def test_unavailable_baseline_keeps_robust_z_null() -> None:
    components, _, _ = build_response_deviation_components(
        responses=[
            {
                "evidence_id": "r1",
                "episode_id": "e1",
                "target_date": "2023-01-02",
                "channel_name": "advance_speed",
                "statistics": {"median": 14.0, "sample_count": 2},
                "quality_grade": "A",
                "quality_flags": [],
                "spatial_scope_usable": True,
            }
        ],
        baselines=[
            {
                "baseline_id": "b1",
                "valid_date": "2023-01-02",
                "channel_name": "advance_speed",
                "sample_count": 3,
                "median": 10.0,
                "mad": 1.0,
                "iqr": 2.0,
                "robust_scale": None,
                "robust_scale_basis": None,
                "baseline_status": "INSUFFICIENT_CAUSAL_HISTORY",
            }
        ],
        eligibility={"r1": True},
        coverage_by_response_id={"r1": "CELL_LINKED"},
        source_operational_manifest_hash="hash",
    )
    assert components[0]["component_status"] == "BASELINE_UNAVAILABLE"
    assert components[0]["robust_z"] is None
