# ruff: noqa: RUF001
"""Offline evaluation supplements for the paper evidence chain.

This module reads frozen artifacts and prepares additional evaluation material.
It does not rebuild or mutate any frozen pipeline stage.
"""

from __future__ import annotations

import json
import random
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, cast

import pandas as pd
import yaml

from tbm_twin.evaluation.construction_progression_review import (
    build_availability_time_sensitivity,
    build_construction_progression_review,
    write_input_hash_audit,
    write_output_hashes,
    write_paper_experiment_hard_check,
)
from tbm_twin.validation.evaluation import (
    EpisodeEvaluationConfig,
    evaluate_episode_predictions,
    write_episode_evaluation_outputs,
)

DEFAULT_CONFIG = Path("configs/paper_evidence_completion.yaml")
DEFAULT_OUTPUT_DIR = Path("artifacts/paper_evidence_completion_v2")

PLC_DIR = Path("artifacts/stage2_plc_operational_freeze_v2")
GEOLOGY_DIR = Path("artifacts/stage2_geology_v2_freeze_candidate")
METRIC_DIR = Path("artifacts/stage4_bitemporal_state_metrics_v1_1")
CLAIM_ANALYSIS_DIR = Path("artifacts/stage5c_claim_expressibility_analysis_v1")
TEXT_EVAL_DIR = Path("artifacts/stage7c_main_auto_eval_v1_2")
REVISION_DIR = Path("artifacts/stage7d_bitemporal_value_v1_1")

PLC_RAW_COLUMNS = (
    "observation_id",
    "asset_id",
    "source_row_number",
    "timestamp",
    "shield_head_chainage",
    "advance_speed",
    "set_advance_speed",
    "total_thrust",
    "cutterhead_torque",
    "cutterhead_rpm",
    "penetration",
    "daily_advance",
    "cumulative_advance",
)


