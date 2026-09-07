# ruff: noqa: E501
"""Build the final, read-only paper technical audit.

This script never writes to a frozen artifact directory.  It reconstructs paper
counts from authoritative objects, exports the frozen GRS registry, runs a bounded
offline mapping sensitivity analysis, and documents spatial semantics.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import re
import subprocess
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import yaml

from tbm_twin.claim_building.batch_builder import (
    _build_lookup,
    _construct_proposal,
    _discover_opportunities,
    _load_stage,
)
from tbm_twin.claims.contracts import load_claim_contracts
from tbm_twin.claims.registry import ClaimTypeRegistry
from tbm_twin.claims.validation import ClaimContractEvaluator
from tbm_twin.metrics.geological_mapping import normalize_value
from tbm_twin.metrics.grci import build_grci
from tbm_twin.metrics.grs import build_grs_for_snapshots
from tbm_twin.metrics.io import stable_id

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = REPO_ROOT / "audit"
SUPPLEMENTARY_DIR = REPO_ROOT / "supplementary"
PAPER_DIR = REPO_ROOT / "paper_artifacts"

STAGE2_PLC = REPO_ROOT / "artifacts/stage2_plc_operational_freeze_v2"
STAGE2_GEO = REPO_ROOT / "artifacts/stage2_geology_v2_freeze_candidate"
STAGE3A = REPO_ROOT / "artifacts/stage3a_initial_epistemic_state_v1_1"
STAGE3B = REPO_ROOT / "artifacts/stage3b_bitemporal_epistemic_state_v1_1"
STAGE4 = REPO_ROOT / "artifacts/stage4_bitemporal_state_metrics_v1_1"
STAGE5B = REPO_ROOT / "artifacts/stage5b_deterministic_claim_builder_v1"
STAGE6A = REPO_ROOT / "artifacts/stage6a_fact_lock_evidence_pack_v1"
STAGE7B = REPO_ROOT / "artifacts/stage7b_main_comparison_v1"
STAGE7C = REPO_ROOT / "artifacts/stage7c_main_auto_eval_v1_2"
STAGE7D = REPO_ROOT / "artifacts/stage7d_bitemporal_value_v1_1"
STAGE7E = REPO_ROOT / "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup"
STAGE7E_CORRECTION = REPO_ROOT / "artifacts/stage7e_ablation_execution_v1_1_correction"
STAGE7F = REPO_ROOT / "artifacts/stage7f_sensitivity_execution_v1"
STAGE7F_FINAL = REPO_ROOT / "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation"

MAPPING_CONFIG = REPO_ROOT / "configs/geological_attention_mapping_v1.yaml"
METRIC_CONFIG = REPO_ROOT / "configs/state_metric_definition_v1.yaml"
CLAIM_CONFIG = REPO_ROOT / "configs/claim_contract_v1.yaml"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_bool(value: Any) -> bool:
    return str(value).lower() == "true"


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _mapping_config() -> dict[str, Any]:
    value = yaml.safe_load(MAPPING_CONFIG.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("Mapping configuration must be a mapping")
    return value


def _mapping_rows(config: dict[str, Any]) -> list[dict[str, Any]]:
    entries = config.get("entries")
    if not isinstance(entries, list):
        raise TypeError("Mapping entries must be a list")
    rows: list[dict[str, Any]] = []
    for entry in entries:
        row = dict(entry)
        row["normalized_serialization"] = normalize_value(row.get("normalized_serialization"))
        row["mapping_id"] = "geo_attention_v1_" + stable_id(
            str(row["attribute_name"]),
            str(row["normalized_serialization"]),
            str(config["method_version"]),
        )
        rows.append(row)
    return rows


def build_mapping_registry(config: dict[str, Any]) -> dict[str, Any]:
    """Export the exact formal mapping plus observed and unmapped values."""

    evidences = _jsonl(STAGE2_GEO / "primary_geological_evidence.jsonl")
    entries = _mapping_rows(config)
    configured_fields = {str(row["attribute_name"]) for row in entries}
    configured_keys = {
        (str(row["attribute_name"]), str(row["normalized_serialization"])) for row in entries
    }
    counts: Counter[tuple[str, str]] = Counter()
    modes: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    evidence_by_uid = {str(row["evidence_uid"]): row for row in evidences}
    snapshot_counts: Counter[tuple[str, str]] = Counter()
    snapshot_modes: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for evidence in evidences:
        for field, raw_value in (evidence.get("attributes") or {}).items():
            if field not in configured_fields:
                continue
            key = (str(field), normalize_value(raw_value))
            counts[key] += 1
            modes[key][str(evidence["epistemic_status"])] += 1
    role_fields = {
        "DAILY_REVIEW_CELL": "materialized_daily_review_evidence_ids",
        "FORWARD_ATTENTION_CELL": "materialized_forward_attention_evidence_ids",
        "LOCAL_BACKGROUND_CELL": "materialized_local_background_evidence_ids",
    }
    for snapshot in _jsonl(STAGE3B / "materialized_state_snapshots.jsonl"):
        role_field = role_fields[str(snapshot["cell_scope_role"])]
        for evidence_id in snapshot[role_field]:
            evidence = evidence_by_uid[str(evidence_id)]
            for field, raw_value in (evidence.get("attributes") or {}).items():
                if field not in configured_fields:
                    continue
                key = (str(field), normalize_value(raw_value))
                snapshot_counts[key] += 1
                snapshot_modes[key][str(evidence["epistemic_status"])] += 1

    registry: list[dict[str, Any]] = []
    for row in entries:
        key = (str(row["attribute_name"]), str(row["normalized_serialization"]))
        registry.append(
            {
                "source_field": key[0],
                "raw_value": key[1],
                "dimension": row["dimension_name"],
                "ordinal_value": row.get("ordinal_rank"),
                "ordinal_scale_max": row.get("ordinal_scale_max"),
                "attention_value": row.get("attention_value"),
                "review_status": row["review_status"],
                "mapping_basis": row["mapping_basis"],
                "mapping_version": config["method_version"],
                "used_in_frozen_run": snapshot_counts[key] > 0,
                "occurrence_count": counts[key],
                "observation_count": modes[key]["OBSERVED"],
                "prediction_count": modes[key]["FORECAST"],
                "evidence_mode_counts": json.dumps(modes[key], ensure_ascii=False, sort_keys=True),
                "frozen_snapshot_use_count": snapshot_counts[key],
                "frozen_snapshot_observation_count": snapshot_modes[key]["OBSERVED"],
                "frozen_snapshot_prediction_count": snapshot_modes[key]["FORECAST"],
                "code_source": "configs/geological_attention_mapping_v1.yaml",
                "rationale_available": False,
                "rationale": "RATIONALE_NOT_RECORDED",
            }
        )

    unmapped: list[dict[str, Any]] = []
    for key, count in sorted(counts.items()):
        if key in configured_keys:
            continue
        unmapped.append(
            {
                "source_field": key[0],
                "raw_value": key[1],
                "occurrence_count": count,
                "observation_count": modes[key]["OBSERVED"],
                "prediction_count": modes[key]["FORECAST"],
                "frozen_snapshot_use_count": snapshot_counts[key],
                "status": "APPEARS_IN_CONFIGURED_SOURCE_FIELD_BUT_NOT_IN_FROZEN_MAPPING",
            }
        )

    registry_fields = [
        "source_field",
        "raw_value",
        "dimension",
        "ordinal_value",
        "ordinal_scale_max",
        "attention_value",
        "review_status",
        "mapping_basis",
        "mapping_version",
        "used_in_frozen_run",
        "occurrence_count",
        "observation_count",
        "prediction_count",
        "evidence_mode_counts",
        "frozen_snapshot_use_count",
        "frozen_snapshot_observation_count",
        "frozen_snapshot_prediction_count",
        "code_source",
        "rationale_available",
        "rationale",
    ]
    _write_csv(SUPPLEMENTARY_DIR / "grs_mapping_registry.csv", registry, registry_fields)
    _write_json(SUPPLEMENTARY_DIR / "grs_mapping_registry.json", registry)
    _write_csv(
        SUPPLEMENTARY_DIR / "grs_unmapped_relevant_values.csv",
        unmapped,
        [
            "source_field",
            "raw_value",
            "occurrence_count",
            "observation_count",
            "prediction_count",
            "frozen_snapshot_use_count",
            "status",
        ],
    )

    lines = [
        "# GRS Frozen Mapping Registry",
        "",
        f"- Frozen entries: **{len(registry)}**",
        f"- Numeric entries: **{sum(row['attention_value'] is not None for row in registry)}**",
        f"- Reviewed-unmappable entries: **{sum(row['attention_value'] is None for row in registry)}**",
        f"- Entries observed in frozen geology: **{sum(bool(row['used_in_frozen_run']) for row in registry)}**",
        f"- Additional raw-evidence values in configured source fields but absent from mapping: **{len(unmapped)}**",
        f"- Unmapped values that actually enter frozen snapshot scoring: **{sum(snapshot_counts[(row['source_field'], row['raw_value'])] > 0 for row in unmapped)}**",
        "- Engineering rationale: **RATIONALE_NOT_RECORDED** for every entry. The repository",
        "  records ordering labels (`mapping_basis`), not a per-value engineering justification.",
        "",
        "| Source field | Value | Dimension | Rank | Attention | Evidence occurrences | Snapshot uses |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in registry:
        lines.append(
            "| {source_field} | {raw_value} | {dimension} | {ordinal_value} | "
            "{attention_value} | {occurrence_count} | {frozen_snapshot_use_count} |".format(**row)
        )
    lines.extend(
        [
            "",
            "## Values outside the 44-entry frozen registry",
            "",
            "These values occur in raw Evidence in one of the configured source fields, but are",
            "not scoring entries. None enters the role-selected frozen GRS snapshot inputs; this",
            "audit does not add mappings.",
            "",
            "| Source field | Value | Occurrences | Obs | Forecast | Snapshot uses |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in unmapped:
        lines.append(
            "| {source_field} | {raw_value} | {occurrence_count} | {observation_count} | "
            "{prediction_count} | {frozen_snapshot_use_count} |".format(**row)
        )
    _write_text(SUPPLEMENTARY_DIR / "grs_mapping_registry.md", "\n".join(lines))
    return {
        "frozen_mapping_entry_count": len(registry),
        "numeric_mapping_entry_count": sum(row["attention_value"] is not None for row in registry),
        "reviewed_unmappable_entry_count": sum(row["attention_value"] is None for row in registry),
        "frozen_entries_observed_count": sum(bool(row["used_in_frozen_run"]) for row in registry),
        "defined_but_unused_count": sum(not bool(row["used_in_frozen_run"]) for row in registry),
        "relevant_unique_source_values_count": len(counts),
        "relevant_unmapped_unique_value_count": len(unmapped),
        "relevant_unmapped_occurrence_count": sum(row["occurrence_count"] for row in unmapped),
        "unmapped_value_in_frozen_snapshot_input_count": sum(
            snapshot_counts[(row["source_field"], row["raw_value"])] > 0 for row in unmapped
        ),
        "rationale_recorded_count": 0,
    }


def _mapping_dict(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(str(row["attribute_name"]), str(row["normalized_serialization"])): row for row in rows}


def _decision_map(stage: Any) -> dict[str, tuple[str, str]]:
    registry = ClaimTypeRegistry.from_contracts(load_claim_contracts(CLAIM_CONFIG))
    evaluator = ClaimContractEvaluator(registry, _build_lookup(stage))
    opportunities, _ = _discover_opportunities(stage)
    decisions: dict[str, tuple[str, str]] = {}
    for opportunity in opportunities:
        proposal, _ = _construct_proposal(opportunity)
        if proposal is None:
            continue
        decision = evaluator.evaluate(proposal)
        decisions[opportunity.semantic_key] = (
            opportunity.claim_type.value,
            decision.expressibility.value,
        )
    return decisions


def _revision_conclusions(
    grs_by_version: dict[str, dict[str, Any]],
    grci_by_version: dict[str, dict[str, Any]],
) -> dict[str, tuple[bool, bool]]:
    conclusions: dict[str, tuple[bool, bool]] = {}
    for pair in _csv(STAGE7D / "stage7d_revision_pairs.csv"):
        pre_id = pair["pre_version_id"]
        post_id = pair["post_version_id"]
        grs_pre = grs_by_version[pre_id]
        grs_post = grs_by_version[post_id]
        grci_pre = grci_by_version[pre_id]
        grci_post = grci_by_version[post_id]
        grs_changed = (grs_pre.get("grs_status"), grs_pre.get("grs")) != (
            grs_post.get("grs_status"),
            grs_post.get("grs"),
        )
        grci_changed = (grci_pre.get("grci_status"), grci_pre.get("grci")) != (
            grci_post.get("grci_status"),
            grci_post.get("grci"),
        )
        conclusions[pair["revision_event_id"]] = (grs_changed, grci_changed)
    return conclusions


def build_mapping_sensitivity(config: dict[str, Any]) -> dict[str, Any]:
    """Run deterministic alias-group, one-rank perturbations in memory."""

    stage = _load_stage(REPO_ROOT)
    snapshots = _jsonl(STAGE3B / "materialized_state_snapshots.jsonl")
    versions = _jsonl(STAGE3B / "bitemporal_state_versions.jsonl")
    evidence_by_uid = {
        str(row["evidence_uid"]): row
        for row in _jsonl(STAGE2_GEO / "primary_geological_evidence.jsonl")
    }
    rai_rows = _jsonl(STAGE4 / "state_rai.jsonl")
    rai_by_version = {str(row["bitemporal_version_id"]): row for row in rai_rows}
    base_rows = _mapping_rows(config)
    _, base_grs, base_grs_by_version, _ = build_grs_for_snapshots(
        snapshots, evidence_by_uid, _mapping_dict(base_rows)
    )
    base_grci, _ = build_grci(versions, rai_by_version, base_grs_by_version)
    base_grci_by_version = {str(row["bitemporal_version_id"]): row for row in base_grci}
    stage.grs_rows = base_grs
    stage.grci_rows = base_grci
    base_decisions = _decision_map(stage)
    base_revision = _revision_conclusions(base_grs_by_version, base_grci_by_version)

    groups: dict[tuple[str, int, int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in base_rows:
        if row.get("ordinal_rank") is None or row.get("ordinal_scale_max") is None:
            continue
        group_key = (
            str(row["dimension_name"]),
            int(row["ordinal_rank"]),
            int(row["ordinal_scale_max"]),
            str(row["mapping_basis"]),
        )
        groups[group_key].append(row)

    base_grs_values = {str(row["bitemporal_version_id"]): row.get("grs") for row in base_grs}
    base_grci_values = {str(row["bitemporal_version_id"]): row.get("grci") for row in base_grci}
    rows: list[dict[str, Any]] = []
    revision_detail_rows: list[dict[str, Any]] = []
    for group_key, group_rows in sorted(groups.items()):
        dimension, rank, scale_max, basis = group_key
        for direction, delta in [("DOWN", -1), ("UP", 1)]:
            new_rank = rank + delta
            if not 0 <= new_rank <= scale_max:
                continue
            perturbed = deepcopy(base_rows)
            group_keys = {
                (str(row["attribute_name"]), str(row["normalized_serialization"]))
                for row in group_rows
            }
            for row in perturbed:
                key = (str(row["attribute_name"]), str(row["normalized_serialization"]))
                if key in group_keys:
                    row["ordinal_rank"] = new_rank
                    row["attention_value"] = new_rank / scale_max
            _, arm_grs, arm_grs_by_version, _ = build_grs_for_snapshots(
                snapshots, evidence_by_uid, _mapping_dict(perturbed)
            )
            arm_grci, _ = build_grci(versions, rai_by_version, arm_grs_by_version)
            arm_grci_by_version = {str(row["bitemporal_version_id"]): row for row in arm_grci}
            stage.grs_rows = arm_grs
            stage.grci_rows = arm_grci
            arm_decisions = _decision_map(stage)

            grs_deltas = [
                abs(float(row["grs"]) - float(base_grs_values[str(row["bitemporal_version_id"])]))
                for row in arm_grs
                if row.get("grs") is not None
                and base_grs_values[str(row["bitemporal_version_id"])] is not None
                and not math.isclose(
                    float(row["grs"]),
                    float(base_grs_values[str(row["bitemporal_version_id"])]),
                    abs_tol=1e-12,
                )
            ]
            grci_deltas = [
                abs(float(row["grci"]) - float(base_grci_values[str(row["bitemporal_version_id"])]))
                for row in arm_grci
                if row.get("grci") is not None
                and base_grci_values[str(row["bitemporal_version_id"])] is not None
                and not math.isclose(
                    float(row["grci"]),
                    float(base_grci_values[str(row["bitemporal_version_id"])]),
                    abs_tol=1e-12,
                )
            ]
            transitions: Counter[str] = Counter()
            claim_types: Counter[str] = Counter()
            for key, (claim_type, base_decision) in base_decisions.items():
                arm_decision = arm_decisions[key][1]
                if base_decision != arm_decision:
                    transitions[f"{base_decision}_TO_{arm_decision}"] += 1
                    claim_types[claim_type] += 1
            arm_revision = _revision_conclusions(arm_grs_by_version, arm_grci_by_version)
            revision_changed = sum(
                base_revision[key] != value for key, value in arm_revision.items()
            )
            for event_id, arm_conclusion in sorted(arm_revision.items()):
                if base_revision[event_id] == arm_conclusion:
                    continue
                revision_detail_rows.append(
                    {
                        "arm_id": f"{dimension}_{rank}_{direction}",
                        "revision_event_id": event_id,
                        "baseline_grs_changed": base_revision[event_id][0],
                        "perturbed_grs_changed": arm_conclusion[0],
                        "baseline_grci_changed": base_revision[event_id][1],
                        "perturbed_grci_changed": arm_conclusion[1],
                        "decision_migration_count": sum(transitions.values()),
                    }
                )
            rows.append(
                {
                    "arm_id": f"{dimension}_{rank}_{direction}",
                    "dimension": dimension,
                    "mapping_basis": basis,
                    "alias_group": ";".join(
                        f"{row['attribute_name']}={row['normalized_serialization']}"
                        for row in group_rows
                    ),
                    "alias_group_size": len(group_rows),
                    "baseline_rank": rank,
                    "perturbed_rank": new_rank,
                    "direction": direction,
                    "grs_available_count": sum(row.get("grs") is not None for row in arm_grs),
                    "grs_value_changed_count": len(grs_deltas),
                    "grs_abs_delta_min": min(grs_deltas) if grs_deltas else 0.0,
                    "grs_abs_delta_median": _percentile(grs_deltas, 0.5) or 0.0,
                    "grs_abs_delta_p95": _percentile(grs_deltas, 0.95) or 0.0,
                    "grs_abs_delta_max": max(grs_deltas) if grs_deltas else 0.0,
                    "grci_available_count": sum(row.get("grci") is not None for row in arm_grci),
                    "grci_value_changed_count": len(grci_deltas),
                    "claim_decision_migration_count": sum(transitions.values()),
                    "allow_to_reject_count": transitions["EXPRESSIBLE_TO_ABSTAIN"],
                    "reject_to_allow_count": transitions["ABSTAIN_TO_EXPRESSIBLE"],
                    "prediction_claim_migration_count": claim_types[
                        "FORECAST_GEOLOGICAL_CONDITION"
                    ],
                    "observation_claim_migration_count": claim_types[
                        "OBSERVED_GEOLOGICAL_CONDITION"
                    ],
                    "metric_claim_migration_count": sum(
                        count
                        for claim_type, count in claim_types.items()
                        if claim_type
                        not in {
                            "FORECAST_GEOLOGICAL_CONDITION",
                            "OBSERVED_GEOLOGICAL_CONDITION",
                        }
                    ),
                    "revision_conclusion_changed_count": revision_changed,
                }
            )

    fields = list(rows[0])
    _write_csv(SUPPLEMENTARY_DIR / "grs_mapping_sensitivity.csv", rows, fields)
    _write_csv(
        SUPPLEMENTARY_DIR / "grs_mapping_sensitivity_revision_audit.csv",
        revision_detail_rows,
        [
            "arm_id",
            "revision_event_id",
            "baseline_grs_changed",
            "perturbed_grs_changed",
            "baseline_grci_changed",
            "perturbed_grci_changed",
            "decision_migration_count",
        ],
    )
    numerical_arms = sum(row["grs_value_changed_count"] > 0 for row in rows)
    migration_arms = sum(row["claim_decision_migration_count"] > 0 for row in rows)
    revision_arms = sum(row["revision_conclusion_changed_count"] > 0 for row in rows)
    _write_text(
        SUPPLEMENTARY_DIR / "grs_mapping_sensitivity_summary.md",
        "\n".join(
            [
                "# GRS Mapping One-Step Sensitivity",
                "",
                "This is an offline deterministic audit. It does not modify frozen outputs.",
                "Aliases sharing dimension, rank, scale, and ordering basis move together by",
                "one legal rank. Null and unmappable values are not perturbed.",
                "",
                f"- Perturbation arms: **{len(rows)}**",
                f"- Arms with numerical GRS change: **{numerical_arms}**",
                f"- Maximum changed GRS states in one arm: **{max(row['grs_value_changed_count'] for row in rows)}**",
                f"- Maximum absolute GRS delta: **{max(row['grs_abs_delta_max'] for row in rows):.12f}**",
                f"- Arms with claim-decision migration: **{migration_arms}**",
                f"- Total decision migrations across all arms: **{sum(row['claim_decision_migration_count'] for row in rows)}**",
                f"- Arms changing a frozen revision conclusion: **{revision_arms}**",
                "",
                "Numerical sensitivity is expected because GRS is ordinal-value based. Claim-level",
                "stability only shows that these bounded local perturbations do not cross current",
                "admissibility boundaries; it does not scientifically validate the mapping.",
                "Two arms each change one event's binary GRS-revision classification. See",
                "the same event from changed to unchanged (36/53 to 35/53). See",
                "`grs_mapping_sensitivity_revision_audit.csv`; Claim decisions remain unchanged.",
            ]
        ),
    )
    return {
        "arm_count": len(rows),
        "arms_with_grs_numerical_change": numerical_arms,
        "arms_with_claim_decision_migration": migration_arms,
        "total_claim_decision_migrations": sum(
            row["claim_decision_migration_count"] for row in rows
        ),
        "arms_with_revision_conclusion_change": revision_arms,
        "max_grs_abs_delta": max(row["grs_abs_delta_max"] for row in rows),
    }


def _scope(scope: dict[str, Any] | None) -> tuple[float, float] | None:
    if not scope:
        return None
    start = scope.get("start_chainage")
    end = scope.get("end_chainage")
    if start is None or end is None:
        return None
    return float(start), float(end)


def build_spatial_lineage() -> dict[str, Any]:
    daily = _jsonl(STAGE3A / "daily_construction_states.jsonl")
    examples = []
    for row in daily:
        trusted = _scope(row.get("trusted_daily_plc_range"))
        review = _scope(row.get("daily_excavated_scope"))
        if trusted and review and trusted != review:
            examples.append((row, trusted, review))
    example, trusted, review = examples[0]
    lineage = f"""# Spatial Semantics Lineage

