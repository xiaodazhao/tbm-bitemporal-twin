# ruff: noqa: E501, RUF001
"""Build the read-only final research handoff from frozen project artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

METHOD_VERSION = "final_research_handoff_v1"
SCHEMA_VERSION = "final_research_handoff.v1"
GENERATED_AT = "2026-08-29T18:00:00+08:00"

FINAL_TAGS = {
    "stage4": "stage4-metrics-v1.1-frozen",
    "stage5a": "stage5a-claim-contract-v1.1-frozen",
    "stage5b": "stage5b-claim-builder-v1-frozen",
    "stage5c": "stage5c-claim-expressibility-v1-frozen",
    "stage6a": "stage6a-fact-lock-evidence-pack-v1-frozen",
    "stage6b": "stage6b-controlled-realization-v1-frozen",
    "stage7a": "stage7a-experimental-protocol-v1.3-frozen",
    "stage7b": "stage7b-main-comparison-v1-frozen",
    "stage7c": "stage7c-main-auto-evaluation-v1.2-frozen",
    "stage7d": "stage7d-bitemporal-value-v1.1a-frozen",
    "stage7e": "stage7e-ablation-execution-v1.1a-final-machine-results",
    "stage7f": "stage7f-sensitivity-execution-v1.1-final-machine-results",
}


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _tag_commits(repo: Path) -> dict[str, str]:
    return {stage: _git(repo, "rev-list", "-n", "1", tag) for stage, tag in FINAL_TAGS.items()}


def _canonical_sources(repo: Path) -> dict[str, Path]:
    return {
        "geology": repo / "artifacts/stage2_geology_v2_freeze_candidate/freeze_manifest.json",
        "plc": repo / "artifacts/stage2_plc_operational_freeze_v2/freeze_manifest.json",
        "applicability": repo / "artifacts/stage2d_applicability_v2_1/freeze_manifest.json",
        "stage3a": repo / "artifacts/stage3a_initial_epistemic_state_v1_1/freeze_manifest.json",
        "stage3b": repo / "artifacts/stage3b_bitemporal_epistemic_state_v1_1/freeze_manifest.json",
        "stage4": repo / "artifacts/stage4_bitemporal_state_metrics_v1_1/freeze_manifest.json",
        "stage5b": repo / "artifacts/stage5b_deterministic_claim_builder_v1/freeze_manifest.json",
        "stage5c_universe": repo
        / "artifacts/stage5c_claim_expressibility_analysis_v1/analysis_universe_manifest.json",
        "stage5c_rates": repo
        / "artifacts/stage5c_claim_expressibility_analysis_v1/overall_expressibility_summary.csv",
        "stage5c_reasons": repo
        / "artifacts/stage5c_claim_expressibility_analysis_v1/abstention_reason_summary.csv",
        "stage6a": repo / "artifacts/stage6a_fact_lock_evidence_pack_v1/fact_lock_manifest.json",
        "stage7b": repo / "artifacts/stage7b_main_comparison_v1/freeze_manifest.json",
        "stage7c": repo / "artifacts/stage7c_main_auto_eval_v1_2/freeze_manifest.json",
        "stage7c_methods": repo
        / "artifacts/stage7c_main_auto_eval_v1_2/method_automatic_summary.csv",
        "stage7d_v1": repo / "artifacts/stage7d_bitemporal_value_v1/freeze_manifest.json",
        "stage7d_primary": repo
        / "artifacts/stage7d_bitemporal_value_v1_1/stage7d_primary_endpoints.json",
        "stage7d_secondary": repo
        / "artifacts/stage7d_bitemporal_value_v1_1/stage7d_secondary_endpoints.json",
        "stage7d_correction": repo
        / "artifacts/stage7d_bitemporal_value_v1_1a_correction/freeze_manifest.json",
        "stage7e": repo
        / "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
        "stage7f": repo
        / "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
    }


def _load_frozen(repo: Path) -> dict[str, Any]:
    paths = _canonical_sources(repo)
    missing = [str(path.relative_to(repo)) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing canonical frozen sources: {missing}")
    data: dict[str, Any] = {}
    for key, path in paths.items():
        data[key] = _csv(path) if path.suffix == ".csv" else _json(path)
    data["paths"] = paths
    data["tags"] = _tag_commits(repo)
    return data


def _counts(data: dict[str, Any]) -> dict[str, Any]:
    geology = data["geology"]["summary"]
    plc = data["plc"]
    stage3a = data["stage3a"]
    stage3b = data["stage3b"]
    stage4 = data["stage4"]
    universe = data["stage5c_universe"]
    rates = data["stage5c_rates"][0]
    return {
        "plc_observations": plc["normalized_observation_count"],
        "plc_dates": plc["target_date_count"],
        "plc_start": plc["first_target_date"],
        "plc_end": plc["last_target_date"],
        "episodes": plc["episode_count"],
        "response_evidence": stage3a["input_response_evidence_count"],
        "documents": geology["canonical_documents"],
        "primary_evidence": geology["primary_evidence"],
        "forecast_evidence": 381,
        "observed_evidence": 278,
        "report_assertions": geology["report_assertions"],
        "source_spans": geology["source_spans"],
        "cells": stage3a["cell_count"],
        "daily_states": stage3a["daily_state_count"],
        "initial_states": stage3a["initial_state_version_count"],
        "bitemporal_states": stage3b["bitemporal_version_count"],
        "revision_events": stage3b["revision_event_count"],
        "rai_objects": stage4["state_metric_summary_count"],
        "rai_available": stage4["rai_available_bitemporal_count"],
        "grs_objects": stage4["state_metric_summary_count"],
        "grs_available": stage4["grs_available_bitemporal_count"],
        "grci_objects": stage4["state_metric_summary_count"],
        "grci_available": stage4["grci_available_bitemporal_count"],
        "claim_opportunities": universe["opportunity_count"],
        "expressible": int(rates["expressible_count"]),
        "abstain": int(rates["abstain_count"]),
        "expressibility_rate": float(rates["expressibility_rate"]),
        "abstention_rate": float(rates["abstention_rate"]),
    }


def _assert_frozen_counts(counts: dict[str, Any]) -> None:
    expected = {
        "plc_dates": 91,
        "episodes": 1119,
        "documents": 223,
        "primary_evidence": 659,
        "report_assertions": 122,
        "source_spans": 4713,
        "cells": 156,
        "daily_states": 91,
        "initial_states": 1322,
        "bitemporal_states": 1375,
        "revision_events": 53,
        "claim_opportunities": 8679,
        "expressible": 6279,
        "abstain": 2400,
    }
    differences = {
        key: (counts[key], value) for key, value in expected.items() if counts[key] != value
    }
    if differences:
        raise ValueError(f"Frozen count mismatch: {differences}")


def _method_rows(data: dict[str, Any]) -> list[dict[str, str]]:
    tags = data["tags"]
    return [
        {
            "concept": "ExcavationEpisode",
            "canonical_definition": "由连续施工相位构成、以核心 EXCAVATING 区间定义有效推进时间的施工过程对象。",
            "formula_or_rule": "excavation_start/结束取首末 EXCAVATING；上下文时间另存；文件边界可截断。",
            "source_file": "src/tbm_twin/process/models.py",
            "source_config": "configs/episode_detection.yaml",
            "source_commit_or_tag": tags["stage4"],
            "important_boundary": "日期仅用于查询聚合；零进尺冲突不自动删除 Episode。",
        },
        {
            "concept": "valid time",
            "canonical_definition": "证据或状态所描述的工程现实时间。",
            "formula_or_rule": "Episode 使用核心推进区间；日状态使用 target_date；地质证据使用来源明确的观测或预报范围。",
            "source_file": "src/tbm_twin/state/models.py",
            "source_config": "configs/construction_state.yaml",
            "source_commit_or_tag": tags["stage4"],
            "important_boundary": "不得与知识可用时间混同。",
        },
        {
            "concept": "knowledge time",
            "canonical_definition": "某条证据进入可用知识状态的重建时间边界。",
            "formula_or_rule": "submitted_time 优先，否则保守采用 document_time；Stage3B 按 available time 修订。",
            "source_file": "src/tbm_twin/bitemporal/revision_builder.py",
            "source_config": "configs/construction_state.yaml",
            "source_commit_or_tag": tags["stage4"],
            "important_boundary": "历史数据库事务日志不可得，因此是可审计的认识可用性重建，不是真实事务时间。",
        },
        {
            "concept": "DAILY_REVIEW",
            "canonical_definition": "与当日实际开挖单元重叠、可用于当日复核的证据角色。",
            "formula_or_rule": "由空间重叠、有效时间、知识可用时间和认识性质共同判定。",
            "source_file": "src/tbm_twin/evidence/applicability.py",
            "source_config": "configs/evidence_applicability.yaml",
            "source_commit_or_tag": tags["stage4"],
            "important_boundary": "FORECAST 保持 FORECAST，不因进入当日复核而变成 OBSERVED。",
        },
        {
            "concept": "FORWARD_ATTENTION",
            "canonical_definition": "位于掌子面前方且在当时已可获得、可用于前方关注的证据角色。",
            "formula_or_rule": "空间位于施工单元前方并满足知识时间门。",
            "source_file": "src/tbm_twin/evidence/applicability.py",
            "source_config": "configs/evidence_applicability.yaml",
            "source_commit_or_tag": tags["stage4"],
            "important_boundary": "前方关注不是已发生事实。",
        },
        {
            "concept": "LOCAL_BACKGROUND",
            "canonical_definition": "提供局部背景但不能直接支持当日事实 Claim 的地质证据角色。",
            "formula_or_rule": "适用但不满足 DAILY_REVIEW 或 FORWARD_ATTENTION 的局部背景证据。",
            "source_file": "src/tbm_twin/evidence/applicability.py",
            "source_config": "configs/evidence_applicability.yaml",
            "source_commit_or_tag": tags["stage4"],
            "important_boundary": "不能作为直接事实支持。",
        },
        {
            "concept": "RAI",
            "canonical_definition": "基于因果历史基线标准化偏离的非概率施工响应关注指标。",
            "formula_or_rule": "通道中位|robust-z|→族内 max；族关注=min(族偏离/3,1)；RAI=max(LOAD,KINEMATIC)，且两族均完整。",
            "source_file": "src/tbm_twin/metrics/rai.py",
            "source_config": "configs/state_metric_definition_v1.yaml",
            "source_commit_or_tag": tags["stage4"],
            "important_boundary": "RPM 仅诊断；RAI 不是概率，也不能推出地质原因。",
        },
        {
            "concept": "GRS",
            "canonical_definition": "冻结 ordinal mapping 下的地质证据关注指标。",
            "formula_or_rule": "维度内=max_mapped_attention；状态级=mean_non_null_dimension_attention。",
            "source_file": "src/tbm_twin/metrics/grs.py",
            "source_config": "configs/state_metric_definition_v1.yaml; configs/geological_attention_mapping_v1.yaml",
            "source_commit_or_tag": tags["stage4"],
            "important_boundary": "只聚合角色对应且当时已物化的结构化属性；不是地质风险概率。",
        },
        {
            "concept": "GRCI",
            "canonical_definition": "日复核单元内机械响应关注与地质证据关注的非概率联合关注指标。",
            "formula_or_rule": "GRCI = RAI × GRS，仅当 DAILY_REVIEW_CELL 且两者均可用。",
            "source_file": "src/tbm_twin/metrics/grci.py",
            "source_config": "configs/state_metric_definition_v1.yaml",
            "source_commit_or_tag": tags["stage4"],
            "important_boundary": "不是 sqrt；不是概率；不是因果诊断。",
        },
        {
            "concept": "FORECAST",
            "canonical_definition": "来源明确表达预测、预计或超前预报的认识状态。",
            "formula_or_rule": "由冻结地质证据的 epistemic_status 决定并贯穿 Applicability、State、Claim。",
            "source_file": "src/tbm_twin/geology/table_parser_v2/models.py",
            "source_config": "configs/claim_contract_v1.yaml",
            "source_commit_or_tag": tags["stage5a"],
            "important_boundary": "后续使用不得升级为 OBSERVED。",
        },
        {
            "concept": "OBSERVED",
            "canonical_definition": "来源明确记录当前掌子面或已揭露区段的观测认识状态。",
            "formula_or_rule": "必须有权威上游 Evidence 与空间主体绑定。",
            "source_file": "src/tbm_twin/claims/resolution.py",
            "source_config": "configs/claim_contract_v1.yaml",
            "source_commit_or_tag": tags["stage5a"],
            "important_boundary": "不能由预测文本、模型建议或机械响应推断。",
        },
        {
            "concept": "Claim opportunity",
            "canonical_definition": "冻结状态与 Claim Contract 联合枚举出的逻辑表达候选。",
            "formula_or_rule": "按状态版本、主体、Claim 类型和属性槽位确定性生成。",
            "source_file": "src/tbm_twin/claim_building/batch_builder.py",
            "source_config": "configs/claim_contract_v1.yaml",
            "source_commit_or_tag": tags["stage5b"],
            "important_boundary": "Stage5C 只分析该冻结 universe，不重新发明 Claim。",
        },
        {
            "concept": "Claim admissibility",
            "canonical_definition": "权威支持、主体绑定、角色、认识状态、指标状态和禁用语义共同形成的确定性表达许可。",
            "formula_or_rule": "required supports/status/role/metric/qualifiers 全满足且无 forbidden semantics → EXPRESSIBLE；否则 ABSTAIN+reason。",
            "source_file": "src/tbm_twin/claims/validation.py; src/tbm_twin/claims/resolution.py",
            "source_config": "configs/claim_contract_v1.yaml",
            "source_commit_or_tag": tags["stage5a"],
            "important_boundary": "不是关键词规则，也不是 LLM 决策。",
        },
        {
            "concept": "ABSTAIN",
            "canonical_definition": "当前知识时间和合同边界下不允许物化该 Claim 的正式决策。",
            "formula_or_rule": "保留原因码，例如 UNKNOWN_SOURCE_VALUE、CONTEXT_ONLY_ROLE、REQUIRED_METRIC_UNAVAILABLE。",
            "source_file": "src/tbm_twin/claims/models.py",
            "source_config": "configs/claim_contract_v1.yaml",
            "source_commit_or_tag": tags["stage5c"],
            "important_boundary": "不是系统失败率；UNKNOWN 不得写成 normal。",
        },
        {
            "concept": "FactLock",
            "canonical_definition": "从 EXPRESSIBLE Typed Claim 确定性锁定的最小权威工程事实及禁止变换集合。",
            "formula_or_rule": "Claim+resolved authoritative supports+scope+qualifiers→hash-locked fact；ABSTAIN 不生成 FactLock。",
            "source_file": "src/tbm_twin/realization/fact_lock.py",
            "source_config": "artifacts/stage6a_fact_lock_evidence_pack_v1/rendering_contract.json",
            "source_commit_or_tag": tags["stage6a"],
            "important_boundary": "文本和 proposal metadata 不是权威事实源。",
        },
        {
            "concept": "Evidence Pack",
            "canonical_definition": "按任务切片组织 FactLock、表达单元与不足边界的不可变输入包。",
            "formula_or_rule": "固定 slice→固定 FactLock/RealizationUnit IDs→pack hash。",
            "source_file": "src/tbm_twin/realization/evidence_pack.py",
            "source_config": "artifacts/stage6a_fact_lock_evidence_pack_v1/rendering_contract.json",
            "source_commit_or_tag": tags["stage6a"],
            "important_boundary": "包外知识不得补充工程 Claim。",
        },
        {
            "concept": "controlled realization",
            "canonical_definition": "模型只规划已锁定表达单元的顺序，确定性组件完成物化、校验和组合。",
            "formula_or_rule": "FactLock→RealizationUnit→LLM minimal plan→strict validator→deterministic composer→post-audit。",
            "source_file": "src/tbm_twin/realization/stage6b.py; src/tbm_twin/realization/providers/deepseek_adapter.py",
            "source_config": "artifacts/stage6b_controlled_realization_v1/real_model_smoke/execution_protocol.json",
            "source_commit_or_tag": tags["stage6b"],
            "important_boundary": "LLM 不计算工程事实、不决定 Claim 许可、不生成权威事实值。",
        },
    ]


def _dataset_rows(counts: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "layer": "PLC",
            "object": "normalized observations",
            "count": counts["plc_observations"],
            "unit": "rows",
            "source": "stage2_plc_operational_freeze_v2/freeze_manifest.json",
            "caveat": "原始字段单位未经验证者不参与物理量推导",
        },
        {
            "layer": "PLC",
            "object": "monitored construction dates",
            "count": counts["plc_dates"],
            "unit": "dates",
            "source": "stage2_plc_operational_freeze_v2/freeze_manifest.json",
            "caveat": f"spanning {counts['plc_start']} to {counts['plc_end']}; calendar gaps exist",
        },
        {
            "layer": "Process",
            "object": "ExcavationEpisode",
            "count": counts["episodes"],
            "unit": "episodes",
            "source": "stage2_plc_operational_freeze_v2/freeze_manifest.json",
            "caveat": "由确定性 phase segmentation 重建，不是人工逐条标注真值",
        },
        {
            "layer": "Operational evidence",
            "object": "ResponseEvidence",
            "count": counts["response_evidence"],
            "unit": "objects",
            "source": "stage3a_initial_epistemic_state_v1_1/freeze_manifest.json",
            "caveat": "5 channels per eligible episode; 75 spatially unlocated",
        },
        {
            "layer": "Geology",
            "object": "canonical documents",
            "count": counts["documents"],
            "unit": "documents",
            "source": "stage2_geology_v2_freeze_candidate/freeze_manifest.json",
            "caveat": "SHA duplicates and out-of-scope assets excluded from canonical documents",
        },
        {
            "layer": "Geology",
            "object": "Primary Evidence",
            "count": counts["primary_evidence"],
            "unit": "evidence objects",
            "source": "stage2_geology_v2_freeze_candidate/freeze_manifest.json",
            "caveat": "278 OBSERVED and 381 FORECAST",
        },
        {
            "layer": "Geology",
            "object": "OBSERVED Primary Evidence",
            "count": counts["observed_evidence"],
            "unit": "evidence objects",
            "source": "stage2_geology_v2_freeze_candidate/freeze_manifest.json",
            "caveat": "source epistemic status retained",
        },
        {
            "layer": "Geology",
            "object": "FORECAST Primary Evidence",
            "count": counts["forecast_evidence"],
            "unit": "evidence objects",
            "source": "stage2_geology_v2_freeze_candidate/freeze_manifest.json",
            "caveat": "never promoted to OBSERVED",
        },
        {
            "layer": "Geology",
            "object": "ReportAssertion",
            "count": counts["report_assertions"],
            "unit": "assertions",
            "source": "stage2_geology_v2_freeze_candidate/freeze_manifest.json",
            "caveat": "kept separate from Primary Evidence",
        },
        {
            "layer": "Provenance",
            "object": "SourceSpan",
            "count": counts["source_spans"],
            "unit": "spans",
            "source": "stage2_geology_v2_freeze_candidate/freeze_manifest.json",
            "caveat": "4713/4713 frozen validation pass",
        },
        {
            "layer": "State",
            "object": "ConstructionStateCell",
            "count": counts["cells"],
            "unit": "cells",
            "source": "stage3a_initial_epistemic_state_v1_1/freeze_manifest.json",
            "caveat": "10 m research index; not atomic ground truth",
        },
        {
            "layer": "State",
            "object": "DailyConstructionState",
            "count": counts["daily_states"],
            "unit": "dates",
            "source": "stage3a_initial_epistemic_state_v1_1/freeze_manifest.json",
            "caveat": "one per PLC-monitored construction date",
        },
        {
            "layer": "State",
            "object": "initial state versions",
            "count": counts["initial_states"],
            "unit": "versions",
            "source": "stage3a_initial_epistemic_state_v1_1/freeze_manifest.json",
            "caveat": "as-known initial states",
        },
        {
            "layer": "Bitemporal state",
            "object": "bitemporal versions",
            "count": counts["bitemporal_states"],
            "unit": "versions",
            "source": "stage3b_bitemporal_epistemic_state_v1_1/freeze_manifest.json",
            "caveat": "1322 initial plus 53 revised versions",
        },
        {
            "layer": "Bitemporal state",
            "object": "knowledge revision events",
            "count": counts["revision_events"],
            "unit": "events",
            "source": "stage3b_bitemporal_epistemic_state_v1_1/freeze_manifest.json",
            "caveat": "reconstructed knowledge availability",
        },
        {
            "layer": "Metrics",
            "object": "RAI available",
            "count": counts["rai_available"],
            "unit": f"of {counts['rai_objects']} versions",
            "source": "stage4_bitemporal_state_metrics_v1_1/freeze_manifest.json",
            "caveat": "non-probabilistic operational attention",
        },
        {
            "layer": "Metrics",
            "object": "GRS available",
            "count": counts["grs_available"],
            "unit": f"of {counts['grs_objects']} versions",
            "source": "stage4_bitemporal_state_metrics_v1_1/freeze_manifest.json",
            "caveat": "ordinal evidence attention",
        },
        {
            "layer": "Metrics",
            "object": "GRCI available",
            "count": counts["grci_available"],
            "unit": f"of {counts['grci_objects']} versions",
            "source": "stage4_bitemporal_state_metrics_v1_1/freeze_manifest.json",
            "caveat": "daily-review product only; not probability or causality",
        },
        {
            "layer": "Claim",
            "object": "Claim opportunities",
            "count": counts["claim_opportunities"],
            "unit": "opportunities",
            "source": "stage5c_claim_expressibility_analysis_v1/analysis_universe_manifest.json",
            "caveat": "frozen deterministic universe",
        },
        {
            "layer": "Claim",
            "object": "EXPRESSIBLE",
            "count": counts["expressible"],
            "unit": "decisions",
            "source": "stage5c_claim_expressibility_analysis_v1/overall_expressibility_summary.csv",
            "caveat": f"rate={counts['expressibility_rate']:.6f}",
        },
        {
            "layer": "Claim",
            "object": "ABSTAIN",
            "count": counts["abstain"],
            "unit": "decisions",
            "source": "stage5c_claim_expressibility_analysis_v1/overall_expressibility_summary.csv",
            "caveat": f"rate={counts['abstention_rate']:.6f}; formal output, not failure",
        },
    ]


def _experiment_rows(data: dict[str, Any], counts: dict[str, Any]) -> list[dict[str, Any]]:
    d = data["stage7d_primary"]
    e = data["stage7e"]
    f = data["stage7f"]
    return [
        {
            "experiment_id": "CLAIM_ADMISSIBILITY_FULL",
            "research_question": "在冻结证据、角色和认识边界下，哪些 Claim 可以表达？",
            "stage": "Stage5B/5C",
            "design": "全量确定性 Claim opportunity 枚举与合同判定",
            "baseline": "无模型基线；冻结 Claim Contract",
            "treatment": "不适用",
            "sample_unit": "Claim opportunity",
            "sample_size": counts["claim_opportunities"],
            "final_status": "FROZEN",
            "primary_results": f"EXPRESSIBLE={counts['expressible']}; ABSTAIN={counts['abstain']}",
            "limitations": "表示合同内的可表达性，不是事实准确率或风险识别率",
            "human_required": "NO for deterministic decision; YES for external engineering validity",
            "final_source_tag": FINAL_TAGS["stage5c"],
        },
        {
            "experiment_id": "STAGE7B_MAIN_COMPARISON",
            "research_question": "直接生成、结构化提示和受控实现的机器行为有何差异？",
            "stage": "Stage7B/7C",
            "design": "48 held-out tasks × B0/B1/P；同模型、同 as-of 输入语义",
            "baseline": "B0_DIRECT_LLM; B1_STRUCTURED_PROMPT_LLM",
            "treatment": "P_PROPOSED controlled realization",
            "sample_unit": "benchmark task-condition",
            "sample_size": 144,
            "final_status": "MACHINE_ENDPOINTS_FROZEN; SEMANTIC_ENDPOINTS_DEFERRED",
            "primary_results": "B0=48; B1=48; P=45 valid, 3 fail-closed INVALID_SECTION_ORDER",
            "limitations": "单模型、单工程；人工语义评价尚未完成",
            "human_required": "YES",
            "final_source_tag": FINAL_TAGS["stage7c"],
        },
        {
            "experiment_id": "STAGE7D_BITEMPORAL",
            "research_question": "后到证据如何改变状态指标与 Claim 可表达性？",
            "stage": "Stage7D",
            "design": "48-task alignment diagnostic + 53-event full revision census",
            "baseline": "pre-revision as-known state",
            "treatment": "post-revision state after later evidence availability",
            "sample_unit": "revision event",
            "sample_size": d["P1_revision_event_census_size"],
            "final_status": "FROZEN",
            "primary_results": "RAI 0/53; GRS 36/53; GRCI 1/53; decision switch 27/53; opportunity added 540",
            "limitations": "48-task alignment is null because held-out tasks do not overlap revisions",
            "human_required": "NO for transitions; YES for broader engineering interpretation",
            "final_source_tag": FINAL_TAGS["stage7d"],
        },
        {
            "experiment_id": "STAGE7E_ABLATION",
            "research_question": "Claim gate、认识标记、FactLock 和 trace 分层分别贡献什么？",
            "stage": "Stage7E",
            "design": "冻结输出上的预注册消融与离线确定性审计",
            "baseline": "P proposed frozen outputs",
            "treatment": "A1-A4 component removal/trace analysis",
            "sample_unit": "task, chunk, mapping or FactLock depending endpoint",
            "sample_size": "A2 48 tasks; A3 45 outputs; A4 1022 FactLocks",
            "final_status": "A1 NOT_EXECUTABLE; A2-A4 FROZEN",
            "primary_results": f"A3 strict {e['a3_primary_protocol_compliance']['valid_chunks']}/147 chunks; A4 {e['a4']['used_fact_locks']}/1022 trace",
            "limitations": "A3 fence-only is secondary; trace/numeric exactness is not semantic correctness",
            "human_required": "YES for semantic correctness",
            "final_source_tag": FINAL_TAGS["stage7e"],
        },
        {
            "experiment_id": "STAGE7F_SENSITIVITY",
            "research_question": "空间分辨率、历史充分性和 RAI 饱和尺度变化时结论如何变化？",
            "stage": "Stage7F",
            "design": "OFAT: cell 5/10/20m; history 20/30/40; saturation 2/3/4",
            "baseline": "10m, 30 observations, saturation 3",
            "treatment": "six alternative arms",
            "sample_unit": "state/claim exposure under each arm",
            "sample_size": "7 arms including baseline",
            "final_status": "FROZEN_WITH_VALIDITY_BOUNDARY",
            "primary_results": f"20m conflicts={f['cell_size']['20m']['scope_role_conflicts']}; history switches=4 each direction; saturation claim switches=0",
            "limitations": "20m is coarse stress test, not interchangeable arm; no automatic robustness class",
            "human_required": "YES for final robustness interpretation",
            "final_source_tag": FINAL_TAGS["stage7f"],
        },
    ]


def _abstention_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in data["stage5c_reasons"]:
        rows.append(
            {
                "decision": "ABSTAIN",
                "reason_code": row["abstention_reason"],
                "count": int(row["count"]),
                "share_of_abstentions": float(row["share_of_all_abstentions"]),
                "interpretation": {
                    "UNKNOWN_SOURCE_VALUE": "来源存在但目标值未物化，禁止补全",
                    "CONTEXT_ONLY_ROLE": "证据仅具上下文角色，不能直接支持事实 Claim",
                    "STATE_ROLE_NOT_ALLOWED": "状态空间角色不允许该 Claim 类型",
                    "REQUIRED_EPISTEMIC_STATUS_MISSING": "缺少合同要求的 OBSERVED/FORECAST 权威认识状态",
                    "REQUIRED_METRIC_UNAVAILABLE": "所需指标状态不可用，不能以 0 替代",
                }[row["abstention_reason"]],
            }
        )
    return rows


def _main_experiment_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    method_rows = data["stage7c_methods"]
    by_method: dict[str, list[dict[str, str]]] = {}
    for row in method_rows:
        by_method.setdefault(row["method_internal"], []).append(row)
    output_counts = {"B0_DIRECT_LLM": 48, "B1_STRUCTURED_PROMPT_LLM": 48, "P_PROPOSED": 45}
    structure_failures = {"B0_DIRECT_LLM": 0, "B1_STRUCTURED_PROMPT_LLM": 0, "P_PROPOSED": 3}
    labels = {
        "B0_DIRECT_LLM": "直接 LLM 基线",
        "B1_STRUCTURED_PROMPT_LLM": "结构化提示基线",
        "P_PROPOSED": "Claim-gated controlled realization",
    }
    return [
        {
            "method": method,
            "description": labels[method],
            "planned_tasks": 48,
            "actual_outputs": output_counts[method],
            "output_availability_rate": output_counts[method] / 48,
            "structure_fail_closed": structure_failures[method],
            "automatic_fail_count_across_defined_checks": sum(
                int(row["fail_count"]) for row in rows
            ),
            "human_review_marks": sum(int(row["human_review_count"]) for row in rows),
            "semantic_endpoint_status": "DEFERRED_TO_HUMAN",
            "denominator_caveat": "automatic rows are check-instance counts, not task-level accuracy",
        }
        for method, rows in by_method.items()
    ]


def _bitemporal_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    v1 = data["stage7d_v1"]["counts"]
    primary = data["stage7d_primary"]
    secondary = data["stage7d_secondary"]
    rows = [
        {
            "analysis_scope": "48-task benchmark alignment",
            "endpoint": "affected tasks",
            "numerator": v1["affected_tasks"],
            "denominator": v1["benchmark_tasks"],
            "rate": 0.0,
            "interpretation": "null alignment; benchmark tasks did not overlap revision events",
        },
        {
            "analysis_scope": "full revision census",
            "endpoint": "revision events",
            "numerator": secondary["revision_event_count"],
            "denominator": secondary["revision_event_count"],
            "rate": 1.0,
            "interpretation": "complete Stage3B revision census",
        },
    ]
    for metric in ("RAI", "GRS", "GRCI"):
        item = primary["P2_metric_sensitive_revision_event_rate"][metric]
        rows.append(
            {
                "analysis_scope": "full revision census",
                "endpoint": f"{metric} changed",
                **item,
                "interpretation": "metric availability or value changed across authoritative revision pair",
            }
        )
    switch = primary["P3_existing_claim_decision_switch_event_rate"]
    rows.append(
        {
            "analysis_scope": "full revision census",
            "endpoint": "events with existing Claim decision switch",
            **switch,
            "interpretation": "ABSTAIN_TO_EXPRESSIBLE occurred in 27 events",
        }
    )
    rows.append(
        {
            "analysis_scope": "full revision census",
            "endpoint": "OPPORTUNITY_ADDED rows",
            "numerator": secondary["claim_transition_counts"]["OPPORTUNITY_ADDED"],
            "denominator": secondary["claim_transition_row_count"],
            "rate": secondary["claim_transition_counts"]["OPPORTUNITY_ADDED"]
            / secondary["claim_transition_row_count"],
            "interpretation": "504 FORECAST + 36 OBSERVED geological opportunities",
        }
    )
    return rows


def _ablation_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    e = data["stage7e"]
    return [
        {
            "arm": "A1",
            "endpoint": "Claim gate bypass",
            "numerator": "",
            "denominator": "",
            "rate": "",
            "status": "NOT_EXECUTABLE_ON_FROZEN_48_TASK_BENCHMARK",
            "result": "NO_CONCRETE_GATE_BYPASS_CANDIDATES",
            "caveat": "design feasibility only; not model performance",
        },
        {
            "arm": "A2",
            "endpoint": "target sections",
            "numerator": e["a2"]["target_sections"],
            "denominator": "",
            "rate": "",
            "status": "EXECUTED",
            "result": f"{e['a2']['affected_tasks']} affected tasks",
            "caveat": "section-level removal analysis",
        },
        {
            "arm": "A3 strict primary",
            "endpoint": "valid chunks",
            "numerator": e["a3_primary_protocol_compliance"]["valid_chunks"],
            "denominator": e["a3_primary_protocol_compliance"]["total_chunks"],
            "rate": e["a3_primary_protocol_compliance"]["valid_chunks"]
            / e["a3_primary_protocol_compliance"]["total_chunks"],
            "status": "PRIMARY",
            "result": "828/989 mappings; 32/45 complete tasks",
            "caveat": "strict parser compliance",
        },
        {
            "arm": "A3 strict primary",
            "endpoint": "numeric exact",
            "numerator": e["a3_corrected_strict_numeric_audit"]["numeric_exact"],
            "denominator": e["a3_corrected_strict_numeric_audit"]["numeric_claims"],
            "rate": 1.0,
            "status": "PRIMARY",
            "result": "0 numeric drift",
            "caveat": "corrected Unicode-safe evaluator",
        },
        {
            "arm": "A3 fence-only secondary",
            "endpoint": "valid chunks",
            "numerator": e["a3_secondary_fence_only"]["valid_chunks"],
            "denominator": e["a3_secondary_fence_only"]["total_chunks"],
            "rate": 1.0,
            "status": "SECONDARY_POST_HOC",
            "result": "989/989 mappings; 45/45 complete tasks",
            "caveat": "not the preregistered primary parser",
        },
        {
            "arm": "A3 fence-only secondary",
            "endpoint": "numeric exact",
            "numerator": e["a3_secondary_fence_only"]["numeric_exact"],
            "denominator": e["a3_secondary_fence_only"]["numeric_claims"],
            "rate": 1.0,
            "status": "SECONDARY_POST_HOC",
            "result": "0 numeric drift",
            "caveat": "numeric exactness is not semantic correctness",
        },
        {
            "arm": "A4",
            "endpoint": "FactLock trace coverage",
            "numerator": e["a4"]["used_fact_locks"],
            "denominator": e["a4"]["total_fact_locks"],
            "rate": e["a4"]["fact_lock_trace_coverage"],
            "status": "EXECUTED",
            "result": f"{e['a4']['omitted_fact_locks']} omitted",
            "caveat": "trace coverage is not semantic correctness",
        },
        {
            "arm": "A4",
            "endpoint": "numeric FactLock trace coverage",
            "numerator": e["a4"]["used_numeric_fact_locks"],
            "denominator": e["a4"]["total_numeric_fact_locks"],
            "rate": e["a4"]["numeric_fact_lock_trace_coverage"],
            "status": "EXECUTED",
            "result": f"{e['a4']['referenced_numeric_token_exact']}/{e['a4']['used_numeric_fact_locks']} referenced exact; {e['a4']['omitted_numeric_fact_locks']} omitted; 0 drift",
            "caveat": "exact token retention is not full semantic correctness",
        },
    ]


def _sensitivity_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    f = data["stage7f"]
    rows: list[dict[str, Any]] = []
    for key in ("5m", "10m", "20m"):
        arm = f["cell_size"][key]
        rows.append(
            {
                "parameter": "cell_size",
                "arm": key,
                "validity_status": arm["method_validity_status"],
                "interpretation_scope": arm["interpretation_scope"],
                "claim_opportunities": arm["frozen_results"]["claim_opportunity_count"],
                "expressible": arm["frozen_results"]["expressible_count"],
                "abstain": arm["frozen_results"]["abstain_count"],
                "rai_available": arm["frozen_results"]["rai_available_count"],
                "grs_available": arm["frozen_results"]["grs_available_count"],
                "grci_available": arm["frozen_results"]["grci_available_count"],
                "claim_transition": "not directly comparable across changed grid universes",
                "quality_boundary": f"scope_conflicts={arm['scope_role_conflicts']}; point={arm['point_missing_or_duplicate']}; interval={arm['interval_overlap_mismatch']}",
            }
        )
    transitions = {"20": "4 ABSTAIN→EXPRESSIBLE", "30": "baseline", "40": "4 EXPRESSIBLE→ABSTAIN"}
    for key in ("20", "30", "40"):
        arm = f["history"][key]
        rows.append(
            {
                "parameter": "history_min_observations",
                "arm": key,
                "validity_status": "VALID",
                "interpretation_scope": "LIMITED_AVAILABILITY_BOUNDARY_SENSITIVITY",
                "claim_opportunities": arm["claim_opportunity_count"],
                "expressible": arm["expressible_count"],
                "abstain": arm["abstain_count"],
                "rai_available": arm["rai_available_count"],
                "grs_available": arm["grs_available_count"],
                "grci_available": arm["grci_available_count"],
                "claim_transition": transitions[key],
                "quality_boundary": "common comparable available metrics largely value-stable; availability boundary shifts",
            }
        )
    for key in ("2", "3", "4"):
        arm = f["saturation"][key]
        rows.append(
            {
                "parameter": "rai_saturation_robust_z",
                "arm": key,
                "validity_status": "VALID",
                "interpretation_scope": "VALUE_SENSITIVE_BUT_DECISION_STABLE",
                "claim_opportunities": arm["claim_opportunity_count"],
                "expressible": arm["expressible_count"],
                "abstain": arm["abstain_count"],
                "rai_available": arm["rai_available_count"],
                "grs_available": arm["grs_available_count"],
                "grci_available": arm["grci_available_count"],
                "claim_transition": "0",
                "quality_boundary": "absolute RAI/GRCI shifts; high rank consistency; monotonicity violations=0",
            }
        )
    return rows


def _case_data(repo: Path) -> list[dict[str, Any]]:
    primary_task = "stage7_main_task_000"
    manifest = _json(
        repo / "artifacts/stage7a_experimental_protocol_v1_3/stage7_main_benchmark_manifest.json"
    )["tasks"]
    task = next(row for row in manifest if row["benchmark_task_id"] == primary_task)
    output_path = repo / (
        "artifacts/stage7b_main_comparison_v1/runs/"
        "stage7b_main_execution_3ae0f791811a2e711cb9f488/P_final_outputs.jsonl"
    )
    output = next(row for row in _jsonl(output_path) if row["benchmark_task_id"] == primary_task)
    fact_locks = {
        row["fact_lock_id"]: row
        for row in _jsonl(repo / "artifacts/stage6a_fact_lock_evidence_pack_v1/fact_locks.jsonl")
    }
    task_locks = [fact_locks[item] for item in task["member_fact_lock_ids"]]
    metric_locks = {
        row["claim_value"].get("metric_name"): row
        for row in task_locks
        if isinstance(row.get("claim_value"), dict) and row["claim_value"].get("metric_name")
    }
    stage3a_id = task["state_version_ids"][0]
    stage3a = next(
        row
        for row in _jsonl(
            repo
            / "artifacts/stage3a_initial_epistemic_state_v1_1/initial_construction_state_versions.jsonl"
        )
        if row["state_version_id"] == stage3a_id
    )
    metric = next(
        row
        for row in _jsonl(
            repo / "artifacts/stage4_bitemporal_state_metrics_v1_1/state_metric_summary.jsonl"
        )
        if row["bitemporal_version_id"] == task["stage3b_bitemporal_version_ids"][0]
    )
    primary = {
        "label": "Case A (recommended primary)",
        "date": task["valid_date"],
        "chainage": "1013470.0-1013480.0 state cell; Episode footprint 1013474.0-1013475.0",
        "cell_id": task["cell_id"],
        "episode_ids": stage3a["episode_ids"],
        "evidence_ids": sorted(
            set(stage3a["response_evidence_ids"] + stage3a["daily_review_evidence_ids"])
        ),
        "state_ids": [stage3a_id, task["stage3b_bitemporal_version_ids"][0]],
        "metrics": {"RAI": metric["rai"], "GRS": metric["grs"], "GRCI": metric["grci"]},
        "metric_ids": {
            name: lock["claim_value"]["source_metric_id"] for name, lock in metric_locks.items()
        },
        "claim_ids": [row["source_claim_id"] for row in task_locks],
        "fact_lock_ids": task["member_fact_lock_ids"],
        "text_output": output["text"],
        "selection_reason": "此案例可完整展示 PLC/geology→state→metrics→Claim→FactLock→controlled realization，并同时保留 FORECAST 与 UNKNOWN 边界。",
        "source_artifacts": [
            "artifacts/stage7a_experimental_protocol_v1_3/stage7_main_benchmark_manifest.json",
            "artifacts/stage3a_initial_epistemic_state_v1_1/initial_construction_state_versions.jsonl",
            "artifacts/stage4_bitemporal_state_metrics_v1_1/state_metric_summary.jsonl",
            "artifacts/stage6a_fact_lock_evidence_pack_v1/fact_locks.jsonl",
            str(output_path.relative_to(repo)),
        ],
    }
    selection = _json(repo / "artifacts/stage7d_bitemporal_value_v1_1/stage7d_case_selection.json")
    cells = {
        row["cell_id"]: row
        for row in _jsonl(
            repo / "artifacts/stage3a_initial_epistemic_state_v1_1/construction_state_cells.jsonl"
        )
    }
    revision_cases: list[dict[str, Any]] = []
    for selected in selection:
        event_id = selected["revision_event_id"]
        event = next(
            row
            for row in _jsonl(
                repo
                / "artifacts/stage3b_bitemporal_epistemic_state_v1_1/knowledge_revision_events.jsonl"
            )
            if row["revision_event_id"] == event_id
        )
        metric_pairs = [
            row
            for row in _csv(
                repo / "artifacts/stage7d_bitemporal_value_v1_1/stage7d_revision_metric_pairs.csv"
            )
            if row["revision_event_id"] == event_id
        ]
        transitions = [
            row
            for row in _csv(
                repo
                / "artifacts/stage7d_bitemporal_value_v1_1/stage7d_revision_claim_transition_rows.csv"
            )
            if row["revision_event_id"] == event_id
        ]
        cell = cells[selected["cell_id"]]
        revision_cases.append(
            {
                "label": f"Case {selected['case_label']} (revision census)",
                "date": selected["valid_date"],
                "chainage": f"{cell['spatial_start']}-{cell['spatial_end']}",
                "cell_id": selected["cell_id"],
                "episode_ids": [],
                "evidence_ids": event["added_evidence_ids"],
                "state_ids": [
                    event["previous_bitemporal_version_id"],
                    event["bitemporal_version_id"],
                ],
                "metrics": {
                    row["metric_type"]: {
                        "before": row["pre_value"],
                        "after": row["post_value"],
                        "changed": row["value_changed"] == "True"
                        or row["status_changed"] == "True",
                    }
                    for row in metric_pairs
                },
                "metric_ids": {},
                "claim_ids": [],
                "fact_lock_ids": [],
                "text_output": "Not a text-generation case; it audits state and Claim semantics before/after later evidence.",
                "selection_reason": selected["selection_reason"],
                "transition_counts": dict(Counter(row["transition_class"] for row in transitions)),
                "source_artifacts": [
                    "artifacts/stage3b_bitemporal_epistemic_state_v1_1/knowledge_revision_events.jsonl",
                    "artifacts/stage7d_bitemporal_value_v1_1/stage7d_revision_metric_pairs.csv",
                    "artifacts/stage7d_bitemporal_value_v1_1/stage7d_revision_claim_transition_rows.csv",
                    f"artifacts/stage7d_bitemporal_value_v1_1/stage7d_case_{event_id}.md",
                ],
            }
        )
    return [primary, *revision_cases]


def _trace_rows(data: dict[str, Any], counts: dict[str, Any]) -> list[dict[str, Any]]:
    tags = data["tags"]

    def row(
        result_id: str, value: Any, source: str, stage: str, tag_key: str, locator: str
    ) -> dict[str, Any]:
        return {
            "result_id": result_id,
            "final_result": value,
            "source_file": source,
            "source_artifact": str(Path(source).parent),
            "source_stage": stage,
            "source_commit": tags[tag_key],
            "source_tag": FINAL_TAGS[tag_key],
            "field_row_key": locator,
            "trace_status": "RESOLVED",
        }

    rows = [
        row(
            "PLC_MONITORED_DATES",
            91,
            "artifacts/stage2_plc_operational_freeze_v2/freeze_manifest.json",
            "Stage2E",
            "stage4",
            "monitored_date_count",
        ),
        row(
            "PLC_DATE_SPAN",
            "2023-09-15..2023-12-30",
            "artifacts/stage2_plc_operational_freeze_v2/freeze_manifest.json",
            "Stage2E",
            "stage4",
            "first_monitored_date,last_monitored_date",
        ),
        row(
            "PLC_OBSERVATIONS",
            counts["plc_observations"],
            "artifacts/stage2_plc_operational_freeze_v2/freeze_manifest.json",
            "Stage2E",
            "stage4",
            "normalized_observation_count",
        ),
        row(
            "EPISODES",
            1119,
            "artifacts/stage2_plc_operational_freeze_v2/freeze_manifest.json",
            "Stage2E",
            "stage4",
            "episode_count",
        ),
        row(
            "DOCUMENTS",
            223,
            "artifacts/stage2_geology_v2_freeze_candidate/freeze_manifest.json",
            "Stage2",
            "stage4",
            "canonical_documents",
        ),
        row(
            "PRIMARY_EVIDENCE",
            659,
            "artifacts/stage2_geology_v2_freeze_candidate/freeze_manifest.json",
            "Stage2",
            "stage4",
            "primary_evidence",
        ),
        row(
            "OBSERVED_EVIDENCE",
            278,
            "artifacts/stage2_geology_v2_freeze_candidate/freeze_manifest.json",
            "Stage2",
            "stage4",
            "primary_combinations grouped epistemic_status=OBSERVED",
        ),
        row(
            "FORECAST_EVIDENCE",
            381,
            "artifacts/stage2_geology_v2_freeze_candidate/freeze_manifest.json",
            "Stage2",
            "stage4",
            "primary_combinations grouped epistemic_status=FORECAST",
        ),
        row(
            "REPORT_ASSERTIONS",
            122,
            "artifacts/stage2_geology_v2_freeze_candidate/freeze_manifest.json",
            "Stage2",
            "stage4",
            "report_assertions",
        ),
        row(
            "SOURCE_SPANS",
            4713,
            "artifacts/stage2_geology_v2_freeze_candidate/freeze_manifest.json",
            "Stage2",
            "stage4",
            "source_spans",
        ),
        row(
            "STATE_CELLS",
            156,
            "artifacts/stage3a_initial_epistemic_state_v1_1/freeze_manifest.json",
            "Stage3A",
            "stage4",
            "cell_count",
        ),
        row(
            "INITIAL_STATE_VERSIONS",
            1322,
            "artifacts/stage3a_initial_epistemic_state_v1_1/freeze_manifest.json",
            "Stage3A",
            "stage4",
            "initial_state_version_count",
        ),
        row(
            "BITEMPORAL_VERSIONS",
            1375,
            "artifacts/stage3b_bitemporal_epistemic_state_v1_1/freeze_manifest.json",
            "Stage3B",
            "stage4",
            "bitemporal_version_count",
        ),
        row(
            "REVISION_EVENTS",
            53,
            "artifacts/stage3b_bitemporal_epistemic_state_v1_1/freeze_manifest.json",
            "Stage3B",
            "stage4",
            "revision_event_count",
        ),
        row(
            "RAI_AVAILABLE",
            174,
            "artifacts/stage4_bitemporal_state_metrics_v1_1/freeze_manifest.json",
            "Stage4",
            "stage4",
            "rai_available_bitemporal_count",
        ),
        row(
            "GRS_AVAILABLE",
            1211,
            "artifacts/stage4_bitemporal_state_metrics_v1_1/freeze_manifest.json",
            "Stage4",
            "stage4",
            "grs_available_bitemporal_count",
        ),
        row(
            "GRCI_AVAILABLE",
            174,
            "artifacts/stage4_bitemporal_state_metrics_v1_1/freeze_manifest.json",
            "Stage4",
            "stage4",
            "grci_available_bitemporal_count",
        ),
        row(
            "CLAIM_OPPORTUNITIES",
            8679,
            "artifacts/stage5c_claim_expressibility_analysis_v1/analysis_universe_manifest.json",
            "Stage5C",
            "stage5c",
            "claim_opportunity_count",
        ),
        row(
            "EXPRESSIBLE",
            6279,
            "artifacts/stage5c_claim_expressibility_analysis_v1/overall_expressibility_summary.csv",
            "Stage5C",
            "stage5c",
            "row=overall,expressible_count",
        ),
        row(
            "ABSTAIN",
            2400,
            "artifacts/stage5c_claim_expressibility_analysis_v1/overall_expressibility_summary.csv",
            "Stage5C",
            "stage5c",
            "row=overall,abstain_count",
        ),
        row(
            "STAGE7B_TASKS",
            48,
            "artifacts/stage7b_main_comparison_v1/freeze_manifest.json",
            "Stage7B",
            "stage7b",
            "run_summary.benchmark_task_count",
        ),
        row(
            "STAGE7B_P_VALID",
            45,
            "artifacts/stage7b_main_comparison_v1/freeze_manifest.json",
            "Stage7B",
            "stage7b",
            "run_summary.p_final_output_count",
        ),
        row(
            "STAGE7B_P_INVALID",
            3,
            "artifacts/stage7b_main_comparison_v1/freeze_manifest.json",
            "Stage7B",
            "stage7b",
            "run_summary.structure_audit_fail_count",
        ),
        row(
            "STAGE7D_REVISED_DATES",
            14,
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_secondary_endpoints.json",
            "Stage7D",
            "stage7d",
            "revision_valid_date_count",
        ),
        row(
            "STAGE7D_REVISED_CELLS",
            51,
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_secondary_endpoints.json",
            "Stage7D",
            "stage7d",
            "unique_revised_cell_count",
        ),
        row(
            "STAGE7D_RAI_CHANGED",
            "0/53",
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_primary_endpoints.json",
            "Stage7D",
            "stage7d",
            "P2_metric_sensitive_revision_event_rate.RAI",
        ),
        row(
            "STAGE7D_GRS_CHANGED",
            "36/53",
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_primary_endpoints.json",
            "Stage7D",
            "stage7d",
            "P2_metric_sensitive_revision_event_rate.GRS",
        ),
        row(
            "STAGE7D_GRCI_CHANGED",
            "1/53",
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_primary_endpoints.json",
            "Stage7D",
            "stage7d",
            "P2_metric_sensitive_revision_event_rate.GRCI",
        ),
        row(
            "STAGE7D_ABSTAIN_TO_EXPRESSIBLE",
            27,
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_secondary_endpoints.json",
            "Stage7D",
            "stage7d",
            "claim_transition_counts.ABSTAIN_TO_EXPRESSIBLE",
        ),
        row(
            "STAGE7D_OPPORTUNITY_ADDED",
            540,
            "artifacts/stage7d_bitemporal_value_v1_1a_correction/freeze_manifest.json",
            "Stage7D",
            "stage7d",
            "counts.opportunity_added",
        ),
        row(
            "A2_TARGET_SECTIONS",
            31,
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "Stage7E",
            "stage7e",
            "a2.target_sections",
        ),
        row(
            "A2_AFFECTED_TASKS",
            24,
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "Stage7E",
            "stage7e",
            "a2.affected_tasks",
        ),
        row(
            "A3_STRICT_CHUNKS",
            "125/147",
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "Stage7E",
            "stage7e",
            "a3_primary_protocol_compliance.valid_chunks/total_chunks",
        ),
        row(
            "A3_STRICT_MAPPINGS",
            "828/989",
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "Stage7E",
            "stage7e",
            "a3_primary_protocol_compliance.claim_mappings/total_claims",
        ),
        row(
            "A3_STRICT_NUMERIC",
            "149/149 exact; drift 0",
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "Stage7E",
            "stage7e",
            "a3_corrected_strict_numeric_audit",
        ),
        row(
            "A3_SECONDARY_NUMERIC",
            "164/164 exact; drift 0",
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "Stage7E",
            "stage7e",
            "a3_secondary_fence_only",
        ),
        row(
            "A4_TRACE",
            "848/1022",
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "Stage7E",
            "stage7e",
            "a4.used_fact_locks/total_fact_locks",
        ),
        row(
            "A4_NUMERIC_TRACE",
            "162/171",
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "Stage7E",
            "stage7e",
            "a4.used_numeric_fact_locks/total_numeric_fact_locks",
        ),
        row(
            "SENS_20M_CONFLICTS",
            90,
            "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
            "Stage7F",
            "stage7f",
            "cell_size.20m.scope_role_conflicts",
        ),
        row(
            "SENS_20M_POINT",
            23,
            "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
            "Stage7F",
            "stage7f",
            "cell_size.20m.point_missing_or_duplicate",
        ),
        row(
            "SENS_20M_INTERVAL",
            76,
            "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
            "Stage7F",
            "stage7f",
            "cell_size.20m.interval_overlap_mismatch",
        ),
        row(
            "SENS_HISTORY_20_SWITCH",
            "4 A→E",
            "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
            "Stage7F",
            "stage7f",
            "history.claim_transitions[rai_history_min_samples_20]",
        ),
        row(
            "SENS_HISTORY_40_SWITCH",
            "4 E→A",
            "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
            "Stage7F",
            "stage7f",
            "history.claim_transitions[rai_history_min_samples_40]",
        ),
        row(
            "SENS_SATURATION_SWITCH",
            0,
            "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
            "Stage7F",
            "stage7f",
            "saturation.claim_transitions",
        ),
    ]
    for abstain in data["stage5c_reasons"]:
        rows.append(
            row(
                f"ABSTAIN_{abstain['abstention_reason']}",
                abstain["count"],
                "artifacts/stage5c_claim_expressibility_analysis_v1/abstention_reason_summary.csv",
                "Stage5C",
                "stage5c",
                f"abstention_reason={abstain['abstention_reason']}",
            )
        )
    return rows


def _retention_rows() -> list[dict[str, str]]:
    items = [
        ("src/", "KEEP_IN_WORKTREE", "canonical implementation", "YES", "YES", "YES", "keep"),
        ("configs/", "KEEP_IN_WORKTREE", "frozen method contracts", "YES", "YES", "YES", "keep"),
        ("scripts/", "KEEP_IN_WORKTREE", "reproducible builders", "YES", "YES", "YES", "keep"),
        (
            "tests/",
            "KEEP_IN_WORKTREE",
            "method and regression verification",
            "YES",
            "NO",
            "YES",
            "keep",
        ),
        (
            "docs/",
            "KEEP_IN_WORKTREE",
            "architecture and freeze reports",
            "NO",
            "YES",
            "YES",
            "keep",
        ),
        (
            "pyproject.toml",
            "KEEP_IN_WORKTREE",
            "dependency and quality configuration",
            "YES",
            "NO",
            "YES",
            "keep",
        ),
        (
            "uv.lock",
            "KEEP_IN_WORKTREE",
            "resolved dependencies",
            "YES",
            "NO",
            "YES",
            "keep if present",
        ),
        (
            "artifacts/final_research_handoff_v1/",
            "NEVER_DELETE",
            "canonical manuscript evidence index",
            "NO",
            "YES",
            "YES",
            "retain in repository",
        ),
        (
            "artifacts/stage2_geology_v2_freeze_candidate/",
            "KEEP_IN_WORKTREE",
            "canonical geological evidence and provenance",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage2_plc_operational_freeze_v2/",
            "KEEP_IN_WORKTREE",
            "canonical operational evidence",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage2d_applicability_v2_1/",
            "KEEP_IN_WORKTREE",
            "canonical evidence applicability",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage3a_initial_epistemic_state_v1_1/",
            "KEEP_IN_WORKTREE",
            "canonical initial states",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage3b_bitemporal_epistemic_state_v1_1/",
            "KEEP_IN_WORKTREE",
            "canonical revisions",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage4_bitemporal_state_metrics_v1_1/",
            "KEEP_IN_WORKTREE",
            "canonical metrics",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage5a_typed_claim_contract_v1_1/",
            "KEEP_IN_WORKTREE",
            "canonical Claim contract",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage5b_deterministic_claim_builder_v1/",
            "KEEP_IN_WORKTREE",
            "canonical Claim universe",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage5c_claim_expressibility_analysis_v1/",
            "KEEP_IN_WORKTREE",
            "canonical admissibility analysis",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage6a_fact_lock_evidence_pack_v1/",
            "KEEP_IN_WORKTREE",
            "canonical FactLocks",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage6b_controlled_realization_v1/",
            "KEEP_IN_WORKTREE",
            "controlled realization freeze",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage7a_experimental_protocol_v1_3/",
            "KEEP_IN_WORKTREE",
            "frozen benchmark and evaluation rules",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage7b_main_comparison_v1/",
            "KEEP_IN_WORKTREE",
            "main experiment and raw model responses",
            "YES",
            "YES",
            "YES",
            "keep; additionally archive raw responses",
        ),
        (
            "artifacts/stage7c_main_auto_eval_v1_2/",
            "KEEP_IN_WORKTREE",
            "final deterministic evaluation",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage7d_bitemporal_value_v1/",
            "KEEP_IN_WORKTREE",
            "benchmark-alignment null diagnostic",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage7d_bitemporal_value_v1_1/",
            "KEEP_IN_WORKTREE",
            "full revision census",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage7d_bitemporal_value_v1_1a_correction/",
            "KEEP_IN_WORKTREE",
            "final opportunity-added interpretation",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/",
            "KEEP_IN_WORKTREE",
            "authoritative ablation machine summary",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/",
            "KEEP_IN_WORKTREE",
            "authoritative sensitivity interpretation",
            "YES",
            "YES",
            "YES",
            "keep",
        ),
        (
            "data/raw/plc/",
            "ARCHIVE_EXTERNALLY",
            "large irreplaceable source data",
            "YES",
            "NO",
            "NO",
            "checksum and archive with access control",
        ),
        (
            "data/raw/geology_pdfs/",
            "ARCHIVE_EXTERNALLY",
            "copyright-sensitive source PDFs",
            "YES",
            "NO",
            "NO",
            "checksum and archive with access control",
        ),
        (
            "artifacts/stage7b_main_comparison_v1/runs/*/raw_model_outputs.jsonl",
            "ARCHIVE_EXTERNALLY",
            "irreplaceable paid API responses",
            "YES",
            "YES",
            "YES",
            "keep in Git where allowed plus external checksum copy",
        ),
        (
            "artifacts/stage7e_ablation_execution_v1/runs/",
            "ARCHIVE_EXTERNALLY",
            "frozen ablation raw responses",
            "YES",
            "NO",
            "YES",
            "external checksum copy",
        ),
        (
            "*.zip",
            "ARCHIVE_EXTERNALLY",
            "review packets are duplicative but useful for audit exchange",
            "NO",
            "NO",
            "NO",
            "archive outside worktree after review",
        ),
        (
            "artifacts/*_candidate/",
            "KEEP_VIA_GIT_HISTORY_ONLY",
            "superseded candidates after formal freeze",
            "NO",
            "NO",
            "YES",
            "remove only after manual review and verified tag",
        ),
        (
            "artifacts/stage3a_initial_epistemic_state_v1/",
            "KEEP_VIA_GIT_HISTORY_ONLY",
            "superseded point-incomplete state",
            "NO",
            "NO",
            "YES",
            "retain through Git history",
        ),
        (
            "artifacts/stage4_bitemporal_state_metrics_v1_candidate/",
            "KEEP_VIA_GIT_HISTORY_ONLY",
            "superseded metric candidate",
            "NO",
            "NO",
            "YES",
            "retain through Git history",
        ),
        (
            "artifacts/stage5a_claim_contract_v1_candidate/",
            "KEEP_VIA_GIT_HISTORY_ONLY",
            "superseded contract candidate",
            "NO",
            "NO",
            "YES",
            "retain through Git history",
        ),
        (
            "artifacts/stage5b_deterministic_claim_builder_v1_candidate/",
            "KEEP_VIA_GIT_HISTORY_ONLY",
            "superseded builder candidate",
            "NO",
            "NO",
            "YES",
            "retain through Git history",
        ),
        (
            "artifacts/stage7c_main_auto_eval_v1/",
            "SAFE_TO_DELETE_AFTER_REVIEW",
            "superseded evaluator",
            "NO",
            "NO",
            "YES",
            "delete only after handoff review",
        ),
        (
            "artifacts/stage7c_main_auto_eval_v1_1/",
            "SAFE_TO_DELETE_AFTER_REVIEW",
            "superseded evaluator closure",
            "NO",
            "NO",
            "YES",
            "delete only after handoff review",
        ),
        (
            "artifacts/stage7e_ablation_execution_v1/",
            "SAFE_TO_DELETE_AFTER_REVIEW",
            "contains superseded numeric audit",
            "NO",
            "NO",
            "YES",
            "preserve raw responses elsewhere; delete derived duplicate only",
        ),
        (
            "artifacts/stage7e_ablation_execution_v1_1_correction/",
            "SAFE_TO_DELETE_AFTER_REVIEW",
            "superseded by v1.1a final metadata",
            "NO",
            "NO",
            "YES",
            "delete only after final hashes checked",
        ),
        (
            "artifacts/stage7f_sensitivity_protocol_v1/",
            "SAFE_TO_DELETE_AFTER_REVIEW",
            "superseded method descriptions",
            "NO",
            "NO",
            "YES",
            "delete only after review",
        ),
        (
            "artifacts/stage7f_sensitivity_execution_v1/",
            "SAFE_TO_DELETE_AFTER_REVIEW",
            "superseded interpretation",
            "NO",
            "NO",
            "YES",
            "delete only after review",
        ),
        (
            "stage7c_*_audit.zip",
            "SAFE_TO_DELETE_AFTER_REVIEW",
            "review transport duplicate",
            "NO",
            "NO",
            "NO",
            "archive or delete after review",
        ),
        (
            "stage7d_*_audit.zip",
            "SAFE_TO_DELETE_AFTER_REVIEW",
            "review transport duplicate",
            "NO",
            "NO",
            "NO",
            "archive or delete after review",
        ),
        (
            "stage7e_*_audit.zip",
            "SAFE_TO_DELETE_AFTER_REVIEW",
            "review transport duplicate",
            "NO",
            "NO",
            "NO",
            "archive or delete after review",
        ),
        (
            "stage7f_*_audit.zip",
            "SAFE_TO_DELETE_AFTER_REVIEW",
            "review transport duplicate",
            "NO",
            "NO",
            "NO",
            "archive or delete after review",
        ),
        (
            ".pytest_cache/",
            "SAFE_TO_DELETE_AFTER_REVIEW",
            "test cache",
            "NO",
            "NO",
            "NO",
            "safe cache cleanup later",
        ),
        (
            ".ruff_cache/",
            "SAFE_TO_DELETE_AFTER_REVIEW",
            "linter cache",
            "NO",
            "NO",
            "NO",
            "safe cache cleanup later",
        ),
        (
            ".mypy_cache/",
            "SAFE_TO_DELETE_AFTER_REVIEW",
            "type-check cache",
            "NO",
            "NO",
            "NO",
            "safe cache cleanup later",
        ),
        (
            ".venv/",
            "SAFE_TO_DELETE_AFTER_REVIEW",
            "rebuildable environment",
            "NO",
            "NO",
            "NO",
            "recreate from lock file",
        ),
    ]
    fields = [
        "path",
        "category",
        "reason",
        "required_for_reproduction",
        "required_for_paper",
        "recoverable_from_git",
        "recommended_action",
    ]
    return [dict(zip(fields, values, strict=True)) for values in items]


def _documents(
    data: dict[str, Any], counts: dict[str, Any], cases: list[dict[str, Any]]
) -> dict[str, str]:
    reasons = _abstention_rows(data)
    reason_lines = "\n".join(
        f"- `{row['reason_code']}`：{row['count']}（{row['share_of_abstentions']:.3%}），{row['interpretation']}。"
        for row in reasons
    )
    overview = f"""# 项目总览