def build_paper_evidence_completion(
    repo_root: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Build the read-only paper evaluation supplement."""

    repo_root = repo_root.resolve()
    output_dir = _resolve(repo_root, output_dir)
    config = _load_yaml(_resolve(repo_root, config_path))
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    plc_summary = _build_plc_annotation_packet(repo_root, output_dir, config)
    geology_summary = _build_geology_annotation_packet(repo_root, output_dir, config)
    text_summary = _build_text_denominator_audit(repo_root, output_dir)
    rai_summary = build_rai_reason_audit(repo_root, output_dir)
    grci_summary = _build_grci_revision_case(repo_root, output_dir)
    _copy_claim_abstention_matrix(repo_root, output_dir)
    progression_summary = build_construction_progression_review(
        repo_root, output_dir, config["construction_progression_review"]
    )
    availability_summary = build_availability_time_sensitivity(repo_root, output_dir)
    hard_checks = write_paper_experiment_hard_check(
        output_dir, progression_summary, availability_summary
    )
    input_hash_rows = write_input_hash_audit(repo_root, output_dir)

    status_rows = [
        {
            "evaluation_component": "PLC_EPISODE_EXTERNAL_VALIDATION",
            "status": "PENDING_HUMAN_ANNOTATION",
            "available_now": False,
            "details": (
                f"{plc_summary['sample_count']} frozen samples prepared; no accuracy is claimed"
            ),
        },
        {
            "evaluation_component": "GEOLOGICAL_FIELD_EXTERNAL_VALIDATION",
            "status": "PENDING_HUMAN_ANNOTATION",
            "available_now": False,
            "details": (
                f"{geology_summary['sample_count']} frozen evidence samples prepared; "
                "three existing executable manual-Gold documents remain separate"
            ),
        },
        {
            "evaluation_component": "TEXT_EVALUATION_DENOMINATORS",
            "status": "COMPLETE_FROM_FROZEN_ARTIFACTS",
            "available_now": True,
            "details": f"{text_summary['condition_count']} method-task conditions reconciled",
        },
        {
            "evaluation_component": "RAI_AVAILABILITY_REASONS",
            "status": "COMPLETE_FROM_FROZEN_ARTIFACTS",
            "available_now": True,
            "details": (
                f"{rai_summary['available_daily_review_count']}/"
                f"{rai_summary['daily_review_count']} Daily Review states have available RAI"
            ),
        },
        {
            "evaluation_component": "GRCI_REVISION_CASE",
            "status": "COMPLETE_FROM_FROZEN_ARTIFACTS",
            "available_now": True,
            "details": f"revision event {grci_summary['revision_event_id']} exported",
        },
        {
            "evaluation_component": "CONSTRUCTION_PROGRESSION_ASSOCIATION",
            "status": "COMPLETE_FROM_FROZEN_ARTIFACTS",
            "available_now": True,
            "details": (
                f"{progression_summary['strict_same_day_direct_context_count']} strict same-day "
                "direct contexts; no forecast accuracy judgment"
            ),
        },
        {
            "evaluation_component": "AVAILABILITY_TIME_SENSITIVITY",
            "status": "COMPLETE_FROM_FROZEN_ARTIFACTS",
            "available_now": True,
            "details": (
                f"{availability_summary['documented_revision_event_count']} documented revisions "
                "compared with an optimistic same-day counterfactual"
            ),
        },
    ]
    _write_csv(output_dir / "evaluation_completion_status.csv", status_rows)
    summary = {
        "method_version": str(config["method_version"]),
        "frozen_pipeline_modified": False,
        "human_results_fabricated": False,
        "plc_episode_validation": plc_summary,
        "geology_field_validation": geology_summary,
        "text_evaluation": text_summary,
        "rai_availability": rai_summary,
        "grci_revision_case": grci_summary,
        "construction_progression_review": progression_summary,
        "availability_time_sensitivity": availability_summary,
        "paper_experiment_hard_check_fail_count": sum(
            row["status"] != "PASS" for row in hard_checks
        ),
        "frozen_input_file_count": len(input_hash_rows),
    }
    _write_json(output_dir / "summary.json", summary)
    (output_dir / "README.md").write_text(_render_readme(summary), encoding="utf-8")
    write_output_hashes(output_dir)
    return summary


def score_plc_episode_annotations(
    packet_dir: Path,
    annotations_path: Path,
    output_dir: Path,
    *,
    minimum_iou_for_match: float = 0.5,
    boundary_tolerance_seconds: float = 60.0,
) -> dict[str, Any]:
    """Score completed PLC annotations without rebuilding Episode objects."""

    predictions = pd.read_csv(packet_dir / "system_predictions.csv")
    annotations = pd.read_csv(annotations_path)
    completed = annotations[_truthy(annotations["review_complete"])].copy()
    if completed.empty:
        raise ValueError("No completed PLC annotation rows were found")
    required = {"sample_id", "manual_episode_id", "manual_start_time", "manual_end_time"}
    missing = required - set(completed.columns)
    if missing:
        raise ValueError(f"PLC annotations are missing columns: {sorted(missing)}")

    pred = predictions.rename(
        columns={
            "sample_id": "date",
            "excavation_start": "system_start_time",
            "excavation_end": "system_end_time",
        }
    )
    gold = completed.rename(columns={"sample_id": "date"})
    result = evaluate_episode_predictions(
        pred,
        gold,
        EpisodeEvaluationConfig(
            minimum_iou_for_match=minimum_iou_for_match,
            boundary_tolerance_seconds=boundary_tolerance_seconds,
        ),
    )
    pred_by_id = predictions.set_index("system_episode_id").to_dict("index")
    gold_by_id = completed.set_index("manual_episode_id").to_dict("index")
    for match in result["matches"]:
        pred_row = pred_by_id[str(match["prediction_id"])]
        gold_row = gold_by_id[str(match["annotation_id"])]
        match["start_chainage_error_m"] = _absolute_numeric_error(
            pred_row.get("start_chainage"), gold_row.get("manual_start_chainage")
        )
        match["end_chainage_error_m"] = _absolute_numeric_error(
            pred_row.get("end_chainage"), gold_row.get("manual_end_chainage")
        )
    chainage_start = [
        float(row["start_chainage_error_m"])
        for row in result["matches"]
        if row["start_chainage_error_m"] is not None
    ]
    chainage_end = [
        float(row["end_chainage_error_m"])
        for row in result["matches"]
        if row["end_chainage_error_m"] is not None
    ]
    result["metrics"]["mean_start_chainage_error_m"] = _mean(chainage_start)
    result["metrics"]["mean_end_chainage_error_m"] = _mean(chainage_end)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_episode_evaluation_outputs(result, output_dir)
    _write_json(output_dir / "metrics.json", result["metrics"])
    return result


def score_geology_field_annotations(
    annotations_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Score completed long-form geological field annotations."""

    frame = pd.read_csv(annotations_path, keep_default_na=False)
    completed = frame[_truthy(frame["review_complete"])].copy()
    if completed.empty:
        raise ValueError("No completed geological annotation rows were found")
    rows: list[dict[str, Any]] = []
    for field_name, group in completed.groupby("field_name", sort=True):
        exact = [
            _normalize_value(predicted) == _normalize_value(manual)
            for predicted, manual in zip(
                group["predicted_value"], group["manual_value"], strict=True
            )
        ]
        tp = fp = fn = 0
        for predicted, manual in zip(group["predicted_value"], group["manual_value"], strict=True):
            predicted_set = _value_set(predicted)
            manual_set = _value_set(manual)
            tp += len(predicted_set & manual_set)
            fp += len(predicted_set - manual_set)
            fn += len(manual_set - predicted_set)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall
            else None
        )
        rows.append(
            {
                "field_name": field_name,
                "reviewed_count": len(group),
                "exact_match_count": sum(exact),
                "exact_match_rate": sum(exact) / len(group),
                "set_precision": precision,
                "set_recall": recall,
                "set_f1": f1,
            }
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "geology_field_metrics.csv", rows)
    overall = {
        "reviewed_field_count": len(completed),
        "exact_match_count": sum(int(row["exact_match_count"]) for row in rows),
        "exact_match_rate": sum(int(row["exact_match_count"]) for row in rows) / len(completed),
    }
    _write_json(output_dir / "geology_field_metrics.json", overall)
    return overall


