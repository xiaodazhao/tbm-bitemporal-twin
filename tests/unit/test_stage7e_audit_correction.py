"""Targeted tests for the Stage7E-B v1.1 offline audit correction."""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tbm_twin.evaluation.stage7e_audit_correction import (
    OLD_COMMIT,
    OLD_TAG,
    build_stage7e_audit_correction,
    claim_id_differences,
    engineering_decimal_tokens_v2,
    fence_only_normalize,
    numeric_value_status_v2,
)
from tbm_twin.evaluation.stage7e_execution import _decimal_tokens

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def correction(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    output = tmp_path_factory.mktemp("stage7e_v1_1") / "correction"
    result = build_stage7e_audit_correction(
        ROOT,
        output_dir=output,
        generated_at="2026-08-26T00:00:00+00:00",
        create_audit_zip=False,
    )
    return {"output": output, "result": result}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_01_tokenizer_accepts_chinese_adjacent_number() -> None:
    assert engineering_decimal_tokens_v2("值为0.315") == {Decimal("0.315")}


def test_02_tokenizer_accepts_ascii_label_and_equals() -> None:
    assert engineering_decimal_tokens_v2("RAI=0.315") == {Decimal("0.315")}


def test_03_tokenizer_accepts_parenthesized_number() -> None:
    assert engineering_decimal_tokens_v2("值（0.315）") == {Decimal("0.315")}  # noqa: RUF001


def test_04_tokenizer_accepts_negative_number() -> None:
    assert engineering_decimal_tokens_v2("-0.25") == {Decimal("-0.25")}


def test_05_tokenizer_does_not_split_float() -> None:
    assert engineering_decimal_tokens_v2("0.315043708909733") == {Decimal("0.315043708909733")}


def test_06_tokenizer_accepts_english_adjacent_number() -> None:
    assert engineering_decimal_tokens_v2("value0.315") == {Decimal("0.315")}


def test_07_metric_value_exact_membership() -> None:
    value = {"metric_value": 0.315043708909733}
    assert numeric_value_status_v2(value, "值为0.315043708909733") == "PASS"


def test_08_v1_false_negative_is_repaired() -> None:
    assert Decimal("0.315") not in _decimal_tokens("值为0.315")
    assert Decimal("0.315") in engineering_decimal_tokens_v2("值为0.315")


def test_09_json_outer_fence_is_normalizable() -> None:
    result = fence_only_normalize('```json\n{"value": 1}\n```')
    assert result["outer_fence_exact_match"] is True
    assert result["inner_json_parse"] == "PASS"


def test_10_bare_outer_fence_is_normalizable() -> None:
    result = fence_only_normalize('```\n{"value": 1}\n```')
    assert result["outer_fence_exact_match"] is True
    assert result["inner_json_parse"] == "PASS"


def test_11_natural_language_before_fence_is_rejected() -> None:
    result = fence_only_normalize('answer:\n```json\n{"value": 1}\n```')
    assert result["outer_fence_exact_match"] is False


def test_12_natural_language_after_fence_is_rejected() -> None:
    result = fence_only_normalize('```json\n{"value": 1}\n```\nanswer')
    assert result["outer_fence_exact_match"] is False


def test_13_invalid_inner_json_is_not_recovered() -> None:
    result = fence_only_normalize('```json\n{"value":}\n```')
    assert result["outer_fence_exact_match"] is True
    assert result["inner_json_parse"] == "FAIL"


def test_14_fence_normalization_preserves_inner_characters() -> None:
    inner = '{"text":"值为0.315", "items":[1,2]}'
    result = fence_only_normalize(f"```json\n{inner}\n```")
    assert result["inner_text"] == inner
    assert result["content_character_change_count"] == 0


def test_15_duplicate_claim_ids_are_detected() -> None:
    missing, duplicate, unexpected = claim_id_differences(["a"], ["a", "a"])
    assert (missing, duplicate, unexpected) == ([], ["a"], [])


def test_16_unexpected_claim_ids_are_detected() -> None:
    missing, duplicate, unexpected = claim_id_differences(["a"], ["a", "b"])
    assert (missing, duplicate, unexpected) == ([], [], ["b"])


def test_17_missing_claim_ids_are_detected() -> None:
    missing, duplicate, unexpected = claim_id_differences(["a", "b"], ["a"])
    assert (missing, duplicate, unexpected) == (["b"], [], [])


def test_18_a3_strict_primary_is_unchanged(correction: dict[str, Any]) -> None:
    summary = _json(correction["output"] / "a3_strict_primary_summary.json")
    assert (summary["valid_chunk_count"], summary["mapping_complete_count"]) == (125, 828)
    assert summary["complete_task_count"] == 32


def test_19_a3_fence_only_recovery_is_exact(correction: dict[str, Any]) -> None:
    rows = _csv(correction["output"] / "a3_fence_only_normalization_audit.csv")
    assert len(rows) == 22
    assert all(row["normalization_status"] == "RECOVERED" for row in rows)
    assert all(row["content_character_change_count"] == "0" for row in rows)


def test_20_a3_secondary_endpoint_is_complete(correction: dict[str, Any]) -> None:
    summary = _json(correction["output"] / "a3_secondary_syntax_normalized_summary.json")
    assert (summary["secondary_valid_chunks"], summary["secondary_claim_mappings"]) == (
        147,
        989,
    )
    assert summary["secondary_complete_tasks"] == 45


def test_21_a3_numeric_result_is_164_exact(correction: dict[str, Any]) -> None:
    summary = _json(correction["output"] / "a3_secondary_syntax_normalized_summary.json")
    assert summary["numeric_claim_count"] == 164
    assert summary["numeric_exact_count"] == 164
    assert summary["numeric_drift_count"] == 0


def test_22_a3_scope_result_is_unchanged(correction: dict[str, Any]) -> None:
    summary = _json(correction["output"] / "a3_secondary_syntax_normalized_summary.json")
    assert summary["scope_status_distribution"] == {"NOT_EXPLICIT": 180, "PASS": 809}


def test_23_a3_and_a4_denominators_are_independent(correction: dict[str, Any]) -> None:
    a3 = _json(correction["output"] / "a3_secondary_syntax_normalized_summary.json")
    a4 = _json(correction["output"] / "a4_corrected_numeric_summary.json")
    assert a3["numeric_claim_count"] == 164
    assert a4["total_numeric_fact_lock_count"] == 171
    assert a3["numeric_claim_count"] != a4["total_numeric_fact_lock_count"]


def test_24_a4_factlock_identity_is_1022(correction: dict[str, Any]) -> None:
    summary = _json(correction["output"] / "a4_corrected_numeric_summary.json")
    assert summary["total_fact_lock_count"] == 1022


def test_25_a4_factlock_coverage_is_848_of_1022(correction: dict[str, Any]) -> None:
    summary = _json(correction["output"] / "a4_corrected_numeric_summary.json")
    assert (summary["used_fact_lock_count"], summary["omitted_fact_lock_count"]) == (848, 174)
    assert summary["fact_lock_coverage"] == pytest.approx(848 / 1022)


def test_26_a4_numeric_partition_is_171_162_9(correction: dict[str, Any]) -> None:
    summary = _json(correction["output"] / "a4_corrected_numeric_summary.json")
    total = summary["total_numeric_fact_lock_count"]
    used = summary["used_numeric_fact_lock_count"]
    omitted = summary["omitted_numeric_fact_lock_count"]
    assert (total, used, omitted) == (171, 162, 9)
    assert used + omitted == total


def test_27_a4_numeric_coverage_is_162_of_171(correction: dict[str, Any]) -> None:
    summary = _json(correction["output"] / "a4_corrected_numeric_summary.json")
    assert summary["numeric_fact_lock_coverage"] == pytest.approx(162 / 171)


def test_28_a4_numeric_omission_distribution(correction: dict[str, Any]) -> None:
    summary = _json(correction["output"] / "a4_corrected_numeric_summary.json")
    assert summary["omitted_numeric_task_distribution"] == {
        "stage7_main_task_002": 2,
        "stage7_main_task_011": 1,
        "stage7_main_task_047": 6,
    }


def test_29_a4_omitted_numeric_rows_are_not_drift(correction: dict[str, Any]) -> None:
    rows = _csv(correction["output"] / "a4_corrected_numeric_audit.csv")
    omitted = [row for row in rows if row["omitted"] == "True"]
    assert len(omitted) == 9
    assert all(row["numeric_status"] == "OMITTED_NOT_EVALUABLE" for row in omitted)
    assert all(row["v1_1_numeric_status"] == "NOT_EVALUABLE" for row in omitted)


def test_30_a4_used_numeric_values_are_all_exact(correction: dict[str, Any]) -> None:
    summary = _json(correction["output"] / "a4_corrected_numeric_summary.json")
    assert summary["used_numeric_exact_count"] == 162
    assert summary["used_numeric_drift_count"] == 0


def test_31_a4_scope_result_is_unchanged(correction: dict[str, Any]) -> None:
    summary = _json(correction["output"] / "a4_corrected_numeric_summary.json")
    assert summary["scope_status_distribution"] == {
        "NOT_EVALUABLE": 2,
        "NOT_EXPLICIT": 108,
        "PASS": 43,
    }


def test_32_all_226_raw_responses_are_unchanged(correction: dict[str, Any]) -> None:
    rows = _csv(correction["output"] / "raw_response_identity_audit.csv")
    assert len(rows) == 226
    assert all(row["raw_hash_match"] == "True" for row in rows)


def test_33_provider_and_request_identities_are_unchanged(correction: dict[str, Any]) -> None:
    rows = _csv(correction["output"] / "raw_response_identity_audit.csv")
    assert all(row["provider_response_id_changed"] == "False" for row in rows)
    assert all(row["request_payload_hash_changed"] == "False" for row in rows)


def test_34_old_tag_and_artifact_are_unchanged(correction: dict[str, Any]) -> None:
    method = _json(correction["output"] / "method_version.json")
    rows = _csv(correction["output"] / "old_execution_artifact_identity_audit.csv")
    assert method["old_execution_tag"] == OLD_TAG
    assert method["old_execution_commit"] == OLD_COMMIT
    assert all(row["identity_match"] == "True" for row in rows)


def test_35_hard_checks_all_pass(correction: dict[str, Any]) -> None:
    rows = _csv(correction["output"] / "hard_check.csv")
    assert rows
    assert all(row["status"] == "PASS" for row in rows)


def test_36_correction_makes_no_api_or_llm_calls(correction: dict[str, Any]) -> None:
    method = _json(correction["output"] / "method_version.json")
    assert method["new_api_calls"] == 0
    assert method["new_llm_calls"] == 0
    assert method["new_deepseek_calls"] == 0


def test_37_offline_replay_is_deterministic(correction: dict[str, Any]) -> None:
    method = _json(correction["output"] / "method_version.json")
    assert correction["result"]["semantic_replay_hash"] == method["semantic_replay_hash"]
