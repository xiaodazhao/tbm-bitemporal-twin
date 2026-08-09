from tbm_twin.metrics.response_deviation import build_response_deviation_components


def test_response_component_is_one_per_response_evidence() -> None:
    responses = [
        {
            "evidence_id": f"r{i}",
            "episode_id": "e1",
            "target_date": "2023-01-02",
            "channel_name": "advance_speed",
            "statistics": {"median": float(i), "sample_count": 2},
            "quality_grade": "A",
            "quality_flags": [],
            "spatial_scope_usable": True,
        }
        for i in range(3)
    ]
    components, by_response, _ = build_response_deviation_components(
        responses=responses,
        baselines=[
            {
                "baseline_id": "b1",
                "valid_date": "2023-01-02",
                "channel_name": "advance_speed",
                "sample_count": 30,
                "median": 0.0,
                "mad": 1.0,
                "iqr": 2.0,
                "robust_scale": 1.0,
                "robust_scale_basis": "MAD",
                "baseline_status": "AVAILABLE",
            }
        ],
        eligibility={f"r{i}": True for i in range(3)},
        coverage_by_response_id={f"r{i}": "CELL_LINKED" for i in range(3)},
        source_operational_manifest_hash="hash",
    )
    assert len(components) == 3
    assert set(by_response) == {"r0", "r1", "r2"}
    assert len({row["component_id"] for row in components}) == 3
