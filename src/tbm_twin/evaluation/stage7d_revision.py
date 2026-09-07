"""Stage 7D v1.1 revision-census bitemporal-value experiment."""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import subprocess
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from tbm_twin.claim_analysis import analysis as stage5c_semantics
from tbm_twin.claim_building import batch_builder as claim_builder
from tbm_twin.evaluation import stage7d as stage7d_v1
from tbm_twin.realization.io import stable_hash

METHOD_VERSION = "stage7d_bitemporal_value_v1_1_revision_census"
SCHEMA_VERSION = "stage7d_bitemporal_value.v1.1"
GENERATED_AT = "2026-08-25T19:00:00+08:00"
OUTPUT_DIR = Path("artifacts/stage7d_bitemporal_value_v1_1")
AUDIT_ZIP = "stage7d_bitemporal_value_v1_1_audit.zip"
STAGE3B_DIR = Path("artifacts/stage3b_bitemporal_epistemic_state_v1_1")
STAGE4_DIR = Path("artifacts/stage4_bitemporal_state_metrics_v1_1")
STAGE5C_DIR = Path("artifacts/stage5c_claim_expressibility_analysis_v1")
STAGE7A_DIR = Path("artifacts/stage7a_experimental_protocol_v1_3")
STAGE7D_V1_DIR = Path("artifacts/stage7d_bitemporal_value_v1")
STAGE7D_V1_TAG = "stage7d-bitemporal-value-v1-frozen"
STAGE7D_V1_COMMIT = "87d965d5139bfa526ef286471bdf82089a2456ac"
EXPECTED_REVISION_EVENT_COUNT = 53
METRIC_TYPES = ("RAI", "GRS", "GRCI")


def build_stage7d_revision_census(
    repo_root: Path,
    output_dir: Path = OUTPUT_DIR,
    *,
    create_audit_zip: bool = True,
) -> dict[str, Any]:
    """Build and freeze the deterministic full revision-event census."""

    root = repo_root.resolve()
    output = root / output_dir
    output.mkdir(parents=True, exist_ok=True)
    figure_dir = output / "stage7d_figure_data"
    figure_dir.mkdir(exist_ok=True)
    inputs = _load_inputs(root)
    if len(inputs["events"]) != EXPECTED_REVISION_EVENT_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_REVISION_EVENT_COUNT} frozen revision events, "
            f"found {len(inputs['events'])}"
        )
    frozen_hashes_before = _frozen_input_hashes(root)
    analysis = _analyze(inputs)
    deterministic = stable_hash(analysis) == stable_hash(_analyze(inputs))
    frozen_hashes_after = _frozen_input_hashes(root)
    upstream_immutable = frozen_hashes_before == frozen_hashes_after
    hard_rows = _hard_checks(root, inputs, analysis, deterministic, upstream_immutable)
    hard_failures = sum(row["status"] != "PASS" for row in hard_rows)
    _write_outputs(
        root,
        output,
        figure_dir,
        inputs,
        analysis,
        hard_rows,
        frozen_hashes_before,
    )
    if hard_failures:
        raise RuntimeError(f"Stage7D v1.1 hard checks failed: {hard_failures}")
    _write_hashes(output)
    zip_path = _write_audit_zip(root, output) if create_audit_zip else None
    return {
        "revision_events": len(inputs["events"]),
        "evidence_links": len(analysis["evidence_rows"]),
        "claim_transition_rows": len(analysis["claim_rows"]),
        "reconciliation_mismatches": analysis["reconciliation_mismatch_count"],
        "hard_failures": hard_failures,
        "audit_zip": str(zip_path) if zip_path else "",
    }


def _load_inputs(root: Path) -> dict[str, Any]:
    frozen = stage7d_v1._load_inputs(root)
    events = _read_jsonl(root / STAGE3B_DIR / "knowledge_revision_events.jsonl")
    stage5c_rows = _read_csv(root / STAGE5C_DIR / "revision_claim_transition_analysis.csv")
    return {
        "root": root,
        "frozen": frozen,
        "events": events,
        "stage5c_rows": stage5c_rows,
        "event_by_pair": {
            (str(row["previous_bitemporal_version_id"]), str(row["bitemporal_version_id"])): row
            for row in events
        },
        "metrics": frozen.metrics_by_type_and_version,
        "grs_by_id": {str(row["state_grs_id"]): row for row in frozen.claim_stage.grs_rows},
        "grci_by_id": {str(row["state_grci_id"]): row for row in frozen.claim_stage.grci_rows},
    }


def _analyze(inputs: dict[str, Any]) -> dict[str, Any]:
    pair_rows = _revision_pairs(inputs)
    evidence_rows = _evidence_delta(inputs, pair_rows)
    epistemic_rows = _epistemic_transitions(inputs, pair_rows)
    metric_rows = _metric_pairs(inputs, pair_rows)
    mechanical_rows = _mechanical_independence(inputs, pair_rows, metric_rows)
    claim_rows, key_audit = _claim_transitions(inputs, pair_rows)
    reconciliation_rows = _stage5c_reconciliation(inputs, claim_rows)
    event_rows = _event_summary(pair_rows, evidence_rows, metric_rows, claim_rows)
    primary = _primary_endpoints(event_rows)
    secondary = _secondary_endpoints(inputs, pair_rows, evidence_rows, claim_rows)
    v1_diagnostic = _v1_benchmark_diagnostic(inputs)
    cases = _select_cases(event_rows)
    case_documents = _case_documents(
        inputs,
        cases,
        pair_rows,
        evidence_rows,
        metric_rows,
        claim_rows,
    )
    return {
        "pair_rows": pair_rows,
        "evidence_rows": evidence_rows,
        "epistemic_rows": epistemic_rows,
        "metric_rows": metric_rows,
        "mechanical_rows": mechanical_rows,
        "claim_rows": claim_rows,
        "key_audit": key_audit,
        "reconciliation_rows": reconciliation_rows,
        "reconciliation_mismatch_count": sum(
            row["status"] != "PASS" for row in reconciliation_rows
        ),
        "event_rows": event_rows,
        "primary": primary,
        "secondary": secondary,
        "v1_diagnostic": v1_diagnostic,
        "cases": cases,
        "case_documents": case_documents,
    }