def _build_plc_annotation_packet(
    repo_root: Path, output_dir: Path, config: dict[str, Any]
) -> dict[str, Any]:
    packet_dir = output_dir / "plc_episode_annotation"
    raw_dir = packet_dir / "raw_windows"
    raw_dir.mkdir(parents=True)
    plc_dir = repo_root / PLC_DIR
    episodes = _read_jsonl(plc_dir / "excavation_episodes.jsonl")
    footprints = {
        str(row["episode_id"]): row for row in _read_jsonl(plc_dir / "spatial_footprints.jsonl")
    }
    settings = config["plc_episode_validation"]
    selected = _stratified_episode_sample(
        episodes,
        footprints,
        sample_count=int(settings["sample_count"]),
        minimum_per_stratum=int(settings["minimum_per_stratum"]),
        seed=int(config["random_seed"]),
    )
    padding = pd.Timedelta(seconds=float(settings["context_padding_seconds"]))
    parquet_cache: dict[str, pd.DataFrame] = {}
    index_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    annotation_rows: list[dict[str, Any]] = []
    for index, (episode, stratum) in enumerate(selected, start=1):
        sample_id = f"plc_episode_review_{index:03d}"
        target_date = str(episode["target_date"])
        if target_date not in parquet_cache:
            parquet_cache[target_date] = pd.read_parquet(
                plc_dir / "normalized_observations" / f"{target_date}.parquet"
            )
        observations = parquet_cache[target_date]
        timestamps = pd.to_datetime(observations["timestamp"], utc=True)
        start = pd.Timestamp(str(episode["context_start"])) - padding
        end = pd.Timestamp(str(episode["context_end"])) + padding
        window = observations.loc[(timestamps >= start) & (timestamps <= end)].copy()
        available_columns = [column for column in PLC_RAW_COLUMNS if column in window.columns]
        raw_path = raw_dir / f"{sample_id}.csv"
        window[available_columns].to_csv(raw_path, index=False)
        footprint = footprints.get(str(episode["episode_id"]), {})
        index_rows.append(
            {
                "sample_id": sample_id,
                "target_date": target_date,
                "raw_window_path": str(raw_path.relative_to(output_dir)),
                "raw_observation_count": len(window),
                "review_instruction": "Identify all genuine excavation intervals in this window",
            }
        )
        prediction_rows.append(
            {
                "sample_id": sample_id,
                "system_episode_id": episode["episode_id"],
                "selection_stratum": stratum,
                "target_date": target_date,
                "excavation_start": episode["excavation_start"],
                "excavation_end": episode["excavation_end"],
                "boundary_status": episode["boundary_status"],
                "start_chainage": footprint.get("start_chainage"),
                "end_chainage": footprint.get("end_chainage"),
                "quality_grade": episode["quality_grade"],
                "quality_flags": ";".join(episode.get("quality_flags", [])),
            }
        )
        annotation_rows.append(
            {
                "sample_id": sample_id,
                "manual_episode_id": "",
                "is_valid_excavation": "",
                "manual_start_time": "",
                "manual_end_time": "",
                "manual_start_chainage": "",
                "manual_end_chainage": "",
                "manual_boundary_censored": "",
                "review_confidence": "",
                "review_notes": "",
                "review_complete": "",
            }
        )
    _write_csv(packet_dir / "sample_index.csv", index_rows)
    _write_csv(packet_dir / "system_predictions.csv", prediction_rows)
    _write_csv(packet_dir / "annotation_template.csv", annotation_rows)
    (packet_dir / "README.md").write_text(_plc_packet_readme(), encoding="utf-8")
    return {
        "sample_count": len(selected),
        "stratum_distribution": dict(Counter(stratum for _, stratum in selected)),
        "status": "PENDING_HUMAN_ANNOTATION",
    }


