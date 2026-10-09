# ruff: noqa: RUF001
"""Read-only audit for the Chapter 4.3 construction-progression experiment."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from datetime import date
from itertools import product
from pathlib import Path
from typing import Any

PLC_DIR = Path("artifacts/stage2_plc_operational_freeze_v2")
GEOLOGY_DIR = Path("artifacts/stage2_geology_v2_freeze_candidate")
STATE_DIR = Path("artifacts/stage3a_initial_epistemic_state_v1_1")
PAPER_DIR = Path("artifacts/paper_evidence_completion_v2")

FORECAST_SOURCE_TYPES = ("SONIC_FORECAST", "TSP_REPORT")

STAGE_LABELS = {
    "ALL_INITIAL_STATE_VERSIONS": "全部初始状态版本",
    "DAILY_REVIEW_CELL": "当日已掘复核状态",
    "HAS_EPISODE_AND_RESPONSE": "同时具有掘进事件和机械响应",
    "HAS_HSP_OR_TSP_DAILY_REVIEW_LINK": "具有关联的HSP或TSP预报",
    "FORECAST_AVAILABLE_STRICTLY_BEFORE_TARGET_DATE": "预报在施工日前已经可用",
    "HAS_AVAILABLE_FACE_OBSERVATION": "同时具有截至施工日可用的掌子面观察",
    "HAS_SAME_DAY_FACE_OBSERVATION": "掌子面观察形成于施工当日",
    "HAS_DIRECT_FORECAST_FACE_OVERLAP": "预报范围与同日观察直接相交",
    "HAS_STRICT_TRUSTED_EPISODE_INTERSECTION": "严格可信PLC足迹通过直接相交核验",
    "BROAD_FORECAST_FACE_PAIRS": "宽口径预报—掌子面配对",
    "SAME_DAY_FACE_PAIRS": "同日掌子面配对",
    "SAME_DAY_DIRECT_SCOPE_PAIRS": "同日且原始范围直接相交的配对",
    "STRICT_TRUSTED_EPISODE_INTERSECTION_PAIRS": "通过严格可信PLC足迹核验的配对",
}


def intervals_intersect(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    """Match the inclusive interval semantics used by the frozen experiment."""

    return max(a_start, b_start) <= min(a_end, b_end)


def is_strict_trusted_footprint(footprint: dict[str, Any] | None) -> bool:
    """Return the exact strict footprint predicate used by the final addendum."""

    return bool(
        footprint
        and footprint.get("spatial_scope_usable") is True
        and footprint.get("chainage_regime_status") == "TRUSTED"
        and footprint.get("trusted_spatial_scope")
    )


def build_chapter43_progression_audit(
    repo_root: Path,
    output_dir: Path = PAPER_DIR / "chapter43_progression_audit",
) -> dict[str, Any]:
    """Recompute the Chapter 4.3 funnel without mutating frozen artifacts."""

    root = repo_root.resolve()
    target = output_dir if output_dir.is_absolute() else root / output_dir
    target.mkdir(parents=True, exist_ok=True)

    states = _read_jsonl(root / STATE_DIR / "initial_construction_state_versions.jsonl")
    cells = _read_jsonl(root / STATE_DIR / "construction_state_cells.jsonl")
    geology_links = _read_jsonl(root / STATE_DIR / "state_geological_evidence_links.jsonl")
    evidence_rows = _read_jsonl(root / GEOLOGY_DIR / "primary_geological_evidence.jsonl")
    document_rows = _read_jsonl(root / GEOLOGY_DIR / "geological_documents.jsonl")
    episodes = _read_jsonl(root / PLC_DIR / "excavation_episodes.jsonl")
    footprints = _read_jsonl(root / PLC_DIR / "spatial_footprints.jsonl")
    manifest = _read_csv(root / PLC_DIR / "normalized_observation_manifest.csv")

    evidence = {str(row["evidence_uid"]): row for row in evidence_rows}
    documents = {str(row["document_id"]): row for row in document_rows}
    states_by_id = {str(row["state_version_id"]): row for row in states}
    episodes_by_id = {str(row["episode_id"]): row for row in episodes}
    footprints_by_episode = {str(row["episode_id"]): row for row in footprints}
    links_by_state: dict[str, list[dict[str, Any]]] = defaultdict(list)
    links_by_evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for link in geology_links:
        links_by_state[str(link["state_version_id"])].append(link)
        links_by_evidence[str(link["evidence_id"])].append(link)

    grid_start = min(float(row["spatial_start"]) for row in cells)
    grid_end = max(float(row["spatial_end"]) for row in cells)
    candidate_states = [row for row in states if _is_candidate_state(row)]
    candidate_state_ids = {str(row["state_version_id"]) for row in candidate_states}

    state_audits: list[dict[str, Any]] = []
    associations: list[dict[str, Any]] = []
    for state in candidate_states:
        state_id = str(state["state_version_id"])
        target_date = str(state["target_date"])
        forecast_links: list[tuple[dict[str, Any], dict[str, Any], str | None]] = []
        eligible_forecasts: list[tuple[dict[str, Any], dict[str, Any], str]] = []
        observation_links: list[tuple[dict[str, Any], dict[str, Any], str | None]] = []
        eligible_observations: list[tuple[dict[str, Any], dict[str, Any], str]] = []
        for link in links_by_state[state_id]:
            if str(link["applicability_role"]) != "DAILY_REVIEW":
                continue
            item = evidence[str(link["evidence_id"])]
            document = documents[str(item["document_id"])]
            temporal = document["document"]["temporal"]
            available = _optional_text(temporal.get("available_local_date"))
            if _is_forecast(item):
                forecast_links.append((link, item, available))
                if available is not None and available < target_date:
                    eligible_forecasts.append((link, item, available))
            if _is_face_observation(item):
                observation_links.append((link, item, available))
                if available is not None and available <= target_date:
                    eligible_observations.append((link, item, available))

        pair_rows: list[dict[str, Any]] = []
        for (_, forecast, _), (_, observation, _) in product(
            eligible_forecasts, eligible_observations
        ):
            observation_document = documents[str(observation["document_id"])]
            observed_date = _optional_text(
                observation_document["document"]["temporal"].get("observed_local_date")
            )
            forecast_start, forecast_end = _scope_bounds(forecast)
            observation_start, observation_end = _scope_bounds(observation)
            direct = intervals_intersect(
                forecast_start, forecast_end, observation_start, observation_end
            )
            pair = {
                "state_version_id": state_id,
                "target_date": target_date,
                "cell_id": str(state["cell_id"]),
                "forecast_evidence_id": str(forecast["evidence_uid"]),
                "forecast_source_type": str(forecast["source_type"]),
                "forecast_start": forecast_start,
                "forecast_end": forecast_end,
                "observation_evidence_id": str(observation["evidence_uid"]),
                "observation_start": observation_start,
                "observation_end": observation_end,
                "same_day_observation": observed_date == target_date,
                "direct_scope_overlap": direct,
                "strict_same_day_direct": observed_date == target_date and direct,
            }
            pair_rows.append(pair)
            associations.append(pair)

        state_audits.append(
            {
                "state_version_id": state_id,
                "target_date": target_date,
                "cell_id": str(state["cell_id"]),
                "forecast_link_count": len(forecast_links),
                "eligible_forecast_link_count": len(eligible_forecasts),
                "observation_link_count": len(observation_links),
                "eligible_observation_link_count": len(eligible_observations),
                "broad_association_count": len(pair_rows),
                "same_day_association_count": sum(
                    bool(row["same_day_observation"]) for row in pair_rows
                ),
                "strict_association_count": sum(
                    bool(row["strict_same_day_direct"]) for row in pair_rows
                ),
            }
        )

    strict_associations = [row for row in associations if row["strict_same_day_direct"]]
    final_associations: list[dict[str, Any]] = []
    association_failure_reasons: Counter[str] = Counter()
    matching_episode_rows: list[tuple[str, str, str]] = []
    for association in strict_associations:
        state = states_by_id[str(association["state_version_id"])]
        has_real_episode = False
        has_trusted_footprint = False
        matched = False
        for episode_id_raw in state["episode_ids"]:
            episode_id = str(episode_id_raw)
            episode = episodes_by_id.get(episode_id)
            footprint = footprints_by_episode.get(episode_id)
            episode_is_real = bool(episode and episode.get("episode_source") == "PLC_INFERRED")
            has_real_episode = has_real_episode or episode_is_real
            trusted = episode_is_real and is_strict_trusted_footprint(footprint)
            has_trusted_footprint = has_trusted_footprint or trusted
            if not trusted:
                continue
            assert footprint is not None
            scope = footprint["trusted_spatial_scope"]
            episode_start = float(scope["start_chainage"])
            episode_end = float(scope["end_chainage"])
            face_match = intervals_intersect(
                episode_start,
                episode_end,
                float(association["observation_start"]),
                float(association["observation_end"]),
            )
            direct_match = intervals_intersect(
                episode_start,
                episode_end,
                max(
                    float(association["forecast_start"]),
                    float(association["observation_start"]),
                ),
                min(
                    float(association["forecast_end"]),
                    float(association["observation_end"]),
                ),
            )
            if face_match or direct_match:
                matched = True
                matching_episode_rows.append(
                    (
                        str(association["state_version_id"]),
                        str(association["forecast_evidence_id"]),
                        episode_id,
                    )
                )
        if matched:
            final_associations.append(association)
            association_failure_reasons["PASS_TRUSTED_INTERSECTION"] += 1
        elif not has_real_episode:
            association_failure_reasons["NO_REAL_PLC_EPISODE"] += 1
        elif not has_trusted_footprint:
            association_failure_reasons["NO_STRICT_TRUSTED_FOOTPRINT_IN_STATE"] += 1
        else:
            association_failure_reasons["STRICT_TRUSTED_FOOTPRINT_NO_DIRECT_INTERSECTION"] += 1

    strict_state_ids = {str(row["state_version_id"]) for row in strict_associations}
    final_state_ids = {str(row["state_version_id"]) for row in final_associations}
    context_failure_reasons: Counter[str] = Counter()
    for state_id in strict_state_ids:
        state_pairs = [row for row in strict_associations if row["state_version_id"] == state_id]
        if state_id in final_state_ids:
            context_failure_reasons["PASS_TRUSTED_INTERSECTION"] += 1
            continue
        pair_reasons = []
        for _pair in state_pairs:
            state = states_by_id[state_id]
            trusted_scopes = []
            for episode_id_raw in state["episode_ids"]:
                episode_id = str(episode_id_raw)
                episode = episodes_by_id.get(episode_id)
                footprint = footprints_by_episode.get(episode_id)
                if (
                    episode
                    and episode.get("episode_source") == "PLC_INFERRED"
                    and footprint is not None
                    and is_strict_trusted_footprint(footprint)
                ):
                    trusted_scopes.append(footprint["trusted_spatial_scope"])
            pair_reasons.append("NO_INTERSECTION" if trusted_scopes else "NO_TRUSTED")
        context_failure_reasons[
            "STRICT_TRUSTED_FOOTPRINT_NO_DIRECT_INTERSECTION"
            if "NO_INTERSECTION" in pair_reasons
            else "NO_STRICT_TRUSTED_FOOTPRINT_IN_STATE"
        ] += 1

    inventory_rows = _inventory_rows(
        manifest, episodes, footprints, evidence_rows, states, associations
    )
    context_funnel = _context_funnel_rows(states, state_audits, context_failure_reasons)
    association_funnel = _association_funnel_rows(
        associations, strict_associations, final_associations, association_failure_reasons
    )
    source_funnel = _source_funnel_rows(
        evidence_rows,
        links_by_evidence,
        candidate_state_ids,
        states_by_id,
        documents,
        grid_start,
        grid_end,
        associations,
        strict_associations,
        final_associations,
    )
    case_rows = _case_rows(states_by_id, final_associations, matching_episode_rows, grid_start)
    tsp_rows = _tsp_rows(source_funnel)

    reconciliation = _reconcile_existing_outputs(root, associations, final_associations)
    summary = {
        "initial_state_count": len(states),
        "candidate_daily_review_state_count": len(candidate_states),
        "broad_context_count": sum(row["broad_association_count"] > 0 for row in state_audits),
        "broad_association_count": len(associations),
        "strict_candidate_context_count": len(strict_state_ids),
        "strict_candidate_association_count": len(strict_associations),
        "final_context_count": len(final_state_ids),
        "final_association_count": len(final_associations),
        "final_source_type_distribution": dict(
            sorted(Counter(row["forecast_source_type"] for row in final_associations).items())
        ),
        "matching_episode_association_row_count": len(matching_episode_rows),
        "matching_unique_episode_count": len({row[2] for row in matching_episode_rows}),
        "context_failure_reasons": dict(sorted(context_failure_reasons.items())),
        "association_failure_reasons": dict(sorted(association_failure_reasons.items())),
        "existing_output_reconciliation": reconciliation,
    }
    _assert_expected_reconciliation(summary)

    _write_csv(target / "chapter43_object_inventory.csv", inventory_rows)
    _write_csv(target / "chapter43_context_funnel.csv", context_funnel)
    _write_csv(target / "chapter43_association_funnel.csv", association_funnel)
    _write_csv(target / "chapter43_source_type_funnel.csv", source_funnel)
    _write_csv(target / "chapter43_anonymized_cases.csv", case_rows)
    _write_csv(target / "chapter43_tsp_exclusion_audit.csv", tsp_rows)
    _write_json(target / "chapter43_audit_summary.json", summary)
    (target / "chapter43_audit_report.md").write_text(
        _render_report(summary, inventory_rows, context_funnel, association_funnel, case_rows),
        encoding="utf-8",
    )
    input_hash_rows = _input_hash_rows(root)
    _write_csv(target / "chapter43_input_hashes.csv", input_hash_rows)
    _write_file_hashes(target)
    return summary


def _inventory_rows(
    manifest: list[dict[str, str]],
    episodes: list[dict[str, Any]],
    footprints: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    states: list[dict[str, Any]],
    associations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    forecasts = [row for row in evidence if _is_forecast(row)]
    observations = [row for row in evidence if _is_face_observation(row)]
    return [
        _inventory("PLC_OBSERVATION", sum(int(row["row_count"]) for row in manifest)),
        _inventory("EXCAVATION_EPISODE", len(episodes)),
        _inventory(
            "SPATIALLY_USABLE_FOOTPRINT",
            sum(bool(row.get("spatial_scope_usable")) for row in footprints),
        ),
        _inventory(
            "STRICT_TRUSTED_FOOTPRINT",
            sum(is_strict_trusted_footprint(row) for row in footprints),
        ),
        _inventory(
            "HSP_FORECAST_SEGMENT", sum(row["source_type"] == "SONIC_FORECAST" for row in forecasts)
        ),
        _inventory(
            "TSP_FORECAST_SEGMENT", sum(row["source_type"] == "TSP_REPORT" for row in forecasts)
        ),
        _inventory("FACE_OBSERVATION", len(observations)),
        _inventory(
            "FACE_POINT",
            sum(
                row.get("attributes", {}).get("observation_scope") == "FACE_POINT"
                for row in observations
            ),
        ),
        _inventory(
            "CURRENT_EXCAVATED_INTERVAL",
            sum(
                row.get("attributes", {}).get("observation_scope") == "CURRENT_EXCAVATED_INTERVAL"
                for row in observations
            ),
        ),
        _inventory("INITIAL_STATE_VERSION", len(states)),
        _inventory("STATE_SPECIFIC_CROSS_SOURCE_ASSOCIATION", len(associations)),
    ]


def _context_funnel_rows(
    states: list[dict[str, Any]],
    audits: list[dict[str, Any]],
    final_reasons: Counter[str],
) -> list[dict[str, Any]]:
    role_states = [row for row in states if row.get("cell_scope_role") == "DAILY_REVIEW_CELL"]
    candidate_count = len(audits)
    forecast_count = sum(row["forecast_link_count"] > 0 for row in audits)
    preavailable_count = sum(row["eligible_forecast_link_count"] > 0 for row in audits)
    broad_count = sum(row["broad_association_count"] > 0 for row in audits)
    same_day_count = sum(row["same_day_association_count"] > 0 for row in audits)
    direct_count = sum(row["strict_association_count"] > 0 for row in audits)
    final_count = final_reasons["PASS_TRUSTED_INTERSECTION"]
    values = [
        ("ALL_INITIAL_STATE_VERSIONS", len(states), len(states), "起始集合"),
        (
            "DAILY_REVIEW_CELL",
            len(states),
            len(role_states),
            "排除局部背景状态和前方关注状态",
        ),
        (
            "HAS_EPISODE_AND_RESPONSE",
            len(role_states),
            candidate_count,
            "排除没有连续掘进事件或机械响应的当日复核状态",
        ),
        (
            "HAS_HSP_OR_TSP_DAILY_REVIEW_LINK",
            candidate_count,
            forecast_count,
            "要求存在HSP/TSP预报区段的当日复核关联",
        ),
        (
            "FORECAST_AVAILABLE_STRICTLY_BEFORE_TARGET_DATE",
            forecast_count,
            preavailable_count,
            "排除预报在施工日当天或之后才可用的状态",
        ),
        (
            "HAS_AVAILABLE_FACE_OBSERVATION",
            preavailable_count,
            broad_count,
            "排除截至施工日没有可用掌子面观察的状态",
        ),
        (
            "HAS_SAME_DAY_FACE_OBSERVATION",
            broad_count,
            same_day_count,
            "排除只有既往掌子面观察背景的状态",
        ),
        (
            "HAS_DIRECT_FORECAST_FACE_OVERLAP",
            same_day_count,
            direct_count,
            "要求至少一组预报区间与同日掌子面范围直接相交",
        ),
        (
            "HAS_STRICT_TRUSTED_EPISODE_INTERSECTION",
            direct_count,
            final_count,
            (
                f"{final_reasons['NO_STRICT_TRUSTED_FOOTPRINT_IN_STATE']}个状态无严格TRUSTED足迹；"
                f"{final_reasons['STRICT_TRUSTED_FOOTPRINT_NO_DIRECT_INTERSECTION']}个状态足迹未直接相交"
            ),
        ),
    ]
    return [
        {
            "stage": stage,
            "stage_label": STAGE_LABELS[stage],
            "unit": "DATE_CELL_STATE",
            "before_count": before,
            "after_count": after,
            "excluded_count": before - after,
            "main_reason": reason,
        }
        for stage, before, after, reason in values
    ]


def _association_funnel_rows(
    associations: list[dict[str, Any]],
    strict: list[dict[str, Any]],
    final: list[dict[str, Any]],
    reasons: Counter[str],
) -> list[dict[str, Any]]:
    same_day = [row for row in associations if row["same_day_observation"]]
    values = [
        (
            "BROAD_FORECAST_FACE_PAIRS",
            len(associations),
            len(associations),
            "40个宽口径情境中的预报与掌子面记录笛卡尔配对",
        ),
        (
            "SAME_DAY_FACE_PAIRS",
            len(associations),
            len(same_day),
            "排除掌子面观察日期早于施工日的配对",
        ),
        (
            "SAME_DAY_DIRECT_SCOPE_PAIRS",
            len(same_day),
            len(strict),
            "排除仅共享10 m单元但原始预报范围与观察范围不相交的配对",
        ),
        (
            "STRICT_TRUSTED_EPISODE_INTERSECTION_PAIRS",
            len(strict),
            len(final),
            (
                f"{reasons['NO_STRICT_TRUSTED_FOOTPRINT_IN_STATE']}条无严格TRUSTED足迹；"
                f"{reasons['STRICT_TRUSTED_FOOTPRINT_NO_DIRECT_INTERSECTION']}条足迹未直接相交"
            ),
        ),
    ]
    return [
        {
            "stage": stage,
            "stage_label": STAGE_LABELS[stage],
            "unit": "FORECAST_FACE_ASSOCIATION",
            "before_count": before,
            "after_count": after,
            "excluded_count": before - after,
            "main_reason": reason,
        }
        for stage, before, after, reason in values
    ]


def _source_funnel_rows(
    evidence: list[dict[str, Any]],
    links_by_evidence: dict[str, list[dict[str, Any]]],
    candidate_state_ids: set[str],
    states_by_id: dict[str, dict[str, Any]],
    documents: dict[str, dict[str, Any]],
    grid_start: float,
    grid_end: float,
    associations: list[dict[str, Any]],
    strict: list[dict[str, Any]],
    final: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_type in FORECAST_SOURCE_TYPES:
        source_evidence = [
            row for row in evidence if _is_forecast(row) and row["source_type"] == source_type
        ]
        ids = {str(row["evidence_uid"]) for row in source_evidence}
        in_grid = {
            str(row["evidence_uid"])
            for row in source_evidence
            if intervals_intersect(*_scope_bounds(row), grid_start, grid_end)
        }
        linked = {evidence_id for evidence_id in ids if links_by_evidence[evidence_id]}
        candidate = {
            evidence_id
            for evidence_id in ids
            if any(
                str(link["state_version_id"]) in candidate_state_ids
                and str(link["applicability_role"]) == "DAILY_REVIEW"
                for link in links_by_evidence[evidence_id]
            )
        }
        preavailable: set[str] = set()
        for evidence_id in candidate:
            item = next(row for row in source_evidence if str(row["evidence_uid"]) == evidence_id)
            available = _optional_text(
                documents[str(item["document_id"])]["document"]["temporal"].get(
                    "available_local_date"
                )
            )
            if any(
                available is not None
                and available < str(states_by_id[str(link["state_version_id"])]["target_date"])
                for link in links_by_evidence[evidence_id]
                if str(link["state_version_id"]) in candidate_state_ids
                and str(link["applicability_role"]) == "DAILY_REVIEW"
            ):
                preavailable.add(evidence_id)
        broad_ids = {
            str(row["forecast_evidence_id"])
            for row in associations
            if row["forecast_source_type"] == source_type
        }
        strict_ids = {
            str(row["forecast_evidence_id"])
            for row in strict
            if row["forecast_source_type"] == source_type
        }
        final_ids = {
            str(row["forecast_evidence_id"])
            for row in final
            if row["forecast_source_type"] == source_type
        }
        counts = [
            ("FROZEN_FORECAST_SEGMENT", len(ids)),
            ("OVERLAPS_ANALYSIS_GRID", len(in_grid)),
            ("LINKED_TO_ANY_INITIAL_STATE", len(linked)),
            ("LINKED_TO_PLC_RESPONSE_DAILY_REVIEW_STATE", len(candidate)),
            ("STRICTLY_PREAVAILABLE_IN_CANDIDATE_STATE", len(preavailable)),
            ("ENTERS_BROAD_CROSS_SOURCE_ASSOCIATION", len(broad_ids)),
            ("ENTERS_SAME_DAY_DIRECT_ASSOCIATION", len(strict_ids)),
            ("ENTERS_FINAL_TRUSTED_EPISODE_ASSOCIATION", len(final_ids)),
        ]
        for stage, count in counts:
            rows.append(
                {
                    "source_type": source_type,
                    "stage": stage,
                    "unit": "UNIQUE_FORECAST_EVIDENCE",
                    "count": count,
                }
            )
    return rows


def _case_rows(
    states: dict[str, dict[str, Any]],
    final_associations: list[dict[str, Any]],
    matching_rows: list[tuple[str, str, str]],
    grid_start: float,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in final_associations:
        grouped[str(row["state_version_id"])].append(row)
    ordered = sorted(grouped, key=lambda state_id: str(states[state_id]["target_date"]))
    first_date = date.fromisoformat(str(states[ordered[0]]["target_date"]))
    rows: list[dict[str, Any]] = []
    for index, state_id in enumerate(ordered, start=1):
        pairs = grouped[state_id]
        current_date = date.fromisoformat(str(states[state_id]["target_date"]))
        face_positions = {float(row["observation_start"]) for row in pairs}
        boundary_matches = sum(
            float(row["observation_start"])
            in {float(row["forecast_start"]), float(row["forecast_end"])}
            for row in pairs
        )
        episode_ids = {
            episode_id
            for matched_state, _, episode_id in matching_rows
            if matched_state == state_id
        }
        rows.append(
            {
                "case_id": f"Case {index}",
                "construction_day_offset": (current_date - first_date).days,
                "relative_face_position_m": round(next(iter(face_positions)) - grid_start, 3),
                "forecast_association_count": len(pairs),
                "face_observation_count": len(
                    {str(row["observation_evidence_id"]) for row in pairs}
                ),
                "matching_unique_episode_count": len(episode_ids),
                "boundary_touching_forecast_count": boundary_matches,
                "forecast_source_type": ";".join(
                    sorted({str(row["forecast_source_type"]) for row in pairs})
                ),
                "structure_note": (
                    "同一现场观察分别与两条施工前预报区段直接相交"
                    if len(pairs) == 2
                    else "一条施工前预报与一条同日现场观察直接相交"
                ),
            }
        )
    return rows


def _tsp_rows(source_funnel: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tsp = {
        row["stage"]: int(row["count"])
        for row in source_funnel
        if row["source_type"] == "TSP_REPORT"
    }
    stages = [
        ("FROZEN_FORECAST_SEGMENT", "冻结TSP预报区段"),
        ("OVERLAPS_ANALYSIS_GRID", "60条位于本次固定分析范围之外"),
        ("LINKED_TO_ANY_INITIAL_STATE", "分析范围内7条均形成状态关联"),
        (
            "LINKED_TO_PLC_RESPONSE_DAILY_REVIEW_STATE",
            "6条仅形成局部背景关联；1条进入含PLC事件和响应的当日复核状态",
        ),
        (
            "STRICTLY_PREAVAILABLE_IN_CANDIDATE_STATE",
            "该1条在施工日前已经可用，时间条件不是排除原因",
        ),
        (
            "ENTERS_BROAD_CROSS_SOURCE_ASSOCIATION",
            "对应状态没有截至施工日可用的掌子面观察，未形成跨来源配对",
        ),
        ("ENTERS_SAME_DAY_DIRECT_ASSOCIATION", "没有TSP配对进入同日直接相交层"),
        ("ENTERS_FINAL_TRUSTED_EPISODE_ASSOCIATION", "最终完整情境中的TSP为0"),
    ]
    rows = []
    before = tsp[stages[0][0]]
    for stage, reason in stages:
        after = tsp[stage]
        rows.append(
            {
                "stage": stage,
                "before_count": before,
                "after_count": after,
                "excluded_count": before - after,
                "reason": reason,
            }
        )
        before = after
    return rows


def _reconcile_existing_outputs(
    root: Path,
    associations: list[dict[str, Any]],
    final_associations: list[dict[str, Any]],
) -> dict[str, Any]:
    existing = _read_csv(root / PAPER_DIR / "construction_progression_associations.csv")
    existing_keys = {
        (
            str(row["state_version_id"]),
            str(row["forecast_evidence_id"]),
            str(row["observation_evidence_id"]),
        )
        for row in existing
    }
    rebuilt_keys = {
        (
            str(row["state_version_id"]),
            str(row["forecast_evidence_id"]),
            str(row["observation_evidence_id"]),
        )
        for row in associations
    }
    final_existing = _read_csv(root / PAPER_DIR / "construction_progression_context_final.csv")
    final_existing_ids = {
        str(row["state_version_id"])
        for row in final_existing
        if str(row["final_formal_strict_context"]).lower() == "true"
    }
    final_rebuilt_ids = {str(row["state_version_id"]) for row in final_associations}
    return {
        "broad_association_key_difference_count": len(existing_keys ^ rebuilt_keys),
        "final_context_id_difference_count": len(final_existing_ids ^ final_rebuilt_ids),
    }


def _assert_expected_reconciliation(summary: dict[str, Any]) -> None:
    expected = {
        "broad_context_count": 40,
        "broad_association_count": 96,
        "strict_candidate_context_count": 19,
        "strict_candidate_association_count": 27,
        "final_context_count": 5,
        "final_association_count": 6,
    }
    for key, value in expected.items():
        if summary[key] != value:
            raise RuntimeError(f"{key}: expected frozen result {value}, got {summary[key]}")
    if any(summary["existing_output_reconciliation"].values()):
        raise RuntimeError("Rebuilt Chapter 4.3 results differ from existing audit outputs")


def _render_report(
    summary: dict[str, Any],
    inventory: list[dict[str, Any]],
    context_funnel: list[dict[str, Any]],
    association_funnel: list[dict[str, Any]],
    cases: list[dict[str, Any]],
) -> str:
    del inventory
    lines = [
        "# Chapter 4.3施工推进多阶段信息组织审计",
        "",
        "## A. 4.3实验目的",
        "",
        (
            "该实验验证的是不同施工阶段形成的信息能否围绕同一施工位置建立可追溯关联。"
            "5个情境不是从几十万条PLC观测中只识别出的5次施工，而是同时具备施工前地质预报、"
            "当天真实掘进足迹和同日现场观察的完整跨来源时空链。字段对照用于描述信息如何随施工推进而补充，"
            "不用于计算地质预报准确率，也不根据机械响应解释地质成因。"
        ),
        "",
        "## B. 筛选漏斗表",
        "",
        "### 日期—空间情境",
        "",
        "| 筛选阶段 | 筛选前 | 筛选后 | 排除 | 主要原因 |",
        "|---|---:|---:|---:|---|",
    ]
    for row in context_funnel:
        lines.append(
            f"| {row['stage_label']} | {row['before_count']} | {row['after_count']} | "
            f"{row['excluded_count']} | {row['main_reason']} |"
        )
    lines.extend(
        [
            "",
            "### 预报—现场观察配对",
            "",
            "| 筛选阶段 | 筛选前 | 筛选后 | 排除 | 主要原因 |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for row in association_funnel:
        lines.append(
            f"| {row['stage_label']} | {row['before_count']} | {row['after_count']} | "
            f"{row['excluded_count']} | {row['main_reason']} |"
        )
    lines.extend(
        [
            "",
            "## C. 5个情境与6条关联的关系",
            "",
            "| 匿名情境 | 相对施工日 | 预报关联数 | 同日观察数 | 匹配PLC事件数 | 结构 |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in cases:
        lines.append(
            f"| {row['case_id']} | +{row['construction_day_offset']} d | "
            f"{row['forecast_association_count']} | {row['face_observation_count']} | "
            f"{row['matching_unique_episode_count']} | {row['structure_note']} |"
        )
    lines.extend(
        [
            "",
            (
                "Case 3中同一现场观察与两条施工前HSP区段直接相交，其中一条在观察点处边界相接，"
                "因此5个日期—空间情境形成6条预报—现场观察关联。6条关联不是6个独立统计样本。"
            ),
            "",
            "## D. TSP未进入最终完整情境的原因",
            "",
            (
                "冻结地质证据中共有67条TSP预报区段，60条位于本次固定分析范围之外。"
                "范围内7条均形成状态关联，其中6条只作为局部背景，1条进入含PLC事件和机械响应的当日复核状态。"
                "该条TSP在施工日前已经可用，但对应状态没有截至施工日可用的掌子面观察，"
                "因此未形成预报—现场观察配对，也没有进入后续直接空间相交和PLC足迹核验。"
            ),
            "",
            "## E. 可直接用于论文4.3.1的中文正文",
            "",
            (
                "为检验施工前地质预报、实际掘进和现场观察能否围绕同一施工位置连续组织，"
                "本文以施工日期和10 m空间单元构成的状态为起点进行逐层筛选。1,322个初始状态中，"
                "178个属于当日已掘复核状态，其中170个同时包含连续掘进事件和机械响应。"
                "在这些状态中，166个具有施工日前已经可用的HSP或TSP预报，40个还具有截至施工日可用的掌子面资料。"
                "进一步要求掌子面观察形成于施工当日，且其原始空间范围与预报区间直接相交，得到19个候选情境和27条预报—观察关联。"
                "最后使用PLC连续掘进事件的严格可信里程足迹核验实际施工覆盖，排除14个足迹不满足条件的候选情境，"
                "最终保留5个完整施工情境和6条直接关联。5个情境均同时包含施工前HSP预报、当天真实掘进和同日现场观察；"
                "其中一个情境的同一观察位置同时与两个预报区段相交，因而关联数多于情境数。"
                "该结果表明，多阶段工程信息可以在保持原有时间、空间和认识属性的前提下建立直接联系，但样本规模仅支持机制可实施性说明。"
            ),
            "",
            "## F. 结论边界",
            "",
            "可以说：在真实工程数据中验证了施工前预报—实际掘进—现场观察的直接关联机制具有可实施性。",
            "",
            "不可以说：5个情境能够支持统计泛化，或代表全部施工条件。",
            "",
            "不可以说：字段相同或不同等同于HSP/TSP预报准确或错误。",
            "",
            "不可以说：PLC机械响应能够解释具体地质成因。",
            "",
            "## 实现与追溯",
            "",
            "- 候选状态：`construction_progression_review.py:72-103,493-498`。",
            "- 直接关联：`construction_progression_review.py:105-159,501-535`。",
            "- PLC足迹终筛：`paper_final_addendum.py:51-180`。",
            "- 冻结条件：`configs/paper_evidence_completion.yaml:31-76`。",
            "- 当前实现未使用SQL或数据库；输入为冻结JSONL/CSV/Parquet，输出为CSV/JSON/Markdown。",
            "",
            f"重算与现有产物关联键差异：{summary['existing_output_reconciliation']['broad_association_key_difference_count']}；"
            f"最终情境ID差异：{summary['existing_output_reconciliation']['final_context_id_difference_count']}。",
        ]
    )
    return "\n".join(lines) + "\n"


def _input_hash_rows(root: Path) -> list[dict[str, str]]:
    paths = [
        PLC_DIR / "normalized_observation_manifest.csv",
        PLC_DIR / "excavation_episodes.jsonl",
        PLC_DIR / "spatial_footprints.jsonl",
        GEOLOGY_DIR / "primary_geological_evidence.jsonl",
        GEOLOGY_DIR / "geological_documents.jsonl",
        STATE_DIR / "initial_construction_state_versions.jsonl",
        STATE_DIR / "construction_state_cells.jsonl",
        STATE_DIR / "state_geological_evidence_links.jsonl",
        STATE_DIR / "state_response_evidence_links.jsonl",
        PAPER_DIR / "construction_progression_contexts.csv",
        PAPER_DIR / "construction_progression_associations.csv",
        PAPER_DIR / "construction_progression_context_final.csv",
        PAPER_DIR / "construction_progression_plc_coverage_audit.csv",
        Path("configs/paper_evidence_completion.yaml"),
        Path("src/tbm_twin/evaluation/construction_progression_review.py"),
        Path("src/tbm_twin/evaluation/paper_final_addendum.py"),
    ]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
    ).stdout.strip()
    return [
        {
            "path": path.as_posix(),
            "sha256": _sha256(root / path),
            "git_head": commit,
        }
        for path in paths
    ]


def _write_file_hashes(output_dir: Path) -> None:
    paths = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "file_hashes.sha256"
    )
    text = "".join(f"{_sha256(path)}  {path.name}\n" for path in paths)
    (output_dir / "file_hashes.sha256").write_text(text, encoding="utf-8")


def _is_candidate_state(state: dict[str, Any]) -> bool:
    return bool(
        state.get("cell_scope_role") == "DAILY_REVIEW_CELL"
        and state.get("episode_ids")
        and state.get("response_evidence_ids")
    )


def _is_forecast(item: dict[str, Any]) -> bool:
    return bool(
        item.get("epistemic_status") == "FORECAST"
        and item.get("source_type") in FORECAST_SOURCE_TYPES
        and item.get("evidence_type") == "FORECAST_SEGMENT"
    )


def _is_face_observation(item: dict[str, Any]) -> bool:
    return bool(
        item.get("epistemic_status") == "OBSERVED"
        and item.get("source_type") == "FACE_SKETCH"
        and item.get("evidence_type") == "FACE_OBSERVATION"
    )


def _scope_bounds(item: dict[str, Any]) -> tuple[float, float]:
    scope = item["spatial_scope"]
    return float(scope["start_chainage"]), float(scope["end_chainage"])


def _optional_text(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return str(value)


def _inventory(name: str, count: int) -> dict[str, Any]:
    return {"object_type": name, "count": count}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write headerless empty audit: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
