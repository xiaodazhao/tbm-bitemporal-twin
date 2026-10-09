# ruff: noqa: RUF001
"""Read-only experiments for construction progression and availability time.

The experiment consumes frozen Stage 2/3/7 artifacts. It does not rebuild or
mutate any upstream object and does not assess geological forecast accuracy.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter, MaxNLocator

STAGE2_GEOLOGY_DIR = Path("artifacts/stage2_geology_v2_freeze_candidate")
STAGE2_PLC_DIR = Path("artifacts/stage2_plc_operational_freeze_v2")
STAGE3A_DIR = Path("artifacts/stage3a_initial_epistemic_state_v1_1")
STAGE3B_DIR = Path("artifacts/stage3b_bitemporal_epistemic_state_v1_1")
STAGE7D_DIR = Path("artifacts/stage7d_bitemporal_value_v1_1")

FORECAST_SOURCE_TYPES = frozenset({"SONIC_FORECAST", "TSP_REPORT"})
OBSERVATION_SOURCE_TYPES = frozenset({"FACE_SKETCH"})


def build_construction_progression_review(
    repo_root: Path,
    output_dir: Path,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Build the multi-stage association experiment from frozen objects."""

    stage3a = repo_root / STAGE3A_DIR
    geology_dir = repo_root / STAGE2_GEOLOGY_DIR
    plc_dir = repo_root / STAGE2_PLC_DIR

    states = _read_jsonl(stage3a / "initial_construction_state_versions.jsonl")
    cells = {
        str(row["cell_id"]): row for row in _read_jsonl(stage3a / "construction_state_cells.jsonl")
    }
    geology_links = _read_jsonl(stage3a / "state_geological_evidence_links.jsonl")
    response_links = _read_jsonl(stage3a / "state_response_evidence_links.jsonl")
    evidence = {
        str(row["evidence_uid"]): row
        for row in _read_jsonl(geology_dir / "primary_geological_evidence.jsonl")
    }
    documents = {
        str(row["document_id"]): row
        for row in _read_jsonl(geology_dir / "geological_documents.jsonl")
    }
    responses = {
        str(row["evidence_id"]): row for row in _read_jsonl(plc_dir / "response_evidence.jsonl")
    }

    geology_by_state: dict[str, list[dict[str, Any]]] = defaultdict(list)
    response_by_state: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in geology_links:
        geology_by_state[str(row["state_version_id"])].append(row)
    for row in response_links:
        response_by_state[str(row["state_version_id"])].append(row)

    comparison_dimensions = settings["comparison_dimensions"]
    context_rows: list[dict[str, Any]] = []
    association_rows: list[dict[str, Any]] = []
    field_rows: list[dict[str, Any]] = []
    response_rows: list[dict[str, Any]] = []

    for state in states:
        if not _is_candidate_daily_review_state(state):
            continue
        state_id = str(state["state_version_id"])
        target_date = str(state["target_date"])
        forecast_links: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        observation_links: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        for link in geology_by_state[state_id]:
            if str(link["applicability_role"]) != "DAILY_REVIEW":
                continue
            item = evidence[str(link["evidence_id"])]
            document = documents[str(item["document_id"])]
            temporal = document["document"]["temporal"]
            available_date = _optional_text(temporal.get("available_local_date"))
            if (
                str(item["epistemic_status"]) == "FORECAST"
                and str(item["source_type"]) in FORECAST_SOURCE_TYPES
                and str(item["evidence_type"]) == "FORECAST_SEGMENT"
                and available_date is not None
                and available_date < target_date
            ):
                forecast_links.append((link, item, document))
            if (
                str(item["epistemic_status"]) == "OBSERVED"
                and str(item["source_type"]) in OBSERVATION_SOURCE_TYPES
                and str(item["evidence_type"]) == "FACE_OBSERVATION"
                and available_date is not None
                and available_date <= target_date
            ):
                observation_links.append((link, item, document))
        if not forecast_links or not observation_links:
            continue

        pairs: list[dict[str, Any]] = []
        for forecast_link, forecast, forecast_document in forecast_links:
            for observation_link, observation, observation_document in observation_links:
                relation = _scope_relation(forecast["spatial_scope"], observation["spatial_scope"])
                observation_temporal = observation_document["document"]["temporal"]
                same_day_observation = (
                    _optional_text(observation_temporal.get("observed_local_date")) == target_date
                )
                tier = _association_tier(same_day_observation, relation)
                association_id = _stable_id(
                    "progression_association",
                    state_id,
                    str(forecast["evidence_uid"]),
                    str(observation["evidence_uid"]),
                )
                pair = {
                    "association_id": association_id,
                    "state_version_id": state_id,
                    "daily_state_id": state["daily_state_id"],
                    "target_date": target_date,
                    "cell_id": state["cell_id"],
                    "forecast_evidence_id": forecast["evidence_uid"],
                    "forecast_document_id": forecast["document_id"],
                    "forecast_filename": forecast["filename"],
                    "forecast_source_type": forecast["source_type"],
                    "forecast_available_local_date": forecast_document["document"]["temporal"][
                        "available_local_date"
                    ],
                    "forecast_start": forecast["spatial_scope"]["start_chainage"],
                    "forecast_end": forecast["spatial_scope"]["end_chainage"],
                    "forecast_link_role": forecast_link["applicability_role"],
                    "observation_evidence_id": observation["evidence_uid"],
                    "observation_document_id": observation["document_id"],
                    "observation_filename": observation["filename"],
                    "observation_observed_local_date": observation_temporal["observed_local_date"],
                    "observation_available_local_date": observation_temporal[
                        "available_local_date"
                    ],
                    "observation_scope": observation.get("attributes", {}).get("observation_scope"),
                    "observation_spatial_kind": observation["spatial_scope"]["kind"],
                    "observation_start": observation["spatial_scope"]["start_chainage"],
                    "observation_end": observation["spatial_scope"]["end_chainage"],
                    "observation_link_role": observation_link["applicability_role"],
                    "spatial_relation": relation["relation"],
                    "direct_overlap_start": relation["overlap_start"],
                    "direct_overlap_end": relation["overlap_end"],
                    "same_day_observation": same_day_observation,
                    "association_tier": tier,
                    "forecast_identity_preserved": True,
                    "observation_identity_preserved": True,
                    "forecast_accuracy_judged": False,
                    "mechanical_cause_inferred": False,
                }
                pairs.append(pair)
                association_rows.append(pair)
                for dimension_name, field_config in comparison_dimensions.items():
                    forecast_field, forecast_value = _first_recorded_value(
                        forecast.get("attributes", {}), field_config["forecast_fields"]
                    )
                    observation_field, observation_value = _first_recorded_value(
                        observation.get("attributes", {}), field_config["observation_fields"]
                    )
                    field_rows.append(
                        _field_relation_row(
                            association_id,
                            state_id,
                            target_date,
                            str(dimension_name),
                            forecast_field,
                            forecast_value,
                            observation_field,
                            observation_value,
                            relation["relation"],
                        )
                    )

        context_tier = _context_tier(pairs)
        cell = cells[str(state["cell_id"])]
        state_response_links = response_by_state[state_id]
        context_id = _stable_id("progression_context", state_id)
        context_rows.append(
            {
                "context_id": context_id,
                "state_version_id": state_id,
                "daily_state_id": state["daily_state_id"],
                "target_date": target_date,
                "cell_id": state["cell_id"],
                "cell_start": cell["spatial_start"],
                "cell_end": cell["spatial_end"],
                "episode_count": len(state["episode_ids"]),
                "episode_ids": ";".join(sorted(str(value) for value in state["episode_ids"])),
                "response_evidence_count": len(state["response_evidence_ids"]),
                "response_channel_count": len(
                    {str(link["channel_name"]) for link in state_response_links}
                ),
                "forecast_evidence_count": len(forecast_links),
                "observation_evidence_count": len(observation_links),
                "state_specific_association_count": len(pairs),
                "direct_overlap_association_count": sum(
                    pair["spatial_relation"] == "DIRECT_SCOPE_OVERLAP" for pair in pairs
                ),
                "same_day_direct_association_count": sum(
                    pair["association_tier"] == "SAME_DAY_DIRECT" for pair in pairs
                ),
                "context_tier": context_tier,
                "strict_primary_context": context_tier == "SAME_DAY_DIRECT",
                "interpretation": _context_interpretation(context_tier),
            }
        )
        for link in state_response_links:
            response = responses[str(link["response_evidence_id"])]
            statistics = response.get("statistics", {})
            response_rows.append(
                {
                    "context_id": context_id,
                    "state_version_id": state_id,
                    "target_date": target_date,
                    "cell_id": state["cell_id"],
                    "episode_id": response["episode_id"],
                    "response_evidence_id": response["evidence_id"],
                    "channel_name": response["channel_name"],
                    "median": statistics.get("median"),
                    "p90": statistics.get("p90"),
                    "minimum": statistics.get("minimum"),
                    "maximum": statistics.get("maximum"),
                    "sample_count": statistics.get("sample_count"),
                    "unit": response.get("unit"),
                    "unit_confidence": response.get("unit_confidence"),
                    "quality_grade": response.get("quality_grade"),
                    "mechanical_cause_inferred": False,
                }
            )

    unique_pair_rows = _unique_evidence_pairs(association_rows)
    _write_csv(output_dir / "construction_progression_contexts.csv", context_rows)
    _write_csv(output_dir / "construction_progression_associations.csv", association_rows)
    _write_csv(output_dir / "construction_progression_unique_evidence_pairs.csv", unique_pair_rows)
    _write_csv(output_dir / "construction_progression_field_relations.csv", field_rows)
    _write_csv(output_dir / "construction_progression_response_profiles.csv", response_rows)

    case_rows = _select_cases(context_rows, association_rows, field_rows, settings)
    _write_csv(output_dir / "construction_progression_case_selection.csv", case_rows)
    _write_case_files(output_dir, case_rows, association_rows, field_rows, response_rows)
    _write_progression_figures(output_dir, context_rows, association_rows, case_rows)

    summary = _progression_summary(context_rows, association_rows, unique_pair_rows, field_rows)
    _write_json(output_dir / "construction_progression_summary.json", summary)
    (output_dir / "construction_progression_report.md").write_text(
        _render_progression_report(summary), encoding="utf-8"
    )
    return summary


