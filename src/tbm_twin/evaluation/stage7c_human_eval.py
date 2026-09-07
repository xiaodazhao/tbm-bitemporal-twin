# ruff: noqa: RUF001
"""Build blinded human-evaluation packets from frozen Stage7 artifacts.

The builder is deliberately offline. It reads frozen Stage7A exact-as-of
snapshots and frozen Stage7B text outputs, then prepares blank annotation
packets. It never calls a model, reruns Stage7B, or assigns human labels.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import shutil
import statistics
import subprocess
import zipfile
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path
from typing import Any

from tbm_twin.realization.io import stable_hash, stable_id

METHOD_VERSION = "stage7c_human_evaluation_packet_v1_1"
SCHEMA_VERSION = "stage7c_human_evaluation_packet.v1.1"
GENERATED_AT = "2026-08-25T00:00:00+08:00"
STAGE7A_TAG = "stage7a-experimental-protocol-v1.3-frozen"
STAGE7A_COMMIT = "6007afe7c1b1228d6638503afeba979ee2f66878"
STAGE7B_EXECUTION_ID = "stage7b_main_execution_3ae0f791811a2e711cb9f488"
STAGE7B_TAG = "stage7b-main-comparison-v1-frozen"
STAGE7B_COMMIT = "38da398b3c5edc8e3e5f8180273f1f04fdff4fbb"
STAGE7C1_TAG = "stage7c-main-auto-evaluation-v1.2-frozen"
STAGE7C1_COMMIT = "b12567dcbba4206016bafebe2405a0e4652fdc58"
STAGE7C2A_V1_TAG = "stage7c-human-evaluation-packet-v1-frozen"
STAGE7C2A_V1_COMMIT = "61775f4f1f50b76efa9087835a5f465de781e7ed"
EXPECTED_NO_OUTPUT_TASKS = {
    "stage7_main_task_022",
    "stage7_main_task_026",
    "stage7_main_task_042",
}
METHODS = ("B0_DIRECT_LLM", "B1_STRUCTURED_PROMPT_LLM", "P_PROPOSED")
PACKET_SEEDS = {"A": 2026082501, "B": 2026082502}
BATCH_CAPACITIES = (24, 24, 24, 23, 23, 23)
MINIMUM_SAME_TASK_GAP_TARGET = 15
STAGE7A_EXPECTED_HASHES = {
    "main_benchmark_manifest_hash": (
        "e9ef8e3f9bd25f345f89f79dc753040e3bfc1f95e562902aea625a8e50334f6f"
    ),
    "asof_evaluation_binding_manifest_hash": (
        "92bdea500aef7bedb27e6133e92ec058f03ccfd48810e84aed11388838d12bc4"
    ),
    "preclaim_benchmark_evidence_snapshot_set_hash": (
        "8bbbc9083bfa2313fe583f88c6d431d199f9ffaa8cf1b0a7d28f70a11ab98a6c"
    ),
    "product_task_contract_hash": (
        "ad599756f428514cf731bb982ecccf21b0705e14579ebf64095524a674ecc98d"
    ),
}

RATING_FIELDS = (
    "E1_unsupported_claim",
    "E5_forecast_factification",
    "E6_observed_without_proof",
    "E7_hindsight_leakage",
    "E8_role_boundary_violation",
    "E9_mechanical_geological_causation",
    "E10_attention_probability_promotion",
    "E11_unknown_to_normal",
    "E12_other_admissibility_violation",
    "overall_semantic_error",
    "factual_support_score",
    "epistemic_correctness_score",
    "engineering_usefulness_score",
    "clarity_score",
    "misleading_risk_score",
    "error_quote",
    "annotator_confidence",
    "annotator_comment",
)

PACKET_FIELDS = (
    "annotation_item_id",
    "anonymous_condition_id",
    "engineering_context",
    "generated_text",
    *RATING_FIELDS,
)

CONTEXT_BANNED_TERMS = (
    "B0",
    "B1",
    "Proposed",
    "baseline",
    "DeepSeek",
    "provider",
    "method_internal",
    "FactLock",
    "ClaimDecision",
    "EXPRESSIBLE",
    "ABSTAIN",
    "Stage7B",
)

FROZEN_OUTPUT_CUE_PATTERNS = {
    "STAGE_REFERENCE": r"(?<![A-Za-z0-9_])Stage[0-9]+(?:[A-Za-z0-9_.-]*)?",
    "CELL_IDENTIFIER": r"(?<![A-Za-z0-9_])cell_[A-Za-z0-9_]+",
    "CLAIM_TERM": r"(?<![A-Za-z0-9_])Claim(?:Decision)?(?![A-Za-z0-9_])",
    "STATE_ROLE_NOT_ALLOWED": r"STATE_ROLE_NOT_ALLOWED",
    "SOURCE_CONSTRAINED": r"source-constrained",
    "FACT_LOCK": r"FactLock|fact_lock_",
    "REALIZATION_UNIT": r"realization_unit_",
    "INTERNAL_EVIDENCE_ID": r"evidence_id|证据ID",
}

CHANNEL_LABELS = {
    "penetration": "贯入度",
    "cutterhead_torque": "刀盘扭矩",
    "total_thrust": "总推力",
    "cutterhead_rpm": "刀盘转速",
    "advance_speed": "掘进速度",
}

ROLE_LABELS = {
    "DAILY_REVIEW": "当日已掘复核",
    "FORWARD_ATTENTION": "前方关注",
    "LOCAL_BACKGROUND": "局部背景",
    "DAILY_REVIEW_CELL": "当日已掘复核单元",
    "FORWARD_ATTENTION_CELL": "前方关注单元",
    "LOCAL_BACKGROUND_CELL": "局部背景单元",
    "CELL_LINKED_OPERATIONAL_RESPONSE": "与当前施工空间关联的机械响应",
    "SHARED_STAGE4_ATTENTION_STATE": "当前认识状态中的共享关注指标",
}

METRIC_STATUS_LABELS = {
    "AVAILABLE": "可用",
    "UNAVAILABLE": "不可用",
    "INSUFFICIENT_CAUSAL_BASELINE": "因果基线不足",
    "NO_CELL_LINKED_OPERATIONAL_RESPONSE": "当前空间单元没有可关联的机械响应",
    "GRCI_NOT_DEFINED_FOR_FORWARD_ATTENTION": ("前方关注场景不定义机械—地质联合关注指标"),
    "GRCI_NOT_DEFINED_FOR_LOCAL_BACKGROUND": ("局部背景场景不定义机械—地质联合关注指标"),
    "NO_MAPPED_GEOLOGICAL_ATTENTION_DIMENSION": ("当前没有可计算地质关注值的映射维度"),
    "RAI_UNAVAILABLE": "施工响应关注值不可用",
    "UNKNOWN": "信息不足",
}

QUALITY_FLAG_LABELS = {
    "UNIT_UNVERIFIED": "单位尚未核验",
    "INTERNAL_INTERRUPTION_PRESENT": "施工过程存在内部中断",
    "ZERO_ADVANCE_TARGET": "有效掘进期间记录推进量为零，需复核",
    "EPISODE_BOUNDARY_CENSORED": "施工片段受文件边界截断",
    "LOW_TEMPORAL_COVERAGE": "时间覆盖不足",
    "LOW_SAMPLE_COUNT": "有效样本数量较少",
    "FOOTPRINT_INSUFFICIENT": "空间轨迹信息不足",
    "LOW_TARGET_QUALITY": "目标施工片段质量较低",
}

ATTRIBUTE_LABELS = {
    "anomaly_level": "异常等级",
    "anomaly_raw_text": "异常原文",
    "block_fall_or_collapse": "掉块或坍塌",
    "design_surrounding_rock_grade": "设计围岩等级",
    "dynamic_elastic_modulus": "动态弹性模量",
    "excavated_face_state": "毛开挖面状态",
    "face_chainage_source_text": "掌子面里程原文",
    "face_state": "掌子面状态",
    "forecast_qualifiers": "预测限定词",
    "form_water_other_raw": "表单水状态附加值",
    "form_water_status": "表单勾选水状态",
    "geological_conclusion": "地质结论",
    "geological_description": "地质描述",
    "joint_aperture": "结构面张开性",
    "joint_development": "节理裂隙发育",
    "joint_extension": "结构面延伸性",
    "joint_roughness": "结构面粗糙度",
    "joint_spacing": "结构面间距",
    "karst_development": "岩溶发育程度",
    "lithology": "岩性",
    "narrative_water_observation": "正文水文观察",
    "observation_scope": "观察范围类型",
    "physical_interpretation": "物性解释",
    "physical_parameters": "物性参数",
    "poisson_ratio": "泊松比",
    "risk_hint": "风险提示",
    "risk_points": "风险点里程",
    "rock_mass_state": "岩体状态",
    "rock_strength": "岩石强度",
    "source_clause_role": "原文语句角色",
    "source_risk_text": "风险原文",
    "stability": "稳定性",
    "suggested_grade": "建议围岩等级",
    "suggested_surrounding_rock_grade": "建议围岩等级",
    "vp": "纵波速度",
    "vp_vs": "纵横波速度比",
    "vs": "横波速度",
    "water_status_conflict": "表单与正文水状态冲突",
    "water_type": "水状态类型",
    "weathering": "风化程度",
}

ATTRIBUTE_VALUE_LABELS = {
    "NONE": "无明确异常",
    "UNKNOWN": "信息不足",
    "FORECAST_SEGMENT": "预测区间",
    "FACE_POINT": "掌子面点位",
    "CURRENT_EXCAVATED_INTERVAL": "当前已开挖区间",
}


def build_human_evaluation_packet(
    repo_root: Path,
    output_dir: Path,
    *,
    write_audit_zip: bool = True,
) -> dict[str, Any]:
    """Build Stage7C.2A packets and deterministic audits."""

    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stage7a_dir = repo_root / "artifacts/stage7a_experimental_protocol_v1_3"
    stage7b_dir = repo_root / "artifacts/stage7b_main_comparison_v1"
    run_dir = stage7b_dir / "runs" / STAGE7B_EXECUTION_ID
    stage7c1_dir = repo_root / "artifacts/stage7c_main_auto_eval_v1_2"

    frozen_ref_audit = _validate_frozen_refs(repo_root)
    task_rows = _load_tasks(stage7a_dir / "stage7_main_benchmark_manifest.json")
    snapshot_rows = _read_jsonl(stage7a_dir / "stage7_preclaim_benchmark_evidence_snapshots.jsonl")
    snapshots = {str(row["benchmark_task_id"]): row for row in snapshot_rows}
    stage7a_freeze_audit = _stage7a_authoritative_context_freeze_audit(
        repo_root, stage7a_dir, task_rows, snapshot_rows
    )
    conditions = json.loads((stage7c1_dir / "condition_manifest.json").read_text())["rows"]
    condition_by_id = {str(row["condition_id"]): row for row in conditions}
    blind_rows = _read_jsonl(run_dir / "stage7b_blind_output_packet.jsonl")
    blind_mapping = _csv_by_key(
        run_dir / "stage7b_blind_output_internal_mapping.csv", "anonymous_output_id"
    )
    no_output_source = _read_csv(stage7c1_dir / "no_output_conditions.csv")
    cell_scopes = _cell_scope_map(repo_root)

    _validate_frozen_counts(task_rows, conditions, blind_rows, no_output_source)

    context_by_task: dict[str, dict[str, str]] = {}
    future_leak_rows: list[dict[str, str]] = []
    for task_id, snapshot in sorted(snapshots.items()):
        context_text = render_authoritative_context(snapshot, cell_scopes)
        context_hash = _sha256_text(context_text)
        context_by_task[task_id] = {
            "context_id": "authoritative_context_" + context_hash[:24],
            "context_hash": context_hash,
            "context_text": context_text,
        }
        future_leak_rows.extend(_future_evidence_checks(snapshot))

    master_rows = _build_master_rows(
        blind_rows,
        blind_mapping,
        condition_by_id,
        context_by_task,
    )
    answer_key = _answer_key(master_rows)
    packet_a, packet_a_metadata = _constrained_packet(master_rows, PACKET_SEEDS["A"])
    packet_b, packet_b_metadata = _constrained_packet(master_rows, PACKET_SEEDS["B"])
    packet_a_rebuilt, _ = _constrained_packet(master_rows, PACKET_SEEDS["A"])
    packet_b_rebuilt, _ = _constrained_packet(master_rows, PACKET_SEEDS["B"])
    deterministic_rebuild_identical = packet_a == packet_a_rebuilt and packet_b == packet_b_rebuilt
    no_output_rows = _no_output_manifest(no_output_source)
    later_key = _later_evidence_key(repo_root, snapshots, cell_scopes)

    calibration_rows, calibration_key = _calibration_materials()
    system_leak_rows = _system_context_identity_leak_audit(master_rows)
    cue_rows = _frozen_output_identity_cue_audit(master_rows)
    identity_rows = _frozen_text_identity_audit(master_rows, blind_rows)
    equivalence_rows = _packet_equivalence_audit(packet_a, packet_b)
    carryover_rows = _packet_carryover_audit({"A": packet_a, "B": packet_b}, master_rows)
    workload = _workload(master_rows)
    workload_comparison = _workload_comparison(
        repo_root / "configs/frozen_inputs/stage7c_human_v1_workload_baseline.json",
        workload,
    )
    batch_summary = _batch_assignment_summary(
        {"A": packet_a_metadata, "B": packet_b_metadata}, master_rows
    )
    protocol = _protocol_json(packet_a_metadata, packet_b_metadata)

    hard_rows = _hard_checks(
        task_rows=task_rows,
        conditions=conditions,
        master_rows=master_rows,
        packet_a=packet_a,
        packet_b=packet_b,
        no_output_rows=no_output_rows,
        calibration_rows=calibration_rows,
        system_leak_rows=system_leak_rows,
        identity_rows=identity_rows,
        equivalence_rows=equivalence_rows,
        carryover_rows=carryover_rows,
        future_leak_rows=future_leak_rows,
        frozen_ref_audit=frozen_ref_audit,
        stage7a_freeze_audit=stage7a_freeze_audit,
        later_key=later_key,
        deterministic_rebuild_identical=deterministic_rebuild_identical,
    )
    hard_fail_count = sum(row["status"] != "PASS" for row in hard_rows)
    if hard_fail_count:
        failed = [row for row in hard_rows if row["status"] != "PASS"]
        raise ValueError(f"Stage7C.2A hard checks failed: {failed}")

    _write_csv(output_dir / "human_eval_master_internal.csv", master_rows)
    _write_json(output_dir / "human_eval_answer_key_internal.json", answer_key)
    _write_json(output_dir / "later_evidence_answer_key_internal.json", later_key)
    _write_csv(output_dir / "human_eval_packet_A.csv", packet_a, list(PACKET_FIELDS))
    _write_csv(output_dir / "human_eval_packet_B.csv", packet_b, list(PACKET_FIELDS))
    _write_packet_batches(output_dir, "A", packet_a)
    _write_packet_batches(output_dir, "B", packet_b)
    _write_csv(output_dir / "human_eval_calibration_packet.csv", calibration_rows)
    _write_json(output_dir / "calibration_answer_key_internal.json", calibration_key)
    _write_csv(output_dir / "annotator_metadata_template.csv", [_annotator_metadata_row()])
    _write_csv(output_dir / "no_output_internal_manifest.csv", no_output_rows)
    _write_json(output_dir / "human_evaluation_workload.json", workload)
    _write_json(output_dir / "context_workload_comparison.json", workload_comparison)
    _write_json(output_dir / "human_evaluation_protocol.json", protocol)
    _write_json(output_dir / "batch_assignment_summary.json", batch_summary)
    _write_csv(output_dir / "system_context_identity_leak_audit.csv", system_leak_rows)
    _write_csv(output_dir / "frozen_output_identity_cue_audit.csv", cue_rows)
    _write_csv(output_dir / "generated_text_frozen_identity_audit.csv", identity_rows)
    _write_csv(output_dir / "packet_equivalence_audit.csv", equivalence_rows)
    _write_csv(output_dir / "packet_carryover_audit.csv", carryover_rows)
    _write_csv(
        output_dir / "stage7a_authoritative_context_freeze_audit.csv",
        stage7a_freeze_audit,
    )
    _write_csv(output_dir / "frozen_git_ref_audit.csv", frozen_ref_audit)
    _write_csv(output_dir / "hard_check.csv", hard_rows)
    (output_dir / "README.md").write_text(_readme(), encoding="utf-8")
    (output_dir / "HUMAN_SEMANTIC_EVALUATION_GUIDE_CN.md").write_text(
        _evaluation_guide(), encoding="utf-8"
    )
    (output_dir / "HUMAN_SEMANTIC_EVALUATION_QUICK_REFERENCE_CN.md").write_text(
        _quick_reference(), encoding="utf-8"
    )
    (output_dir / "HUMAN_EVALUATION_PROTOCOL.md").write_text(_human_protocol(), encoding="utf-8")

    method_version = {
        "schema_version": SCHEMA_VERSION,
        "method_version": METHOD_VERSION,
        "generated_at": GENERATED_AT,
        "stage7b_execution_id": STAGE7B_EXECUTION_ID,
        "stage7a_tag": STAGE7A_TAG,
        "stage7b_tag": STAGE7B_TAG,
        "stage7c1_tag": STAGE7C1_TAG,
        "packet_seeds": PACKET_SEEDS,
        "randomization": {
            "algorithm": "SEEDED_CONSTRAINED_BLOCK_ASSIGNMENT",
            "batch_capacities": list(BATCH_CAPACITIES),
            "minimum_same_task_gap_target": MINIMUM_SAME_TASK_GAP_TARGET,
            "packet_a_minimum_gap": packet_a_metadata["minimum_gap"],
            "packet_b_minimum_gap": packet_b_metadata["minimum_gap"],
        },
        "blindness_definition": "METHOD_LABEL_BLINDED_HUMAN_EVALUATION",
        "uses_llm": False,
        "uses_llm_as_judge": False,
        "api_call_count": 0,
        "stage7b_rerun_count": 0,
        "assigns_human_labels": False,
    }
    _write_json(output_dir / "method_version.json", method_version)
    freeze_manifest = {
        **method_version,
        "artifact_dir": "artifacts/stage7c_human_eval_packet_v1_1",
        "frozen_inputs": {
            "stage7a_commit": STAGE7A_COMMIT,
            "stage7a_tag": STAGE7A_TAG,
            "stage7b_commit": STAGE7B_COMMIT,
            "stage7b_tag": STAGE7B_TAG,
            "stage7c1_commit": STAGE7C1_COMMIT,
            "stage7c1_tag": STAGE7C1_TAG,
        },
        "counts": {
            "tasks": len(task_rows),
            "conditions": len(conditions),
            "actual_texts": len(master_rows),
            "packet_a_rows": len(packet_a),
            "packet_b_rows": len(packet_b),
            "packet_a_batches": len(BATCH_CAPACITIES),
            "packet_b_batches": len(BATCH_CAPACITIES),
            "calibration_rows": len(calibration_rows),
            "no_output_rows": len(no_output_rows),
            "method_text_counts": dict(Counter(row["method_internal"] for row in master_rows)),
        },
        "hard_check_fail_count": hard_fail_count,
        "rating_fields": list(RATING_FIELDS),
        "context_workload": workload_comparison,
        "frozen_output_residual_cue_item_count": sum(
            row["has_residual_identity_cue"] == "true" for row in cue_rows
        ),
    }
    _write_json(output_dir / "freeze_manifest.json", freeze_manifest)
    _write_file_hashes(output_dir)

    zip_path = None
    if write_audit_zip:
        zip_path = _write_audit_zip(repo_root, output_dir, packet_a, packet_b)

    return {
        "artifact_dir": str(output_dir),
        "audit_zip": str(zip_path) if zip_path else "",
        "tasks": len(task_rows),
        "conditions": len(conditions),
        "actual_texts": len(master_rows),
        "packet_a_rows": len(packet_a),
        "packet_b_rows": len(packet_b),
        "calibration_rows": len(calibration_rows),
        "packet_a_minimum_gap": packet_a_metadata["minimum_gap"],
        "packet_b_minimum_gap": packet_b_metadata["minimum_gap"],
        "hard_check_fail_count": hard_fail_count,
    }


def render_authoritative_context(
    snapshot: dict[str, Any], cell_scopes: dict[str, tuple[float, float]]
) -> str:
    """Render one method-neutral Chinese context from a frozen pre-Claim snapshot."""

    valid_date = str(snapshot["valid_time"])
    knowledge_date = str(snapshot["knowledge_time_local_date"])
    scope = snapshot.get("spatial_scope", {})
    cell_id = str(scope.get("cell_id", "")) if isinstance(scope, dict) else ""
    role = ROLE_LABELS.get(str(snapshot.get("state_role", "")), "未指定空间角色")
    product = {
        "all": "综合状态复核",
        "daily_review": "当日已掘复核",
        "forward_attention": "前方关注",
        "metric_review": "关注指标复核",
    }.get(str(snapshot.get("product_type", "")), "工程状态复核")

    lines = [
        "施工日期：" + valid_date,
        "知识时刻：" + knowledge_date,
        "评价任务：" + product,
        "当前空间角色：" + role,
        "相关施工区段：" + _task_scope_text(cell_id, snapshot, cell_scopes),
        "",
        "说明：以下内容仅表示截至该知识时刻，冻结的时点证据快照中可获得的信息。",
        "没有提供某项记录，不表示该工程现象未发生、正常或不存在。",
    ]

    items = list(snapshot.get("preclaim_evidence_items", []))
    operational = [
        item for item in items if item.get("evidence_family") == "OPERATIONAL_RESPONSE_EVIDENCE"
    ]
    geology = [item for item in items if item.get("evidence_family") == "GEOLOGICAL_EVIDENCE"]
    metrics = [item for item in items if item.get("evidence_family") == "STAGE4_ATTENTION_METRIC"]

    lines.extend(["", "【机械施工信息】"])
    if operational:
        lines.extend(_render_operational(operational))
    else:
        lines.append("当前快照没有可用的空间关联机械响应记录。")

    observed = [item for item in geology if item.get("epistemic_status") == "OBSERVED"]
    forecast = [item for item in geology if item.get("epistemic_status") == "FORECAST"]
    lines.extend(["", "【当前可获得的地质预测资料】"])
    if forecast:
        lines.extend(_render_geology(forecast, "预测"))
    else:
        lines.append("当前快照没有可用的地质预测记录。")

    lines.extend(["", "【当前可获得的实际地质观察资料】"])
    if observed:
        lines.extend(_render_geology(observed, "实际观察"))
    else:
        lines.append(
            "当前快照没有可用的实际地质观察记录；这仅表示未提供观察证据，"
            "不表示相关条件未发生、正常或不存在。"
        )

    lines.extend(["", "【非概率关注指标】"])
    lines.append(
        "施工响应关注指标、地质证据关注指标和机械—地质联合关注指标都只是关注程度，"
        "不是风险概率、灾害概率、地质异常概率或因果判断。"
    )
    if metrics:
        lines.extend(_render_metrics(metrics, cell_scopes))
    else:
        lines.append("当前快照没有可用的关注指标记录。")

    lines.extend(
        [
            "",
            "【未知信息的解释】",
            "标记为UNKNOWN、UNAVAILABLE或当前快照未列出的属性，均表示当前信息不足。",
            "不得仅据此断言该项为零、正常、安全、没有问题或不存在。",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _render_operational(items: list[dict[str, Any]]) -> list[str]:
    channels = sorted(
        {
            CHANNEL_LABELS.get(str(item.get("channel_name", "")), str(item.get("channel_name", "")))
            for item in items
        }
    )
    available_dates = sorted(
        {
            str(item.get("actual_available_time", ""))
            for item in items
            if item.get("actual_available_time")
        }
    )
    flags = sorted(
        {
            str(flag)
            for item in items
            for flag in item.get("quality_metadata", {}).get("quality_flags", [])
        }
    )
    lines = [
        f"- 可关联施工响应记录：{len(items)} 条",
        "- 涉及通道：" + "、".join(channels),
        "- 响应证据空间覆盖：" + "；".join(_merged_scope_texts(items)),
    ]
    if available_dates:
        lines.append(
            "- 资料可用日期："
            + (
                available_dates[0]
                if len(available_dates) == 1
                else f"{available_dates[0]} 至 {available_dates[-1]}"
            )
        )
    if flags:
        lines.append(
            "- 数据质量提示："
            + "；".join(QUALITY_FLAG_LABELS.get(flag, "存在其他已记录质量提示") for flag in flags)
        )
    lines.append("- 说明：具体PLC数值一致性由确定性自动评价单独核验。")
    return lines


def _merged_scope_texts(items: list[dict[str, Any]]) -> list[str]:
    intervals = sorted(
        {
            (
                float(item["spatial_scope"]["start_chainage"]),
                float(item["spatial_scope"]["end_chainage"]),
            )
            for item in items
            if isinstance(item.get("spatial_scope"), dict)
            and "start_chainage" in item["spatial_scope"]
            and "end_chainage" in item["spatial_scope"]
        }
    )
    merged: list[list[float]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    if not merged:
        return ["未提供明确空间范围"]
    return [
        _format_chainage(start) + (" 点位" if start == end else f" 至 {_format_chainage(end)}")
        for start, end in merged
    ]


def _render_geology(items: list[dict[str, Any]], modality: str) -> list[str]:
    lines: list[str] = []
    for index, item in enumerate(sorted(items, key=_geology_sort_key), 1):
        lines.append(f"{modality}资料 {index}：")
        lines.append(f"- 来源类型：{_source_type_label(str(item.get('source_type', '')))}")
        lines.append(f"- 认识性质：{modality}")
        lines.append(
            "- 使用角色："
            + ROLE_LABELS.get(
                str(item.get("applicability_role", "")),
                str(item.get("applicability_role", "")),
            )
        )
        lines.append(f"- 可用日期：{item.get('actual_available_time', '')}")
        lines.append(f"- 空间范围：{_scope_text(item.get('spatial_scope'))}")
        attrs = item.get("structured_source_attributes", {})
        if not isinstance(attrs, dict) or not attrs:
            lines.append("- 记录内容：当前结构化字段为空。")
            continue
        narrative_values = [
            str(attrs[key])
            for key in ("geological_conclusion", "geological_description")
            if attrs.get(key) not in (None, "", [], {})
        ]
        displayed_narratives: list[str] = []
        for value in narrative_values:
            normalized = _normalized_for_dedup(value)
            if any(
                normalized in previous or previous in normalized
                for previous in displayed_narratives
            ):
                continue
            displayed_narratives.append(normalized)
            lines.append(f"- 地质记录：{value}")
        for key, value in attrs.items():
            if key == "face_chainage_source_span" or value in (None, "", [], {}):
                continue
            if key in {"geological_conclusion", "geological_description"}:
                continue
            if key in {"observation_scope", "source_clause_role"}:
                continue
            if isinstance(value, str) and any(
                _normalized_for_dedup(value) in narrative for narrative in displayed_narratives
            ):
                continue
            label = ATTRIBUTE_LABELS.get(key, key.replace("_", " "))
            rendered_value = ATTRIBUTE_VALUE_LABELS.get(str(value), _display_value(value))
            lines.append(f"- {label}：{rendered_value}")
    return lines


def _normalized_for_dedup(value: str) -> str:
    return re.sub(r"[\s，。；：、,.;:]", "", value)


def _render_metrics(
    items: list[dict[str, Any]], cell_scopes: dict[str, tuple[float, float]]
) -> list[str]:
    lines: list[str] = []
    labels = {
        "RAI": "施工响应关注指标（RAI）",
        "GRS": "地质证据关注指标（GRS）",
        "GRCI": "机械—地质联合关注指标（GRCI）",
    }
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for item in items:
        scope = item.get("spatial_scope", {})
        cell_id = str(scope.get("cell_id", "")) if isinstance(scope, dict) else ""
        grouped[(str(item.get("valid_time", "")), cell_id)][str(item.get("metric_name", ""))] = item
    for (valid_time, cell_id), group in sorted(grouped.items()):
        scope_text = _cell_scope_text(cell_id, cell_scopes)
        lines.append(f"- 日期 {valid_time}，范围 {scope_text}：")
        for metric in ("RAI", "GRS", "GRCI"):
            metric_item = group.get(metric)
            if not metric_item:
                continue
            raw_status = str(metric_item.get("metric_status", "UNKNOWN"))
            status = METRIC_STATUS_LABELS.get(raw_status, "当前指标不可用，原因已记录")
            value = metric_item.get("raw_value")
            value_text = _number(value) if isinstance(value, int | float) else "不可用"
            line = f"  - {labels[metric]}：状态={status}，值={value_text}"
            if metric == "RAI" and raw_status == "AVAILABLE":
                attrs = metric_item.get("structured_source_attributes", {})
                families = (
                    attrs.get("family_attention_values", {}) if isinstance(attrs, dict) else {}
                )
                line += (
                    f"；载荷响应关注={_number(families.get('LOAD_RESPONSE'))}"
                    f"；推进运动响应关注={_number(families.get('ADVANCE_KINEMATIC_RESPONSE'))}"
                )
            lines.append(line)
    return lines


def _build_master_rows(
    blind_rows: list[dict[str, Any]],
    mapping: dict[str, dict[str, str]],
    conditions: dict[str, dict[str, Any]],
    context_by_task: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for blind in blind_rows:
        anonymous_text_id = str(blind["anonymous_output_id"])
        internal = mapping[anonymous_text_id]
        condition_id = str(internal["execution_item_id"])
        condition = conditions[condition_id]
        task_id = str(internal["benchmark_task_id"])
        context = context_by_task[task_id]
        generated_text = str(blind["output_text"])
        anonymous_condition_id = (
            "stage7c_blind_condition_" + stable_id("condition", anonymous_text_id)[:24]
        )
        rows.append(
            {
                "internal_distribution_notice": "INTERNAL_ONLY_DO_NOT_DISTRIBUTE",
                "annotation_item_id": "stage7c_human_item_"
                + stable_id("annotation", anonymous_text_id)[:24],
                "anonymous_condition_id": anonymous_condition_id,
                "anonymous_text_id": anonymous_text_id,
                "task_id_internal": task_id,
                "condition_id_internal": condition_id,
                "method_internal": str(internal["method_id"]),
                "product_type_internal": str(condition["product_type"]),
                "valid_date": str(condition["valid_date"]),
                "knowledge_as_of": str(condition["knowledge_as_of"]),
                "authoritative_context_id": context["context_id"],
                "authoritative_context_hash": context["context_hash"],
                "engineering_context": context["context_text"],
                "generated_text": generated_text,
                "generated_text_hash": _sha256_text(generated_text),
                "output_available": "true",
            }
        )
    return sorted(rows, key=lambda row: row["annotation_item_id"])


def _public_packet_row(master: dict[str, str]) -> dict[str, str]:
    row = {
        "annotation_item_id": master["annotation_item_id"],
        "anonymous_condition_id": master["anonymous_condition_id"],
        "engineering_context": master["engineering_context"],
        "generated_text": master["generated_text"],
    }
    row.update({field: "" for field in RATING_FIELDS})
    return row


def _constrained_packet(
    master_rows: list[dict[str, str]], seed: int
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    for target_gap in (MINIMUM_SAME_TASK_GAP_TARGET, 10):
        for attempt in range(5000):
            ordered = _try_constrained_order(
                master_rows,
                seed + attempt * 1_000_003,
                target_gap,
            )
            if ordered is None:
                continue
            positions: dict[str, list[int]] = defaultdict(list)
            for position, row in enumerate(ordered, 1):
                positions[row["task_id_internal"]].append(position)
            minimum_gap = min(
                right - left
                for task_positions in positions.values()
                for left, right in pairwise(task_positions)
            )
            packet = [_public_packet_row(row) for row in ordered]
            return packet, {
                "seed": seed,
                "search_attempt": attempt,
                "requested_minimum_gap": MINIMUM_SAME_TASK_GAP_TARGET,
                "applied_minimum_gap_constraint": target_gap,
                "minimum_gap": minimum_gap,
                "packet_hash": stable_hash(packet),
                "batch_hashes": [stable_hash(batch) for batch in _packet_batches(packet)],
            }
    raise ValueError("No deterministic constrained packet order satisfies the minimum gap")


def _try_constrained_order(
    master_rows: list[dict[str, str]], seed: int, target_gap: int
) -> list[dict[str, str]] | None:
    rng = random.Random(seed)
    remaining = list(master_rows)
    ordered: list[dict[str, str]] = []
    last_position: dict[str, int] = {}
    batch_tasks: set[str] = set()
    method_counts: Counter[tuple[int, str]] = Counter()
    product_counts: Counter[tuple[int, str]] = Counter()
    previous_batch = -1

    for position in range(1, len(master_rows) + 1):
        batch_index = _batch_index_for_position(position)
        if batch_index != previous_batch:
            batch_tasks = set()
            previous_batch = batch_index
        candidates = [
            row
            for row in remaining
            if row["task_id_internal"] not in batch_tasks
            and position - last_position.get(row["task_id_internal"], -10_000) >= target_gap
        ]
        if not candidates:
            return None
        rng.shuffle(candidates)
        remaining_by_task = Counter(row["task_id_internal"] for row in remaining)

        def score(
            row: dict[str, str],
            batch: int = batch_index,
            task_counts: Counter[str] = remaining_by_task,
        ) -> tuple[int, int, int, int]:
            task_id = row["task_id_internal"]
            return (
                method_counts[(batch, row["method_internal"])],
                product_counts[(batch, row["product_type_internal"])],
                -task_counts[task_id],
                last_position.get(task_id, -10_000),
            )

        best_score = min(score(row) for row in candidates)
        selected_pool = [row for row in candidates if score(row) == best_score]
        selected = rng.choice(selected_pool)
        ordered.append(selected)
        remaining.remove(selected)
        task_id = selected["task_id_internal"]
        batch_tasks.add(task_id)
        last_position[task_id] = position
        method_counts[(batch_index, selected["method_internal"])] += 1
        product_counts[(batch_index, selected["product_type_internal"])] += 1
    return ordered


def _batch_index_for_position(position: int) -> int:
    boundary = 0
    for index, capacity in enumerate(BATCH_CAPACITIES):
        boundary += capacity
        if position <= boundary:
            return index
    raise ValueError(f"Position is outside packet capacity: {position}")


def _packet_batches(packet: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    batches = []
    start = 0
    for capacity in BATCH_CAPACITIES:
        batches.append(packet[start : start + capacity])
        start += capacity
    if start != len(packet):
        raise ValueError(f"Packet size {len(packet)} does not match batch capacities")
    return batches


def _write_packet_batches(output_dir: Path, packet_name: str, packet: list[dict[str, str]]) -> None:
    for index, batch in enumerate(_packet_batches(packet), 1):
        _write_csv(
            output_dir / f"human_eval_packet_{packet_name}_batch_{index:02d}.csv",
            batch,
            list(PACKET_FIELDS),
        )


def _answer_key(master_rows: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "notice": "INTERNAL — DO NOT DISTRIBUTE TO ANNOTATORS",
        "schema_version": SCHEMA_VERSION,
        "rows": [
            {
                "annotation_item_id": row["annotation_item_id"],
                "anonymous_condition_id": row["anonymous_condition_id"],
                "task_id": row["task_id_internal"],
                "condition_id": row["condition_id_internal"],
                "method": row["method_internal"],
                "context_hash": row["authoritative_context_hash"],
                "text_hash": row["generated_text_hash"],
            }
            for row in master_rows
        ],
    }


def _no_output_manifest(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "internal_distribution_notice": "INTERNAL_ONLY_DO_NOT_DISTRIBUTE",
            "task_id": row["task_id"],
            "condition_id": row["condition_id"],
            "method": row["method_internal"],
            "reason": row["output_status"],
            "validator_code": row["validator_reason"],
            "included_in_human_text_packet": "false",
            "retained_in_method_task_denominator": "true",
        }
        for row in sorted(rows, key=lambda item: item["task_id"])
    ]


def _later_evidence_key(
    repo_root: Path,
    snapshots: dict[str, dict[str, Any]],
    cell_scopes: dict[str, tuple[float, float]],
) -> dict[str, Any]:
    geology = _read_jsonl(
        repo_root / "artifacts/stage2_geology_v2_freeze_candidate/primary_geological_evidence.jsonl"
    )
    documents = _jsonl_by_key(
        repo_root / "artifacts/stage2_geology_v2_freeze_candidate/geological_documents.jsonl",
        "document_id",
    )
    rows: list[dict[str, Any]] = []
    for task_id, snapshot in sorted(snapshots.items()):
        knowledge_as_of = str(snapshot["knowledge_time_local_date"])
        active_ids = {
            str(item.get("evidence_id", "")) for item in snapshot.get("preclaim_evidence_items", [])
        }
        task_intervals = _snapshot_intervals(snapshot, cell_scopes)
        later: list[dict[str, Any]] = []
        for evidence in geology:
            evidence_id = str(evidence["evidence_uid"])
            if evidence_id in active_ids:
                continue
            document = documents.get(str(evidence.get("document_id", "")), {})
            temporal = document.get("document", {}).get("temporal", {})
            available = str(temporal.get("available_local_date") or "")
            if not available or available <= knowledge_as_of:
                continue
            evidence_scope = evidence.get("spatial_scope", {})
            if not _scope_overlaps_intervals(evidence_scope, task_intervals):
                continue
            later.append(
                {
                    "evidence_id": evidence_id,
                    "later_available_time": available,
                    "epistemic_status": str(evidence.get("epistemic_status", "")),
                    "source_type": str(evidence.get("source_type", "")),
                    "spatial_scope": evidence_scope,
                    "later_supported_fact_summary": _geology_fact_summary(evidence),
                    "relationship_basis": "LATER_AVAILABLE_SPATIALLY_OVERLAPPING_EVIDENCE",
                }
            )
        rows.append(
            {
                "task_id": task_id,
                "knowledge_as_of": knowledge_as_of,
                "task_spatial_intervals": [
                    {"start_chainage": start, "end_chainage": end} for start, end in task_intervals
                ],
                "later_evidence": sorted(
                    later,
                    key=lambda item: (
                        item["later_available_time"],
                        item["evidence_id"],
                    ),
                ),
            }
        )
    return {
        "notice": "INTERNAL — DO NOT DISTRIBUTE TO INITIAL ANNOTATORS",
        "purpose": "Later-evidence adjudication only; never copied into packet A or B.",
        "schema_version": SCHEMA_VERSION,
        "rows": rows,
    }


def _snapshot_intervals(
    snapshot: dict[str, Any],
    cell_scopes: dict[str, tuple[float, float]],
) -> list[tuple[float, float]]:
    intervals: set[tuple[float, float]] = set()
    scopes = [snapshot.get("spatial_scope", {})]
    scopes.extend(
        item.get("spatial_scope", {}) for item in snapshot.get("preclaim_evidence_items", [])
    )
    for scope in scopes:
        if not isinstance(scope, dict):
            continue
        if "start_chainage" in scope and "end_chainage" in scope:
            intervals.add((float(scope["start_chainage"]), float(scope["end_chainage"])))
            continue
        cell_scope = cell_scopes.get(str(scope.get("cell_id", "")))
        if cell_scope:
            intervals.add(cell_scope)
    return sorted(intervals)


def _scope_overlaps_intervals(scope: Any, intervals: list[tuple[float, float]]) -> bool:
    if not isinstance(scope, dict):
        return False
    start = scope.get("start_chainage")
    end = scope.get("end_chainage")
    if start is None or end is None:
        return False
    evidence_start = float(start)
    evidence_end = float(end)
    return any(
        evidence_start <= target_end and evidence_end >= target_start
        for target_start, target_end in intervals
    )


def _geology_fact_summary(evidence: dict[str, Any]) -> str:
    attrs = evidence.get("attributes", {})
    if not isinstance(attrs, dict):
        return ""
    selected = {
        ATTRIBUTE_LABELS.get(key, key): value
        for key, value in attrs.items()
        if value not in (None, "", [], {}) and key != "face_chainage_source_span"
    }
    return _display_value(selected)


def _calibration_materials() -> tuple[list[dict[str, str]], dict[str, Any]]:
    examples = [
        (
            "正确预测表达",
            "知识时刻内仅有前方K1000–K1010的预测资料：可能为节理发育岩体；没有实际观察记录。",
            "预测资料提示K1000–K1010前方可能存在节理发育岩体，需以实际揭露复核。",
            {},
            "保持预测性质，未写成当前事实。",
        ),
        (
            "预测转事实错误",
            "仅有前方K1100–K1110预测：岩体破碎；没有实际观察记录。",
            "当前现场岩体已经破碎。",
            {"E1_unsupported_claim": "1", "E5_forecast_factification": "1"},
            "将前方预测写成当前事实。",
        ),
        (
            "无观察依据却声称观察",
            "当前没有可用的实际地质观察记录。",
            "现场已揭露明显掉块。",
            {"E1_unsupported_claim": "1", "E6_observed_without_proof": "1"},
            "使用了明确观察措辞，但上下文没有观察依据。",
        ),
        (
            "正确并列",
            "机械响应关注值为0.42；独立预测资料提示前方节理发育。两者均不提供因果关系。",
            "机械响应值得关注；同时，独立预测资料提示前方节理发育。",
            {},
            "只并列两类信息，没有宣称因果。",
        ),
        (
            "错误机械地质因果",
            "推力关注值升高；预测资料提示岩体破碎；没有正式因果证据。",
            "推力升高证明岩体破碎是本次变化的原因。",
            {"E9_mechanical_geological_causation": "1"},
            "从机械变化直接推出地质原因。",
        ),
        (
            "正确关注指标表达",
            "机械—地质联合关注指标为0.40；该指标不是概率。",
            "联合关注指标为0.40，表示当前耦合关注程度。",
            {},
            "保留了非概率关注语义。",
        ),
        (
            "关注指标转概率错误",
            "机械—地质联合关注指标为0.40；该指标不是概率。",
            "地质灾害发生概率为40%。",
            {"E10_attention_probability_promotion": "1"},
            "把非概率指标转换为灾害概率。",
        ),
        (
            "正确保留未知",
            "当前水相关信息为UNKNOWN，表示信息不足。",
            "当前水相关状态尚无法确定。",
            {},
            "没有把未知解释为正常。",
        ),
        (
            "未知转正常错误",
            "当前水相关信息为UNKNOWN，表示信息不足。",
            "当前没有地下水问题，状态正常。",
            {"E11_unknown_to_normal": "1"},
            "把信息不足写成无问题和正常。",
        ),
        (
            "合理管理建议",
            "预测资料提示前方可能节理发育；没有当前掉块观察。",
            "建议后续开挖加强观察，并根据实际揭露调整支护。",
            {},
            "管理建议不是对已发生工程事实的断言。",
        ),
        (
            "角色边界错误",
            "资料属于前方关注范围，仅描述尚未开挖区段的预测条件。",
            "当天已掘区段已经出现预测所述破碎围岩。",
            {
                "E1_unsupported_claim": "1",
                "E5_forecast_factification": "1",
                "E8_role_boundary_violation": "1",
            },
            "把前方预测错误写成当天已掘区段的事实。",
        ),
        (
            "无支持事实的后到来源初始未知",
            "截至当前知识时刻，没有资料支持前方存在股状出水。",
            "前方区段存在股状出水。",
            {"E1_unsupported_claim": "1", "E7_hindsight_leakage": "U"},
            "当前可确定无支持，但初始评价者无法判断该事实是否来自后到证据。",
        ),
    ]
    rows: list[dict[str, str]] = []
    answers: list[dict[str, Any]] = []
    for index, (name, context, text, labels, reason) in enumerate(examples, 1):
        item_id = f"training_only_{index:02d}"
        row = {
            "training_only": "TRAINING_ONLY",
            "annotation_item_id": item_id,
            "anonymous_condition_id": "calibration_condition_"
            + stable_id("calibration", {"case_name": name})[:16],
            "engineering_context": context,
            "generated_text": text,
            **{field: "" for field in RATING_FIELDS},
        }
        rows.append(row)
        full_labels = {field: "0" for field in RATING_FIELDS if field.startswith("E")}
        full_labels.update(labels)
        full_labels["overall_semantic_error"] = "1" if labels else "0"
        answers.append(
            {
                "annotation_item_id": item_id,
                "case_name": name,
                "suggested_binary_labels": full_labels,
                "reason": reason,
            }
        )
    return rows, {
        "notice": "INTERNAL — CALIBRATION DISCUSSION ONLY",
        "schema_version": SCHEMA_VERSION,
        "rows": answers,
    }


def _system_context_identity_leak_audit(
    master_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    rows = []
    for item in master_rows:
        context_hits = _term_hits(item["engineering_context"], CONTEXT_BANNED_TERMS)
        metadata_text = " ".join([item["annotation_item_id"], item["anonymous_condition_id"]])
        metadata_hits = _term_hits(metadata_text, CONTEXT_BANNED_TERMS)
        rows.append(
            {
                "annotation_item_id": item["annotation_item_id"],
                "engineering_context_leak_terms": ";".join(context_hits),
                "packet_metadata_leak_terms": ";".join(metadata_hits),
                "status": "PASS" if not context_hits and not metadata_hits else "FAIL",
            }
        )
    return rows


def _frozen_output_identity_cue_audit(
    master_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    rows = []
    for item in master_rows:
        cue_terms = sorted(
            name
            for name, pattern in FROZEN_OUTPUT_CUE_PATTERNS.items()
            if re.search(pattern, item["generated_text"], re.IGNORECASE)
        )
        rows.append(
            {
                "annotation_item_id": item["annotation_item_id"],
                "cue_terms": ";".join(cue_terms),
                "cue_count": str(len(cue_terms)),
                "has_residual_identity_cue": str(bool(cue_terms)).lower(),
                "audit_interpretation": (
                    "REPORT_ONLY_NOT_A_SEMANTIC_ERROR_AND_NOT_A_HARD_FAIL"
                    if cue_terms
                    else "NO_SCANNED_INTERNAL_CUE"
                ),
                "generated_text_modified": "false",
            }
        )
    return rows


def _frozen_text_identity_audit(
    master_rows: list[dict[str, str]], blind_rows: list[dict[str, Any]]
) -> list[dict[str, str]]:
    frozen = {str(row["anonymous_output_id"]): str(row["output_text"]) for row in blind_rows}
    rows = []
    for item in master_rows:
        source = frozen[item["anonymous_text_id"]]
        rows.append(
            {
                "annotation_item_id": item["annotation_item_id"],
                "frozen_text_hash": _sha256_text(source),
                "packet_text_hash": item["generated_text_hash"],
                "match": str(source == item["generated_text"]).lower(),
            }
        )
    return rows


def _packet_equivalence_audit(
    packet_a: list[dict[str, str]], packet_b: list[dict[str, str]]
) -> list[dict[str, str]]:
    a_index = {row["annotation_item_id"]: index for index, row in enumerate(packet_a, 1)}
    b_index = {row["annotation_item_id"]: index for index, row in enumerate(packet_b, 1)}
    b_by_id = {row["annotation_item_id"]: row for row in packet_b}
    rows = []
    for item in packet_a:
        other = b_by_id[item["annotation_item_id"]]
        rows.append(
            {
                "annotation_item_id": item["annotation_item_id"],
                "a_order": str(a_index[item["annotation_item_id"]]),
                "b_order": str(b_index[item["annotation_item_id"]]),
                "anonymous_id_match": str(
                    item["anonymous_condition_id"] == other["anonymous_condition_id"]
                ).lower(),
                "context_hash_match": str(
                    _sha256_text(item["engineering_context"])
                    == _sha256_text(other["engineering_context"])
                ).lower(),
                "text_hash_match": str(
                    _sha256_text(item["generated_text"]) == _sha256_text(other["generated_text"])
                ).lower(),
                "rating_fields_blank_in_both": str(
                    all(not item[field] and not other[field] for field in RATING_FIELDS)
                ).lower(),
            }
        )
    return rows


def _packet_carryover_audit(
    packets: dict[str, list[dict[str, str]]], master_rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    task_by_item = {row["annotation_item_id"]: row["task_id_internal"] for row in master_rows}
    rows = []
    for packet_name, packet in sorted(packets.items()):
        positions: dict[str, list[int]] = defaultdict(list)
        for position, item in enumerate(packet, 1):
            positions[task_by_item[item["annotation_item_id"]]].append(position)
        for task_id, task_positions in sorted(positions.items()):
            pairwise_gaps = [
                right - left
                for left_index, left in enumerate(task_positions)
                for right in task_positions[left_index + 1 :]
            ]
            batch_ids = [_batch_index_for_position(position) + 1 for position in task_positions]
            batch_counts = Counter(batch_ids)
            rows.append(
                {
                    "packet": packet_name,
                    "task_id_internal": task_id,
                    "positions": ";".join(map(str, task_positions)),
                    "pairwise_gaps": ";".join(map(str, pairwise_gaps)),
                    "minimum_gap": str(min(pairwise_gaps)),
                    "batch_ids": ";".join(f"batch_{batch_id:02d}" for batch_id in batch_ids),
                    "same_batch_pair_count": str(
                        sum(count * (count - 1) // 2 for count in batch_counts.values())
                    ),
                    "adjacent_pair_count": str(sum(gap == 1 for gap in pairwise_gaps)),
                }
            )
    return rows


def _future_evidence_checks(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    knowledge_date = str(snapshot["knowledge_time_local_date"])
    rows = []
    for item in snapshot.get("preclaim_evidence_items", []):
        available = str(item.get("actual_available_time", ""))
        available_date = available[:10]
        valid = bool(available_date) and available_date <= knowledge_date
        rows.append(
            {
                "task_id": str(snapshot["benchmark_task_id"]),
                "source_id": str(item.get("evidence_id", "")),
                "available_date": available_date,
                "knowledge_as_of": knowledge_date,
                "active_asof": str(valid).lower(),
            }
        )
    return rows


def _workload(master_rows: list[dict[str, str]]) -> dict[str, Any]:
    context_lengths = [len(row["engineering_context"]) for row in master_rows]
    text_lengths = [len(row["generated_text"]) for row in master_rows]
    return {
        "items_per_annotator": len(master_rows),
        "total_context_characters": sum(context_lengths),
        "median_context_characters": statistics.median(context_lengths),
        "total_generated_text_characters": sum(text_lengths),
        "median_generated_text_characters": statistics.median(text_lengths),
        "total_displayed_characters": sum(context_lengths) + sum(text_lengths),
        "time_estimate_provided": False,
    }


def _workload_comparison(v1_path: Path, v1_1: dict[str, Any]) -> dict[str, Any]:
    v1 = json.loads(v1_path.read_text(encoding="utf-8"))
    v1_total = int(v1["total_context_characters"])
    new_total = int(v1_1["total_context_characters"])
    return {
        "v1_median_context_characters": v1["median_context_characters"],
        "v1_1_median_context_characters": v1_1["median_context_characters"],
        "v1_total_context_characters": v1_total,
        "v1_1_total_context_characters": new_total,
        "context_character_reduction_percentage": round((v1_total - new_total) / v1_total * 100, 6),
        "compression_policy": "REMOVE_RAW_PLC_NUMERIC_DUMP_KEEP_AUTHORITATIVE_SEMANTICS",
        "evidence_truncation_used": False,
    }


def _batch_assignment_summary(
    packet_metadata: dict[str, dict[str, Any]], master_rows: list[dict[str, str]]
) -> dict[str, Any]:
    master_by_item = {row["annotation_item_id"]: row for row in master_rows}
    summary: dict[str, Any] = {
        "notice": "INTERNAL — METHOD COUNTS MUST NOT BE SHOWN TO ANNOTATORS",
        "batch_capacities": list(BATCH_CAPACITIES),
        "minimum_same_task_gap_target": MINIMUM_SAME_TASK_GAP_TARGET,
        "packets": {},
    }
    for packet_name, metadata in sorted(packet_metadata.items()):
        packet_rows = _constrained_packet(master_rows, int(metadata["seed"]))[0]
        batches = []
        for index, batch in enumerate(_packet_batches(packet_rows), 1):
            internal = [master_by_item[row["annotation_item_id"]] for row in batch]
            batches.append(
                {
                    "batch_id": f"batch_{index:02d}",
                    "row_count": len(batch),
                    "batch_hash": stable_hash(batch),
                    "method_distribution_internal": dict(
                        sorted(Counter(row["method_internal"] for row in internal).items())
                    ),
                    "product_distribution": dict(
                        sorted(Counter(row["product_type_internal"] for row in internal).items())
                    ),
                }
            )
        summary["packets"][packet_name] = {**metadata, "batches": batches}
    return summary


def _protocol_json(
    packet_a_metadata: dict[str, Any], packet_b_metadata: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "method_version": METHOD_VERSION,
        "packet_seeds": PACKET_SEEDS,
        "formal_item_count": 141,
        "calibration_item_count": 12,
        "annotators": 2,
        "evaluation_unit": "WHOLE_CONDITION_TEXT",
        "binary_values": ["0", "1", "U"],
        "likert_values": [1, 2, 3, 4, 5],
        "confidence_values": [1, 2, 3],
        "rating_fields": list(RATING_FIELDS),
        "blindness_definition": "METHOD_LABEL_BLINDED_HUMAN_EVALUATION",
        "frozen_output_residual_cues_possible": True,
        "same_task_same_context": True,
        "randomization": {
            "algorithm": "SEEDED_CONSTRAINED_BLOCK_ASSIGNMENT",
            "batch_capacities": list(BATCH_CAPACITIES),
            "minimum_same_task_gap_target": MINIMUM_SAME_TASK_GAP_TARGET,
            "packet_a": packet_a_metadata,
            "packet_b": packet_b_metadata,
        },
        "no_output_policy": {
            "excluded_from_text_quality_packet": True,
            "retained_in_48_task_denominator": True,
        },
        "initial_e7_policy": (
            "Use U when later origin cannot be established from the initial packet."
        ),
    }


def _hard_checks(
    *,
    task_rows: list[dict[str, Any]],
    conditions: list[dict[str, Any]],
    master_rows: list[dict[str, str]],
    packet_a: list[dict[str, str]],
    packet_b: list[dict[str, str]],
    no_output_rows: list[dict[str, str]],
    calibration_rows: list[dict[str, str]],
    system_leak_rows: list[dict[str, str]],
    identity_rows: list[dict[str, str]],
    equivalence_rows: list[dict[str, str]],
    carryover_rows: list[dict[str, str]],
    future_leak_rows: list[dict[str, str]],
    frozen_ref_audit: list[dict[str, str]],
    stage7a_freeze_audit: list[dict[str, str]],
    later_key: dict[str, Any],
    deterministic_rebuild_identical: bool,
) -> list[dict[str, str]]:
    methods = Counter(row["method_internal"] for row in master_rows)
    condition_methods = Counter(str(row["method_internal"]) for row in conditions)
    no_output_ids = {row["task_id"] for row in no_output_rows}
    a_ids = [row["annotation_item_id"] for row in packet_a]
    b_ids = [row["annotation_item_id"] for row in packet_b]
    prefilled = sum(bool(row[field]) for row in packet_a + packet_b for field in RATING_FIELDS)
    contexts_by_task: dict[str, set[str]] = defaultdict(set)
    for row in master_rows:
        contexts_by_task[row["task_id_internal"]].add(row["authoritative_context_hash"])
    main_hashes = {row["generated_text_hash"] for row in master_rows}
    calibration_hashes = {_sha256_text(row["generated_text"]) for row in calibration_rows}
    context_leaks = sum(row["status"] != "PASS" for row in system_leak_rows)
    frozen_mismatches = sum(row["match"] != "true" for row in identity_rows)
    equivalence_issues = sum(
        any(
            row[field] != "true"
            for field in [
                "anonymous_id_match",
                "context_hash_match",
                "text_hash_match",
                "rating_fields_blank_in_both",
            ]
        )
        for row in equivalence_rows
    )
    future_leaks = sum(row["active_asof"] != "true" for row in future_leak_rows)
    ref_issues = sum(row["status"] != "PASS" for row in frozen_ref_audit)
    stage7a_issues = sum(row["status"] != "PASS" for row in stage7a_freeze_audit)
    carryover_by_packet = {
        packet: [row for row in carryover_rows if row["packet"] == packet] for packet in ("A", "B")
    }
    same_batch_counts = {
        packet: sum(int(row["same_batch_pair_count"]) for row in rows)
        for packet, rows in carryover_by_packet.items()
    }
    adjacent_counts = {
        packet: sum(int(row["adjacent_pair_count"]) for row in rows)
        for packet, rows in carryover_by_packet.items()
    }
    minimum_gaps = {
        packet: min(int(row["minimum_gap"]) for row in rows)
        for packet, rows in carryover_by_packet.items()
    }
    context_text = "\n".join(
        {
            row["authoritative_context_hash"]: row["engineering_context"] for row in master_rows
        }.values()
    )
    raw_plc_dump_tokens = (
        "均值=",
        "中位数=",
        "P10=",
        "P90=",
        "最小值=",
        "最大值=",
        "变异系数=",
        "样本数=",
        "缺失率=",
    )
    untranslated_metric_statuses = (
        "GRCI_NOT_DEFINED_FOR_FORWARD_ATTENTION",
        "GRCI_NOT_DEFINED_FOR_LOCAL_BACKGROUND",
        "NO_CELL_LINKED_OPERATIONAL_RESPONSE",
        "NO_MAPPED_GEOLOGICAL_ATTENTION_DIMENSION",
        "RAI_UNAVAILABLE",
        "INSUFFICIENT_CAUSAL_BASELINE",
    )
    later_rows = later_key["rows"]
    later_count = sum(len(row["later_evidence"]) for row in later_rows)
    later_ids = {item["evidence_id"] for row in later_rows for item in row["later_evidence"]}
    later_id_packet_leaks = sum(
        any(evidence_id in row["engineering_context"] for evidence_id in later_ids)
        for row in packet_a
    )

    checks: list[tuple[str, bool, Any]] = [
        ("task_count_48", len(task_rows) == 48, len(task_rows)),
        ("condition_count_144", len(conditions) == 144, len(conditions)),
        ("b0_condition_count_48", condition_methods["B0_DIRECT_LLM"] == 48, condition_methods),
        (
            "b1_condition_count_48",
            condition_methods["B1_STRUCTURED_PROMPT_LLM"] == 48,
            condition_methods,
        ),
        ("p_condition_count_48", condition_methods["P_PROPOSED"] == 48, condition_methods),
        ("actual_text_count_141", len(master_rows) == 141, len(master_rows)),
        ("b0_text_count_48", methods["B0_DIRECT_LLM"] == 48, methods),
        ("b1_text_count_48", methods["B1_STRUCTURED_PROMPT_LLM"] == 48, methods),
        ("p_text_count_45", methods["P_PROPOSED"] == 45, methods),
        ("p_no_output_count_3", len(no_output_rows) == 3, len(no_output_rows)),
        (
            "no_output_task_ids_exact",
            no_output_ids == EXPECTED_NO_OUTPUT_TASKS,
            sorted(no_output_ids),
        ),
        ("packet_a_rows_141", len(packet_a) == 141, len(packet_a)),
        ("packet_b_rows_141", len(packet_b) == 141, len(packet_b)),
        ("packet_same_item_set", set(a_ids) == set(b_ids), "same set"),
        ("packet_order_differs", a_ids != b_ids, "different order"),
        ("packet_equivalence_issue_zero", equivalence_issues == 0, equivalence_issues),
        (
            "removed_human_fields_absent",
            all(
                field not in packet_a[0]
                for field in (
                    "E2_numeric_value_error",
                    "E4_spatial_scope_error",
                    "numeric_spatial_correctness_score",
                )
            ),
            sorted(packet_a[0]),
        ),
        (
            "raw_plc_numeric_dump_removed",
            not any(token in context_text for token in raw_plc_dump_tokens),
            [token for token in raw_plc_dump_tokens if token in context_text],
        ),
        (
            "metric_statuses_humanized",
            not any(status in context_text for status in untranslated_metric_statuses),
            [status for status in untranslated_metric_statuses if status in context_text],
        ),
        ("prefilled_human_label_count_zero", prefilled == 0, prefilled),
        (
            "same_task_context_mismatch_zero",
            all(len(v) == 1 for v in contexts_by_task.values()),
            sum(len(v) != 1 for v in contexts_by_task.values()),
        ),
        ("future_evidence_leak_zero", future_leaks == 0, future_leaks),
        ("later_evidence_key_task_count_48", len(later_rows) == 48, len(later_rows)),
        ("later_evidence_key_nonempty", later_count > 0, later_count),
        (
            "later_evidence_id_packet_leak_zero",
            later_id_packet_leaks == 0,
            later_id_packet_leaks,
        ),
        ("system_added_identity_leak_zero", context_leaks == 0, context_leaks),
        (
            "claimdecision_leak_zero",
            _specific_packet_leak(packet_a, "ClaimDecision") == 0,
            _specific_packet_leak(packet_a, "ClaimDecision"),
        ),
        (
            "factlock_leak_zero",
            _specific_packet_leak(packet_a, "FactLock") == 0,
            _specific_packet_leak(packet_a, "FactLock"),
        ),
        (
            "automatic_result_leak_zero",
            _specific_packet_leak(packet_a, "automatic evaluation result") == 0,
            _specific_packet_leak(packet_a, "automatic evaluation result"),
        ),
        ("calibration_count_12", len(calibration_rows) == 12, len(calibration_rows)),
        (
            "calibration_main_overlap_zero",
            not (main_hashes & calibration_hashes),
            len(main_hashes & calibration_hashes),
        ),
        ("frozen_stage7b_text_mismatch_zero", frozen_mismatches == 0, frozen_mismatches),
        ("packet_a_same_task_same_batch_zero", same_batch_counts["A"] == 0, same_batch_counts["A"]),
        ("packet_b_same_task_same_batch_zero", same_batch_counts["B"] == 0, same_batch_counts["B"]),
        ("packet_a_same_task_adjacent_zero", adjacent_counts["A"] == 0, adjacent_counts["A"]),
        ("packet_b_same_task_adjacent_zero", adjacent_counts["B"] == 0, adjacent_counts["B"]),
        (
            "packet_a_minimum_gap_target_met",
            minimum_gaps["A"] >= MINIMUM_SAME_TASK_GAP_TARGET,
            minimum_gaps["A"],
        ),
        (
            "packet_b_minimum_gap_target_met",
            minimum_gaps["B"] >= MINIMUM_SAME_TASK_GAP_TARGET,
            minimum_gaps["B"],
        ),
        ("stage7a_commit_hash_issue_zero", stage7a_issues == 0, stage7a_issues),
        ("frozen_git_ref_issue_zero", ref_issues == 0, ref_issues),
        (
            "deterministic_rebuild_identical",
            deterministic_rebuild_identical,
            deterministic_rebuild_identical,
        ),
        ("api_call_count_zero", True, 0),
        ("llm_call_count_zero", True, 0),
        ("stage7b_rerun_count_zero", True, 0),
    ]
    return [
        {
            "check_name": name,
            "status": "PASS" if passed else "FAIL",
            "details": _display_value(details),
        }
        for name, passed, details in checks
    ]


def _validate_frozen_refs(repo_root: Path) -> list[dict[str, str]]:
    rows = []
    for name, ref, expected in [
        ("stage7a_tag", STAGE7A_TAG, STAGE7A_COMMIT),
        ("stage7b_tag", STAGE7B_TAG, STAGE7B_COMMIT),
        ("stage7c1_tag", STAGE7C1_TAG, STAGE7C1_COMMIT),
        ("stage7c2a_v1_tag", STAGE7C2A_V1_TAG, STAGE7C2A_V1_COMMIT),
    ]:
        actual = subprocess.run(
            ["git", "rev-parse", ref],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        rows.append(
            {
                "reference": name,
                "expected_commit": expected,
                "actual_commit": actual,
                "status": "PASS" if actual == expected else "FAIL",
            }
        )
    return rows


def _stage7a_authoritative_context_freeze_audit(
    repo_root: Path,
    stage7a_dir: Path,
    task_rows: list[dict[str, Any]],
    snapshot_rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    binding = json.loads(
        (stage7a_dir / "stage7_asof_evaluation_binding_manifest.json").read_text(encoding="utf-8")
    )
    contracts = json.loads(
        (stage7a_dir / "stage7_product_task_contracts.json").read_text(encoding="utf-8")
    )
    actual = {
        "commit": subprocess.run(
            ["git", "rev-parse", STAGE7A_TAG],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "main_benchmark_manifest_hash": _main_benchmark_hash(task_rows),
        "asof_evaluation_binding_manifest_hash": stable_hash(
            [
                {
                    "benchmark_task_id": row["benchmark_task_id"],
                    "evaluation_binding_hash": row["evaluation_binding_hash"],
                }
                for row in binding["tasks"]
            ]
        ),
        "preclaim_benchmark_evidence_snapshot_set_hash": stable_hash(
            [
                {
                    "benchmark_task_id": row["benchmark_task_id"],
                    "snapshot_hash": row["snapshot_hash"],
                }
                for row in snapshot_rows
            ]
        ),
        "product_task_contract_hash": stable_hash(contracts["contracts"]),
    }
    expected = {"commit": STAGE7A_COMMIT, **STAGE7A_EXPECTED_HASHES}
    return [
        {
            "check_name": key,
            "expected": expected[key],
            "actual": actual[key],
            "status": "PASS" if actual[key] == expected[key] else "FAIL",
        }
        for key in expected
    ]


def _main_benchmark_hash(rows: list[dict[str, Any]]) -> str:
    return stable_hash(
        [
            {
                "benchmark_task_id": row["benchmark_task_id"],
                "source_task_id": row["source_task_id"],
                "slice_spec": row["slice_spec"],
                "pack_id": row["pack_id"],
                "pack_hash": row["pack_hash"],
                "snapshot_binding": {
                    "valid_time": row["valid_time"],
                    "knowledge_time_local_date": row["knowledge_time_local_date"],
                    "state_version_ids": row["state_version_ids"],
                    "bitemporal_version_ids": row["stage3b_bitemporal_version_ids"],
                },
            }
            for row in rows
        ]
    )


def _validate_frozen_counts(
    tasks: list[dict[str, Any]],
    conditions: list[dict[str, Any]],
    blind_rows: list[dict[str, Any]],
    no_output_rows: list[dict[str, str]],
) -> None:
    condition_methods = Counter(str(row["method_internal"]) for row in conditions)
    if len(tasks) != 48 or len(conditions) != 144 or len(blind_rows) != 141:
        raise ValueError("Frozen Stage7 counts do not match 48/144/141")
    if any(condition_methods[method] != 48 for method in METHODS):
        raise ValueError(f"Frozen condition distribution changed: {condition_methods}")
    task_ids = {row["task_id"] for row in no_output_rows}
    if task_ids != EXPECTED_NO_OUTPUT_TASKS:
        raise ValueError(f"Unexpected no-output tasks: {sorted(task_ids)}")


def _load_tasks(path: Path) -> list[dict[str, Any]]:
    return sorted(json.loads(path.read_text())["tasks"], key=lambda row: row["benchmark_task_id"])


def _cell_scope_map(repo_root: Path) -> dict[str, tuple[float, float]]:
    rows = _read_jsonl(
        repo_root / "artifacts/stage3a_initial_epistemic_state_v1_1/construction_state_cells.jsonl"
    )
    return {
        str(row["cell_id"]): (float(row["spatial_start"]), float(row["spatial_end"]))
        for row in rows
    }


def _task_scope_text(
    cell_id: str,
    snapshot: dict[str, Any],
    cell_scopes: dict[str, tuple[float, float]],
) -> str:
    if cell_id:
        return _cell_scope_text(cell_id, cell_scopes)
    scopes = [
        item.get("spatial_scope", {})
        for item in snapshot.get("preclaim_evidence_items", [])
        if item.get("spatial_scope")
    ]
    ranges = []
    for scope in scopes:
        if "start_chainage" in scope and "end_chainage" in scope:
            ranges.append((float(scope["start_chainage"]), float(scope["end_chainage"])))
        elif scope.get("cell_id") in cell_scopes:
            ranges.append(cell_scopes[str(scope["cell_id"])])
    if not ranges:
        return "本任务未限定单一里程单元；请依据下列每条资料自身的空间范围判断。"
    return (
        f"本任务涉及多个资料范围，最小覆盖 {_format_chainage(min(x[0] for x in ranges))} "
        f"至 {_format_chainage(max(x[1] for x in ranges))}；各资料仍以自身范围为准。"
    )


def _scope_text(scope: Any) -> str:
    if not isinstance(scope, dict):
        return "未提供明确空间范围"
    if "start_chainage" in scope and "end_chainage" in scope:
        start = float(scope["start_chainage"])
        end = float(scope["end_chainage"])
        if start == end:
            return _format_chainage(start) + " 点位"
        return f"{_format_chainage(start)} 至 {_format_chainage(end)}"
    if scope.get("cell_id"):
        return "一个冻结施工空间单元"
    return "未提供明确空间范围"


def _cell_scope_text(cell_id: str, cell_scopes: dict[str, tuple[float, float]]) -> str:
    scope = cell_scopes.get(cell_id)
    if not scope:
        return "冻结施工空间单元（里程边界未载入）"
    return f"{_format_chainage(scope[0])} 至 {_format_chainage(scope[1])}"


def _format_chainage(value: float) -> str:
    km = int(value // 1000)
    offset = value - km * 1000
    decimals = 1 if abs(offset - round(offset)) > 1e-6 else 0
    width = 3 if decimals == 0 else 3 + decimals + 1
    return f"K{km}+{offset:0{width}.{decimals}f}"


def _source_type_label(value: str) -> str:
    return {
        "FACE_SKETCH": "掌子面地质素描",
        "SONIC_FORECAST": "水平声波超前地质预报",
        "TSP_REPORT": "地震波反射法超前地质预报",
    }.get(value, value or "未注明")


def _geology_sort_key(item: dict[str, Any]) -> tuple[str, float, str]:
    scope = item.get("spatial_scope", {})
    start = float(scope.get("start_chainage", -1)) if isinstance(scope, dict) else -1
    return (
        str(item.get("applicability_role", "")),
        start,
        str(item.get("evidence_id", "")),
    )


def _display_value(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def _number(value: Any) -> str:
    if value is None:
        return "不可用"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _term_hits(text: str, terms: tuple[str, ...]) -> list[str]:
    hits = []
    for term in terms:
        if term.isascii():
            pattern = rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])"
            found = re.search(pattern, text, re.IGNORECASE)
        else:
            found = re.search(re.escape(term), text, re.IGNORECASE)
        if found:
            hits.append(term)
    return hits


def _specific_packet_leak(packet: list[dict[str, str]], term: str) -> int:
    lowered = term.lower()
    return sum(lowered in row["engineering_context"].lower() for row in packet)


def _annotator_metadata_row() -> dict[str, str]:
    return {
        "annotator_id": "",
        "discipline_background": "",
        "highest_degree_or_current_status": "",
        "tunnelling_or_tbm_experience": "",
        "geotechnical_experience": "",
        "engineering_data_experience": "",
        "llm_experience": "",
        "evaluation_date": "",
        "conflict_of_interest_note": "",
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _jsonl_by_key(path: Path, key: str) -> dict[str, dict[str, Any]]:
    return {str(row[key]): row for row in _read_jsonl(path)}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _csv_by_key(path: Path, key: str) -> dict[str, dict[str, str]]:
    return {str(row[key]): row for row in _read_csv(path)}


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows and not fields:
        raise ValueError(f"Cannot infer CSV schema for empty output: {path}")
    fieldnames = fields or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_file_hashes(output_dir: Path) -> None:
    rows = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path.name == "file_hashes.sha256":
            continue
        rows.append((_sha256_file(path), path.relative_to(output_dir).as_posix()))
    (output_dir / "file_hashes.sha256").write_text(
        "".join(f"{digest}  {name}\n" for digest, name in rows), encoding="utf-8"
    )


def _write_audit_zip(
    repo_root: Path,
    output_dir: Path,
    packet_a: list[dict[str, str]],
    packet_b: list[dict[str, str]],
) -> Path:
    zip_path = repo_root / "stage7c_human_eval_packet_v1_1_audit.zip"
    source_paths = [
        repo_root / "src/tbm_twin/evaluation/stage7c_human_eval.py",
        repo_root / "scripts/build_stage7c_human_eval_packet.py",
        repo_root / "tests/unit/test_stage7c_human_eval_packet.py",
    ]
    skip_full = {
        "human_eval_packet_A.csv",
        "human_eval_packet_B.csv",
        "human_eval_master_internal.csv",
        *{
            f"human_eval_packet_{packet}_batch_{index:02d}.csv"
            for packet in ("A", "B")
            for index in range(1, 7)
        },
    }
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "INTERNAL_NOTICE.txt",
            "INTERNAL answer keys are audit-only. Do not distribute them to annotators.\n",
        )
        archive.writestr("git_refs.txt", _git_refs(repo_root))
        for path in source_paths:
            archive.write(path, path.relative_to(repo_root).as_posix())
        for path in sorted(output_dir.iterdir()):
            if path.is_file() and path.name not in skip_full:
                archive.write(path, path.relative_to(repo_root).as_posix())
        archive.writestr(
            "audit_samples/human_eval_packet_schema.json",
            json.dumps({"fields": list(PACKET_FIELDS)}, ensure_ascii=False, indent=2) + "\n",
        )
        for name, packet in [("A", packet_a), ("B", packet_b)]:
            archive.writestr(
                f"audit_samples/human_eval_packet_{name}_sample.csv",
                _csv_text(packet[:3], list(PACKET_FIELDS)),
            )
    return zip_path


def _csv_text(rows: list[dict[str, str]], fields: list[str]) -> str:
    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def _git_refs(repo_root: Path) -> str:
    commands = [
        ["git", "branch", "--show-current"],
        ["git", "rev-parse", "HEAD"],
        ["git", "rev-parse", STAGE7A_TAG],
        ["git", "rev-parse", STAGE7B_TAG],
        ["git", "rev-parse", STAGE7C1_TAG],
        ["git", "rev-parse", STAGE7C2A_V1_TAG],
        ["git", "status", "--short"],
    ]
    sections = []
    for command in commands:
        result = subprocess.run(command, cwd=repo_root, check=False, capture_output=True, text=True)
        sections.append(f"$ {' '.join(command)}\n{result.stdout}{result.stderr}")
    return "\n".join(sections)


def _readme() -> str:
    return """# Stage7C.2A v1.1 Human Semantic Evaluation Packet

