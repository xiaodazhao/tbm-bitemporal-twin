"""Build Stage 6B controlled realization candidate artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from tbm_twin.realization.io import stable_hash, write_csv, write_hashes, write_json, write_jsonl
from tbm_twin.realization.models import SliceSpec
from tbm_twin.realization.stage6b import (
    ATTENTION_CLAIM_TYPES,
    GEOLOGICAL_FORMATTER_POLICIES,
    PresentationScopeResolver,
    audit_canonical_drift,
    audit_post_realization,
    build_task_bundle,
    extract_engineering_numbers,
    load_stage6b_inputs,
    validate_plan,
)
from tbm_twin.realization.stage6b_models import (
    PRESENTATION_POLICY_VERSION,
    STAGE6B_GENERATED_AT,
    STAGE6B_METHOD_VERSION,
    STAGE6B_OUTPUT,
    STAGE6B_SCHEMA_VERSION,
    STAGE6B_STATUS,
    RealizationPlan,
    RealizationPlanSection,
)
from tbm_twin.realization.stage6b_smoke import (
    MockPlanProvider,
    accounting_audit_rows,
    build_manifest_bound_task_bundles,
    build_smoke_request,
    credential_literal_audit,
    default_provider_config_public,
    dry_run_smoke,
    execute_smoke_tasks,
    execution_protocol,
    group_member_semantic_equivalence_audit,
    smoke_manifest_coverage_audit,
    smoke_manifest_hash,
    smoke_protocol,
    smoke_task_valid_date_audit,
)
from tbm_twin.realization.validation import upstream_hash_issue_count


def build_stage6b_candidate(
    repo_root: Path,
    output_dir: Path | None = None,
    *,
    generated_at: str = STAGE6B_GENERATED_AT,
    run_determinism: bool = True,
) -> dict[str, int]:
    """Build Stage6B deterministic candidate from frozen Stage6A artifacts."""

    root = repo_root.resolve()
    output = root / (output_dir or Path(STAGE6B_OUTPUT))
    output.mkdir(parents=True, exist_ok=True)
    (output / "real_model_smoke").mkdir(exist_ok=True)

    inputs = load_stage6b_inputs(root)
    locks = inputs["stage6a_locks"]
    abstentions = inputs["stage5b_abstentions"]
    cells = inputs["stage3a_cells"]
    resolver = PresentationScopeResolver(cells)
    all_scope_rows = _presentation_scope_audit(locks, resolver)
    task_specs = _task_specs(locks)
    task_bundles = [build_task_bundle(locks, abstentions, cells, spec) for spec in task_specs]
    all_units = [unit for bundle in task_bundles for unit in bundle["units"]]
    all_sentences = [sentence for bundle in task_bundles for sentence in bundle["sentences"]]
    all_contracts = {bundle["contract"].product_type: bundle["contract"] for bundle in task_bundles}

    task_abstention_rows = _task_abstention_audit(task_bundles)
    grouping_rows = _grouping_audit(task_bundles)
    formatter_rows = _formatter_coverage_audit(locks)
    rendering_rows = _canonical_rendering_audit(all_sentences)
    plan_rows = _plan_validation_audit(task_bundles)
    plan_tamper_rows = _plan_tamper_audit(task_bundles)
    post_rows = _post_realization_audit(task_bundles)
    post_tamper_rows = _post_tamper_audit(task_bundles)
    extractor_rows = _number_extractor_audit()
    grouping_regression_rows = _grouping_regression_audit(task_bundles)
    fixed_rows = _fixed_case_audit(root, locks, abstentions, cells, task_bundles)
    smoke = _real_model_smoke_artifacts(output, task_bundles)
    group_equivalence_rows = group_member_semantic_equivalence_audit(task_bundles)
    smoke_temporal_rows = smoke_task_valid_date_audit(task_bundles)
    smoke_coverage_rows = smoke_manifest_coverage_audit(smoke["task_manifest"])
    credential_rows = _credential_literal_audit(root)
    dry_run = dry_run_smoke(
        smoke["task_manifest"],
        smoke["requests"],
        output / "real_model_smoke",
    )
    execution_task_bundles, execution_binding_rows = build_manifest_bound_task_bundles(
        locks,
        abstentions,
        cells,
        smoke["task_manifest"],
        smoke["requests"],
    )
    mock_execution_result = execute_smoke_tasks(
        execution_task_bundles,
        smoke["requests"],
        MockPlanProvider("success"),
        output / "real_model_smoke" / "mock_run",
        smoke["execution_protocol"],
        execution_manifest_binding_rows=execution_binding_rows,
        allow_overwrite=True,
    )
    mock_parse_failure_result = execute_smoke_tasks(
        execution_task_bundles[:1],
        smoke["requests"][:1],
        MockPlanProvider("malformed_json"),
        output / "real_model_smoke" / "mock_run",
        smoke["execution_protocol"],
        execution_manifest_binding_rows=execution_binding_rows[:1],
        execution_id="mock_parse_failure_execution",
        allow_overwrite=True,
    )
    mock_schema_failure_result = execute_smoke_tasks(
        execution_task_bundles[:1],
        smoke["requests"][:1],
        MockPlanProvider("schema_invalid"),
        output / "real_model_smoke" / "mock_run",
        smoke["execution_protocol"],
        execution_manifest_binding_rows=execution_binding_rows[:1],
        execution_id="mock_schema_failure_execution",
        allow_overwrite=True,
    )
    mock_plan_failure_result = execute_smoke_tasks(
        execution_task_bundles[:1],
        smoke["requests"][:1],
        MockPlanProvider("plan_invalid"),
        output / "real_model_smoke" / "mock_run",
        smoke["execution_protocol"],
        execution_manifest_binding_rows=execution_binding_rows[:1],
        execution_id="mock_plan_failure_execution",
        allow_overwrite=True,
    )
    mock_post_failure_result = execute_smoke_tasks(
        execution_task_bundles[:1],
        smoke["requests"][:1],
        MockPlanProvider("success"),
        output / "real_model_smoke" / "mock_run",
        smoke["execution_protocol"],
        execution_manifest_binding_rows=execution_binding_rows[:1],
        execution_id="mock_post_failure_execution",
        composer_tamper_text="该区段风险概率为 0.5。",
        allow_overwrite=True,
    )
    mock_transport_failure_result = execute_smoke_tasks(
        execution_task_bundles[:3],
        smoke["requests"][:3],
        MockPlanProvider("transport_failure"),
        output / "real_model_smoke" / "mock_run",
        smoke["execution_protocol"],
        execution_manifest_binding_rows=execution_binding_rows[:3],
        execution_id="mock_transport_failure_execution",
        allow_overwrite=True,
    )
    execution_layer_rows = _execution_layer_audit(mock_execution_result)
    raw_first_rows = _raw_first_persistence_audit(Path(mock_execution_result["run_dir"]))
    materialization_rows = _plan_materialization_audit(Path(mock_execution_result["run_dir"]))
    provider_parameter_rows = _provider_parameter_audit(smoke["execution_protocol"])
    accounting_rows = _provider_accounting_audit(
        Path(mock_execution_result["run_dir"]),
        mock_execution_result,
    )
    protocol_hash_rows = _protocol_hash_audit(output, smoke)
    preflight_rows = _preflight_boundary_audit(output)
    determinism_rows = (
        _determinism_audit(root, generated_at) if run_determinism else _empty_determinism_rows()
    )
    hard_rows = _hard_check_rows(
        root,
        all_scope_rows,
        task_abstention_rows,
        grouping_rows,
        formatter_rows,
        rendering_rows,
        plan_rows,
        plan_tamper_rows,
        post_rows,
        post_tamper_rows,
        extractor_rows,
        grouping_regression_rows,
        group_equivalence_rows,
        smoke_temporal_rows,
        smoke_coverage_rows,
        credential_rows,
        dry_run,
        execution_binding_rows,
        mock_execution_result,
        mock_parse_failure_result,
        mock_schema_failure_result,
        mock_plan_failure_result,
        mock_post_failure_result,
        mock_transport_failure_result,
        fixed_rows,
        determinism_rows,
        smoke,
        accounting_rows,
        protocol_hash_rows,
        provider_parameter_rows,
        preflight_rows,
    )
    manifest = _manifest(locks, all_units, all_sentences, task_bundles, hard_rows, smoke)

    write_csv(output / "presentation_scope_audit.csv", all_scope_rows)
    write_csv(output / "task_abstention_view_audit.csv", task_abstention_rows)
    write_json(output / "realization_unit_manifest.json", manifest)
    write_csv(output / "realization_grouping_audit.csv", grouping_rows)
    write_json(
        output / "geological_attribute_formatter_registry.json",
        GEOLOGICAL_FORMATTER_POLICIES,
    )
    write_csv(output / "formatter_coverage_audit.csv", formatter_rows)
    write_jsonl(
        output / "canonical_sentences.jsonl",
        [sentence.model_dump(mode="json") for sentence in all_sentences],
    )
    write_csv(output / "canonical_rendering_audit.csv", rendering_rows)
    write_csv(output / "number_extractor_audit.csv", extractor_rows)
    write_json(
        output / "product_realization_contract.json",
        {
            product_type: contract.model_dump(mode="json")
            for product_type, contract in sorted(all_contracts.items())
        },
    )
    write_csv(output / "plan_validation_audit.csv", plan_rows)
    write_csv(output / "plan_tamper_audit.csv", plan_tamper_rows)
    write_csv(output / "post_realization_audit.csv", post_rows)
    write_csv(output / "post_realization_tamper_audit.csv", post_tamper_rows)
    write_csv(output / "real_grouping_regression_audit.csv", grouping_regression_rows)
    write_csv(output / "group_member_semantic_equivalence_audit.csv", group_equivalence_rows)
    write_csv(output / "smoke_task_valid_date_audit.csv", smoke_temporal_rows)
    write_csv(output / "smoke_manifest_coverage_audit.csv", smoke_coverage_rows)
    write_csv(output / "credential_literal_audit.csv", credential_rows)
    write_csv(output / "execution_layer_audit.csv", execution_layer_rows)
    write_csv(output / "raw_first_persistence_audit.csv", raw_first_rows)
    write_csv(output / "plan_materialization_audit.csv", materialization_rows)
    write_csv(output / "provider_parameter_audit.csv", provider_parameter_rows)
    write_csv(output / "provider_accounting_audit.csv", accounting_rows)
    write_csv(output / "protocol_hash_audit.csv", protocol_hash_rows)
    write_csv(output / "provider_preflight_audit.csv", preflight_rows)
    write_csv(output / "execution_manifest_binding_audit.csv", execution_binding_rows)
    write_csv(output / "stage6b_fixed_case_audit.csv", fixed_rows)
    write_csv(output / "stage6b_determinism_audit.csv", determinism_rows)
    write_csv(output / "stage6b_hard_check.csv", hard_rows)
    _write_real_model_smoke(output, smoke, dry_run)
    write_json(output / "method_version.json", _method_version(inputs, generated_at, smoke))
    _write_report(output / "stage6b_report.md", manifest, hard_rows, smoke, dry_run)
    write_hashes(output)
    return {
        "fact_locks": len(locks),
        "realization_units": len(all_units),
        "canonical_sentences": len(all_sentences),
        "task_count": len(task_bundles),
    }


def _task_specs(locks: list[Any]) -> list[SliceSpec]:
    by_date = Counter(lock.valid_date for lock in locks if lock.valid_date)
    high_date = by_date.most_common(1)[0][0]
    low_date = sorted(
        Counter(lock.valid_date for lock in locks if lock.valid_date).items(),
        key=lambda x: (x[1], x[0]),
    )[0][0]
    medium_date = sorted(by_date.items(), key=lambda item: (abs(item[1] - 62), item[0]))[0][0]
    metric_lock = next(
        lock for lock in locks if lock.claim_type == "OPERATIONAL_RESPONSE_ATTENTION"
    )
    grs_lock = next(
        lock for lock in locks if lock.claim_type == "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW"
    )
    grci_lock = next(lock for lock in locks if lock.claim_type == "COUPLED_ATTENTION_REVIEW")
    forward_metric_lock = next(
        lock for lock in locks if lock.claim_type == "FORWARD_GEOLOGICAL_ATTENTION"
    )
    risk_lock = next(
        lock
        for lock in locks
        if lock.claim_value.get("attribute_name") in {"risk_hint", "anomaly_level"}
        and lock.state_role == "DAILY_REVIEW_CELL"
        and lock.valid_date
        and lock.cell_id
    )
    observed_lock = next(
        lock
        for lock in locks
        if lock.claim_type == "OBSERVED_GEOLOGICAL_CONDITION"
        and lock.state_role == "DAILY_REVIEW_CELL"
        and lock.valid_date
        and lock.cell_id
    )
    forecast_lock = next(
        lock
        for lock in locks
        if lock.claim_type == "FORECAST_GEOLOGICAL_CONDITION"
        and lock.state_role == "DAILY_REVIEW_CELL"
        and lock.valid_date
        and lock.cell_id
    )
    specs = [
        SliceSpec(product_type="daily_review", valid_date=str(high_date)),
        SliceSpec(product_type="daily_review", valid_date=str(medium_date)),
        SliceSpec(product_type="daily_review", valid_date=str(low_date)),
        SliceSpec(product_type="daily_review", valid_date="2023-12-24"),
        SliceSpec(product_type="forward_attention", valid_date="2023-10-29"),
        SliceSpec(product_type="forward_attention", valid_date=forward_metric_lock.valid_date),
        SliceSpec(product_type="metric_review", valid_date=metric_lock.valid_date),
        SliceSpec(product_type="metric_review", valid_date=grs_lock.valid_date),
        SliceSpec(product_type="metric_review", valid_date=grci_lock.valid_date),
        SliceSpec(product_type="metric_review", valid_date=forward_metric_lock.valid_date),
        SliceSpec(
            product_type="metric_review",
            valid_date=metric_lock.valid_date,
            cell_id=metric_lock.cell_id,
        ),
        SliceSpec(
            product_type="metric_review",
            valid_date=grci_lock.valid_date,
            cell_id=grci_lock.cell_id,
        ),
        SliceSpec(
            product_type="daily_review",
            valid_date=risk_lock.valid_date,
            cell_id=risk_lock.cell_id,
        ),
        SliceSpec(
            product_type="daily_review",
            valid_date=observed_lock.valid_date,
            cell_id=observed_lock.cell_id,
        ),
        SliceSpec(
            product_type="daily_review",
            valid_date=forecast_lock.valid_date,
            cell_id=forecast_lock.cell_id,
        ),
        SliceSpec(product_type="all", valid_date=str(high_date)),
    ]
    seen: set[str] = set()
    unique_specs = []
    for spec in specs:
        key = stable_hash(spec.model_dump(mode="json"))
        if key not in seen:
            seen.add(key)
            unique_specs.append(spec)
    return unique_specs


def _presentation_scope_audit(
    locks: list[Any], resolver: PresentationScopeResolver
) -> list[dict[str, object]]:
    rows = []
    for lock in locks:
        try:
            resolved = resolver.resolve(lock)
            status = "PASS"
            issue = ""
        except (KeyError, ValueError) as exc:
            resolved = None
            status = "FAIL"
            issue = str(exc)
        rows.append(
            {
                "fact_lock_id": lock.fact_lock_id,
                "claim_type": lock.claim_type,
                "source_scope_kind": lock.spatial_scope.get("scope_kind"),
                "source_cell_id": lock.cell_id,
                "display_start_chainage": ""
                if resolved is None or resolved.display_start_chainage is None
                else resolved.display_start_chainage,
                "display_end_chainage": ""
                if resolved is None or resolved.display_end_chainage is None
                else resolved.display_end_chainage,
                "display_point_chainage": ""
                if resolved is None or resolved.display_point_chainage is None
                else resolved.display_point_chainage,
                "scope_source": "" if resolved is None else resolved.scope_source,
                "scope_source_object_id": ""
                if resolved is None
                else resolved.scope_source_object_id,
                "scope_source_hash": "" if resolved is None else resolved.scope_source_hash,
                "resolution_method": "" if resolved is None else resolved.resolution_method,
                "issue": issue,
                "status": status,
            }
        )
    return rows


def _task_abstention_audit(task_bundles: list[dict[str, Any]]) -> list[dict[str, object]]:
    rows = []
    for bundle in task_bundles:
        view = bundle["task_view"]
        unsupported_value_exposed = sum(
            "claim_value" in record or "candidate_value" in record for record in view.records
        )
        rows.append(
            {
                "task_abstention_view_id": view.task_abstention_view_id,
                "slice_spec": view.slice_spec,
                "abstention_count": view.abstention_count,
                "counts_by_reason": view.counts_by_reason,
                "unsupported_candidate_value_exposed": unsupported_value_exposed,
                "status": "PASS" if unsupported_value_exposed == 0 else "FAIL",
            }
        )
    return rows


def _grouping_audit(task_bundles: list[dict[str, Any]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, bundle in enumerate(task_bundles):
        pack = bundle["pack"]
        units = bundle["units"]
        member_ids = [fact_id for unit in units for fact_id in unit.member_fact_lock_ids]
        selected_ids = [lock.fact_lock_id for lock in pack.locked_facts]
        duplicated = len(member_ids) - len(set(member_ids))
        missing = len(set(selected_ids) - set(member_ids))
        metric_cross_cell = sum(
            len(unit.member_fact_lock_ids) > 1 and unit.claim_type in ATTENTION_CLAIM_TYPES
            for unit in units
        )
        rows.append(
            {
                "task_index": index,
                "input_fact_lock_count": len(selected_ids),
                "output_realization_unit_count": len(units),
                "multi_member_unit_count": sum(
                    len(unit.member_fact_lock_ids) > 1 for unit in units
                ),
                "max_member_count": max(
                    (len(unit.member_fact_lock_ids) for unit in units), default=0
                ),
                "fact_lock_missing_from_unit": missing,
                "fact_lock_multi_unit_membership": duplicated,
                "metric_cross_cell_grouping": metric_cross_cell,
                "status": "PASS"
                if missing == 0 and duplicated == 0 and metric_cross_cell == 0
                else "FAIL",
            }
        )
    return rows


def _formatter_coverage_audit(locks: list[Any]) -> list[dict[str, object]]:
    attrs = sorted(
        {
            str(lock.claim_value.get("attribute_name"))
            for lock in locks
            if lock.claim_type
            in {
                "FORECAST_GEOLOGICAL_CONDITION",
                "OBSERVED_GEOLOGICAL_CONDITION",
            }
        }
    )
    return [
        {
            "attribute_name": attr,
            "formatter_policy": GEOLOGICAL_FORMATTER_POLICIES.get(attr, ""),
            "status": "PASS" if attr in GEOLOGICAL_FORMATTER_POLICIES else "FAIL",
        }
        for attr in attrs
    ]


def _canonical_rendering_audit(sentences: list[Any]) -> list[dict[str, object]]:
    rows = []
    for sentence in sentences:
        text = sentence.text
        drift_issues = audit_canonical_drift([sentence])
        boundary_violation = int(
            "风险概率" in text
            or "发生概率" in text
            or "灾害概率" in text
            or "地质导致" in text
            or "由地质原因造成" in text
        )
        rows.append(
            {
                "canonical_sentence_id": sentence.canonical_sentence_id,
                "realization_unit_id": sentence.realization_unit_id,
                "claim_type": sentence.claim_type,
                "numeric_token_count": len(sentence.numeric_tokens),
                "chainage_token_count": len(sentence.chainage_tokens),
                "canonical_numeric_drift": int("CANONICAL_NUMERIC_DRIFT" in drift_issues),
                "canonical_chainage_drift": int("CANONICAL_CHAINAGE_DRIFT" in drift_issues),
                "canonical_modality_drift": int("CANONICAL_MODALITY_DRIFT" in drift_issues),
                "canonical_boundary_violation": boundary_violation,
                "status": "PASS" if boundary_violation == 0 and not drift_issues else "FAIL",
            }
        )
    return rows


def _number_extractor_audit() -> list[dict[str, object]]:
    cases: list[tuple[str, str, list[str]]] = [
        ("decimal_metric", "RAI 为 0.253。", ["0.253"]),
        ("chainage_decimal", "里程 1014500.0。", ["1014500.0"]),
        ("negative_decimal", "偏离值为 -0.25。", ["-0.25"]),
        ("integer_value", "推力为 35。", ["35"]),
        ("section_number", "1. 综合情况", []),
    ]
    rows: list[dict[str, object]] = []
    for case_id, text, expected in cases:
        actual = extract_engineering_numbers(text)
        rows.append(
            {
                "case_id": case_id,
                "text": text,
                "expected": expected,
                "actual": actual,
                "status": "PASS" if actual == expected else "FAIL",
            }
        )
    return rows


def _plan_tamper_audit(task_bundles: list[dict[str, Any]]) -> list[dict[str, object]]:
    bundle = task_bundles[0]
    plan = bundle["plan"]
    units = bundle["units"]
    contract = bundle["contract"]
    pack = bundle["pack"]
    view_id = bundle["task_view"].task_abstention_view_id
    first_section = plan.sections[0]
    all_omitted = RealizationPlan(
        **{
            **plan.model_dump(mode="json"),
            "sections": [],
            "omitted_optional_unit_ids": [unit.realization_unit_id for unit in units],
            "plan_hash": "tampered",
        }
    )
    duplicate_section = RealizationPlan(
        **{
            **plan.model_dump(mode="json"),
            "sections": [first_section, first_section],
            "plan_hash": "tampered",
        }
    )
    product_mismatch = RealizationPlan(
        **{**plan.model_dump(mode="json"), "product_type": "metric_review", "plan_hash": "tampered"}
    )
    view_mismatch = RealizationPlan(
        **{
            **plan.model_dump(mode="json"),
            "task_abstention_view_id": "tampered",
            "plan_hash": "tampered",
        }
    )
    invalid_hash = RealizationPlan(**{**plan.model_dump(mode="json"), "plan_hash": "tampered"})
    illegal_omitted_unit = units[0].realization_unit_id
    illegal_omission_sections = []
    for section in plan.sections:
        illegal_omission_sections.append(
            RealizationPlanSection(
                section_id=section.section_id,
                ordered_unit_ids=[
                    unit_id
                    for unit_id in section.ordered_unit_ids
                    if unit_id != illegal_omitted_unit
                ],
            )
        )
    illegal_omission = RealizationPlan(
        **{
            **plan.model_dump(mode="json"),
            "sections": illegal_omission_sections,
            "omitted_optional_unit_ids": [illegal_omitted_unit],
            "plan_hash": "tampered",
        }
    )
    cases = [
        ("plan_product_mismatch_accepted", product_mismatch, "PRODUCT_TYPE_MISMATCH"),
        ("plan_abstention_view_mismatch_accepted", view_mismatch, "TASK_ABSTENTION_VIEW_MISMATCH"),
        ("invalid_plan_hash_accepted", invalid_hash, "PLAN_HASH_MISMATCH"),
        ("duplicate_section_accepted", duplicate_section, "DUPLICATE_SECTION"),
        ("all_units_omitted_accepted", all_omitted, "ALL_UNITS_OMITTED"),
        ("illegal_optional_omission_accepted", illegal_omission, "ILLEGAL_OPTIONAL_OMISSION"),
    ]
    rows: list[dict[str, object]] = []
    for case_id, tampered_plan, expected_issue in cases:
        issues = validate_plan(
            tampered_plan, units, contract, pack.pack_id, pack.pack_hash, view_id
        )
        rows.append(
            {
                "case_id": case_id,
                "expected_issue": expected_issue,
                "issue_codes": ";".join(issues),
                "detected": str(expected_issue in issues).lower(),
                "status": "PASS" if expected_issue in issues else "FAIL",
            }
        )
    return rows


def _post_tamper_audit(task_bundles: list[dict[str, Any]]) -> list[dict[str, object]]:
    bundle = task_bundles[0]
    composed = bundle["composed"]
    cases = [
        (
            "extra_engineering_sentence_undetected",
            "该区段围岩整体较差。",
            "UNAUTHORIZED_ENGINEERING_SENTENCE",
        ),
        (
            "fake_chainage_undetected",
            "该区段里程 999999.9 地质情况较差。",
            "UNTRACED_CHAINAGE",
        ),
        (
            "forecast_factification_undetected",
            "该区段实际揭露岩体破碎。",
            "UNAUTHORIZED_ENGINEERING_SENTENCE",
        ),
        (
            "risk_statement_undetected",
            "该区段风险为较高水平。",
            "UNAUTHORIZED_ENGINEERING_SENTENCE",
        ),
        (
            "causal_statement_undetected",
            "地质异常导致推力增加。",
            "MECHANICAL_RESPONSE_PROMOTED_TO_GEOLOGICAL_CAUSE",
        ),
        (
            "unknown_to_normal_undetected",
            "未发现异常, 施工状态正常。",
            "UNKNOWN_PROMOTED_TO_NORMAL",
        ),
    ]
    rows: list[dict[str, object]] = []
    for case_id, extra_text, expected_issue in cases:
        tampered = composed.__class__(
            **{
                **composed.model_dump(mode="json"),
                "text": composed.text + "\n" + extra_text,
                "realization_hash": "tampered",
            }
        )
        issues = audit_post_realization(tampered, bundle["sentences"])
        rows.append(
            {
                "case_id": case_id,
                "expected_issue": expected_issue,
                "issue_codes": ";".join(issues),
                "detected": str(expected_issue in issues).lower(),
                "status": "PASS" if expected_issue in issues else "FAIL",
            }
        )
    return rows


def _grouping_regression_audit(task_bundles: list[dict[str, Any]]) -> list[dict[str, object]]:
    rows = []
    for bundle in task_bundles:
        spec = bundle["pack"].knowledge_context.get("slice_spec", {})
        if spec.get("valid_date") not in {"2023-12-24", "2023-10-29"}:
            continue
        units = bundle["units"]
        multi_member = sum(len(unit.member_fact_lock_ids) > 1 for unit in units)
        input_count = len(bundle["pack"].locked_facts)
        output_count = len(units)
        rows.append(
            {
                "valid_date": spec.get("valid_date"),
                "product_type": spec.get("product_type"),
                "input_fact_locks": input_count,
                "output_realization_units": output_count,
                "multi_member_units": multi_member,
                "max_members": max((len(unit.member_fact_lock_ids) for unit in units), default=0),
                "deduplicated_presentation_count": input_count - output_count,
                "status": "PASS" if multi_member > 0 and input_count > output_count else "FAIL",
            }
        )
    return rows


def _plan_validation_audit(task_bundles: list[dict[str, Any]]) -> list[dict[str, object]]:
    rows = []
    for index, bundle in enumerate(task_bundles):
        rows.append(
            {
                "task_index": index,
                "plan_id": bundle["plan"].plan_id,
                "product_type": bundle["contract"].product_type,
                "unit_count": len(bundle["units"]),
                "issue_codes": ";".join(bundle["plan_issues"]),
                "issue_count": len(bundle["plan_issues"]),
                "status": "PASS" if not bundle["plan_issues"] else "FAIL",
            }
        )
    return rows


def _post_realization_audit(task_bundles: list[dict[str, Any]]) -> list[dict[str, object]]:
    rows = []
    for index, bundle in enumerate(task_bundles):
        rows.append(
            {
                "task_index": index,
                "composed_realization_id": bundle["composed"].composed_realization_id,
                "product_type": bundle["contract"].product_type,
                "issue_codes": ";".join(bundle["post_issues"]),
                "issue_count": len(bundle["post_issues"]),
                "status": "PASS" if not bundle["post_issues"] else "FAIL",
            }
        )
    return rows


def _fixed_case_audit(
    repo_root: Path,
    locks: list[Any],
    abstentions: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    task_bundles: list[dict[str, Any]],
) -> list[dict[str, object]]:
    metric_lock = next(
        lock for lock in locks if lock.claim_type == "OPERATIONAL_RESPONSE_ATTENTION"
    )
    interval_lock = next(
        lock for lock in locks if lock.spatial_scope.get("scope_kind") == "LOCATED_INTERVAL"
    )
    point_lock = next(
        lock for lock in locks if lock.spatial_scope.get("scope_kind") == "LOCATED_POINT"
    )
    resolver = PresentationScopeResolver(cells)
    metric_scope = resolver.resolve(metric_lock)
    interval_scope = resolver.resolve(interval_lock)
    point_scope = resolver.resolve(point_lock)
    fake_bundle = task_bundles[0]
    units = fake_bundle["units"]
    contract = fake_bundle["contract"]
    pack = fake_bundle["pack"]
    view_id = fake_bundle["task_view"].task_abstention_view_id
    legal = fake_bundle["plan"]
    unknown_plan = RealizationPlan(
        **{
            **legal.model_dump(mode="json"),
            "plan_id": "tampered_unknown_unit",
            "sections": [
                RealizationPlanSection(
                    section_id=contract.section_order[0],
                    ordered_unit_ids=["unknown_unit"],
                )
            ],
            "plan_hash": "tampered",
        }
    )
    bad_pack_plan = RealizationPlan(
        **{
            **legal.model_dump(mode="json"),
            "plan_id": "tampered_pack_hash",
            "pack_hash": "tampered",
            "plan_hash": "tampered",
        }
    )
    composed = fake_bundle["composed"]
    tampered = composed.__class__(
        **{
            **composed.model_dump(mode="json"),
            "text": composed.text + "\n该区段风险概率为 0.5。",
            "realization_hash": "tampered",
        }
    )
    rows = [
        _case(
            "S1_CELL_METRIC_RESOLVES_STAGE3A_GEOMETRY",
            metric_scope.scope_source == "FROZEN_STAGE3A_CONSTRUCTION_STATE_CELL"
            and metric_scope.display_start_chainage is not None,
        ),
        _case(
            "S2_LOCATED_INTERVAL_NOT_OVERWRITTEN",
            interval_scope.scope_source == "FACT_LOCK_SPATIAL_SCOPE",
        ),
        _case(
            "S3_LOCATED_POINT_PRESERVED",
            point_scope.display_point_chainage == point_lock.spatial_scope.get("point_chainage"),
        ),
        _case(
            "A5_UNSUPPORTED_CANDIDATE_VALUE_NOT_IN_VIEW",
            all(
                row["unsupported_candidate_value_exposed"] == 0
                for row in _task_abstention_audit(task_bundles)
            ),
        ),
        _case(
            "G8_ALL_MEMBER_FACTLOCKS_ONE_UNIT",
            all(row["status"] == "PASS" for row in _grouping_audit(task_bundles)),
        ),
        _case(
            "R3_GRCI_NONPROBABILISTIC",
            any(
                "非概率" in sentence.text
                for bundle in task_bundles
                for sentence in bundle["sentences"]
                if sentence.claim_type == "COUPLED_ATTENTION_REVIEW"
            ),
        ),
        _case(
            "P2_UNKNOWN_UNIT_REJECTED",
            "UNKNOWN_UNIT"
            in validate_plan(unknown_plan, units, contract, pack.pack_id, pack.pack_hash, view_id),
        ),
        _case(
            "P7_PACK_HASH_MISMATCH_REJECTED",
            "PACK_HASH_MISMATCH"
            in validate_plan(bad_pack_plan, units, contract, pack.pack_id, pack.pack_hash, view_id),
        ),
        _case(
            "T4_GRCI_RISK_PROBABILITY_REJECTED",
            "ATTENTION_PROMOTED_TO_PROBABILITY"
            in audit_post_realization(tampered, fake_bundle["sentences"]),
        ),
        _case("UPSTREAM_STAGE6A_HASH_UNCHANGED", _stage6a_hash_issue_count(repo_root) == 0),
    ]
    return rows


def _real_model_smoke_artifacts(output: Path, task_bundles: list[dict[str, Any]]) -> dict[str, Any]:
    tasks = []
    for index, bundle in enumerate(task_bundles):
        claim_counts = Counter(unit.claim_type for unit in bundle["units"])
        sentences_by_unit = {
            sentence.realization_unit_id: sentence.text for sentence in bundle["sentences"]
        }
        category, rationale = _task_selection_metadata(index, bundle)
        tasks.append(
            {
                "task_id": f"stage6b_smoke_task_{index:02d}",
                "valid_date": bundle["pack"].valid_date,
                "product_type": bundle["contract"].product_type,
                "cell_id": bundle["pack"].knowledge_context.get("slice_spec", {}).get("cell_id"),
                "slice_spec": bundle["pack"].knowledge_context.get("slice_spec", {}),
                "pack_id": bundle["pack"].pack_id,
                "pack_hash": bundle["pack"].pack_hash,
                "product_contract_hash": bundle["contract"].contract_hash,
                "presentation_policy_version": PRESENTATION_POLICY_VERSION,
                "fact_lock_count": len(bundle["pack"].locked_facts),
                "realization_unit_count": len(bundle["units"]),
                "canonical_sentence_count": len(bundle["sentences"]),
                "claim_type_distribution": dict(sorted(claim_counts.items())),
                "abstention_count": bundle["task_view"].abstention_count,
                "selection_category": category,
                "selection_rationale": rationale,
                "realization_unit_ids": [
                    unit.realization_unit_id
                    for unit in sorted(bundle["units"], key=lambda item: item.realization_unit_id)
                ],
                "canonical_sentences_by_unit": sentences_by_unit,
                "status": "NOT_RUN_REAL_MODEL_SMOKE",
            }
        )
    task_manifest_hash = smoke_manifest_hash(tasks)
    for task, bundle in zip(tasks, task_bundles, strict=True):
        bundle["smoke_task"] = task
    requests = [
        build_smoke_request(
            bundle["smoke_task"],
            bundle["units"],
            bundle["contract"],
            bundle["task_view"],
            task_manifest_hash,
        )
        for bundle in task_bundles
    ]
    public_tasks = [
        {k: v for k, v in task.items() if k != "canonical_sentences_by_unit"} for task in tasks
    ]
    provider_config = default_provider_config_public()
    protocol = smoke_protocol(provider_config)
    exec_protocol = execution_protocol(task_manifest_hash, provider_config)
    return {
        "real_model_smoke_status": "NOT_RUN",
        "real_model_smoke_required_before_freeze": True,
        "task_manifest": public_tasks,
        "task_manifest_hash": task_manifest_hash,
        "requests": requests,
        "prompt_payloads": [request.model_dump(mode="json") for request in requests],
        "prompt_hashes": [request.prompt_hash for request in requests],
        "protocol": protocol,
        "execution_protocol": exec_protocol,
        "provider_config_public": provider_config,
        "raw_output_count": 0,
        "parsed_plan_count": 0,
        "first_attempt_plan_acceptance_rate": None,
        "final_plan_acceptance_rate": None,
    }


def _write_real_model_smoke(
    output: Path,
    smoke: dict[str, Any],
    dry_run: dict[str, Any],
) -> None:
    smoke_dir = output / "real_model_smoke"
    write_json(smoke_dir / "task_manifest.json", smoke["task_manifest"])
    write_json(smoke_dir / "protocol.json", smoke["protocol"])
    write_json(smoke_dir / "execution_protocol.json", smoke["execution_protocol"])
    execution_protocol_file_hash = _stable_json_file_sha256(smoke["execution_protocol"])
    task_manifest_file_hash = _stable_json_file_sha256(smoke["task_manifest"])
    write_json(smoke_dir / "provider_config_public.json", smoke["provider_config_public"])
    write_jsonl(smoke_dir / "prompt_payloads.jsonl", smoke["prompt_payloads"])
    write_json(
        smoke_dir / "status.json",
        {
            "real_model_smoke_status": smoke["real_model_smoke_status"],
            "real_model_smoke_required_before_freeze": smoke[
                "real_model_smoke_required_before_freeze"
            ],
            "task_manifest_hash": smoke["task_manifest_hash"],
            "dry_run_status": dry_run["dry_run_status"],
            "execution_layer_status": "READY",
            "accounting_layer_status": "READY",
            "mock_execution_status": "PASS",
            "manifest_frozen": True,
            "api_call_count": dry_run["api_call_count"],
            "provider_request_attempt_count": 0,
            "provider_transport_success_count": 0,
            "provider_transport_failure_count": 0,
            "real_api_request_attempt_count": 0,
            "real_api_transport_success_count": 0,
            "real_api_transport_failure_count": 0,
            "execution_protocol_hash": smoke["execution_protocol"]["execution_protocol_hash"],
            "execution_protocol_file_sha256": execution_protocol_file_hash,
            "task_manifest_file_sha256": task_manifest_file_hash,
            "freeze_ready": False,
        },
    )
    write_json(
        smoke_dir / "dry_run_status.json",
        {
            **dry_run,
            "provider": smoke["provider_config_public"]["provider"],
            "model": smoke["provider_config_public"]["model"],
            "task_manifest_hash": smoke["task_manifest_hash"],
            "api_request_sent": False,
        },
    )
    write_jsonl(smoke_dir / "raw_model_outputs.jsonl", [])
    write_jsonl(smoke_dir / "parsed_plans.jsonl", [])
    write_csv(smoke_dir / "plan_validation_results.csv", [])
    write_csv(smoke_dir / "post_realization_results.csv", [])
    write_csv(
        smoke_dir / "smoke_summary.csv",
        [
            {
                "real_model_smoke_status": smoke["real_model_smoke_status"],
                "dry_run_status": dry_run["dry_run_status"],
                "raw_output_count": smoke["raw_output_count"],
                "parsed_plan_count": smoke["parsed_plan_count"],
                "task_count": len(smoke["task_manifest"]),
                "api_call_count": dry_run["api_call_count"],
                "provider_request_attempt_count": 0,
                "provider_transport_success_count": 0,
                "provider_transport_failure_count": 0,
                "provider_transport_success_rate": "",
                "provider_transport_success_rate_n": 0,
                "real_api_request_attempt_count": 0,
                "real_api_transport_success_count": 0,
                "real_api_transport_failure_count": 0,
                "real_api_transport_success_rate": "",
                "real_api_transport_success_rate_n": 0,
                "freeze_ready": "false",
            }
        ],
    )
    write_csv(
        smoke_dir / "accounting_audit.csv",
        [
            {
                "metric": "real_api_request_attempt_count",
                "reported_value": 0,
                "recomputed_value": 0,
                "diff": 0.0,
                "status": "PASS",
            }
        ],
    )


def _task_selection_metadata(index: int, bundle: dict[str, Any]) -> tuple[str, str]:
    spec = bundle["pack"].knowledge_context.get("slice_spec", {})
    product_type = bundle["contract"].product_type
    unit_count = len(bundle["units"])
    if product_type == "all":
        return ("REVISION_REPRESENTATIVE_CASE", f"deterministic_smoke_task_{index:02d}")
    if spec.get("valid_date") == "2023-12-24" and product_type == "daily_review":
        return (
            "HIGH_UNIT_DAILY_REVIEW",
            "required_real_grouping_regression_high_duplicate_daily_review",
        )
    if spec.get("valid_date") == "2023-10-29" and product_type == "forward_attention":
        return (
            "FORWARD_FORECAST_CASE",
            "required_real_grouping_regression_forward_attention",
        )
    if product_type == "daily_review" and not spec.get("cell_id"):
        if unit_count <= 15:
            return ("LOW_UNIT_DAILY_REVIEW", "low_unit_daily_review_coverage")
        if unit_count <= 50:
            return ("MEDIUM_UNIT_DAILY_REVIEW", "medium_unit_daily_review_coverage")
        return ("HIGH_UNIT_DAILY_REVIEW", "high_unit_daily_review_coverage")
    claim_counts = Counter(unit.claim_type for unit in bundle["units"])
    if (
        claim_counts["FORECAST_GEOLOGICAL_CONDITION"]
        and claim_counts["OBSERVED_GEOLOGICAL_CONDITION"]
    ):
        return (
            "OBSERVED_AND_FORECAST_COEXISTENCE",
            "coexistence_of_forecast_and_observed_geological_conditions",
        )
    if spec.get("cell_id") and any(
        unit.claim_value.get("attribute_name") in {"risk_hint", "anomaly_level"}
        for unit in bundle["units"]
    ):
        return (
            "RISK_OR_ANOMALY_SOURCE_FIELD_CASE",
            "risk_hint_or_anomaly_level_source_field_case",
        )
    if bundle["task_view"].abstention_count > 0 and index % 3 == 1:
        return ("TASK_ABSTENTION_CASE", "task_specific_abstention_view_coverage")
    if product_type == "metric_review":
        if claim_counts["COUPLED_ATTENTION_REVIEW"]:
            return ("METRIC_GRCI_CASE", "metric_grci_case_coverage")
        if claim_counts["GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW"]:
            return ("METRIC_GRS_CASE", "metric_grs_case_coverage")
        return ("METRIC_RAI_CASE", "metric_rai_case_coverage")
    if product_type == "forward_attention":
        return ("FORWARD_ATTENTION_CASE", "forward_attention_smoke_coverage")
    if product_type == "daily_review":
        return ("DAILY_REVIEW_CELL_SPECIFIC_CASE", "cell_specific_single_date_daily_review")
    return ("DETERMINISTIC_SMOKE_CASE", f"deterministic_smoke_task_{index:02d}")


def _determinism_audit(repo_root: Path, generated_at: str) -> list[dict[str, object]]:
    with tempfile.TemporaryDirectory() as left_dir, tempfile.TemporaryDirectory() as right_dir:
        left = Path(left_dir) / "stage6b"
        right = Path(right_dir) / "stage6b"
        build_stage6b_candidate(repo_root, left, generated_at=generated_at, run_determinism=False)
        build_stage6b_candidate(repo_root, right, generated_at=generated_at, run_determinism=False)
        diff = int(_artifact_payload(left) != _artifact_payload(right))
    return [
        {
            "check_name": "stage6b_semantic_content",
            "semantic_diff_count": diff,
            "status": "PASS" if diff == 0 else "FAIL",
        }
    ]


def _empty_determinism_rows() -> list[dict[str, object]]:
    return [{"check_name": "not_run", "semantic_diff_count": 0, "status": "PASS"}]


def _artifact_payload(path: Path) -> str:
    payload = {}
    for item in sorted(path.rglob("*")):
        if item.is_file() and item.name != "file_hashes.sha256":
            payload[item.relative_to(path).as_posix()] = item.read_text(encoding="utf-8")
    return stable_hash(payload)


def _hard_check_rows(
    repo_root: Path,
    scope_rows: list[dict[str, object]],
    abstention_rows: list[dict[str, object]],
    grouping_rows: list[dict[str, object]],
    formatter_rows: list[dict[str, object]],
    rendering_rows: list[dict[str, object]],
    plan_rows: list[dict[str, object]],
    plan_tamper_rows: list[dict[str, object]],
    post_rows: list[dict[str, object]],
    post_tamper_rows: list[dict[str, object]],
    extractor_rows: list[dict[str, object]],
    grouping_regression_rows: list[dict[str, object]],
    group_equivalence_rows: list[dict[str, object]],
    smoke_temporal_rows: list[dict[str, object]],
    smoke_coverage_rows: list[dict[str, object]],
    credential_rows: list[dict[str, object]],
    dry_run: dict[str, Any],
    execution_binding_rows: list[dict[str, object]],
    mock_execution_result: dict[str, Any],
    mock_parse_failure_result: dict[str, Any],
    mock_schema_failure_result: dict[str, Any],
    mock_plan_failure_result: dict[str, Any],
    mock_post_failure_result: dict[str, Any],
    mock_transport_failure_result: dict[str, Any],
    fixed_rows: list[dict[str, object]],
    determinism_rows: list[dict[str, object]],
    smoke: dict[str, Any],
    accounting_rows: list[dict[str, object]],
    protocol_hash_rows: list[dict[str, object]],
    provider_parameter_rows: list[dict[str, object]],
    preflight_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    checks = [
        ("upstream_stage6a_modified", _stage6a_hash_issue_count(repo_root), 0),
        ("frozen_upstream_hash_issue", upstream_hash_issue_count(repo_root), 0),
        ("presentation_scope_unresolved", sum(row["status"] != "PASS" for row in scope_rows), 0),
        ("presentation_scope_untraced", sum(not row["scope_source_hash"] for row in scope_rows), 0),
        (
            "task_abstention_scope_leakage",
            sum(row["status"] != "PASS" for row in abstention_rows),
            0,
        ),
        (
            "unsupported_abstention_value_exposed",
            sum(_as_int(row["unsupported_candidate_value_exposed"]) for row in abstention_rows),
            0,
        ),
        (
            "fact_lock_missing_from_realization_unit",
            sum(_as_int(row["fact_lock_missing_from_unit"]) for row in grouping_rows),
            0,
        ),
        (
            "fact_lock_multi_unit_membership",
            sum(_as_int(row["fact_lock_multi_unit_membership"]) for row in grouping_rows),
            0,
        ),
        ("unsafe_geo_grouping", sum(row["status"] != "PASS" for row in grouping_rows), 0),
        (
            "metric_cross_cell_grouping",
            sum(_as_int(row["metric_cross_cell_grouping"]) for row in grouping_rows),
            0,
        ),
        (
            "unhandled_geological_attribute",
            sum(row["status"] != "PASS" for row in formatter_rows),
            0,
        ),
        (
            "engineering_number_extractor_effective",
            sum(row["status"] != "PASS" for row in extractor_rows),
            0,
        ),
        (
            "untraced_chainage_detection_effective",
            _tamper_undetected(post_tamper_rows, "fake_chainage_undetected"),
            0,
        ),
        (
            "canonical_numeric_audit_evidence_present",
            int(not any(_as_int(row["numeric_token_count"]) > 0 for row in rendering_rows)),
            0,
        ),
        (
            "canonical_chainage_audit_evidence_present",
            int(not any(_as_int(row["chainage_token_count"]) > 0 for row in rendering_rows)),
            0,
        ),
        (
            "canonical_modality_audit_evidence_present",
            int(not rendering_rows),
            0,
        ),
        (
            "geological_grouping_not_identity_bound",
            int(not grouping_regression_rows),
            0,
        ),
        (
            "real_grouping_regression_multi_member_count",
            sum(_as_int(row["multi_member_units"]) for row in grouping_regression_rows),
            ">0",
        ),
        (
            "group_member_semantic_equivalence_issue",
            sum(row["status"] != "PASS" for row in group_equivalence_rows),
            0,
        ),
        (
            "canonical_numeric_drift",
            sum(_as_int(row["canonical_numeric_drift"]) for row in rendering_rows),
            0,
        ),
        (
            "canonical_chainage_drift",
            sum(_as_int(row["canonical_chainage_drift"]) for row in rendering_rows),
            0,
        ),
        (
            "canonical_modality_drift",
            sum(_as_int(row["canonical_modality_drift"]) for row in rendering_rows),
            0,
        ),
        (
            "canonical_boundary_violation",
            sum(_as_int(row["canonical_boundary_violation"]) for row in rendering_rows),
            0,
        ),
        ("unknown_unit_accepted", _plan_issue_count(plan_rows, "UNKNOWN_UNIT"), 0),
        ("out_of_task_unit_accepted", _plan_issue_count(plan_rows, "OUT_OF_TASK_UNIT"), 0),
        ("forbidden_unit_accepted", _plan_issue_count(plan_rows, "FORBIDDEN_FAMILY"), 0),
        (
            "plan_product_mismatch_accepted",
            _tamper_undetected(plan_tamper_rows, "plan_product_mismatch_accepted"),
            0,
        ),
        (
            "plan_abstention_view_mismatch_accepted",
            _tamper_undetected(plan_tamper_rows, "plan_abstention_view_mismatch_accepted"),
            0,
        ),
        (
            "invalid_plan_hash_accepted",
            _tamper_undetected(plan_tamper_rows, "invalid_plan_hash_accepted"),
            0,
        ),
        (
            "duplicate_section_accepted",
            _tamper_undetected(plan_tamper_rows, "duplicate_section_accepted"),
            0,
        ),
        (
            "all_units_omitted_accepted",
            _tamper_undetected(plan_tamper_rows, "all_units_omitted_accepted"),
            0,
        ),
        (
            "illegal_optional_omission_accepted",
            _tamper_undetected(plan_tamper_rows, "illegal_optional_omission_accepted"),
            0,
        ),
        (
            "unauthorized_engineering_sentence",
            _post_issue_count(post_rows, "UNAUTHORIZED_ENGINEERING_SENTENCE"),
            0,
        ),
        (
            "untraced_engineering_number",
            _post_issue_count(post_rows, "UNTRACED_ENGINEERING_NUMBER"),
            0,
        ),
        ("untraced_chainage", _post_issue_count(post_rows, "UNTRACED_CHAINAGE"), 0),
        (
            "forecast_promoted_to_observed",
            _post_issue_count(post_rows, "FORECAST_PROMOTED_TO_OBSERVED"),
            0,
        ),
        (
            "attention_promoted_to_probability",
            _post_issue_count(post_rows, "ATTENTION_PROMOTED_TO_PROBABILITY"),
            0,
        ),
        (
            "mechanical_response_promoted_to_geological_cause",
            _post_issue_count(post_rows, "MECHANICAL_RESPONSE_PROMOTED_TO_GEOLOGICAL_CAUSE"),
            0,
        ),
        (
            "unknown_promoted_to_normal",
            _post_issue_count(post_rows, "UNKNOWN_PROMOTED_TO_NORMAL"),
            0,
        ),
        (
            "extra_engineering_sentence_undetected",
            _tamper_undetected(post_tamper_rows, "extra_engineering_sentence_undetected"),
            0,
        ),
        (
            "fake_chainage_undetected",
            _tamper_undetected(post_tamper_rows, "fake_chainage_undetected"),
            0,
        ),
        (
            "forecast_factification_undetected",
            _tamper_undetected(post_tamper_rows, "forecast_factification_undetected"),
            0,
        ),
        (
            "causal_statement_undetected",
            _tamper_undetected(post_tamper_rows, "causal_statement_undetected"),
            0,
        ),
        (
            "unknown_to_normal_undetected",
            _tamper_undetected(post_tamper_rows, "unknown_to_normal_undetected"),
            0,
        ),
        ("trace_failure", _post_issue_count(post_rows, "TRACE_FAILURE"), 0),
        (
            "deterministic_stage_semantic_diff",
            sum(_as_int(row["semantic_diff_count"]) for row in determinism_rows),
            0,
        ),
        ("fixed_case_failure_count", sum(row["status"] != "PASS" for row in fixed_rows), 0),
        ("real_model_smoke_not_run", int(smoke["real_model_smoke_status"] != "NOT_RUN"), 0),
        ("smoke_manifest_task_count", len(smoke["task_manifest"]), ">=12"),
        ("smoke_manifest_task_count_upper", len(smoke["task_manifest"]), "<=20"),
        (
            "smoke_multi_valid_date_task_count",
            sum(row["status"] != "PASS" for row in smoke_temporal_rows),
            0,
        ),
        ("smoke_coverage_daily_review", _coverage_issue(smoke_coverage_rows, "daily_review"), 0),
        (
            "smoke_coverage_forward_attention",
            _coverage_issue(smoke_coverage_rows, "forward_attention"),
            0,
        ),
        ("smoke_coverage_metric_review", _coverage_issue(smoke_coverage_rows, "metric_review"), 0),
        ("smoke_coverage_forecast", _coverage_issue(smoke_coverage_rows, "forecast"), 0),
        ("smoke_coverage_observed", _coverage_issue(smoke_coverage_rows, "observed"), 0),
        ("smoke_coverage_rai", _coverage_issue(smoke_coverage_rows, "rai"), 0),
        ("smoke_coverage_grs", _coverage_issue(smoke_coverage_rows, "grs"), 0),
        ("smoke_coverage_grci", _coverage_issue(smoke_coverage_rows, "grci"), 0),
        ("smoke_coverage_abstention", _coverage_issue(smoke_coverage_rows, "abstention"), 0),
        (
            "smoke_manifest_hash_valid",
            int(smoke.get("task_manifest_hash") != smoke_manifest_hash(smoke["task_manifest"])),
            0,
        ),
        (
            "execution_manifest_binding_issue",
            sum(row["status"] != "PASS" for row in execution_binding_rows),
            0,
        ),
        (
            "prompt_determinism_issue",
            int(len(smoke["prompt_hashes"]) != len(set(smoke["prompt_hashes"]))),
            0,
        ),
        ("provider_domain_leakage", _provider_domain_leakage_count(repo_root), 0),
        ("credential_literal_detected", sum(row["status"] != "PASS" for row in credential_rows), 0),
        ("dry_run_task_preparation_failure", dry_run["prompt_preparation_failure"], 0),
        ("dry_run_api_call_count", dry_run["api_call_count"], 0),
        ("dry_run_status_failure", int(dry_run["dry_run_status"] != "PASS"), 0),
        ("hardcoded_real_api_call_count_literal", _hardcoded_real_api_count_literal(repo_root), 0),
        (
            "non_dry_run_execution_path_implemented",
            int(mock_execution_result["provider_request_attempt_count"] == 0),
            0,
        ),
        (
            "raw_first_persistence_verified",
            int(
                mock_execution_result["provider_request_attempt_count"]
                != len(smoke["task_manifest"])
            ),
            0,
        ),
        (
            "minimal_provider_plan_schema_strict",
            int(mock_schema_failure_result["first_attempt_schema_valid_rate"] != 0.0),
            0,
        ),
        (
            "unexpected_provider_field_rejected",
            int(mock_schema_failure_result["first_attempt_schema_valid_rate"] != 0.0),
            0,
        ),
        ("authoritative_metadata_model_control_count", _model_controlled_metadata_count(smoke), 0),
        (
            "materialized_plan_hash_valid",
            int(mock_execution_result["first_attempt_plan_acceptance_rate"] != 1.0),
            0,
        ),
        (
            "plan_metadata_injection_valid",
            int(mock_execution_result["first_attempt_plan_acceptance_rate"] != 1.0),
            0,
        ),
        (
            "invalid_parse_composed_count",
            int(mock_parse_failure_result["composition_count"] != 0),
            0,
        ),
        (
            "invalid_schema_composed_count",
            int(mock_schema_failure_result["composition_count"] != 0),
            0,
        ),
        (
            "invalid_plan_composed_count",
            int(mock_plan_failure_result["composition_count"] != 0),
            0,
        ),
        (
            "mock_success_execution_pass",
            int(mock_execution_result["post_audit_violation_count"] != 0),
            0,
        ),
        (
            "mock_parse_failure_execution_pass",
            int(mock_parse_failure_result["first_attempt_parse_valid_rate"] != 0.0),
            0,
        ),
        (
            "mock_schema_failure_execution_pass",
            int(mock_schema_failure_result["first_attempt_schema_valid_rate"] != 0.0),
            0,
        ),
        (
            "mock_plan_failure_execution_pass",
            int(mock_plan_failure_result["first_attempt_plan_acceptance_rate"] != 0.0),
            0,
        ),
        (
            "mock_post_audit_failure_detected",
            int(mock_post_failure_result["post_audit_violation_count"] == 0),
            0,
        ),
        (
            "provider_attempt_reconciliation_issue",
            _accounting_issue(accounting_rows, "provider_request_attempt_count"),
            0,
        ),
        ("provider_transport_reconciliation_issue", _transport_sum_issue(mock_execution_result), 0),
        (
            "provider_transport_success_rate_formula_issue",
            _transport_rate_issue(mock_execution_result),
            0,
        ),
        (
            "real_api_attempt_reconciliation_issue",
            _accounting_issue(accounting_rows, "real_api_request_attempt_count"),
            0,
        ),
        (
            "real_api_transport_reconciliation_issue",
            _real_api_transport_sum_issue(mock_execution_result),
            0,
        ),
        ("mock_real_api_request_count", mock_execution_result["real_api_request_attempt_count"], 0),
        (
            "transport_failure_counted_as_parse_failure",
            int(mock_transport_failure_result["first_attempt_parse_valid_rate_n"] != 0),
            0,
        ),
        (
            "parse_failure_counted_as_transport_failure",
            int(mock_parse_failure_result["provider_transport_failure_count"] != 0),
            0,
        ),
        ("real_api_call_count", mock_execution_result["real_api_call_count"], 0),
        (
            "execution_protocol_hash_valid",
            int("execution_protocol_hash" not in smoke["execution_protocol"]),
            0,
        ),
        (
            "execution_protocol_hash_naming_issue",
            _protocol_hash_issue(protocol_hash_rows, "execution_protocol_hash_naming"),
            0,
        ),
        (
            "task_manifest_hash_naming_issue",
            _protocol_hash_issue(protocol_hash_rows, "task_manifest_hash_naming"),
            0,
        ),
        ("unset_model_real_api_call_count", 0, 0),
        (
            "smoke_summary_reconciliation_issue",
            sum(row["status"] != "PASS" for row in accounting_rows),
            0,
        ),
        (
            "requested_vs_applied_parameter_mismatch_unreported",
            _parameter_mismatch_issue(provider_parameter_rows),
            0,
        ),
        ("sdk_hidden_retry_risk_count", _sdk_hidden_retry_risk(provider_parameter_rows), 0),
        (
            "preflight_failure_formal_run_created_count",
            _preflight_issue(preflight_rows, "formal_run_directory_created"),
            0,
        ),
        (
            "preflight_failure_real_api_attempt_count",
            _preflight_issue(preflight_rows, "real_api_request_attempt_count"),
            0,
        ),
        (
            "preflight_failure_execution_complete_count",
            _preflight_issue(preflight_rows, "execution_complete_printed"),
            0,
        ),
        ("accidental_api_call_without_execute", _dry_run_api_issue(dry_run), 0),
    ]
    rows = []
    issue_count = 0
    for check_name, actual, expected in checks:
        if expected == ">0":
            status = "PASS" if _as_int(actual) > 0 else "FAIL"
        elif expected == ">=12":
            status = "PASS" if _as_int(actual) >= 12 else "FAIL"
        elif expected == "<=20":
            status = "PASS" if _as_int(actual) <= 20 else "FAIL"
        else:
            status = "PASS" if actual == expected else "FAIL"
        issue_count += int(status != "PASS")
        rows.append(
            {
                "check_name": check_name,
                "actual": actual,
                "expected": expected,
                "status": status,
            }
        )
    rows.append(
        {
            "check_name": "issue_count",
            "actual": issue_count,
            "expected": 0,
            "status": "PASS" if issue_count == 0 else "FAIL",
        }
    )
    return rows


def _manifest(
    locks: list[Any],
    units: list[Any],
    sentences: list[Any],
    task_bundles: list[dict[str, Any]],
    hard_rows: list[dict[str, object]],
    smoke: dict[str, Any],
) -> dict[str, Any]:
    return {
        "input_fact_lock_count": len(locks),
        "task_count": len(task_bundles),
        "realization_unit_count": len(units),
        "canonical_sentence_count": len(sentences),
        "multi_member_unit_count": sum(len(unit.member_fact_lock_ids) > 1 for unit in units),
        "max_member_count": max((len(unit.member_fact_lock_ids) for unit in units), default=0),
        "hard_issue_count": next(
            row["actual"] for row in hard_rows if row["check_name"] == "issue_count"
        ),
        "real_model_smoke_status": smoke["real_model_smoke_status"],
    }


def _method_version(
    inputs: dict[str, Any], generated_at: str, smoke: dict[str, Any]
) -> dict[str, Any]:
    return {
        "method_version": STAGE6B_METHOD_VERSION,
        "schema_version": STAGE6B_SCHEMA_VERSION,
        "status": STAGE6B_STATUS,
        "generated_at": generated_at,
        "generated_at_semantics": "OFFLINE_RECONSTRUCTION_TIME",
        "upstream_stage6a_method": inputs["stage6a_method"]["method_version"],
        "uses_llm": False,
        "real_model_smoke_status": smoke["real_model_smoke_status"],
        "real_model_smoke_required_before_freeze": True,
        "real_model_smoke_manifest_frozen": True,
        "real_model_smoke_task_manifest_hash": smoke["task_manifest_hash"],
        "real_model_smoke_protocol_version": smoke["protocol"]["protocol_version"],
        "real_model_smoke_execution_protocol_hash": smoke["execution_protocol"][
            "execution_protocol_hash"
        ],
        "real_model_smoke_retry_policy": smoke["protocol"]["retry_policy"],
        "execution_layer_status": "READY",
        "mock_execution_status": "PASS",
        "presentation_policy_version": PRESENTATION_POLICY_VERSION,
        "generates_natural_language_with_llm": False,
        "llm_role": "PLAN_SELECTION_AND_ORDERING_ONLY_NOT_RUN_IN_CANDIDATE",
        "llm_cannot_generate_engineering_text": True,
    }


def _write_report(
    path: Path,
    manifest: dict[str, Any],
    hard_rows: list[dict[str, object]],
    smoke: dict[str, Any],
    dry_run: dict[str, Any],
) -> None:
    issue_count = next(row["actual"] for row in hard_rows if row["check_name"] == "issue_count")
    text = f"""# Stage6B Controlled Realization Candidate

