# ruff: noqa: RUF001

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from tbm_twin.evaluation.stage7c_human_eval import (
    BATCH_CAPACITIES,
    EXPECTED_NO_OUTPUT_TASKS,
    MINIMUM_SAME_TASK_GAP_TARGET,
    RATING_FIELDS,
    build_human_evaluation_packet,
)


@pytest.fixture(scope="module")
def built_packet(tmp_path_factory: pytest.TempPathFactory) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    output = tmp_path_factory.mktemp("stage7c-human-v1-1") / "artifact"
    build_human_evaluation_packet(repo_root, output, write_audit_zip=False)
    return output


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_formal_counts_and_no_output_denominator_are_frozen(built_packet: Path) -> None:
    master = _read_csv(built_packet / "human_eval_master_internal.csv")
    no_output = _read_csv(built_packet / "no_output_internal_manifest.csv")
    assert len(master) == 141
    assert Counter(row["method_internal"] for row in master) == {
        "B0_DIRECT_LLM": 48,
        "B1_STRUCTURED_PROMPT_LLM": 48,
        "P_PROPOSED": 45,
    }
    assert len(no_output) == 3
    assert {row["task_id"] for row in no_output} == EXPECTED_NO_OUTPUT_TASKS
    assert all(row["included_in_human_text_packet"] == "false" for row in no_output)
    assert all(row["retained_in_method_task_denominator"] == "true" for row in no_output)


def test_human_fields_exclude_deterministic_numeric_and_spatial_checks(
    built_packet: Path,
) -> None:
    packet = _read_csv(built_packet / "human_eval_packet_A.csv")
    assert len(packet) == 141
    assert "E2_numeric_value_error" not in packet[0]
    assert "E4_spatial_scope_error" not in packet[0]
    assert "numeric_spatial_correctness_score" not in packet[0]
    assert [field for field in packet[0] if field in RATING_FIELDS] == list(RATING_FIELDS)
    assert all(row[field] == "" for row in packet for field in RATING_FIELDS)