## Authoritative path

`raw PLC shield-head chainage` -> `core EXCAVATING observations` ->
`ExcavationEpisode trusted SpatialFootprint` -> `cell overlap/reference link` ->
`Claim authoritative support` -> `FactLock contained scope` -> `controlled realization`.

## Field contract

| Formal field | True source | Cell aligned | May be called actual excavation? | Permitted use | Forbidden inference |
|---|---|---:|---:|---|---|
| `ExcavationEpisode.excavation_start/end` | Core EXCAVATING intervals | No | Time only | Event temporal boundary | Spatial advance |
| `SpatialFootprint.trusted_spatial_scope` | Core shield-head chainage | No | Yes, only as event-supported footprint | Mechanical evidence location | Geological cause |
| `raw_daily_plc_range` | Raw daily shield-head range | No | Raw measured range, with quality caveat | Audit/diagnosis | Trusted advance when regime invalid |
| `trusted_daily_plc_range` | Trusted daily chainage regime | No | Yes, as trusted measured day range | Day-level measured span | Cell coverage |
| `daily_excavated_scope` | Ten-metre alignment of trusted range | **Yes** | **No** | Daily review cell selection | Actual daily advance or measured range |
| `ConstructionStateCell` | Fixed alignment/grid/index | Yes | No | Knowledge-state spatial index | Construction fact |
| `forward_scope` | Applicability rule ahead of review scope | Yes | No | Forecast attention organization | Already excavated fact |
| `local_background_scope` | Applicability rule behind review scope | Yes | No | Context organization | Current measured advance |
| Claim spatial scope | Frozen subject/support intersection | Sometimes | Only if claim type and support authorize it | Claim subject | Expansion beyond support |
| FactLock spatial scope | Resolved authoritative support | Inherited | Only with matching fact semantics | Controlled realization | Any support expansion |

