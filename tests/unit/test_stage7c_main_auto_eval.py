from __future__ import annotations

import csv
import json
from pathlib import Path

from tbm_twin.evaluation.stage7c import (
    NumericReference,
    Scope,
    build_stage7c_auto_eval,
    evaluate_e2_numeric,
    evaluate_e3_missing_to_zero,
    evaluate_e4_spatial_scope,
    evaluate_e5_forecast_factification,
    evaluate_e7_hindsight,
    evaluate_e10_attention_probability,
    evaluate_e12_claim_admissibility,
    evaluate_e13_structure,
    evaluate_e14_trace,
    split_engineering_statements,
)


def test_stage7c_statement_split_is_method_neutral() -> None:
    text = "## 施工状态\nA\u3002B\uff1bC\nD."
    assert split_engineering_statements(text) == ["施工状态", "A", "B", "C", "D"]


def test_e2_numeric_legal_rounding_passes_and_wrong_value_fails() -> None:
    refs = {"RAI": NumericReference("RAI", 0.3150437, "AVAILABLE", "state_rai_x")}
    assert evaluate_e2_numeric("RAI=0.315", refs).result == "PASS"
    decision = evaluate_e2_numeric("RAI=0.351", refs)
    assert decision.result == "FAIL"
    assert decision.reason_code == "NUMERIC_VALUE_MISMATCH"


def test_e3_missing_to_zero_distinguishes_true_zero() -> None:
    zero_ref = {"GRS": NumericReference("GRS", 0.0, "AVAILABLE", "state_grs_zero")}
    missing_ref = {"GRS": NumericReference("GRS", None, "GRS_UNAVAILABLE", "state_grs_missing")}
    assert evaluate_e3_missing_to_zero("GRS=0", zero_ref).result == "NOT_APPLICABLE"
    assert evaluate_e3_missing_to_zero("GRS=0", missing_ref).result == "FAIL"
    decimal_ref = {"RAI": NumericReference("RAI", 0.327, "AVAILABLE", "state_rai")}
    assert evaluate_e3_missing_to_zero("RAI 为 0.327", decimal_ref).result == "PASS"


def test_e2_binds_metric_to_exact_statement_scope() -> None:
    refs = [
        NumericReference(
            "GRS",
            0.20833333333333331,
            "AVAILABLE",
            "state_grs_cell_a",
            "cell_a",
            Scope(1014040.0, 1014050.0, "cell_a"),
        ),
        NumericReference(
            "GRS",
            0.5833333333333333,
            "AVAILABLE",
            "state_grs_cell_b",
            "cell_b",
            Scope(1014050.0, 1014060.0, "cell_b"),
        ),
    ]
    assert evaluate_e2_numeric("1014040-1014050 GRS=0.208", refs).result == "PASS"
    decision = evaluate_e2_numeric("1014040-1014050 GRS=0.583", refs)
    assert decision.result == "FAIL"
    assert decision.authoritative_reference == "state_grs_cell_a"


def test_e4_spatial_scope_containment_and_expansion() -> None:
    scopes = [Scope(1013470.0, 1013480.0, "claim_scope")]
    assert evaluate_e4_spatial_scope("支持范围为1013470-1013480", scopes).result == "PASS"
    decision = evaluate_e4_spatial_scope("整个施工区段1013400-1013600均为破碎岩体", scopes)
    assert decision.result == "FAIL"
    assert decision.reason_code == "EXPLICIT_SCOPE_EXPANSION"
    report_title = "水平声波剖面法超前地质预报报告\uff08DyK1014+019\uff5eDyK1014+119\uff09"
    assert evaluate_e4_spatial_scope(report_title, scopes).result == "REQUIRES_HUMAN_REVIEW"


def test_e5_forecast_factification_pass_and_fail() -> None:
    terms = {"岩体破碎"}
    assert evaluate_e5_forecast_factification("预测资料提示岩体破碎", terms).result == "PASS"
    decision = evaluate_e5_forecast_factification("现场已揭露岩体破碎", terms)
    assert decision.result == "FAIL"
    assert decision.reason_code == "FORECAST_RENDERED_AS_OBSERVED_OR_CURRENT_FACT"
    observed_support = [{"evidence_id": "obs", "terms": {"岩体破碎"}, "scope": None}]
    forecast_support = [{"evidence_id": "fc", "terms": {"岩体破碎"}, "scope": None}]
    assert (
        evaluate_e5_forecast_factification("当前掌子面出露岩体破碎", [], observed_support).result
        == "PASS"
    )
    assert (
        evaluate_e5_forecast_factification(
            "当前掌子面出露岩体破碎", forecast_support, observed_support
        ).result
        == "REQUIRES_HUMAN_REVIEW"
    )
    assert (
        evaluate_e5_forecast_factification(
            "围岩与当前掌子面相当\uff0c岩体破碎",
            terms,
            semantic_context_text=(
                "该段预报结论为\uff1a无明显反射异常\uff1b围岩与当前掌子面相当\uff0c岩体破碎"
            ),
        ).result
        == "PASS"
    )
    assert evaluate_e5_forecast_factification("建议按Ⅳ级围岩管理", terms).result != "FAIL"


