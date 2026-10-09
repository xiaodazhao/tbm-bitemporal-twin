"""Freeze and analyze the partitioned Stage 7C human ratings."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import re
import shutil
import statistics
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

METHOD_VERSION = "stage7c_partitioned_human_evaluation_v1"
SCHEMA_VERSION = "stage7c_partitioned_human_evaluation.v1"
GENERATED_AT = "2026-09-16T00:00:00+08:00"
BOOTSTRAP_SEED = 2026091601
BOOTSTRAP_ITERATIONS = 10_000

METHODS = ("B0_DIRECT_LLM", "B1_STRUCTURED_PROMPT_LLM", "P_PROPOSED")
METHOD_LABELS = {
    "B0_DIRECT_LLM": "B0 Direct LLM",
    "B1_STRUCTURED_PROMPT_LLM": "B1 Structured-prompt LLM",
    "P_PROPOSED": "P Proposed",
}
SCORE_FIELDS = {
    "事实支持": "factual_support",
    "认识区分": "epistemic_distinction",
    "内容完整": "content_completeness",
    "清晰实用": "clarity_usability",
}
ERROR_VALUES = {"有": "YES", "无": "NO", "无法判断": "UNDETERMINED"}
EXPECTED_METHOD_COUNTS = {
    "B0_DIRECT_LLM": 48,
    "B1_STRUCTURED_PROMPT_LLM": 48,
    "P_PROPOSED": 45,
}
EXPECTED_REVIEWER_COUNTS = {"R1": 48, "R2": 46, "R3": 47}
REVIEWER_RANGES = {
    "R1": (1, 16, "reviewer_a_combined_source"),
    "R2": (17, 32, "reviewer_a_combined_source"),
    "R3": (33, 48, "reviewer_b_source"),
}


def build_stage7c_human_results(
    repo_root: Path,
    reviewer_a_path: Path,
    reviewer_b_path: Path,
    mapping_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Build a read-only analysis artifact from the three partitioned reviewers."""

    root = repo_root.resolve()
    output = output_dir if output_dir.is_absolute() else root / output_dir
    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / "raw_inputs"
    raw_dir.mkdir(exist_ok=True)

    source_paths = {
        "reviewer_a_combined_source": reviewer_a_path.resolve(),
        "reviewer_b_source": reviewer_b_path.resolve(),
        "anonymous_method_mapping_internal": mapping_path.resolve(),
    }
    copied_paths = {
        key: raw_dir / f"{key}{path.suffix.lower()}" for key, path in source_paths.items()
    }
    for key, source in source_paths.items():
        if not source.exists():
            raise FileNotFoundError(source)
        shutil.copyfile(source, copied_paths[key])

    source_hashes = {key: _sha256(path) for key, path in source_paths.items()}
    copy_hashes = {key: _sha256(path) for key, path in copied_paths.items()}
    if source_hashes != copy_hashes:
        raise ValueError("Raw input copy hash mismatch")

    mapping_rows = _read_csv(mapping_path)
    mapping_by_output = {row["display_output_id"]: row for row in mapping_rows}
    if len(mapping_by_output) != len(mapping_rows):
        raise ValueError("Duplicate display output IDs in mapping")

    reviewer_a_rows = _read_csv(reviewer_a_path)
    reviewer_b_rows = _read_csv(reviewer_b_path)
    long_rows = _normalize_ratings(reviewer_a_rows, reviewer_b_rows, mapping_by_output)
    hard_rows = _hard_checks(long_rows, source_hashes, copy_hashes)
    hard_issues = [row for row in hard_rows if row["status"] != "PASS"]
    if hard_issues:
        raise ValueError(f"Human rating hard checks failed: {hard_issues}")

    assignment_rows = _reviewer_assignment_rows(long_rows)
    reviewer_summary = _reviewer_method_summary(long_rows)
    method_summary = _method_score_summary(long_rows)
    paired_rows = _paired_score_comparisons(long_rows)
    friedman_rows = _friedman_rows(long_rows)
    error_summary = _explicit_error_summary(long_rows)
    error_pair_rows = _paired_error_comparisons(long_rows)
    error_cases = [row for row in long_rows if row["explicit_error"] == "YES"]
    protocol_rows = _protocol_deviation_rows()
    paper_rows = _paper_table_rows(method_summary, error_summary)

    _write_csv(output / "human_ratings_long.csv", long_rows)
    _write_csv(output / "reviewer_assignment_manifest.csv", assignment_rows)
    _write_csv(output / "reviewer_method_summary.csv", reviewer_summary)
    _write_csv(output / "method_score_summary.csv", method_summary)
    _write_csv(output / "paired_score_comparisons.csv", paired_rows)
    _write_csv(output / "friedman_omnibus.csv", friedman_rows)
    _write_csv(output / "explicit_error_summary.csv", error_summary)
    _write_csv(output / "paired_error_comparisons.csv", error_pair_rows)
    _write_csv(output / "explicit_error_cases.csv", error_cases)
    _write_csv(output / "protocol_deviation_audit.csv", protocol_rows)
    _write_csv(output / "stage7c_human_results_hard_check.csv", hard_rows)
    _write_csv(output / "paper_table_human_evaluation.csv", paper_rows)

    git_commit = _git_output(root, ["git", "rev-parse", "HEAD"])
    git_status = _git_output(root, ["git", "status", "--short"])
    method_version = {
        "bootstrap_iterations": BOOTSTRAP_ITERATIONS,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "generated_at": GENERATED_AT,
        "git_commit_hash": git_commit,
        "method_version": METHOD_VERSION,
        "rating_design": "THREE_REVIEWER_DISJOINT_TASK_PARTITIONS_WITHIN_TASK_PAIRED_METHODS",
        "schema_version": SCHEMA_VERSION,
        "working_tree_dirty": bool(git_status),
    }
    _write_json(output / "method_version.json", method_version)

    report = _freeze_report(
        long_rows,
        method_summary,
        reviewer_summary,
        paired_rows,
        friedman_rows,
        error_summary,
        protocol_rows,
    )
    (output / "human_evaluation_freeze_report.md").write_text(report, encoding="utf-8")

    manifest = {
        "artifact_dir": str(output.relative_to(root))
        if output.is_relative_to(root)
        else str(output),
        "explicit_error_count": sum(row["explicit_error"] == "YES" for row in long_rows),
        "generated_at": GENERATED_AT,
        "input_hashes": source_hashes,
        "method_counts": dict(Counter(row["method_internal"] for row in long_rows)),
        "method_version": METHOD_VERSION,
        "output_rating_count": len(long_rows),
        "reviewer_counts": dict(Counter(row["reviewer_id"] for row in long_rows)),
        "reviewer_count": 3,
        "schema_version": SCHEMA_VERSION,
        "task_count": len({row["task_number"] for row in long_rows}),
        "text_output_denominator": 141,
        "total_task_denominator": 48,
    }
    _write_json(output / "freeze_manifest.json", manifest)
    _write_hash_manifest(output)

    return {
        "artifact_dir": str(output),
        "hard_issue_count": 0,
        "rating_count": len(long_rows),
        "reviewer_count": 3,
        "task_count": 48,
    }


