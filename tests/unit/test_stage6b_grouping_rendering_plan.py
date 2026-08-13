"""Stage6B grouping, canonical rendering and plan validation tests."""

from __future__ import annotations

import subprocess
import sys
import types

from tbm_twin.realization.io import stable_hash
from tbm_twin.realization.models import SliceSpec
from tbm_twin.realization.providers.configured_llm import LLMProviderConfig
from tbm_twin.realization.providers.deepseek_adapter import (
    DEEPSEEK_RESPONSES_BASE_URL,
    DEEPSEEK_RESPONSES_SUPPORTED_MODEL,
    DeepSeekResponsesPlanProvider,
)
from tbm_twin.realization.providers.openai_adapter import OpenAIPlanProvider
from tbm_twin.realization.stage6b import (
    PresentationScopeResolver,
    audit_chainage_tokens,
    audit_post_realization,
    build_canonical_sentence,
    build_product_contract,
    build_realization_units,
    build_task_bundle,
    extract_engineering_numbers,
    load_stage6b_inputs,
    validate_plan,
)
from tbm_twin.realization.stage6b_models import RealizationPlan, RealizationPlanSection
from tbm_twin.realization.stage6b_smoke import (
    MinimalProviderPlan,
    MockPlanProvider,
    SmokeRealizationRequest,
    build_manifest_bound_task_bundles,
    default_provider_config_public,
    execute_smoke_tasks,
    execution_protocol,
    parse_provider_plan,
    smoke_manifest_hash,
)
from tests.unit.stage6b_helpers import REPO_ROOT, read_csv, read_json, read_jsonl, stage6b_artifact


def test_stage6b_grouping_reconciliation_is_complete(tmp_path_factory) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    rows = read_csv(artifact / "realization_grouping_audit.csv")

    assert rows
    assert all(row["fact_lock_missing_from_unit"] == "0" for row in rows)
    assert all(row["fact_lock_multi_unit_membership"] == "0" for row in rows)
    assert all(row["metric_cross_cell_grouping"] == "0" for row in rows)


def test_stage6b_metrics_do_not_cross_cell_group() -> None:
    inputs = load_stage6b_inputs(REPO_ROOT)
    metric_locks = [
        lock
        for lock in inputs["stage6a_locks"]
        if lock.claim_type == "OPERATIONAL_RESPONSE_ATTENTION"
    ][:2]
    units = build_realization_units(
        metric_locks, PresentationScopeResolver(inputs["stage3a_cells"])
    )

    assert len(units) == len(metric_locks)
    assert all(len(unit.member_fact_lock_ids) == 1 for unit in units)


def test_stage6b_forecast_and_observed_never_group() -> None:
    inputs = load_stage6b_inputs(REPO_ROOT)
    locks = [
        next(
            lock
            for lock in inputs["stage6a_locks"]
            if lock.claim_type == "FORECAST_GEOLOGICAL_CONDITION"
        ),
        next(
            lock
            for lock in inputs["stage6a_locks"]
            if lock.claim_type == "OBSERVED_GEOLOGICAL_CONDITION"
        ),
    ]
    units = build_realization_units(locks, PresentationScopeResolver(inputs["stage3a_cells"]))

    assert len(units) == 2


def test_stage6b_formatter_covers_all_current_geological_attributes(tmp_path_factory) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    rows = read_csv(artifact / "formatter_coverage_audit.csv")

    assert len(rows) == 24
    assert all(row["status"] == "PASS" for row in rows)


def test_stage6b_metric_canonical_rendering_preserves_value_and_boundary() -> None:
    inputs = load_stage6b_inputs(REPO_ROOT)
    lock = next(
        item for item in inputs["stage6a_locks"] if item.claim_type == "COUPLED_ATTENTION_REVIEW"
    )
    unit = build_realization_units([lock], PresentationScopeResolver(inputs["stage3a_cells"]))[0]
    sentence = build_canonical_sentence(unit)

    assert sentence.numeric_tokens[0]["raw_value"] == lock.claim_value["metric_value"]
    assert sentence.numeric_tokens[0]["display_value"] == f"{lock.claim_value['metric_value']:.3f}"
    assert "非概率" in sentence.text
    assert "风险概率" not in sentence.text
    assert "地质导致" not in sentence.text


def test_stage6b_forecast_daily_review_uses_forecast_wording() -> None:
    inputs = load_stage6b_inputs(REPO_ROOT)
    lock = next(
        item
        for item in inputs["stage6a_locks"]
        if item.claim_type == "FORECAST_GEOLOGICAL_CONDITION"
        and item.state_role == "DAILY_REVIEW_CELL"
    )
    unit = build_realization_units([lock], PresentationScopeResolver(inputs["stage3a_cells"]))[0]
    sentence = build_canonical_sentence(unit)

    assert "预报资料" in sentence.text
    assert "实际揭露为" not in sentence.text