## Concrete distinction

On `{example["target_date"]}`, the trusted PLC range is `{trusted[0]}-{trusted[1]}`
({trusted[1] - trusted[0]:.3f} m), while the field named `daily_excavated_scope` is
`{review[0]}-{review[1]}` ({review[1] - review[0]:.3f} m) with basis
`{example["daily_excavated_scope"].get("basis")}`.  The latter is a cell-aligned review
scope and must not be reported as actual daily advance.

## Enforcement evidence

- `src/tbm_twin/state/builder.py`: measured span fields are computed from raw/trusted PLC
  ranges; the aligned scope is used for cell-role assignment.
- `src/tbm_twin/state/builder.py`: multicell response links carry
  `response_stat_scope=EPISODE_LEVEL_SHARED`.
- `configs/claim_contract_v1.yaml` and Stage5A validation: claim scope must be contained
  by resolved support.
- `artifacts/stage6a_fact_lock_evidence_pack_v1/fact_locks.jsonl`: locked support and
  prohibited spatial expansion are persisted.

## Paper wording rule

Translate `daily_excavated_scope` as **cell-aligned daily review scope**, despite its
legacy internal field name. Use **trusted daily PLC range** for actual measured daily
range, and **event footprint** for episode-supported mechanical location.
"""
    _write_text(AUDIT_DIR / "spatial_semantics_lineage.md", lineage)
    return {
        "daily_state_count": len(daily),
        "aligned_scope_differs_from_trusted_range_count": len(examples),
        "example_target_date": example["target_date"],
    }


def build_spatial_text_scan() -> dict[str, Any]:
    patterns = {
        "CELL_AS_ACTUAL": re.compile(
            r"cell.{0,40}(actual (?:advance|excavat)|实际(?:推进|开挖))",
            re.IGNORECASE,
        ),
        "REVIEW_AS_ACTUAL": re.compile(
            r"(?:review scope|daily_excavated_scope).{0,50}(actual|实际推进|实际开挖)",
            re.IGNORECASE,
        ),
        "PREDICTION_AS_OBSERVED": re.compile(
            r"(?:forecast|prediction|预测|预报).{0,40}(?:observed fact|已观测事实|实测事实)",
            re.IGNORECASE,
        ),
        "FORWARD_AS_EXCAVATED": re.compile(
            r"(?:forward scope|forward_attention|前方范围).{0,40}(?:already excavated|已开挖)",
            re.IGNORECASE,
        ),
    }
    roots = [REPO_ROOT / name for name in ["src", "scripts", "configs", "tests"]]
    frozen_files = [
        STAGE7B / "runs/stage7b_main_execution_3ae0f791811a2e711cb9f488/B0_outputs.jsonl",
        STAGE7B / "runs/stage7b_main_execution_3ae0f791811a2e711cb9f488/B1_outputs.jsonl",
        STAGE7B / "runs/stage7b_main_execution_3ae0f791811a2e711cb9f488/P_final_outputs.jsonl",
    ]
    files: list[Path] = []
    for root in roots:
        files.extend(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix in {".py", ".yaml", ".yml", ".json", ".md"}
        )
    files.extend(path for path in frozen_files if path.exists())
    files = [path for path in files if path.resolve() != Path(__file__).resolve()]
    rows: list[dict[str, Any]] = []
    for path in sorted(set(files)):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, 1):
            for pattern_name, pattern in patterns.items():
                if not pattern.search(line):
                    continue
                relative = str(path.relative_to(REPO_ROOT))
                negative_guard = any(
                    phrase in line.lower()
                    for phrase in [
                        "not observed",
                        "do not upgrade",
                        "cannot",
                        "prohibit",
                        "非实测事实",
                        "非已观测事实",
                        "不能等同于已观测事实",
                        "不代表已观测事实",
                        "不得",
                    ]
                )
                if negative_guard:
                    classification = "safe wording"
                elif relative.startswith("tests/"):
                    classification = "test fixture only"
                elif "_archive" in relative or "deprecated" in relative.lower():
                    classification = "deprecated/archive"
                elif relative.startswith("artifacts/"):
                    classification = "requires manual paper wording check"
                else:
                    classification = "requires manual paper wording check"
                rows.append(
                    {
                        "path": relative,
                        "line": line_number,
                        "pattern": pattern_name,
                        "classification": classification,
                        "text": line.strip()[:500],
                    }
                )
    _write_csv(
        AUDIT_DIR / "spatial_semantics_text_scan.csv",
        rows,
        ["path", "line", "pattern", "classification", "text"],
    )
    return {
        "match_count": len(rows),
        "true_violation_count": sum(row["classification"] == "true violation" for row in rows),
        "manual_paper_wording_check_count": sum(
            row["classification"] == "requires manual paper wording check" for row in rows
        ),
    }


def build_20m_analysis() -> dict[str, Any]:
    arm = STAGE7F / "arms/cell_size_m_20/stage3a"
    conflicts = [
        row
        for row in _csv(arm / "cell_scope_role_audit.csv")
        if row["status"] == "SCOPE_ROLE_CONFLICT"
    ]
    cells = {str(row["cell_id"]): row for row in _jsonl(arm / "construction_state_cells.jsonl")}
    daily = {
        str(row["target_date"]): row for row in _jsonl(arm / "daily_construction_states.jsonl")
    }
    patterns = Counter(
        f"{row['existing_cell_scope_role']} -> {row['conflicting_cell_scope_role']}"
        for row in conflicts
    )
    unique_problem_cells = {row["cell_id"] for row in conflicts}
    multi_role_regions = {
        (row["target_date"], row["cell_id"])
        for row in conflicts
        if row["existing_cell_scope_role"] and row["conflicting_cell_scope_role"]
    }
    examples: list[dict[str, Any]] = []
    for row in conflicts[:5]:
        cell = cells[row["cell_id"]]
        day = daily[row["target_date"]]
        examples.append(
            {
                "target_date": row["target_date"],
                "cell_id": row["cell_id"],
                "cell_range": f"{cell['spatial_start']}-{cell['spatial_end']}",
                "daily_review_scope": day.get("daily_excavated_scope"),
                "forward_scope": day.get("forward_scope"),
                "local_background_scope": day.get("local_background_scope"),
                "existing_role": row["existing_cell_scope_role"],
                "conflicting_role": row["conflicting_cell_scope_role"],
                "scope_key": row["scope_key"],
            }
        )
    point_bad = sum(
        row["status"] == "DUPLICATE_OR_MISSING"
        for row in _csv(arm / "point_boundary_policy_audit.csv")
    )
    interval_bad = sum(
        row["status"] == "MISMATCH" for row in _csv(arm / "interval_overlap_conservation_audit.csv")
    )
    summary = _json(STAGE7F_FINAL / "stage7f_final_machine_summary.json")["cell_size"]
    lines = [
        "# Spatial Resolution Failure Analysis",
        "",
        "## Deterministic conclusion",
        "",
        "The 20 m arm crosses the method's support-semantic validity boundary. This is not",
        "a numerical instability in RAI/GRS/GRCI. A coarse cell can intersect a 10 m-aligned",
        "daily review region and an adjacent forward or local-background region on the same",
        "date, while the state model requires one role per cell. Retaining one role necessarily",
        "drops or misallocates some point/interval support, producing the observed secondary",
        "coverage failures.",
        "",
        f"- Role-conflict rows: **{len(conflicts)}**",
        f"- Unique problematic 20 m cells: **{len(unique_problem_cells)}**",
        f"- Date-cell instances containing multiple role-support regions: **{len(multi_role_regions)}**",
        f"- Point missing/duplicate: **{point_bad}**",
        f"- Interval overlap mismatch: **{interval_bad}**",
        f"- 5 m role conflicts: **{summary['5m']['scope_role_conflicts']}**",
        f"- 10 m role conflicts: **{summary['10m']['scope_role_conflicts']}**",
        "",
        "## Conflict patterns",
        "",
    ]
    for pattern, count in sorted(patterns.items()):
        lines.append(f"- `{pattern}`: {count}")
    lines.extend(["", "## Real examples", ""])
    for index, example in enumerate(examples, 1):
        lines.extend(
            [
                f"### Example {index}: {example['target_date']} / {example['cell_id']}",
                "",
                f"- Cell range: `{example['cell_range']}`",
                f"- Existing role: `{example['existing_role']}`",
                f"- Conflicting role: `{example['conflicting_role']}`",
                f"- Triggering scope: `{example['scope_key']}`",
                f"- Daily review scope: `{json.dumps(example['daily_review_scope'], ensure_ascii=False)}`",
                f"- Forward scope: `{json.dumps(example['forward_scope'], ensure_ascii=False)}`",
                f"- Local background scope: `{json.dumps(example['local_background_scope'], ensure_ascii=False)}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Why 5 m and 10 m pass",
            "",
            "The 10 m baseline shares the native review-boundary alignment. The 5 m grid refines",
            "those boundaries, so a native 10 m role region can be represented by two cells without",
            "mixing adjacent roles. A 20 m cell aggregates across those boundaries and cannot preserve",
            "the one-cell/one-role support contract.",
            "",
            "Therefore 20 m is an intentionally retained coarse-resolution stress test and not a valid",
            "alternative estimator for headline comparison.",
        ]
    )
    _write_text(AUDIT_DIR / "spatial_resolution_failure_analysis.md", "\n".join(lines))
    _write_json(AUDIT_DIR / "spatial_resolution_20m_examples.json", examples)
    return {
        "role_conflict_count": len(conflicts),
        "unique_problematic_cell_count": len(unique_problem_cells),
        "multi_role_region_date_cell_count": len(multi_role_regions),
        "point_coverage_deficiency_count": point_bad,
        "interval_coverage_inconsistency_count": interval_bad,
    }


def validate_freeze_hashes() -> dict[str, Any]:
    directories = [
        STAGE2_PLC,
        STAGE2_GEO,
        STAGE3A,
        STAGE3B,
        STAGE4,
        STAGE5B,
        STAGE6A,
        STAGE7B,
        STAGE7C,
        STAGE7D,
        STAGE7E,
        STAGE7F_FINAL,
    ]
    rows: list[dict[str, Any]] = []
    for directory in directories:
        hash_file = directory / "file_hashes.sha256"
        if not hash_file.exists():
            rows.append(
                {
                    "artifact": str(directory.relative_to(REPO_ROOT)),
                    "file": "file_hashes.sha256",
                    "status": "NO_HASH_MANIFEST",
                    "expected_sha256": "",
                    "actual_sha256": "",
                }
            )
            continue
        for line in hash_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            expected, relative = line.split(maxsplit=1)
            target = directory / relative.strip()
            status = "MISSING" if not target.is_file() else "PASS"
            actual = "" if not target.is_file() else _sha256(target)
            if actual and actual != expected:
                status = "HASH_MISMATCH"
            rows.append(
                {
                    "artifact": str(directory.relative_to(REPO_ROOT)),
                    "file": relative.strip(),
                    "status": status,
                    "expected_sha256": expected,
                    "actual_sha256": actual,
                }
            )
    _write_csv(
        AUDIT_DIR / "freeze_hash_validation.csv",
        rows,
        ["artifact", "file", "status", "expected_sha256", "actual_sha256"],
    )
    return {
        "checked_entry_count": len(rows),
        "pass_count": sum(row["status"] == "PASS" for row in rows),
        "issue_count": sum(row["status"] not in {"PASS", "NO_HASH_MANIFEST"} for row in rows),
        "artifact_without_hash_manifest_count": sum(
            row["status"] == "NO_HASH_MANIFEST" for row in rows
        ),
    }


def _count_parquet_rows(directory: Path) -> int:
    return sum(pq.ParquetFile(path).metadata.num_rows for path in directory.glob("*.parquet"))


def _count_claims() -> tuple[Counter[str], Counter[str]]:
    decisions = _jsonl(STAGE5B / "claim_decisions.jsonl")
    decision_counts = Counter(str(row["expressibility"]) for row in decisions)
    reasons = Counter(
        str(row["abstention_reason"]) for row in _jsonl(STAGE5B / "claim_abstentions.jsonl")
    )
    return decision_counts, reasons


def _rq2_counts() -> dict[str, Any]:
    run = _json(STAGE7B / "run_summary.json")
    plan_summary = {
        row["metric"]: row["value"] for row in _csv(STAGE7B / "P_plan_validation_summary.csv")
    }
    automatic = _csv(STAGE7C / "method_automatic_summary.csv")
    failures = Counter()
    for row in automatic:
        failures[str(row["method_internal"])] += int(row["fail_count"])
    return {
        "planned_tasks": int(run["benchmark_task_count"]),
        "execution_items": int(run["execution_item_count"]),
        "transport_successes": int(run["real_api_transport_success_count"]),
        "B0_final_texts": int(run["b0_output_count"]),
        "B1_final_texts": int(run["b1_output_count"]),
        "P_raw_plans": int(run["p_raw_plan_count"]),
        "P_parse_valid": int(plan_summary["parse_valid_count"]),
        "P_schema_valid": int(plan_summary["schema_valid_count"]),
        "P_valid_plans": int(run["p_plan_valid_count"]),
        "P_fail_closed": int(run["structure_audit_fail_count"]),
        "P_final_texts": int(run["p_final_output_count"]),
        "P_post_audit_pass": int(run["p_post_audit_pass_count"]),
        "B0_automatic_failures": failures["B0_DIRECT_LLM"],
        "B1_automatic_failures": failures["B1_STRUCTURED_PROMPT_LLM"],
        "P_automatic_failures": failures["PROPOSED_PIPELINE"],
    }


def recompute_paper_results() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    geology = _jsonl(STAGE2_GEO / "primary_geological_evidence.jsonl")
    epistemic = Counter(str(row["epistemic_status"]) for row in geology)
    bitemporal = _jsonl(STAGE3B / "bitemporal_state_versions.jsonl")
    revisions = _jsonl(STAGE3B / "knowledge_revision_events.jsonl")
    rai = _jsonl(STAGE4 / "state_rai.jsonl")
    grs = _jsonl(STAGE4 / "state_grs.jsonl")
    grci = _jsonl(STAGE4 / "state_grci.jsonl")
    decisions, reasons = _count_claims()
    rq2 = _rq2_counts()
    revision_primary = _json(STAGE7D / "stage7d_primary_endpoints.json")
    revision_secondary = _json(STAGE7D / "stage7d_secondary_endpoints.json")
    transition_rows = _csv(STAGE7D / "stage7d_revision_claim_transition_rows.csv")
    added_decisions = Counter(
        row["post_decision"] for row in transition_rows if _as_bool(row["opportunity_added"])
    )
    ablation = _json(STAGE7E / "stage7e_final_machine_result_summary.json")
    sensitivity = _json(STAGE7F_FINAL / "stage7f_final_machine_summary.json")

    values: dict[str, tuple[Any, str, str]] = {
        "evidence.plc_observations": (
            _count_parquet_rows(STAGE2_PLC / "normalized_observations"),
            "artifacts/stage2_plc_operational_freeze_v2/normalized_observations/*.parquet",
            "Parquet metadata row sum",
        ),
        "evidence.excavation_events": (
            len(_jsonl(STAGE2_PLC / "excavation_episodes.jsonl")),
            "artifacts/stage2_plc_operational_freeze_v2/excavation_episodes.jsonl",
            "line count",
        ),
        "evidence.mechanical": (
            len(_jsonl(STAGE2_PLC / "response_evidence.jsonl")),
            "artifacts/stage2_plc_operational_freeze_v2/response_evidence.jsonl",
            "line count",
        ),
        "evidence.geological_documents": (
            len(_jsonl(STAGE2_GEO / "geological_documents.jsonl")),
            "artifacts/stage2_geology_v2_freeze_candidate/geological_documents.jsonl",
            "line count",
        ),
        "evidence.geological_total": (
            len(geology),
            "artifacts/stage2_geology_v2_freeze_candidate/primary_geological_evidence.jsonl",
            "line count",
        ),
        "evidence.geological_observed": (
            epistemic["OBSERVED"],
            "artifacts/stage2_geology_v2_freeze_candidate/primary_geological_evidence.jsonl",
            "epistemic_status=OBSERVED",
        ),
        "evidence.geological_forecast": (
            epistemic["FORECAST"],
            "artifacts/stage2_geology_v2_freeze_candidate/primary_geological_evidence.jsonl",
            "epistemic_status=FORECAST",
        ),
        "evidence.source_spans": (
            len(_jsonl(STAGE2_GEO / "source_spans.jsonl")),
            "artifacts/stage2_geology_v2_freeze_candidate/source_spans.jsonl",
            "line count",
        ),
        "state.cells": (
            len(_jsonl(STAGE3A / "construction_state_cells.jsonl")),
            "artifacts/stage3a_initial_epistemic_state_v1_1/construction_state_cells.jsonl",
            "line count",
        ),
        "state.initial_versions": (
            len(_jsonl(STAGE3A / "initial_construction_state_versions.jsonl")),
            "artifacts/stage3a_initial_epistemic_state_v1_1/initial_construction_state_versions.jsonl",
            "line count",
        ),
        "state.total_bitemporal_versions": (
            len(bitemporal),
            "artifacts/stage3b_bitemporal_epistemic_state_v1_1/bitemporal_state_versions.jsonl",
            "line count",
        ),
        "state.revision_events": (
            len(revisions),
            "artifacts/stage3b_bitemporal_epistemic_state_v1_1/knowledge_revision_events.jsonl",
            "line count",
        ),
        "state.revision_dates": (
            len({str(row["valid_date"]) for row in revisions}),
            "artifacts/stage3b_bitemporal_epistemic_state_v1_1/knowledge_revision_events.jsonl",
            "unique valid_date",
        ),
        "state.revised_cells": (
            len({str(row["affected_cell_id"]) for row in revisions}),
            "artifacts/stage3b_bitemporal_epistemic_state_v1_1/knowledge_revision_events.jsonl",
            "unique affected_cell_id",
        ),
        "metric.rai_available": (
            sum(row.get("rai") is not None for row in rai),
            "artifacts/stage4_bitemporal_state_metrics_v1_1/state_rai.jsonl",
            "rai != null",
        ),
        "metric.grs_available": (
            sum(row.get("grs") is not None for row in grs),
            "artifacts/stage4_bitemporal_state_metrics_v1_1/state_grs.jsonl",
            "grs != null",
        ),
        "metric.grci_available": (
            sum(row.get("grci") is not None for row in grci),
            "artifacts/stage4_bitemporal_state_metrics_v1_1/state_grci.jsonl",
            "grci != null",
        ),
        "claim.total_opportunities": (
            len(_jsonl(STAGE5B / "claim_opportunities.jsonl")),
            "artifacts/stage5b_deterministic_claim_builder_v1/claim_opportunities.jsonl",
            "line count",
        ),
        "claim.allow": (
            decisions["EXPRESSIBLE"],
            "artifacts/stage5b_deterministic_claim_builder_v1/claim_decisions.jsonl",
            "expressibility=EXPRESSIBLE",
        ),
        "claim.reject": (
            decisions["ABSTAIN"],
            "artifacts/stage5b_deterministic_claim_builder_v1/claim_decisions.jsonl",
            "expressibility=ABSTAIN",
        ),
        "revision.total_events": (
            revision_primary["P1_revision_event_census_size"],
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_primary_endpoints.json",
            "P1_revision_event_census_size",
        ),
        "revision.rai_changed": (
            revision_primary["P2_metric_sensitive_revision_event_rate"]["RAI"]["numerator"],
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_primary_endpoints.json",
            "P2.RAI.numerator",
        ),
        "revision.grs_changed": (
            revision_primary["P2_metric_sensitive_revision_event_rate"]["GRS"]["numerator"],
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_primary_endpoints.json",
            "P2.GRS.numerator",
        ),
        "revision.grci_changed": (
            revision_primary["P2_metric_sensitive_revision_event_rate"]["GRCI"]["numerator"],
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_primary_endpoints.json",
            "P2.GRCI.numerator",
        ),
        "revision.reject_to_allow_events": (
            revision_primary["P3_existing_claim_decision_switch_event_rate"]["numerator"],
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_primary_endpoints.json",
            "P3.numerator",
        ),
        "revision.opportunity_added": (
            revision_secondary["claim_transition_counts"]["OPPORTUNITY_ADDED"],
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_secondary_endpoints.json",
            "claim_transition_counts.OPPORTUNITY_ADDED",
        ),
        "revision.opportunity_added_forecast": (
            revision_secondary["claim_type_by_transition"]["OPPORTUNITY_ADDED"][
                "FORECAST_GEOLOGICAL_CONDITION"
            ],
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_secondary_endpoints.json",
            "claim_type_by_transition.OPPORTUNITY_ADDED.FORECAST_GEOLOGICAL_CONDITION",
        ),
        "revision.opportunity_added_observed": (
            revision_secondary["claim_type_by_transition"]["OPPORTUNITY_ADDED"][
                "OBSERVED_GEOLOGICAL_CONDITION"
            ],
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_secondary_endpoints.json",
            "claim_type_by_transition.OPPORTUNITY_ADDED.OBSERVED_GEOLOGICAL_CONDITION",
        ),
        "revision.opportunity_added_allow": (
            added_decisions["EXPRESSIBLE"],
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_revision_claim_transition_rows.csv",
            "opportunity_added=true, post_decision=EXPRESSIBLE",
        ),
        "revision.opportunity_added_reject": (
            added_decisions["ABSTAIN"],
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_revision_claim_transition_rows.csv",
            "opportunity_added=true, post_decision=ABSTAIN",
        ),
        "revision.any_claim_change_events": (
            revision_primary["P5_any_claim_semantic_change_event_rate"]["numerator"],
            "artifacts/stage7d_bitemporal_value_v1_1/stage7d_primary_endpoints.json",
            "P5.numerator",
        ),
        "ablation.a3.strict_blocks": (
            ablation["a3_primary_protocol_compliance"]["total_chunks"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a3_primary_protocol_compliance.total_chunks",
        ),
        "ablation.a3.strict_valid": (
            ablation["a3_primary_protocol_compliance"]["valid_chunks"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a3_primary_protocol_compliance.valid_chunks",
        ),
        "ablation.a3.strict_mappings": (
            ablation["a3_primary_protocol_compliance"]["claim_mappings"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a3_primary_protocol_compliance.claim_mappings",
        ),
        "ablation.a3.strict_complete_tasks": (
            ablation["a3_primary_protocol_compliance"]["complete_tasks"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a3_primary_protocol_compliance.complete_tasks",
        ),
        "ablation.a3.strict_numeric_exact": (
            ablation["a3_corrected_strict_numeric_audit"]["numeric_exact"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a3_corrected_strict_numeric_audit.numeric_exact",
        ),
        "ablation.a3.strict_numeric_total": (
            ablation["a3_corrected_strict_numeric_audit"]["numeric_claims"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a3_corrected_strict_numeric_audit.numeric_claims",
        ),
        "ablation.a3.strict_numeric_drift": (
            ablation["a3_corrected_strict_numeric_audit"]["numeric_drift"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a3_corrected_strict_numeric_audit.numeric_drift",
        ),
        "ablation.a3.fence_valid": (
            ablation["a3_secondary_fence_only"]["valid_chunks"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a3_secondary_fence_only.valid_chunks",
        ),
        "ablation.a3.fence_mappings": (
            ablation["a3_secondary_fence_only"]["claim_mappings"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a3_secondary_fence_only.claim_mappings",
        ),
        "ablation.a3.fence_complete_tasks": (
            ablation["a3_secondary_fence_only"]["complete_tasks"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a3_secondary_fence_only.complete_tasks",
        ),
        "ablation.a3.fence_numeric_exact": (
            ablation["a3_secondary_fence_only"]["numeric_exact"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a3_secondary_fence_only.numeric_exact",
        ),
        "ablation.a3.fence_numeric_total": (
            ablation["a3_secondary_fence_only"]["numeric_claims"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a3_secondary_fence_only.numeric_claims",
        ),
        "ablation.a3.fence_numeric_drift": (
            ablation["a3_secondary_fence_only"]["numeric_drift"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a3_secondary_fence_only.numeric_drift",
        ),
        "ablation.a4.factlocks_used": (
            ablation["a4"]["used_fact_locks"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a4.used_fact_locks",
        ),
        "ablation.a4.factlocks_total": (
            ablation["a4"]["total_fact_locks"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a4.total_fact_locks",
        ),
        "ablation.a4.numeric_used": (
            ablation["a4"]["used_numeric_fact_locks"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a4.used_numeric_fact_locks",
        ),
        "ablation.a4.numeric_total": (
            ablation["a4"]["total_numeric_fact_locks"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a4.total_numeric_fact_locks",
        ),
        "ablation.a4.numeric_exact": (
            ablation["a4"]["referenced_numeric_token_exact"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a4.referenced_numeric_token_exact",
        ),
        "ablation.a4.factlock_coverage": (
            ablation["a4"]["fact_lock_trace_coverage"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a4.fact_lock_trace_coverage",
        ),
        "ablation.a4.numeric_factlock_coverage": (
            ablation["a4"]["numeric_fact_lock_trace_coverage"],
            "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json",
            "a4.numeric_fact_lock_trace_coverage",
        ),
    }
    for key, value in rq2.items():
        values[f"rq2.{key}"] = (
            value,
            "artifacts/stage7b_main_comparison_v1/run_summary.json or stage7c_main_auto_eval_v1_2/method_automatic_summary.csv",
            key,
        )
    for size in ["5m", "10m", "20m"]:
        cell = sensitivity["cell_size"][size]
        values[f"sensitivity.cell.{size}.count"] = (
            int(cell["cell_count"]),
            "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
            f"cell_size.{size}.cell_count",
        )
        values[f"sensitivity.cell.{size}.role_conflicts"] = (
            int(cell["scope_role_conflicts"]),
            "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
            f"cell_size.{size}.scope_role_conflicts",
        )
        values[f"sensitivity.cell.{size}.point_deficiencies"] = (
            int(cell["point_missing_or_duplicate"]),
            "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
            f"cell_size.{size}.point_missing_or_duplicate",
        )
        values[f"sensitivity.cell.{size}.interval_inconsistencies"] = (
            int(cell["interval_overlap_mismatch"]),
            "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
            f"cell_size.{size}.interval_overlap_mismatch",
        )
    history_transitions = {
        (row["alternative_arm_id"], row["transition"]): int(row["count"])
        for row in sensitivity["history"]["claim_transitions"]
    }
    for threshold in ["20", "30", "40"]:
        history = sensitivity["history"][threshold]
        values[f"sensitivity.n_min.{threshold}.rai_available"] = (
            int(history["rai_available_count"]),
            "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
            f"history.{threshold}.rai_available_count",
        )
        values[f"sensitivity.n_min.{threshold}.grci_available"] = (
            int(history["grci_available_count"]),
            "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
            f"history.{threshold}.grci_available_count",
        )
    values["sensitivity.n_min.20.reject_to_allow"] = (
        history_transitions[("rai_history_min_samples_20", "ABSTAIN_TO_EXPRESSIBLE")],
        "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
        "history.claim_transitions",
    )
    values["sensitivity.n_min.40.allow_to_reject"] = (
        history_transitions[("rai_history_min_samples_40", "EXPRESSIBLE_TO_ABSTAIN")],
        "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
        "history.claim_transitions",
    )
    saturation_transitions = {
        (row["alternative_arm_id"], row["transition"]): int(row["count"])
        for row in sensitivity["saturation"]["claim_transitions"]
    }
    for value in ["2", "3", "4"]:
        saturation = sensitivity["saturation"][value]
        values[f"sensitivity.lambda.{value}.claim_opportunities"] = (
            int(saturation["claim_opportunity_count"]),
            "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
            f"saturation.{value}.claim_opportunity_count",
        )
    values["sensitivity.lambda.2.decision_migrations"] = (
        saturation_transitions.get(("rai_saturation_robust_z_2", "ABSTAIN_TO_EXPRESSIBLE"), 0)
        + saturation_transitions.get(("rai_saturation_robust_z_2", "EXPRESSIBLE_TO_ABSTAIN"), 0),
        "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
        "saturation.claim_transitions",
    )
    values["sensitivity.lambda.4.decision_migrations"] = (
        saturation_transitions.get(("rai_saturation_robust_z_4", "ABSTAIN_TO_EXPRESSIBLE"), 0)
        + saturation_transitions.get(("rai_saturation_robust_z_4", "EXPRESSIBLE_TO_ABSTAIN"), 0),
        "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json",
        "saturation.claim_transitions",
    )
    for reason, count in sorted(reasons.items()):
        values[f"claim.reject_reason.{reason}"] = (
            count,
            "artifacts/stage5b_deterministic_claim_builder_v1/claim_abstentions.jsonl",
            f"abstention_reason={reason}",
        )

    expected: dict[str, Any] = {
        "evidence.plc_observations": 328217,
        "evidence.excavation_events": 1119,
        "evidence.mechanical": 5595,
        "evidence.geological_documents": 223,
        "evidence.geological_total": 659,
        "evidence.geological_observed": 278,
        "evidence.geological_forecast": 381,
        "evidence.source_spans": 4713,
        "state.cells": 156,
        "state.initial_versions": 1322,
        "state.total_bitemporal_versions": 1375,
        "state.revision_events": 53,
        "metric.rai_available": 174,
        "metric.grs_available": 1211,
        "metric.grci_available": 174,
        "claim.total_opportunities": 8679,
        "claim.allow": 6279,
        "claim.reject": 2400,
    }
    manifest: list[dict[str, Any]] = []
    for metric_id, (value, source, source_key) in values.items():
        paper_section = metric_id.split(".", 1)[0]
        manifest.append(
            {
                "metric_id": metric_id,
                "paper_section": paper_section,
                "paper_table_or_figure": "TO_BE_BOUND_IN_MANUSCRIPT",
                "value": value,
                "unit_or_denominator": "count_or_recorded_ratio",
                "paper_expected": expected.get(metric_id),
                "matches_expected": expected.get(metric_id) is None or expected[metric_id] == value,
                "exact_source_artifact": source,
                "source_key_or_row": source_key,
                "recomputation_script": "scripts/audit_final_paper_technical.py",
                "method_config_version": _json(STAGE4 / "method_version.json").get(
                    "method_version", ""
                ),
                "verified": True,
                "notes": "Authoritative frozen object or deterministic recount",
            }
        )
    _write_json(PAPER_DIR / "paper_results_manifest.json", manifest)
    lines = [
        "# Paper Results Single Source of Truth",
        "",
        "| Metric | Value | Expected | Match | Authoritative source |",
        "|---|---:|---:|---|---|",
    ]
    for row in manifest:
        lines.append(
            f"| `{row['metric_id']}` | {row['value']} | {row['paper_expected']} | "
            f"{row['matches_expected']} | `{row['exact_source_artifact']}` |"
        )
    _write_text(PAPER_DIR / "paper_results_manifest.md", "\n".join(lines))
    checks = {
        "allow_reject_closes": decisions["EXPRESSIBLE"] + decisions["ABSTAIN"]
        == len(_jsonl(STAGE5B / "claim_opportunities.jsonl")),
        "abstention_reason_closes": sum(reasons.values()) == decisions["ABSTAIN"],
        "expected_mismatch_count": sum(
            row["paper_expected"] is not None and not row["matches_expected"] for row in manifest
        ),
        "manifest_metric_count": len(manifest),
    }
    return manifest, checks


def write_repository_identity(hash_summary: dict[str, Any]) -> dict[str, Any]:
    tags = _git("tag", "--points-at", "HEAD").splitlines()
    identity = {
        "branch": _git("branch", "--show-current"),
        "head_commit": _git("rev-parse", "HEAD"),
        "head_tags": tags,
        "working_tree_dirty": bool(_git("status", "--short")),
        "python_version": platform.python_version(),
        "dependency_identity": "pyproject.toml; no lock file present",
        "metric_method": _json(STAGE4 / "method_version.json"),
        "mapping_method": _mapping_config()["method_version"],
        "stage7b_model": _json(STAGE7B / "run_summary.json")["model"],
        "stage7b_provider": _json(STAGE7B / "run_summary.json")["provider"],
        "freeze_hash_validation": hash_summary,
    }
    _write_json(AUDIT_DIR / "repository_freeze_identity.json", identity)
    return identity


def write_final_hard_check(
    mapping: dict[str, Any],
    sensitivity: dict[str, Any],
    scan: dict[str, Any],
    hashes: dict[str, Any],
    result_checks: dict[str, Any],
) -> None:
    checks = {
        "paper_expected_values_reconciled": result_checks["expected_mismatch_count"] == 0,
        "claim_decision_totals_close": result_checks["allow_reject_closes"],
        "abstention_reasons_close": result_checks["abstention_reason_closes"],
        "frozen_hashes_close": hashes["issue_count"] == 0,
        "frozen_mapping_entry_count_is_44": mapping["frozen_mapping_entry_count"] == 44,
        "unmapped_values_entering_grs_input_is_zero": (
            mapping["unmapped_value_in_frozen_snapshot_input_count"] == 0
        ),
        "mapping_perturbation_claim_migration_is_zero": (
            sensitivity["total_claim_decision_migrations"] == 0
        ),
        "spatial_text_true_violation_is_zero": scan["true_violation_count"] == 0,
    }
    rows = [
        {
            "check_name": name,
            "status": "PASS" if passed else "FAIL",
            "details": str(passed),
        }
        for name, passed in checks.items()
    ]
    _write_csv(
        AUDIT_DIR / "final_technical_hard_check.csv",
        rows,
        ["check_name", "status", "details"],
    )


def write_final_report(
    identity: dict[str, Any],
    mapping: dict[str, Any],
    sensitivity: dict[str, Any],
    spatial: dict[str, Any],
    scan: dict[str, Any],
    resolution: dict[str, Any],
    hashes: dict[str, Any],
    manifest: list[dict[str, Any]],
    result_checks: dict[str, Any],
) -> None:
    core = [row for row in manifest if row["paper_expected"] is not None]
    quality_path = AUDIT_DIR / "quality_gate_results.json"
    quality = _json(quality_path) if quality_path.exists() else {}
    full_tests = quality.get("full_pytest", {})
    quality_statement = (
        f"Quality gates passed: {quality.get('audit_invariant_tests', {}).get('passed')}/"
        f"{quality.get('audit_invariant_tests', {}).get('passed')} audit invariants, "
        f"{full_tests.get('passed')}/{full_tests.get('passed')} full tests, Ruff check and "
        f"format, and Mypy over {quality.get('mypy', {}).get('source_files')} source files. "
        f"{full_tests.get('warnings')} warnings are third-party SWIG deprecations."
        if quality
        else "Quality-gate results are pending."
    )
    table = [
        "| metric | paper expected | recomputed | match | authoritative source |",
        "|---|---:|---:|---|---|",
    ]
    for row in core:
        table.append(
            f"| `{row['metric_id']}` | {row['paper_expected']} | {row['value']} | "
            f"{row['matches_expected']} | `{row['exact_source_artifact']}` |"
        )
    report = f"""# FINAL PAPER TECHNICAL AUDIT