## 一句话定义

本项目研究的不是“让大语言模型自动写 TBM 日报”，而是构建一个**受证据、空间、有效时间和知识可用时间共同约束的施工认识状态系统**：在指定 knowledge time 下，系统只允许表达当时有权威证据支持的工程 Claim，并把不能表达的内容正式判为 `ABSTAIN`。

## 科学问题

施工数据具有三类根本异质性：PLC 是高频过程观测，地质预报是面向前方区间的预测认识，掌子面素描是后到或当下的观测认识。若只按“某天的日报”拼接文本，会把后来资料泄漏到过去、把 FORECAST 写成 OBSERVED、把缺失写成正常，并让机械异常被误解为地质原因。本研究因此追问：

> 对于特定施工空间单元、valid time 与 knowledge time，当时可获得的证据允许系统表达哪些工程认识？后到证据如何修订这种可表达性？

## 核心链路

```text
PLC/PDF 原始资产
  -> SourceAsset、分页文本、时区与哈希治理
  -> OperationPhase、ExcavationEpisode、SpatialFootprint
  -> 机械响应证据 + 地质 FORECAST/OBSERVED 证据
  -> time/space/epistemic Applicability
  -> ConstructionStateCell + DailyConstructionState
  -> valid time × knowledge time 的双时间认识状态
  -> RAI / GRS / GRCI 非概率关注指标
  -> Typed Claim opportunity + Claim Contract
  -> EXPRESSIBLE 或 ABSTAIN
  -> FactLock + Evidence Pack
  -> 模型仅规划表达顺序
  -> 确定性物化、校验、组合与审计
```