def _build_geology_annotation_packet(
    repo_root: Path, output_dir: Path, config: dict[str, Any]
) -> dict[str, Any]:
    packet_dir = output_dir / "geology_field_annotation"
    packet_dir.mkdir(parents=True)
    geology_dir = repo_root / GEOLOGY_DIR
    evidence = _read_jsonl(geology_dir / "primary_geological_evidence.jsonl")
    documents = {
        str(row["document_id"]): row
        for row in _read_jsonl(geology_dir / "geological_documents.jsonl")
    }
    settings = config["geology_field_validation"]
    selected = _stratified_geology_sample(
        evidence,
        samples_per_source_type=int(settings["samples_per_source_type"]),
        seed=int(config["random_seed"]),
    )
    fields = [str(value) for value in settings["fields"]]
    index_rows: list[dict[str, Any]] = []
    annotation_rows: list[dict[str, Any]] = []
    for index, row in enumerate(selected, start=1):
        sample_id = f"geology_review_{index:03d}"
        document = documents[str(row["document_id"])]
        spans = {str(span["span_id"]): span for span in row.get("source_spans", [])}
        index_rows.append(
            {
                "sample_id": sample_id,
                "document_id": row["document_id"],
                "evidence_id": row["evidence_uid"],
                "filename": row["filename"],
                "source_type": row["source_type"],
                "evidence_type": row["evidence_type"],
                "source_pdf_path": document["document"]["source_pdf_path"],
                "source_pages": ";".join(
                    str(value)
                    for value in sorted(
                        {span["page_number"] for span in spans.values() if span["page_number"]}
                    )
                ),
            }
        )
        core_fields: dict[str, Any] = {
            "epistemic_status": row.get("epistemic_status"),
            "spatial_kind": row.get("spatial_scope", {}).get("kind"),
            "start_chainage": row.get("spatial_scope", {}).get("start_chainage"),
            "end_chainage": row.get("spatial_scope", {}).get("end_chainage"),
        }
        attributes = row.get("attributes", {})
        values = {**core_fields, **{field: attributes.get(field) for field in fields}}
        for field_name, predicted in values.items():
            span_ids = _field_span_ids(row, field_name)
            supporting_spans = [spans[span_id] for span_id in span_ids if span_id in spans]
            if field_name in {"spatial_kind", "start_chainage", "end_chainage"}:
                supporting_spans = list(spans.values())
            annotation_rows.append(
                {
                    "sample_id": sample_id,
                    "document_id": row["document_id"],
                    "evidence_id": row["evidence_uid"],
                    "source_type": row["source_type"],
                    "evidence_type": row["evidence_type"],
                    "field_name": field_name,
                    "predicted_value": _json_cell(predicted),
                    "source_span_ids": ";".join(str(span["span_id"]) for span in supporting_spans),
                    "source_pages": ";".join(
                        str(value)
                        for value in sorted({span["page_number"] for span in supporting_spans})
                    ),
                    "source_text": " || ".join(str(span["raw_text"]) for span in supporting_spans),
                    "manual_value": "",
                    "manual_is_supported_by_source": "",
                    "review_confidence": "",
                    "review_notes": "",
                    "review_complete": "",
                }
            )
    _write_csv(packet_dir / "sample_index.csv", index_rows)
    _write_csv(packet_dir / "field_annotation_template.csv", annotation_rows)
    manual_gold_dir = repo_root / "tests/manual_gold/geology"
    inventory = [
        {
            "gold_file": str(path.relative_to(repo_root)),
            "status": "EXISTING_EXECUTABLE_MANUAL_GOLD",
            "scope": "THREE_FIXED_REAL_PDF_REGRESSIONS_NOT_A_CORPUS_ACCURACY_ESTIMATE",
        }
        for path in sorted(manual_gold_dir.glob("*.json"))
    ]
    _write_csv(packet_dir / "existing_manual_gold_inventory.csv", inventory)
    (packet_dir / "README.md").write_text(_geology_packet_readme(), encoding="utf-8")
    return {
        "sample_count": len(selected),
        "field_review_row_count": len(annotation_rows),
        "source_type_distribution": dict(Counter(str(row["source_type"]) for row in selected)),
        "existing_manual_gold_document_count": len(inventory),
        "status": "PENDING_HUMAN_ANNOTATION",
    }