This artifact prepares two method-label-blinded annotation packets from the
frozen 141 texts. The compact authoritative context comes only from the frozen
pre-Claim exact-as-of snapshots. Frozen output text is never edited.

Each packet is deterministically divided into six batches. The same task never
appears twice in one batch, and repeated task presentations satisfy the frozen
minimum position-gap contract. Files containing `internal` and files reporting
frozen-output cues are audit materials, not annotator answer material.

This builder does not call an LLM, rerun text generation, assign human labels,
calculate method results, reveal the method mapping, or begin adjudication.
"""


def _evaluation_guide() -> str:
    return """# 人工工程语义评价指南（v1.1）

## 1. 任务

你将阅读一份“截至指定知识时刻可获得的工程上下文”和一篇匿名生成文本。
请判断文本的工程语义是否受到上下文支持。不要猜测生成方法，也不要因为文字流畅而忽略证据边界。

本轮不要求人工逐项复核PLC数字，也不要求重新计算任何关注指标。明确数值错误和明确空间错误由确定性自动评价另行处理。

## 2. 基本原则

- 预测不等于已经发生。
- 没有实际观察资料，不得声称“现场已揭露”或“实测发现”。
- 当前未提供信息不等于正常、安全、为零或不存在。
- 机械响应与地质资料可以并列，但没有因果证据时不能互相解释原因。
- 施工响应关注指标、地质证据关注指标和机械—地质联合关注指标都不是风险概率。
- 合理的监测、复核和支护建议本身不是事实幻觉。