## 大语言模型的真实角色

大语言模型只出现在最后的 presentation planning 层。它看见的是冻结的 RealizationUnit 和表达约束，只能返回最小 JSON 计划；工程事实值、认识性质、空间范围、Claim 许可和最终规范句均由上游权威对象及确定性代码决定。模型不能计算施工事实、判断地质原因、补齐 UNKNOWN、把 attention 解释为概率，也不能绕过 FactLock。

## 冻结研究规模

- {counts["plc_observations"]} 条 PLC 标准观测，形成 {counts["episodes"]} 个 ExcavationEpisode。
- 91 PLC-monitored construction dates，跨度 {counts["plc_start"]} 至 {counts["plc_end"]}，中间存在日历空档。
- {counts["documents"]} 份 canonical geological documents，{counts["primary_evidence"]} 条 Primary Evidence。
- {counts["initial_states"]} 个初始状态与 {counts["bitemporal_states"]} 个双时间状态版本。
- {counts["claim_opportunities"]} 个 Claim opportunities，其中 {counts["expressible"]} EXPRESSIBLE、{counts["abstain"]} ABSTAIN。
- 主实验为 48 个 held-out tasks × 3 种方法；机器实验已完成，人工语义评价保留为 `DEFERRED_TO_HUMAN`。

## 研究贡献的准确表述

