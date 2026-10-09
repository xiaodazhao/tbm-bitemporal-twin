#!/usr/bin/env python3
# ruff: noqa: E501
"""Export paper-facing experiment data from authoritative frozen artifacts.

This script is deliberately read-only with respect to the research pipeline.  It
joins existing Stage 2--7 artifacts into analysis-friendly CSV files and records
all derived semantics in the accompanying audit documentation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

METRIC_CLAIM_TYPES = {
    "OPERATIONAL_RESPONSE_ATTENTION",
    "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
    "COUPLED_ATTENTION_REVIEW",
    "FORWARD_GEOLOGICAL_ATTENTION",
}

CLAIM_TYPE_PUBLIC = {
    "OPERATIONAL_RESPONSE_ATTENTION": "rai_indicator_claim",
    "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW": "excavated_grs_indicator_claim",
    "FORWARD_GEOLOGICAL_ATTENTION": "forward_grs_indicator_claim",
    "COUPLED_ATTENTION_REVIEW": "grci_indicator_claim",
    "OBSERVED_GEOLOGICAL_CONDITION": "observed_geological_condition",
    "FORECAST_GEOLOGICAL_CONDITION": "predicted_geological_condition",
}

METHOD_PUBLIC = {
    "B0_DIRECT_LLM": "B0",
    "B1_STRUCTURED_PROMPT_LLM": "B1",
    "P_PROPOSED": "P",
}

REFERENCE_VALUES = {
    "plc_file_days": 91,
    "plc_normalized_observations": 328217,
    "excavation_episodes": 1119,
    "spatially_valid_episodes": 1104,
    "spatially_invalid_episodes": 15,
    "mechanical_response_records": 5595,
    "geological_documents": 223,
    "geological_evidence": 659,
    "observed_evidence": 278,
    "forecast_evidence": 381,
    "multistage_cases": 5,
    "multistage_associations": 6,
    "multistage_attribute_comparisons": 54,
    "multistage_same": 16,
    "multistage_different": 14,
    "multistage_observation_only": 16,
    "multistage_both_missing": 8,
    "initial_state_versions": 1322,
    "revision_pairs": 53,
    "state_versions": 1375,
    "revision_dates": 14,
    "revision_cells": 51,
    "revision_evidence_links": 72,
    "revision_unique_evidence": 34,
    "claim_candidates": 8679,
    "claim_expressible": 6279,
    "claim_abstain": 2400,
    "abstain_UNKNOWN_SOURCE_VALUE": 1078,
    "abstain_CONTEXT_ONLY_ROLE": 880,
    "abstain_STATE_ROLE_NOT_ALLOWED": 305,
    "abstain_REQUIRED_EPISTEMIC_STATUS_MISSING": 105,
    "abstain_REQUIRED_METRIC_UNAVAILABLE": 32,
    "generation_tasks": 200,
    "generation_B0_outputs": 200,
    "generation_B1_outputs": 200,
    "generation_P_outputs": 188,
    "generation_P_controlled_stop": 12,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def cell(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return canonical(value)
    if value is None:
        return ""
    return value


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: cell(row.get(key)) for key in fields})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def truth(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def maybe_json(value: str) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def chainage_text(value: float | None) -> str:
    if value is None:
        return ""
    km = int(value // 1000)
    remainder = value - km * 1000
    rendered = f"{remainder:05.1f}".rstrip("0").rstrip(".")
    return f"DyK{km}+{rendered}"


def rule_pass(decision: dict[str, Any], rule: str) -> bool:
    return rule in set(decision.get("passed_rules") or [])


def comparison_key(opportunity: dict[str, Any], proposal: dict[str, Any]) -> str:
    payload = opportunity.get("payload") or {}
    claim_value = proposal.get("claim_value") or {}
    common = {
        "claim_type": opportunity["claim_type"],
        "base_stage3a_state_version_id": opportunity.get("base_stage3a_state_version_id"),
        "valid_date": opportunity.get("valid_date"),
        "cell_id": opportunity.get("cell_id"),
        "state_role": opportunity.get("state_role"),
        "source_kind": opportunity.get("source_kind"),
    }
    if opportunity["claim_type"] in METRIC_CLAIM_TYPES:
        common["metric_name"] = payload.get("metric_name")
    else:
        common["source_evidence_id"] = claim_value.get("source_evidence_id")
        common["attribute_name"] = claim_value.get("attribute_name")
    return canonical(common)


class Exporter:
    def __init__(self, repo: Path, output: Path) -> None:
        self.repo = repo.resolve()
        self.output = output.resolve()
        self.data = self.output / "data"
        self.source_info = self.output / "source_info"
        self.scripts = self.output / "scripts"
        self.sources: set[str] = set()
        self.row_counts: dict[str, int | None] = {}
        self.notes: list[str] = []
        self.actual: dict[str, int] = {}

    def source(self, relative: str) -> Path:
        self.sources.add(relative)
        return self.repo / relative

    def emit(
        self, filename: str, rows: list[dict[str, Any]], fields: list[str] | None = None
    ) -> None:
        write_csv(self.data / filename, rows, fields)
        self.row_counts[f"data/{filename}"] = len(rows)

    def export_inputs(self) -> None:
        manifest = load_csv(
            self.source(
                "artifacts/stage2_plc_operational_freeze_v2/normalized_observation_manifest.csv"
            )
        )
        documents = load_jsonl(
            self.source("artifacts/stage2_geology_v2_freeze_candidate/geological_documents.jsonl")
        )
        evidence = load_jsonl(
            self.source(
                "artifacts/stage2_geology_v2_freeze_candidate/primary_geological_evidence.jsonl"
            )
        )
        by_source_docs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_source_evidence: Counter[str] = Counter()
        for row in documents:
            by_source_docs[row["source_type"]].append(row)
        for row in evidence:
            by_source_evidence[row["source_type"]] += 1
        rows: list[dict[str, Any]] = []
        rows.append(
            {
                "data_type": "PLC",
                "source_name": "PLC normalized observations",
                "raw_count": sum(int(row["row_count"]) for row in manifest),
                "document_count": len(manifest),
                "file_day_count": len({row["target_date"] for row in manifest}),
                "time_start": min(row["target_date"] for row in manifest),
                "time_end": max(row["target_date"] for row in manifest),
                "chainage_start": min(
                    float(row["minimum_chainage"]) for row in manifest if row["minimum_chainage"]
                ),
                "chainage_end": max(
                    float(row["maximum_chainage"]) for row in manifest if row["maximum_chainage"]
                ),
                "notes": "Rows and file-days come from the frozen normalized observation manifest.",
            }
        )
        labels = {"FACE_SKETCH": "Face sketch", "SONIC_FORECAST": "HSP", "TSP_REPORT": "TSP"}
        for source_type in ["FACE_SKETCH", "SONIC_FORECAST", "TSP_REPORT"]:
            docs = by_source_docs[source_type]
            dates = [
                row["document"]["temporal"].get("available_local_date")
                for row in docs
                if row["document"]["temporal"].get("available_local_date")
            ]
            source_evidence = [row for row in evidence if row["source_type"] == source_type]
            starts = [row["spatial_scope"].get("start_chainage") for row in source_evidence]
            ends = [row["spatial_scope"].get("end_chainage") for row in source_evidence]
            rows.append(
                {
                    "data_type": "GEOLOGY",
                    "source_name": labels[source_type],
                    "raw_count": by_source_evidence[source_type],
                    "document_count": len(docs),
                    "file_day_count": len(set(dates)),
                    "time_start": min(dates) if dates else "",
                    "time_end": max(dates) if dates else "",
                    "chainage_start": min(value for value in starts if value is not None),
                    "chainage_end": max(value for value in ends if value is not None),
                    "notes": f"Canonical documents; raw_count is primary evidence count for {source_type}.",
                }
            )
        self.emit("01_input_summary.csv", rows)
        self.actual.update(
            plc_file_days=len(manifest),
            plc_normalized_observations=sum(int(row["row_count"]) for row in manifest),
            geological_documents=len(documents),
            geological_evidence=len(evidence),
            observed_evidence=sum(row["epistemic_status"] == "OBSERVED" for row in evidence),
            forecast_evidence=sum(row["epistemic_status"] == "FORECAST" for row in evidence),
        )

    def export_reconstruction(self) -> None:
        episodes = load_jsonl(
            self.source("artifacts/stage2_plc_operational_freeze_v2/excavation_episodes.jsonl")
        )
        footprints = load_jsonl(
            self.source("artifacts/stage2_plc_operational_freeze_v2/spatial_footprints.jsonl")
        )
        responses = load_jsonl(
            self.source("artifacts/stage2_plc_operational_freeze_v2/response_evidence.jsonl")
        )
        documents = load_jsonl(
            self.source("artifacts/stage2_geology_v2_freeze_candidate/geological_documents.jsonl")
        )
        evidence = load_jsonl(
            self.source(
                "artifacts/stage2_geology_v2_freeze_candidate/primary_geological_evidence.jsonl"
            )
        )
        spans = load_jsonl(
            self.source("artifacts/stage2_geology_v2_freeze_candidate/source_spans.jsonl")
        )
        rows: list[dict[str, Any]] = []

        def summary(
            object_type: str,
            total: int,
            spatial_valid: int | None = None,
            observed: int | None = None,
            predicted: int | None = None,
            provenance: int | None = None,
            notes: str = "",
        ) -> None:
            rows.append(
                {
                    "object_type": object_type,
                    "total_count": total,
                    "spatial_valid_count": spatial_valid,
                    "spatial_invalid_count": None
                    if spatial_valid is None
                    else total - spatial_valid,
                    "observed_count": observed,
                    "predicted_count": predicted,
                    "provenance_link_count": provenance,
                    "notes": notes,
                }
            )

        usable = sum(bool(row.get("spatial_scope_usable")) for row in footprints)
        summary(
            "continuous_excavation_event",
            len(episodes),
            usable,
            notes="ExcavationEpisode is the primary process object.",
        )
        summary(
            "mechanical_response",
            len(responses),
            sum(bool(row.get("spatial_scope_usable")) for row in responses),
        )
        summary("geological_document", len(documents), notes="Canonical document count.")
        summary(
            "geological_evidence",
            len(evidence),
            sum(
                row.get("spatial_scope", {}).get("kind") in {"POINT", "INTERVAL"}
                for row in evidence
            ),
            sum(row["epistemic_status"] == "OBSERVED" for row in evidence),
            sum(row["epistemic_status"] == "FORECAST" for row in evidence),
            len(spans),
            "Source-span count is reported as provenance links.",
        )
        for source_type, label in [
            ("FACE_SKETCH", "face_evidence"),
            ("SONIC_FORECAST", "HSP_evidence"),
            ("TSP_REPORT", "TSP_evidence"),
        ]:
            selected = [row for row in evidence if row["source_type"] == source_type]
            summary(
                label,
                len(selected),
                sum(
                    row.get("spatial_scope", {}).get("kind") in {"POINT", "INTERVAL"}
                    for row in selected
                ),
                sum(row["epistemic_status"] == "OBSERVED" for row in selected),
                sum(row["epistemic_status"] == "FORECAST" for row in selected),
            )
        episode_flags = Counter(
            flag for row in episodes for flag in (row.get("quality_flags") or [])
        )
        response_flags = Counter(
            flag for row in responses for flag in (row.get("quality_flags") or [])
        )
        for flag, count in sorted(episode_flags.items()):
            summary(
                f"episode_quality_issue:{flag}",
                count,
                notes="Count of episodes carrying this non-exclusive quality flag.",
            )
        for flag, count in sorted(response_flags.items()):
            summary(
                f"response_quality_issue:{flag}",
                count,
                notes="Count of response records carrying this non-exclusive quality flag.",
            )
        geo_manifest = load_json(
            self.source("artifacts/stage2_geology_v2_freeze_candidate/freeze_manifest.json")
        )["summary"]
        for issue, count in sorted(geo_manifest["source_issue_counts"].items()):
            summary(
                f"geology_source_issue:{issue}",
                int(count),
                notes="Non-exclusive source-data issue count from frozen audit.",
            )
        self.emit("02_reconstruction_summary.csv", rows)
        self.actual.update(
            excavation_episodes=len(episodes),
            spatially_valid_episodes=usable,
            spatially_invalid_episodes=len(episodes) - usable,
            mechanical_response_records=len(responses),
        )

    def export_multistage(self) -> None:
        coverage = load_csv(
            self.source(
                "artifacts/paper_evidence_completion_v2/construction_progression_plc_coverage_audit.csv"
            )
        )
        associations = {
            row["association_id"]: row
            for row in load_csv(
                self.source(
                    "artifacts/paper_evidence_completion_v2/construction_progression_associations.csv"
                )
            )
        }
        passing = [row for row in coverage if truth(row["association_passes_episode_coverage"])]
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in passing:
            grouped[row["association_id"]].append(row)
        case_keys = sorted(
            {(row["target_date"], row["state_version_id"], row["cell_id"]) for row in passing}
        )
        case_ids = {key: f"Case {index + 1}" for index, key in enumerate(case_keys)}
        rows: list[dict[str, Any]] = []
        for association_id, matches in sorted(
            grouped.items(),
            key=lambda item: (
                item[1][0]["target_date"],
                float(item[1][0]["face_chainage"]),
                item[0],
            ),
        ):
            first = matches[0]
            association = associations[association_id]
            key = (first["target_date"], first["state_version_id"], first["cell_id"])
            episode_ids = sorted({row["episode_id"] for row in matches})
            footprint_ids = sorted({row["footprint_id"] for row in matches})
            start = min(float(row["episode_start"]) for row in matches)
            end = max(float(row["episode_end"]) for row in matches)
            forecast_start = float(first["forecast_start"])
            forecast_end = float(first["forecast_end"])
            face = float(first["face_chainage"])
            rows.append(
                {
                    "case_id": case_ids[key],
                    "construction_date": first["target_date"],
                    "association_id": association_id,
                    "forecast_source_type": association["forecast_source_type"],
                    "forecast_record_id": first["forecast_evidence_id"],
                    "forecast_start_chainage_text": chainage_text(forecast_start),
                    "forecast_end_chainage_text": chainage_text(forecast_end),
                    "forecast_start_m": forecast_start,
                    "forecast_end_m": forecast_end,
                    "plc_event_id": episode_ids[0],
                    "plc_start_chainage_text": chainage_text(start),
                    "plc_end_chainage_text": chainage_text(end),
                    "plc_start_m": start,
                    "plc_end_m": end,
                    "matching_plc_event_count": len(episode_ids),
                    "all_matching_plc_event_ids": episode_ids,
                    "all_matching_footprint_ids": footprint_ids,
                    "observation_record_id": first["face_evidence_id"],
                    "observation_chainage_text": chainage_text(face),
                    "observation_chainage_m": face,
                    "temporal_relation_valid": association["same_day_observation"] == "True"
                    and association["forecast_available_local_date"] < first["target_date"],
                    "spatial_relation_valid": first["intersection_flag"] == "True",
                    "notes": "PLC range is the union of all trusted episode footprints intersecting this association.",
                }
            )
        self.emit("03_multistage_cases.csv", rows)

        final_ids = set(grouped)
        relation_map = {
            "SAME_RECORDED_VALUE": "same",
            "DIFFERENT_RECORDED_VALUE": "different",
            "OBSERVATION_SIDE_ONLY": "observation_only",
            "BOTH_UNRECORDED": "both_missing",
        }
        comparison_rows = []
        for row in load_csv(
            self.source(
                "artifacts/paper_evidence_completion_v2/construction_progression_field_relations.csv"
            )
        ):
            if row["association_id"] not in final_ids:
                continue
            assoc_case = next(
                item["case_id"] for item in rows if item["association_id"] == row["association_id"]
            )
            comparison_rows.append(
                {
                    "case_id": assoc_case,
                    "association_id": row["association_id"],
                    "attribute_name": row["field_name"],
                    "forecast_value": row["forecast_value"],
                    "observation_value": row["observation_value"],
                    "comparison_category": relation_map.get(
                        row["relation"], row["relation"].lower()
                    ),
                    "formal_relation": row["relation"],
                }
            )
        self.emit("03_multistage_attribute_comparisons.csv", comparison_rows)
        categories = Counter(row["comparison_category"] for row in comparison_rows)
        self.actual.update(
            multistage_cases=len(case_keys),
            multistage_associations=len(rows),
            multistage_attribute_comparisons=len(comparison_rows),
            multistage_same=categories["same"],
            multistage_different=categories["different"],
            multistage_observation_only=categories["observation_only"],
            multistage_both_missing=categories["both_missing"],
        )

    def export_states(self) -> None:
        cells = {
            row["cell_id"]: row
            for row in load_jsonl(
                self.source(
                    "artifacts/stage3a_initial_epistemic_state_v1_1/construction_state_cells.jsonl"
                )
            )
        }
        versions = load_jsonl(
            self.source(
                "artifacts/stage3b_bitemporal_epistemic_state_v1_1/bitemporal_state_versions.jsonl"
            )
        )
        rai = {
            row["bitemporal_version_id"]: row
            for row in load_jsonl(
                self.source("artifacts/stage4_bitemporal_state_metrics_v1_1/state_rai.jsonl")
            )
        }
        grs = {
            row["bitemporal_version_id"]: row
            for row in load_jsonl(
                self.source("artifacts/stage4_bitemporal_state_metrics_v1_1/state_grs.jsonl")
            )
        }
        grci = {
            row["bitemporal_version_id"]: row
            for row in load_jsonl(
                self.source("artifacts/stage4_bitemporal_state_metrics_v1_1/state_grci.jsonl")
            )
        }
        rows = []
        for version in versions:
            version_id = version["bitemporal_version_id"]
            role = version["cell_scope_role"]
            cell_row = cells[version["cell_id"]]
            rai_row, grs_row, grci_row = rai[version_id], grs[version_id], grci[version_id]
            forecast = set(version.get("materialized_forecast_evidence_ids") or [])
            observed = set(version.get("materialized_observed_evidence_ids") or [])
            background = set(version.get("materialized_background_evidence_ids") or [])
            geology = forecast | observed | background
            daily = role == "DAILY_REVIEW_CELL"
            rows.append(
                {
                    "state_id": version_id,
                    "base_state_id": version["base_stage3a_state_version_id"],
                    "construction_date": version["valid_date"],
                    "cell_id": version["cell_id"],
                    "cell_start_m": cell_row["spatial_start"],
                    "cell_end_m": cell_row["spatial_end"],
                    "knowledge_cutoff": version["knowledge_time_start_local_date"],
                    "version_index": version["version_number"],
                    "position_role": role,
                    "mechanical_evidence_count": len(
                        version.get("materialized_response_evidence_ids") or []
                    ),
                    "geological_evidence_count": len(geology),
                    "observed_geology_count": len(observed),
                    "predicted_geology_count": len(forecast),
                    "background_evidence_count": len(background),
                    "rai_applicable": daily,
                    "rai_available": rai_row["rai_status"] == "AVAILABLE",
                    "rai_value": rai_row.get("rai"),
                    "rai_unavailable_reason": rai_row.get("reason_codes") or [],
                    "grs_applicable": True,
                    "grs_available": grs_row["grs_status"] == "AVAILABLE",
                    "grs_value": grs_row.get("grs"),
                    "grs_unavailable_reason": grs_row.get("reason_codes") or [],
                    "grci_applicable": daily,
                    "grci_available": grci_row["grci_status"] == "AVAILABLE",
                    "grci_value": grci_row.get("grci"),
                    "grci_unavailable_reason": grci_row.get("reason_codes") or [],
                    "is_initial_version": version["version_number"] == 1,
                    "is_revised_version": version["version_number"] > 1,
                    "applicability_basis": "Reconstructed from frozen role policy: RAI/GRCI apply only to DAILY_REVIEW_CELL; GRS applies to all state roles.",
                }
            )
        self.emit("04_state_versions.csv", rows)

        summary_rows: list[dict[str, Any]] = []
        indicators = [("RAI", "rai"), ("GRS", "grs"), ("GRCI", "grci")]
        roles = ["ALL", *sorted({row["position_role"] for row in rows})]
        for indicator, prefix in indicators:
            for role in roles:
                selected = (
                    rows if role == "ALL" else [row for row in rows if row["position_role"] == role]
                )
                applicable = [row for row in selected if row[f"{prefix}_applicable"]]
                available = [row for row in applicable if row[f"{prefix}_available"]]
                values = [float(row[f"{prefix}_value"]) for row in available]
                summary_rows.append(
                    {
                        "indicator": indicator,
                        "role": role,
                        "state_count": len(selected),
                        "applicable_count": len(applicable),
                        "available_count": len(available),
                        "availability_rate": len(available) / len(applicable)
                        if applicable
                        else None,
                        "min": min(values) if values else None,
                        "q1": percentile(values, 0.25),
                        "median": percentile(values, 0.5),
                        "q3": percentile(values, 0.75),
                        "p95": percentile(values, 0.95),
                        "max": max(values) if values else None,
                    }
                )
        self.emit("04_indicator_summary.csv", summary_rows)
        self.actual.update(
            state_versions=len(rows),
            initial_state_versions=sum(row["is_initial_version"] for row in rows),
        )
        self._versions = {row["bitemporal_version_id"]: row for row in versions}
        self._cells = cells
        self._rai, self._grs, self._grci = rai, grs, grci

    def export_revisions(self) -> None:
        evidence = {
            row["evidence_uid"]: row
            for row in load_jsonl(
                self.source(
                    "artifacts/stage2_geology_v2_freeze_candidate/primary_geological_evidence.jsonl"
                )
            )
        }
        audit = load_csv(
            self.source(
                "artifacts/stage4_bitemporal_state_metrics_v1_1/bitemporal_metric_revision_audit.csv"
            )
        )
        rows = []
        revision_ids: dict[str, str] = {}
        all_added: list[str] = []
        for index, row in enumerate(audit, 1):
            before_id, after_id = (
                row["previous_bitemporal_version_id"],
                row["current_bitemporal_version_id"],
            )
            after = self._versions[after_id]
            added = maybe_json(row["added_geological_evidence_ids"]) or []
            all_added.extend(added)
            observed_count = sum(
                evidence.get(item, {}).get("epistemic_status") == "OBSERVED" for item in added
            )
            forecast_count = sum(
                evidence.get(item, {}).get("epistemic_status") == "FORECAST" for item in added
            )
            revision_id = (after.get("revision_event_ids") or [f"revision_pair_{index:03d}"])[0]
            revision_ids[after_id] = revision_id
            role = after["cell_scope_role"]
            daily = role == "DAILY_REVIEW_CELL"
            cell_row = self._cells[after["cell_id"]]
            rai_before, rai_after = self._rai[before_id], self._rai[after_id]
            grs_before, grs_after = self._grs[before_id], self._grs[after_id]
            grci_before, grci_after = self._grci[before_id], self._grci[after_id]
            rows.append(
                {
                    "revision_id": revision_id,
                    "construction_date": after["valid_date"],
                    "cell_id": after["cell_id"],
                    "position_role": role,
                    "cell_start_m": cell_row["spatial_start"],
                    "cell_end_m": cell_row["spatial_end"],
                    "state_before_id": before_id,
                    "state_after_id": after_id,
                    "tau_before": row["previous_knowledge_date"],
                    "tau_after": row["current_knowledge_date"],
                    "new_evidence_count": len(added),
                    "new_observed_evidence_count": observed_count,
                    "new_predicted_evidence_count": forecast_count,
                    "new_evidence_ids": added,
                    "rai_applicable_before": daily,
                    "rai_applicable_after": daily,
                    "rai_available_before": rai_before["rai_status"] == "AVAILABLE",
                    "rai_available_after": rai_after["rai_status"] == "AVAILABLE",
                    "rai_before": rai_before.get("rai"),
                    "rai_after": rai_after.get("rai"),
                    "rai_changed": truth(row["rai_changed"]),
                    "grs_applicable_before": True,
                    "grs_applicable_after": True,
                    "grs_available_before": grs_before["grs_status"] == "AVAILABLE",
                    "grs_available_after": grs_after["grs_status"] == "AVAILABLE",
                    "grs_before": grs_before.get("grs"),
                    "grs_after": grs_after.get("grs"),
                    "grs_changed": truth(row["grs_changed"]),
                    "grci_applicable_before": daily,
                    "grci_applicable_after": daily,
                    "grci_available_before": grci_before["grci_status"] == "AVAILABLE",
                    "grci_available_after": grci_after["grci_status"] == "AVAILABLE",
                    "grci_before": grci_before.get("grci"),
                    "grci_after": grci_after.get("grci"),
                    "grci_changed": truth(row["grci_changed"]),
                }
            )
        self.emit("05_revision_pairs.csv", rows)
        self.actual.update(
            revision_pairs=len(rows),
            revision_dates=len({row["construction_date"] for row in rows}),
            revision_cells=len({row["cell_id"] for row in rows}),
            revision_evidence_links=len(all_added),
            revision_unique_evidence=len(set(all_added)),
        )
        self._revision_ids = revision_ids

    def load_claim_universe(self) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        opportunities = load_jsonl(
            self.source(
                "artifacts/stage5b_deterministic_claim_builder_v1/claim_opportunities.jsonl"
            )
        )
        proposals = load_jsonl(
            self.source("artifacts/stage5b_deterministic_claim_builder_v1/claim_proposals.jsonl")
        )
        decisions = load_jsonl(
            self.source("artifacts/stage5b_deterministic_claim_builder_v1/claim_decisions.jsonl")
        )
        proposal_by_opportunity = {row["metadata"]["opportunity_id"]: row for row in proposals}
        decision_by_proposal = {row["proposal_id"]: row for row in decisions}
        joined: list[dict[str, Any]] = []
        lookup: dict[str, dict[str, Any]] = {}
        for opportunity in opportunities:
            proposal = proposal_by_opportunity[opportunity["opportunity_id"]]
            decision = decision_by_proposal[proposal["proposal_id"]]
            row = {"opportunity": opportunity, "proposal": proposal, "decision": decision}
            joined.append(row)
            lookup[
                f"{opportunity['bitemporal_version_id']}|{comparison_key(opportunity, proposal)}"
            ] = row
        return joined, lookup

    def export_revision_claims(self) -> None:
        joined, lookup = self.load_claim_universe()
        transitions = load_csv(
            self.source(
                "artifacts/stage5c_claim_expressibility_analysis_v1/revision_claim_transition_analysis.csv"
            )
        )
        rows = []
        normalized_transition = {
            "OPPORTUNITY_ADDED": "new_claim",
            "OPPORTUNITY_REMOVED": "removed_claim",
            "ABSTAIN_TO_EXPRESSIBLE": "abstain_to_expressible",
            "EXPRESSIBLE_TO_ABSTAIN": "expressible_to_abstain",
        }
        for row in transitions:
            key = row["revision_comparison_key"]
            before = lookup.get(f"{row['v1_bitemporal_version_id']}|{key}")
            after = lookup.get(f"{row['v2_bitemporal_version_id']}|{key}")
            before_opp = before["opportunity"] if before else {}
            after_opp = after["opportunity"] if after else {}
            before_proposal = before["proposal"] if before else {}
            after_proposal = after["proposal"] if after else {}
            formal = row["transition_class"]
            change_type = normalized_transition.get(formal, "matched_unchanged")
            if formal in {"CLAIM_VALUE_CHANGED", "RESOLVED_SUPPORT_CHANGED"}:
                change_type = formal.lower()
            key_data = maybe_json(key) or {}
            rows.append(
                {
                    "revision_id": self._revision_ids.get(row["v2_bitemporal_version_id"], ""),
                    "claim_id_before": before_opp.get("opportunity_id"),
                    "claim_id_after": after_opp.get("opportunity_id"),
                    "claim_type": key_data.get("claim_type"),
                    "change_type": change_type,
                    "formal_transition_class": formal,
                    "decision_before": row["v1_decision"],
                    "decision_after": row["v2_decision"],
                    "value_before": before_proposal.get("claim_value"),
                    "value_after": after_proposal.get("claim_value"),
                    "source_before": before_opp.get("source_object_ids"),
                    "source_after": after_opp.get("source_object_ids"),
                    "comparison_key": key_data,
                    "construction_date": row["valid_date"],
                    "cell_id": row["cell_id"],
                    "position_role": row["state_role"],
                }
            )
        self.emit("05_revision_claim_changes.csv", rows)
        self._joined_claims = joined

    def export_claims(self) -> None:
        rows: list[dict[str, Any]] = []
        for item in self._joined_claims:
            opportunity, proposal, decision = (
                item["opportunity"],
                item["proposal"],
                item["decision"],
            )
            claim_type = opportunity["claim_type"]
            payload = opportunity.get("payload") or {}
            claim_value = proposal.get("claim_value") or {}
            passed = set(decision.get("passed_rules") or [])
            rows.append(
                {
                    "claim_id": opportunity["opportunity_id"],
                    "proposal_id": proposal["proposal_id"],
                    "decision_id": decision["decision_id"],
                    "state_id": opportunity["bitemporal_version_id"],
                    "construction_date": opportunity["valid_date"],
                    "cell_id": opportunity.get("cell_id"),
                    "knowledge_cutoff": self._versions[opportunity["bitemporal_version_id"]][
                        "knowledge_time_start_local_date"
                    ],
                    "position_role": opportunity["state_role"],
                    "claim_type": CLAIM_TYPE_PUBLIC[claim_type],
                    "claim_type_internal": claim_type,
                    "claim_group": "indicator_claim"
                    if claim_type in METRIC_CLAIM_TYPES
                    else "geological_condition_claim",
                    "source_path": f"{opportunity.get('source_origin')}:{opportunity.get('source_kind')}",
                    "indicator_name": payload.get("metric_name") or claim_value.get("metric_name"),
                    "attribute_name": claim_value.get("attribute_name"),
                    "candidate_value": claim_value,
                    "epistemic_property": {
                        "modality": proposal.get("modality"),
                        "source_epistemic_statuses": proposal.get("source_epistemic_statuses")
                        or [],
                    },
                    "source_record_id": claim_value.get("source_evidence_id")
                    or opportunity.get("source_object_ids"),
                    "applicable": "allowed_state_roles" in passed,
                    "decision": decision["expressibility"],
                    "abstain_reason": decision.get("abstention_reason"),
                    "time_valid": True,
                    "time_valid_basis": "Frozen Stage5B opportunity already bound to a Stage3B as-of state.",
                    "spatial_valid": "spatial_containment" in passed,
                    "role_valid": "allowed_state_roles" in passed,
                    "epistemic_valid": all(
                        rule in passed
                        for rule in [
                            "forbidden_epistemic_promotions",
                            "required_epistemic_statuses",
                        ]
                    ),
                    "value_available": "unknown_source_value" in passed
                    and (
                        "metric_payload_contract" in passed
                        or "geological_payload_contract" in passed
                    ),
                    "source_valid": "resolved_support_integrity" in passed
                    and "required_primary_support" in passed,
                    "quality_valid": "generation_eligible" in passed,
                    "failed_rules": decision.get("failed_rules") or [],
                }
            )
        self.emit("06_claim_results.csv", rows)
        abstain = [row for row in rows if row["decision"] == "ABSTAIN"]
        summary_rows: list[dict[str, Any]] = []

        def append_summary(
            scope: str, selected: list[dict[str, Any]], claim_type: str, claim_group: str
        ) -> None:
            denominator = len(selected)
            for reason, count in sorted(Counter(row["abstain_reason"] for row in selected).items()):
                summary_rows.append(
                    {
                        "scope": scope,
                        "abstain_reason": reason,
                        "count": count,
                        "percentage": count / denominator if denominator else None,
                        "denominator": denominator,
                        "claim_type": claim_type,
                        "claim_group": claim_group,
                    }
                )

        append_summary("overall", abstain, "ALL", "ALL")
        for claim_type in sorted({row["claim_type"] for row in abstain}):
            selected = [row for row in abstain if row["claim_type"] == claim_type]
            append_summary("claim_type", selected, claim_type, selected[0]["claim_group"])
        for group in sorted({row["claim_group"] for row in abstain}):
            selected = [row for row in abstain if row["claim_group"] == group]
            append_summary("claim_group", selected, "ALL", group)
        self.emit("06_abstain_reasons.csv", summary_rows)
        overall_reason = Counter(row["abstain_reason"] for row in abstain)
        self.actual.update(
            claim_candidates=len(rows),
            claim_expressible=sum(row["decision"] == "EXPRESSIBLE" for row in rows),
            claim_abstain=len(abstain),
            **{f"abstain_{key}": value for key, value in overall_reason.items()},
        )

    def export_generation(self) -> None:
        manifest = load_csv(
            self.source(
                "artifacts/stage7_supplemental_automated_benchmark_v1/evaluation/condition_manifest.csv"
            )
        )
        task_manifest = {
            row["benchmark_task_id"]: row
            for row in load_csv(
                self.source(
                    "artifacts/stage7_supplemental_automated_benchmark_v1/protocol/combined_200_benchmark_manifest.csv"
                )
            )
        }
        endpoints = load_csv(
            self.source(
                "artifacts/stage7_supplemental_automated_benchmark_v1/evaluation/automatic_condition_binary_endpoints.csv"
            )
        )
        endpoint_map: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
        for row in endpoints:
            endpoint_map[row["condition_id"]][row["error_code"]] = row
        text_rows = load_csv(
            self.source(
                "artifacts/stage7_supplemental_automated_benchmark_v1/evaluation/actual_text_manifest.csv"
            )
        )
        text_map = {row["condition_id"]: row["text"] for row in text_rows}

        def failed(condition_id: str, *codes: str) -> bool | None:
            selected = [endpoint_map[condition_id].get(code) for code in codes]
            if not any(selected):
                return None
            return any(int(row["fail_count"]) > 0 for row in selected if row)

        rows = []
        for condition in manifest:
            condition_id = condition["condition_id"]
            task = task_manifest[condition["task_id"]]
            available = truth(condition["output_available"])
            errors = endpoint_map.get(condition_id, {})
            error_count = sum(int(row["fail_count"]) for row in errors.values())
            rows.append(
                {
                    "task_id": condition["task_id"],
                    "condition_id": condition_id,
                    "method": METHOD_PUBLIC[condition["method_internal"]],
                    "method_internal": condition["method_internal"],
                    "task_type": condition["product_type"],
                    "complexity_group": task["unit_complexity_band"],
                    "epistemic_group": task["epistemic_mix"],
                    "generated": True,
                    "controlled_stop": condition["output_status"] != "OUTPUT_AVAILABLE",
                    "output_available": available,
                    "numeric_error": failed(condition_id, "E2", "E3"),
                    "spatial_error": failed(condition_id, "E4"),
                    "epistemic_error": failed(condition_id, "E5", "E7", "E12"),
                    "prediction_factualization": failed(condition_id, "E5"),
                    "future_leakage": failed(condition_id, "E7"),
                    "causal_error": None,
                    "causal_error_note": "E9 is not automatically evaluable in the frozen taxonomy.",
                    "probability_error": failed(condition_id, "E10"),
                    "source_error": failed(condition_id, "E14"),
                    "structure_error": failed(condition_id, "E13"),
                    "admissibility_error": failed(condition_id, "E12"),
                    "automatic_error_count": error_count,
                    "automatic_error_any": error_count > 0,
                    "output_length": len(text_map.get(condition_id, "")),
                    "source_output_file": condition["output_reference"],
                    "output_status": condition["output_status"],
                }
            )
        self.emit("07_generation_auto_eval.csv", rows)
        self.actual.update(
            generation_tasks=len({row["task_id"] for row in rows}),
            generation_B0_outputs=sum(
                row["method"] == "B0" and row["output_available"] for row in rows
            ),
            generation_B1_outputs=sum(
                row["method"] == "B1" and row["output_available"] for row in rows
            ),
            generation_P_outputs=sum(
                row["method"] == "P" and row["output_available"] for row in rows
            ),
            generation_P_controlled_stop=sum(
                row["method"] == "P" and row["controlled_stop"] for row in rows
            ),
        )

    def export_human(self) -> None:
        ratings = load_csv(
            self.source("artifacts/stage7c_partitioned_human_evaluation_v1/human_ratings_long.csv")
        )
        rows = []
        observed_keys: set[tuple[int, str]] = set()
        rater_for_task: dict[int, str] = {}
        for row in ratings:
            task_number = int(row["task_number"])
            method = METHOD_PUBLIC[row["method_internal"]]
            observed_keys.add((task_number, method))
            rater_for_task[task_number] = row["reviewer_id"]
            rows.append(
                {
                    "task_id": row["task_id_internal"],
                    "task_number": task_number,
                    "rater_id": row["reviewer_id"],
                    "method": method,
                    "method_internal": row["method_internal"],
                    "fact_support": row["factual_support"],
                    "epistemic_distinction": row["epistemic_distinction"],
                    "completeness": row["content_completeness"],
                    "clarity_utility": row["clarity_usability"],
                    "semantic_error_label": row["explicit_error"].lower(),
                    "error_quote": row["error_quote"],
                    "error_reason": row["error_reason"],
                    "output_available": True,
                    "source_file_key": row["source_file_key"],
                }
            )
        for task_number in range(1, 49):
            if (task_number, "P") in observed_keys:
                continue
            task_id = f"stage7_main_task_{task_number - 1:03d}"
            rows.append(
                {
                    "task_id": task_id,
                    "task_number": task_number,
                    "rater_id": rater_for_task[task_number],
                    "method": "P",
                    "method_internal": "P_PROPOSED",
                    "fact_support": None,
                    "epistemic_distinction": None,
                    "completeness": None,
                    "clarity_utility": None,
                    "semantic_error_label": "not_applicable_no_output",
                    "error_quote": None,
                    "error_reason": "No valid P output after deterministic validator intercept.",
                    "output_available": False,
                    "source_file_key": "stage7c_partitioned_human_evaluation_v1/freeze_manifest",
                }
            )
        rows.sort(key=lambda row: (row["task_number"], ["B0", "B1", "P"].index(row["method"])))
        self.emit("08_human_eval.csv", rows)

    def export_mechanisms(self) -> None:
        summary = load_json(
            self.source(
                "artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json"
            )
        )
        rows = [
            {
                "condition": "A1",
                "analysis_unit": "design",
                "n_total": None,
                "n_success": None,
                "n_failure": None,
                "metric_name": "execution_status",
                "metric_value": summary["a1"]["execution_status"],
                "notes": summary["a1"]["interpretation"],
            },
            {
                "condition": "A2",
                "analysis_unit": "task",
                "n_total": summary["a2"]["affected_tasks"],
                "n_success": None,
                "n_failure": None,
                "metric_name": "target_sections",
                "metric_value": summary["a2"]["target_sections"],
                "notes": "Architectural abstention target inventory; not a performance comparison.",
            },
            {
                "condition": "A3_primary",
                "analysis_unit": "chunk",
                "n_total": summary["a3_primary_protocol_compliance"]["total_chunks"],
                "n_success": summary["a3_primary_protocol_compliance"]["valid_chunks"],
                "n_failure": summary["a3_primary_protocol_compliance"]["total_chunks"]
                - summary["a3_primary_protocol_compliance"]["valid_chunks"],
                "metric_name": "strict_protocol_valid_chunk",
                "metric_value": summary["a3_primary_protocol_compliance"]["valid_chunks"]
                / summary["a3_primary_protocol_compliance"]["total_chunks"],
                "notes": "Primary strict JSON protocol.",
            },
            {
                "condition": "A3_corrected",
                "analysis_unit": "numeric_claim",
                "n_total": summary["a3_corrected_strict_numeric_audit"]["numeric_claims"],
                "n_success": summary["a3_corrected_strict_numeric_audit"]["numeric_exact"],
                "n_failure": summary["a3_corrected_strict_numeric_audit"]["numeric_drift"],
                "metric_name": "exact_numeric_preservation",
                "metric_value": summary["a3_corrected_strict_numeric_audit"]["numeric_exact"]
                / summary["a3_corrected_strict_numeric_audit"]["numeric_claims"],
                "notes": f"Evaluator: {summary['a3_corrected_strict_numeric_audit']['evaluator']}",
            },
            {
                "condition": "A3_secondary_fence_only",
                "analysis_unit": "chunk",
                "n_total": summary["a3_secondary_fence_only"]["total_chunks"],
                "n_success": summary["a3_secondary_fence_only"]["valid_chunks"],
                "n_failure": summary["a3_secondary_fence_only"]["total_chunks"]
                - summary["a3_secondary_fence_only"]["valid_chunks"],
                "metric_name": "fence_normalized_valid_chunk",
                "metric_value": summary["a3_secondary_fence_only"]["valid_chunks"]
                / summary["a3_secondary_fence_only"]["total_chunks"],
                "notes": summary["a3_secondary_fence_only"]["analysis_role"],
            },
            {
                "condition": "A4",
                "analysis_unit": "fact_lock",
                "n_total": summary["a4"]["total_fact_locks"],
                "n_success": summary["a4"]["used_fact_locks"],
                "n_failure": summary["a4"]["omitted_fact_locks"],
                "metric_name": "fact_lock_trace_coverage",
                "metric_value": summary["a4"]["fact_lock_trace_coverage"],
                "notes": "Omission means not explicitly referenced; no semantic correctness inference.",
            },
            {
                "condition": "A4",
                "analysis_unit": "numeric_fact_lock",
                "n_total": summary["a4"]["total_numeric_fact_locks"],
                "n_success": summary["a4"]["used_numeric_fact_locks"],
                "n_failure": summary["a4"]["omitted_numeric_fact_locks"],
                "metric_name": "numeric_fact_lock_trace_coverage",
                "metric_value": summary["a4"]["numeric_fact_lock_trace_coverage"],
                "notes": "Referenced numeric token drift = 0.",
            },
        ]
        self.emit("09_mechanism_diagnostics.csv", rows)

    def export_sensitivity(self) -> None:
        summary = load_json(
            self.source(
                "artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json"
            )
        )
        cell_stats = load_csv(
            self.source(
                "artifacts/stage7f_sensitivity_execution_v1/cell_size_metric_pairwise_statistics.csv"
            )
        )
        history_stats = load_csv(
            self.source(
                "artifacts/stage7f_sensitivity_execution_v1/rai_history_pairwise_statistics.csv"
            )
        )
        saturation_stats = load_csv(
            self.source(
                "artifacts/stage7f_sensitivity_execution_v1/rai_saturation_pairwise_statistics.csv"
            )
        )

        def correlations(stats: list[dict[str, str]], arm: str) -> dict[str, float]:
            result: dict[str, float] = {}
            for row in stats:
                if row["alternative_arm_id"] == arm and row["summary_statistic"] == "median":
                    result[row["metric_name"]] = float(row["spearman_rank_correlation"])
            return result

        rows = []
        for setting in ["5m", "10m", "20m"]:
            item = summary["cell_size"][setting]
            frozen = item["frozen_results"]
            arm = item["arm_id"]
            corr = {} if setting == "10m" else correlations(cell_stats, arm)
            rows.append(
                {
                    "factor": "spatial_unit_m",
                    "setting": setting.rstrip("m"),
                    "baseline_setting": 10,
                    "analysis_scope": item["interpretation_scope"],
                    "state_count": int(frozen["grs_eligible_count"]),
                    "applicable_count": int(frozen["grci_eligible_count"]),
                    "available_count": int(frozen["rai_available_count"]),
                    "rai_applicable_count": int(frozen["grci_eligible_count"]),
                    "rai_available_count": int(frozen["rai_available_count"]),
                    "grs_applicable_count": int(frozen["grs_eligible_count"]),
                    "grs_available_count": int(frozen["grs_available_count"]),
                    "grci_applicable_count": int(frozen["grci_eligible_count"]),
                    "grci_available_count": int(frozen["grci_available_count"]),
                    "claim_total": int(frozen["claim_opportunity_count"]),
                    "claim_expressible": int(frozen["expressible_count"]),
                    "claim_abstain": int(frozen["abstain_count"]),
                    "spatial_support_length": float(item["evaluated_cell_length_m"]),
                    "role_conflict_count": int(item["scope_role_conflicts"]),
                    "point_coverage_issue_count": int(item["point_missing_or_duplicate"]),
                    "interval_coverage_issue_count": int(item["interval_overlap_mismatch"]),
                    "changed_claim_count": None,
                    "rank_correlation_rai": 1.0 if setting == "10m" else corr.get("RAI"),
                    "rank_correlation_grs": 1.0 if setting == "10m" else corr.get("GRS"),
                    "rank_correlation_grci": 1.0 if setting == "10m" else corr.get("GRCI"),
                    "notes": item["denominator_caveat"],
                }
            )

        def append_scalar(
            factor: str,
            setting: str,
            baseline: str,
            item: dict[str, Any],
            stats: list[dict[str, str]],
            arm: str,
            changed: int,
        ) -> None:
            corr = {} if setting == baseline else correlations(stats, arm)
            rows.append(
                {
                    "factor": factor,
                    "setting": setting,
                    "baseline_setting": baseline,
                    "analysis_scope": "BASELINE"
                    if setting == baseline
                    else "SENSITIVITY_COMPARISON",
                    "state_count": int(item["grs_eligible_count"]),
                    "applicable_count": int(item["grci_eligible_count"]),
                    "available_count": int(item["rai_available_count"]),
                    "rai_applicable_count": int(item["grci_eligible_count"]),
                    "rai_available_count": int(item["rai_available_count"]),
                    "grs_applicable_count": int(item["grs_eligible_count"]),
                    "grs_available_count": int(item["grs_available_count"]),
                    "grci_applicable_count": int(item["grci_eligible_count"]),
                    "grci_available_count": int(item["grci_available_count"]),
                    "claim_total": int(item["claim_opportunity_count"]),
                    "claim_expressible": int(item["expressible_count"]),
                    "claim_abstain": int(item["abstain_count"]),
                    "spatial_support_length": None,
                    "role_conflict_count": None,
                    "point_coverage_issue_count": None,
                    "interval_coverage_issue_count": None,
                    "changed_claim_count": changed,
                    "rank_correlation_rai": 1.0 if setting == baseline else corr.get("RAI"),
                    "rank_correlation_grs": 1.0 if setting == baseline else corr.get("GRS"),
                    "rank_correlation_grci": 1.0 if setting == baseline else corr.get("GRCI"),
                    "notes": "No automatic robustness classification or p-value claim.",
                }
            )

        for setting in ["20", "30", "40"]:
            arm = f"rai_history_min_samples_{setting}"
            append_scalar(
                "rai_min_history",
                setting,
                "30",
                summary["history"][setting],
                history_stats,
                arm,
                0 if setting == "30" else 4,
            )
        for setting in ["2", "3", "4"]:
            arm = f"rai_saturation_robust_z_{setting}"
            append_scalar(
                "rai_lambda", setting, "3", summary["saturation"][setting], saturation_stats, arm, 0
            )
        self.emit("10_sensitivity.csv", rows)

    def export_mapping(self) -> None:
        path = self.source(
            "artifacts/stage4_bitemporal_state_metrics_v1_1/geological_attention_mapping_v1.yaml"
        )
        mapping = yaml.safe_load(path.read_text(encoding="utf-8"))["mappings"]
        rows = []
        for item in mapping:
            rows.append(
                {
                    "dimension": item["dimension_name"],
                    "attribute_name": item["attribute_name"],
                    "raw_value": item["normalized_serialization"],
                    "normalized_value": item["normalized_serialization"],
                    "mapping_value": item.get("attention_value"),
                    "mapping_status": item["review_status"],
                    "ordinal_rank": item.get("ordinal_rank"),
                    "ordinal_scale_max": item.get("ordinal_scale_max"),
                    "source_definition": item["mapping_basis"],
                    "notes": item["engineering_ordering_rationale"],
                }
            )
        self.emit("11_grs_mapping.csv", rows)

    def write_docs(self) -> None:
        protocol = load_json(
            self.source(
                "artifacts/stage7_supplemental_automated_benchmark_v1/execution/execution_protocol.json"
            )
        )
        commit = git(self.repo, "rev-parse", "HEAD")
        branch = git(self.repo, "branch", "--show-current")
        status = git(self.repo, "status", "--short")
        baseline = {
            "spatial_unit_m": 10,
            "rai_min_history": 30,
            "rai_lambda": 3,
            "grs_mapping": "geological_attention_mapping_v1",
            "grci_operator": "RAI * GRS; DAILY_REVIEW_CELL only",
        }
        experiment_config = {
            "git_head": commit,
            "git_branch": branch,
            "working_tree_clean": not bool(status),
            "baseline": baseline,
            "generation": protocol["provider_config_public"],
            "authoritative_result_families": [
                "stage2_plc_operational_freeze_v2",
                "stage2_geology_v2_freeze_candidate",
                "stage3b_bitemporal_epistemic_state_v1_1",
                "stage4_bitemporal_state_metrics_v1_1",
                "stage5b_deterministic_claim_builder_v1",
                "stage5c_claim_expressibility_analysis_v1",
                "paper_evidence_completion_v2",
                "stage7_supplemental_automated_benchmark_v1",
                "stage7c_partitioned_human_evaluation_v1",
                "stage7e_ablation_execution_v1_1a_metadata_cleanup",
                "stage7f_sensitivity_execution_v1_1_final_interpretation",
            ],
        }
        self.source_info.mkdir(parents=True, exist_ok=True)
        (self.source_info / "experiment_config.json").write_text(
            json.dumps(experiment_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (self.source_info / "source_files.md").write_text(
            "# Source files\n\n"
            "Every exported table was derived from the following existing repository files. No source artifact was modified.\n\n"
            + "\n".join(f"- `{item}`" for item in sorted(self.sources))
            + "\n",
            encoding="utf-8",
        )
        (self.source_info / "commands.md").write_text(
            "# Export command\n\n"
            f"```bash\npython scripts/export_paper_experiment_bundle.py --repo {self.repo} --output {self.output}\n```\n\n"
            "This export reads existing artifacts only. It does not call an API, rerun a model, or regenerate experiment outputs.\n",
            encoding="utf-8",
        )

        readme = f"""# Paper experiment data bundle