def test_e7_later_only_support_fails() -> None:
    decision = evaluate_e7_hindsight(
        "该段出现突涌水",
        current_terms={"弱风化"},
        later_terms={"突涌水"},
    )
    assert decision.result == "FAIL"
    assert decision.reason_code == "LATER_AVAILABLE_SUPPORT_USED_IN_CURRENT_ASOF"


def test_e10_attention_probability_promotion() -> None:
    assert evaluate_e10_attention_probability("GRCI=0.4").result == "PASS"
    assert (
        evaluate_e10_attention_probability(
            "GRS为注意力指数\uff0c反映关注度\uff0c但不代表风险概率。"
        ).result
        == "PASS"
    )
    assert evaluate_e10_attention_probability("GRCI不能解释为灾害发生概率。").result == "PASS"
    assert evaluate_e10_attention_probability("RAI不直接等同于地质风险概率。").result == "PASS"
    assert evaluate_e10_attention_probability("GRCI不构成概率或因果估计。").result == "PASS"
    assert evaluate_e10_attention_probability("GRCI不构成风险概率。").result == "PASS"
    assert evaluate_e10_attention_probability("RAI不直接代表风险概率。").result == "PASS"
    assert evaluate_e10_attention_probability("RAI不能直接解释为风险概率。").result == "PASS"
    assert evaluate_e10_attention_probability("RAI、GRS、GRCI均不得解释为概率。").result == "PASS"
    assert evaluate_e10_attention_probability("GRS不应解释为概率或因果估计。").result == "PASS"
    assert evaluate_e10_attention_probability("不能据RAI推断风险概率或因果结论。").result == "PASS"
    assert evaluate_e10_attention_probability("RAI不宜据此扩展为概率性结论。").result == "PASS"
    assert evaluate_e10_attention_probability("RAI证据不足以形成概率性判断。").result == "PASS"
    assert (
        evaluate_e10_attention_probability(
            "所给证据不足以对RAI进行评价;也不足以将任何指标解释为概率。"
        ).result
        == "PASS"
    )
    assert evaluate_e10_attention_probability("不能从RAI得出概率性结论。").result == "PASS"
    assert evaluate_e10_attention_probability("不得据RAI推断风险概率。").result == "PASS"
    assert evaluate_e10_attention_probability("不将RAI/GRS/GRCI解释为概率。").result == "PASS"
    assert (
        evaluate_e10_attention_probability(
            "GRCI=0.4",
            semantic_context_text="该指标仅表示耦合关注强度\uff0c不构成概率或因果判断。",
        ).result
        == "PASS"
    )
    assert evaluate_e10_attention_probability("注意力指标为非概率性指标。").result == "PASS"
    decision = evaluate_e10_attention_probability("GRCI 表示灾害概率40%")
    assert decision.result == "FAIL"
    assert decision.reason_code == "ATTENTION_RENDERED_AS_PROBABILITY"
    assert evaluate_e10_attention_probability("RAI 0.315 表示31.5%的风险概率。").result == "FAIL"


def test_e12_abstained_claim_value_expression() -> None:
    assert (
        evaluate_e12_claim_admissibility("岩体破碎", set(), {"岩体破碎"}).result == "NOT_APPLICABLE"
    )
    decision = evaluate_e12_claim_admissibility("存在突涌水", {"突涌水"}, set())
    assert decision.result == "FAIL"
    assert decision.reason_code == "FORMAL_ABSTAIN_CLAIM_VALUE_EXPRESSED"


def test_e13_invalid_plan_fail_closed_is_expected_behavior() -> None:
    condition = {
        "method_internal": "P_PROPOSED",
        "output_available": "false",
        "output_status": "NO_VALID_OUTPUT_VALIDATOR_INTERCEPT",
    }
    assert evaluate_e13_structure(condition, "").result == "PASS"
    bad_condition = {
        "method_internal": "P_PROPOSED",
        "output_available": "true",
        "output_status": "INVALID_PLAN_PROPAGATED_TO_FINAL_TEXT",
    }
    assert evaluate_e13_structure(bad_condition, "statement_1").result == "FAIL"


def test_e14_trace_pass_and_broken_trace_fails() -> None:
    good = {
        "method_internal": "P_PROPOSED",
        "output_available": "true",
        "support_reference": "canonical_sentence_x;realization_unit_y",
    }
    bad = {
        "method_internal": "P_PROPOSED",
        "output_available": "true",
        "support_reference": "",
    }
    trace_row = {
        "trace_status": "CANONICAL_PARENT_TRACE_COMPLETE",
        "authoritative_support_ids": "doc_x",
        "fact_lock_ids": "fact_lock_x",
    }
    assert evaluate_e14_trace("fact", good, trace_row).result == "PASS"
    assert evaluate_e14_trace("fact", bad).result == "FAIL"