def test_stage6b_plan_validator_rejects_unknown_unit_and_pack_mismatch() -> None:
    inputs = load_stage6b_inputs(REPO_ROOT)
    bundle = build_task_bundle(
        inputs["stage6a_locks"],
        inputs["stage5b_abstentions"],
        inputs["stage3a_cells"],
        SliceSpec(product_type="metric_review"),
    )
    plan = bundle["plan"]
    contract = build_product_contract("metric_review")
    unknown = RealizationPlan(
        **{
            **plan.model_dump(mode="json"),
            "plan_id": "unknown",
            "sections": [
                RealizationPlanSection(
                    section_id=contract.section_order[0],
                    ordered_unit_ids=["unknown_unit"],
                )
            ],
            "plan_hash": "tampered",
        }
    )
    bad_pack = RealizationPlan(
        **{
            **plan.model_dump(mode="json"),
            "plan_id": "bad_pack",
            "pack_hash": "tampered",
            "plan_hash": "tampered",
        }
    )

    assert "UNKNOWN_UNIT" in validate_plan(
        unknown,
        bundle["units"],
        bundle["contract"],
        bundle["pack"].pack_id,
        bundle["pack"].pack_hash,
        bundle["task_view"].task_abstention_view_id,
    )
    assert "PACK_HASH_MISMATCH" in validate_plan(
        bad_pack,
        bundle["units"],
        bundle["contract"],
        bundle["pack"].pack_id,
        bundle["pack"].pack_hash,
        bundle["task_view"].task_abstention_view_id,
    )


def test_stage6b_plan_validator_rejects_product_view_hash_and_omission_tamper() -> None:
    inputs = load_stage6b_inputs(REPO_ROOT)
    bundle = build_task_bundle(
        inputs["stage6a_locks"],
        inputs["stage5b_abstentions"],
        inputs["stage3a_cells"],
        SliceSpec(product_type="metric_review"),
    )
    plan = bundle["plan"]
    units = bundle["units"]
    common_args = (
        units,
        bundle["contract"],
        bundle["pack"].pack_id,
        bundle["pack"].pack_hash,
        bundle["task_view"].task_abstention_view_id,
    )
    product_mismatch = RealizationPlan(
        **{**plan.model_dump(mode="json"), "product_type": "daily_review", "plan_hash": "bad"}
    )
    view_mismatch = RealizationPlan(
        **{
            **plan.model_dump(mode="json"),
            "task_abstention_view_id": "wrong_view",
            "plan_hash": "bad",
        }
    )
    bad_hash = RealizationPlan(**{**plan.model_dump(mode="json"), "plan_hash": "bad"})
    all_omitted = RealizationPlan(
        **{
            **plan.model_dump(mode="json"),
            "sections": [],
            "omitted_optional_unit_ids": [unit.realization_unit_id for unit in units],
            "plan_hash": "bad",
        }
    )

    assert "PRODUCT_TYPE_MISMATCH" in validate_plan(product_mismatch, *common_args)
    assert "TASK_ABSTENTION_VIEW_MISMATCH" in validate_plan(view_mismatch, *common_args)
    assert "PLAN_HASH_MISMATCH" in validate_plan(bad_hash, *common_args)
    issues = validate_plan(all_omitted, *common_args)
    assert "ALL_UNITS_OMITTED" in issues
    assert "ILLEGAL_OPTIONAL_OMISSION" in issues


def test_stage6b_post_audit_rejects_probability_tamper() -> None:
    inputs = load_stage6b_inputs(REPO_ROOT)
    bundle = build_task_bundle(
        inputs["stage6a_locks"],
        inputs["stage5b_abstentions"],
        inputs["stage3a_cells"],
        SliceSpec(product_type="metric_review"),
    )
    composed = bundle["composed"]
    tampered = composed.__class__(
        **{
            **composed.model_dump(mode="json"),
            "text": composed.text + "\n该区段风险概率为 0.5。",
            "realization_hash": "tampered",
        }
    )

    assert "ATTENTION_PROMOTED_TO_PROBABILITY" in audit_post_realization(
        tampered, bundle["sentences"]
    )