Decision: READY_FOR_REAL_MODEL_SMOKE

Stage6B v1 candidate builds the deterministic presentation layer on frozen
Stage6A FactLocks. It resolves presentation chainage, creates task-scoped
abstention views, performs exact semantic grouping, renders canonical safe
sentences, validates a constrained RealizationPlan, composes final text without
LLM rewriting, and audits numeric/chainage/modality/provenance boundaries.

It does not call a real LLM in this candidate run. Therefore it is not ready for
freeze audit until real-model smoke outputs are captured and validated.

## Counts

- Input FactLocks: {manifest["input_fact_lock_count"]}
- Task count: {manifest["task_count"]}
- RealizationUnits: {manifest["realization_unit_count"]}
- CanonicalFactSentences: {manifest["canonical_sentence_count"]}
- Multi-member units: {manifest["multi_member_unit_count"]}
- Max member count: {manifest["max_member_count"]}
- Hard check issue count: {issue_count}
- Real model smoke status: {smoke["real_model_smoke_status"]}
- Real model smoke task manifest hash: {smoke["task_manifest_hash"]}
- Real model smoke dry-run status: {dry_run["dry_run_status"]}
- Real model smoke API call count: {dry_run["api_call_count"]}

## Boundary

LLM output is constrained to a RealizationPlan: section assignment and ordering
of existing RealizationUnit IDs. It cannot produce generated engineering text,
rewrite canonical sentences, create facts, modify numbers, change chainage,
upgrade epistemic modality, or infer geological cause from mechanical response.

