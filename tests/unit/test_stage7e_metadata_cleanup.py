"""Tests for Stage7E-B v1.1a final machine-result metadata cleanup."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from tbm_twin.evaluation.stage7e_metadata_cleanup import (
    CORRECTION_COMMIT,
    CORRECTION_TAG,
    OLD_COMMIT,
    OLD_TAG,
    _unqualified_stale_149_count,
    build_stage7e_metadata_cleanup,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def cleanup(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    output = tmp_path_factory.mktemp("stage7e_v1_1a") / "metadata"
    result = build_stage7e_metadata_cleanup(
        ROOT,
        output_dir=output,
        generated_at="2026-08-26T00:00:00+00:00",
        create_audit_zip=False,
    )
    return {"output": output, "result": result}


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_01_strict_numeric_denominator_derives_149(cleanup: dict[str, Any]) -> None:
    summary = _json(cleanup["output"] / "stage7e_final_machine_result_summary.json")
    assert summary["a3_corrected_strict_numeric_audit"]["numeric_claims"] == 149


def test_02_strict_numeric_exact_is_149(cleanup: dict[str, Any]) -> None:
    summary = _json(cleanup["output"] / "stage7e_final_machine_result_summary.json")
    assert summary["a3_corrected_strict_numeric_audit"]["numeric_exact"] == 149


def test_03_strict_numeric_drift_is_zero(cleanup: dict[str, Any]) -> None:
    summary = _json(cleanup["output"] / "stage7e_final_machine_result_summary.json")
    assert summary["a3_corrected_strict_numeric_audit"]["numeric_drift"] == 0


def test_04_strict_numeric_rows_are_recomputed(cleanup: dict[str, Any]) -> None:
    rows = _csv(cleanup["output"] / "a3_corrected_strict_numeric_audit.csv")
    assert len(rows) == 149
    assert all(row["numeric_status"] == "PASS" for row in rows)
    assert all(row["evaluator"] == "engineering_decimal_tokens_v2" for row in rows)


def test_05_primary_protocol_endpoint_is_unchanged(cleanup: dict[str, Any]) -> None:
    summary = _json(cleanup["output"] / "stage7e_final_machine_result_summary.json")
    protocol = summary["a3_primary_protocol_compliance"]
    assert (protocol["valid_chunks"], protocol["claim_mappings"], protocol["complete_tasks"]) == (
        125,
        828,
        32,
    )


def test_06_secondary_numeric_result_is_164_exact(cleanup: dict[str, Any]) -> None:
    summary = _json(cleanup["output"] / "stage7e_final_machine_result_summary.json")
    secondary = summary["a3_secondary_fence_only"]
    assert (
        secondary["numeric_claims"],
        secondary["numeric_exact"],
        secondary["numeric_drift"],
    ) == (
        164,
        164,
        0,
    )


def test_07_legacy_149_exists_only_as_superseded(cleanup: dict[str, Any]) -> None:
    legacy = _json(cleanup["output"] / "legacy_superseded_result_registry.json")
    assert legacy["legacy_v1_reported_numeric_drift_count"] == 149
    assert legacy["legacy_v1_numeric_result_status"] == "SUPERSEDED_BY_V1_1_CORRECTED_NUMERIC_AUDIT"


def test_08_current_summary_has_no_unqualified_149_drift(cleanup: dict[str, Any]) -> None:
    summary = _json(cleanup["output"] / "stage7e_final_machine_result_summary.json")
    freeze = _json(cleanup["output"] / "freeze_manifest.json")
    assert _unqualified_stale_149_count(summary) == 0
    assert _unqualified_stale_149_count(freeze) == 0


def test_09_a4_counts_are_unchanged(cleanup: dict[str, Any]) -> None:
    summary = _json(cleanup["output"] / "stage7e_final_machine_result_summary.json")
    a4 = summary["a4"]
    assert (a4["total_fact_locks"], a4["used_fact_locks"]) == (1022, 848)
    assert (a4["total_numeric_fact_locks"], a4["used_numeric_fact_locks"]) == (171, 162)
    assert a4["omitted_numeric_fact_locks"] == 9


def test_10_a4_numeric_results_are_token_presence_only(cleanup: dict[str, Any]) -> None:
    summary = _json(cleanup["output"] / "stage7e_final_machine_result_summary.json")
    a4 = summary["a4"]
    assert a4["referenced_numeric_token_exact"] == 162
    assert a4["referenced_numeric_token_drift"] == 0
    assert a4["semantic_correctness_inference"] == "PROHIBITED"


def test_11_a4_interpretation_uses_section_level_wording(cleanup: dict[str, Any]) -> None:
    text = (cleanup["output"] / "STAGE7E_FINAL_RESULT_SEMANTICS.md").read_text(encoding="utf-8")
    assert "section text that declared use of the" in text
    assert "FactLock ID" in text
    assert "does not show that all facts" in text


def test_12_a1_and_a2_final_metadata(cleanup: dict[str, Any]) -> None:
    summary = _json(cleanup["output"] / "stage7e_final_machine_result_summary.json")
    assert summary["a1"]["execution_status"] == "NOT_EXECUTABLE"
    assert summary["a2"] == {"affected_tasks": 24, "target_sections": 31}


def test_13_old_v1_and_v1_1_identities_are_unchanged(cleanup: dict[str, Any]) -> None:
    method = _json(cleanup["output"] / "method_version.json")
    rows = _csv(cleanup["output"] / "old_v1_1_correction_identity_audit.csv")
    assert (method["source_execution_tag"], method["source_execution_commit"]) == (
        OLD_TAG,
        OLD_COMMIT,
    )
    assert (method["source_corrected_audit_tag"], method["source_corrected_audit_commit"]) == (
        CORRECTION_TAG,
        CORRECTION_COMMIT,
    )
    assert all(row["identity_match"] == "True" for row in rows)


def test_14_all_226_raw_responses_are_unchanged(cleanup: dict[str, Any]) -> None:
    rows = _csv(cleanup["output"] / "raw_response_identity_audit.csv")
    assert len(rows) == 226
    assert all(row["raw_hash_match"] == "True" for row in rows)
    assert all(row["provider_response_id_changed"] == "False" for row in rows)
    assert all(row["request_payload_hash_changed"] == "False" for row in rows)


def test_15_no_api_or_llm_calls(cleanup: dict[str, Any]) -> None:
    summary = _json(cleanup["output"] / "stage7e_final_machine_result_summary.json")
    assert summary["new_api_calls"] == 0
    assert summary["new_llm_calls"] == 0
    assert summary["new_deepseek_calls"] == 0


def test_16_all_hard_checks_pass(cleanup: dict[str, Any]) -> None:
    rows = _csv(cleanup["output"] / "hard_check.csv")
    assert rows
    assert all(row["status"] == "PASS" for row in rows)


def test_17_authoritative_summary_role_is_explicit(cleanup: dict[str, Any]) -> None:
    summary = _json(cleanup["output"] / "stage7e_final_machine_result_summary.json")
    assert summary["summary_role"] == "AUTHORITATIVE_STAGE7E_FINAL_MACHINE_RESULT_SUMMARY"


def test_18_metadata_replay_is_deterministic(cleanup: dict[str, Any]) -> None:
    method = _json(cleanup["output"] / "method_version.json")
    assert cleanup["result"]["semantic_replay_hash"] == method["semantic_replay_hash"]
