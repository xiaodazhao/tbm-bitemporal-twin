"""Stage7F-B v1.1 final interpretation tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from tbm_twin.evaluation.stage7f_final_interpretation import (
    CLAIM_TABLES,
    METRIC_TABLES,
    _comparison_unchanged,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FORMAL = REPO_ROOT / "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation"


def _csv(name: str) -> list[dict[str, str]]:
    with (FORMAL / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _json(name: str) -> dict[str, Any]:
    value = json.loads((FORMAL / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def native() -> list[dict[str, Any]]:
    return list(_json("freeze_manifest.json")["native_quality_gate_rows"])


@pytest.fixture(scope="module")
def identity() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = _json("freeze_manifest.json")
    return list(_csv("old_stage7f_b_identity_audit.csv")), {
        "listed_file_count": manifest["old_output_listed_file_count"],
        "mismatch_count": manifest["old_output_hash_mismatch_count"],
    }


def _by_arm(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["arm_id"]: row for row in rows}


def test_01_five_m_resolution_audit_is_clean(native: list[dict[str, Any]]) -> None:
    row = _by_arm(native)["cell_size_m_5"]
    assert row["scope_role_conflicts"] == 0
    assert row["point_missing_or_duplicate"] == 0
    assert row["interval_overlap_mismatch"] == 0
    assert row["native_quality_gate_status"] == "PASS"


def test_02_baseline_resolution_audit_is_clean(native: list[dict[str, Any]]) -> None:
    row = _by_arm(native)["stage7f_baseline"]
    assert row["native_quality_gate_status"] == "PASS"
    assert row["method_validity_status"] == "VALID_BASELINE"


def test_03_twenty_m_role_conflicts_are_reconstructed(native: list[dict[str, Any]]) -> None:
    row = _by_arm(native)["cell_size_m_20"]
    assert row["scope_role_conflicts"] == 90
    assert row["daily_review_vs_local_background_conflicts"] == 49
    assert row["daily_review_vs_forward_attention_conflicts"] == 41


def test_04_twenty_m_point_undercoverage_is_reconstructed(native: list[dict[str, Any]]) -> None:
    assert _by_arm(native)["cell_size_m_20"]["point_missing_or_duplicate"] == 23


def test_05_twenty_m_interval_undercoverage_is_reconstructed(
    native: list[dict[str, Any]],
) -> None:
    assert _by_arm(native)["cell_size_m_20"]["interval_overlap_mismatch"] == 76


def test_06_twenty_m_is_a_stress_test_boundary(native: list[dict[str, Any]]) -> None:
    row = _by_arm(native)["cell_size_m_20"]
    assert row["execution_status"] == "SUCCESS"
    assert row["method_validity_status"] == "COARSE_RESOLUTION_VALIDITY_BOUNDARY_EXCEEDED"
    assert row["interpretation_scope"] == "COARSE_RESOLUTION_STRESS_TEST"
    assert row["native_quality_gate_status"] == "FAIL_RESOLUTION_VALIDITY"


def test_07_twenty_m_execution_is_retained(native: list[dict[str, Any]]) -> None:
    row = _by_arm(native)["cell_size_m_20"]
    assert row["sensitivity_adapter_continued_execution"] is True


def test_08_twenty_m_exposure_remains_14180(native: list[dict[str, Any]]) -> None:
    rows = _by_arm(_csv("cell_size_resolution_validity_summary.csv"))
    assert float(rows["cell_size_m_20"]["evaluated_cell_length_m"]) == 14180.0
    assert rows["cell_size_m_20"]["denominator_caveat"] != "NONE"


def test_09_five_and_ten_m_exposure_remains_13220(native: list[dict[str, Any]]) -> None:
    rows = _by_arm(_csv("cell_size_resolution_validity_summary.csv"))
    assert float(rows["cell_size_m_5"]["evaluated_cell_length_m"]) == 13220.0
    assert float(rows["stage7f_baseline"]["evaluated_cell_length_m"]) == 13220.0


def test_10_z2_actual_saturation_is_two() -> None:
    rows = _by_arm(_csv("rai_saturation_metadata_consistency_audit.csv"))
    assert float(rows["rai_saturation_robust_z_2"]["actual_saturation_robust_z"]) == 2.0


def test_11_z4_actual_saturation_is_four() -> None:
    rows = _by_arm(_csv("rai_saturation_metadata_consistency_audit.csv"))
    assert float(rows["rai_saturation_robust_z_4"]["actual_saturation_robust_z"]) == 4.0


def test_12_legacy_divided_by_three_label_is_detected() -> None:
    rows = _csv("rai_saturation_metadata_consistency_audit.csv")
    assert all(row["legacy_operator_label"] == "min_raw_deviation_divided_by_3" for row in rows)
    assert all(row["legacy_label_used_as_authoritative_parameter"] == "False" for row in rows)


def test_13_saturation_results_are_unchanged(
    identity: tuple[list[dict[str, Any]], dict[str, Any]],
) -> None:
    rows, _ = identity
    names = tuple(name for name in METRIC_TABLES + CLAIM_TABLES if "saturation" in name)
    assert _comparison_unchanged(rows, names)


def test_14_all_old_stage7f_outputs_match_hash_manifest(
    identity: tuple[list[dict[str, Any]], dict[str, Any]],
) -> None:
    rows, verification = identity
    assert verification["listed_file_count"] == 518
    assert verification["mismatch_count"] == 0
    assert all(row["status"] == "PASS" for row in rows)


def test_15_replay_hash_identity(
    identity: tuple[list[dict[str, Any]], dict[str, Any]],
) -> None:
    rows, _ = identity
    replay = next(
        row for row in rows if row["check_name"] == "FROZEN_FILE_deterministic_replay_audit.csv"
    )
    assert replay["status"] == "PASS"


def test_16_no_api_or_llm(native: list[dict[str, Any]]) -> None:
    hard = _csv("hard_check.csv")
    assert all(row["status"] == "PASS" for row in hard)
    assert {row["check_name"] for row in hard} >= {
        "API_CALLS_ZERO",
        "LLM_CALLS_ZERO",
        "DEEPSEEK_CALLS_ZERO",
    }


def test_17_final_summary_has_no_automatic_robustness_classification(
    native: list[dict[str, Any]],
) -> None:
    summary = _json("stage7f_final_machine_summary.json")
    assert summary["automatic_robustness_classification"] == "NOT_PERFORMED"
    assert summary["interpretation_boundaries"]["no_best_parameter_selected"] is True


def test_18_summary_preserves_all_three_parameter_families(
    native: list[dict[str, Any]],
) -> None:
    summary = _json("stage7f_final_machine_summary.json")
    assert set(summary["cell_size"]) == {"5m", "10m", "20m"}
    assert set(summary["history"]) >= {"20", "30", "40"}
    assert set(summary["saturation"]) >= {"2", "3", "4"}