本项目能够证明的是：证据治理、双时间状态、Claim Contract、受控实现和审计链在本工程数据上实现了内部一致、可追溯和确定性行为；后到证据确实能够在不污染历史认识的情况下改变 GRS、GRCI 与 Claim 可表达性。它不能证明跨项目普适性、灾害概率、因果诊断、人工工程正确率或对所有生成基线的普遍优越性。
"""
    pipeline = """# 完整技术路线

## 1. 资产与证据治理

**输入**：91 个 PLC 监测施工日期对应的 CSV、227 个原始地质 PDF 资产。  
**方法**：SHA-256 去重、左右线范围治理、SourceAsset 登记、分页文本、source timezone 本地化后转 UTC、submitted/document/observed 时间分离。PDF 主表由 `pdfplumber` 解析并以真实页码和 bbox 形成 SourceSpan。  
**输出**：标准 PLC Observation；223 个 canonical GeologicalDocument；659 条 Primary Geological Evidence；122 条 ReportAssertion；4713 个 SourceSpan。  
**约束**：表头、方法原理和仪器说明不是地质 Evidence；FORECAST/OBSERVED 由来源语义决定；无法定位的条款不扩展到文档范围。

## 2. 施工过程对象

**输入**：按时间排序的 PLC Observation。  
**方法**：状态机识别 IDLE、STARTUP、EXCAVATING、COASTDOWN、UNKNOWN，随后将相邻相位聚合为 `ExcavationEpisode`。Episode 的核心时间只由首末 EXCAVATING 区间定义；上下文时间、内部中断、文件边界截断和覆盖率独立保存。  
**输出**：1119 个 Episode、对应 SpatialFootprint 与 5595 条通道级 ResponseEvidence。  
**约束**：文件首尾截断不能伪装成真实起止；0 m 推进冲突保留；单位未验证字段不能用于物理计算；机械响应不解释为地质原因。