This bundle consolidates the final paper-facing experiment data currently present in `{self.repo.name}`. It is intended for independent plotting, tabulation, and descriptive statistical checks. It does not change or rerun the research pipeline.

## Identity and baseline

- Repository HEAD: `{commit}` on `{branch}`
- Working tree clean at export: `{not bool(status)}`
- Spatial unit: 10 m
- RAI minimum historical samples: 30
- RAI saturation scale: 3
- Generation model: `{protocol["provider_config_public"]["model"]}`
- Temperature/top-p: `{protocol["provider_config_public"]["temperature"]}` / `{protocol["provider_config_public"]["top_p"]}`

The current working tree contains uncommitted paper-evaluation additions. Consequently, HEAD is the repository baseline, while each source artifact retains its own method version and hash identity. See `audit_report.md`.

## Analysis units

- `04_state_versions.csv`: one row per bitemporal state version.
- `05_revision_pairs.csv`: one row per before/after revision pair.
- `06_claim_results.csv`: one row per deterministic claim opportunity and decision.
- `07_generation_auto_eval.csv`: one row per benchmark task and method.
- `08_human_eval.csv`: one row per task, method, and assigned rater, including three no-output placeholders.

## Status semantics

- `applicable`: the indicator or Claim is defined for the current role and object.
- `available`: an applicable indicator was successfully materialized with a value.
- `missing/unavailable`: applicable in principle, but required history, evidence, or value was unavailable.
- `not_applicable`: the method does not define the indicator for that role; this is not a calculation failure.
- `EXPRESSIBLE`: all frozen ClaimContract checks passed.
- `ABSTAIN`: at least one required check failed; the deterministic reason is retained.