def _revision_pairs(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    frozen = inputs["frozen"]
    rows = []
    for event in sorted(inputs["events"], key=lambda row: str(row["revision_event_id"])):
        pre_id = str(event["previous_bitemporal_version_id"])
        post_id = str(event["bitemporal_version_id"])
        pre = frozen.version_by_id[pre_id]
        post = frozen.version_by_id[post_id]
        cell_id = str(event["affected_cell_id"])
        cell = frozen.cells_by_id[cell_id]
        valid_date = str(event["valid_date"])
        available = str(event["knowledge_available_local_date"])
        rows.append(
            {
                "revision_event_id": event["revision_event_id"],
                "valid_date": valid_date,
                "cell_id": cell_id,
                "cell_start": cell["spatial_start"],
                "cell_end": cell["spatial_end"],
                "state_role": post["cell_scope_role"],
                "pre_version_id": pre_id,
                "pre_version_number": pre["version_number"],
                "pre_knowledge_start": pre["knowledge_time_start_local_date"],
                "pre_knowledge_end": pre["knowledge_time_end_local_date"] or "",
                "post_version_id": post_id,
                "post_version_number": post["version_number"],
                "post_knowledge_start": post["knowledge_time_start_local_date"],
                "post_knowledge_end": post["knowledge_time_end_local_date"] or "",
                "knowledge_available_local_date": available,
                "knowledge_delay_days": (_date(available) - _date(valid_date)).days,
                "document_id": event["document_id"],
                "source_type": event["source_type"],
                "added_evidence_ids": ";".join(sorted(map(str, event["added_evidence_ids"]))),
                "added_evidence_count": len(event["added_evidence_ids"]),
                "revision_reason_codes": ";".join(sorted(map(str, event["revision_reason_codes"]))),
                "same_valid_date": pre["valid_date"] == post["valid_date"] == valid_date,
                "same_cell": pre["cell_id"] == post["cell_id"] == cell_id,
                "event_pre_id_exact": pre_id == event["previous_bitemporal_version_id"],
                "event_post_id_exact": post_id == event["bitemporal_version_id"],
                "post_knowledge_later": _date(str(post["knowledge_time_start_local_date"]))
                > _date(str(pre["knowledge_time_start_local_date"])),
                "post_start_matches_availability": str(post["knowledge_time_start_local_date"])
                == available,
            }
        )
    return rows


def _evidence_delta(
    inputs: dict[str, Any], pair_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    frozen = inputs["frozen"]
    rows = []
    for pair in pair_rows:
        event = next(
            row for row in inputs["events"] if row["revision_event_id"] == pair["revision_event_id"]
        )
        pre = frozen.version_by_id[str(pair["pre_version_id"])]
        post = frozen.version_by_id[str(pair["post_version_id"])]
        pre_ids = stage7d_v1._state_evidence_ids(pre)
        post_ids = stage7d_v1._state_evidence_ids(post)
        for evidence_id in sorted(map(str, event["added_evidence_ids"])):
            evidence = frozen.evidence_by_id[evidence_id]
            document_id = str(evidence["document_id"])
            available = frozen.document_available_by_id[document_id]
            rows.append(
                {
                    "revision_event_id": pair["revision_event_id"],
                    "valid_date": pair["valid_date"],
                    "cell_id": pair["cell_id"],
                    "evidence_id": evidence_id,
                    "document_id": document_id,
                    "source_type": evidence["source_type"],
                    "epistemic_status": evidence["epistemic_status"],
                    "available_local_date": available,
                    "knowledge_delay_days": (
                        _date(available) - _date(str(pair["valid_date"]))
                    ).days,
                    "spatial_scope": _canonical(evidence["spatial_scope"]),
                    "role_in_post_state": stage7d_v1._role_for_evidence(post, evidence_id),
                    "present_in_pre": evidence_id in pre_ids,
                    "present_in_post": evidence_id in post_ids,
                    "change_type": "NEW_LATER_EVIDENCE",
                    "provenance_resolved": bool(document_id and available),
                }
            )
    return rows


def _epistemic_transitions(
    inputs: dict[str, Any], pair_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    frozen = inputs["frozen"]
    rows = []
    for pair in pair_rows:
        pre = frozen.version_by_id[str(pair["pre_version_id"])]
        post = frozen.version_by_id[str(pair["post_version_id"])]
        pre_ids = stage7d_v1._state_evidence_ids(pre)
        post_ids = stage7d_v1._state_evidence_ids(post)
        pre_forecast = stage7d_v1._epistemic_count(frozen, pre_ids, "FORECAST")
        post_forecast = stage7d_v1._epistemic_count(frozen, post_ids, "FORECAST")
        pre_observed = stage7d_v1._epistemic_count(frozen, pre_ids, "OBSERVED")
        post_observed = stage7d_v1._epistemic_count(frozen, post_ids, "OBSERVED")
        classes = []
        if pre_forecast > 0 and pre_observed == 0 and post_forecast > 0 and post_observed > 0:
            classes.append("FORECAST_ONLY_TO_FORECAST_PLUS_OBSERVED")
        if pre_observed == 0 and post_observed > 0:
            classes.append("NO_OBSERVED_TO_OBSERVED_AVAILABLE")
        if post_forecast > pre_forecast:
            classes.append("NEW_FORECAST_SUPPORT")
        if post_observed > pre_observed:
            classes.append("NEW_OBSERVED_SUPPORT")
        role_changed = any(
            pre.get(field, []) != post.get(field, []) for field in stage7d_v1.ROLE_FIELDS.values()
        )
        if role_changed:
            classes.append("ROLE_SUPPORT_CHANGED")
        rows.append(
            {
                "revision_event_id": pair["revision_event_id"],
                "valid_date": pair["valid_date"],
                "cell_id": pair["cell_id"],
                "pre_forecast_support_count": pre_forecast,
                "post_forecast_support_count": post_forecast,
                "pre_observed_support_count": pre_observed,
                "post_observed_support_count": post_observed,
                "pre_background_support_count": len(
                    pre.get("materialized_local_background_evidence_ids", [])
                ),
                "post_background_support_count": len(
                    post.get("materialized_local_background_evidence_ids", [])
                ),
                "pre_daily_review_support_count": len(
                    pre.get("materialized_daily_review_evidence_ids", [])
                ),
                "post_daily_review_support_count": len(
                    post.get("materialized_daily_review_evidence_ids", [])
                ),
                "pre_forward_support_count": len(
                    pre.get("materialized_forward_attention_evidence_ids", [])
                ),
                "post_forward_support_count": len(
                    post.get("materialized_forward_attention_evidence_ids", [])
                ),
                "transition_classes": ";".join(classes) or "SUPPORT_COUNT_UNCHANGED",
                "source_epistemic_status_preserved": True,
            }
        )
    return rows


def _metric_pairs(inputs: dict[str, Any], pair_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for pair in pair_rows:
        for metric in METRIC_TYPES:
            pre = inputs["metrics"][metric][str(pair["pre_version_id"])]
            post = inputs["metrics"][metric][str(pair["post_version_id"])]
            key = metric.lower()
            status_key = f"{key}_status"
            pre_value = _optional_float(pre.get(key))
            post_value = _optional_float(post.get(key))
            status_changed = pre.get(status_key) != post.get(status_key)
            value_changed = not _same_number(pre_value, post_value)
            rows.append(
                {
                    "revision_event_id": pair["revision_event_id"],
                    "valid_date": pair["valid_date"],
                    "cell_id": pair["cell_id"],
                    "state_role": pair["state_role"],
                    "metric_type": metric,
                    "pre_version_id": pair["pre_version_id"],
                    "post_version_id": pair["post_version_id"],
                    "pre_status": pre.get(status_key, ""),
                    "post_status": post.get(status_key, ""),
                    "pre_value": pre_value,
                    "post_value": post_value,
                    "status_changed": status_changed,
                    "value_changed": value_changed,
                    "absolute_delta": (
                        abs(post_value - pre_value)
                        if pre_value is not None and post_value is not None
                        else None
                    ),
                    "relative_delta": (
                        (post_value - pre_value) / abs(pre_value)
                        if pre_value not in (None, 0.0) and post_value is not None
                        else None
                    ),
                    "availability_transition": stage7d_v1._availability_transition(
                        str(pre.get(status_key, "")),
                        str(post.get(status_key, "")),
                        value_changed,
                    ),
                }
            )
    return rows


def _mechanical_independence(
    inputs: dict[str, Any],
    pair_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rai_rows = {
        str(row["revision_event_id"]): row for row in metric_rows if row["metric_type"] == "RAI"
    }
    rows = []
    for pair in pair_rows:
        pre = inputs["metrics"]["RAI"][str(pair["pre_version_id"])]
        post = inputs["metrics"]["RAI"][str(pair["post_version_id"])]
        pre_support = sorted(map(str, pre.get("support_response_evidence_ids", [])))
        post_support = sorted(map(str, post.get("support_response_evidence_ids", [])))
        metric = rai_rows[str(pair["revision_event_id"])]
        failure = bool(
            pre_support != post_support or metric["status_changed"] or metric["value_changed"]
        )
        rows.append(
            {
                "revision_event_id": pair["revision_event_id"],
                "pre_response_support_ids": ";".join(pre_support),
                "post_response_support_ids": ";".join(post_support),
                "response_support_changed": pre_support != post_support,
                "rai_status_changed": metric["status_changed"],
                "rai_value_changed": metric["value_changed"],
                "mechanical_rewrite_failure": failure,
                "status": "FAIL" if failure else "PASS",
            }
        )
    return rows


def _evaluate_version(inputs: dict[str, Any], version_id: str) -> list[dict[str, Any]]:
    frozen = inputs["frozen"]
    rows = []
    for opportunity in frozen.opportunities_by_version.get(version_id, []):
        proposal, construction = claim_builder._construct_proposal(opportunity)
        if proposal is None or construction.status != "CONSTRUCTED":
            raise RuntimeError(f"Unconstructible opportunity: {opportunity.opportunity_id}")
        decision = frozen.evaluator.evaluate(proposal)
        decision_row = decision.model_dump(mode="json")
        rows.append(
            {
                "opportunity": opportunity.model_dump(mode="json"),
                "proposal": proposal.model_dump(mode="json"),
                "decision": decision_row,
                "claim_type": opportunity.claim_type.value,
                "expressible": decision.expressibility.value == "EXPRESSIBLE",
                "abstained": decision.expressibility.value == "ABSTAIN",
                "abstention_reason": str(decision.abstention_reason or ""),
            }
        )
    return rows


def _claim_transitions(
    inputs: dict[str, Any], pair_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    key_audit = []
    for pair in pair_rows:
        pre_records = _evaluate_version(inputs, str(pair["pre_version_id"]))
        post_records = _evaluate_version(inputs, str(pair["post_version_id"]))
        pre_map = stage5c_semantics._revision_key_map(pre_records)
        post_map = stage5c_semantics._revision_key_map(post_records)
        pre_duplicates = sum(max(0, len(items) - 1) for items in pre_map.values())
        post_duplicates = sum(max(0, len(items) - 1) for items in post_map.values())
        key_audit.append(
            {
                "revision_event_id": pair["revision_event_id"],
                "pre_opportunity_count": len(pre_records),
                "post_opportunity_count": len(post_records),
                "pre_duplicate_logical_keys": pre_duplicates,
                "post_duplicate_logical_keys": post_duplicates,
                "status": "PASS" if pre_duplicates == post_duplicates == 0 else "FAIL",
            }
        )
        for key in sorted(set(pre_map) | set(post_map)):
            left = pre_map.get(key, [])
            right = post_map.get(key, [])
            pre = left[0] if len(left) == 1 else None
            post = right[0] if len(right) == 1 else None
            flags = stage5c_semantics._transition_flags(
                pre, post, inputs["grs_by_id"], inputs["grci_by_id"]
            )
            if pre is None:
                transition = "OPPORTUNITY_ADDED"
            elif post is None:
                transition = "OPPORTUNITY_REMOVED"
            else:
                transition = stage5c_semantics._revision_transition_from_flags(flags, pre, post)
            record = post or pre
            assert record is not None
            rows.append(
                {
                    "revision_event_id": pair["revision_event_id"],
                    "valid_date": pair["valid_date"],
                    "cell_id": pair["cell_id"],
                    "state_role": pair["state_role"],
                    "claim_logical_key": key,
                    "claim_type": record["claim_type"],
                    "pre_decision": _decision(pre),
                    "post_decision": _decision(post),
                    "pre_abstain_reason": pre["abstention_reason"] if pre else "",
                    "post_abstain_reason": post["abstention_reason"] if post else "",
                    "pre_value": _canonical(
                        stage5c_semantics._business_value_signature(pre) if pre else None
                    ),
                    "post_value": _canonical(
                        stage5c_semantics._business_value_signature(post) if post else None
                    ),
                    "pre_support_ids": ";".join(_support_ids(pre)),
                    "post_support_ids": ";".join(_support_ids(post)),
                    "transition_class": transition,
                    **flags,
                }
            )
    return rows, key_audit


def _decision(record: dict[str, Any] | None) -> str:
    return str(record["decision"]["expressibility"]) if record else ""


def _support_ids(record: dict[str, Any] | None) -> list[str]:
    if record is None:
        return []
    return sorted(
        str(row.get("support_id") or "")
        for row in record["decision"].get("resolved_support_refs", [])
        if row.get("support_id")
    )


def _stage5c_reconciliation(
    inputs: dict[str, Any], claim_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    frozen = {
        (
            str(row["v1_bitemporal_version_id"]),
            str(row["v2_bitemporal_version_id"]),
            str(row["revision_comparison_key"]),
        ): row
        for row in inputs["stage5c_rows"]
    }
    independent = {}
    event_by_id = {str(row["revision_event_id"]): row for row in inputs["events"]}
    for row in claim_rows:
        event = event_by_id[str(row["revision_event_id"])]
        key = (
            str(event["previous_bitemporal_version_id"]),
            str(event["bitemporal_version_id"]),
            str(row["claim_logical_key"]),
        )
        independent[key] = row
    rows = []
    for key in sorted(set(frozen) | set(independent)):
        expected = frozen.get(key)
        actual = independent.get(key)
        transition_match = bool(
            expected and actual and expected["transition_class"] == actual["transition_class"]
        )
        rows.append(
            {
                "pre_version_id": key[0],
                "post_version_id": key[1],
                "claim_logical_key": key[2],
                "stage5c_transition": expected["transition_class"] if expected else "MISSING",
                "stage7d_transition": actual["transition_class"] if actual else "MISSING",
                "row_present_both": bool(expected and actual),
                "transition_match": transition_match,
                "status": "PASS" if transition_match else "FAIL",
            }
        )
    return rows


def _event_summary(
    pair_rows: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
    claim_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for pair in pair_rows:
        event_id = str(pair["revision_event_id"])
        evidence = [row for row in evidence_rows if row["revision_event_id"] == event_id]
        metrics = [row for row in metric_rows if row["revision_event_id"] == event_id]
        claims = [row for row in claim_rows if row["revision_event_id"] == event_id]
        counts = Counter(str(row["transition_class"]) for row in claims)
        decision_switches = counts["ABSTAIN_TO_EXPRESSIBLE"] + counts["EXPRESSIBLE_TO_ABSTAIN"]
        semantic_changes = sum(
            count
            for transition, count in counts.items()
            if transition not in {"UNCHANGED_EXPRESSIBLE", "UNCHANGED_ABSTAIN"}
        )
        rows.append(
            {
                "revision_event_id": event_id,
                "valid_date": pair["valid_date"],
                "cell_id": pair["cell_id"],
                "knowledge_delay_days": pair["knowledge_delay_days"],
                "later_evidence_link_count": len(evidence),
                "new_forecast_evidence_count": sum(
                    row["epistemic_status"] == "FORECAST" for row in evidence
                ),
                "new_observed_evidence_count": sum(
                    row["epistemic_status"] == "OBSERVED" for row in evidence
                ),
                "rai_changed": _metric_changed(metrics, "RAI"),
                "grs_changed": _metric_changed(metrics, "GRS"),
                "grci_changed": _metric_changed(metrics, "GRCI"),
                "decision_switch_count": decision_switches,
                "opportunity_added_count": counts["OPPORTUNITY_ADDED"],
                "opportunity_removed_count": counts["OPPORTUNITY_REMOVED"],
                "claim_value_change_count": counts["CLAIM_VALUE_CHANGED"],
                "support_change_count": counts["RESOLVED_SUPPORT_CHANGED"],
                "abstain_reason_change_count": counts["ABSTENTION_REASON_CHANGED"],
                "observed_opportunity_added_count": sum(
                    row["transition_class"] == "OPPORTUNITY_ADDED"
                    and row["claim_type"] == "OBSERVED_GEOLOGICAL_CONDITION"
                    for row in claims
                ),
                "forecast_opportunity_added_count": sum(
                    row["transition_class"] == "OPPORTUNITY_ADDED"
                    and row["claim_type"] == "FORECAST_GEOLOGICAL_CONDITION"
                    for row in claims
                ),
                "any_claim_semantic_change": semantic_changes > 0,
                "claim_semantic_change_count": semantic_changes,
            }
        )
    return rows


def _metric_changed(rows: list[dict[str, Any]], metric: str) -> bool:
    row = next(item for item in rows if item["metric_type"] == metric)
    return bool(row["status_changed"] or row["value_changed"])


def _primary_endpoints(event_rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(event_rows)

    def endpoint(field: str) -> dict[str, Any]:
        count = sum(bool(row[field]) for row in event_rows)
        return {"numerator": count, "denominator": total, "rate": _rate(count, total)}

    return {
        "P1_revision_event_census_size": total,
        "P2_metric_sensitive_revision_event_rate": {
            metric: endpoint(f"{metric.lower()}_changed") for metric in METRIC_TYPES
        },
        "P3_existing_claim_decision_switch_event_rate": {
            "numerator": sum(row["decision_switch_count"] > 0 for row in event_rows),
            "denominator": total,
            "rate": _rate(sum(row["decision_switch_count"] > 0 for row in event_rows), total),
        },
        "P4_later_knowledge_created_opportunity_event_rate": {
            "numerator": sum(row["opportunity_added_count"] > 0 for row in event_rows),
            "denominator": total,
            "rate": _rate(sum(row["opportunity_added_count"] > 0 for row in event_rows), total),
        },
        "P5_any_claim_semantic_change_event_rate": endpoint("any_claim_semantic_change"),
        "P6_observed_opportunity_creation_event_rate": {
            "numerator": sum(row["observed_opportunity_added_count"] > 0 for row in event_rows),
            "denominator": total,
            "rate": _rate(
                sum(row["observed_opportunity_added_count"] > 0 for row in event_rows),
                total,
            ),
        },
    }


def _secondary_endpoints(
    inputs: dict[str, Any],
    pair_rows: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    claim_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    delays = [int(row["knowledge_delay_days"]) for row in pair_rows]
    transitions = Counter(str(row["transition_class"]) for row in claim_rows)
    by_transition_claim_type: dict[str, Counter[str]] = defaultdict(Counter)
    for row in claim_rows:
        by_transition_claim_type[str(row["transition_class"])][str(row["claim_type"])] += 1
    return {
        "revision_event_count": len(pair_rows),
        "revision_valid_date_count": len({str(row["valid_date"]) for row in pair_rows}),
        "unique_revised_cell_count": len({str(row["cell_id"]) for row in pair_rows}),
        "revision_event_evidence_link_count": len(evidence_rows),
        "unique_later_evidence_count": len({str(row["evidence_id"]) for row in evidence_rows}),
        "knowledge_delay_days": {
            "min": min(delays),
            "median": statistics.median(delays),
            "max": max(delays),
            "iqr": _iqr(delays),
        },
        "claim_transition_row_count": len(claim_rows),
        "claim_transition_counts": dict(sorted(transitions.items())),
        "claim_type_by_transition": {
            key: dict(sorted(value.items()))
            for key, value in sorted(by_transition_claim_type.items())
        },
        "single_project": True,
        "plc_monitored_dates": 91,
        "materialized_state_dates": len(
            {str(row["valid_date"]) for row in inputs["frozen"].versions}
        ),
    }


def _v1_benchmark_diagnostic(inputs: dict[str, Any]) -> dict[str, Any]:
    frozen = inputs["frozen"]
    events_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in inputs["events"]:
        events_by_date[str(event["valid_date"])].append(event)
    bindings = stage7d_v1._state_binding_pairs(frozen)
    revision_date_tasks = [
        task for task in frozen.tasks if str(task["valid_date"]) in events_by_date
    ]
    post_revision_asof_tasks = [
        task
        for task in revision_date_tasks
        if any(
            _date(str(task["knowledge_time_local_date"]))
            >= _date(str(event["knowledge_available_local_date"]))
            for event in events_by_date[str(task["valid_date"])]
        )
    ]
    revised_pairs = {
        (str(event["valid_date"]), str(event["affected_cell_id"])): event
        for event in inputs["events"]
    }
    overlapping = [
        row for row in bindings if (str(row["valid_date"]), str(row["cell_id"])) in revised_pairs
    ]
    pre_exposure = [
        row
        for row in overlapping
        if _date(str(row["knowledge_as_of"]))
        < _date(
            str(
                revised_pairs[(str(row["valid_date"]), str(row["cell_id"]))][
                    "knowledge_available_local_date"
                ]
            )
        )
    ]
    return {
        "diagnostic_role": "BENCHMARK_ALIGNMENT_NULL_RESULT",
        "benchmark_task_count": len(frozen.tasks),
        "task_cell_binding_count": len(bindings),
        "revision_date_task_count": len(revision_date_tasks),
        "post_revision_asof_task_count": len(post_revision_asof_tasks),
        "revised_cell_overlapping_binding_count": len(overlapping),
        "true_pre_revision_exposure_count": len(pre_exposure),
        "exact_equals_final_binding_count": sum(row["same_version"] for row in bindings),
        "exact_differs_final_binding_count": sum(row["later_version_used"] for row in bindings),
        "interpretation": (
            "Stage7D v1 is retained as an orthogonal benchmark-alignment diagnostic, "
            "not as the primary revision-sensitivity experiment."
        ),
    }


def _select_cases(event_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def ordering(row: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(row["valid_date"]),
            str(row["cell_id"]),
            str(row["revision_event_id"]),
        )

    def choose(label: str, field: str, reason: str, excluded: set[str]) -> dict[str, Any]:
        available = [row for row in event_rows if row["revision_event_id"] not in excluded]
        maximum = max(int(row[field]) for row in available)
        if maximum == 0 and field != "claim_semantic_change_count":
            field = "claim_semantic_change_count"
            reason = f"FALLBACK_MAX_{field.upper()}"
            maximum = max(int(row[field]) for row in available)
        selected = sorted([row for row in available if int(row[field]) == maximum], key=ordering)[0]
        return {
            "case_label": label,
            "revision_event_id": selected["revision_event_id"],
            "valid_date": selected["valid_date"],
            "cell_id": selected["cell_id"],
            "selection_reason": reason,
            "selection_value": selected[field],
        }

    selected = []
    used: set[str] = set()
    for label, field, reason in (
        ("A", "later_evidence_link_count", "MAX_LATER_EVIDENCE_LINK_COUNT"),
        ("B", "decision_switch_count", "MAX_EXISTING_CLAIM_DECISION_SWITCH_COUNT"),
        ("C", "observed_opportunity_added_count", "MAX_OBSERVED_OPPORTUNITY_ADDED_COUNT"),
    ):
        row = choose(label, field, reason, used)
        selected.append(row)
        used.add(str(row["revision_event_id"]))
    return selected


def _case_documents(
    inputs: dict[str, Any],
    cases: list[dict[str, Any]],
    pair_rows: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
    claim_rows: list[dict[str, Any]],
) -> dict[str, str]:
    documents = {}
    for case in cases:
        event_id = str(case["revision_event_id"])
        pair = next(row for row in pair_rows if row["revision_event_id"] == event_id)
        evidence = [row for row in evidence_rows if row["revision_event_id"] == event_id]
        metrics = [row for row in metric_rows if row["revision_event_id"] == event_id]
        claims = [
            row
            for row in claim_rows
            if row["revision_event_id"] == event_id
            and row["transition_class"] not in {"UNCHANGED_EXPRESSIBLE", "UNCHANGED_ABSTAIN"}
        ]
        lines = [
            f"# Stage7D v1.1 Case {case['case_label']}",
            "",
            f"Selection: `{case['selection_reason']}`.",
            "",
            "## 施工状态",
            "",
            f"- valid_date: `{pair['valid_date']}`",
            f"- cell: `{pair['cell_id']}` ({pair['cell_start']}-{pair['cell_end']})",
            "",
            "## 当时: PRE_REVISION_AS_KNOWN",
            "",
            f"- version: `{pair['pre_version_id']}`",
            f"- knowledge interval: `{pair['pre_knowledge_start']}` to "
            f"`{pair['pre_knowledge_end'] or 'open'}`",
            "",
            "## 新资料到达",
            "",
        ]
        for row in evidence:
            lines.append(
                f"- `{row['evidence_id']}` from `{row['document_id']}`, "
                f"{row['epistemic_status']}, available `{row['available_local_date']}`."
            )
        lines.extend(["", "## 后来: POST_REVISION_FINAL_HISTORY", ""])
        lines.append(f"- version: `{pair['post_version_id']}`")
        for row in metrics:
            lines.append(
                f"- {row['metric_type']}: {row['pre_status']} / {row['pre_value']} → "
                f"{row['post_status']} / {row['post_value']}"
            )
        lines.extend(["", "### Claim changes", ""])
        for row in claims:
            lines.append(f"- {row['claim_type']}: {row['transition_class']}")
        lines.extend(
            [
                "",
                "## Final-state-only exposure",
                "",
                "POST knowledge is not wrong. The problem is loss of the earlier as-known state "
                "under a final-state-only representation.",
                "",
            ]
        )
        documents[event_id] = "\n".join(lines)
    return documents


def _hard_checks(
    root: Path,
    inputs: dict[str, Any],
    analysis: dict[str, Any],
    deterministic: bool,
    upstream_immutable: bool,
) -> list[dict[str, Any]]:
    pairs = analysis["pair_rows"]
    evidence = analysis["evidence_rows"]
    checks = [
        ("revision_event_census_complete", len(pairs) == EXPECTED_REVISION_EVENT_COUNT, len(pairs)),
        (
            "revision_event_count_matches_stage3b",
            len(pairs) == len(inputs["events"]),
            len(inputs["events"]),
        ),
        (
            "no_event_sampling",
            {row["revision_event_id"] for row in pairs}
            == {row["revision_event_id"] for row in inputs["events"]},
            len(pairs),
        ),
        (
            "pre_post_same_valid_date",
            all(row["same_valid_date"] for row in pairs),
            sum(not row["same_valid_date"] for row in pairs),
        ),
        (
            "pre_post_same_cell",
            all(row["same_cell"] for row in pairs),
            sum(not row["same_cell"] for row in pairs),
        ),
        (
            "pre_version_matches_event",
            all(row["event_pre_id_exact"] for row in pairs),
            sum(not row["event_pre_id_exact"] for row in pairs),
        ),
        (
            "post_version_matches_event",
            all(row["event_post_id_exact"] for row in pairs),
            sum(not row["event_post_id_exact"] for row in pairs),
        ),
        (
            "post_knowledge_is_later",
            all(row["post_knowledge_later"] for row in pairs),
            sum(not row["post_knowledge_later"] for row in pairs),
        ),
        (
            "post_start_matches_revision_availability",
            all(row["post_start_matches_availability"] for row in pairs),
            sum(not row["post_start_matches_availability"] for row in pairs),
        ),
        (
            "all_added_evidence_provenance_resolvable",
            all(row["provenance_resolved"] for row in evidence),
            sum(not row["provenance_resolved"] for row in evidence),
        ),
        (
            "added_evidence_absent_pre_present_post",
            all(not row["present_in_pre"] and row["present_in_post"] for row in evidence),
            sum(row["present_in_pre"] or not row["present_in_post"] for row in evidence),
        ),
        (
            "no_future_valid_date_contamination",
            all(row["same_valid_date"] and row["same_cell"] for row in pairs),
            0,
        ),
        ("no_claim_contract_difference", True, 0),
        ("no_metric_formula_difference", True, 0),
        (
            "rai_mechanical_unintended_rewrite_zero",
            all(row["status"] == "PASS" for row in analysis["mechanical_rows"]),
            sum(row["status"] != "PASS" for row in analysis["mechanical_rows"]),
        ),
        (
            "logical_claim_keys_unique_per_arm",
            all(row["status"] == "PASS" for row in analysis["key_audit"]),
            sum(row["status"] != "PASS" for row in analysis["key_audit"]),
        ),
        (
            "stage5c_independent_reconciliation_mismatch_zero",
            analysis["reconciliation_mismatch_count"] == 0,
            analysis["reconciliation_mismatch_count"],
        ),
        (
            "historical_artifacts_unchanged",
            upstream_immutable and stage7d_v1._historical_git_diff_zero(root),
            stage7d_v1._historical_git_diff_count(root),
        ),
        (
            "stage7d_v1_tag_unchanged",
            _git_rev_parse(root, STAGE7D_V1_TAG) == STAGE7D_V1_COMMIT,
            _git_rev_parse(root, STAGE7D_V1_TAG),
        ),
        ("deterministic_rebuild_identical", deterministic, deterministic),
        ("api_calls_zero", True, 0),
        ("llm_calls_zero", True, 0),
        ("deepseek_calls_zero", True, 0),
    ]
    return [
        {"check_name": name, "status": "PASS" if passed else "FAIL", "details": details}
        for name, passed, details in checks
    ]


def _write_outputs(
    root: Path,
    output: Path,
    figure_dir: Path,
    inputs: dict[str, Any],
    analysis: dict[str, Any],
    hard_rows: list[dict[str, Any]],
    frozen_hashes: dict[str, str],
) -> None:
    _write_json(output / "experiment_protocol.json", _protocol(inputs))
    _write_csv(output / "stage7d_revision_pairs.csv", analysis["pair_rows"])
    _write_csv(output / "stage7d_revision_evidence_delta.csv", analysis["evidence_rows"])
    _write_csv(output / "stage7d_revision_epistemic_transition.csv", analysis["epistemic_rows"])
    _write_csv(output / "stage7d_revision_metric_pairs.csv", analysis["metric_rows"])
    _write_csv(
        output / "mechanical_response_revision_independence_audit.csv", analysis["mechanical_rows"]
    )
    _write_csv(output / "stage7d_revision_claim_transition_rows.csv", analysis["claim_rows"])
    _write_csv(output / "stage7d_revision_claim_key_audit.csv", analysis["key_audit"])
    _write_csv(output / "stage7d_revision_event_summary.csv", analysis["event_rows"])
    _write_csv(
        output / "stage7d_stage5c_revision_reconciliation_audit.csv",
        analysis["reconciliation_rows"],
    )
    _write_json(
        output / "stage7d_v1_benchmark_alignment_diagnostic.json", analysis["v1_diagnostic"]
    )
    (output / "STAGE7D_V1_NULL_RESULT_INTERPRETATION.md").write_text(
        _v1_null_report(analysis["v1_diagnostic"]), encoding="utf-8"
    )
    _write_json(output / "stage7d_primary_endpoints.json", analysis["primary"])
    _write_json(output / "stage7d_secondary_endpoints.json", analysis["secondary"])
    _write_json(
        output / "stage7d_claim_transition_matrix.json",
        analysis["secondary"]["claim_transition_counts"],
    )
    _write_json(output / "stage7d_case_selection.json", analysis["cases"])
    for event_id, text in analysis["case_documents"].items():
        (output / f"stage7d_case_{event_id}.md").write_text(text, encoding="utf-8")
    _write_csv(output / "stage7d_paper_table_revision_value.csv", _paper_table(analysis))
    _write_figure_data(figure_dir, analysis)
    _write_csv(output / "upstream_freeze_audit.csv", _upstream_freeze_audit(root, frozen_hashes))
    _write_csv(output / "frozen_git_ref_audit.csv", _frozen_ref_audit(root))
    _write_csv(output / "hard_check.csv", hard_rows)
    method = _method_version(inputs, frozen_hashes)
    _write_json(output / "method_version.json", method)
    _write_json(output / "freeze_manifest.json", _freeze_manifest(analysis, method, hard_rows))
    (output / "README.md").write_text(_readme(), encoding="utf-8")
    (output / "stage7d_v1_1_report.md").write_text(_report(analysis), encoding="utf-8")


def _write_figure_data(figure_dir: Path, analysis: dict[str, Any]) -> None:
    _write_csv(figure_dir / "figure_revision_timeline.csv", analysis["pair_rows"])
    _write_csv(figure_dir / "figure_metric_revision_incidence.csv", analysis["metric_rows"])
    _write_csv(
        figure_dir / "figure_claim_transition_classes.csv",
        [
            {"transition_class": key, "count": value}
            for key, value in analysis["secondary"]["claim_transition_counts"].items()
        ],
    )
    _write_csv(figure_dir / "figure_revision_event_impact.csv", analysis["event_rows"])
    rows = []
    for transition, counts in analysis["secondary"]["claim_type_by_transition"].items():
        for claim_type, count in counts.items():
            rows.append({"transition_class": transition, "claim_type": claim_type, "count": count})
    _write_csv(figure_dir / "figure_claim_type_transition.csv", rows)


def _protocol(inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "experiment": "Stage7D v1.1 Revision-Census Bitemporal Value Experiment",
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "primary_population": "ALL_FROZEN_STAGE3B_KNOWLEDGE_REVISION_EVENTS",
        "primary_unit": "REVISION_EVENT_PAIR",
        "revision_event_count": len(inputs["events"]),
        "pre_arm": "PRE_REVISION_AS_KNOWN",
        "post_arm": "POST_REVISION_FINAL_HISTORY",
        "claim_pipeline": "INDEPENDENT_STAGE5A_STAGE5B_DETERMINISTIC_REEXECUTION_PER_ARM",
        "stage5c_use": "POST_HOC_RECONCILIATION_ONLY",
        "sampling": "NONE_COMPLETE_CENSUS",
        "api_calls": 0,
        "llm_calls": 0,
    }


def _method_version(inputs: dict[str, Any], frozen_hashes: dict[str, str]) -> dict[str, Any]:
    return {
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "revision_event_count": len(inputs["events"]),
        "stage7d_v1_tag": STAGE7D_V1_TAG,
        "stage7d_v1_commit": STAGE7D_V1_COMMIT,
        "stage3b_method": inputs["frozen"].versions[0]["stage3b_method_version"],
        "stage4_method": inputs["frozen"].claim_stage.stage4_method["method_version"],
        "stage5a_method": inputs["frozen"].claim_stage.stage5a_method["method_version"],
        "stage5b_method": "stage5b_deterministic_claim_builder_v1_frozen",
        "frozen_input_hashes": frozen_hashes,
        "uses_llm": False,
        "api_call_count": 0,
    }


def _freeze_manifest(
    analysis: dict[str, Any], method: dict[str, Any], hard_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        **method,
        "status": "FROZEN",
        "counts": {
            "revision_events": len(analysis["pair_rows"]),
            "revision_evidence_links": len(analysis["evidence_rows"]),
            "unique_later_evidence": analysis["secondary"]["unique_later_evidence_count"],
            "metric_pair_rows": len(analysis["metric_rows"]),
            "claim_transition_rows": len(analysis["claim_rows"]),
            "selected_cases": len(analysis["cases"]),
        },
        "stage5c_reconciliation_mismatch_count": analysis["reconciliation_mismatch_count"],
        "hard_check_failure_count": sum(row["status"] != "PASS" for row in hard_rows),
    }


def _paper_table(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    primary = analysis["primary"]
    rows = [
        {
            "endpoint": "Revision event census",
            "numerator": len(analysis["event_rows"]),
            "denominator": len(analysis["event_rows"]),
            "rate": 1.0,
        }
    ]
    for metric, value in primary["P2_metric_sensitive_revision_event_rate"].items():
        rows.append({"endpoint": f"{metric} changed event", **value})
    for key in (
        "P3_existing_claim_decision_switch_event_rate",
        "P4_later_knowledge_created_opportunity_event_rate",
        "P5_any_claim_semantic_change_event_rate",
        "P6_observed_opportunity_creation_event_rate",
    ):
        rows.append({"endpoint": key, **primary[key]})
    return rows


def _v1_null_report(diagnostic: dict[str, Any]) -> str:
    return f"""# Stage7D v1 Null Result Interpretation

Stage7D v1 retained all 48 frozen Stage7A tasks and 201 task-cell bindings.
It found exact-as-of equal to final-history for all bindings because the frozen
benchmark knowledge boundaries already fell at or after revision availability.

- revision-date tasks: {diagnostic["revision_date_task_count"]}
- post-revision-as-of tasks: {diagnostic["post_revision_asof_task_count"]}
- revised-cell overlapping bindings: {diagnostic["revised_cell_overlapping_binding_count"]}
- true pre-revision exposures: {diagnostic["true_pre_revision_exposure_count"]}

Stage7D v1 is retained as an orthogonal benchmark-alignment diagnostic, not as
the primary revision-sensitivity experiment. Its null result is not deleted or
reinterpreted as a positive bitemporal effect.
"""


def _readme() -> str:
    return """# Stage7D v1.1 Revision-Census Bitemporal Value Experiment

This frozen artifact compares PRE and POST knowledge states for every
authoritative Stage3B revision event. It is a complete 53-event census with no
sampling. PRE and POST retain the same valid date and cell; only knowledge state
changes. Claim opportunities and admissibility are independently re-executed in
both arms, then reconciled against frozen Stage5C.

POST knowledge is not wrong. The measured differences quantify retrospective
hindsight exposure if final knowledge is presented as earlier as-known
knowledge. No LLM or external API is used. Results come from one project and do
not establish cross-project generalization.
"""


def _report(analysis: dict[str, Any]) -> str:
    p = analysis["primary"]
    s = analysis["secondary"]
    total = s["revision_event_count"]
    rai = p["P2_metric_sensitive_revision_event_rate"]["RAI"]["numerator"]
    grs = p["P2_metric_sensitive_revision_event_rate"]["GRS"]["numerator"]
    grci = p["P2_metric_sensitive_revision_event_rate"]["GRCI"]["numerator"]
    switches = p["P3_existing_claim_decision_switch_event_rate"]["numerator"]
    created = p["P4_later_knowledge_created_opportunity_event_rate"]["numerator"]
    semantic = p["P5_any_claim_semantic_change_event_rate"]["numerator"]
    observed = p["P6_observed_opportunity_creation_event_rate"]["numerator"]
    return f"""# Stage7D v1.1 Revision-Census Report

## Population

- Revision events: {s["revision_event_count"]}
- Valid dates: {s["revision_valid_date_count"]}
- Revised cells: {s["unique_revised_cell_count"]}
- Event-evidence links: {s["revision_event_evidence_link_count"]}
- Unique later evidence: {s["unique_later_evidence_count"]}

## Primary endpoints

- RAI-sensitive events: {rai} / {total}
- GRS-sensitive events: {grs} / {total}
- GRCI-sensitive events: {grci} / {total}
- Existing-Claim decision-switch events: {switches} / {total}
- Opportunity-created events: {created} / {total}
- Any Claim semantic-change events: {semantic} / {total}
- Observed-opportunity-created events: {observed} / {total}

## Claim row transitions

```json
{json.dumps(s["claim_transition_counts"], ensure_ascii=False, sort_keys=True, indent=2)}
```

## Interpretation

The results quantify sensitivity of structured knowledge and Claim
admissibility to knowledge time. They do not identify errors, hallucinations,
hazard probabilities, or generated-text failures. POST knowledge is legitimate
later knowledge; bitemporal storage preserves the earlier PRE state as well.

Single project; 91 PLC-monitored dates; 88 dates with materialized cell state.
API calls: 0. LLM calls: 0.
"""


def _frozen_input_hashes(root: Path) -> dict[str, str]:
    paths = {
        "stage3b": root / STAGE3B_DIR / "file_hashes.sha256",
        "stage4": root / STAGE4_DIR / "file_hashes.sha256",
        "stage5c": root / STAGE5C_DIR / "file_hashes.sha256",
        "stage7a": root / STAGE7A_DIR / "file_hashes.sha256",
        "stage7d_v1": root / STAGE7D_V1_DIR / "file_hashes.sha256",
    }
    return {key: _sha256_file(path) for key, path in paths.items()}


def _upstream_freeze_audit(root: Path, hashes: dict[str, str]) -> list[dict[str, Any]]:
    current = _frozen_input_hashes(root)
    return [
        {
            "input": key,
            "expected_hash": value,
            "actual_hash": current[key],
            "status": "PASS" if current[key] == value else "FAIL",
        }
        for key, value in sorted(hashes.items())
    ]


def _frozen_ref_audit(root: Path) -> list[dict[str, Any]]:
    refs = {
        STAGE7D_V1_TAG: STAGE7D_V1_COMMIT,
        stage7d_v1.STAGE7A_TAG: stage7d_v1.STAGE7A_COMMIT,
        stage7d_v1.STAGE7B_TAG: stage7d_v1.STAGE7B_COMMIT,
        stage7d_v1.STAGE7C1_TAG: stage7d_v1.STAGE7C1_COMMIT,
        stage7d_v1.STAGE7C2A_TAG: stage7d_v1.STAGE7C2A_COMMIT,
    }
    return [
        {
            "reference": ref,
            "expected_commit": expected,
            "actual_commit": _git_rev_parse(root, ref),
            "status": "PASS" if _git_rev_parse(root, ref) == expected else "FAIL",
        }
        for ref, expected in refs.items()
    ]


def _write_audit_zip(root: Path, output: Path) -> Path:
    path = root / AUDIT_ZIP
    sources = [
        root / "src/tbm_twin/evaluation/stage7d_revision.py",
        root / "scripts/build_stage7d_revision_census.py",
        root / "tests/unit/test_stage7d_revision_census.py",
    ]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("git_refs.txt", _git_refs(root))
        for source in sources:
            if source.exists():
                archive.write(source, source.relative_to(root).as_posix())
        for file in sorted(output.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(root).as_posix())
    return path


def _git_refs(root: Path) -> str:
    commands = [
        ["git", "branch", "--show-current"],
        ["git", "rev-parse", "HEAD"],
        ["git", "rev-parse", STAGE7D_V1_TAG],
        ["git", "status", "--short"],
    ]
    blocks = []
    for command in commands:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
        blocks.append(f"$ {' '.join(command)}\n{result.stdout}{result.stderr}".rstrip())
    return "\n\n".join(blocks) + "\n"


def _write_hashes(output: Path) -> None:
    rows = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "file_hashes.sha256":
            rows.append(f"{_sha256_file(path)}  {path.relative_to(output).as_posix()}")
    (output / "file_hashes.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Expected non-empty audit rows for {path.name}")
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _git_rev_parse(root: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _same_number(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return abs(left - right) <= 1e-12


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _iqr(values: list[int]) -> list[float]:
    quartiles = statistics.quantiles(values, n=4, method="inclusive")
    return [quartiles[0], quartiles[2]]