def build_availability_time_sensitivity(
    repo_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Compare documented availability with an optimistic same-day assumption."""

    stage3b = repo_root / STAGE3B_DIR
    stage7d = repo_root / STAGE7D_DIR
    events = {
        str(row["revision_event_id"]): row
        for row in _read_jsonl(stage3b / "knowledge_revision_events.jsonl")
    }
    event_summary = pd.read_csv(stage7d / "stage7d_revision_event_summary.csv")
    revision_pairs = pd.read_csv(stage7d / "stage7d_revision_pairs.csv", keep_default_na=False)
    evidence_delta = pd.read_csv(
        stage7d / "stage7d_revision_evidence_delta.csv", keep_default_na=False
    )
    pair_by_event = {
        str(row["revision_event_id"]): row for row in revision_pairs.to_dict("records")
    }
    link_count_by_event = Counter(
        str(value) for value in evidence_delta["revision_event_id"].tolist()
    )
    delta_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for delta_row in evidence_delta.to_dict("records"):
        delta_by_event[str(delta_row["revision_event_id"])].append(delta_row)
    rows: list[dict[str, Any]] = []
    latest_vs_as_known_rows: list[dict[str, Any]] = []
    for row in event_summary.to_dict("records"):
        event_id = str(row["revision_event_id"])
        event = events[event_id]
        pair = pair_by_event[event_id]
        observed_date = str(event["observed_local_date"])
        valid_date = str(row["valid_date"])
        optimistic_preincluded = observed_date <= valid_date
        rows.append(
            {
                "revision_event_id": event_id,
                "valid_date": valid_date,
                "cell_id": row["cell_id"],
                "state_role": pair["state_role"],
                "source_type": event["source_type"],
                "document_id": event["document_id"],
                "observed_local_date": observed_date,
                "documented_available_local_date": event["available_local_date"],
                "documented_available_basis": event["available_basis"],
                "documented_delay_days": row["knowledge_delay_days"],
                "documented_policy_revision_occurs": True,
                "optimistic_assumption": "OBSERVED_DATE_AVAILABLE_BY_END_OF_DAY",
                "optimistic_available_local_date": observed_date,
                "optimistic_evidence_preincluded_in_initial_state": optimistic_preincluded,
                "optimistic_later_revision_occurs": not optimistic_preincluded,
                "added_evidence_link_count": link_count_by_event[event_id],
                "rai_changed_between_documented_pre_post": row["rai_changed"],
                "grs_changed_between_documented_pre_post": row["grs_changed"],
                "grci_changed_between_documented_pre_post": row["grci_changed"],
                "decision_switch_count": row["decision_switch_count"],
                "opportunity_added_count": row["opportunity_added_count"],
                "claim_value_change_count": row["claim_value_change_count"],
                "support_change_count": row["support_change_count"],
                "interpretation": (
                    "Post-version evidence would be present in the initial end-of-day view; "
                    "the documented next-day revision would collapse under this counterfactual."
                    if optimistic_preincluded
                    else "Revision remains later under the optimistic assumption."
                ),
            }
        )
        for delta_row in delta_by_event[event_id]:
            latest_vs_as_known_rows.append(
                {
                    "revision_event_id": event_id,
                    "valid_date": valid_date,
                    "cell_id": row["cell_id"],
                    "as_known_version_id": pair["pre_version_id"],
                    "latest_version_id": pair["post_version_id"],
                    "evidence_id": delta_row["evidence_id"],
                    "source_type": delta_row["source_type"],
                    "epistemic_status": delta_row["epistemic_status"],
                    "documented_available_local_date": delta_row["available_local_date"],
                    "present_in_as_known_state": _as_bool(delta_row["present_in_pre"]),
                    "present_in_latest_state": _as_bool(delta_row["present_in_post"]),
                    "using_latest_for_as_known_would_leak": bool(
                        not _as_bool(delta_row["present_in_pre"])
                        and _as_bool(delta_row["present_in_post"])
                    ),
                    "provenance_resolved": _as_bool(delta_row["provenance_resolved"]),
                    "interpretation": (
                        "Evidence is absent from the as-known state and present only after its "
                        "documented availability boundary."
                    ),
                }
            )
    _write_csv(output_dir / "availability_time_sensitivity.csv", rows)
    _write_csv(output_dir / "latest_state_vs_as_known_audit.csv", latest_vs_as_known_rows)
    summary = {
        "documented_revision_event_count": len(rows),
        "documented_delay_distribution_days": dict(
            sorted(Counter(int(row["documented_delay_days"]) for row in rows).items())
        ),
        "optimistic_revision_event_count": sum(
            bool(row["optimistic_later_revision_occurs"]) for row in rows
        ),
        "revision_events_collapsed_under_optimistic_assumption": sum(
            bool(row["optimistic_evidence_preincluded_in_initial_state"]) for row in rows
        ),
        "added_evidence_link_count": sum(int(row["added_evidence_link_count"]) for row in rows),
        "documented_pre_post_rai_change_count": sum(
            _as_bool(row["rai_changed_between_documented_pre_post"]) for row in rows
        ),
        "documented_pre_post_grs_change_count": sum(
            _as_bool(row["grs_changed_between_documented_pre_post"]) for row in rows
        ),
        "documented_pre_post_grci_change_count": sum(
            _as_bool(row["grci_changed_between_documented_pre_post"]) for row in rows
        ),
        "decision_switch_count": sum(int(row["decision_switch_count"]) for row in rows),
        "opportunity_added_count": sum(int(row["opportunity_added_count"]) for row in rows),
        "claim_value_change_count": sum(int(row["claim_value_change_count"]) for row in rows),
        "support_change_count": sum(int(row["support_change_count"]) for row in rows),
        "latest_vs_as_known_evidence_row_count": len(latest_vs_as_known_rows),
        "latest_for_as_known_leak_count": sum(
            bool(row["using_latest_for_as_known_would_leak"]) for row in latest_vs_as_known_rows
        ),
        "latest_vs_as_known_provenance_unresolved_count": sum(
            not bool(row["provenance_resolved"]) for row in latest_vs_as_known_rows
        ),
        "scope_note": (
            "This is a deterministic counterfactual over documented pre/post pairs, not a claim "
            "about when site personnel first knew the information."
        ),
    }
    _write_json(output_dir / "availability_time_sensitivity_summary.json", summary)
    (output_dir / "availability_time_sensitivity_report.md").write_text(
        _render_availability_report(summary), encoding="utf-8"
    )
    _write_availability_figure(output_dir, summary)
    return summary


def write_paper_experiment_hard_check(
    output_dir: Path,
    progression: dict[str, Any],
    availability: dict[str, Any],
) -> list[dict[str, str]]:
    """Write explicit validity checks for the two supplementary experiments."""

    checks = [
        _check_row(
            "STRICT_PROGRESSION_CONTEXTS_EXIST",
            progression["strict_same_day_direct_context_count"] > 0,
            f"count={progression['strict_same_day_direct_context_count']}",
        ),
        _check_row(
            "FORECAST_EPISTEMIC_IDENTITY_PRESERVED",
            progression["forecast_identity_violation_count"] == 0,
            f"violations={progression['forecast_identity_violation_count']}",
        ),
        _check_row(
            "STRICT_FORECAST_AVAILABLE_BEFORE_EXCAVATION",
            progression["strict_forecast_not_earlier_count"] == 0,
            f"violations={progression['strict_forecast_not_earlier_count']}",
        ),
        _check_row(
            "STRICT_OBSERVATION_IS_SAME_DAY",
            progression["strict_observation_not_same_day_count"] == 0,
            f"violations={progression['strict_observation_not_same_day_count']}",
        ),
        _check_row(
            "STRICT_EVIDENCE_SCOPES_OVERLAP",
            progression["strict_nonoverlap_count"] == 0,
            f"violations={progression['strict_nonoverlap_count']}",
        ),
        _check_row(
            "OBSERVATION_EPISTEMIC_IDENTITY_PRESERVED",
            progression["observation_identity_violation_count"] == 0,
            f"violations={progression['observation_identity_violation_count']}",
        ),
        _check_row(
            "NO_FORECAST_ACCURACY_JUDGMENT",
            progression["forecast_accuracy_claim_count"] == 0,
            f"claims={progression['forecast_accuracy_claim_count']}",
        ),
        _check_row(
            "NO_MECHANICAL_TO_GEOLOGICAL_CAUSAL_INFERENCE",
            progression["mechanical_cause_inference_count"] == 0,
            f"inferences={progression['mechanical_cause_inference_count']}",
        ),
        _check_row(
            "DOCUMENTED_REVISION_SET_RECONCILED",
            availability["documented_revision_event_count"] == 53,
            f"events={availability['documented_revision_event_count']}",
        ),
        _check_row(
            "LATEST_VS_AS_KNOWN_PROVENANCE_RESOLVED",
            availability["latest_vs_as_known_provenance_unresolved_count"] == 0,
            (f"unresolved={availability['latest_vs_as_known_provenance_unresolved_count']}"),
        ),
    ]
    _write_csv(output_dir / "paper_experiment_hard_check.csv", checks)
    return checks


def _check_row(check_name: str, passed: bool, details: str) -> dict[str, str]:
    return {"check_name": check_name, "status": "PASS" if passed else "FAIL", "details": details}


def classify_field_relation(
    forecast_value: Any,
    observation_value: Any,
    spatial_relation: str,
) -> str:
    """Classify recorded values without judging forecast correctness."""

    if spatial_relation != "DIRECT_SCOPE_OVERLAP":
        return "SPATIAL_SCALE_NOT_DIRECTLY_COMPARABLE"
    forecast_missing = _is_missing(forecast_value)
    observation_missing = _is_missing(observation_value)
    if forecast_missing and observation_missing:
        return "BOTH_UNRECORDED"
    if forecast_missing:
        return "OBSERVATION_SIDE_ONLY"
    if observation_missing:
        return "FORECAST_SIDE_ONLY"
    if _normalize_value(forecast_value) == _normalize_value(observation_value):
        return "SAME_RECORDED_VALUE"
    return "DIFFERENT_RECORDED_VALUE"


def scope_relation(first: dict[str, Any], second: dict[str, Any]) -> str:
    """Public test seam for direct evidence-scope comparison."""

    return str(_scope_relation(first, second)["relation"])


def _is_candidate_daily_review_state(state: dict[str, Any]) -> bool:
    return bool(
        state.get("cell_scope_role") == "DAILY_REVIEW_CELL"
        and state.get("episode_ids")
        and state.get("response_evidence_ids")
    )


def _scope_relation(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    first_start = float(first["start_chainage"])
    first_end = float(first["end_chainage"])
    second_start = float(second["start_chainage"])
    second_end = float(second["end_chainage"])
    overlap_start = max(first_start, second_start)
    overlap_end = min(first_end, second_end)
    if overlap_start <= overlap_end:
        return {
            "relation": "DIRECT_SCOPE_OVERLAP",
            "overlap_start": overlap_start,
            "overlap_end": overlap_end,
        }
    return {
        "relation": "SHARED_DAILY_REVIEW_CELL_ONLY",
        "overlap_start": None,
        "overlap_end": None,
    }


def _association_tier(same_day_observation: bool, relation: dict[str, Any]) -> str:
    if same_day_observation and relation["relation"] == "DIRECT_SCOPE_OVERLAP":
        return "SAME_DAY_DIRECT"
    if same_day_observation:
        return "SAME_DAY_SHARED_CELL_ONLY"
    return "PRIOR_OBSERVATION_CONTEXT"


def _context_tier(pairs: list[dict[str, Any]]) -> str:
    tiers = {str(pair["association_tier"]) for pair in pairs}
    if "SAME_DAY_DIRECT" in tiers:
        return "SAME_DAY_DIRECT"
    if "SAME_DAY_SHARED_CELL_ONLY" in tiers:
        return "SAME_DAY_SHARED_CELL_ONLY"
    return "PRIOR_OBSERVATION_CONTEXT"


def _context_interpretation(tier: str) -> str:
    if tier == "SAME_DAY_DIRECT":
        return "STRICT_PROGRESS_REVIEW_CONTEXT"
    if tier == "SAME_DAY_SHARED_CELL_ONLY":
        return "SAME_DAY_CONTEXT_WITHOUT_DIRECT_EVIDENCE_SCOPE_OVERLAP"
    return "HISTORICAL_OBSERVATION_CONTEXT_NOT_SAME_DAY_REVEAL"


def _field_relation_row(
    association_id: str,
    state_id: str,
    target_date: str,
    field_name: str,
    forecast_source_field: str | None,
    forecast_value: Any,
    observation_source_field: str | None,
    observation_value: Any,
    spatial_relation: str,
) -> dict[str, Any]:
    return {
        "association_id": association_id,
        "state_version_id": state_id,
        "target_date": target_date,
        "field_name": field_name,
        "forecast_source_field": forecast_source_field,
        "forecast_value": _json_cell(forecast_value),
        "observation_source_field": observation_source_field,
        "observation_value": _json_cell(observation_value),
        "relation": classify_field_relation(forecast_value, observation_value, spatial_relation),
        "forecast_accuracy_judged": False,
        "engineering_cause_inferred": False,
    }


def _first_recorded_value(
    attributes: dict[str, Any], candidate_fields: list[str]
) -> tuple[str | None, Any]:
    for field_name in candidate_fields:
        value = attributes.get(field_name)
        if not _is_missing(value):
            return str(field_name), value
    return None, None


def _unique_evidence_pairs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["forecast_evidence_id"]), str(row["observation_evidence_id"]))].append(row)
    result: list[dict[str, Any]] = []
    for (forecast_id, observation_id), group in sorted(grouped.items()):
        result.append(
            {
                "forecast_evidence_id": forecast_id,
                "observation_evidence_id": observation_id,
                "state_context_count": len(group),
                "state_version_ids": ";".join(
                    sorted({str(row["state_version_id"]) for row in group})
                ),
                "target_dates": ";".join(sorted({str(row["target_date"]) for row in group})),
                "spatial_relations": ";".join(
                    sorted({str(row["spatial_relation"]) for row in group})
                ),
                "association_tiers": ";".join(
                    sorted({str(row["association_tier"]) for row in group})
                ),
                "is_independent_statistical_sample": False,
            }
        )
    return result


def _select_cases(
    contexts: list[dict[str, Any]],
    associations: list[dict[str, Any]],
    fields: list[dict[str, Any]],
    settings: dict[str, Any],
) -> list[dict[str, Any]]:
    strict_contexts = {
        str(row["state_version_id"]): row for row in contexts if row["strict_primary_context"]
    }
    field_by_state: dict[str, list[dict[str, Any]]] = defaultdict(list)
    association_by_state: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fields:
        field_by_state[str(row["state_version_id"])].append(row)
    for row in associations:
        association_by_state[str(row["state_version_id"])].append(row)

    selected: list[str] = []
    fixed_date = str(settings.get("fixed_case_target_date", ""))
    fixed_chainage = float(settings.get("fixed_case_chainage", 0.0))
    for state_id, context in strict_contexts.items():
        if str(context["target_date"]) == fixed_date and float(
            context["cell_start"]
        ) <= fixed_chainage <= float(context["cell_end"]):
            selected.append(state_id)
            break
    ranked = sorted(
        strict_contexts,
        key=lambda state_id: (
            -sum(row["relation"] == "DIFFERENT_RECORDED_VALUE" for row in field_by_state[state_id]),
            -sum(row["relation"] == "OBSERVATION_SIDE_ONLY" for row in field_by_state[state_id]),
            str(strict_contexts[state_id]["target_date"]),
            state_id,
        ),
    )
    for state_id in ranked:
        if state_id not in selected:
            selected.append(state_id)
        if len(selected) >= int(settings.get("case_count", 3)):
            break

    rows: list[dict[str, Any]] = []
    for index, state_id in enumerate(selected, start=1):
        context = strict_contexts[state_id]
        direct = [
            row
            for row in association_by_state[state_id]
            if row["association_tier"] == "SAME_DAY_DIRECT"
        ]
        rows.append(
            {
                "case_id": f"progression_case_{index:02d}",
                "state_version_id": state_id,
                "target_date": context["target_date"],
                "cell_id": context["cell_id"],
                "cell_start": context["cell_start"],
                "cell_end": context["cell_end"],
                "direct_association_count": len(direct),
                "selection_reason": (
                    "FIXED_REAL_CASE_DYK1013_320"
                    if index == 1 and fixed_date
                    else "FIELD_RELATION_DIVERSITY"
                ),
            }
        )
    return rows


def _write_case_files(
    output_dir: Path,
    cases: list[dict[str, Any]],
    associations: list[dict[str, Any]],
    fields: list[dict[str, Any]],
    responses: list[dict[str, Any]],
) -> None:
    case_dir = output_dir / "construction_progression_cases"
    case_dir.mkdir(parents=True, exist_ok=True)
    for case in cases:
        state_id = str(case["state_version_id"])
        case_associations = [
            row
            for row in associations
            if row["state_version_id"] == state_id and row["association_tier"] == "SAME_DAY_DIRECT"
        ]
        association_ids = {str(row["association_id"]) for row in case_associations}
        case_fields = [row for row in fields if row["association_id"] in association_ids]
        case_responses = [row for row in responses if row["state_version_id"] == state_id]
        payload = {
            "case": case,
            "associations": case_associations,
            "field_relations": case_fields,
            "mechanical_response_descriptors": case_responses,
            "interpretation_limits": [
                "No geological forecast accuracy is calculated.",
                "No mechanical response is interpreted as a geological cause.",
                "Point observations are not expanded to the full forecast interval.",
            ],
        }
        _write_json(case_dir / f"{case['case_id']}.json", payload)
        lines = [
            f"# {case['case_id']}",
            "",
            f"- 施工日期：`{case['target_date']}`",
            f"- 空间单元：`{case['cell_start']}–{case['cell_end']}`",
            f"- 状态版本：`{state_id}`",
            "",
            "## 信息链",
            "",
        ]
        for row in case_associations:
            lines.extend(
                [
                    f"- 施工前预测：`{row['forecast_filename']}`，"
                    f"{row['forecast_start']}–{row['forecast_end']}，"
                    f"于 {row['forecast_available_local_date']} 前已可用。",
                    f"- 同日观察：`{row['observation_filename']}`，"
                    f"{row['observation_start']}–{row['observation_end']}。",
                ]
            )
        lines.extend(["- 实际施工：存在冻结的PLC掘进事件及机械响应。", "", "## 字段记录", ""])
        lines.append("| 字段 | 施工前预测 | 同日观察 | 中性关系 |")
        lines.append("|---|---|---|---|")
        for row in case_fields:
            if row["relation"] != "BOTH_UNRECORDED":
                lines.append(
                    f"| {row['field_name']} | {row['forecast_value'] or '—'} | "
                    f"{row['observation_value'] or '—'} | {row['relation']} |"
                )
        lines.extend(
            [
                "",
                "本案例仅展示不同阶段记录的并列关系，不判断预报准确率，"
                "也不根据机械响应推断地质原因。",
            ]
        )
        (case_dir / f"{case['case_id']}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _progression_summary(
    contexts: list[dict[str, Any]],
    associations: list[dict[str, Any]],
    unique_pairs: list[dict[str, Any]],
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    strict_associations = [
        row for row in associations if row["association_tier"] == "SAME_DAY_DIRECT"
    ]
    strict_state_ids = {str(row["state_version_id"]) for row in strict_associations}
    strict_association_ids = {str(row["association_id"]) for row in strict_associations}
    strict_field_rows = [
        row for row in fields if str(row["association_id"]) in strict_association_ids
    ]
    return {
        "broad_daily_review_context_count": len(contexts),
        "strict_same_day_direct_context_count": len(strict_state_ids),
        "prior_observation_context_count": sum(
            row["context_tier"] == "PRIOR_OBSERVATION_CONTEXT" for row in contexts
        ),
        "same_day_shared_cell_only_context_count": sum(
            row["context_tier"] == "SAME_DAY_SHARED_CELL_ONLY" for row in contexts
        ),
        "state_specific_association_count": len(associations),
        "unique_evidence_pair_count": len(unique_pairs),
        "strict_same_day_direct_association_count": len(strict_associations),
        "strict_forecast_not_earlier_count": sum(
            str(row["forecast_available_local_date"]) >= str(row["target_date"])
            for row in strict_associations
        ),
        "strict_observation_not_same_day_count": sum(
            str(row["observation_observed_local_date"]) != str(row["target_date"])
            for row in strict_associations
        ),
        "strict_nonoverlap_count": sum(
            str(row["spatial_relation"]) != "DIRECT_SCOPE_OVERLAP" for row in strict_associations
        ),
        "strict_unique_construction_date_count": len(
            {str(row["target_date"]) for row in contexts if row["strict_primary_context"]}
        ),
        "strict_unique_cell_count": len(
            {str(row["cell_id"]) for row in contexts if row["strict_primary_context"]}
        ),
        "forecast_source_type_distribution": dict(
            sorted(Counter(str(row["forecast_source_type"]) for row in associations).items())
        ),
        "strict_forecast_source_type_distribution": dict(
            sorted(Counter(str(row["forecast_source_type"]) for row in strict_associations).items())
        ),
        "strict_field_relation_distribution": dict(
            sorted(Counter(str(row["relation"]) for row in strict_field_rows).items())
        ),
        "forecast_identity_violation_count": sum(
            not bool(row["forecast_identity_preserved"]) for row in associations
        ),
        "observation_identity_violation_count": sum(
            not bool(row["observation_identity_preserved"]) for row in associations
        ),
        "forecast_accuracy_claim_count": sum(
            bool(row["forecast_accuracy_judged"]) for row in associations
        ),
        "mechanical_cause_inference_count": sum(
            bool(row["mechanical_cause_inferred"]) for row in associations
        ),
        "unit_of_analysis_note": (
            "Contexts are date-cell states; state-specific associations and unique evidence pairs "
            "are not independent statistical samples."
        ),
    }


def _write_progression_figures(
    output_dir: Path,
    contexts: list[dict[str, Any]],
    associations: list[dict[str, Any]],
    cases: list[dict[str, Any]],
) -> None:
    plt.rcParams.update(
        {
            "font.family": "Arial Unicode MS",
            "axes.unicode_minus": False,
            "svg.hashsalt": "paper_evidence_completion_v2",
        }
    )
    counts = Counter(str(row["context_tier"]) for row in contexts)
    labels = ["同日且范围直接对应", "既有现场观察背景"]
    values = [counts["SAME_DAY_DIRECT"], counts["PRIOR_OBSERVATION_CONTEXT"]]
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    bars = ax.bar(labels, values, color=["#4F8F8B", "#A9BAC5"], width=0.55)
    ax.set_ylabel("日期—空间对照情境数量")
    ax.set_title("施工推进下的多阶段信息关联情境")
    ax.spines[["top", "right"]].set_visible(False)
    ax.bar_label(bars, padding=4)
    fig.tight_layout()
    _save_figure(fig, output_dir / "construction_progression_context_distribution")
    plt.close(fig)

    if not cases:
        return
    case = cases[0]
    state_id = str(case["state_version_id"])
    rows = [
        row
        for row in associations
        if row["state_version_id"] == state_id and row["association_tier"] == "SAME_DAY_DIRECT"
    ]
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(10.5, 4.7))
    forecast_seen: set[str] = set()
    observation_seen: set[str] = set()
    for row in rows:
        forecast_id = str(row["forecast_evidence_id"])
        if forecast_id not in forecast_seen:
            ax.plot(
                [row["forecast_start"], row["forecast_end"]],
                [2, 2],
                color="#4E79A7",
                linewidth=8,
                solid_capstyle="butt",
            )
            forecast_seen.add(forecast_id)
        observation_id = str(row["observation_evidence_id"])
        if observation_id not in observation_seen:
            if row["observation_spatial_kind"] == "POINT":
                ax.scatter([row["observation_start"]], [0], s=90, color="#E07A5F", zorder=3)
            else:
                ax.plot(
                    [row["observation_start"], row["observation_end"]],
                    [0, 0],
                    color="#E07A5F",
                    linewidth=8,
                    solid_capstyle="butt",
                )
            observation_seen.add(observation_id)
    ax.plot(
        [case["cell_start"], case["cell_end"]],
        [1, 1],
        color="#59A14F",
        linewidth=8,
        solid_capstyle="butt",
    )
    ax.set_yticks([0, 1, 2], ["同日现场观察", "实际施工单元", "施工前预测"])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: _format_chainage(value)))
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.set_xlabel("线路里程")
    ax.set_title(f"典型多阶段信息链：{case['target_date']}")
    ax.grid(axis="x", color="#D9E2E7", linewidth=0.7)
    ax.spines[["top", "right", "left"]].set_visible(False)
    fig.tight_layout()
    _save_figure(fig, output_dir / "construction_progression_case_timeline")
    plt.close(fig)


def _write_availability_figure(output_dir: Path, summary: dict[str, Any]) -> None:
    plt.rcParams.update(
        {
            "font.family": "Arial Unicode MS",
            "axes.unicode_minus": False,
            "svg.hashsalt": "paper_evidence_completion_v2",
        }
    )
    labels = ["按明确提交日期", "假定现场工作日即可用"]
    values = [
        summary["documented_revision_event_count"],
        summary["optimistic_revision_event_count"],
    ]
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    bars = ax.bar(labels, values, color=["#4E79A7", "#B8C7D1"], width=0.55)
    ax.set_ylabel("后到资料修订事件数量")
    ax.set_title("资料可用时间假设的敏感性")
    ax.spines[["top", "right"]].set_visible(False)
    ax.bar_label(bars, padding=4)
    fig.tight_layout()
    _save_figure(fig, output_dir / "availability_time_sensitivity")
    plt.close(fig)


def _save_figure(figure: Any, stem: Path) -> None:
    figure.savefig(
        stem.with_suffix(".png"),
        dpi=300,
        metadata={"Software": "tbm-bitemporal-twin"},
    )
    figure.savefig(
        stem.with_suffix(".svg"),
        metadata={"Date": None, "Creator": "tbm-bitemporal-twin"},
    )


def _render_progression_report(summary: dict[str, Any]) -> str:
    return f"""# 施工推进下的多阶段信息关联实验

本实验只读取冻结对象，不修改 Stage 2–7 主链，也不评价地质预报准确率。

## 口径

- 宽口径对照情境：{summary["broad_daily_review_context_count"]} 个。
- 严格同日、直接空间对应情境：{summary["strict_same_day_direct_context_count"]} 个。
- 仅具有既有现场观察背景的情境：{summary["prior_observation_context_count"]} 个。
- 同一状态内的证据关联行：{summary["state_specific_association_count"]} 条。
- 去除跨状态重复后的预测—观察证据对：{summary["unique_evidence_pair_count"]} 对。
- 严格同日且直接相交的关联：{summary["strict_same_day_direct_association_count"]} 条。

宽口径情境不能全部称为“开挖当天形成掌子面观察”的完整链。论文主结果应使用严格口径；
其余情境只能作为该空间单元已有现场观察背景。

## 语义边界

- 预测身份违规：{summary["forecast_identity_violation_count"]}。
- 观察身份违规：{summary["observation_identity_violation_count"]}。
- 自动预报准确率判断：{summary["forecast_accuracy_claim_count"]}。
- 机械响应到地质原因的自动推断：{summary["mechanical_cause_inference_count"]}。

字段关系仅表示两份资料的记录关系，不表示预报正确、错误或工程因果关系。
"""


def _render_availability_report(summary: dict[str, Any]) -> str:
    return f"""# 资料可用时间敏感性分析

正式双时间结果使用报告明确记载的提交日期作为可核查的资料可用边界。

- 正式口径修订事件：{summary["documented_revision_event_count"]}。
- 假定现场工作日结束前即可用时的修订事件：{summary["optimistic_revision_event_count"]}。
- 在提前可用反事实下被预先纳入初始状态的事件：
  {summary["revision_events_collapsed_under_optimistic_assumption"]}。
- 正式 pre/post 对中 RAI 变化：{summary["documented_pre_post_rai_change_count"]}。
- 正式 pre/post 对中 GRS 变化：{summary["documented_pre_post_grs_change_count"]}。
- 正式 pre/post 对中 GRCI 变化：{summary["documented_pre_post_grci_change_count"]}。
- 工程陈述机会新增：{summary["opportunity_added_count"]}。
- ABSTAIN→EXPRESSIBLE：{summary["decision_switch_count"]}。

提前可用方案是反事实敏感性假设，不代表工程人员真实首次获知信息的时间。
该结果用于说明双时间结论对资料可用时间定义的依赖程度。
"""


def write_input_hash_audit(repo_root: Path, output_dir: Path) -> list[dict[str, Any]]:
    """Record hashes of every frozen file directly consumed by this experiment."""

    paths = [
        STAGE2_GEOLOGY_DIR / "primary_geological_evidence.jsonl",
        STAGE2_GEOLOGY_DIR / "geological_documents.jsonl",
        STAGE2_PLC_DIR / "response_evidence.jsonl",
        STAGE3A_DIR / "initial_construction_state_versions.jsonl",
        STAGE3A_DIR / "construction_state_cells.jsonl",
        STAGE3A_DIR / "state_geological_evidence_links.jsonl",
        STAGE3A_DIR / "state_response_evidence_links.jsonl",
        STAGE3B_DIR / "knowledge_revision_events.jsonl",
        STAGE7D_DIR / "stage7d_revision_event_summary.csv",
        STAGE7D_DIR / "stage7d_revision_pairs.csv",
        STAGE7D_DIR / "stage7d_revision_evidence_delta.csv",
    ]
    rows = []
    for relative in paths:
        path = repo_root / relative
        rows.append(
            {
                "relative_path": str(relative),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
                "source_modified": False,
            }
        )
    _write_csv(output_dir / "paper_experiment_input_hash_audit.csv", rows)
    return rows


def write_output_hashes(output_dir: Path) -> None:
    """Write deterministic hashes for generated files, excluding the hash list itself."""

    rows = []
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path.name != "file_hashes.sha256":
            rows.append(
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(output_dir)}"
            )
    (output_dir / "file_hashes.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _optional_text(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return str(value)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _normalize_value(value: Any) -> str:
    if isinstance(value, list):
        return "|".join(sorted(_normalize_value(item) for item in value))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "".join(str(value).casefold().split())


def _format_chainage(value: float) -> str:
    kilometre = int(value // 1000)
    offset = value - kilometre * 1000
    offset_text = f"{offset:.1f}".rstrip("0").rstrip(".")
    return f"DyK{kilometre}+{offset_text}"


def _json_cell(value: Any) -> str:
    if _is_missing(value):
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}