def test_stage6b_engineering_number_extractor_and_chainage_audit() -> None:
    assert extract_engineering_numbers("RAI 为 0.253, 里程 1014500.0, 偏离 -0.25, 数值 35。") == [
        "0.253",
        "1014500.0",
        "-0.25",
        "35",
    ]
    assert extract_engineering_numbers("1. 综合情况") == []

    inputs = load_stage6b_inputs(REPO_ROOT)
    interval_lock = next(
        lock
        for lock in inputs["stage6a_locks"]
        if lock.spatial_scope.get("scope_kind") == "LOCATED_INTERVAL"
    )
    point_lock = next(
        lock
        for lock in inputs["stage6a_locks"]
        if lock.spatial_scope.get("scope_kind") == "LOCATED_POINT"
    )
    resolver = PresentationScopeResolver(inputs["stage3a_cells"])
    interval_sentence = build_canonical_sentence(
        build_realization_units([interval_lock], resolver)[0]
    )
    point_sentence = build_canonical_sentence(build_realization_units([point_lock], resolver)[0])

    assert audit_chainage_tokens(interval_sentence.text, [interval_sentence]) == []
    assert audit_chainage_tokens(point_sentence.text, [point_sentence]) == []
    assert "UNTRACED_CHAINAGE" in audit_chainage_tokens(
        f"{interval_sentence.text} 该区段里程 999999.9 地质情况较差。",
        [interval_sentence],
    )
    changed_end = interval_sentence.text.replace(
        str(interval_sentence.chainage_tokens[-1]["display_value"]),
        "999999.9",
        1,
    )
    assert "UNTRACED_CHAINAGE" in audit_chainage_tokens(changed_end, [interval_sentence])


def test_stage6b_post_audit_rejects_required_tamper_cases() -> None:
    inputs = load_stage6b_inputs(REPO_ROOT)
    bundle = build_task_bundle(
        inputs["stage6a_locks"],
        inputs["stage5b_abstentions"],
        inputs["stage3a_cells"],
        SliceSpec(product_type="daily_review"),
    )
    cases = [
        ("该区段围岩整体较差。", "UNAUTHORIZED_ENGINEERING_SENTENCE"),
        ("该区段里程 999999.9 地质情况较差。", "UNTRACED_CHAINAGE"),
        ("该区段实际揭露岩体破碎。", "UNAUTHORIZED_ENGINEERING_SENTENCE"),
        ("该区段风险为较高水平。", "UNAUTHORIZED_ENGINEERING_SENTENCE"),
        ("地质异常导致推力增加。", "MECHANICAL_RESPONSE_PROMOTED_TO_GEOLOGICAL_CAUSE"),
        ("UNKNOWN 施工状态正常。", "UNKNOWN_PROMOTED_TO_NORMAL"),
    ]
    for extra_text, expected_issue in cases:
        tampered = bundle["composed"].__class__(
            **{
                **bundle["composed"].model_dump(mode="json"),
                "text": bundle["composed"].text + "\n" + extra_text,
                "realization_hash": "tampered",
            }
        )
        assert expected_issue in audit_post_realization(tampered, bundle["sentences"])


def test_stage6b_real_grouping_regression_has_multi_member_units(tmp_path_factory) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    rows = read_csv(artifact / "real_grouping_regression_audit.csv")

    assert rows
    assert {row["valid_date"] for row in rows} == {"2023-10-29", "2023-12-24"}
    assert all(int(row["multi_member_units"]) > 0 for row in rows)
    assert all(int(row["input_fact_locks"]) > int(row["output_realization_units"]) for row in rows)


def test_stage6b_artifact_hard_check_passes(tmp_path_factory) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    rows = read_csv(artifact / "stage6b_hard_check.csv")
    manifest = read_json(artifact / "realization_unit_manifest.json")
    sentences = read_jsonl(artifact / "canonical_sentences.jsonl")

    assert manifest["hard_issue_count"] == 0
    assert sentences
    assert all(row["status"] == "PASS" for row in rows)
    assert _row(rows, "issue_count")["actual"] == "0"
    assert int(_row(rows, "smoke_manifest_task_count")["actual"]) >= 12
    assert int(_row(rows, "smoke_manifest_task_count_upper")["actual"]) <= 20
    assert _row(rows, "smoke_multi_valid_date_task_count")["actual"] == "0"
    assert _row(rows, "dry_run_api_call_count")["actual"] == "0"


def test_stage6b_real_model_smoke_is_not_run_and_candidate_not_freeze_ready(
    tmp_path_factory,
) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    method = read_json(artifact / "method_version.json")
    smoke = read_csv(artifact / "real_model_smoke/smoke_summary.csv")[0]
    status = read_json(artifact / "real_model_smoke/status.json")

    assert method["status"] == "READY_FOR_REAL_MODEL_SMOKE"
    assert method["uses_llm"] is False
    assert smoke["real_model_smoke_status"] == "NOT_RUN"
    assert smoke["dry_run_status"] == "PASS"
    assert smoke["freeze_ready"] == "false"
    assert status["manifest_frozen"] is True
    assert status["api_call_count"] == 0


def test_stage6b_smoke_manifest_is_single_date_and_covered(tmp_path_factory) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    temporal_rows = read_csv(artifact / "smoke_task_valid_date_audit.csv")
    coverage_rows = read_csv(artifact / "smoke_manifest_coverage_audit.csv")
    tasks = read_json(artifact / "real_model_smoke/task_manifest.json")

    assert len(tasks) == 15
    assert all(task["valid_date"] for task in tasks)
    assert all(row["distinct_count"] == "1" for row in temporal_rows)
    assert all(row["status"] == "PASS" for row in temporal_rows)
    assert all(row["status"] == "PASS" for row in coverage_rows)
    assert any(task["cell_id"] for task in tasks)


