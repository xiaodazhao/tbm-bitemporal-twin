"""Stage7E-B frozen execution and deterministic-audit tests."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from tbm_twin.evaluation.stage7e_execution import (
    EXPECTED_ARM_COUNTS,
    NO_OUTPUT_TASKS,
    FrozenDeepSeekProvider,
    _analysis_inputs,
    _analyze_a2,
    _analyze_a3,
    _analyze_a4,
    _attempt_record,
    _explicit_insufficiency_class,
    _human_deferred_rows,
    _load_attempts,
    _request_input_payload,
    _scope_union_status,
    _termination,
    build_execution_order,
    preflight_stage7e,
    replay_stage7e,
    run_stage7e,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


class MockFrozenProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def request(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(str(request["request_id"]))
        payload = _request_input_payload(request)
        arm = str(request["arm_internal"])
        if arm == "A2_NO_ARCHITECTURAL_ABSTENTION":
            response = {
                "section_id": payload["section_id"],
                "text": "当前指标不可用。",
                "used_context_ids": [
                    row["context_id"] for row in payload["engineering_context_items"]
                ],
            }
        elif arm == "A3_NO_FACTLOCK":
            response = {
                "realizations": [
                    {"claim_id": row["claim_id"], "sentence": f"工程句子 {row['claim_id']}"}
                    for row in payload["claims"]
                ]
            }
        else:
            response = {
                "sections": [
                    {
                        "section_name": "工程事实",
                        "text": "仅依据锁定事实形成的文本。",
                        "used_fact_lock_ids": [row["fact_lock_id"] for row in payload["facts"]],
                    }
                ]
            }
        raw_text = json.dumps(response, ensure_ascii=False)
        raw_payload = {
            "id": f"mock_{request['request_id']}",
            "model": "deepseek-v4-flash",
            "status": "completed",
            "output": [],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        return _attempt_record(
            request,
            started_at="2026-08-26T00:00:00+00:00",
            finished_at="2026-08-26T00:00:01+00:00",
            latency_ms=1000,
            transport_success=True,
            transport_status="SUCCESS",
            provider_response_id=raw_payload["id"],
            provider_model=raw_payload["model"],
            raw_payload=raw_payload,
            raw_text=raw_text,
            termination="NORMAL_COMPLETION",
            usage=raw_payload["usage"],
            error_type=None,
            error_message=None,
        )


@pytest.fixture(scope="module")
def preflight() -> dict[str, Any]:
    return preflight_stage7e(REPO_ROOT, require_credential=False)


@pytest.fixture(scope="module")
def mock_execution(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    output = tmp_path_factory.mktemp("stage7e") / "execution"
    provider = MockFrozenProvider()
    summary = run_stage7e(
        REPO_ROOT,
        execute=True,
        output_dir=output,
        provider=provider,  # type: ignore[arg-type]
        create_audit_zip=False,
    )
    inputs = _analysis_inputs(
        REPO_ROOT, preflight_stage7e(REPO_ROOT, require_credential=False)["requests"]
    )
    return {
        "output": output,
        "provider": provider,
        "summary": summary,
        "attempts": _load_attempts(output),
        "inputs": inputs,
    }


def _attempt_for_arm(mock_execution: dict[str, Any], arm: str) -> dict[str, Any]:
    return next(row for row in mock_execution["attempts"] if row["arm_internal"] == arm)


def test_01_frozen_request_hashes_are_exact(preflight: dict[str, Any]) -> None:
    assert preflight["status"] == "PASS"
    assert len(preflight["request_integrity"]) == 226
    assert all(row["status"] == "PASS" for row in preflight["request_integrity"])


def test_02_execution_order_is_deterministic(preflight: dict[str, Any]) -> None:
    first = build_execution_order(preflight["requests"])
    second = build_execution_order(list(reversed(preflight["requests"])))
    assert first == second
    assert [row["execution_index"] for row in first] == list(range(226))


def test_03_one_attempt_per_frozen_request(mock_execution: dict[str, Any]) -> None:
    attempts = mock_execution["attempts"]
    assert len(attempts) == 226
    assert set(Counter(row["request_id"] for row in attempts).values()) == {1}


def test_04_a1_has_no_request_or_attempt(mock_execution: dict[str, Any]) -> None:
    assert not any(row["arm_internal"].startswith("A1_") for row in mock_execution["attempts"])
    assert mock_execution["summary"]["a1_api_calls"] == 0


def test_05_p_has_no_new_request_or_attempt(mock_execution: dict[str, Any]) -> None:
    assert not any(row["arm_internal"] == "P_FULL" for row in mock_execution["attempts"])
    assert mock_execution["summary"]["p_output_availability"] == "45/48"


def test_06_every_request_uses_same_provider_config(preflight: dict[str, Any]) -> None:
    assert {
        json.dumps(row["inference_config"], sort_keys=True) for row in preflight["requests"]
    } == {json.dumps(preflight["provider_config"], sort_keys=True)}


def test_07_a2_executes_exactly_31_requests(mock_execution: dict[str, Any]) -> None:
    assert Counter(row["arm_internal"] for row in mock_execution["attempts"]) == EXPECTED_ARM_COUNTS


def test_08_a2_validates_returned_section_id(mock_execution: dict[str, Any]) -> None:
    attempt = dict(_attempt_for_arm(mock_execution, "A2_NO_ARCHITECTURAL_ABSTENTION"))
    payload = json.loads(str(attempt["raw_response_content"]))
    payload["section_id"] = "wrong_section"
    attempt["raw_response_content"] = json.dumps(payload)
    result = _analyze_a2(
        mock_execution["inputs"], [attempt], mock_execution["inputs"]["request_by_id"]
    )
    assert result["section_results"][0]["schema_status"] == "FAIL"


def test_09_a2_rejects_unknown_context_id(mock_execution: dict[str, Any]) -> None:
    attempt = dict(_attempt_for_arm(mock_execution, "A2_NO_ARCHITECTURAL_ABSTENTION"))
    payload = json.loads(str(attempt["raw_response_content"]))
    payload["used_context_ids"].append("unknown_context")
    attempt["raw_response_content"] = json.dumps(payload)
    result = _analyze_a2(
        mock_execution["inputs"], [attempt], mock_execution["inputs"]["request_by_id"]
    )
    assert result["section_results"][0]["unknown_context_id_count"] == 1


def test_10_a2_composes_24_affected_tasks(mock_execution: dict[str, Any]) -> None:
    assert mock_execution["summary"]["a2"]["affected_task_count"] == 24
    assert mock_execution["summary"]["a2"]["valid_affected_task_count"] == 24


def test_11_a2_preserves_non_target_p_text(mock_execution: dict[str, Any]) -> None:
    assert mock_execution["summary"]["a2"]["non_target_p_identity_mismatch_count"] == 0


def test_12_a2_preserves_three_p_no_output_tasks(mock_execution: dict[str, Any]) -> None:
    rows = _read_csv_for_test(mock_execution["output"] / "a2_task_composition_manifest.csv")
    no_output = {row["task_id"] for row in rows if row["composition_status"] == "NO_VALID_OUTPUT"}
    assert no_output == NO_OUTPUT_TASKS


def test_13_a3_executes_exactly_147_chunks(mock_execution: dict[str, Any]) -> None:
    assert mock_execution["summary"]["a3"]["chunk_count"] == 147
    assert mock_execution["summary"]["a3"]["valid_chunk_count"] == 147


def test_14_a3_tracks_all_989_expected_claims(mock_execution: dict[str, Any]) -> None:
    assert mock_execution["summary"]["a3"]["expected_claim_count"] == 989
    assert mock_execution["summary"]["a3"]["mapping_complete_count"] == 989


def test_15_a3_detects_missing_and_duplicate_claim_ids(mock_execution: dict[str, Any]) -> None:
    attempt = dict(
        next(
            row
            for row in mock_execution["attempts"]
            if row["arm_internal"] == "A3_NO_FACTLOCK"
            and len(json.loads(str(row["raw_response_content"]))["realizations"]) > 1
        )
    )
    payload = json.loads(str(attempt["raw_response_content"]))
    removed = payload["realizations"].pop()
    payload["realizations"].append(payload["realizations"][0])
    attempt["raw_response_content"] = json.dumps(payload)
    result = _analyze_a3(
        mock_execution["inputs"], [attempt], mock_execution["inputs"]["request_by_id"]
    )
    assert result["missing_claim_count"] >= 1
    assert result["duplicate_claim_count"] >= 1
    assert removed["claim_id"]


def test_16_a3_reconstructs_tasks_deterministically(mock_execution: dict[str, Any]) -> None:
    assert mock_execution["summary"]["a3"]["complete_task_count"] == 45
    first = replay_stage7e(REPO_ROOT, mock_execution["output"])
    second = replay_stage7e(REPO_ROOT, mock_execution["output"])
    assert first == second


def test_17_a3_reuses_frozen_p_plan(mock_execution: dict[str, Any]) -> None:
    rows = _read_csv_for_test(mock_execution["output"] / "a3_task_reconstruction_manifest.csv")
    assert sum(row["p_plan_reused"] == "True" for row in rows) == 45


def test_18_execution_has_no_repair_or_retry(mock_execution: dict[str, Any]) -> None:
    assert mock_execution["summary"]["retry_count"] == 0
    assert all(row["attempt_number"] == 1 for row in mock_execution["attempts"])


def test_19_a4_executes_exactly_48_tasks(mock_execution: dict[str, Any]) -> None:
    assert mock_execution["summary"]["a4"]["task_count"] == 48
    assert mock_execution["summary"]["a4"]["valid_task_count"] == 48


def test_20_a4_rejects_unknown_factlock_id(mock_execution: dict[str, Any]) -> None:
    attempt = dict(_attempt_for_arm(mock_execution, "A4_FREE_FINAL_REALIZATION"))
    payload = json.loads(str(attempt["raw_response_content"]))
    payload["sections"][0]["used_fact_lock_ids"].append("unknown_fact_lock")
    attempt["raw_response_content"] = json.dumps(payload)
    result = _analyze_a4(
        mock_execution["inputs"], [attempt], mock_execution["inputs"]["request_by_id"]
    )
    assert result["unknown_fact_lock_id_count"] == 1
    assert result["valid_task_count"] == 0


def test_21_a4_computes_factlock_trace_coverage(mock_execution: dict[str, Any]) -> None:
    assert mock_execution["summary"]["a4"]["used_fact_lock_count"] == 1022
    assert mock_execution["summary"]["a4"]["fact_lock_coverage"] == 1.0


def test_22_termination_and_truncation_are_classified() -> None:
    assert _termination({"status": "completed"}, transport_success=True) == "NORMAL_COMPLETION"
    assert (
        _termination(
            {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
            transport_success=True,
        )
        == "OUTPUT_LIMIT_OR_LENGTH_TERMINATION"
    )


def test_23_a4_tracks_exactly_1022_factlocks(mock_execution: dict[str, Any]) -> None:
    rows = _read_csv_for_test(mock_execution["output"] / "a4_factlock_trace_audit.csv")
    assert len(rows) == 1022
    assert {row["coverage_status"] for row in rows} == {"USED"}


def test_24_a4_does_not_rewrite_model_text(mock_execution: dict[str, Any]) -> None:
    outputs = _read_jsonl_for_test(mock_execution["output"] / "a4_final_task_outputs.jsonl")
    assert all(not row["model_text_rewritten"] for row in outputs)
    assert all("仅依据锁定事实形成的文本。" in row["text"] for row in outputs)


def test_25_raw_responses_are_preserved_first(mock_execution: dict[str, Any]) -> None:
    for attempt in mock_execution["attempts"]:
        path = mock_execution["output"] / attempt["raw_response_path"]
        assert path.is_file()
        assert json.loads(path.read_text())["parse_status"] == "NOT_PARSED_RAW_FIRST"


def test_26_provider_response_identity_is_unique(mock_execution: dict[str, Any]) -> None:
    ids = [row["provider_response_id"] for row in mock_execution["attempts"]]
    assert len(ids) == len(set(ids)) == 226


def test_27_token_usage_is_recorded_when_supplied(mock_execution: dict[str, Any]) -> None:
    assert all(row["prompt_input_token_count"] == 10 for row in mock_execution["attempts"])
    assert all(row["completion_output_token_count"] == 5 for row in mock_execution["attempts"])
    assert all(row["total_token_count"] == 15 for row in mock_execution["attempts"])


def test_28_replay_has_zero_semantic_mismatch(mock_execution: dict[str, Any]) -> None:
    replay = replay_stage7e(REPO_ROOT, mock_execution["output"])
    assert replay["replay_mismatch_count"] == 0
    assert replay["hard_check_failure_count"] == 0


def test_29_no_broad_semantic_keyword_evaluator() -> None:
    assert _explicit_insufficiency_class("风险正常并导致变化") == "UNKNOWN"
    assert _explicit_insufficiency_class("当前指标不可用。") == "EXPLICIT_INSUFFICIENCY"


def test_30_no_human_semantic_labels_are_generated() -> None:
    rows = _human_deferred_rows()
    assert len(rows) == 6
    assert all(row["status"] == "DEFERRED_TO_HUMAN" for row in rows)
    assert all(not row["automatic_label_generated"] for row in rows)


def test_31_final_run_summary_records_executed_attempts(
    mock_execution: dict[str, Any],
) -> None:
    summary = json.loads((mock_execution["output"] / "run_summary.json").read_text())
    assert summary == mock_execution["summary"]
    assert summary["status"] == "EXECUTION_COMPLETE_DETERMINISTIC_AUDIT_PASS"
    assert summary["actual_attempts"] == 226
    assert summary["actual_api_calls"] == 226


def test_32_a4_scope_audit_uses_union_of_cited_factlock_scopes() -> None:
    scopes = [
        {"start_chainage": 1014555.0, "end_chainage": 1014585.0},
        {"start_chainage": 1014562.0, "end_chainage": 1014608.0},
    ]
    text = "里程1014555至1014585段与里程1014562至1014608段。"
    status, observed = _scope_union_status(scopes, text)
    assert status == "PASS"
    assert observed == [1014555.0, 1014585.0, 1014562.0, 1014608.0]
    assert _scope_union_status(scopes, text + " 里程1014610。 ")[0] == "FAIL"


def test_deepseek_adapter_passes_frozen_messages_and_parameters(
    preflight: dict[str, Any],
) -> None:
    captured: dict[str, Any] = {}

    class Response:
        output_text = "{}"

        def model_dump(self, *, mode: str) -> dict[str, Any]:
            assert mode == "json"
            return {"id": "provider-id", "model": "deepseek-v4-flash", "status": "completed"}

    class Responses:
        def create(self, **kwargs: Any) -> Response:
            captured.update(kwargs)
            return Response()

    class Client:
        responses = Responses()

    request = preflight["requests"][0]
    provider = FrozenDeepSeekProvider(preflight["provider_config"], client=Client())
    provider.request(request)
    assert captured["input"] == request["messages"]
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["temperature"] == 0.0
    assert captured["top_p"] == 1.0
    assert captured["max_output_tokens"] == 4096
    assert captured["reasoning"] == {"effort": "none"}


def _read_csv_for_test(path: Path) -> list[dict[str, str]]:
    import csv

    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_jsonl_for_test(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]
