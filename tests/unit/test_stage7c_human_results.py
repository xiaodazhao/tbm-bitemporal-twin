from __future__ import annotations

import math

from tbm_twin.evaluation.stage7c_human_results import (
    _bootstrap_mean_ci,
    _fmt_p,
    _friedman,
    _holm_adjust,
    _mcnemar_exact,
    _wilcoxon_exact,
)


def test_bootstrap_mean_ci_is_deterministic_and_contains_mean() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    first = _bootstrap_mean_ci(values, 123, iterations=1000)
    second = _bootstrap_mean_ci(values, 123, iterations=1000)
    assert first == second
    assert first[0] <= 3.0 <= first[1]


def test_wilcoxon_exact_detects_consistent_positive_difference() -> None:
    p_value, effect = _wilcoxon_exact([1.0] * 10)
    assert math.isclose(p_value, 2 / (2**10))
    assert effect == 1.0


def test_wilcoxon_all_ties_is_neutral() -> None:
    assert _wilcoxon_exact([0.0, 0.0]) == (1.0, 0.0)


def test_friedman_detects_consistent_ordering() -> None:
    statistic, p_value, effect = _friedman([[1.0, 2.0, 3.0] for _ in range(12)])
    assert statistic == 24.0
    assert p_value < 0.001
    assert effect == 1.0


def test_holm_adjustment_is_monotone_in_rank_order() -> None:
    adjusted = _holm_adjust([0.01, 0.04, 0.03])
    assert adjusted == [0.03, 0.06, 0.06]


def test_mcnemar_exact_uses_discordant_pairs() -> None:
    assert _mcnemar_exact(8, 0) == 2 / (2**8)
    assert _mcnemar_exact(0, 0) == 1.0


def test_small_p_values_are_not_rendered_as_zero() -> None:
    assert _fmt_p(1e-9) == "1.000e-09"
