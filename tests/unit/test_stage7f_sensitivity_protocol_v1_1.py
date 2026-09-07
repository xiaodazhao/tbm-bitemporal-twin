"""Stage7F-A v1.1 metric-semantics metadata correction tests."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

import pytest

from tbm_twin.evaluation.stage7f_protocol import (
    CLAIM_CONTRACT_CONFIG,
    STATE_METRIC_CONFIG,
    _arm_manifest,
    _baseline_identity_audit,
    _canonical,
    _load_baseline,
    _monitored_dates,
    _read_yaml,
    _sha256_file,
    _stable_hash,
)
from tbm_twin.evaluation.stage7f_protocol_v1_1 import (
    EXPECTED_STATE_METRIC_CONFIG_SHA256,
    _corrected_inventory,
    _corrected_protocol,
    _grci_numeric_sanity,
    _grs_state_numeric_sanity,
    _metric_semantics,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    return _load_baseline(REPO_ROOT)


@pytest.fixture(scope="module")
def metrics() -> dict[str, Any]:
    return _read_yaml(REPO_ROOT / STATE_METRIC_CONFIG)


def test_01_grci_inventory_reads_operator_from_actual_config(
    baseline: dict[str, Any], metrics: dict[str, Any]
) -> None:
    row = next(
        row
        for row in _corrected_inventory(baseline, metrics)
        if row["parameter_id"] == "GRCI_COUPLING_OPERATOR"
    )
    assert metrics["grci"]["operator"] == "NONPROBABILISTIC_CONJUNCTIVE_PRODUCT"
    assert row["current_value"] == "RAI * GRS when both available in DAILY_REVIEW_CELL_ONLY"
    assert row["sensitivity_candidate"] is False


def test_02_grci_inventory_never_reports_sqrt_product(
    baseline: dict[str, Any], metrics: dict[str, Any]
) -> None:
    inventory = _corrected_inventory(baseline, metrics)
    assert "sqrt(RAI * GRS)" not in _canonical(inventory)


def test_03_grci_numeric_sanity_is_product() -> None:
    value = _grci_numeric_sanity(0.315043708909733, 0.5416666666666666)
    assert math.isclose(value, 0.1706486756594387, rel_tol=0.0, abs_tol=1e-15)
    assert not math.isclose(value, math.sqrt(0.315043708909733 * 0.5416666666666666))


def test_04_grs_dimension_operator_reads_actual_config(metrics: dict[str, Any]) -> None:
    assert _metric_semantics(metrics)["GRS"]["dimension_operator"] == "max_mapped_attention"


def test_05_grs_state_operator_reads_actual_config(metrics: dict[str, Any]) -> None:
    assert (
        _metric_semantics(metrics)["GRS"]["state_operator"] == "mean_non_null_dimension_attention"
    )


def test_06_grs_sanity_uses_mean_across_non_null_dimensions() -> None:
    value = _grs_state_numeric_sanity([0.0, 0.6666666667, 0.75, 0.75, None, None])
    assert value is not None
    assert math.isclose(value, 0.541666666675, rel_tol=0.0, abs_tol=1e-15)
    assert value != 0.75


def test_07_all_seven_arm_identities_are_unchanged(baseline: dict[str, Any]) -> None:
    path = (
        REPO_ROOT
        / "artifacts/stage7f_sensitivity_protocol_v1_1/stage7f_v1_v1_1_arm_identity_audit.csv"
    )
    with path.open(encoding="utf-8", newline="") as handle:
        audit = list(csv.DictReader(handle))
    assert len(audit) == 7
    assert all(row["status"] == "PASS" for row in audit)


def test_08_sensitivity_values_and_baseline_are_unchanged(
    baseline: dict[str, Any], metrics: dict[str, Any]
) -> None:
    identity = _baseline_identity_audit(REPO_ROOT)
    protocol = _corrected_protocol(
        baseline,
        _arm_manifest(baseline),
        _monitored_dates(REPO_ROOT),
        identity,
        metrics,
    )
    assert baseline == {
        "cell_size_m": 10.0,
        "minimum_baseline_sample_count": 30,
        "saturation_robust_z": 3.0,
    }
    assert [row["values"] for row in protocol["parameters"]] == [
        [5.0, 10.0, 20.0],
        [20, 30, 40],
        [2.0, 3.0, 4.0],
    ]


def test_09_baseline_hashes_and_formal_protocol_audit_are_unchanged() -> None:
    assert _sha256_file(REPO_ROOT / STATE_METRIC_CONFIG) == EXPECTED_STATE_METRIC_CONFIG_SHA256
    assert all(row["status"] == "PASS" for row in _baseline_identity_audit(REPO_ROOT))
    path = REPO_ROOT / "artifacts/stage7f_sensitivity_protocol_v1_1/hard_check.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        hard_checks = list(csv.DictReader(handle))
    assert hard_checks
    assert all(row["status"] == "PASS" for row in hard_checks)


def test_10_claim_contract_is_unchanged() -> None:
    row = next(
        row
        for row in _baseline_identity_audit(REPO_ROOT)
        if row["path"] == CLAIM_CONTRACT_CONFIG.as_posix()
    )
    assert row["status"] == "PASS"


def test_11_protocol_has_no_api_llm_or_outcome(
    baseline: dict[str, Any], metrics: dict[str, Any]
) -> None:
    protocol = _corrected_protocol(
        baseline,
        _arm_manifest(baseline),
        _monitored_dates(REPO_ROOT),
        _baseline_identity_audit(REPO_ROOT),
        metrics,
    )
    assert protocol["api_calls"] == 0
    assert protocol["llm_calls"] == 0
    assert protocol["sensitivity_outcomes_generated"] is False


def test_12_deterministic_rebuild_identity(
    baseline: dict[str, Any], metrics: dict[str, Any]
) -> None:
    identity = _baseline_identity_audit(REPO_ROOT)
    args = (
        baseline,
        _arm_manifest(baseline),
        _monitored_dates(REPO_ROOT),
        identity,
        metrics,
    )
    assert _stable_hash(_corrected_protocol(*args)) == _stable_hash(_corrected_protocol(*args))