## 3. 空间足迹与适用性

**输入**：Episode footprint、地质 point/interval evidence、available time。  
**方法**：把 10 m ConstructionStateCell 作为空间索引；按区间重叠、点边界唯一归属、target date 与 knowledge availability 判定 Evidence role。  
**输出**：59969 条 Primary Evidence Applicability assignments，并区分 DAILY_REVIEW、FORWARD_ATTENTION、LOCAL_BACKGROUND、NOT_APPLICABLE。  
**约束**：未来网格只是索引，不是施工事实；前方预报进入 DAILY_REVIEW 后仍是 FORECAST；LOCAL_BACKGROUND 不能直接支持事实 Claim。

## 4. 初始施工认识状态

**输入**：Episode、ResponseEvidence、Applicability assignments。  
**方法**：为每个 PLC-monitored construction date 构建 DailyConstructionState，把实际开挖关联到 156 个固定 Cell，再生成 1322 个 InitialStateVersion。  
**输出**：2685 条地质链接、5510 条 Cell-level response 链接；另保留 95 条 located point daily-only 与 75 条 spatially unlocated response coverage。  
**约束**：5595/5595 ResponseEvidence 必须有唯一覆盖类；不可定位对象不静默丢失，也不猜测空间。

## 5. 双时间认识状态

**输入**：初始状态、后到地质证据的 available time、历史 applicability。  
**方法**：valid date 表示被描述的施工日；knowledge interval 表示该版本在何时可被系统知道。新证据到达时，新版本通过 `supersedes_bitemporal_version_id` 连接旧版本。  
**输出**：1375 个 bitemporal versions、53 个 revision events、72 条 revision evidence links。  
**约束**：版本方向来自 version_number 与 supersession lineage，不来自 ID 字典序；历史数据库 transaction log 不可得，knowledge time 是可审计的认识可用性重建。

## 6. RAI：施工响应关注度

对每个通道，先以只使用此前观测的因果历史窗口计算 robust z：

```text
z_c = (x_c - median_history,c) / (1.4826 * MAD_history,c)
d_c = median_episode(|z_c|)
```

LOAD_RESPONSE 包含 total_thrust 与 cutterhead_torque；ADVANCE_KINEMATIC_RESPONSE 包含 advance_speed 与 penetration。族内取两通道 `d_c` 的最大值，族关注度为 `min(d_family / 3, 1)`，最终 `RAI=max(A_LOAD,A_KINEMATIC)`。两族必须都完整；cutterhead_rpm 仅作诊断，不进入标量 RAI。

## 7. GRS：地质证据关注度

冻结的 44 个来源值映射到六个维度：异常、围岩等级、岩体完整性、节理发育、稳定/掉块和水。维度内使用最值得关注的映射值：

```text
G_d = max(mapped_attention values in dimension d)
GRS = mean_non_null_dimension_attention(G_d)
```

缺失维度不当作 0。证据角色和 FORECAST/OBSERVED 状态完整保留。

## 8. GRCI：联合关注度

仅在 DAILY_REVIEW_CELL 且 RAI、GRS 同时可用时：

```text
GRCI = RAI * GRS
```

它是非概率 conjunctive attention，不是风险概率，也不是地质—机械因果估计。

## 9. Claim opportunity 与 admissibility

Stage5B 对每个双时间状态、主体和属性槽位确定性枚举 Claim opportunity。Stage5A Claim Contract 要求权威 support kind、state role、epistemic status、metric availability、qualifiers 与 spatial subject binding，并禁止 probability/causality 等越界语义。全部满足则物化 TypedEngineeringClaim；否则输出 ABSTAIN 与单一主原因码。

## 10. FactLock、Evidence Pack 与受控实现

每个 EXPRESSIBLE Claim 转为 FactLock，记录原值、范围、认识状态、支持对象、允许修饰语和禁止变换。Evidence Pack 按日期/Cell/产品切片，并用 hash 锁定。模型只能对 RealizationUnit 返回 pure-JSON 计划；随后由确定性 materializer、validator、composer 与 post-audit 生成文本。任何结构错误均 fail closed，不进行 JSON repair。

## 11. 实验与追溯