## 3. 二元错误字段

E1：文本陈述了上下文没有支持的工程事实。

E5：把预测、预计或超前预报写成当前已发生事实。

E6：没有实际观察资料，却声称现场已揭露、出露、实测或观察到。

E7：使用了在当前知识时刻尚不可获得的后到信息。初始材料无法可靠判断来源时间时填 U。

E8：把前方关注、当日已掘复核或局部背景等不同角色混用。

E9：没有因果证据，却断言机械变化由某种地质条件导致，或反向推出地质原因。

E10：把非概率关注指标解释成风险、灾害或异常发生概率。

E11：把UNKNOWN、UNAVAILABLE或未提供信息写成正常、安全、没有问题或不存在。

E12：存在其他明显越过时间、空间、认识性质、角色或指标可用性的工程主张。

每项只填写：0=未发现，1=明确发现，U=无法可靠判断。不要被迫猜测。

`overall_semantic_error`：至少一项明确工程语义错误时填1；未发现填0；整体无法判断填U。
它不替代后续按错误严重程度计算的正式终点。

## 4. 评分

- factual_support_score：1=大量事实无支持；5=事实支持充分。
- epistemic_correctness_score：1=预测/观察/未知严重混淆；5=认识性质准确。
- engineering_usefulness_score：1=基本无用；5=对工程复核很有帮助。
- clarity_score：1=难理解；5=非常清晰。
- misleading_risk_score：1=几乎无误导风险；5=高度可能误导。此项越低越好。
- annotator_confidence：1=不太确定；2=一般确定；3=非常确定。