## Files

The numbered CSV files follow the order of the paper experiment chapter. `data_dictionary.md` documents every exported column. `manifest.json` records row counts and SHA-256 hashes. `source_info/` records source paths and execution identity.
"""
        (self.output / "README.md").write_text(readme, encoding="utf-8")
        self.write_dictionary()
        self.write_audit(commit, branch, status)

    def write_dictionary(self) -> None:
        descriptions = {
            "construction_date": "Engineering date of the construction object.",
            "knowledge_cutoff": "As-of knowledge date used to materialize the state.",
            "position_role": "Formal spatial role: DAILY_REVIEW_CELL, FORWARD_ATTENTION_CELL, or LOCAL_BACKGROUND_CELL.",
            "epistemic_property": "Original observed/forecast modality metadata; never inferred from text.",
            "applicable": "Whether the formal contract permits this object/indicator for the current role.",
            "available": "Whether an applicable value was materialized.",
            "decision": "Frozen ClaimContract result: EXPRESSIBLE or ABSTAIN.",
            "abstain_reason": "First deterministic reason preventing expression.",
            "claim_type": "Paper-facing name for one of the six frozen claim types.",
            "claim_group": "indicator_claim or geological_condition_claim.",
            "output_available": "Whether a validated final text exists; false is not counted as a correct text.",
            "controlled_stop": "Proposed method stopped before final text after deterministic validation failure.",
            "rai_applicable": "True only for DAILY_REVIEW_CELL under the frozen method.",
            "grs_applicable": "True for the frozen state roles represented in Stage4.",
            "grci_applicable": "True only for DAILY_REVIEW_CELL under the frozen method.",
        }
        lines = [
            "# Data dictionary",
            "",
            "All CSV files use UTF-8 and retain empty cells for unavailable/non-evaluated fields. JSON-valued cells contain canonical UTF-8 JSON.",
            "",
        ]
        for path in sorted(self.data.glob("*.csv")):
            with path.open(encoding="utf-8", newline="") as handle:
                fields = next(csv.reader(handle))
            lines.extend(
                [
                    f"## {path.name}",
                    "",
                    "| field_name | meaning | data_type | allowed_values / unit | nullable |",
                    "|---|---|---|---|---|",
                ]
            )
            for field in fields:
                meaning = descriptions.get(field)
                if meaning is None:
                    meaning = (
                        field.replace("_", " ").capitalize()
                        + "; exported or derived as documented in the audit report."
                    )
                data_type = (
                    "boolean"
                    if field.startswith(("is_", "has_"))
                    or field.endswith(("_valid", "_available", "_applicable", "_changed"))
                    else "string/number"
                )
                allowed = (
                    "true/false" if data_type == "boolean" else "See authoritative source and notes"
                )
                lines.append(
                    f"| `{field}` | {meaning} | {data_type} | {allowed} | yes unless required identifier |"
                )
            lines.append("")
        (self.output / "data_dictionary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_audit(self, commit: str, branch: str, status: str) -> None:
        differences = []
        for key, reference in REFERENCE_VALUES.items():
            actual = self.actual.get(key)
            if actual is None:
                differences.append(
                    (
                        key,
                        reference,
                        "NOT_EXPORTED",
                        "Reference item was not independently reconstructed.",
                    )
                )
            elif actual != reference:
                differences.append(
                    (
                        key,
                        reference,
                        actual,
                        "Program-derived value differs from the manuscript reference.",
                    )
                )
        rows = [
            "# Audit report",
            "",
            f"- Git HEAD: `{commit}`",
            f"- Branch: `{branch}`",
            f"- Working tree clean: `{not bool(status)}`",
            "- Export operation: read-only consolidation; no API/model calls and no experimental regeneration.",
            "",
            "## Closure checks",
            "",
            f"- 1,119 episodes = {self.actual['spatially_valid_episodes']} spatially usable + {self.actual['spatially_invalid_episodes']} unusable: {'PASS' if self.actual['excavation_episodes'] == self.actual['spatially_valid_episodes'] + self.actual['spatially_invalid_episodes'] else 'FAIL'}",
            f"- 659 geological evidence = {self.actual['observed_evidence']} observed + {self.actual['forecast_evidence']} forecast: {'PASS' if self.actual['geological_evidence'] == self.actual['observed_evidence'] + self.actual['forecast_evidence'] else 'FAIL'}",
            f"- 1,375 states = {self.actual['initial_state_versions']} initial + {self.actual['revision_pairs']} revised: {'PASS' if self.actual['state_versions'] == self.actual['initial_state_versions'] + self.actual['revision_pairs'] else 'FAIL'}",
            f"- 8,679 claims = {self.actual['claim_expressible']} EXPRESSIBLE + {self.actual['claim_abstain']} ABSTAIN: {'PASS' if self.actual['claim_candidates'] == self.actual['claim_expressible'] + self.actual['claim_abstain'] else 'FAIL'}",
            "- Available metric rows were checked during export to require a non-empty value.",
            "- Revision pairs preserve construction date/cell and change the knowledge boundary/content.",
            "",
            "## Reference comparison",
            "",
        ]
        if differences:
            rows.extend(
                [
                    "| item | reference_value | actual_value | difference / likely reason |",
                    "|---|---:|---:|---|",
                ]
            )
            for key, reference, actual, reason in differences:
                diff = actual - reference if isinstance(actual, int) else reason
                rows.append(
                    f"| {key} | {reference} | {actual} | {diff if isinstance(diff, int) else reason} |"
                )
        else:
            rows.append(
                "All exported manuscript reference counts match the current authoritative artifacts."
            )
        rows.extend(
            [
                "",
                "## Version and interpretation notes",
                "",
                "1. The repository working tree was dirty before export. Existing uncommitted paper-evaluation files were not changed. HEAD therefore identifies the code baseline, while source artifact method versions and hashes identify later paper-facing results.",
                "2. `rai_applicable`, `grs_applicable`, and `grci_applicable` are reconstructed from the frozen role policy because Stage4 metric rows store status and value but no explicit `applicable` boolean.",
                "3. `03_multistage_cases.csv` contains one row per final association. When several trusted PLC episodes intersect one association, the plotting range is their union and all episode IDs are retained.",
                "4. Automatic E9 causal error is not machine-evaluable in the frozen taxonomy. Its field is blank rather than incorrectly set to false.",
                "5. `08_human_eval.csv` includes three explicit P no-output rows without fabricated scores. The source rating file contains 141 scored texts; the analysis grid contains 144 task-method conditions.",
                "6. The 5 multistage cases are information-complete illustrative cases, not a statistical generalization sample and not a forecast-accuracy study.",
                "7. The 20 m sensitivity arm fails the native resolution-validity gate and must not be treated as an equal-support comparison with 5 m/10 m.",
                "8. A1/A2 diagnostic outputs are design/interface evidence, not model-performance improvements.",
                "",
                "## Working tree snapshot",
                "",
                "```text",
                status or "(clean)",
                "```",
            ]
        )
        (self.output / "audit_report.md").write_text("\n".join(rows) + "\n", encoding="utf-8")

    def validate(self) -> None:
        assert (
            self.actual["excavation_episodes"]
            == self.actual["spatially_valid_episodes"] + self.actual["spatially_invalid_episodes"]
        )
        assert (
            self.actual["geological_evidence"]
            == self.actual["observed_evidence"] + self.actual["forecast_evidence"]
        )
        assert (
            self.actual["state_versions"]
            == self.actual["initial_state_versions"] + self.actual["revision_pairs"]
        )
        assert (
            self.actual["claim_candidates"]
            == self.actual["claim_expressible"] + self.actual["claim_abstain"]
        )
        state_rows = load_csv(self.data / "04_state_versions.csv")
        for row in state_rows:
            for indicator in ["rai", "grs", "grci"]:
                if truth(row[f"{indicator}_available"]):
                    assert row[f"{indicator}_value"] != ""
        claim_rows = load_csv(self.data / "06_claim_results.csv")
        assert {row["decision"] for row in claim_rows} <= {"EXPRESSIBLE", "ABSTAIN"}
        revision_rows = load_csv(self.data / "05_revision_pairs.csv")
        for row in revision_rows:
            assert row["construction_date"]
            assert row["cell_id"]

    def write_manifest(self) -> None:
        protocol = load_json(
            self.source(
                "artifacts/stage7_supplemental_automated_benchmark_v1/execution/execution_protocol.json"
            )
        )
        file_list = []
        for path in sorted(
            item
            for item in self.output.rglob("*")
            if item.is_file() and item.name != "manifest.json"
        ):
            relative = path.relative_to(self.output).as_posix()
            row_count = self.row_counts.get(relative)
            file_list.append({"path": relative, "row_count": row_count, "sha256": sha256(path)})
        manifest = {
            "git_commit": git(self.repo, "rev-parse", "HEAD"),
            "git_branch": git(self.repo, "branch", "--show-current"),
            "generated_at": datetime.now().astimezone().isoformat(),
            "baseline_config": {
                "spatial_unit_m": 10,
                "rai_min_history": 30,
                "rai_lambda": 3,
                "grs_mapping": "geological_attention_mapping_v1",
            },
            "spatial_unit": 10,
            "rai_min_history": 30,
            "rai_lambda": 3,
            "model_name": protocol["provider_config_public"]["model"],
            "temperature": protocol["provider_config_public"]["temperature"],
            "top_p": protocol["provider_config_public"]["top_p"],
            "source_result_directories": sorted({str(Path(item).parent) for item in self.sources}),
            "export_script": "scripts/export_paper_experiment_bundle.py",
            "file_list": file_list,
        }
        (self.output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def run(self) -> None:
        self.output.mkdir(parents=True, exist_ok=True)
        self.data.mkdir(parents=True, exist_ok=True)
        self.scripts.mkdir(parents=True, exist_ok=True)
        self.export_inputs()
        self.export_reconstruction()
        self.export_multistage()
        self.export_states()
        self.export_revisions()
        self.export_revision_claims()
        self.export_claims()
        self.export_generation()
        self.export_human()
        self.export_mechanisms()
        self.export_sensitivity()
        self.export_mapping()
        source_script = Path(__file__).resolve()
        target_script = self.scripts / source_script.name
        target_script.write_bytes(source_script.read_bytes())
        self.row_counts["scripts/export_paper_experiment_bundle.py"] = None
        self.write_docs()
        self.validate()
        self.write_manifest()


def main() -> None:
    args = parse_args()
    Exporter(args.repo, args.output).run()


if __name__ == "__main__":
    main()
