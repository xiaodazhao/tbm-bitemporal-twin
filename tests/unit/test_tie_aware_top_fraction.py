from tbm_twin.metrics.stage4a2_builder import (
    compute_tie_aware_top_comparison,
    compute_tie_aware_top_fraction,
)


def test_threshold_inclusive_top_fraction_keeps_all_boundary_ties() -> None:
    records = {f"id_{index}": 1.0 for index in range(19)}
    records.update({f"low_{index}": 0.1 for index in range(181)})
    top = compute_tie_aware_top_fraction(records, 0.10)
    assert top["nominal_top_count"] == 20
    assert top["top_threshold"] == 0.1
    assert top["threshold_inclusive_set_size"] == 200
    assert top["boundary_tie_count"] == 181


def test_tie_aware_recall_precision_and_jaccard() -> None:
    reference = {"a": 1.0, "b": 0.9, "c": 0.9, "d": 0.1}
    variant = {"a": 1.0, "b": 0.8, "x": 0.8, "d": 0.1}
    result = compute_tie_aware_top_comparison(reference, variant, 0.50)
    assert result["reference_threshold_inclusive_set_size"] == 3
    assert result["variant_threshold_inclusive_set_size"] == 3
    assert result["intersection_with_official"] == 2
    assert result["union_with_official"] == 4
    assert result["reference_recall"] == 2 / 3
    assert result["variant_precision"] == 2 / 3
    assert result["jaccard"] == 0.5