def test_stage6b_smoke_prompts_are_plan_only_and_deterministic(tmp_path_factory) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    payloads = [
        SmokeRealizationRequest(**row)
        for row in read_jsonl(artifact / "real_model_smoke/prompt_payloads.jsonl")
    ]

    assert len(payloads) == 15
    first = payloads[0]
    assert "You are not writing the engineering report." in first.instructions
    assert all("canonical_safe_text" in unit for unit in first.units)
    assert all("raw PLC" not in str(payload.model_dump(mode="json")) for payload in payloads)
    prompt_payload = {
        key: value
        for key, value in first.model_dump(mode="json").items()
        if key not in {"request_id", "prompt_hash"}
    }
    assert stable_hash(prompt_payload) == first.prompt_hash
    assert stable_hash(prompt_payload) == (
        stable_hash(
            {
                key: value
                for key, value in SmokeRealizationRequest(**first.model_dump(mode="json"))
                .model_dump(mode="json")
                .items()
                if key not in {"request_id", "prompt_hash"}
            }
        )
    )


def test_stage6b_real_model_smoke_dry_run_artifacts(tmp_path_factory) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    dry_run = read_json(artifact / "real_model_smoke/dry_run_status.json")
    protocol = read_json(artifact / "real_model_smoke/protocol.json")

    assert dry_run["dry_run_status"] == "PASS"
    assert dry_run["api_call_count"] == 0
    assert dry_run["tasks_loaded"] == 15
    assert dry_run["requests_prepared"] == 15
    assert protocol["model_must_not_generate_engineering_text"] is True
    assert protocol["retry_policy"]["max_retries"] == 0


def test_stage6b_minimal_provider_plan_parser_fails_closed() -> None:
    valid, codes, error = parse_provider_plan(
        '{"product_type":"daily_review","sections":[],"omitted_optional_unit_ids":[]}'
    )
    assert isinstance(valid, MinimalProviderPlan)
    assert codes == []
    assert error == ""

    markdown, codes, _ = parse_provider_plan(
        '```json\n{"product_type":"daily_review","sections":[],"omitted_optional_unit_ids":[]}\n```'
    )
    assert markdown is None
    assert codes == ["PARSE_FAILURE"]

    extra, codes, _ = parse_provider_plan(
        '{"product_type":"daily_review","sections":[],"omitted_optional_unit_ids":[],"generated_text":"bad"}'
    )
    assert extra is None
    assert codes == ["SCHEMA_VALIDATION_FAILURE"]

    missing, codes, _ = parse_provider_plan('{"product_type":"daily_review","sections":[]}')
    assert missing is None
    assert codes == ["SCHEMA_VALIDATION_FAILURE"]


def test_stage6b_mock_execution_artifacts_cover_success_and_failures(tmp_path_factory) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    run_root = artifact / "real_model_smoke/mock_run/runs"
    success_dir = next(
        path for path in run_root.iterdir() if path.name.startswith("stage6b_smoke_execution_")
    )
    success = read_json(success_dir / "status.json")

    assert success["task_count"] == 15
    assert success["provider_attempt_count"] == 15
    assert success["real_api_call_count"] == 0
    assert success["first_attempt_parse_valid_rate"] == 1.0
    assert success["first_attempt_schema_valid_rate"] == 1.0
    assert success["first_attempt_plan_acceptance_rate"] == 1.0
    assert success["post_audit_pass_rate"] == 1.0
    assert len(read_jsonl(success_dir / "raw_model_outputs.jsonl")) == 15

    parse_failure = read_json(run_root / "mock_parse_failure_execution/status.json")
    schema_failure = read_json(run_root / "mock_schema_failure_execution/status.json")
    plan_failure = read_json(run_root / "mock_plan_failure_execution/status.json")
    post_failure = read_json(run_root / "mock_post_failure_execution/status.json")

    assert parse_failure["composition_count"] == 0
    assert schema_failure["composition_count"] == 0
    assert plan_failure["composition_count"] == 0
    assert plan_failure["validator_interception_count"] == 1
    assert post_failure["composition_count"] == 1
    assert post_failure["post_audit_violation_count"] == 1