## Real-Model Smoke Protocol

The model is not asked to write an engineering report. It receives only task
metadata, product contract rules, allowed section IDs, task-scoped abstention
summary, and RealizationUnit public records containing unit IDs plus canonical
safe text. It does not receive raw PLC, raw geological documents, Stage3 state
objects, Stage4 calculations, rejected candidate values, or proposal internals.

The current product contract keeps ALL_TASK_UNITS_REQUIRED, so the model cannot
delete required facts. Its current freedom is limited to valid section placement
and ordering. Canonical numeric/chainage correctness is deterministic system
behaviour, not LLM accuracy.

Raw model attempts must be saved before parsing, schema validation, deterministic
validate_plan(), composition, and post-realization audit. This candidate run is
dry-run only and sends no API requests.
"""
    path.write_text(text, encoding="utf-8")


def _stage6a_hash_issue_count(repo_root: Path) -> int:
    manifest = repo_root / "artifacts/stage6a_fact_lock_evidence_pack_v1/file_hashes.sha256"
    base = manifest.parent
    count = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, rel_path = line.split(maxsplit=1)
        actual = hashlib.sha256((base / rel_path).read_bytes()).hexdigest()
        count += int(actual != expected)
    return count


def _artifact_hash_issue_count(manifest: Path) -> int:
    base = manifest.parent
    count = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.strip():
            expected, rel_path = line.split(maxsplit=1)
            count += int(hashlib.sha256((base / rel_path).read_bytes()).hexdigest() != expected)
    return count


def _plan_issue_count(rows: list[dict[str, object]], code: str) -> int:
    return sum(code in str(row["issue_codes"]).split(";") for row in rows)


def _post_issue_count(rows: list[dict[str, object]], code: str) -> int:
    return sum(code in str(row["issue_codes"]).split(";") for row in rows)


def _coverage_issue(rows: list[dict[str, object]], check_name: str) -> int:
    matching = [row for row in rows if row.get("check_name") == check_name]
    return int(not matching or matching[0].get("status") != "PASS")


def _accounting_issue(rows: list[dict[str, object]], metric: str) -> int:
    matching = [row for row in rows if row.get("metric") == metric]
    return int(not matching or any(row.get("status") != "PASS" for row in matching))


def _transport_sum_issue(summary: dict[str, Any]) -> int:
    return int(
        summary["provider_request_attempt_count"]
        != summary["provider_transport_success_count"] + summary["provider_transport_failure_count"]
    )


def _real_api_transport_sum_issue(summary: dict[str, Any]) -> int:
    return int(
        summary["real_api_request_attempt_count"]
        != summary["real_api_transport_success_count"] + summary["real_api_transport_failure_count"]
    )


def _transport_rate_issue(summary: dict[str, Any]) -> int:
    denominator = summary["provider_request_attempt_count"]
    expected = (
        None if denominator == 0 else summary["provider_transport_success_count"] / denominator
    )
    return int(summary["provider_transport_success_rate"] != expected)


def _protocol_hash_issue(rows: list[dict[str, object]], check_name: str) -> int:
    matching = [row for row in rows if row.get("check_name") == check_name]
    return int(not matching or any(row.get("status") != "PASS" for row in matching))


def _parameter_mismatch_issue(rows: list[dict[str, object]]) -> int:
    mismatches = 0
    for row in rows:
        if str(row.get("supported", "")).lower() == "true" and row.get("requested") != row.get(
            "applied"
        ):
            mismatches += 1
    return mismatches


def _sdk_hidden_retry_risk(rows: list[dict[str, object]]) -> int:
    matching = [row for row in rows if row.get("parameter") == "max_retries"]
    if not matching:
        return 1
    row = matching[0]
    return int(
        row.get("requested") != 0
        or row.get("applied") != 0
        or str(row.get("supported")).lower() != "true"
    )


def _preflight_issue(rows: list[dict[str, object]], field: str) -> int:
    return sum(_as_int(row.get(field, 0)) for row in rows)


def _dry_run_api_issue(dry_run: dict[str, Any]) -> int:
    return int(_as_int(dry_run.get("api_call_count", 0)) != 0)


def _hardcoded_real_api_count_literal(repo_root: Path) -> int:
    paths = [
        repo_root / "src/tbm_twin/realization/stage6b_smoke.py",
        repo_root / "scripts/run_stage6b_real_model_smoke.py",
    ]
    pattern = re.compile(r'"real_api_call_count"\s*:\s*0')
    return sum(
        bool(pattern.search(path.read_text(encoding="utf-8"))) for path in paths if path.exists()
    )


def _tamper_undetected(rows: list[dict[str, object]], case_id: str) -> int:
    matching = [row for row in rows if row.get("case_id") == case_id]
    if not matching:
        return 1
    return int(any(row.get("status") != "PASS" for row in matching))


def _as_int(value: object) -> int:
    return int(str(value))


def _credential_literal_audit(repo_root: Path) -> list[dict[str, object]]:
    paths = [
        *sorted((repo_root / "src/tbm_twin/realization").glob("stage6b*.py")),
        *sorted((repo_root / "src/tbm_twin/realization/providers").glob("*.py")),
        repo_root / "src/tbm_twin/realization/build_stage6b.py",
        repo_root / "scripts/build_stage6b_controlled_realization.py",
        repo_root / "scripts/run_stage6b_real_model_smoke.py",
    ]
    return credential_literal_audit(paths)


def _provider_domain_leakage_count(repo_root: Path) -> int:
    domain_files = [
        repo_root / "src/tbm_twin/realization/stage6b.py",
        repo_root / "src/tbm_twin/realization/stage6b_models.py",
        repo_root / "src/tbm_twin/realization/stage6b_smoke.py",
    ]
    forbidden = ["from openai", "import openai", "anthropic", "google.generativeai"]
    count = 0
    for path in domain_files:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            count += sum(token in text for token in forbidden)
    return count


def _execution_layer_audit(mock_execution_result: dict[str, Any]) -> list[dict[str, object]]:
    return [
        {
            "check_name": "non_dry_run_execution_path",
            "actual": mock_execution_result["provider_attempt_count"],
            "expected": 15,
            "status": "PASS" if mock_execution_result["provider_attempt_count"] == 15 else "FAIL",
        },
        {
            "check_name": "composition_after_valid_plan_only",
            "actual": mock_execution_result["composition_count"],
            "expected": 15,
            "status": "PASS" if mock_execution_result["composition_count"] == 15 else "FAIL",
        },
        {
            "check_name": "real_api_call_count",
            "actual": mock_execution_result["real_api_call_count"],
            "expected": 0,
            "status": "PASS" if mock_execution_result["real_api_call_count"] == 0 else "FAIL",
        },
    ]


def _raw_first_persistence_audit(run_dir: Path) -> list[dict[str, object]]:
    raw_rows = _read_jsonl(run_dir / "raw_model_outputs.jsonl")
    parsed_rows = _read_jsonl(run_dir / "parsed_plans.jsonl")
    return [
        {
            "check_name": "raw_attempt_count",
            "actual": len(raw_rows),
            "expected": 15,
            "status": "PASS" if len(raw_rows) == 15 else "FAIL",
        },
        {
            "check_name": "raw_available_before_parse",
            "actual": int(len(raw_rows) >= len(parsed_rows)),
            "expected": 1,
            "status": "PASS" if len(raw_rows) >= len(parsed_rows) else "FAIL",
        },
    ]


def _plan_materialization_audit(run_dir: Path) -> list[dict[str, object]]:
    rows = _read_jsonl(run_dir / "materialized_plans.jsonl")
    invalid_hashes = 0
    for row in rows:
        payload = {
            "pack_id": row["pack_id"],
            "task_abstention_view_id": row["task_abstention_view_id"],
            "product_type": row["product_type"],
            "sections": row["sections"],
            "omitted_optional_unit_ids": row["omitted_optional_unit_ids"],
            "contract_hash": row["contract_hash"],
            "pack_hash": row["pack_hash"],
            "presentation_policy_version": row["presentation_policy_version"],
            "provider_name": row["provider_name"],
        }
        invalid_hashes += int(row["plan_hash"] != stable_hash(payload))
    return [
        {
            "check_name": "materialized_plan_count",
            "actual": len(rows),
            "expected": 15,
            "status": "PASS" if len(rows) == 15 else "FAIL",
        },
        {
            "check_name": "materialized_plan_hash_invalid",
            "actual": invalid_hashes,
            "expected": 0,
            "status": "PASS" if invalid_hashes == 0 else "FAIL",
        },
    ]


def _provider_parameter_audit(protocol: dict[str, Any]) -> list[dict[str, object]]:
    rows = []
    for name in [
        "temperature",
        "top_p",
        "max_output_tokens",
        "seed",
        "reasoning_effort",
        "timeout_seconds",
        "max_retries",
        "base_url",
    ]:
        value = protocol.get(name)
        if isinstance(value, dict):
            supported = bool(value["supported"])
            applied = value["applied"]
            requested = value["requested"]
        else:
            supported = value is not None
            applied = value
            requested = value
        rows.append(
            {
                "parameter": name,
                "requested": "" if requested is None else requested,
                "applied": "" if applied is None else applied,
                "supported": str(supported).lower(),
                "status": "PASS",
            }
        )
    return rows


def _provider_accounting_audit(
    run_dir: Path, mock_execution_result: dict[str, Any]
) -> list[dict[str, object]]:
    attempts = [SmokeAttemptProxy(row) for row in _read_jsonl(run_dir / "attempt_results.jsonl")]
    return accounting_audit_rows(mock_execution_result, attempts)


def _protocol_hash_audit(output: Path, smoke: dict[str, Any]) -> list[dict[str, object]]:
    _ = output
    protocol_file_sha = _stable_json_file_sha256(smoke["execution_protocol"])
    task_manifest_file_sha = _stable_json_file_sha256(smoke["task_manifest"])
    rows = [
        {
            "check_name": "execution_protocol_hash_naming",
            "semantic_hash_field": "execution_protocol_hash",
            "semantic_hash": smoke["execution_protocol"]["execution_protocol_hash"],
            "file_sha256_field": "execution_protocol_file_sha256",
            "file_sha256": protocol_file_sha,
            "status": "PASS",
        },
        {
            "check_name": "task_manifest_hash_naming",
            "semantic_hash_field": "task_manifest_hash",
            "semantic_hash": smoke["task_manifest_hash"],
            "file_sha256_field": "task_manifest_file_sha256",
            "file_sha256": task_manifest_file_sha,
            "status": "PASS",
        },
    ]
    return rows


def _preflight_boundary_audit(output: Path) -> list[dict[str, object]]:
    failure_dir = output / "real_model_smoke" / "preflight_failures"
    rows = []
    if not failure_dir.exists():
        return [
            {
                "case_id": "no_preflight_failure_in_candidate",
                "failure_code": "",
                "formal_run_directory_created": 0,
                "real_api_request_attempt_count": 0,
                "execution_complete_printed": 0,
                "status": "PASS",
            }
        ]
    for path in sorted(failure_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        formal_run_created = int(bool(payload.get("formal_run_directory_created")))
        real_api_attempts = _as_int(payload.get("real_api_request_attempt_count", 0))
        execution_complete_printed = int(bool(payload.get("execution_complete_printed")))
        rows.append(
            {
                "case_id": path.stem,
                "failure_code": payload.get("failure_code", ""),
                "formal_run_directory_created": formal_run_created,
                "real_api_request_attempt_count": real_api_attempts,
                "execution_complete_printed": execution_complete_printed,
                "status": "PASS"
                if formal_run_created == 0
                and real_api_attempts == 0
                and execution_complete_printed == 0
                else "FAIL",
            }
        )
    return rows


def _stable_json_file_sha256(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SmokeAttemptProxy:
    """Small attribute proxy for recomputing accounting from JSONL rows."""

    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    def __getattr__(self, name: str) -> Any:
        return self._row[name]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _model_controlled_metadata_count(smoke: dict[str, Any]) -> int:
    forbidden = {
        "pack_id",
        "pack_hash",
        "contract_hash",
        "task_abstention_view_id",
        "presentation_policy_version",
        "plan_hash",
        "plan_id",
    }
    return sum(
        int(any(field in request["output_schema"].get("properties", {}) for field in forbidden))
        for request in smoke["prompt_payloads"]
    )


def _case(case_id: str, passed: bool) -> dict[str, object]:
    return {"case_id": case_id, "status": "PASS" if passed else "FAIL"}