def _normalize_ratings(
    reviewer_a_rows: list[dict[str, str]],
    reviewer_b_rows: list[dict[str, str]],
    mapping_by_output: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    sources = {
        "reviewer_a_combined_source": reviewer_a_rows,
        "reviewer_b_source": reviewer_b_rows,
    }
    seen: set[str] = set()
    for reviewer_id, (start, end, source_key) in REVIEWER_RANGES.items():
        for source_row_number, row in enumerate(sources[source_key], start=2):
            task_number = _task_number(row.get("任务编号", ""))
            if task_number is None or not start <= task_number <= end:
                continue
            required_values = [row.get(field, "").strip() for field in SCORE_FIELDS]
            required_values.append(row.get("明确错误", "").strip())
            if not any(required_values):
                continue
            if not all(required_values):
                raise ValueError(f"Partial rating row: {row.get('文本编号', '')}")
            output_id = row["文本编号"].strip()
            if output_id in seen:
                raise ValueError(f"Duplicate rated output: {output_id}")
            seen.add(output_id)
            mapping = mapping_by_output.get(output_id)
            if mapping is None:
                raise ValueError(f"Missing method mapping for {output_id}")
            scores: dict[str, str] = {}
            for source_field, normalized_field in SCORE_FIELDS.items():
                value = row[source_field].strip()
                if value not in {"1", "2", "3", "4", "5"}:
                    raise ValueError(f"Invalid score {output_id} {source_field}: {value}")
                scores[normalized_field] = value
            error_value = row["明确错误"].strip()
            if error_value not in ERROR_VALUES:
                raise ValueError(f"Invalid error status {output_id}: {error_value}")
            rows.append(
                {
                    "reviewer_id": reviewer_id,
                    "task_number": str(task_number),
                    "display_task": row["任务编号"].strip(),
                    "display_output_id": output_id,
                    "task_id_internal": mapping["task_id_internal"],
                    "anonymous_text_id": mapping["anonymous_text_id"],
                    "method_internal": mapping["method_internal"],
                    "product_type_internal": mapping["product_type_internal"],
                    "valid_date": mapping["valid_date"],
                    "knowledge_as_of": mapping["knowledge_as_of"],
                    **scores,
                    "explicit_error": ERROR_VALUES[error_value],
                    "error_quote": row.get("错误原句", "").strip(),
                    "error_reason": row.get("错误说明", "").strip(),
                    "other_note": row.get("其他备注", "").strip(),
                    "source_file_key": source_key,
                    "source_row_number": str(source_row_number),
                    "generated_text_hash": mapping["generated_text_hash"],
                }
            )
    rows.sort(key=lambda row: (int(row["task_number"]), row["display_output_id"]))
    return rows


def _hard_checks(
    rows: list[dict[str, str]],
    source_hashes: dict[str, str],
    copy_hashes: dict[str, str],
) -> list[dict[str, str]]:
    method_counts = Counter(row["method_internal"] for row in rows)
    reviewer_counts = Counter(row["reviewer_id"] for row in rows)
    task_reviewers: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        task_reviewers[row["task_number"]].add(row["reviewer_id"])
    checks = {
        "raw_input_copy_hashes_match": source_hashes == copy_hashes,
        "rating_row_count_is_141": len(rows) == 141,
        "rated_output_ids_are_unique": len({row["display_output_id"] for row in rows}) == 141,
        "task_count_is_48": len(task_reviewers) == 48,
        "each_task_has_one_reviewer": all(len(values) == 1 for values in task_reviewers.values()),
        "method_counts_match_frozen_outputs": dict(method_counts) == EXPECTED_METHOD_COUNTS,
        "reviewer_partition_counts_match": dict(reviewer_counts) == EXPECTED_REVIEWER_COUNTS,
        "all_scores_in_range": all(
            row[field] in {"1", "2", "3", "4", "5"}
            for row in rows
            for field in SCORE_FIELDS.values()
        ),
        "all_error_statuses_valid": all(
            row["explicit_error"] in {"YES", "NO", "UNDETERMINED"} for row in rows
        ),
    }
    return [
        {
            "check_name": name,
            "status": "PASS" if status else "FAIL",
            "details": "",
        }
        for name, status in checks.items()
    ]


def _reviewer_assignment_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for reviewer_id, (start, end, source_key) in REVIEWER_RANGES.items():
        selected = [row for row in rows if row["reviewer_id"] == reviewer_id]
        result.append(
            {
                "reviewer_id": reviewer_id,
                "task_start": str(start),
                "task_end": str(end),
                "task_count": str(len({row["task_number"] for row in selected})),
                "rated_text_count": str(len(selected)),
                "source_file_key": source_key,
                "overlap_with_other_reviewers": "0",
                "rating_design": "DISJOINT_TASK_PARTITION_WITHIN_TASK_PAIRED_METHODS",
            }
        )
    return result


def _reviewer_method_summary(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for reviewer_id in REVIEWER_RANGES:
        for method in METHODS:
            selected = [
                row
                for row in rows
                if row["reviewer_id"] == reviewer_id and row["method_internal"] == method
            ]
            result.append(_summary_row(selected, method, reviewer_id))
    return result


def _method_score_summary(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for method_index, method in enumerate(METHODS):
        selected = [row for row in rows if row["method_internal"] == method]
        base = {
            "method_internal": method,
            "method_label": METHOD_LABELS[method],
            "rated_text_count": str(len(selected)),
            "task_denominator": "48",
            "output_rate": _fmt(len(selected) / 48),
        }
        for field_index, normalized_field in enumerate(SCORE_FIELDS.values()):
            values = [float(row[normalized_field]) for row in selected]
            stats = _descriptive_stats(values)
            low, high = _bootstrap_mean_ci(
                values,
                BOOTSTRAP_SEED + method_index * 100 + field_index,
            )
            prefix = normalized_field
            base.update(
                {
                    f"{prefix}_mean": _fmt(stats["mean"]),
                    f"{prefix}_sd": _fmt(stats["sd"]),
                    f"{prefix}_median": _fmt(stats["median"]),
                    f"{prefix}_q1": _fmt(stats["q1"]),
                    f"{prefix}_q3": _fmt(stats["q3"]),
                    f"{prefix}_mean_ci95_low": _fmt(low),
                    f"{prefix}_mean_ci95_high": _fmt(high),
                }
            )
        result.append(base)
    return result


def _summary_row(rows: list[dict[str, str]], method: str, reviewer_id: str) -> dict[str, str]:
    result = {
        "reviewer_id": reviewer_id,
        "method_internal": method,
        "method_label": METHOD_LABELS[method],
        "rated_text_count": str(len(rows)),
        "explicit_error_yes": str(sum(row["explicit_error"] == "YES" for row in rows)),
        "explicit_error_no": str(sum(row["explicit_error"] == "NO" for row in rows)),
        "explicit_error_undetermined": str(
            sum(row["explicit_error"] == "UNDETERMINED" for row in rows)
        ),
    }
    for normalized_field in SCORE_FIELDS.values():
        values = [float(row[normalized_field]) for row in rows]
        result[f"{normalized_field}_mean"] = _fmt(statistics.fmean(values))
    return result


def _paired_score_comparisons(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_task: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        by_task[row["task_number"]][row["method_internal"]] = row
    result: list[dict[str, str]] = []
    pairs = ((METHODS[0], METHODS[1]), (METHODS[0], METHODS[2]), (METHODS[1], METHODS[2]))
    for field_index, field in enumerate(SCORE_FIELDS.values()):
        field_rows: list[dict[str, str]] = []
        for pair_index, (method_a, method_b) in enumerate(pairs):
            differences = [
                float(method_rows[method_a][field]) - float(method_rows[method_b][field])
                for method_rows in by_task.values()
                if method_a in method_rows and method_b in method_rows
            ]
            ci_low, ci_high = _bootstrap_mean_ci(
                differences,
                BOOTSTRAP_SEED + 1000 + field_index * 100 + pair_index,
            )
            p_value, rank_biserial = _wilcoxon_exact(differences)
            field_rows.append(
                {
                    "score_dimension": field,
                    "method_a": method_a,
                    "method_b": method_b,
                    "paired_task_count": str(len(differences)),
                    "mean_difference_a_minus_b": _fmt(statistics.fmean(differences)),
                    "mean_difference_ci95_low": _fmt(ci_low),
                    "mean_difference_ci95_high": _fmt(ci_high),
                    "a_higher_count": str(sum(value > 0 for value in differences)),
                    "tie_count": str(sum(value == 0 for value in differences)),
                    "a_lower_count": str(sum(value < 0 for value in differences)),
                    "wilcoxon_exact_p": _fmt_p(p_value),
                    "rank_biserial_effect": _fmt(rank_biserial),
                    "holm_adjusted_p": "",
                }
            )
        adjusted = _holm_adjust([float(row["wilcoxon_exact_p"]) for row in field_rows])
        for row, value in zip(field_rows, adjusted, strict=True):
            row["holm_adjusted_p"] = _fmt_p(value)
        result.extend(field_rows)
    return result


def _friedman_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_task: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        by_task[row["task_number"]][row["method_internal"]] = row
    result: list[dict[str, str]] = []
    for field in SCORE_FIELDS.values():
        blocks = [
            [float(method_rows[method][field]) for method in METHODS]
            for method_rows in by_task.values()
            if all(method in method_rows for method in METHODS)
        ]
        statistic, p_value, kendalls_w = _friedman(blocks)
        result.append(
            {
                "score_dimension": field,
                "complete_task_count": str(len(blocks)),
                "friedman_chi_square": _fmt(statistic),
                "degrees_of_freedom": "2",
                "p_value": _fmt_p(p_value),
                "kendalls_w": _fmt(kendalls_w),
            }
        )
    return result


def _explicit_error_summary(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for method in METHODS:
        selected = [row for row in rows if row["method_internal"] == method]
        counts = Counter(row["explicit_error"] for row in selected)
        determinate = counts["YES"] + counts["NO"]
        result.append(
            {
                "method_internal": method,
                "method_label": METHOD_LABELS[method],
                "rated_text_count": str(len(selected)),
                "task_denominator": "48",
                "output_rate": _fmt(len(selected) / 48),
                "error_yes": str(counts["YES"]),
                "error_no": str(counts["NO"]),
                "error_undetermined": str(counts["UNDETERMINED"]),
                "determinate_count": str(determinate),
                "error_rate_among_all_rated": _fmt(counts["YES"] / len(selected)),
                "error_rate_among_determinate": _fmt(
                    counts["YES"] / determinate if determinate else 0.0
                ),
            }
        )
    return result


def _paired_error_comparisons(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_task: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        by_task[row["task_number"]][row["method_internal"]] = row
    pairs = ((METHODS[0], METHODS[1]), (METHODS[0], METHODS[2]), (METHODS[1], METHODS[2]))
    result: list[dict[str, str]] = []
    for pair_index, (method_a, method_b) in enumerate(pairs):
        determinate_pairs: list[tuple[int, int]] = []
        excluded = 0
        for method_rows in by_task.values():
            if method_a not in method_rows or method_b not in method_rows:
                continue
            status_a = method_rows[method_a]["explicit_error"]
            status_b = method_rows[method_b]["explicit_error"]
            if "UNDETERMINED" in {status_a, status_b}:
                excluded += 1
                continue
            determinate_pairs.append((int(status_a == "YES"), int(status_b == "YES")))
        a_yes_b_no = sum(a == 1 and b == 0 for a, b in determinate_pairs)
        a_no_b_yes = sum(a == 0 and b == 1 for a, b in determinate_pairs)
        differences = [float(a - b) for a, b in determinate_pairs]
        ci_low, ci_high = _bootstrap_mean_ci(
            differences,
            BOOTSTRAP_SEED + 2000 + pair_index,
        )
        result.append(
            {
                "method_a": method_a,
                "method_b": method_b,
                "determinate_paired_task_count": str(len(determinate_pairs)),
                "excluded_undetermined_count": str(excluded),
                "a_error_b_no_error": str(a_yes_b_no),
                "a_no_error_b_error": str(a_no_b_yes),
                "paired_error_rate_difference_a_minus_b": _fmt(
                    statistics.fmean(differences) if differences else 0.0
                ),
                "difference_ci95_low": _fmt(ci_low),
                "difference_ci95_high": _fmt(ci_high),
                "mcnemar_exact_p": _fmt_p(_mcnemar_exact(a_yes_b_no, a_no_b_yes)),
                "holm_adjusted_p": "",
            }
        )
    adjusted = _holm_adjust([float(row["mcnemar_exact_p"]) for row in result])
    for row, value in zip(result, adjusted, strict=True):
        row["holm_adjusted_p"] = _fmt_p(value)
    return result


def _protocol_deviation_rows() -> list[dict[str, str]]:
    return [
        {
            "item": "annotator_count",
            "frozen_protocol": "2",
            "actual_execution": "3",
            "classification": "DOCUMENTED_PROTOCOL_DEVIATION",
            "consequence": "Actual reviewer count is higher, but workloads are partitioned.",
        },
        {
            "item": "rating_overlap",
            "frozen_protocol": "Each annotator rates all 141 texts",
            "actual_execution": "Three disjoint 16-task partitions; one reviewer per task",
            "classification": "DOCUMENTED_PROTOCOL_DEVIATION",
            "consequence": "Inter-rater reliability is not estimable.",
        },
        {
            "item": "comparison_unit",
            "frozen_protocol": "Same-task method comparison",
            "actual_execution": "Preserved within every assigned task",
            "classification": "PRESERVED",
            "consequence": "Within-task paired method comparisons remain valid.",
        },
        {
            "item": "formal_rating_schema",
            "frozen_protocol": "Detailed semantic-error taxonomy plus Likert fields",
            "actual_execution": "Four 1-5 dimensions plus explicit error tri-state",
            "classification": "DOCUMENTED_PROTOCOL_DEVIATION",
            "consequence": "Analysis is limited to the fields actually collected.",
        },
        {
            "item": "calibration_completion",
            "frozen_protocol": "12 TRAINING_ONLY calibration items per annotator",
            "actual_execution": "NOT_DOCUMENTED",
            "classification": "LIMITATION",
            "consequence": "Calibration adherence cannot be claimed.",
        },
        {
            "item": "reviewer_qualification_metadata",
            "frozen_protocol": "Record engineering-related background and conflicts",
            "actual_execution": "NOT_DOCUMENTED_IN_RATING_FILES",
            "classification": "LIMITATION",
            "consequence": (
                "Paper must describe only qualifications that can be separately verified."
            ),
        },
    ]


def _paper_table_rows(
    method_summary: list[dict[str, str]],
    error_summary: list[dict[str, str]],
) -> list[dict[str, str]]:
    errors = {row["method_internal"]: row for row in error_summary}
    result: list[dict[str, str]] = []
    for row in method_summary:
        method = row["method_internal"]
        error = errors[method]
        result.append(
            {
                "method": row["method_label"],
                "outputs_over_48_tasks": f"{row['rated_text_count']}/48",
                "factual_support_mean_ci95": _mean_ci_cell(row, "factual_support"),
                "epistemic_distinction_mean_ci95": _mean_ci_cell(row, "epistemic_distinction"),
                "content_completeness_mean_ci95": _mean_ci_cell(row, "content_completeness"),
                "clarity_usability_mean_ci95": _mean_ci_cell(row, "clarity_usability"),
                "explicit_error_yes_over_rated": (
                    f"{error['error_yes']}/{error['rated_text_count']}"
                ),
                "undetermined_error_judgments": error["error_undetermined"],
            }
        )
    return result


def _mean_ci_cell(row: dict[str, str], field: str) -> str:
    return (
        f"{float(row[f'{field}_mean']):.2f} "
        f"[{float(row[f'{field}_mean_ci95_low']):.2f}, "
        f"{float(row[f'{field}_mean_ci95_high']):.2f}]"
    )


def _freeze_report(
    rows: list[dict[str, str]],
    method_summary: list[dict[str, str]],
    reviewer_summary: list[dict[str, str]],
    paired_rows: list[dict[str, str]],
    friedman_rows: list[dict[str, str]],
    error_summary: list[dict[str, str]],
    protocol_rows: list[dict[str, str]],
) -> str:
    method_by_id = {row["method_internal"]: row for row in method_summary}
    error_by_id = {row["method_internal"]: row for row in error_summary}
    lines = [
        "# Stage7C Partitioned Human Evaluation Freeze Report",
        "",
        "## Execution identity",
        "",
        f"- Method version: `{METHOD_VERSION}`",
        f"- Rated texts: {len(rows)}/141",
        "- Benchmark tasks: 48",
        "- Human reviewers: 3",
        "- Assignment: R1 tasks 1-16; R2 tasks 17-32; R3 tasks 33-48",
        "- Design: disjoint task partitions with within-task paired method ratings",
        "- AI ratings are not included in the primary human analysis.",
        "",
        "## Primary descriptive results",
        "",
        (
            "| Method | Outputs | Factual support | Epistemic distinction | "
            "Content completeness | Clarity/usability | Explicit errors |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for method in METHODS:
        summary = method_by_id[method]
        error = error_by_id[method]
        lines.append(
            "| "
            + " | ".join(
                [
                    METHOD_LABELS[method],
                    f"{summary['rated_text_count']}/48",
                    _mean_ci_cell(summary, "factual_support"),
                    _mean_ci_cell(summary, "epistemic_distinction"),
                    _mean_ci_cell(summary, "content_completeness"),
                    _mean_ci_cell(summary, "clarity_usability"),
                    f"{error['error_yes']}/{error['rated_text_count']}",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Means are reported with deterministic task/output bootstrap 95% confidence intervals.",
            "The four dimensions are not collapsed into a single primary score.",
            "",
            "## Statistical analysis",
            "",
            "- Friedman omnibus tests use the 45 tasks with outputs from all three methods.",
            "- Pairwise score comparisons use exact signed-rank tests and Holm correction.",
            "- Explicit-error comparisons exclude UNDETERMINED pairs and use exact McNemar tests.",
            (
                "- P's three validator-intercepted tasks remain in the 48-task "
                "output-rate denominator."
            ),
            "",
            "See `friedman_omnibus.csv`, `paired_score_comparisons.csv`, and "
            "`paired_error_comparisons.csv` for complete statistics.",
            "",
            "## Reviewer-level consistency of direction",
            "",
            "All three reviewers gave P the highest factual-support mean and an "
            "epistemic-distinction "
            "mean of 5.00. All three also gave P lower completeness and/or clarity than the more "
            "fluent baselines. This is directional replication across disjoint task blocks, not "
            "inter-rater reliability.",
            "",
            "## Protocol deviations and limitations",
            "",
        ]
    )
    for row in protocol_rows:
        lines.append(f"- **{row['item']}**: {row['classification']}; {row['consequence']}")
    lines.extend(
        [
            "",
            "Because reviewers rated disjoint task subsets, inter-rater reliability cannot be "
            "estimated. Reviewer severity is partly controlled by the within-task paired design, "
            "but reviewer and task-block effects remain confounded. The result supports "
            "comparative claims about the observed benchmark, not general human agreement "
            "or engineering validity.",
            "",
            "## Interpretation boundary",
            "",
            "The human results support a trade-off: P more consistently preserves factual and "
            "epistemic boundaries, while B0/B1 are generally more complete and fluent. They do not "
            "prove engineering correctness, cross-project generalization, or superiority on every "
            "text-quality dimension.",
            "",
            "## Internal references",
            "",
            f"- Reviewer-method rows: {len(reviewer_summary)}",
            f"- Paired score rows: {len(paired_rows)}",
            f"- Friedman rows: {len(friedman_rows)}",
        ]
    )
    return "\n".join(lines) + "\n"


def _descriptive_stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "mean": statistics.fmean(values),
        "sd": statistics.stdev(values) if len(values) > 1 else 0.0,
        "median": statistics.median(values),
        "q1": _percentile(ordered, 0.25),
        "q3": _percentile(ordered, 0.75),
    }


def _percentile(ordered: list[float], probability: float) -> float:
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _bootstrap_mean_ci(
    values: list[float], seed: int, iterations: int = BOOTSTRAP_ITERATIONS
) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    rng = random.Random(seed)
    size = len(values)
    means = sorted(
        statistics.fmean(values[rng.randrange(size)] for _ in range(size))
        for _ in range(iterations)
    )
    return _percentile(means, 0.025), _percentile(means, 0.975)


def _wilcoxon_exact(differences: list[float]) -> tuple[float, float]:
    nonzero = [value for value in differences if value != 0]
    if not nonzero:
        return 1.0, 0.0
    absolute = [abs(value) for value in nonzero]
    ranks2 = _average_ranks_times_two(absolute)
    observed = sum(rank for rank, value in zip(ranks2, nonzero, strict=True) if value > 0)
    total_rank = sum(ranks2)
    distribution: Counter[int] = Counter({0: 1})
    for rank in ranks2:
        updated: Counter[int] = Counter()
        for score, count in distribution.items():
            updated[score] += count
            updated[score + rank] += count
        distribution = updated
    total_assignments = 2 ** len(ranks2)
    lower = sum(count for score, count in distribution.items() if score <= observed)
    upper = sum(count for score, count in distribution.items() if score >= observed)
    p_value = min(1.0, 2.0 * min(lower, upper) / total_assignments)
    positive = observed
    negative = total_rank - observed
    rank_biserial = (positive - negative) / total_rank
    return p_value, rank_biserial


def _average_ranks_times_two(values: list[float]) -> list[int]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    result = [0] * len(values)
    index = 0
    while index < len(indexed):
        end = index + 1
        while end < len(indexed) and indexed[end][1] == indexed[index][1]:
            end += 1
        first_rank = index + 1
        last_rank = end
        rank_times_two = first_rank + last_rank
        for original_index, _ in indexed[index:end]:
            result[original_index] = rank_times_two
        index = end
    return result


def _friedman(blocks: list[list[float]]) -> tuple[float, float, float]:
    if not blocks:
        return 0.0, 1.0, 0.0
    method_count = len(blocks[0])
    rank_sums = [0.0] * method_count
    tie_sum = 0.0
    for block in blocks:
        ranks = _ranks(block)
        for index, rank in enumerate(ranks):
            rank_sums[index] += rank
        counts = Counter(block)
        tie_sum += sum(count**3 - count for count in counts.values() if count > 1)
    block_count = len(blocks)
    statistic = 12.0 / (block_count * method_count * (method_count + 1)) * sum(
        rank_sum**2 for rank_sum in rank_sums
    ) - 3.0 * block_count * (method_count + 1)
    correction = 1.0 - tie_sum / (block_count * (method_count**3 - method_count))
    if correction > 0:
        statistic /= correction
    p_value = math.exp(-statistic / 2.0)  # Chi-square survival function for df=2.
    kendalls_w = statistic / (block_count * (method_count - 1))
    return statistic, p_value, kendalls_w


def _ranks(values: list[float]) -> list[float]:
    ranks2 = _average_ranks_times_two(values)
    return [rank / 2.0 for rank in ranks2]


def _holm_adjust(p_values: list[float]) -> list[float]:
    order = sorted(range(len(p_values)), key=lambda index: p_values[index])
    adjusted = [0.0] * len(p_values)
    running = 0.0
    count = len(p_values)
    for position, index in enumerate(order):
        value = min(1.0, (count - position) * p_values[index])
        running = max(running, value)
        adjusted[index] = running
    return adjusted


def _mcnemar_exact(a_yes_b_no: int, a_no_b_yes: int) -> float:
    discordant = a_yes_b_no + a_no_b_yes
    if discordant == 0:
        return 1.0
    smaller = min(a_yes_b_no, a_no_b_yes)
    tail = sum(math.comb(discordant, value) for value in range(smaller + 1))
    return float(min(1.0, 2.0 * tail / (2**discordant)))


def _task_number(value: str) -> int | None:
    match = re.search(r"\d+", value)
    return int(match.group()) if match else None


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {str(key): "" if value is None else str(value) for key, value in row.items()}
            for row in reader
        ]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write headerless empty CSV: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_hash_manifest(output: Path) -> None:
    lines = []
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        if path.name == "file_hashes.sha256":
            continue
        lines.append(f"{_sha256(path)}  {path.relative_to(output)}")
    (output / "file_hashes.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _git_output(root: Path, command: list[str]) -> str:
    completed = subprocess.run(command, cwd=root, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def _fmt(value: float) -> str:
    return f"{value:.6f}"


def _fmt_p(value: float) -> str:
    if 0.0 < value < 0.000001:
        return f"{value:.3e}"
    return f"{value:.6f}"