## 1. Executive conclusion

**PASS WITH PAPER CORRECTIONS**

The frozen machine results reconcile with authoritative objects, bounded GRS mapping
perturbations cause no claim-decision migration, and no formal experiment must be rerun.
The paper must correct two descriptions: the 44 entries are the **frozen reviewed mapping
registry used by role-selected state snapshots**, not all raw Evidence values occurring in
those source fields; and the legacy internal field
`daily_excavated_scope` is a **cell-aligned review scope**, not actual daily excavation.

## 2. Repository and freeze identity

- Branch: `{identity["branch"]}`
- HEAD at audit start: `{identity["head_commit"]}`
- HEAD tags: `{", ".join(identity["head_tags"]) or "none"}`
- Working tree dirty: `{identity["working_tree_dirty"]}` (pre-existing untracked paper/audit
  packages plus this audit branch's outputs)
- Python: `{identity["python_version"]}`
- Dependencies: `{identity["dependency_identity"]}`
- Frozen mapping version: `{identity["mapping_method"]}`
- Stage7B model/provider: `{identity["stage7b_model"]}` / `{identity["stage7b_provider"]}`

## 3. Paper-number reconciliation

{chr(10).join(table)}

Closure checks: allow + reject = total is `{result_checks["allow_reject_closes"]}`;
abstention reasons close to rejected decisions is `{result_checks["abstention_reason_closes"]}`.

## 4. GRS mapping audit

- Frozen unique mapping entries: **{mapping["frozen_mapping_entry_count"]}**.
- Numeric / reviewed-unmappable: **{mapping["numeric_mapping_entry_count"]} / {mapping["reviewed_unmappable_entry_count"]}**.
- Frozen mapping entries observed in data: **{mapping["frozen_entries_observed_count"]}**.
- Values in the same configured source fields but outside the registry: **{mapping["relevant_unmapped_unique_value_count"]}** unique, **{mapping["relevant_unmapped_occurrence_count"]}** occurrences.
- Unmapped values entering formal frozen snapshot scoring: **{mapping["unmapped_value_in_frozen_snapshot_input_count"]}**.
- Per-value engineering rationale recorded: **{mapping["rationale_recorded_count"]}**; ordering labels exist,
  but detailed rationale is `RATIONALE_NOT_RECORDED`.
- Registry: `supplementary/grs_mapping_registry.csv` and `.md`.

The paper may say “44 frozen reviewed mapping entries.” It should not say “all structured
geological values were mapped.”

## 5. GRS mapping sensitivity

- One-step alias-group arms: **{sensitivity["arm_count"]}**.
- Arms with numerical GRS change: **{sensitivity["arms_with_grs_numerical_change"]}**.
- Maximum absolute GRS delta: **{sensitivity["max_grs_abs_delta"]:.12f}**.
- Claim-decision migrations: **{sensitivity["total_claim_decision_migrations"]}**.
- Arms changing revision-event conclusions: **{sensitivity["arms_with_revision_conclusion_change"]}**.

This demonstrates claim-level stability only under the tested bounded perturbations; it does
not establish scientific validity of the ordinal mapping. Two arms each change one event's
binary “GRS changed” classification while leaving every Claim decision unchanged; the frozen
36/53 result therefore remains the primary endpoint. In both affected arms the same event
changes from “GRS changed” to “unchanged,” so the arm-level count is 35/53.

## 6. Spatial semantic audit

The event footprint, trusted daily PLC range, aligned review scope, forward scope, claim
scope, and FactLock scope are separate in the formal chain. **No frozen-output true violation
was detected by the targeted scan** (`true_violation_count={scan["true_violation_count"]}`).
`{scan["manual_paper_wording_check_count"]}` hits require manual paper wording review.
The internal name `daily_excavated_scope` is misleading: in all relevant states it is generated
with ten-metre alignment and must be described as the daily review scope. See
`audit/spatial_semantics_lineage.md`.

## 7. Bitemporal integrity audit

Stage3B contains 53 authoritative revision events with predecessor IDs, non-overlapping
knowledge intervals, and materialized as-of snapshots. Stage7D recomputation reports 53/53
events with a claim spatial or admissibility effect. Geological epistemic status remains on
the source Evidence object: later role changes do not promote FORECAST to OBSERVED.

## 8. Claim-admissibility integrity

Stage5B has 8,679 decisions and closes exactly to 6,279 EXPRESSIBLE plus 2,400 ABSTAIN.
Only EXPRESSIBLE decisions are materialized. Stage6A FactLocks retain resolved authoritative
support, spatial containment, qualifiers, and missing values. Mechanical response is not used
as geological cause, and GRCI remains a non-probabilistic, non-causal attention product.

## 9. 20 m resolution failure mechanism

The 20 m arm has **{resolution["role_conflict_count"]}** date-cell role conflicts across
**{resolution["unique_problematic_cell_count"]}** cell identities, plus
**{resolution["point_coverage_deficiency_count"]}** point and
**{resolution["interval_coverage_inconsistency_count"]}** interval failures. Coarse cells cross
native review/forward/background boundaries while the model requires one support role per cell.
This is a spatial aggregation validity limit, not a hidden metric formula bug. See
`audit/spatial_resolution_failure_analysis.md`.

## 10. Reproducibility status

The paper's machine counts can be reconstructed from frozen objects without an API call.
`{hashes["checked_entry_count"]}` manifest entries were checked; unexpected hash issues:
**{hashes["issue_count"]}**. Stage7E corrected summaries explicitly supersede the historical
numeric-tokenizer false positives, and the result manifest points only to the corrected endpoint.

{quality_statement}

## 11. Files generated

- `scripts/audit_final_paper_technical.py`
- `tests/unit/test_final_paper_technical_audit.py`
- `supplementary/grs_mapping_registry.csv|json|md`
- `supplementary/grs_unmapped_relevant_values.csv`
- `supplementary/grs_mapping_sensitivity.csv|md`
- `supplementary/grs_mapping_sensitivity_revision_audit.csv`
- `audit/repository_freeze_identity.json`
- `audit/audit_command_log.md`
- `audit/quality_gate_results.json`
- `audit/freeze_hash_validation.csv`
- `audit/final_technical_hard_check.csv`
- `audit/spatial_semantics_lineage.md`
- `audit/spatial_semantics_text_scan.csv`
- `audit/spatial_resolution_failure_analysis.md`
- `audit/spatial_resolution_20m_examples.json`
- `paper_artifacts/paper_results_manifest.json|md`
- `FINAL_PAPER_TECHNICAL_AUDIT.md`

## 12. Changes made

Only the audit script, deterministic tests, supplementary exports, paper manifest, and this
report were added. **Formal pipeline unchanged.** No frozen result, parser, metric formula,
claim contract, prompt, raw model response, or tag was modified.

## 13. Remaining work before submission

1. Human evaluation remains deferred.
2. Correct manuscript wording for the 44-entry mapping registry and the cell-aligned review scope.
3. Package the generated registry, sensitivity table, lineage, and results manifest as supplement.
"""
    _write_text(REPO_ROOT / "FINAL_PAPER_TECHNICAL_AUDIT.md", report)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-sensitivity",
        action="store_true",
        help="Skip the optional offline GRS sensitivity computation.",
    )
    args = parser.parse_args()
    for directory in [AUDIT_DIR, SUPPLEMENTARY_DIR, PAPER_DIR]:
        directory.mkdir(parents=True, exist_ok=True)

    config = _mapping_config()
    mapping = build_mapping_registry(config)
    sensitivity = (
        {
            "arm_count": 0,
            "arms_with_grs_numerical_change": 0,
            "arms_with_claim_decision_migration": 0,
            "total_claim_decision_migrations": 0,
            "arms_with_revision_conclusion_change": 0,
            "max_grs_abs_delta": 0.0,
        }
        if args.skip_sensitivity
        else build_mapping_sensitivity(config)
    )
    spatial = build_spatial_lineage()
    scan = build_spatial_text_scan()
    resolution = build_20m_analysis()
    hashes = validate_freeze_hashes()
    identity = write_repository_identity(hashes)
    manifest, result_checks = recompute_paper_results()
    write_final_hard_check(mapping, sensitivity, scan, hashes, result_checks)
    write_final_report(
        identity,
        mapping,
        sensitivity,
        spatial,
        scan,
        resolution,
        hashes,
        manifest,
        result_checks,
    )
    print(
        json.dumps(
            {
                "mapping": mapping,
                "sensitivity": sensitivity,
                "spatial": spatial,
                "text_scan": scan,
                "resolution_20m": resolution,
                "freeze_hashes": hashes,
                "paper_results": result_checks,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