def test_stage6b_provider_accounting_distinguishes_transport_and_parse(
    tmp_path_factory, tmp_path
) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    tasks = read_json(artifact / "real_model_smoke/task_manifest.json")
    requests = [
        SmokeRealizationRequest(**row)
        for row in read_jsonl(artifact / "real_model_smoke/prompt_payloads.jsonl")
    ]
    inputs = load_stage6b_inputs(REPO_ROOT)
    bundles, binding_rows = build_manifest_bound_task_bundles(
        inputs["stage6a_locks"],
        inputs["stage5b_abstentions"],
        inputs["stage3a_cells"],
        tasks,
        requests,
    )
    protocol = execution_protocol(
        smoke_manifest_hash(tasks), default_provider_config_public(provider="mock", model="mock")
    )

    partial = execute_smoke_tasks(
        bundles,
        requests,
        _PartialFailureProvider(success_count=10),
        tmp_path / "partial",
        protocol,
        execution_manifest_binding_rows=binding_rows,
    )
    assert partial["provider_request_attempt_count"] == 15
    assert partial["provider_transport_success_count"] == 10
    assert partial["provider_transport_failure_count"] == 5
    assert partial["provider_transport_success_rate"] == 10 / 15
    assert partial["provider_transport_success_rate_n"] == 15
    assert partial["first_attempt_parse_valid_rate_n"] == 10
    assert partial["real_api_request_attempt_count"] == 0

    all_failed = execute_smoke_tasks(
        bundles[:3],
        requests[:3],
        MockPlanProvider("transport_failure"),
        tmp_path / "all_failed",
        protocol,
        execution_manifest_binding_rows=binding_rows[:3],
    )
    assert all_failed["provider_request_attempt_count"] == 3
    assert all_failed["provider_transport_success_count"] == 0
    assert all_failed["provider_transport_failure_count"] == 3
    assert all_failed["provider_transport_success_rate"] == 0.0
    assert all_failed["first_attempt_parse_valid_rate"] is None
    assert all_failed["first_attempt_parse_valid_rate_n"] == 0

    malformed = execute_smoke_tasks(
        bundles[:1],
        requests[:1],
        MockPlanProvider("malformed_json"),
        tmp_path / "malformed",
        protocol,
        execution_manifest_binding_rows=binding_rows[:1],
    )
    assert malformed["provider_request_attempt_count"] == 1
    assert malformed["provider_transport_success_count"] == 1
    assert malformed["provider_transport_failure_count"] == 0
    assert malformed["first_attempt_parse_valid_rate"] == 0.0


def test_stage6b_runner_without_execute_does_not_call_api(tmp_path) -> None:
    output_dir = tmp_path / "smoke"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_stage6b_real_model_smoke.py",
            "--provider",
            "openai",
            "--model",
            "UNSET_REAL_MODEL",
            "--output-dir",
            output_dir.as_posix(),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "REAL_MODEL_SMOKE_EXECUTE_NOT_REQUESTED" in result.stdout
    status = read_json(output_dir / "no_execute_status.json")
    assert status["api_call_count"] == 0


def test_stage6b_runner_openai_unset_model_fails_before_api(tmp_path) -> None:
    output_dir = tmp_path / "smoke"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_stage6b_real_model_smoke.py",
            "--provider",
            "openai",
            "--model",
            "UNSET_REAL_MODEL",
            "--execute",
            "--output-dir",
            output_dir.as_posix(),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "REAL_MODEL_SMOKE_PREFLIGHT_FAILED UNSET_REAL_MODEL" in result.stdout
    failures = list((output_dir / "preflight_failures").glob("*.json"))
    assert failures
    status = read_json(failures[0])
    assert status["real_api_request_attempt_count"] == 0
    assert status["formal_run_directory_created"] is False


def test_stage6b_execution_is_manifest_driven_even_if_task_specs_change(
    tmp_path_factory, monkeypatch
) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    tasks = read_json(artifact / "real_model_smoke/task_manifest.json")
    requests = [
        SmokeRealizationRequest(**row)
        for row in read_jsonl(artifact / "real_model_smoke/prompt_payloads.jsonl")
    ]
    inputs = load_stage6b_inputs(REPO_ROOT)

    import tbm_twin.realization.build_stage6b as build_stage6b

    monkeypatch.setattr(build_stage6b, "_task_specs", lambda _locks: [])
    bundles, rows = build_manifest_bound_task_bundles(
        inputs["stage6a_locks"],
        inputs["stage5b_abstentions"],
        inputs["stage3a_cells"],
        tasks,
        requests,
    )

    assert len(bundles) == len(tasks) == 15
    assert all(row["status"] == "PASS" for row in rows)
    assert [unit.realization_unit_id for unit in bundles[0]["units"]] == tasks[0][
        "realization_unit_ids"
    ]


