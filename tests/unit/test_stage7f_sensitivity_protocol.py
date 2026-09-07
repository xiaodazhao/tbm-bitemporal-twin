"""Stage7F-A sensitivity protocol regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tbm_twin.evaluation.stage7f_protocol import (
    CLAIM_CONTRACT_CONFIG,
    _arm_manifest,
    _baseline_identity_audit,
    _canonical,
    _implementation_parameter_usage,
    _load_baseline,
    _monitored_dates,
    _parameter_inventory,
    _protocol,
    _stable_hash,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def baseline() -> dict[str, object]:
    return _load_baseline(REPO_ROOT)


@pytest.fixture(scope="module")
def inventory(baseline: dict[str, object]) -> list[dict[str, object]]:
    return _parameter_inventory(baseline)


@pytest.fixture(scope="module")
def arms(baseline: dict[str, object]) -> list[dict[str, object]]:
    return _arm_manifest(baseline)


def test_01_parameter_inventory_maps_to_real_config(baseline: dict[str, object]) -> None:
    assert baseline == {
        "cell_size_m": 10.0,
        "minimum_baseline_sample_count": 30,
        "saturation_robust_z": 3.0,
    }


def test_02_cell_baseline_identity_is_10m(baseline: dict[str, object]) -> None:
    assert baseline["cell_size_m"] == 10.0


def test_02b_candidate_parameters_are_consumed_by_real_implementation() -> None:
    assert all(_implementation_parameter_usage(REPO_ROOT).values())


def test_03_cell_arms_are_exact_and_deterministic(arms: list[dict[str, object]]) -> None:
    actual = {
        float(str(row["parameter_value"])) for row in arms if row["parameter_id"] == "CELL_SIZE_M"
    }
    assert actual == {5.0, 20.0}
    # The shared baseline carries 10 m once rather than duplicating baseline executions.
    baseline_row = next(row for row in arms if row["is_baseline"])
    assert '"CELL_SIZE_M":10.0' in str(baseline_row["parameter_value"])


def test_04_rai_history_arms_require_verified_30_baseline(
    baseline: dict[str, object], arms: list[dict[str, object]]
) -> None:
    assert baseline["minimum_baseline_sample_count"] == 30
    values = {
        int(str(row["parameter_value"]))
        for row in arms
        if row["parameter_id"] == "RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT"
    }
    assert values == {20, 40}


def test_05_rai_saturation_arms_use_preregistered_2_3_4(
    baseline: dict[str, object], arms: list[dict[str, object]]
) -> None:
    assert baseline["saturation_robust_z"] == 3.0
    values = {
        float(str(row["parameter_value"]))
        for row in arms
        if row["parameter_id"] == "RAI_SATURATION_ROBUST_Z"
    }
    assert values == {2.0, 4.0}


def test_06_semantic_domain_parameters_are_excluded(
    inventory: list[dict[str, object]],
) -> None:
    assert not any(
        row["sensitivity_candidate"]
        for row in inventory
        if row["parameter_type"] == "SEMANTIC_DOMAIN_DEFINITION"
    )


def test_07_contract_rules_are_excluded(inventory: list[dict[str, object]]) -> None:
    assert not any(
        row["sensitivity_candidate"]
        for row in inventory
        if row["parameter_type"] == "NON_TUNABLE_CONTRACT_RULE"
    )


def test_08_claim_contract_is_bound_to_stage7e_final_tag() -> None:
    row = next(
        row
        for row in _baseline_identity_audit(REPO_ROOT)
        if row["path"] == CLAIM_CONTRACT_CONFIG.as_posix()
    )
    assert row["status"] == "PASS"
    assert row["expected_sha256"] == row["actual_sha256"]


def test_09_ofat_isolation_is_exact(arms: list[dict[str, object]]) -> None:
    baseline_rows = [row for row in arms if row["is_baseline"]]
    alternatives = [row for row in arms if not row["is_baseline"]]
    assert len(baseline_rows) == 1
    assert len(alternatives) == 6
    assert all(row["all_other_parameters_frozen"] for row in alternatives)
    assert all(row["changed_config_path"] for row in alternatives)


def test_10_no_llm_or_api_is_required(arms: list[dict[str, object]]) -> None:
    assert all(row["llm_required"] is False for row in arms)
    assert all(row["api_required"] is False for row in arms)


def test_11_arm_hashes_are_deterministic(baseline: dict[str, object]) -> None:
    assert _arm_manifest(baseline) == _arm_manifest(baseline)
    arms = _arm_manifest(baseline)
    assert len({row["arm_hash"] for row in arms}) == 7


def test_12_baseline_hash_is_deterministic() -> None:
    first = _baseline_identity_audit(REPO_ROOT)
    second = _baseline_identity_audit(REPO_ROOT)
    assert first == second
    assert _stable_hash(first) == _stable_hash(second)


def test_13_corpus_is_91_monitored_dates_with_calendar_gaps() -> None:
    dates = _monitored_dates(REPO_ROOT)
    assert len(dates) == 91
    assert dates[0] == "2023-09-15"
    assert dates[-1] == "2023-12-30"
    assert "2023-10-01" not in dates


def test_14_protocol_has_no_results_or_pass_threshold(
    baseline: dict[str, object], arms: list[dict[str, object]]
) -> None:
    dates = _monitored_dates(REPO_ROOT)
    identity = _baseline_identity_audit(REPO_ROOT)
    protocol = _protocol(baseline, arms, dates, identity)
    assert protocol["sensitivity_outcomes_generated"] is False
    assert protocol["interpretation"]["mode"] == (
        "DESCRIPTIVE_ROBUSTNESS_WITHOUT_PROGRAMMATIC_PASS_THRESHOLD"
    )
    assert protocol["full_factorial_design"] is False


def test_15_protocol_semantics_are_deterministic(
    baseline: dict[str, object], arms: list[dict[str, object]]
) -> None:
    dates = _monitored_dates(REPO_ROOT)
    identity = _baseline_identity_audit(REPO_ROOT)
    first = _protocol(baseline, arms, dates, identity)
    second = _protocol(baseline, arms, dates, identity)
    assert _canonical(first) == _canonical(second)