def test_context_is_compact_semantic_not_raw_plc_numeric_dump(built_packet: Path) -> None:
    master = _read_csv(built_packet / "human_eval_master_internal.csv")
    contexts = {row["engineering_context"] for row in master}
    raw_dump_tokens = (
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
    assert all(not any(token in context for token in raw_dump_tokens) for context in contexts)
    assert any("可关联施工响应记录" in context for context in contexts)
    assert any("涉及通道" in context for context in contexts)
    assert any("响应证据空间覆盖" in context for context in contexts)


def test_geological_semantics_remain_distinguishable(built_packet: Path) -> None:
    master = _read_csv(built_packet / "human_eval_master_internal.csv")
    combined = "\n".join(row["engineering_context"] for row in master)
    for required in (
        "当前可获得的地质预测资料",
        "当前可获得的实际地质观察资料",
        "来源类型",
        "认识性质：预测",
        "认识性质：实际观察",
        "使用角色",
        "可用日期",
        "空间范围",
        "岩性",
        "水状态类型",
    ):
        assert required in combined


def test_metric_statuses_and_quality_flags_are_humanized(built_packet: Path) -> None:
    master = _read_csv(built_packet / "human_eval_master_internal.csv")
    combined = "\n".join(row["engineering_context"] for row in master)
    for internal in (
        "GRCI_NOT_DEFINED_FOR_FORWARD_ATTENTION",
        "GRCI_NOT_DEFINED_FOR_LOCAL_BACKGROUND",
        "NO_CELL_LINKED_OPERATIONAL_RESPONSE",
        "NO_MAPPED_GEOLOGICAL_ATTENTION_DIMENSION",
        "RAI_UNAVAILABLE",
        "INSUFFICIENT_CAUSAL_BASELINE",
        "UNIT_UNVERIFIED",
        "LOW_TEMPORAL_COVERAGE",
    ):
        assert internal not in combined
    assert "前方关注场景不定义机械—地质联合关注指标" in combined
    assert "单位尚未核验" in combined


def test_same_task_uses_same_exact_asof_method_neutral_context(built_packet: Path) -> None:
    master = _read_csv(built_packet / "human_eval_master_internal.csv")
    contexts: dict[str, set[str]] = defaultdict(set)
    for row in master:
        contexts[row["task_id_internal"]].add(row["authoritative_context_hash"])
        context = row["engineering_context"]
        assert "ClaimDecision" not in context
        assert "FactLock" not in context
        assert "EXPRESSIBLE" not in context
        assert "ABSTAIN" not in context
        assert "没有提供某项记录，不表示该工程现象未发生" in context
    assert len(contexts) == 48
    assert all(len(values) == 1 for values in contexts.values())
    leak = _read_csv(built_packet / "system_context_identity_leak_audit.csv")
    assert all(row["status"] == "PASS" for row in leak)


def test_packets_have_six_fixed_batches_with_no_same_task_in_batch(
    built_packet: Path,
) -> None:
    master = _read_csv(built_packet / "human_eval_master_internal.csv")
    task_by_item = {row["annotation_item_id"]: row["task_id_internal"] for row in master}
    for packet_name in ("A", "B"):
        concatenated = []
        for batch_index, capacity in enumerate(BATCH_CAPACITIES, 1):
            batch = _read_csv(
                built_packet / f"human_eval_packet_{packet_name}_batch_{batch_index:02d}.csv"
            )
            assert len(batch) == capacity
            task_ids = [task_by_item[row["annotation_item_id"]] for row in batch]
            assert len(task_ids) == len(set(task_ids))
            concatenated.extend(batch)
        canonical = _read_csv(built_packet / f"human_eval_packet_{packet_name}.csv")
        assert concatenated == canonical


def test_carryover_minimum_gap_and_adjacency_contract(built_packet: Path) -> None:
    audit = _read_csv(built_packet / "packet_carryover_audit.csv")
    assert len(audit) == 96
    for packet_name in ("A", "B"):
        rows = [row for row in audit if row["packet"] == packet_name]
        assert sum(int(row["same_batch_pair_count"]) for row in rows) == 0
        assert sum(int(row["adjacent_pair_count"]) for row in rows) == 0
        assert min(int(row["minimum_gap"]) for row in rows) >= MINIMUM_SAME_TASK_GAP_TARGET


def test_constrained_randomization_is_deterministic_and_a_b_differ(
    built_packet: Path, tmp_path: Path
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    rebuilt = tmp_path / "rebuilt"
    build_human_evaluation_packet(repo_root, rebuilt, write_audit_zip=False)
    compared = [
        "human_eval_packet_A.csv",
        "human_eval_packet_B.csv",
        "packet_carryover_audit.csv",
        "batch_assignment_summary.json",
    ] + [
        f"human_eval_packet_{packet}_batch_{index:02d}.csv"
        for packet in ("A", "B")
        for index in range(1, 7)
    ]
    assert all(_sha256(built_packet / name) == _sha256(rebuilt / name) for name in compared)
    packet_a = _read_csv(built_packet / "human_eval_packet_A.csv")
    packet_b = _read_csv(built_packet / "human_eval_packet_B.csv")
    assert [row["annotation_item_id"] for row in packet_a] != [
        row["annotation_item_id"] for row in packet_b
    ]


def test_stage7a_authoritative_freeze_and_all_git_refs_pass(built_packet: Path) -> None:
    stage7a = _read_csv(built_packet / "stage7a_authoritative_context_freeze_audit.csv")
    refs = _read_csv(built_packet / "frozen_git_ref_audit.csv")
    assert len(stage7a) == 5
    assert all(row["status"] == "PASS" for row in stage7a)
    assert {row["reference"] for row in refs} == {
        "stage7a_tag",
        "stage7b_tag",
        "stage7c1_tag",
        "stage7c2a_v1_tag",
    }
    assert all(row["status"] == "PASS" for row in refs)


def test_frozen_output_cues_are_report_only_and_text_is_unchanged(built_packet: Path) -> None:
    cues = _read_csv(built_packet / "frozen_output_identity_cue_audit.csv")
    identity = _read_csv(built_packet / "generated_text_frozen_identity_audit.csv")
    assert len(cues) == len(identity) == 141
    assert any(row["has_residual_identity_cue"] == "true" for row in cues)
    assert all(row["generated_text_modified"] == "false" for row in cues)
    assert all(row["match"] == "true" for row in identity)
    hard = _read_csv(built_packet / "hard_check.csv")
    assert not any("frozen_output_identity_cue" in row["check_name"] for row in hard)


def test_calibration_has_twelve_training_only_non_main_examples(built_packet: Path) -> None:
    calibration = _read_csv(built_packet / "human_eval_calibration_packet.csv")
    master = _read_csv(built_packet / "human_eval_master_internal.csv")
    assert len(calibration) == 12
    assert all(row["training_only"] == "TRAINING_ONLY" for row in calibration)
    assert {row["generated_text"] for row in calibration}.isdisjoint(
        {row["generated_text"] for row in master}
    )
    assert all(row[field] == "" for row in calibration for field in RATING_FIELDS)


def test_context_workload_is_reduced_without_evidence_truncation(built_packet: Path) -> None:
    comparison = json.loads(
        (built_packet / "context_workload_comparison.json").read_text(encoding="utf-8")
    )
    assert comparison["v1_median_context_characters"] == 5265
    assert comparison["v1_1_median_context_characters"] < 5265
    assert comparison["v1_1_total_context_characters"] < 1_039_806
    assert comparison["context_character_reduction_percentage"] > 0
    assert comparison["evidence_truncation_used"] is False


def test_later_evidence_is_internal_temporally_later_and_not_in_packet(
    built_packet: Path,
) -> None:
    later_key = json.loads(
        (built_packet / "later_evidence_answer_key_internal.json").read_text(encoding="utf-8")
    )
    packet = _read_csv(built_packet / "human_eval_packet_A.csv")
    later_items = [item for row in later_key["rows"] for item in row["later_evidence"]]
    assert len(later_key["rows"]) == 48
    assert later_items
    assert all(
        item["later_available_time"] > row["knowledge_as_of"]
        for row in later_key["rows"]
        for item in row["later_evidence"]
    )
    later_ids = {item["evidence_id"] for item in later_items}
    assert all(
        not any(evidence_id in row["engineering_context"] for evidence_id in later_ids)
        for row in packet
    )


def test_all_hard_checks_pass_and_no_calls_or_rerun(built_packet: Path) -> None:
    hard = _read_csv(built_packet / "hard_check.csv")
    method = json.loads((built_packet / "method_version.json").read_text(encoding="utf-8"))
    assert all(row["status"] == "PASS" for row in hard)
    assert method["api_call_count"] == 0
    assert method["uses_llm"] is False
    assert method["uses_llm_as_judge"] is False
    assert method["stage7b_rerun_count"] == 0