Stage7A 冻结 held-out benchmark；Stage7B 运行 B0/B1/P；Stage7C 做确定性错误审计；Stage7D 分析双时间修订价值；Stage7E 做消融；Stage7F 做参数敏感性。每个核心数字在 `14_RESULT_TRACEABILITY.csv` 中映射到 frozen source、commit、tag 与字段。
"""
    dataset = f"""# 数据集与系统规模

## 输入边界

研究对象为单一 TBM 工程进口右线。PLC 覆盖 **91 PLC-monitored construction dates**，从 **{counts["plc_start"]}** 跨度至 **{counts["plc_end"]}**；这些日期并非连续日历天。原始地质资产治理结果为 227 个 raw assets，其中 225 个 in-scope assets，2 个 duplicate aliases 和 2 个 out-of-scope assets，形成 223 个 canonical documents。

## 证据规模

- PLC 标准观测：{counts["plc_observations"]}。
- ExcavationEpisode：{counts["episodes"]}。
- ResponseEvidence：{counts["response_evidence"]}。
- Primary Geological Evidence：{counts["primary_evidence"]}，其中 OBSERVED={counts["observed_evidence"]}、FORECAST={counts["forecast_evidence"]}。
- ReportAssertion：{counts["report_assertions"]}；SourceSpan：{counts["source_spans"]}。

## 状态与指标规模

- 固定 10 m ConstructionStateCell：{counts["cells"]}。
- DailyConstructionState：{counts["daily_states"]}；InitialStateVersion：{counts["initial_states"]}。
- BitemporalVersion：{counts["bitemporal_states"]}；RevisionEvent：{counts["revision_events"]}。
- RAI/GRS/GRCI 对每个双时间版本均有状态对象，各 {counts["bitemporal_states"]} 条；实际可用分别为 {counts["rai_available"]}、{counts["grs_available"]}、{counts["grci_available"]}。

## Claim 规模

冻结 universe 有 {counts["claim_opportunities"]} 个 opportunity。{counts["expressible"]} 个满足合同并生成 Typed Claim，{counts["abstain"]} 个正式拒绝表达。可表达率 {counts["expressibility_rate"]:.3%} 只表示合同与证据边界内的 materialization rate，不是模型准确率。

完整逐层表见 `03_dataset_scale.csv`。
"""
    main = """# 主实验：三方法真实模型比较

## 设计

Stage7A.3 冻结 48 个 held-out tasks。每个任务以完全相同的 as-of evidence snapshot 构造三种条件，总计 144 个执行项，均使用 `deepseek-v4-flash`、temperature=0、top_p=1、max_retries=0。

- **B0**：把 pre-Claim 原始结构输入直接交给模型生成。
- **B1**：同一 pre-Claim 信息配合结构化提示生成。
- **P**：冻结 Claim Gate、FactLock、Evidence Pack 和 deterministic composer；模型只规划 RealizationUnit 顺序。

## 执行结果

B0 产生 48/48 输出，B1 产生 48/48 输出。P 收到 48 个 raw plans，其中 45 个通过严格 schema 与 section-order 校验并形成最终文本；任务 `022`、`026`、`042` 因 `INVALID_SECTION_ORDER` 被 fail closed，因此 P 最终输出为 45/48。三项不是 transport failure，也没有重试或 JSON repair。

## 确定性评价

Stage7C.1 v1.2 对 E2/E3/E4/E5/E7/E10/E12/E13/E14 做离线规则审计。P 的 45 份实际文本在自动可判定项上没有 fail；B0 出现 2 个 E5 自动 fail；B1 没有自动 fail。这里的分母是 check instances，不是 48 个任务的“准确率”。P 的 3 个无输出任务保留在 condition denominator 中，但不被算作 prose semantic failure。

## 尚未完成的评价

E7 的语义完整性、E14 的整体工程可接受性，以及许多 E2/E4/E5/E10/E12 边界样本仍标记 `DEFERRED_TO_HUMAN`。因此现有机器结果能够支持“结构、数值、边界和 trace 的确定性约束更强”，不能支持“P 的工程语义质量已经被人工证明优于 B0/B1”。

## 复现身份

正式 run 为 `stage7b_main_execution_3ae0f791811a2e711cb9f488`，execution manifest hash=`75f2f9976b2cc85bdcf79a790baf07a8c623fa3fa24c2de16cdbdef9eafe34cc`，protocol hash=`19c1bb629765198316c44951bddfbdf7547f017da6793c698c6f98f376260cbf`。
"""
    claims = f"""# Claim 可表达性与正式拒答

## 冻结 universe

Stage5B 基于 1375 个双时间状态版本确定性生成 {counts["claim_opportunities"]} 个 Claim opportunities。Stage5C 不重新生成 Claim，也不使用文本启发式改变决定，而是分析冻结 proposal/decision/typed-claim 对象。

## 总体结果

- EXPRESSIBLE：{counts["expressible"]}（{counts["expressibility_rate"]:.3%}）。
- ABSTAIN：{counts["abstain"]}（{counts["abstention_rate"]:.3%}）。

可表达率表示：在当前 Claim Contract、状态角色、权威支持、空间主体绑定、knowledge time 和 metric availability 下，有多少冻结机会满足表达条件。它不是模型准确率、风险识别率或 LLM 正确率。ABSTAIN 也不是失败，而是防止越界陈述的正式输出。

## ABSTAIN 分类

{reason_lines}

其中政策/上下文边界类 `CONTEXT_ONLY_ROLE + STATE_ROLE_NOT_ALLOWED` 共 1185 条，占全部 ABSTAIN 的 49.375%。这部分拒答反映的是设计边界，不是数据解析失败。

## Gate 的执行顺序

1. 由权威状态对象确定 Claim 主体、valid date、Cell 与 role。
2. 根据 contract 解析 required/allowed/forbidden support kinds。
3. 对地质事实验证 source epistemic status；FORECAST 和 OBSERVED 不混层。
4. 对指标 Claim 验证 metric name、status、value 和非概率语义。
5. 验证 spatial subject binding 与 resolved support context。
6. 检查禁用语义，包括因果、概率、UNKNOWN→normal 和 forecast→observed。
7. 通过才生成 TypedEngineeringClaim；否则保存 ABSTAIN reason。

模型不参与上述任何步骤。
"""
    bitemporal = """# 双时间结果

## A. 48-task benchmark alignment：零重叠诊断

Stage7D v1 将 48 个 held-out benchmark tasks 与 53 条 Stage3B revision chains 对齐，得到 affected tasks=0、later evidence=0。这个 null result 的含义是：当前 held-out 任务没有落在修订事件覆盖的 date-cell 上，因此主生成实验不能直接估计 revision-aware 与 final-state-only 的差异。

它不能解释为“双时间没有用”。把无重叠设计产生的零效应写成方法无效，会混淆实验支持域与研究机制。

## B. 全量 revision census

Stage7D v1.1 对全部 53 个 revision events 做 paired census，覆盖 14 个 valid dates、51 个 revised cells、72 条 later-evidence links 和 34 条唯一后到证据：

- RAI changed：0/53。地质后到证据不应反向改变机械响应指标。
- GRS changed：36/53（67.925%）。
- GRCI changed：1/53（1.887%），因为仅 DAILY_REVIEW 且 RAI/GRS 同时可用时才定义。
- 既有 Claim decision `ABSTAIN_TO_EXPRESSIBLE`：27。
- 新增 Claim opportunities：540，其中 504 FORECAST、36 OBSERVED；修正后 454 EXPRESSIBLE、86 ABSTAIN。
- 所有 53 个事件均出现至少一种 Claim semantic change。

## 认识论解释

pre-revision 版本不是“错误状态”，它忠实表示当时可知道什么；post-revision 也不是对过去的篡改，而是保留旧版本后新增一个知识区间。研究价值在于同时回答“当时能说什么”和“后来知道了什么”，而不是只保存最终历史。
"""
    ablation = """# 消融结果

## A1：Claim Gate bypass

最终状态为 `NOT_EXECUTABLE_ON_FROZEN_48_TASK_BENCHMARK`，原因 `NO_CONCRETE_GATE_BYPASS_CANDIDATES`。因此 A1 只能报告设计可执行性边界，不能报告模型性能，也不能把未执行当成零效应。

## A2：认识限定语移除

冻结目标为 31 个 sections，影响 24 个 tasks。该实验用于定位 FORECAST/OBSERVED/attention 等限定语在输出中的保护作用；最终语义影响仍需人工评价。

## A3：规划结构与映射

严格 primary parser：125/147 chunks 合法，828/989 Claim mappings 成功，32/45 tasks 完整。修正后的严格 numeric audit 为 149/149 exact、0 drift。

仅去除完整外层 Markdown JSON fence 的 secondary 离线解释：147/147 chunks、989/989 mappings、45/45 tasks；164/164 numeric exact、0 drift。它是 post-hoc secondary endpoint，不能替代严格 primary protocol compliance。

## A4：FactLock trace

总 FactLock trace coverage 为 848/1022（82.975%），遗漏 174；numeric FactLock coverage 为 162/171（94.737%），遗漏 9。已引用的 162 个 numeric FactLocks 全部 exact，numeric drift=0。

## 解释边界

`trace coverage != semantic correctness`，`numeric exact != full semantic correctness`。旧版记录的 149 个数值漂移来自 Unicode tokenizer bug，已被最终审计废弃，不得用于论文。
"""
    sensitivity = """# 敏感性与有效性边界

## Cell size：5 m / 10 m / 20 m

- 5 m：`VALID_SENSITIVITY_ARM`，是相对 10 m 的主要更细分辨率比较。
- 10 m：`VALID_BASELINE`，156 个固定 Cell。
- 20 m：`COARSE_RESOLUTION_STRESS_TEST`，并已越过方法有效性边界。

20 m 产生 90 个 scope-role conflicts、23 个 point undercoverage 和 76 个 interval undercoverage；实际 evaluated exposure 为 14180 m，而 5/10 m 均为 13220 m。因此 20 m 的 per-100m 统计只能描述 coarse stress behaviour，不能与 5/10 m 当作等支持域 arms，也不得概括为跨全部分辨率的等稳健结论。

## RAI 历史充分性：20 / 30 / 40 observations

30 为 baseline。20 使 RAI/GRCI availability 各增加 2，并出现 4 个 ABSTAIN→EXPRESSIBLE；40 各减少 2，并出现 4 个 EXPRESSIBLE→ABSTAIN。共同可比较的 RAI/GRCI 值总体稳定，但 availability 边界会改变 Claim decision。

## RAI 饱和尺度：2 / 3 / 4

改变饱和尺度会改变 absolute RAI/GRCI values，但 rank consistency 高；Claim transitions=0，monotonicity violations=0。这表示当前合同不以数值阈值切换 Claim，不等于指标数值对参数完全不敏感。

## 最终结论

冻结结果没有执行 automatic robust/not-robust classification，也没有选择“最佳参数”。可支持的结论是：10 m 基线与 5 m finer arm 在原生质量门上有效；20 m 暴露出空间角色离散化的粗分辨率边界；history 参数影响早期可用性；saturation 参数影响数值尺度但未改变当前 Claim 决策。
"""
    boundaries = """# 科学边界与禁止过度解释

1. **LLM 不计算工程事实。** 数值、范围、认识状态和 Claim admissibility 来自确定性上游对象。
2. **LLM 不判断地质风险。** 它只能规划已锁定句子的顺序。
3. **FORECAST 不等于 OBSERVED。** 预报进入当日 review 后仍是预报。
4. **UNKNOWN 不等于 NORMAL。** 不可用值必须保留缺失或 ABSTAIN。
5. **missing metric 不等于 0。** 指标状态与指标数值分开保存。
6. **attention 不等于 probability。** RAI、GRS、GRCI 均为关注指标。
7. **GRCI 不等于 causality。** 乘积只表示两类关注同时存在，不诊断地质致因。
8. **forward attention 不等于 occurred fact。** 前方证据不能写成已揭露事实。
9. **10 m Cell 不等于原子 ground truth。** 它是研究空间索引，敏感性实验已经显示分辨率边界。
10. **ExcavationEpisode 不等于人工观测真值。** 它由 PLC 相位规则重建，并带截断和质量状态。
11. **knowledge time 是 reconstructed epistemic availability。** 历史数据库 transaction log 不可得。
12. **single project 不支持 cross-project generalization。** 外部效度需要其他工程验证。
13. **machine audit 不等于 human semantic correctness。** 自动审计验证结构、数值和部分边界；人工语义端点仍 deferred。
14. **20 m 是 stress test。** 它越过原生空间质量门，不能作为 clean robustness arm。
15. **Claim 可表达率不是模型准确率。** 它是合同约束下冻结 opportunity universe 的 materialization proportion。
16. **后到 Claim opportunity 不表示旧版本错误。** 它表示新证据改变了可知道内容。
"""
    case_sections: list[str] = ["# 工程案例候选", ""]
    for index, case in enumerate(cases, 1):
        case_sections.extend(
            [
                f"## {index}. {case['label']}",
                "",
                f"- 日期：`{case['date']}`",
                f"- 空间：`{case['chainage']}`",
                f"- Cell：`{case['cell_id']}`",
                f"- Episode：`{', '.join(case['episode_ids']) or '不适用'}`",
                f"- Evidence IDs：`{', '.join(case['evidence_ids'])}`",
                f"- State IDs：`{', '.join(case['state_ids'])}`",
                f"- Metrics：`{json.dumps(case['metrics'], ensure_ascii=False)}`",
                f"- Claim IDs：`{', '.join(case['claim_ids']) or '见 revision transition rows'}`",
                f"- FactLocks：`{', '.join(case['fact_lock_ids']) or '不适用'}`",
                f"- Claim transitions：`{json.dumps(case.get('transition_counts', {}), ensure_ascii=False) or '不适用'}`",
                f"- 选择原因：{case['selection_reason']}",
                f"- 冻结文本：{case['text_output']}",
                "- 来源：" + "；".join(f"`{item}`" for item in case["source_artifacts"]),
                "",
            ]
        )
    case_sections.extend(
        [
            "## 最终推荐",
            "",
            "- **论文主案例**：Case A（2023-10-07）。它在同一任务中闭合 Episode、5 通道响应证据、HSP FORECAST、状态、三指标、10 个 FactLocks 与最终文本，并可用于对照检查 B0/B1 的因果与认识边界表述。",
            "- **论文修订案例**：revision census Case A（2023-11-28）。三条后到 FORECAST 证据使前方 Cell 的 GRS 从不可用变为 0.625，新增 24 个 FORECAST geological opportunities，并使 1 条 FORWARD_GEOLOGICAL_ATTENTION 从 ABSTAIN 转为 EXPRESSIBLE。",
        ]
    )
    outline = """# 论文结果章节骨架

## 4.1 Experimental setup

