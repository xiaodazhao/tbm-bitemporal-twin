from tbm_twin.metrics.stage4a2_builder import compute_tie_aware_top_comparison


def test_overall_max_saturation_tie_is_threshold_inclusive_not_order_cut() -> None:
    official = {f"state_{index}": float(100 - index) for index in range(100)}
    variant = {f"state_{index}": 1.0 if index < 72 else 0.2 for index in range(100)}
    result = compute_tie_aware_top_comparison(official, variant, 0.10)
    assert result["nominal_top_count"] == 10
    assert result["variant_top_threshold"] == 1.0
    assert result["variant_threshold_inclusive_set_size"] == 72
    assert result["variant_boundary_tie_count"] == 72
    assert result["intersection_with_official"] == 10
    assert result["reference_recall"] == 1.0
    assert result["variant_precision"] == 10 / 72