def _build_text_denominator_audit(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    source_dir = repo_root / TEXT_EVAL_DIR
    denominator = json.loads((source_dir / "denominator_contract.json").read_text())
    endpoints = pd.read_csv(source_dir / "automatic_condition_binary_endpoints.csv")
    statements = pd.read_csv(source_dir / "automatic_statement_audit.csv", keep_default_na=False)
    rows: list[dict[str, Any]] = []
    for method, method_endpoints in endpoints.groupby("method_internal", sort=True):
        method_statements = statements[statements["method_internal"] == method]
        output_conditions = method_endpoints[
            method_endpoints["output_status"] == "OUTPUT_AVAILABLE"
        ]["condition_id"].nunique()
        failed = method_statements[method_statements["result"] == "FAIL"]
        rows.append(
            {
                "method": method,
                "task_denominator": method_endpoints["task_id"].nunique(),
                "condition_denominator": method_endpoints["condition_id"].nunique(),
                "actual_text_output_count": output_conditions,
                "no_valid_output_count": method_endpoints["condition_id"].nunique()
                - output_conditions,
                "unique_statement_count": method_statements.loc[
                    method_statements["statement_id"] != "", "statement_id"
                ].nunique(),
                "automatic_check_instance_count": len(
                    method_statements[method_statements["result"].isin(["PASS", "FAIL"])]
                ),
                "automatic_error_instance_count": len(failed),
                "conditions_with_automatic_error": failed["condition_id"].nunique(),
            }
        )
    _write_csv(output_dir / "text_evaluation_denominator_by_method.csv", rows)

    coverage_rows: list[dict[str, Any]] = []
    for (method, code), group in endpoints.groupby(["method_internal", "error_code"], sort=True):
        counts = Counter(str(value) for value in group["binary_endpoint"])
        coverage_rows.append(
            {
                "method": method,
                "error_code": code,
                "condition_count": len(group),
                "pass_conditions": counts["PASS"],
                "fail_conditions": counts["FAIL"],
                "human_review_conditions": counts["HUMAN_REVIEW"],
                "not_evaluable_conditions": counts["NOT_EVALUABLE"] + counts["NOT_APPLICABLE"],
            }
        )
    _write_csv(output_dir / "text_automatic_error_coverage.csv", coverage_rows)
    return {
        "task_count": int(denominator["task_denominator"]),
        "condition_count": int(denominator["condition_denominator"]),
        "actual_text_count": int(denominator["actual_text_denominator"]),
        "no_valid_output_count": int(denominator["proposed_no_valid_output_denominator"]),
    }


def build_rai_reason_audit(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    rows = _read_jsonl(repo_root / METRIC_DIR / "state_rai.jsonl")
    summary_rows: list[dict[str, Any]] = []
    for (role, status), count in sorted(
        Counter((str(row["cell_scope_role"]), str(row["rai_status"])) for row in rows).items()
    ):
        paper_status = _paper_rai_status(status)
        if paper_status == "AVAILABLE":
            interpretation = "AVAILABLE"
        elif role != "DAILY_REVIEW_CELL" and paper_status == "NO_CELL_LINKED_OPERATIONAL_RESPONSE":
            interpretation = "NOT_EXPECTED_FOR_NON_DAILY_REVIEW_ROLE"
        else:
            interpretation = paper_status
        summary_rows.append(
            {
                "cell_scope_role": role,
                "rai_status": paper_status,
                "paper_interpretation": interpretation,
                "state_version_count": count,
            }
        )
    _write_csv(output_dir / "rai_availability_reason_summary.csv", summary_rows)
    daily_cases = [row for row in rows if row["cell_scope_role"] == "DAILY_REVIEW_CELL"]
    unavailable_cases = [row for row in daily_cases if row["rai_status"] != "AVAILABLE"]
    _write_csv(
        output_dir / "rai_daily_review_unavailability_cases.csv",
        [
            {
                "state_rai_id": row["state_rai_id"],
                "bitemporal_version_id": row["bitemporal_version_id"],
                "valid_date": row["valid_date"],
                "cell_id": row["cell_id"],
                "rai_status": _paper_rai_status(str(row["rai_status"])),
                "reason_codes": ";".join(
                    _paper_rai_status(str(value)) for value in row["reason_codes"]
                ),
                "support_episode_count": row["support_episode_count"],
                "support_response_evidence_count": row["support_response_evidence_count"],
            }
            for row in unavailable_cases
        ],
    )
    return {
        "all_state_version_count": len(rows),
        "daily_review_count": len(daily_cases),
        "available_daily_review_count": sum(
            row["rai_status"] == "AVAILABLE" for row in daily_cases
        ),
        "daily_review_unavailable_count": len(unavailable_cases),
        "non_daily_review_not_expected_count": sum(
            row["cell_scope_role"] != "DAILY_REVIEW_CELL"
            and row["rai_status"] == "NO_CELL_LINKED_OPERATIONAL_RESPONSE"
            for row in rows
        ),
    }


def _paper_rai_status(value: str) -> str:
    """Use neutral paper terminology without changing the upstream decision."""

    if value == "INSUFFICIENT_CAUSAL_BASELINE":
        return "INSUFFICIENT_HISTORICAL_BASELINE"
    return value


def _build_grci_revision_case(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    revision_dir = repo_root / REVISION_DIR
    events = pd.read_csv(revision_dir / "stage7d_revision_event_summary.csv")
    changed = events[events["grci_changed"].astype(str).str.lower() == "true"]
    if len(changed) != 1:
        raise ValueError(f"Expected exactly one GRCI-changing event, found {len(changed)}")
    event_id = str(changed.iloc[0]["revision_event_id"])
    metric_rows = _csv_records_for_event(
        revision_dir / "stage7d_revision_metric_pairs.csv", event_id
    )
    evidence_rows = _csv_records_for_event(
        revision_dir / "stage7d_revision_evidence_delta.csv", event_id
    )
    claim_rows = _csv_records_for_event(
        revision_dir / "stage7d_revision_claim_transition_rows.csv", event_id
    )
    pair_rows = _csv_records_for_event(revision_dir / "stage7d_revision_pairs.csv", event_id)
    evidence_index = {
        str(row["evidence_uid"]): row
        for row in _read_jsonl(repo_root / GEOLOGY_DIR / "primary_geological_evidence.jsonl")
    }
    source_evidence = [
        evidence_index[row["evidence_id"]]
        for row in evidence_rows
        if row["evidence_id"] in evidence_index
    ]
    payload = {
        "revision_event": changed.iloc[0].to_dict(),
        "revision_pair": pair_rows,
        "metric_changes": metric_rows,
        "new_evidence": evidence_rows,
        "source_evidence": source_evidence,
        "claim_transitions": claim_rows,
    }
    _write_json(output_dir / "grci_revision_case.json", payload)
    (output_dir / "grci_revision_case.md").write_text(_render_grci_case(payload), encoding="utf-8")
    return {
        "revision_event_id": event_id,
        "new_evidence_count": len(evidence_rows),
        "claim_transition_count": len(claim_rows),
    }


def _copy_claim_abstention_matrix(repo_root: Path, output_dir: Path) -> None:
    source = repo_root / CLAIM_ANALYSIS_DIR / "claim_type_abstention_matrix.csv"
    shutil.copy2(source, output_dir / "claim_type_abstention_reason.csv")


def _stratified_episode_sample(
    episodes: list[dict[str, Any]],
    footprints: dict[str, dict[str, Any]],
    *,
    sample_count: int,
    minimum_per_stratum: int,
    seed: int,
) -> list[tuple[dict[str, Any], str]]:
    rng = random.Random(seed)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for episode in episodes:
        grouped[_episode_stratum(episode, footprints.get(str(episode["episode_id"]), {}))].append(
            episode
        )
    selected: list[tuple[dict[str, Any], str]] = []
    selected_ids: set[str] = set()
    for stratum in sorted(grouped):
        candidates = sorted(grouped[stratum], key=lambda row: str(row["episode_id"]))
        rng.shuffle(candidates)
        for row in candidates[:minimum_per_stratum]:
            selected.append((row, stratum))
            selected_ids.add(str(row["episode_id"]))
    remaining = [
        (row, stratum)
        for stratum, rows in grouped.items()
        for row in rows
        if str(row["episode_id"]) not in selected_ids
    ]
    rng.shuffle(remaining)
    selected.extend(remaining[: max(sample_count - len(selected), 0)])
    return sorted(selected[:sample_count], key=lambda item: (str(item[0]["target_date"]), item[1]))


def _episode_stratum(episode: dict[str, Any], footprint: dict[str, Any]) -> str:
    flags = set(episode.get("quality_flags", [])) | set(footprint.get("quality_flags", []))
    if str(episode["boundary_status"]) != "COMPLETE":
        return "BOUNDARY_CENSORED"
    if "ZERO_ADVANCE_DURING_EXCAVATION" in flags or footprint.get("estimated_advance_m") == 0:
        return "ZERO_ADVANCE_REVIEW"
    if float(episode.get("interruption_duration_seconds", 0.0)) > 0:
        return "INTERNAL_INTERRUPTION"
    if str(episode.get("quality_grade")) != "A":
        return "QUALITY_REVIEW"
    return "ROUTINE_COMPLETE"


def _stratified_geology_sample(
    evidence: list[dict[str, Any]], *, samples_per_source_type: int, seed: int
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    selected: list[dict[str, Any]] = []
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in evidence:
        by_source[str(row["source_type"])].append(row)
    for source_type in sorted(by_source):
        rows = by_source[source_type]
        by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_type[str(row["evidence_type"])].append(row)
        source_selected: list[dict[str, Any]] = []
        for evidence_type in sorted(by_type):
            candidates = sorted(by_type[evidence_type], key=lambda row: str(row["evidence_uid"]))
            rng.shuffle(candidates)
            source_selected.extend(candidates[: min(3, len(candidates))])
        selected_ids = {str(row["evidence_uid"]) for row in source_selected}
        remainder = [row for row in rows if str(row["evidence_uid"]) not in selected_ids]
        rng.shuffle(remainder)
        source_selected.extend(remainder[: max(samples_per_source_type - len(source_selected), 0)])
        selected.extend(source_selected[:samples_per_source_type])
    return sorted(selected, key=lambda row: (str(row["source_type"]), str(row["evidence_uid"])))


def _field_span_ids(row: dict[str, Any], field_name: str) -> list[str]:
    if field_name == "epistemic_status":
        return [str(span["span_id"]) for span in row.get("source_spans", [])]
    return [str(value) for value in row.get("field_spans", {}).get(field_name, [])]


def _csv_records_for_event(path: Path, event_id: str) -> list[dict[str, Any]]:
    frame = pd.read_csv(path, keep_default_na=False)
    records = frame[frame["revision_event_id"] == event_id].to_dict("records")
    return cast(list[dict[str, Any]], records)


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping in {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _resolve(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _truthy(values: pd.Series) -> pd.Series:
    return values.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y", "是"})


def _absolute_numeric_error(first: Any, second: Any) -> float | None:
    if pd.isna(first) or pd.isna(second) or str(first).strip() == "" or str(second).strip() == "":
        return None
    return abs(float(first) - float(second))


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _json_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _normalize_value(value: Any) -> str:
    text = str(value).strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = text
    if isinstance(parsed, list):
        return "|".join(sorted(_normalize_value(item) for item in parsed))
    return re.sub(r"\s+", "", str(parsed)).casefold()


def _value_set(value: Any) -> set[str]:
    text = str(value).strip()
    if not text:
        return set()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return {_normalize_value(item) for item in parsed if _normalize_value(item)}
    return {
        normalized for part in re.split(r"[;；|、]", text) if (normalized := _normalize_value(part))
    }


def _render_grci_case(payload: dict[str, Any]) -> str:
    event = payload["revision_event"]
    metrics = {row["metric_type"]: row for row in payload["metric_changes"]}
    evidence = payload["new_evidence"][0]
    metric_table = "\n".join(
        "| "
        + metric_name
        + " | "
        + str(metrics[metric_name]["pre_value"])
        + " | "
        + str(metrics[metric_name]["post_value"])
        + " | "
        + str(metrics[metric_name]["absolute_delta"])
        + " |"
        for metric_name in ("RAI", "GRS", "GRCI")
    )
    return f"""# GRCI变化案例

- 修订事件：`{event["revision_event_id"]}`
- 施工日期：{event["valid_date"]}
- 状态单元：`{event["cell_id"]}`
- 后到资料可用日期：{evidence["available_local_date"]}
- 新增证据：`{evidence["evidence_id"]}`（{evidence["source_type"]}，{evidence["epistemic_status"]}）

## 指标变化

| 指标 | 修订前 | 修订后 | 变化 |
|---|---:|---:|---:|
{metric_table}

RAI保持不变，说明后到地质资料没有反向改写历史机械响应。
GRS因新增地质证据而变化，GRCI在当日复核角色下随之变化。
完整证据、来源位置和Claim变化见同目录的`grci_revision_case.json`。
"""


def _plc_packet_readme() -> str:
    return """# PLC事件人工验证包

1. 只查看`sample_index.csv`和`raw_windows/`中的原始观测，避免先看算法边界。
2. 在`annotation_template.csv`填写人工判断；一个窗口有多个事件时复制该样本行。
3. 时间填写带时区的ISO 8601格式，里程填写绝对米值。
4. 完成一行后将`review_complete`设为`true`。
5. `system_predictions.csv`仅供评分程序读取，不作为人工标注依据。

该包尚无人工标签，因此不得据此声称Episode检测准确率。
"""


def _geology_packet_readme() -> str:
    return """# 地质字段人工验证包

`field_annotation_template.csv`按“证据-字段”展开。
审查者应回看原PDF及给出的页码、原文和来源位置，填写`manual_value`和
`manual_is_supported_by_source`，完成后将`review_complete`设为`true`。

数值里程使用误差统计；单值分类字段使用exact match；
复合或多值字段同时计算集合precision、recall和F1。
现有3份人工Gold用于固定真实PDF回归，不等于全量字段准确率。
"""


def _render_readme(summary: dict[str, Any]) -> str:
    rai_available = summary["rai_availability"]["available_daily_review_count"]
    rai_daily = summary["rai_availability"]["daily_review_count"]
    plc_samples = summary["plc_episode_validation"]["sample_count"]
    geology_samples = summary["geology_field_validation"]["sample_count"]
    progression = summary["construction_progression_review"]
    availability = summary["availability_time_sensitivity"]
    return f"""# 论文证据链补充评测 v2

本目录只读取既有冻结产物，不重建或修改Stage1至Stage7对象。

## 已完成的离线结果

- 文本统计已统一为任务、方法-任务条件、实际文本、可核查陈述和错误实例等不同分母。
- RAI统计已区分全部双时间状态与真正应计算机械响应的当日复核状态；
  当日复核状态中{rai_available}/{rai_daily}个RAI可用。
- 已导出唯一GRCI变化事件及其修订前后指标、新增证据和Claim变化。
- 已复制Claim类型与不表达原因交叉表，供论文解释72.347%/27.653%的组成。
- 施工推进信息关联采用预先固定的严格口径：共识别
  {progression["strict_same_day_direct_context_count"]}个“施工前正式预测—实际PLC掘进—同日且直接空间对应的掌子面观察”情境。
- 宽口径的{progression["broad_daily_review_context_count"]}个当日复核状态被单独保留，
  其中既有历史观察背景不得冒充开挖当天观察。
- {availability["documented_revision_event_count"]}个正式资料可用时间修订已与
  “现场工作日结束前即可用”的反事实假设比较；该假设不代表人员真实获知时间。

## 解释边界

- 不计算地质预报准确率。
- 不把机械响应解释为地质原因。
- 不把点状掌子面观察扩展为整个预测区间。
- 施工推进跨越不同施工日期；双时间修订只比较同一日期、同一空间对象的不同知识版本。

## 仍需人工完成

- PLC Episode：{plc_samples}个分层样本已冻结，尚未填写人工边界。
- 地质字段：{geology_samples}条分层证据已冻结，尚未填写人工字段。

在人工表填写前，准确率、precision、recall和F1均没有被生成，也不得写入论文。
"""