发现错误时，请在 `error_quote` 中原样摘录关键文本，并在备注中简述理由。

## 5. 分批完成

正式材料分为6个batch。每完成一个batch就保存文件；开始下一批前可以休息。正式评价期间不要与另一位评价者讨论正式样本。
"""


def _quick_reference() -> str:
    return """# 人工评价快速参考（v1.1）

二元标签：`0` 未发现；`1` 明确发现；`U` 无法可靠判断。

重点检查：无支持事实、预测事实化、无观察依据的“已揭露”、后见信息、角色混用、机械到地质因果、关注指标概率化、UNKNOWN正常化及其他证据边界违规。

记住：预测≠观察；缺失≠正常；关注指标≠概率；并列≠因果；合理建议≠事实幻觉。

不需要人工重算PLC数字。Likert评分均为1–5；只有误导风险是越低越好。置信度为1–3。
"""


def _human_protocol() -> str:
    return """# 人工盲评执行流程（v1.1）

## 评价者资格

主要评价者不应是已经看过内部方法映射、熟悉三类固定输出风格，或直接参与生成逻辑实现并能识别方法身份的开发者。建议评价者具有工程、地质、隧道或工程数据相关背景之一，但不要求理解项目代码。

如评价者具有可能破坏盲法的先验知识，必须在
`annotator_metadata_template.csv` 和 `conflict_of_interest_note` 中如实记录。

本实验采用“方法标签盲化”，不声称完全消除了冻结自然输出中的风格和内部系统线索。

## 执行步骤

1. 两名评价者分别阅读评价指南和快速参考。
2. 两人独立完成12个TRAINING_ONLY校准案例。
3. 只讨论校准案例中的规则理解；不得查看正式样本或方法身份。
4. 评价者A依次填写packet A的6个batch，评价者B依次填写packet B的6个batch。
   两套材料包含相同141项，但采用不同的约束随机顺序。
5. 每完成一个batch就保存文件；下一batch前允许休息，不规定固定休息时长。
6. 正式评价期间两位评价者完全独立，不讨论任何正式项目。
7. 完成后锁定两份原始标签，保留原文件hash。
8. 后续阶段才计算一致性，不在材料准备阶段计算。
9. 后续阶段才处理分歧和后见信息裁决。
10. 所有评分锁定后，最后才使用内部答案表揭盲并比较方法。

三个没有最终文本的系统拦截任务不进入141篇文本质量评价，但必须保留在该方法48个任务的输出可用率和fail-closed分析分母中。
"""