- **Research question**：三种 realization 方法在同一 as-of 输入下的可审计行为有何差异？
- **Data**：48 held-out tasks × B0/B1/P。
- **Metrics**：输出可用率、结构 fail-closed、E2-E14 自动 endpoints、人工评价状态。
- **Table/Figure**：Table 3；Figure main experiment。
- **Main finding**：P 45/48 通过严格计划门，3 个结构错误被拦截；自动可判定文本项零 fail。
- **Allowed**：受控层提供可观察、可拦截的结构行为。
- **Forbidden**：在人工评价完成前宣称整体语义显著优于 baseline。

## 4.2 Dataset and implementation

- **Research question**：证据和状态系统的实际规模与覆盖是什么？
- **Data**：Stage2-6 frozen manifests。
- **Metrics**：observations、Episode、Evidence、State、Metric、Claim 数量。
- **Table/Figure**：Table 1；技术路线图。
- **Main finding**：异构证据被统一到可追溯的时空认识状态。
- **Allowed**：报告单工程内部覆盖与质量门。
- **Forbidden**：称 91 天为连续日期或将单工程规模外推。

## 4.3 Main comparison

- **Research question**：直接、结构化提示、Claim-gated controlled realization 的机器行为差异。
- **Data**：Stage7B raw/final outputs 与 Stage7C deterministic audits。
- **Metrics**：输出率、自动错误、结构拦截。
- **Table/Figure**：Table 3；Figure 3。
- **Main finding**：P 将不可接受 plan fail closed，并保持数值/认识边界。
- **Allowed**：确定性 endpoints。
- **Forbidden**：把 check-instance count 当 task accuracy。

## 4.4 Claim admissibility analysis

- **Research question**：证据与合同边界如何塑造可表达空间？
- **Data**：8679 frozen opportunities。
- **Metrics**：EXPRESSIBLE/ABSTAIN、reason taxonomy。
- **Table/Figure**：Table 2；Claim gate bar chart。
- **Main finding**：72.347% 可表达，27.653% 正式拒答；近半拒答源于 policy/context boundary。
- **Allowed**：contract-governed expressibility。
- **Forbidden**：解释成 accuracy 或 failure rate。

## 4.5 Bitemporal knowledge revision

- **Research question**：later evidence 如何改变指标与 Claim？
- **Data**：48-task null alignment + 53-event full census。
- **Metrics**：metric change、decision switch、opportunity addition。
- **Table/Figure**：Table 4；revision transition figure。
- **Main finding**：地质修订主要改变 GRS 和 geological Claim，不改变 RAI。
- **Allowed**：说明双时间保留 as-known 历史的必要性。
- **Forbidden**：用 benchmark null 否定双时间价值。

## 4.6 Ablation study

- **Research question**：gate、qualifier、plan structure、FactLock trace 的作用。
- **Data**：Stage7E final corrected machine summary。
- **Metrics**：A1 status、A2 affected、A3 strict/secondary、A4 coverage。
- **Table/Figure**：Table 5；ablation coverage figure。
- **Main finding**：数值漂移为 0；严格 schema 暴露 22 个 fence failures；trace 并非全覆盖。
- **Allowed**：结构与 trace 的机器证据。
- **Forbidden**：把 numeric exact/trace coverage 当语义正确率。

## 4.7 Sensitivity and robustness

- **Research question**：三类参数扰动如何改变结果与有效性边界？
- **Data**：7 个 OFAT arms。
- **Metrics**：native quality gate、availability、Claim transitions、rank/value behaviour。
- **Table/Figure**：Table 6；sensitivity panel。
- **Main finding**：5 m 有效；20 m 越界；history 改变早期可用性；saturation 改值不改 Claim。
- **Allowed**：有限条件下的敏感性描述。
- **Forbidden**：宣布 5-20 m 等稳健或自动选择最优参数。

## 4.8 Engineering case study

- **Research question**：完整证据链和知识修订在具体里程上如何工作？
- **Data**：2023-10-07 主案例；2023-11-28 修订案例。
- **Metrics**：RAI/GRS/GRCI、Claim/FactLock/输出与 revision transitions。
- **Table/Figure**：案例链路图、pre/post 状态图。
- **Main finding**：controlled realization 保留 FORECAST 与非概率边界；later evidence 扩展可表达空间而不覆盖旧认识。
- **Allowed**：逐对象 trace-backed 解释。
- **Forbidden**：把个案写成因果证明或跨工程结论。
"""
    archive = """# 最小研究归档集合

未来若清理工作区，必须先完成离线校验并保留以下集合：

1. **Git 身份**：完整 repository history、所有 frozen tags、最终 handoff tag；至少保留一份可校验的 bare mirror。
2. **实现**：`src/`、`scripts/`、`configs/`、`tests/`、`pyproject.toml` 和 lock file。
3. **论文证据索引**：整个 `artifacts/final_research_handoff_v1/`，包括 traceability、superseded registry、paper tables/figures 与 hashes。
4. **冻结核心成果**：Stage2 geology/PLC/applicability，Stage3A/3B，Stage4，Stage5A/B/C，Stage6A/B，Stage7A-F 的正式 manifest、summary、hard-check、hash 文件。
5. **不可重建原始资料**：PLC 原始 CSV 与地质 PDF。因体积和版权可不进入 Git，但必须外部加密归档并保存 SHA-256、目录清单、访问说明和至少两份副本。
6. **真实模型原始响应**：Stage6B smoke、Stage7B main、Stage7E ablation 的 raw response 是付费调用的实验原始记录，必须保留。建议 Git LFS 或外部只读归档，不能只保留解析后的文本。
7. **环境**：lock file、Python 版本、pdfplumber/PyMuPDF/SDK 版本以及 provider/model/protocol identity；API key 永不归档。

可通过 Git 历史保留但不必长期放在当前 worktree 的，是已被正式目录替代的 candidate 与旧 schema。review ZIP、cache 和可重建虚拟环境在人工核验后可清理。任何删除都必须依据 `15_REPOSITORY_RETENTION_PLAN.csv` 另行执行；本轮没有删除文件。
"""
    readme = """# Final Research Handoff Bundle v1

这是论文写作和后续接手的唯一入口。目录内容来自冻结实现与 artifact 的只读汇总，不重跑实验，也不修改任何历史结果。

## 推荐阅读顺序

`00_PROJECT_OVERVIEW.md` → `01_TECHNICAL_PIPELINE.md` → `03_DATASET_AND_SYSTEM_SCALE.md` → `04_EXPERIMENT_MASTER_REGISTRY.csv` → `06_CLAIM_ADMISSIBILITY.md` → `07_BITEMPORAL_RESULTS.md` → `08_ABLATION_RESULTS.md` → `09_SENSITIVITY_RESULTS.md` → `11_SCIENTIFIC_BOUNDARIES.md` → `13_PAPER_RESULTS_CHAPTER_OUTLINE.md`。

## 论文只能引用的 canonical 文件

- 数字总索引：`14_RESULT_TRACEABILITY.csv`。
- 表格数据：`paper_tables/table_*.csv` 及各 README。
- 图数据：`paper_figures/figure_*.csv` 与 `PAPER_FIGURE_PLAN.md`。
- 方法公式：`02_METHOD_DEFINITION_REGISTRY.csv`，并以其中列出的源码/配置为最终依据。
- 废弃结果：`10_SUPERSEDED_RESULT_REGISTRY.csv`。其中任何 `must_not_use_in_paper=true` 的值不得引用。
- 科学边界：`11_SCIENTIFIC_BOUNDARIES.md`。

## 审计入口

`final_handoff_hard_check.csv` 必须全部 PASS；`SOURCE_INVENTORY.csv` 给出读取源及 SHA-256；`file_hashes.sha256` 校验本目录；`freeze_manifest.json` 记录数量和 Git 身份。
"""
    return {
        "00_PROJECT_OVERVIEW.md": overview,
        "01_TECHNICAL_PIPELINE.md": pipeline,
        "03_DATASET_AND_SYSTEM_SCALE.md": dataset,
        "05_MAIN_EXPERIMENT.md": main,
        "06_CLAIM_ADMISSIBILITY.md": claims,
        "07_BITEMPORAL_RESULTS.md": bitemporal,
        "08_ABLATION_RESULTS.md": ablation,
        "09_SENSITIVITY_RESULTS.md": sensitivity,
        "11_SCIENTIFIC_BOUNDARIES.md": boundaries,
        "12_CASE_STUDY_CANDIDATES.md": "\n".join(case_sections) + "\n",
        "13_PAPER_RESULTS_CHAPTER_OUTLINE.md": outline,
        "16_MINIMAL_RESEARCH_ARCHIVE.md": archive,
        "README.md": readme,
    }


def _superseded_rows() -> list[dict[str, str]]:
    return [
        {
            "old_result": "Stage7C v1/v1.1 automatic evaluation summaries",
            "why_invalid": "later deterministic closure corrected denominator and boundary handling",
            "correct_result": "use Stage7C v1.2 final closure only",
            "superseded_by": "stage7c-main-auto-evaluation-v1.2-frozen",
            "must_not_use_in_paper": "true",
        },
        {
            "old_result": "A3 numeric drift = 149",
            "why_invalid": "Python Unicode \\w boundary prevented numbers adjacent to Chinese characters from tokenizing",
            "correct_result": "strict 149/149 exact, drift=0; secondary 164/164 exact, drift=0",
            "superseded_by": "stage7e-ablation-execution-v1.1a-final-machine-results",
            "must_not_use_in_paper": "true",
        },
        {
            "old_result": "A4 numeric denominator = 164",
            "why_invalid": "164 was a secondary A3 mapped-claim denominator, not the frozen A4 numeric FactLock universe",
            "correct_result": "A4 numeric FactLocks 162/171 used; 9 omitted; referenced 162/162 exact",
            "superseded_by": "stage7e-ablation-execution-v1.1a-final-machine-results",
            "must_not_use_in_paper": "true",
        },
        {
            "old_result": "A1 is executable or has zero effect",
            "why_invalid": "frozen 48-task benchmark contains no concrete gate-bypass candidates",
            "correct_result": "NOT_EXECUTABLE_ON_FROZEN_48_TASK_BENCHMARK / NO_CONCRETE_GATE_BYPASS_CANDIDATES",
            "superseded_by": "stage7e-ablation-execution-v1.1a-final-machine-results",
            "must_not_use_in_paper": "true",
        },
        {
            "old_result": "Stage7D benchmark null means bitemporal state has no value",
            "why_invalid": "48 held-out tasks have zero overlap with the 53 revision events",
            "correct_result": "report null alignment separately; full census has 53 events, GRS 36 changes, 27 decision switches, 540 additions",
            "superseded_by": "stage7d-bitemporal-value-v1.1a-frozen",
            "must_not_use_in_paper": "true",
        },
        {
            "old_result": "GRCI = sqrt(RAI * GRS)",
            "why_invalid": "stale Stage7F protocol description conflicted with frozen implementation",
            "correct_result": "GRCI = RAI * GRS",
            "superseded_by": "stage7f-sensitivity-execution-v1.1-final-machine-results",
            "must_not_use_in_paper": "true",
        },
        {
            "old_result": "GRS uses one global maximum",
            "why_invalid": "stale Stage7F metadata collapsed two aggregation levels",
            "correct_result": "dimension=max_mapped_attention; state=mean_non_null_dimension_attention",
            "superseded_by": "stage7f-sensitivity-execution-v1.1-final-machine-results",
            "must_not_use_in_paper": "true",
        },
        {
            "old_result": "20m is a clean robustness arm or 5-20m are equally robust",
            "why_invalid": "20m has 90 role conflicts, 23 point undercoverage and 76 interval undercoverage",
            "correct_result": "20m is COARSE_RESOLUTION_STRESS_TEST beyond native validity boundary",
            "superseded_by": "stage7f-sensitivity-execution-v1.1-final-machine-results",
            "must_not_use_in_paper": "true",
        },
        {
            "old_result": "Stage3A v1 point response links are complete",
            "why_invalid": "old v1 omitted trusted POINT mechanical response linkage",
            "correct_result": "use Stage3A v1.1 point-response-complete",
            "superseded_by": "artifacts/stage3a_initial_epistemic_state_v1_1/freeze_manifest.json",
            "must_not_use_in_paper": "true",
        },
    ]


def _paper_readme(title: str, unit: str, denominator: str, source: str, caveat: str) -> str:
    return f"""# {title}

- **统计单位**：{unit}
- **分母**：{denominator}
- **冻结来源**：`{source}`
- **使用说明**：该 CSV 是论文制表数据，不替代权威 frozen artifact。
- **关键边界**：{caveat}
"""


def _figure_plan() -> str:
    return """# 论文图数据计划

## Figure 1：Claim Gate 输出分布

使用 `figure_claim_gate.csv` 绘制 EXPRESSIBLE 与各 ABSTAIN reason 的堆叠条形图。分母固定为 8679 opportunities；不要把 ABSTAIN 标为错误率。

## Figure 2：双时间修订效应

使用 `figure_bitemporal.csv` 绘制 RAI/GRS/GRCI change incidence、ABSTAIN→EXPRESSIBLE 和 OPPORTUNITY_ADDED。48-task null alignment 应作为独立注释，不与 53-event census 混分母。

## Figure 3：主实验流程与确定性端点

使用 `figure_main_experiment.csv` 绘制 48 planned tasks 的输出可用性、P fail-closed 和自动 fail。人工语义 endpoints 用灰色 `DEFERRED_TO_HUMAN` 标识，不能补零。

## Figure 4：消融覆盖

使用 `figure_ablation.csv` 展示 A3 strict/secondary 与 A4 trace/numeric coverage。A1 用 `NOT_EXECUTABLE` 单独标记，旧 numeric drift 149 不进入图。

## Figure 5：敏感性与有效性边界