def test_stage6b_manifest_binding_mismatch_fails_before_provider_call(
    tmp_path_factory, tmp_path
) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    tasks = read_json(artifact / "real_model_smoke/task_manifest.json")
    requests = [
        SmokeRealizationRequest(**row)
        for row in read_jsonl(artifact / "real_model_smoke/prompt_payloads.jsonl")
    ]
    inputs = load_stage6b_inputs(REPO_ROOT)

    tampered_request = SmokeRealizationRequest(
        **{
            **requests[0].model_dump(mode="json"),
            "slice_spec": {**requests[0].slice_spec, "valid_date": "2099-01-01"},
        }
    )
    _, rows = build_manifest_bound_task_bundles(
        inputs["stage6a_locks"],
        inputs["stage5b_abstentions"],
        inputs["stage3a_cells"],
        tasks[:1],
        [tampered_request],
    )
    provider = _CountingProvider()
    try:
        execute_smoke_tasks(
            [],
            [tampered_request],
            provider,
            tmp_path,
            execution_protocol(smoke_manifest_hash(tasks), default_provider_config_public()),
            execution_manifest_binding_rows=rows,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("manifest binding mismatch should fail closed")
    assert provider.call_count == 0

    tampered_task = {**tasks[0], "realization_unit_ids": ["wrong_unit"]}
    _, rows = build_manifest_bound_task_bundles(
        inputs["stage6a_locks"],
        inputs["stage5b_abstentions"],
        inputs["stage3a_cells"],
        [tampered_task],
        requests[:1],
    )
    assert rows[0]["status"] == "FAIL"

    tampered_task = {**tasks[0], "pack_hash": "wrong_pack_hash"}
    _, rows = build_manifest_bound_task_bundles(
        inputs["stage6a_locks"],
        inputs["stage5b_abstentions"],
        inputs["stage3a_cells"],
        [tampered_task],
        requests[:1],
    )
    assert rows[0]["status"] == "FAIL"


def test_stage6b_openai_adapter_uses_transport_parameters_without_network(
    tmp_path_factory, monkeypatch
) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    request = SmokeRealizationRequest(
        **read_jsonl(artifact / "real_model_smoke/prompt_payloads.jsonl")[0]
    )
    calls = {}

    class FakeResponse:
        output_text = '{"product_type":"daily_review","sections":[],"omitted_optional_unit_ids":[]}'

        def model_dump(self, mode: str) -> dict[str, object]:
            assert mode == "json"
            return {"usage": {"input_tokens": 1, "output_tokens": 1}}

    class FakeResponses:
        def create(self, **kwargs):
            calls.update(kwargs)
            return FakeResponse()

    class FakeOpenAI:
        def __init__(self, api_key: str, max_retries: int) -> None:
            calls["api_key"] = api_key
            calls["max_retries"] = max_retries
            self.responses = FakeResponses()

    fake_module = types.SimpleNamespace(OpenAI=FakeOpenAI)
    monkeypatch.setitem(sys.modules, "openai", fake_module)
    monkeypatch.setenv("STAGE6B_REAL_MODEL_API_KEY", "test-key-from-env")
    provider = OpenAIPlanProvider(
        LLMProviderConfig(
            model_provider="openai",
            model_name="mock-model",
            temperature=0.0,
            top_p=1.0,
            seed=0,
            reasoning_effort="none",
            max_output_tokens=256,
            timeout_seconds=120,
            max_retries=0,
            retry_causes=[],
            api_key_env_var="STAGE6B_REAL_MODEL_API_KEY",
        )
    )

    attempt = provider.request_plan(request)

    assert calls["api_key"] == "test-key-from-env"
    assert calls["max_retries"] == 0
    assert calls["model"] == "mock-model"
    assert calls["temperature"] == 0.0
    assert calls["top_p"] == 1.0
    assert calls["max_output_tokens"] == 256
    assert calls["reasoning"] == {"effort": "none"}
    assert "seed" not in calls
    assert attempt.raw_response_text.startswith("{")
    assert attempt.raw_response_payload is not None
    assert attempt.provider_kind == "REAL_API"
    assert attempt.real_api_attempted is True
    assert attempt.real_api_transport_success is True


def test_stage6b_openai_adapter_records_transport_failure_without_network(
    tmp_path_factory, monkeypatch
) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    request = SmokeRealizationRequest(
        **read_jsonl(artifact / "real_model_smoke/prompt_payloads.jsonl")[0]
    )
    calls = {}

    class FakeResponses:
        def create(self, **kwargs):
            calls.update(kwargs)
            raise TimeoutError("simulated timeout")

    class FakeOpenAI:
        def __init__(self, api_key: str, max_retries: int) -> None:
            calls["api_key"] = api_key
            calls["max_retries"] = max_retries
            self.responses = FakeResponses()

    fake_module = types.SimpleNamespace(OpenAI=FakeOpenAI)
    monkeypatch.setitem(sys.modules, "openai", fake_module)
    monkeypatch.setenv("STAGE6B_REAL_MODEL_API_KEY", "test-key-from-env")
    provider = OpenAIPlanProvider(
        LLMProviderConfig(
            model_provider="openai",
            model_name="mock-model",
            temperature=0.0,
            top_p=1.0,
            seed=0,
            reasoning_effort="none",
            max_output_tokens=256,
            timeout_seconds=120,
            max_retries=0,
            retry_causes=[],
            api_key_env_var="STAGE6B_REAL_MODEL_API_KEY",
        )
    )

    attempt = provider.request_plan(request)

    assert calls["model"] == "mock-model"
    assert calls["max_retries"] == 0
    assert attempt.provider_kind == "REAL_API"
    assert attempt.provider_attempted is True
    assert attempt.transport_success is False
    assert attempt.real_api_attempted is True
    assert attempt.real_api_transport_success is False
    assert attempt.raw_response_available is False
    assert attempt.provider_error_type == "TimeoutError"


def test_stage6b_deepseek_adapter_uses_official_responses_base_url_without_network(
    tmp_path_factory, monkeypatch
) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    request = SmokeRealizationRequest(
        **read_jsonl(artifact / "real_model_smoke/prompt_payloads.jsonl")[0]
    )
    calls = {}

    class FakeResponse:
        output_text = '{"product_type":"daily_review","sections":[],"omitted_optional_unit_ids":[]}'

        def model_dump(self, mode: str) -> dict[str, object]:
            assert mode == "json"
            return {"usage": {"input_tokens": 2, "output_tokens": 3}}

    class FakeResponses:
        def create(self, **kwargs):
            calls["create_kwargs"] = kwargs
            return FakeResponse()

    class FakeOpenAI:
        def __init__(self, api_key: str, base_url: str, max_retries: int) -> None:
            calls["api_key"] = api_key
            calls["base_url"] = base_url
            calls["max_retries"] = max_retries
            self.responses = FakeResponses()

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    provider = DeepSeekResponsesPlanProvider(
        LLMProviderConfig(
            model_provider="deepseek",
            model_name=DEEPSEEK_RESPONSES_SUPPORTED_MODEL,
            temperature=0.0,
            top_p=1.0,
            seed=0,
            reasoning_effort="none",
            max_output_tokens=256,
            timeout_seconds=120,
            max_retries=0,
            retry_causes=[],
            api_key_env_var="DEEPSEEK_API_KEY",
            base_url=DEEPSEEK_RESPONSES_BASE_URL,
        )
    )

    attempt = provider.request_plan(request)

    assert calls["api_key"] == "test-deepseek-key"
    assert calls["base_url"] == DEEPSEEK_RESPONSES_BASE_URL
    assert calls["max_retries"] == 0
    kwargs = calls["create_kwargs"]
    assert kwargs["model"] == DEEPSEEK_RESPONSES_SUPPORTED_MODEL
    assert kwargs["temperature"] == 0.0
    assert kwargs["top_p"] == 1.0
    assert kwargs["max_output_tokens"] == 256
    assert kwargs["reasoning"] == {"effort": "none"}
    assert request.task_id in kwargs["input"][1]["content"]
    assert attempt.provider_kind == "REAL_API"
    assert attempt.provider == "deepseek"
    assert attempt.real_api_attempted is True
    assert attempt.real_api_transport_success is True
    assert attempt.raw_response_available is True


def test_stage6b_deepseek_adapter_records_exception_accounting_without_network(
    tmp_path_factory, monkeypatch
) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    request = SmokeRealizationRequest(
        **read_jsonl(artifact / "real_model_smoke/prompt_payloads.jsonl")[0]
    )

    calls = {"create_count": 0}

    class FakeResponses:
        def create(self, **kwargs):
            calls["create_count"] += 1
            raise TimeoutError("deepseek timeout")

    class FakeOpenAI:
        def __init__(self, api_key: str, base_url: str, max_retries: int) -> None:
            assert max_retries == 0
            self.responses = FakeResponses()

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    provider = DeepSeekResponsesPlanProvider(
        LLMProviderConfig(
            model_provider="deepseek",
            model_name=DEEPSEEK_RESPONSES_SUPPORTED_MODEL,
            temperature=0.0,
            top_p=1.0,
            seed=0,
            reasoning_effort="none",
            max_output_tokens=256,
            timeout_seconds=120,
            max_retries=0,
            retry_causes=[],
            api_key_env_var="DEEPSEEK_API_KEY",
            base_url=DEEPSEEK_RESPONSES_BASE_URL,
        )
    )

    attempt = provider.request_plan(request)

    assert attempt.provider == "deepseek"
    assert attempt.provider_kind == "REAL_API"
    assert attempt.provider_attempted is True
    assert attempt.transport_success is False
    assert attempt.real_api_attempted is True
    assert attempt.real_api_transport_success is False
    assert attempt.raw_response_available is False
    assert attempt.provider_error_type == "TimeoutError"
    assert calls["create_count"] == 1


def test_stage6b_deepseek_malformed_json_is_parse_failure_not_transport_failure(
    tmp_path_factory, tmp_path, monkeypatch
) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    tasks = read_json(artifact / "real_model_smoke/task_manifest.json")
    requests = [
        SmokeRealizationRequest(**row)
        for row in read_jsonl(artifact / "real_model_smoke/prompt_payloads.jsonl")
    ]
    inputs = load_stage6b_inputs(REPO_ROOT)
    bundles, binding_rows = build_manifest_bound_task_bundles(
        inputs["stage6a_locks"],
        inputs["stage5b_abstentions"],
        inputs["stage3a_cells"],
        tasks,
        requests,
    )
    calls = {"create_count": 0}

    class FakeResponse:
        output_text = "not json"

        def model_dump(self, mode: str) -> dict[str, object]:
            assert mode == "json"
            return {"usage": {"input_tokens": 1, "output_tokens": 1}}

    class FakeResponses:
        def create(self, **kwargs):
            calls["create_count"] += 1
            return FakeResponse()

    class FakeOpenAI:
        def __init__(self, api_key: str, base_url: str, max_retries: int) -> None:
            assert max_retries == 0
            self.responses = FakeResponses()

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    provider = DeepSeekResponsesPlanProvider(
        LLMProviderConfig(
            model_provider="deepseek",
            model_name=DEEPSEEK_RESPONSES_SUPPORTED_MODEL,
            temperature=0.0,
            top_p=1.0,
            seed=0,
            reasoning_effort="none",
            max_output_tokens=256,
            timeout_seconds=120,
            max_retries=0,
            retry_causes=[],
            api_key_env_var="DEEPSEEK_API_KEY",
            base_url=DEEPSEEK_RESPONSES_BASE_URL,
        )
    )
    protocol = execution_protocol(
        smoke_manifest_hash(tasks),
        default_provider_config_public(
            provider="deepseek", model=DEEPSEEK_RESPONSES_SUPPORTED_MODEL
        ),
    )

    result = execute_smoke_tasks(
        bundles[:1],
        requests[:1],
        provider,
        tmp_path,
        protocol,
        execution_manifest_binding_rows=binding_rows[:1],
    )

    assert calls["create_count"] == 1
    assert result["provider_request_attempt_count"] == 1
    assert result["real_api_request_attempt_count"] == 1
    assert result["provider_transport_success_count"] == 1
    assert result["provider_transport_failure_count"] == 0
    assert result["first_attempt_parse_valid_rate"] == 0.0


def test_stage6b_deepseek_execute_missing_credential_fails_before_formal_run(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_stage6b_real_model_smoke.py",
            "--provider",
            "deepseek",
            "--model",
            DEEPSEEK_RESPONSES_SUPPORTED_MODEL,
            "--execute",
            "--output-dir",
            tmp_path.as_posix(),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "REAL_MODEL_SMOKE_PREFLIGHT_FAILED MISSING_DEEPSEEK_API_KEY" in result.stdout
    assert "REAL_MODEL_SMOKE_EXECUTION_COMPLETE" not in result.stdout
    assert not (tmp_path / "runs").exists()
    failures = list((tmp_path / "preflight_failures").glob("*.json"))
    assert failures
    status = read_json(failures[0])
    assert status["provider_request_attempt_count"] == 0
    assert status["real_api_request_attempt_count"] == 0
    assert status["formal_run_directory_created"] is False


def test_stage6b_deepseek_execute_missing_sdk_fails_before_formal_run(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    import builtins

    from scripts.run_stage6b_real_model_smoke import _provider_preflight

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "openai":
            raise ImportError("simulated missing openai")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    config = default_provider_config_public(
        provider="deepseek", model=DEEPSEEK_RESPONSES_SUPPORTED_MODEL
    )
    protocol = execution_protocol("manifest_hash", config)
    result = _provider_preflight("deepseek", DEEPSEEK_RESPONSES_SUPPORTED_MODEL, config, protocol)

    assert result["failure_code"] == "OPENAI_SDK_MISSING"
    assert result["real_api_request_attempt_count"] == 0


def test_stage6b_deepseek_unsupported_model_fails_before_formal_run(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_stage6b_real_model_smoke.py",
            "--provider",
            "deepseek",
            "--model",
            "deepseek-v4-pro",
            "--execute",
            "--output-dir",
            tmp_path.as_posix(),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "UNSUPPORTED_DEEPSEEK_RESPONSES_MODEL" in result.stdout
    assert not (tmp_path / "runs").exists()


class _CountingProvider(MockPlanProvider):
    def __init__(self) -> None:
        super().__init__("success")
        self.call_count = 0

    def request_plan(self, request: SmokeRealizationRequest):
        self.call_count += 1
        return super().request_plan(request)


class _PartialFailureProvider(MockPlanProvider):
    def __init__(self, success_count: int) -> None:
        super().__init__("success")
        self.success_count = success_count
        self.call_count = 0

    def request_plan(self, request: SmokeRealizationRequest):
        self.call_count += 1
        if self.call_count > self.success_count:
            raise RuntimeError("deterministic partial transport failure")
        return super().request_plan(request)


def _row(rows: list[dict[str, str]], check_name: str) -> dict[str, str]:
    return next(row for row in rows if row["check_name"] == check_name)