def test_stage7c_build_is_deterministic(tmp_path: Path) -> None:
    repo_root = Path.cwd()
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    summary_a = build_stage7c_auto_eval(repo_root, out_a, write_audit_zip=False)
    build_stage7c_auto_eval(repo_root, out_b, write_audit_zip=False)
    assert summary_a["condition_count"] == 144
    assert summary_a["actual_text_count"] == 141
    assert summary_a["p_no_output_count"] == 3
    assert (out_a / "automatic_statement_audit.csv").read_text() == (
        out_b / "automatic_statement_audit.csv"
    ).read_text()
    assert (out_a / "method_automatic_summary.csv").read_text() == (
        out_b / "method_automatic_summary.csv"
    ).read_text()
    assert (out_a / "trace_cardinality_audit.csv").read_text() == (
        out_b / "trace_cardinality_audit.csv"
    ).read_text()


def test_stage7c_real_regressions_are_bound_to_statement_subjects(tmp_path: Path) -> None:
    repo_root = Path.cwd()
    out = tmp_path / "stage7c"
    summary = build_stage7c_auto_eval(repo_root, out, write_audit_zip=False)
    assert summary["hard_check_fail_count"] == 0

    audits = list(csv.DictReader((out / "automatic_statement_audit.csv").open()))
    task_002_e2 = [
        row
        for row in audits
        if row["task_id"] == "stage7_main_task_002"
        and row["error_code"] == "E2"
        and "GRS" in row["statement_text"]
        and "0.208" in row["statement_text"]
    ]
    assert task_002_e2
    assert all(row["result"] != "FAIL" for row in task_002_e2)

    decimal_e3 = [
        row
        for row in audits
        if row["error_code"] == "E3"
        and "RAI" in row["statement_text"]
        and "0.327" in row["statement_text"]
    ]
    assert all(row["result"] != "FAIL" for row in decimal_e3)

    task_002_e4_report = [
        row
        for row in audits
        if row["task_id"] == "stage7_main_task_002"
        and row["method_internal"] == "B1_STRUCTURED_PROMPT_LLM"
        and row["error_code"] == "E4"
        and "报告" in row["statement_text"]
    ]
    assert task_002_e4_report
    assert all(row["result"] != "FAIL" for row in task_002_e4_report)

    observed_p_e5 = [
        row
        for row in audits
        if row["task_id"]
        in {"stage7_main_task_011", "stage7_main_task_043", "stage7_main_task_047"}
        and row["method_internal"] == "P_PROPOSED"
        and row["error_code"] == "E5"
        and "当前掌子面出露" in row["statement_text"]
    ]
    assert all(row["result"] != "FAIL" for row in observed_p_e5)

    trace_rows = list(csv.DictReader((out / "statement_trace_table.csv").open()))
    p_engineering_rows = [
        row
        for row in trace_rows
        if row["method_internal"] == "P_PROPOSED"
        and row["trace_status"]
        not in {"BASELINE_REQUIRES_HUMAN_SUPPORT_MAPPING", "NOT_ENGINEERING_FACT"}
    ]
    assert p_engineering_rows
    assert all(
        row["trace_status"] == "CANONICAL_PARENT_TRACE_COMPLETE" for row in p_engineering_rows
    )

    task_021_trace = [
        row
        for row in trace_rows
        if row["task_id"] == "stage7_main_task_021"
        and row["canonical_sentence_ids"] == "canonical_sentence_a95bdf0b8edca17a9c29f55d"
    ]
    assert task_021_trace
    assert task_021_trace[0]["fact_lock_ids"]
    assert task_021_trace[0]["typed_claim_ids"]

    cardinality_rows = list(csv.DictReader((out / "trace_cardinality_audit.csv").open()))
    assert cardinality_rows
    assert all(row["status"] == "PASS" for row in cardinality_rows)
    assert {row["relation_source"] for row in cardinality_rows} == {
        "rebuilt_stage7a_asof_stage6b_bundle_realization_unit_member_fact_lock_ids"
    }

    contexts = list(csv.DictReader((out / "statement_context_table.csv").open()))
    assert contexts
    assert all(row["semantic_context_unit_id"] for row in contexts)

    e10_reclassified = list(csv.DictReader((out / "e10_v1_1_fail_reclassification.csv").open()))
    assert e10_reclassified
    assert all(row["v1_2_result"] != "FAIL" for row in e10_reclassified)

    e5_reclassified = list(csv.DictReader((out / "e5_v1_1_fail_reclassification.csv").open()))
    assert e5_reclassified
    assert all(row["v1_2_result"] != "FAIL" for row in e5_reclassified)

    e13_plans = list(csv.DictReader((out / "e13_plan_level_summary.csv").open()))
    assert sum(row["plan_valid"] == "false" for row in e13_plans) == 3
    assert sum(row["intercepted"] == "true" for row in e13_plans) == 3
    assert sum(row["invalid_plan_propagated_to_final_text"] == "true" for row in e13_plans) == 0

    e7_coverage = json.loads((out / "e7_automatic_coverage.json").read_text())
    assert e7_coverage["status"] == "E7_DEFERRED_TO_HUMAN_EVALUATION"
    assert e7_coverage["evaluable_statement_count"] == 0
    assert e7_coverage["fail_count"] == 0