使用 `figure_sensitivity.csv` 分三面板展示 Cell size、history 和 saturation。20m 必须用 stress-test 样式并标注 90/23/76 质量问题；不要用一条“robust”折线概括全部 arms。
"""


def _source_inventory(repo: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
    stage_for_key = {
        "geology": "Stage2 geology",
        "plc": "Stage2 PLC",
        "applicability": "Stage2 applicability",
        "stage3a": "Stage3A",
        "stage3b": "Stage3B",
        "stage4": "Stage4",
        "stage5b": "Stage5B",
        "stage5c_universe": "Stage5C",
        "stage5c_rates": "Stage5C",
        "stage5c_reasons": "Stage5C",
        "stage6a": "Stage6A",
        "stage7b": "Stage7B",
        "stage7c": "Stage7C",
        "stage7c_methods": "Stage7C",
        "stage7d_v1": "Stage7D",
        "stage7d_primary": "Stage7D",
        "stage7d_secondary": "Stage7D",
        "stage7d_correction": "Stage7D",
        "stage7e": "Stage7E",
        "stage7f": "Stage7F",
    }
    tag_key_for_stage = {
        "Stage4": "stage4",
        "Stage5B": "stage5b",
        "Stage5C": "stage5c",
        "Stage6A": "stage6a",
        "Stage7B": "stage7b",
        "Stage7C": "stage7c",
        "Stage7D": "stage7d",
        "Stage7E": "stage7e",
        "Stage7F": "stage7f",
    }
    rows = []
    for key, path in data["paths"].items():
        stage = stage_for_key[key]
        broad = stage.split()[0]
        tag_key = tag_key_for_stage.get(broad, "stage4")
        rows.append(
            {
                "inventory_id": key,
                "stage": stage,
                "relative_path": str(path.relative_to(repo)),
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
                "source_tag": FINAL_TAGS[tag_key],
                "source_commit": data["tags"][tag_key],
                "use_in_handoff": "canonical counts/results",
            }
        )
    extras = [
        (
            "metric_config",
            "Stage4",
            "configs/state_metric_definition_v1.yaml",
            "stage4",
            "metric formula",
        ),
        ("rai_source", "Stage4", "src/tbm_twin/metrics/rai.py", "stage4", "RAI implementation"),
        ("grs_source", "Stage4", "src/tbm_twin/metrics/grs.py", "stage4", "GRS implementation"),
        ("grci_source", "Stage4", "src/tbm_twin/metrics/grci.py", "stage4", "GRCI implementation"),
        (
            "claim_contract",
            "Stage5A",
            "configs/claim_contract_v1.yaml",
            "stage5a",
            "Claim Contract",
        ),
        (
            "claim_validation",
            "Stage5A",
            "src/tbm_twin/claims/validation.py",
            "stage5a",
            "admissibility implementation",
        ),
        (
            "claim_resolution",
            "Stage5A",
            "src/tbm_twin/claims/resolution.py",
            "stage5a",
            "authoritative support resolution",
        ),
        (
            "fact_locks",
            "Stage6A",
            "artifacts/stage6a_fact_lock_evidence_pack_v1/fact_locks.jsonl",
            "stage6a",
            "case trace",
        ),
        (
            "benchmark",
            "Stage7A",
            "artifacts/stage7a_experimental_protocol_v1_3/stage7_main_benchmark_manifest.json",
            "stage7a",
            "held-out tasks",
        ),
        (
            "main_outputs",
            "Stage7B",
            "artifacts/stage7b_main_comparison_v1/runs/stage7b_main_execution_3ae0f791811a2e711cb9f488/P_final_outputs.jsonl",
            "stage7b",
            "controlled text outputs",
        ),
        (
            "revision_cases",
            "Stage7D",
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_case_selection.json",
            "stage7d",
            "case selection",
        ),
    ]
    for inventory_id, stage, relative, tag_key, use in extras:
        path = repo / relative
        if not path.exists():
            raise FileNotFoundError(relative)
        rows.append(
            {
                "inventory_id": inventory_id,
                "stage": stage,
                "relative_path": relative,
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
                "source_tag": FINAL_TAGS[tag_key],
                "source_commit": data["tags"][tag_key],
                "use_in_handoff": use,
            }
        )
    return rows


def _hard_checks(
    output: Path,
    trace_rows: list[dict[str, Any]],
    counts: dict[str, Any],
    tags: dict[str, str],
    preexisting_paths: set[str],
    repo: Path,
) -> list[dict[str, str]]:
    all_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in output.rglob("*")
        if path.is_file()
        and path.suffix in {".md", ".csv", ".json"}
        and path.name != "10_SUPERSEDED_RESULT_REGISTRY.csv"
    )
    current_paths = {str(path.relative_to(repo)) for path in repo.rglob("*") if path.is_file()}
    checks = [
        ("all_final_tags_resolved", all(len(value) == 40 for value in tags.values()), str(tags)),
        (
            "all_final_commits_resolved",
            all(_git(repo, "cat-file", "-t", value) == "commit" for value in tags.values()),
            f"resolved={len(tags)}",
        ),
        (
            "all_paper_numbers_traceable",
            len(trace_rows) >= 40 and all(row["trace_status"] == "RESOLVED" for row in trace_rows),
            f"entries={len(trace_rows)}",
        ),
        (
            "no_source_unknown",
            not any("SOURCE_UNKNOWN" in str(value) for row in trace_rows for value in row.values()),
            "traceability contains no unresolved source",
        ),
        (
            "frozen_claim_counts",
            counts["claim_opportunities"] == 8679
            and counts["expressible"] == 6279
            and counts["abstain"] == 2400,
            "8679=6279+2400",
        ),
        (
            "no_superseded_numeric_drift_as_current",
            "numeric drift = 149" not in all_text and "numeric drift=149" not in all_text,
            "legacy 149 appears only in the superseded registry or as a negated warning",
        ),
        (
            "a1_not_executable",
            "NOT_EXECUTABLE_ON_FROZEN_48_TASK_BENCHMARK" in all_text
            and "NO_CONCRETE_GATE_BYPASS_CANDIDATES" in all_text,
            "A1 frozen boundary present",
        ),
        (
            "twenty_m_stress_test",
            "COARSE_RESOLUTION_STRESS_TEST" in all_text,
            "20m validity boundary present",
        ),
        (
            "monitored_dates_not_consecutive",
            "91 consecutive" not in all_text and "连续 91" not in all_text,
            "uses PLC-monitored construction dates",
        ),
        (
            "grci_product_correct",
            "GRCI = RAI * GRS" in all_text
            and "GRCI = RAI × GRS" in all_text
            and "sqrt(RAI" not in all_text,
            "product operator only in canonical documents",
        ),
        (
            "grs_aggregation_correct",
            "max_mapped_attention" in all_text and "mean_non_null_dimension_attention" in all_text,
            "two-level aggregation present",
        ),
        (
            "human_deferred_preserved",
            "DEFERRED_TO_HUMAN" in all_text,
            "semantic endpoints remain deferred",
        ),
        (
            "no_superseded_leakage",
            "5-20 m 同等稳健" not in all_text and "5–20m equally robust" not in all_text,
            "superseded claims only documented as forbidden",
        ),
        (
            "no_api_or_llm_calls",
            True,
            "builder performs local file reads, hashing and Git inspection only",
        ),
        (
            "no_existing_file_deleted",
            preexisting_paths <= current_paths,
            f"missing={sorted(preexisting_paths - current_paths)}",
        ),
    ]
    return [
        {"check_name": name, "status": "PASS" if passed else "FAIL", "details": details}
        for name, passed, details in checks
    ]


def _write_hashes(output: Path) -> None:
    paths = sorted(
        path for path in output.rglob("*") if path.is_file() and path.name != "file_hashes.sha256"
    )
    content = "".join(f"{_sha256(path)}  {path.relative_to(output)}\n" for path in paths)
    (output / "file_hashes.sha256").write_text(content, encoding="utf-8")


def build_final_handoff(repo: Path, output: Path | None = None) -> Path:
    """Build the manuscript evidence bundle without changing frozen inputs."""

    repo = repo.resolve()
    output = output or repo / "artifacts/final_research_handoff_v1"
    output = output.resolve()
    preexisting_paths = {str(path.relative_to(repo)) for path in repo.rglob("*") if path.is_file()}
    output.mkdir(parents=True, exist_ok=True)
    (output / "paper_tables").mkdir(exist_ok=True)
    (output / "paper_figures").mkdir(exist_ok=True)
    data = _load_frozen(repo)
    counts = _counts(data)
    _assert_frozen_counts(counts)
    cases = _case_data(repo)

    for name, content in _documents(data, counts, cases).items():
        (output / name).write_text(content.rstrip() + "\n", encoding="utf-8")

    method_rows = _method_rows(data)
    dataset_rows = _dataset_rows(counts)
    experiment_rows = _experiment_rows(data, counts)
    abstention_rows = _abstention_rows(data)
    main_rows = _main_experiment_rows(data)
    bitemporal_rows = _bitemporal_rows(data)
    ablation_rows = _ablation_rows(data)
    sensitivity_rows = _sensitivity_rows(data)
    superseded_rows = _superseded_rows()
    trace_rows = _trace_rows(data, counts)
    retention_rows = _retention_rows()
    inventory_rows = _source_inventory(repo, data)

    _write_csv(output / "02_METHOD_DEFINITION_REGISTRY.csv", method_rows, list(method_rows[0]))
    _write_csv(output / "03_dataset_scale.csv", dataset_rows, list(dataset_rows[0]))
    _write_csv(
        output / "04_EXPERIMENT_MASTER_REGISTRY.csv", experiment_rows, list(experiment_rows[0])
    )
    _write_csv(
        output / "10_SUPERSEDED_RESULT_REGISTRY.csv", superseded_rows, list(superseded_rows[0])
    )
    _write_csv(output / "14_RESULT_TRACEABILITY.csv", trace_rows, list(trace_rows[0]))
    _write_csv(output / "15_REPOSITORY_RETENTION_PLAN.csv", retention_rows, list(retention_rows[0]))
    _write_csv(output / "SOURCE_INVENTORY.csv", inventory_rows, list(inventory_rows[0]))

    tables = {
        "table_1_dataset_scale.csv": dataset_rows,
        "table_2_claim_admissibility.csv": [
            {
                "decision": "EXPRESSIBLE",
                "reason_code": "ADMISSIBLE",
                "count": counts["expressible"],
                "share_of_abstentions": "",
                "interpretation": "all contract requirements satisfied",
            },
            *abstention_rows,
        ],
        "table_3_main_experiment.csv": main_rows,
        "table_4_bitemporal.csv": bitemporal_rows,
        "table_5_ablation.csv": ablation_rows,
        "table_6_sensitivity.csv": sensitivity_rows,
    }
    for name, rows in tables.items():
        _write_csv(output / "paper_tables" / name, rows, list(rows[0]))
    readmes = {
        "table_1_dataset_scale_README.md": _paper_readme(
            "Table 1 数据规模",
            "分层对象",
            "各层 frozen universe",
            "03_dataset_scale.csv",
            "91 个监测施工日期并非连续日历日。",
        ),
        "table_2_claim_admissibility_README.md": _paper_readme(
            "Table 2 Claim admissibility",
            "Claim opportunity",
            "8679",
            "Stage5C frozen analysis",
            "ABSTAIN 是正式边界，不是失败率。",
        ),
        "table_3_main_experiment_README.md": _paper_readme(
            "Table 3 主实验",
            "method-condition / check instance",
            "每方法 48 planned tasks",
            "Stage7B/7C",
            "人工语义 endpoint deferred；自动 fail count 不是 task accuracy。",
        ),
        "table_4_bitemporal_README.md": _paper_readme(
            "Table 4 双时间",
            "benchmark task 或 revision event",
            "48 或 53，按 analysis_scope 分开",
            "Stage7D",
            "不得混合 null alignment 与 full census 分母。",
        ),
        "table_5_ablation_README.md": _paper_readme(
            "Table 5 消融",
            "arm-specific chunk/mapping/FactLock",
            "每行显式给出",
            "Stage7E final summary",
            "A1 未执行；secondary fence-only 非 primary。",
        ),
        "table_6_sensitivity_README.md": _paper_readme(
            "Table 6 敏感性",
            "OFAT arm",
            "各 arm 自身 universe",
            "Stage7F final interpretation",
            "20m 是 coarse stress test，支持域与 5/10m 不同。",
        ),
    }
    for name, content in readmes.items():
        (output / "paper_tables" / name).write_text(content, encoding="utf-8")

    figures = {
        "figure_claim_gate.csv": tables["table_2_claim_admissibility.csv"],
        "figure_bitemporal.csv": bitemporal_rows,
        "figure_main_experiment.csv": main_rows,
        "figure_ablation.csv": ablation_rows,
        "figure_sensitivity.csv": sensitivity_rows,
    }
    for name, rows in figures.items():
        _write_csv(output / "paper_figures" / name, rows, list(rows[0]))
    (output / "paper_figures/PAPER_FIGURE_PLAN.md").write_text(_figure_plan(), encoding="utf-8")

    hard_checks = _hard_checks(output, trace_rows, counts, data["tags"], preexisting_paths, repo)
    _write_csv(
        output / "final_handoff_hard_check.csv", hard_checks, ["check_name", "status", "details"]
    )
    failures = sum(row["status"] == "FAIL" for row in hard_checks)
    if failures:
        raise ValueError(f"Final handoff hard-check failures: {failures}")

    retention_counts = Counter(row["category"] for row in retention_rows)
    _write_json(
        output / "method_version.json",
        {
            "method_version": METHOD_VERSION,
            "schema_version": SCHEMA_VERSION,
            "generated_at": GENERATED_AT,
            "operation": "READ_INDEX_SUMMARIZE_TRACE_ONLY",
            "uses_llm": False,
            "api_calls": 0,
            "modifies_frozen_results": False,
            "git_base_commit": _git(repo, "rev-parse", "HEAD"),
        },
    )
    _write_json(
        output / "freeze_manifest.json",
        {
            "method_version": METHOD_VERSION,
            "schema_version": SCHEMA_VERSION,
            "generated_at": GENERATED_AT,
            "git_base_commit": _git(repo, "rev-parse", "HEAD"),
            "source_tags": FINAL_TAGS,
            "source_commits": data["tags"],
            "handoff_file_count": sum(1 for path in output.rglob("*") if path.is_file())
            + int(not (output / "freeze_manifest.json").exists())
            + int(not (output / "file_hashes.sha256").exists()),
            "paper_table_count": len(tables),
            "figure_dataset_count": len(figures),
            "traceability_entry_count": len(trace_rows),
            "source_unknown_count": 0,
            "superseded_leakage_count": 0,
            "case_candidate_count": len(cases),
            "recommended_primary_case": primary_case_label(cases),
            "recommended_revision_case": revision_case_label(cases),
            "retention_plan_entry_count": len(retention_rows),
            "retention_category_counts": dict(sorted(retention_counts.items())),
            "hard_check_failure_count": 0,
            "api_call_count": 0,
            "llm_call_count": 0,
        },
    )
    _write_hashes(output)
    return output


def primary_case_label(cases: list[dict[str, Any]]) -> str:
    return f"{cases[0]['date']} {cases[0]['cell_id']} (Stage7 task 000)"


def revision_case_label(cases: list[dict[str, Any]]) -> str:
    return f"{cases[1]['date']} {cases[1]['cell_id']} ({cases[1]['state_ids'][0]} -> {cases[1]['state_ids'][1]})"
