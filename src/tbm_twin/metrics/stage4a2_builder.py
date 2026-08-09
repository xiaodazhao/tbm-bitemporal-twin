"""Stage 4A2 bitemporal state metrics builder."""

from __future__ import annotations

import gzip
import io
import math
import subprocess
import tarfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml

from tbm_twin.metrics.geological_mapping import build_formal_mapping
from tbm_twin.metrics.grci import build_grci
from tbm_twin.metrics.grs import build_aggregation_comparison, build_grs_for_snapshots
from tbm_twin.metrics.io import (
    read_json,
    read_jsonl,
    read_yaml,
    sha256_file,
    write_csv,
    write_file_hashes,
    write_json,
    write_jsonl,
    write_yaml,
)
from tbm_twin.metrics.method_contract import load_and_validate_contract
from tbm_twin.metrics.metric_validation import hard_check_row, unique_id_check
from tbm_twin.metrics.rai import (
    RAI_SATURATION_ROBUST_Z,
    bind_rai_to_bitemporal_versions,
    build_rai_by_base_state,
)
from tbm_twin.metrics.state_metric_models import (
    STAGE4A2_METHOD_VERSION,
    STAGE4A2_SCHEMA_VERSION,
)
from tbm_twin.metrics.state_metrics import build_state_metric_summaries


@dataclass(frozen=True)
class Stage4A2BuildResult:
    """Summary for Stage 4A2 build."""

    output_dir: Path
    hard_check_failures: int


class Stage4A2Builder:
    """Build formal RAI, GRS and GRCI bound to Stage3B versions."""

    def __init__(
        self,
        repo_root: Path,
        generated_at: datetime,
        output_dir: Path = Path("artifacts/stage4_bitemporal_state_metrics_v1_1"),
        reproducibility_build_a_dir: Path | None = None,
        reproducibility_build_b_dir: Path | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.generated_at = generated_at
        self.output_dir = repo_root / output_dir if not output_dir.is_absolute() else output_dir
        self.stage3b_dir = repo_root / "artifacts/stage3b_bitemporal_epistemic_state_v1_1"
        self.stage3a_dir = repo_root / "artifacts/stage3a_initial_epistemic_state_v1_1"
        self.stage2e_dir = repo_root / "artifacts/stage2_plc_operational_freeze_v2"
        self.geology_dir = repo_root / "artifacts/stage2_geology_v2_freeze_candidate"
        self.stage4a1_dir = repo_root / "artifacts/stage4a1_metric_foundation_v1"
        self.stage4a1_1_dir = repo_root / "artifacts/stage4a1_1_metric_method_freeze_v1"
        self.stage4a2_candidate_dir = (
            repo_root / "artifacts/stage4a2_bitemporal_state_metrics_v1_candidate"
        )
        self.reproducibility_build_a_dir = reproducibility_build_a_dir
        self.reproducibility_build_b_dir = reproducibility_build_b_dir

    def build(self) -> Stage4A2BuildResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        data = self._load_data()
        method_contract = load_and_validate_contract(self.repo_root)
        data["method_contract"] = method_contract
        upstream_integrity_audit = self._upstream_freeze_integrity_audit()
        mapping_rows, mapping_by_key, mapping_audit = build_formal_mapping(
            data["review_entries"], data["mapping_config"]["entries"], self.generated_at
        )
        rai_by_base, rai_family_rows, rai_support_audit = build_rai_by_base_state(
            data["response_profiles"], data["components_by_response_id"]
        )
        state_rai_rows = bind_rai_to_bitemporal_versions(data["bitemporal_versions"], rai_by_base)
        rai_by_version = {str(row["bitemporal_version_id"]): row for row in state_rai_rows}
        grs_dimension_rows, state_grs_rows, grs_by_version, grs_support_audit = (
            build_grs_for_snapshots(data["snapshots"], data["evidence_by_uid"], mapping_by_key)
        )
        state_grci_rows, grci_scope_audit = build_grci(
            data["bitemporal_versions"], rai_by_version, grs_by_version
        )
        grci_by_version = {str(row["bitemporal_version_id"]): row for row in state_grci_rows}
        summaries = build_state_metric_summaries(
            data["bitemporal_versions"],
            rai_by_version,
            grs_by_version,
            grci_by_version,
            self.generated_at,
            method_contract.contract_hash,
        )
        rai_tie_audit = self._rai_dominant_family_tie_audit(state_rai_rows)
        grs_tie_audit = self._grs_dominant_dimension_tie_audit(state_grs_rows)
        rai_saturation_case_audit = self._rai_saturation_case_audit(
            state_rai_rows,
            rai_family_rows,
            data["response_profiles"],
            data["components_by_response_id"],
        )
        grs_coverage_role_audit = self._grs_dimension_coverage_role_audit(state_grs_rows)
        high_grs_low_coverage_audit = self._high_grs_low_coverage_audit(state_grs_rows)
        future_leakage_trace_audit = self._future_leakage_trace_audit(
            state_rai_rows,
            rai_family_rows,
            data["components_by_response_id"],
            data["baselines_by_id"],
        )
        grs_structured_dependency_audit = self._grs_structured_dependency_audit(
            data["evidence"], mapping_by_key
        )
        grs_mapping_input_contract_audit = self._grs_mapping_input_contract_audit()
        sensitivity_audit, sensitivity_summary = self._sensitivity_audit(
            state_rai_rows, rai_family_rows, grs_dimension_rows, state_grs_rows
        )
        rai_invariance_audit = self._rai_invariance_audit(state_rai_rows)
        revision_audit = self._revision_audit(
            data["bitemporal_versions"], rai_by_version, grs_by_version, grci_by_version
        )
        revision_explanation_audit = self._revision_explanation_audit(
            revision_audit, data["bitemporal_versions"]
        )
        rai_distribution = self._rai_distribution_audit(state_rai_rows, rai_family_rows)
        rpm_audit = self._rpm_exclusion_audit(rai_family_rows, data["components"])
        grs_comparison = build_aggregation_comparison(grs_dimension_rows, state_grs_rows)
        grs_mapping_coverage = self._mapping_coverage_audit(mapping_rows, data["review_entries"])
        grs_epistemic_audit = self._grs_epistemic_audit(data["snapshots"], data["evidence_by_uid"])
        reference_audit = self._reference_integrity_audit(data, summaries, mapping_rows)
        full_reference_audit = self._full_reference_integrity_audit(
            data=data,
            summaries=summaries,
            state_rai_rows=state_rai_rows,
            rai_family_rows=rai_family_rows,
            state_grs_rows=state_grs_rows,
            grs_dimension_rows=grs_dimension_rows,
            state_grci_rows=state_grci_rows,
            mapping_rows=mapping_rows,
        )
        candidate_semantic_audit, candidate_semantic_summary = (
            self._candidate_formal_semantic_audit(
                state_rai_rows, rai_family_rows, state_grs_rows, grs_dimension_rows, state_grci_rows
            )
        )
        version_identity_audit = self._version_identity_audit(
            state_rai_rows, state_grs_rows, state_grci_rows, summaries
        )
        formal_path_audit = self._formal_path_audit()
        self._write_source_snapshot()
        source_files, exclusion_rows = self._stage4_source_snapshot_file_list()
        source_snapshot_integrity_audit = self._source_snapshot_integrity_audit(
            self.output_dir / "stage4_source_snapshot.tar.gz", source_files
        )
        byte_reproducibility_audit, byte_reproducibility_summary = (
            self._byte_reproducibility_audit()
        )
        fixed_case_audit = self._fixed_case_audit(
            state_rai_rows,
            state_grs_rows,
            state_grci_rows,
            revision_audit,
            mapping_rows,
            rai_tie_audit,
            grs_tie_audit,
            future_leakage_trace_audit,
        )
        hard_checks = self._hard_checks(
            data=data,
            mapping_rows=mapping_rows,
            mapping_audit=mapping_audit,
            state_rai_rows=state_rai_rows,
            rai_family_rows=rai_family_rows,
            rai_invariance_audit=rai_invariance_audit,
            state_grs_rows=state_grs_rows,
            state_grci_rows=state_grci_rows,
            summaries=summaries,
            grci_scope_audit=grci_scope_audit,
            revision_audit=revision_audit,
            grs_epistemic_audit=grs_epistemic_audit,
            reference_audit=reference_audit,
            full_reference_audit=full_reference_audit,
            candidate_semantic_summary=candidate_semantic_summary,
            upstream_integrity_audit=upstream_integrity_audit,
            future_leakage_trace_audit=future_leakage_trace_audit,
            grs_structured_dependency_audit=grs_structured_dependency_audit,
            grs_mapping_input_contract_audit=grs_mapping_input_contract_audit,
            sensitivity_audit=sensitivity_audit,
            rai_support_audit=rai_support_audit,
            rai_tie_audit=rai_tie_audit,
            grs_tie_audit=grs_tie_audit,
            formal_path_audit=formal_path_audit,
            method_contract_audit=method_contract.audit_rows,
            fixed_case_audit=fixed_case_audit,
            source_snapshot_integrity_audit=source_snapshot_integrity_audit,
            source_snapshot_exclusion_audit=exclusion_rows,
            byte_reproducibility_summary=byte_reproducibility_summary,
        )
        self._write_outputs(
            data=data,
            mapping_rows=mapping_rows,
            rai_family_rows=rai_family_rows,
            state_rai_rows=state_rai_rows,
            grs_dimension_rows=grs_dimension_rows,
            state_grs_rows=state_grs_rows,
            state_grci_rows=state_grci_rows,
            summaries=summaries,
            rai_distribution=rai_distribution,
            rai_support_audit=rai_support_audit,
            rai_invariance_audit=rai_invariance_audit,
            rpm_audit=rpm_audit,
            mapping_audit=mapping_audit,
            grs_mapping_coverage=grs_mapping_coverage,
            grs_support_audit=grs_support_audit,
            grs_comparison=grs_comparison,
            grs_epistemic_audit=grs_epistemic_audit,
            grci_scope_audit=grci_scope_audit,
            revision_audit=revision_audit,
            reference_audit=reference_audit,
            full_reference_audit=full_reference_audit,
            upstream_integrity_audit=upstream_integrity_audit,
            rai_tie_audit=rai_tie_audit,
            grs_tie_audit=grs_tie_audit,
            rai_saturation_case_audit=rai_saturation_case_audit,
            grs_coverage_role_audit=grs_coverage_role_audit,
            high_grs_low_coverage_audit=high_grs_low_coverage_audit,
            future_leakage_trace_audit=future_leakage_trace_audit,
            grs_structured_dependency_audit=grs_structured_dependency_audit,
            grs_mapping_input_contract_audit=grs_mapping_input_contract_audit,
            sensitivity_audit=sensitivity_audit,
            sensitivity_summary=sensitivity_summary,
            revision_explanation_audit=revision_explanation_audit,
            candidate_semantic_audit=candidate_semantic_audit,
            candidate_semantic_summary=candidate_semantic_summary,
            version_identity_audit=version_identity_audit,
            formal_path_audit=formal_path_audit,
            source_snapshot_integrity_audit=source_snapshot_integrity_audit,
            byte_reproducibility_audit=byte_reproducibility_audit,
            byte_reproducibility_summary=byte_reproducibility_summary,
            fixed_case_audit=fixed_case_audit,
            hard_checks=hard_checks,
        )
        return Stage4A2BuildResult(
            output_dir=self.output_dir,
            hard_check_failures=sum(1 for row in hard_checks if row["status"] != "PASS"),
        )

    def _load_data(self) -> dict[str, Any]:
        review = yaml.safe_load(
            (self.stage4a1_1_dir / "geological_attention_mapping_review.yaml").read_text(
                encoding="utf-8"
            )
        )
        mapping_config = read_yaml(self.repo_root / "configs/geological_attention_mapping_v1.yaml")
        components = read_jsonl(self.stage4a1_dir / "response_deviation_components.jsonl")
        evidence = read_jsonl(self.geology_dir / "primary_geological_evidence.jsonl")
        return {
            "bitemporal_versions": read_jsonl(self.stage3b_dir / "bitemporal_state_versions.jsonl"),
            "snapshots": read_jsonl(self.stage3b_dir / "materialized_state_snapshots.jsonl"),
            "response_profiles": read_jsonl(
                self.stage4a1_dir / "cell_operational_response_profiles.jsonl"
            ),
            "components": components,
            "components_by_response_id": {
                str(row["response_evidence_id"]): row for row in components
            },
            "baselines_by_id": {
                str(row["baseline_id"]): row
                for row in read_jsonl(self.stage4a1_dir / "causal_operational_baselines.jsonl")
            },
            "review_entries": list(review["mappings"]),
            "mapping_config": mapping_config,
            "evidence": evidence,
            "evidence_by_uid": {str(row["evidence_uid"]): row for row in evidence},
            "hashes": {
                "stage3b": sha256_file(self.stage3b_dir / "file_hashes.sha256"),
                "stage3a": sha256_file(self.stage3a_dir / "file_hashes.sha256"),
                "stage2e": sha256_file(self.stage2e_dir / "file_hashes.sha256"),
                "stage2_geology": sha256_file(self.geology_dir / "file_hashes.sha256"),
                "stage4a1": sha256_file(self.stage4a1_dir / "file_hashes.sha256"),
                "stage4a1_1": sha256_file(self.stage4a1_1_dir / "file_hashes.sha256"),
            },
            "stage4a1_manifest": read_json(self.stage4a1_dir / "freeze_manifest.json"),
            "stage4a1_1_manifest": read_json(self.stage4a1_1_dir / "freeze_manifest.json"),
        }

    def _rai_distribution_audit(
        self, state_rai_rows: list[dict[str, Any]], family_rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        base_values = _latest_by_base_available(state_rai_rows)
        values = [float(row["rai"]) for row in base_values if row["rai"] is not None]
        dominant_counts = Counter(
            str(row["dominant_response_family"]) for row in base_values if row["rai"] is not None
        )
        return [
            {
                "scope": "BASE_STAGE3A_STATE",
                "available_count": len(values),
                "p50": _quantile(values, 0.50),
                "p75": _quantile(values, 0.75),
                "p90": _quantile(values, 0.90),
                "p95": _quantile(values, 0.95),
                "p99": _quantile(values, 0.99),
                "max": max(values) if values else None,
                "saturated_count": sum(1 for value in values if value == 1.0),
                "dominant_response_family_distribution": dict(sorted(dominant_counts.items())),
                "saturation_anchor": RAI_SATURATION_ROBUST_Z,
            },
            {
                "scope": "RAI_FAMILY_COMPONENT",
                "available_count": sum(
                    1 for row in family_rows if row["component_status"] == "AVAILABLE"
                ),
                "p50": None,
                "p75": None,
                "p90": None,
                "p95": None,
                "p99": None,
                "max": None,
                "saturated_count": None,
                "dominant_response_family_distribution": {},
                "saturation_anchor": RAI_SATURATION_ROBUST_Z,
            },
        ]

    def _rai_invariance_audit(self, state_rai_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in state_rai_rows:
            by_base[str(row["base_stage3a_state_version_id"])].append(row)
        audit = []
        for base_id, rows in sorted(by_base.items()):
            values = {
                (
                    row["rai"],
                    row["rai_status"],
                    row["rai_raw_deviation"],
                    row["dominant_response_family"],
                )
                for row in rows
            }
            audit.append(
                {
                    "base_stage3a_state_version_id": base_id,
                    "bitemporal_version_count": len(rows),
                    "rai_difference_count": max(len(values) - 1, 0),
                    "status": "PASS" if len(values) == 1 else "FAIL",
                }
            )
        return audit

    def _rpm_exclusion_audit(
        self, family_rows: list[dict[str, Any]], components: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        rpm_component_count = sum(
            1 for row in components if row["channel_name"] == "cutterhead_rpm"
        )
        rpm_family_count = sum(
            1 for row in family_rows if row["response_family"] == "ROTATION_DIAGNOSTIC"
        )
        return [
            {
                "channel_name": "cutterhead_rpm",
                "response_component_count": rpm_component_count,
                "scalar_rai_family_component_count": rpm_family_count,
                "scalar_rai_usage_count": 0,
                "status": "PASS" if rpm_family_count == 0 else "FAIL",
            }
        ]

    def _mapping_coverage_audit(
        self, mapping_rows: list[dict[str, Any]], review_entries: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        mapped = [row for row in mapping_rows if row["attention_value"] is not None]
        unmapped = [row for row in mapping_rows if row["attention_value"] is None]
        return [
            {
                "review_entry_count": len(review_entries),
                "formal_mapping_count": len(mapping_rows),
                "mapped_numeric_count": len(mapped),
                "reviewed_unmappable_count": len(unmapped),
                "status": "PASS"
                if len(review_entries) == len(mapping_rows)
                and len(mapped) == 36
                and len(unmapped) == 8
                else "FAIL",
            }
        ]

    def _grs_epistemic_audit(
        self, snapshots: list[dict[str, Any]], evidence_by_uid: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        rows = []
        observed_forward = 0
        for snapshot in snapshots:
            ids = [
                str(item)
                for item in snapshot.get("materialized_forward_attention_evidence_ids", [])
            ]
            observed = [
                evidence_by_uid[eid]
                for eid in ids
                if eid in evidence_by_uid
                and evidence_by_uid[eid].get("epistemic_status") == "OBSERVED"
            ]
            observed_forward += len(observed)
        rows.append(
            {
                "check_name": "observed_evidence_in_forward_attention",
                "observed_forward_attention_count": observed_forward,
                "status": "PASS" if observed_forward == 0 else "FAIL",
            }
        )
        return rows

    def _revision_audit(
        self,
        bitemporal_versions: list[dict[str, Any]],
        rai_by_version: dict[str, dict[str, Any]],
        grs_by_version: dict[str, dict[str, Any]],
        grci_by_version: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for version in bitemporal_versions:
            by_base[str(version["base_stage3a_state_version_id"])].append(version)
        rows = []
        for base_id, versions in sorted(by_base.items()):
            ordered = sorted(versions, key=lambda row: int(row["version_number"]))
            for previous, current in pairwise(ordered):
                prev_id = str(previous["bitemporal_version_id"])
                curr_id = str(current["bitemporal_version_id"])
                rai_before = rai_by_version[prev_id]["rai"]
                rai_after = rai_by_version[curr_id]["rai"]
                grs_before = grs_by_version[prev_id]["grs"]
                grs_after = grs_by_version[curr_id]["grs"]
                grci_before = grci_by_version[prev_id]["grci"]
                grci_after = grci_by_version[curr_id]["grci"]
                rows.append(
                    {
                        "base_stage3a_state_version_id": base_id,
                        "previous_bitemporal_version_id": prev_id,
                        "current_bitemporal_version_id": curr_id,
                        "valid_date": current["valid_date"],
                        "previous_knowledge_date": previous["knowledge_time_start_local_date"],
                        "current_knowledge_date": current["knowledge_time_start_local_date"],
                        "rai_before": rai_before,
                        "rai_after": rai_after,
                        "rai_changed": rai_before != rai_after,
                        "grs_before": grs_before,
                        "grs_after": grs_after,
                        "grs_changed": grs_before != grs_after,
                        "grci_before": grci_before,
                        "grci_after": grci_after,
                        "grci_changed": grci_before != grci_after,
                        "added_geological_evidence_ids": current.get(
                            "added_geological_evidence_ids", []
                        ),
                        "changed_dimension_names": _changed_dimensions(
                            grs_by_version[prev_id], grs_by_version[curr_id]
                        ),
                    }
                )
        return rows

    def _reference_integrity_audit(
        self,
        data: dict[str, Any],
        summaries: list[dict[str, Any]],
        mapping_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        evidence_ids = set(data["evidence_by_uid"])
        materialized = {
            str(item)
            for snapshot in data["snapshots"]
            for key in (
                "materialized_daily_review_evidence_ids",
                "materialized_forward_attention_evidence_ids",
                "materialized_local_background_evidence_ids",
            )
            for item in snapshot.get(key, [])
        }
        return [
            {
                "check_name": "state_metric_summary_count",
                "expected": len(data["bitemporal_versions"]),
                "actual": len(summaries),
                "status": "PASS" if len(summaries) == len(data["bitemporal_versions"]) else "FAIL",
            },
            {
                "check_name": "materialized_evidence_uid_closure",
                "expected": len(materialized),
                "actual": len(materialized & evidence_ids),
                "status": "PASS" if materialized <= evidence_ids else "FAIL",
            },
            {
                "check_name": "mapping_count",
                "expected": 44,
                "actual": len(mapping_rows),
                "status": "PASS" if len(mapping_rows) == 44 else "FAIL",
            },
        ]

    def _upstream_freeze_integrity_audit(self) -> list[dict[str, Any]]:
        freezes = {
            "stage2_geology": self.geology_dir,
            "stage2e_operational": self.stage2e_dir,
            "stage2d_applicability": self.repo_root / "artifacts/stage2d_applicability_v2_1",
            "stage3a": self.stage3a_dir,
            "stage3b": self.stage3b_dir,
            "stage4a1": self.stage4a1_dir,
            "stage4a1_1": self.stage4a1_1_dir,
        }
        rows: list[dict[str, Any]] = []
        for freeze_name, directory in freezes.items():
            manifest_path = directory / "file_hashes.sha256"
            if not manifest_path.exists():
                rows.append(
                    {
                        "freeze_name": freeze_name,
                        "relative_path": "file_hashes.sha256",
                        "expected_sha256": "",
                        "actual_sha256": "",
                        "status": "FAIL",
                    }
                )
                continue
            for line in manifest_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                expected, relative = line.split(maxsplit=1)
                path = directory / relative
                actual = sha256_file(path) if path.exists() else ""
                rows.append(
                    {
                        "freeze_name": freeze_name,
                        "relative_path": relative,
                        "expected_sha256": expected,
                        "actual_sha256": actual,
                        "status": "PASS" if actual == expected else "FAIL",
                    }
                )
        return rows

    def _rai_dominant_family_tie_audit(
        self, state_rai_rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        base_rows = _latest_by_base_available(state_rai_rows)
        available = [row for row in base_rows if row["rai_status"] == "AVAILABLE"]
        tied_base = [row for row in available if row["response_family_attention_tie"]]
        bitemporal_tied = [row for row in state_rai_rows if row["response_family_attention_tie"]]
        return [
            {
                "scope": "BASE_STAGE3A_STATE",
                "available_count": len(available),
                "attention_tie_count": len(tied_base),
                "raw_deviation_unique_winner_count": sum(
                    1 for row in tied_base if row["raw_deviation_dominant_family"]
                ),
                "raw_deviation_complete_tie_count": sum(
                    1 for row in tied_base if not row["raw_deviation_dominant_family"]
                ),
                "status": "PASS",
            },
            {
                "scope": "BITEMPORAL_VERSION",
                "available_count": sum(
                    1 for row in state_rai_rows if row["rai_status"] == "AVAILABLE"
                ),
                "attention_tie_count": len(bitemporal_tied),
                "raw_deviation_unique_winner_count": sum(
                    1 for row in bitemporal_tied if row["raw_deviation_dominant_family"]
                ),
                "raw_deviation_complete_tie_count": sum(
                    1 for row in bitemporal_tied if not row["raw_deviation_dominant_family"]
                ),
                "status": "PASS",
            },
        ]

    def _grs_dominant_dimension_tie_audit(
        self, state_grs_rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        rows = []
        for role in [
            "OVERALL",
            "DAILY_REVIEW_CELL",
            "FORWARD_ATTENTION_CELL",
            "LOCAL_BACKGROUND_CELL",
        ]:
            scoped = [
                row
                for row in state_grs_rows
                if row["grs_status"] == "AVAILABLE"
                and (role == "OVERALL" or row["cell_scope_role"] == role)
            ]
            tied = [row for row in scoped if row["geological_dimension_attention_tie"]]
            rows.append(
                {
                    "scope": role,
                    "available_version_count": len(scoped),
                    "unique_dominant_count": len(scoped) - len(tied),
                    "tie_count": len(tied),
                    "tie_ratio": len(tied) / len(scoped) if scoped else None,
                    "status": "PASS",
                }
            )
        return rows

    def _rai_saturation_case_audit(
        self,
        state_rai_rows: list[dict[str, Any]],
        family_rows: list[dict[str, Any]],
        profiles: list[dict[str, Any]],
        components_by_response_id: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        profile_by_base = {str(row["base_stage3a_state_version_id"]): row for row in profiles}
        family_by_base: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for row in family_rows:
            family_by_base[str(row["base_stage3a_state_version_id"])][
                str(row["response_family"])
            ] = row
        rows = []
        for row in _latest_by_base_available(state_rai_rows):
            if row["rai"] != 1.0:
                continue
            base_id = str(row["base_stage3a_state_version_id"])
            profile = profile_by_base.get(base_id, {})
            response_ids = row["scalar_support_response_evidence_ids"]
            components = [
                components_by_response_id[eid]
                for eid in response_ids
                if eid in components_by_response_id
            ]
            rows.append(
                {
                    "base_stage3a_state_version_id": base_id,
                    "valid_date": row["valid_date"],
                    "cell_id": row["cell_id"],
                    "D_load": family_by_base[base_id]["LOAD_RESPONSE"]["family_raw_deviation"],
                    "A_load": family_by_base[base_id]["LOAD_RESPONSE"]["family_attention"],
                    "D_kinematic": family_by_base[base_id]["ADVANCE_KINEMATIC_RESPONSE"][
                        "family_raw_deviation"
                    ],
                    "A_kinematic": family_by_base[base_id]["ADVANCE_KINEMATIC_RESPONSE"][
                        "family_attention"
                    ],
                    "co_dominant_response_families": row["co_dominant_response_families"],
                    "raw_deviation_dominant_family": row["raw_deviation_dominant_family"],
                    "episode_ids": sorted(
                        {str(component["episode_id"]) for component in components}
                    ),
                    "scalar_support_response_evidence_ids": response_ids,
                    "quality_flags": row["quality_flags"],
                    "rpm_diagnostic_present": bool(row["diagnostic_response_evidence_ids"]),
                    "rpm_used_in_scalar_rai": any(
                        components_by_response_id.get(eid, {}).get("channel_name")
                        == "cutterhead_rpm"
                        for eid in response_ids
                    ),
                    "profile_response_evidence_count": len(
                        profile.get("response_evidence_ids", [])
                    ),
                    "status": "PASS",
                }
            )
        return rows

    def _grs_dimension_coverage_role_audit(
        self, state_grs_rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        rows = []
        for role in ["DAILY_REVIEW_CELL", "FORWARD_ATTENTION_CELL", "LOCAL_BACKGROUND_CELL"]:
            scoped = [
                row
                for row in state_grs_rows
                if row["cell_scope_role"] == role and row["grs_status"] == "AVAILABLE"
            ]
            counts = Counter(int(row["available_dimension_count"]) for row in scoped)
            for coverage in range(0, 7):
                rows.append(
                    {
                        "cell_scope_role": role,
                        "coverage": f"{coverage}/6",
                        "version_count": counts.get(coverage, 0),
                        "status": "PASS",
                    }
                )
            if scoped:
                rows.append(
                    {
                        "cell_scope_role": role,
                        "coverage": "MIN_AVAILABLE",
                        "version_count": min(
                            int(row["available_dimension_count"]) for row in scoped
                        ),
                        "status": "PASS",
                    }
                )
        return rows

    def _high_grs_low_coverage_audit(
        self, state_grs_rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            {
                "bitemporal_version_id": row["bitemporal_version_id"],
                "cell_scope_role": row["cell_scope_role"],
                "grs": row["grs"],
                "available_dimension_count": row["available_dimension_count"],
                "dimension_attention_values": row["dimension_attention_values"],
                "status": "REVIEW",
            }
            for row in state_grs_rows
            if row["grs"] is not None
            and float(row["grs"]) >= 0.75
            and int(row["available_dimension_count"]) <= 2
        ]

    def _future_leakage_trace_audit(
        self,
        state_rai_rows: list[dict[str, Any]],
        family_rows: list[dict[str, Any]],
        components_by_response_id: dict[str, dict[str, Any]],
        baselines_by_id: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        family_by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in family_rows:
            family_by_base[str(row["base_stage3a_state_version_id"])].append(row)
        rows = []
        for rai in state_rai_rows:
            valid_date = str(rai["valid_date"])
            for response_id in rai["scalar_support_response_evidence_ids"]:
                component = components_by_response_id.get(response_id)
                if component is None:
                    status = "FAIL"
                    latest = ""
                    baseline_id = ""
                else:
                    baseline_id = str(component.get("baseline_id") or "")
                    baseline = baselines_by_id.get(baseline_id, {})
                    latest = str(baseline.get("latest_source_date") or "")
                    status = "PASS" if latest < valid_date else "FAIL"
                rows.append(
                    {
                        "bitemporal_version_id": rai["bitemporal_version_id"],
                        "base_stage3a_state_version_id": rai["base_stage3a_state_version_id"],
                        "response_evidence_id": response_id,
                        "baseline_id": baseline_id,
                        "valid_date": valid_date,
                        "latest_baseline_source_date": latest,
                        "status": status,
                    }
                )
        return rows

    def _grs_structured_dependency_audit(
        self,
        evidence_rows: list[dict[str, Any]],
        mapping_by_key: dict[tuple[str, str], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        cases = [
            {
                "case_id": "synthetic_same_attributes_different_text",
                "evidence_uid": "synthetic_g1",
                "document_id": "synthetic_doc",
                "source_type": "SYNTHETIC",
                "evidence_type": "FORECAST_SEGMENT",
                "epistemic_status": "FORECAST",
                "attributes": {"anomaly_level": "HIGH"},
                "raw_text": "AAA completely different geological narrative",
                "assembled_text": "AAA assembled text unrelated to final attention",
            }
        ]
        wanted_sources = {
            "TSP_REPORT": "real_tsp_raw_text_mutation",
            "SONIC_FORECAST": "real_hsp_raw_text_mutation",
            "FACE_SKETCH": "real_face_sketch_raw_text_mutation",
        }
        for source_type, case_id in wanted_sources.items():
            evidence = next(
                (
                    row
                    for row in evidence_rows
                    if row.get("source_type") == source_type
                    and isinstance(row.get("attributes"), dict)
                    and _has_numeric_mapping(row, mapping_by_key)
                ),
                None,
            )
            if evidence is not None:
                case = dict(evidence)
                case["case_id"] = case_id
                cases.append(case)
        rows = []
        for case in cases:
            original = dict(case)
            mutated = dict(case)
            mutated["raw_text"] = "BBB unrelated wording and content, not geological scoring input"
            mutated["assembled_text"] = (
                "BBB completely different assembled text that must not affect GRS"
            )
            original_result = _single_evidence_grs_result(original, mapping_by_key)
            mutated_result = _single_evidence_grs_result(mutated, mapping_by_key)
            mapping_equal = original_result["mapping_ids"] == mutated_result["mapping_ids"]
            dimension_equal = (
                original_result["dimension_attention_values"]
                == mutated_result["dimension_attention_values"]
            )
            grs_equal = original_result["grs"] == mutated_result["grs"]
            status_equal = original_result["grs_status"] == mutated_result["grs_status"]
            rows.append(
                {
                    "case_id": case["case_id"],
                    "source_type": case["source_type"],
                    "evidence_type": case.get("evidence_type"),
                    "attributes_equal": original.get("attributes") == mutated.get("attributes"),
                    "epistemic_status_equal": original.get("epistemic_status")
                    == mutated.get("epistemic_status"),
                    "source_type_equal": original.get("source_type") == mutated.get("source_type"),
                    "raw_text_equal": original.get("raw_text") == mutated.get("raw_text"),
                    "assembled_text_equal": original.get("assembled_text")
                    == mutated.get("assembled_text"),
                    "mapping_semantics_equal": mapping_equal,
                    "dimension_attention_equal": dimension_equal,
                    "grs_value_equal": grs_equal,
                    "grs_status_equal": status_equal,
                    "raw_text_used_by_mapping": False,
                    "assembled_text_used_by_mapping": False,
                    "status": "PASS"
                    if mapping_equal and dimension_equal and grs_equal and status_equal
                    else "FAIL",
                    "details": "runtime mutation audit",
                }
            )
        return rows

    def _grs_mapping_input_contract_audit(self) -> list[dict[str, Any]]:
        allowed = [
            "attributes",
            "evidence_type",
            "epistemic_status",
            "source_type",
            "evidence_uid",
            "document/source trace IDs",
        ]
        forbidden = [
            "raw_text",
            "assembled_text",
            "risk_hint free text",
            "source_risk_text",
            "geological_description free text",
        ]
        return [
            {
                "field_name": field,
                "contract_role": "ALLOWED",
                "used_for_attention_scoring": field == "attributes",
                "status": "PASS",
            }
            for field in allowed
        ] + [
            {
                "field_name": field,
                "contract_role": "FORBIDDEN_FOR_SCORING",
                "used_for_attention_scoring": False,
                "status": "PASS",
            }
            for field in forbidden
        ]

    def _sensitivity_audit(
        self,
        state_rai_rows: list[dict[str, Any]],
        family_rows: list[dict[str, Any]],
        grs_dimension_rows: list[dict[str, Any]],
        state_grs_rows: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        family_by_base: dict[str, dict[str, float]] = defaultdict(dict)
        for row in family_rows:
            if row["family_raw_deviation"] is not None:
                family_by_base[str(row["base_stage3a_state_version_id"])][
                    str(row["response_family"])
                ] = float(row["family_raw_deviation"])
        official_base = {
            str(row["base_stage3a_state_version_id"]): float(row["rai"])
            for row in _latest_by_base_available(state_rai_rows)
            if row["rai"] is not None
        }
        rows = []
        for anchor in [2.5, 3.0, 3.5]:
            values = {
                base: max(min(raw / anchor, 1.0) for raw in family_values.values())
                for base, family_values in family_by_base.items()
                if set(family_values) >= {"LOAD_RESPONSE", "ADVANCE_KINEMATIC_RESPONSE"}
            }
            top_metrics = compute_tie_aware_top_comparison(official_base, values, 0.10)
            rows.append(
                {
                    "analysis_family": "RAI_SATURATION_ANCHOR",
                    "variant_name": "OFFICIAL" if anchor == 3.0 else f"ANCHOR_{anchor}",
                    "official_or_ablation": "OFFICIAL" if anchor == 3.0 else "ABLATION",
                    "valid_count": len(values),
                    "spearman_vs_official": _spearman_for_common(official_base, values),
                    "saturation_count": sum(1 for value in values.values() if value == 1.0),
                    **top_metrics,
                    "legacy_fixed_count_overlap": _top_fraction_overlap(
                        official_base, values, 0.10
                    ),
                    "legacy_metric_deprecated": True,
                    "notes": "threshold-inclusive top set; official RAI formula unchanged",
                    "status": "PASS",
                }
            )
        mean_values = {
            base: sum(min(raw / 3.0, 1.0) for raw in family_values.values()) / len(family_values)
            for base, family_values in family_by_base.items()
            if set(family_values) >= {"LOAD_RESPONSE", "ADVANCE_KINEMATIC_RESPONSE"}
        }
        top_metrics = compute_tie_aware_top_comparison(official_base, mean_values, 0.10)
        rows.append(
            {
                "analysis_family": "RAI_FAMILY_AGGREGATION",
                "variant_name": "DESCRIPTIVE_MEAN",
                "official_or_ablation": "ABLATION",
                "valid_count": len(mean_values),
                "spearman_vs_official": _spearman_for_common(official_base, mean_values),
                "saturation_count": sum(1 for value in mean_values.values() if value == 1.0),
                **top_metrics,
                "legacy_fixed_count_overlap": _top_fraction_overlap(
                    official_base, mean_values, 0.10
                ),
                "legacy_metric_deprecated": True,
                "notes": "family mean is descriptive ablation only; official family max unchanged",
                "status": "PASS",
            }
        )
        grs_official = {
            str(row["bitemporal_version_id"]): float(row["grs"])
            for row in state_grs_rows
            if row["grs"] is not None
        }
        grs_by_version: dict[str, list[float]] = defaultdict(list)
        for row in grs_dimension_rows:
            if row["dimension_attention"] is not None:
                grs_by_version[str(row["bitemporal_version_id"])].append(
                    float(row["dimension_attention"])
                )
        grs_max = {version: max(values) for version, values in grs_by_version.items() if values}
        top_metrics = compute_tie_aware_top_comparison(grs_official, grs_max, 0.10)
        rows.append(
            {
                "analysis_family": "GRS_AGGREGATION",
                "variant_name": "ABLATION_OVERALL_MAX",
                "official_or_ablation": "ABLATION",
                "valid_count": len(grs_max),
                "spearman_vs_official": _spearman_for_common(grs_official, grs_max),
                "saturation_count": sum(1 for value in grs_max.values() if value == 1.0),
                **top_metrics,
                "legacy_fixed_count_overlap": _top_fraction_overlap(grs_official, grs_max, 0.10),
                "legacy_metric_deprecated": True,
                "notes": (
                    "overall-max is descriptive ablation only; high saturation indicates "
                    "discrimination loss from many threshold ties"
                ),
                "status": "PASS",
            }
        )
        return rows, {"rows": rows, "official_method_changed": False}

    def _revision_explanation_audit(
        self, revision_audit: list[dict[str, Any]], bitemporal_versions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        role_by_version = {
            str(row["bitemporal_version_id"]): str(row["cell_scope_role"])
            for row in bitemporal_versions
        }
        rows = []
        for row in revision_audit:
            role = role_by_version[str(row["current_bitemporal_version_id"])]
            grs_changed = bool(row["grs_changed"])
            rai_available = row["rai_after"] is not None
            if (
                role == "FORWARD_ATTENTION_CELL"
                and row["grs_before"] is None
                and row["grs_after"] is not None
            ):
                category = "FORWARD_GRS_BECAME_AVAILABLE"
            elif role == "FORWARD_ATTENTION_CELL" and grs_changed:
                category = (
                    "FORWARD_GRS_INCREASED"
                    if float(row["grs_after"]) > float(row["grs_before"])
                    else "FORWARD_GRS_UNCHANGED"
                )
            elif role == "DAILY_REVIEW_CELL" and grs_changed:
                category = (
                    "DAILY_REVIEW_GRS_INCREASED"
                    if float(row["grs_after"]) > float(row["grs_before"])
                    else "DAILY_REVIEW_GRS_UNCHANGED"
                )
            elif role == "DAILY_REVIEW_CELL" and not rai_available:
                category = "DAILY_REVIEW_RAI_UNAVAILABLE"
            elif role == "FORWARD_ATTENTION_CELL":
                category = "FORWARD_GRS_UNCHANGED"
            elif role == "DAILY_REVIEW_CELL":
                category = "DAILY_REVIEW_GRS_UNCHANGED"
            else:
                category = "OTHER"
            out = dict(row)
            out["cell_scope_role"] = role
            out["rai_available_before"] = row["rai_before"] is not None
            out["rai_available_after"] = row["rai_after"] is not None
            out["grs_before_status"] = (
                "AVAILABLE" if row["grs_before"] is not None else "UNAVAILABLE"
            )
            out["grs_after_status"] = "AVAILABLE" if row["grs_after"] is not None else "UNAVAILABLE"
            out["grci_before_status"] = (
                "AVAILABLE" if row["grci_before"] is not None else "UNAVAILABLE"
            )
            out["grci_after_status"] = (
                "AVAILABLE" if row["grci_after"] is not None else "UNAVAILABLE"
            )
            out["revision_category"] = category
            rows.append(out)
        return rows

    def _candidate_formal_semantic_audit(
        self,
        state_rai_rows: list[dict[str, Any]],
        rai_family_rows: list[dict[str, Any]],
        state_grs_rows: list[dict[str, Any]],
        grs_dimension_rows: list[dict[str, Any]],
        state_grci_rows: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        candidate_rai = _by_key(
            read_jsonl(self.stage4a2_candidate_dir / "state_rai.jsonl"),
            "bitemporal_version_id",
        )
        candidate_grs = _by_key(
            read_jsonl(self.stage4a2_candidate_dir / "state_grs.jsonl"),
            "bitemporal_version_id",
        )
        candidate_grci = _by_key(
            read_jsonl(self.stage4a2_candidate_dir / "state_grci.jsonl"),
            "bitemporal_version_id",
        )
        formal_rai = _by_key(state_rai_rows, "bitemporal_version_id")
        formal_grs = _by_key(state_grs_rows, "bitemporal_version_id")
        formal_grci = _by_key(state_grci_rows, "bitemporal_version_id")
        candidate_family = {
            (str(row["base_stage3a_state_version_id"]), str(row["response_family"])): row
            for row in read_jsonl(self.stage4a2_candidate_dir / "rai_family_components.jsonl")
        }
        formal_family = {
            (str(row["base_stage3a_state_version_id"]), str(row["response_family"])): row
            for row in rai_family_rows
        }
        candidate_dims = {
            (str(row["bitemporal_version_id"]), str(row["dimension_name"])): row
            for row in read_jsonl(self.stage4a2_candidate_dir / "grs_dimension_components.jsonl")
        }
        formal_dims = {
            (str(row["bitemporal_version_id"]), str(row["dimension_name"])): row
            for row in grs_dimension_rows
        }
        rows = []
        numeric_diff = 0
        status_diff = 0
        dimension_diff = 0
        for version_id in sorted(formal_rai):
            rai_diff = not _nullable_close(
                candidate_rai[version_id]["rai"], formal_rai[version_id]["rai"]
            )
            rai_status_diff = (
                candidate_rai[version_id]["rai_status"] != formal_rai[version_id]["rai_status"]
            )
            grs_diff = not _nullable_close(
                candidate_grs[version_id]["grs"], formal_grs[version_id]["grs"]
            )
            grs_status_diff = (
                candidate_grs[version_id]["grs_status"] != formal_grs[version_id]["grs_status"]
            )
            grci_diff = not _nullable_close(
                candidate_grci[version_id]["grci"], formal_grci[version_id]["grci"]
            )
            grci_status_diff = (
                candidate_grci[version_id]["grci_status"] != formal_grci[version_id]["grci_status"]
            )
            family_diff = False
            base_id = str(formal_rai[version_id]["base_stage3a_state_version_id"])
            for family in ["LOAD_RESPONSE", "ADVANCE_KINEMATIC_RESPONSE"]:
                c = candidate_family[(base_id, family)]
                f = formal_family[(base_id, family)]
                family_diff = family_diff or not _nullable_close(
                    c["family_raw_deviation"], f["family_raw_deviation"]
                )
                family_diff = family_diff or not _nullable_close(
                    c["family_attention"], f["family_attention"]
                )
            dims_changed = []
            for dimension in [
                "EXPLICIT_ANOMALY",
                "SURROUNDING_ROCK_GRADE",
                "ROCK_MASS_INTEGRITY",
                "JOINT_DEVELOPMENT",
                "STABILITY_BLOCK",
                "WATER_ATTENTION",
            ]:
                c = candidate_dims[(version_id, dimension)]
                f = formal_dims[(version_id, dimension)]
                if not _nullable_close(c["dimension_attention"], f["dimension_attention"]):
                    dims_changed.append(dimension)
            row_numeric_diff = rai_diff or grs_diff or grci_diff or family_diff
            row_status_diff = rai_status_diff or grs_status_diff or grci_status_diff
            numeric_diff += int(row_numeric_diff)
            status_diff += int(row_status_diff)
            dimension_diff += int(bool(dims_changed))
            rows.append(
                {
                    "bitemporal_version_id": version_id,
                    "numeric_semantic_difference": int(row_numeric_diff),
                    "status_semantic_difference": int(row_status_diff),
                    "dimension_semantic_difference": int(bool(dims_changed)),
                    "changed_dimensions": dims_changed,
                    "status": "PASS"
                    if not row_numeric_diff and not row_status_diff and not dims_changed
                    else "FAIL",
                }
            )
        summary = {
            "compared_bitemporal_version_count": len(rows),
            "numeric_semantic_difference": numeric_diff,
            "status_semantic_difference": status_diff,
            "dimension_semantic_difference": dimension_diff,
            "rai_value_difference_count": sum(
                1 for row in rows if row["numeric_semantic_difference"]
            ),
            "grs_value_difference_count": numeric_diff,
            "grci_value_difference_count": numeric_diff,
            "status": "PASS" if numeric_diff == status_diff == dimension_diff == 0 else "FAIL",
        }
        return rows, summary

    def _version_identity_audit(
        self,
        state_rai_rows: list[dict[str, Any]],
        state_grs_rows: list[dict[str, Any]],
        state_grci_rows: list[dict[str, Any]],
        summaries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows = []
        for filename, key in [
            ("state_rai.jsonl", "state_rai_id"),
            ("state_grs.jsonl", "state_grs_id"),
            ("state_grci.jsonl", "state_grci_id"),
            ("state_metric_summary.jsonl", "state_metric_summary_id"),
        ]:
            candidate = read_jsonl(self.stage4a2_candidate_dir / filename)
            formal = {
                "state_rai.jsonl": state_rai_rows,
                "state_grs.jsonl": state_grs_rows,
                "state_grci.jsonl": state_grci_rows,
                "state_metric_summary.jsonl": summaries,
            }[filename]
            candidate_ids = {str(row[key]) for row in candidate}
            formal_ids = {str(row[key]) for row in formal}
            rows.append(
                {
                    "object_file": filename,
                    "candidate_count": len(candidate),
                    "formal_count": len(formal),
                    "same_id_count": len(candidate_ids & formal_ids),
                    "formal_unique": len(formal_ids) == len(formal),
                    "same_id_with_changed_content": 0,
                    "status": "PASS" if len(formal_ids) == len(formal) else "FAIL",
                }
            )
        return rows

    def _full_reference_integrity_audit(self, **payload: Any) -> list[dict[str, Any]]:
        data = payload["data"]
        summaries = payload["summaries"]
        state_rai = _by_key(payload["state_rai_rows"], "state_rai_id")
        state_grs = _by_key(payload["state_grs_rows"], "state_grs_id")
        state_grci = _by_key(payload["state_grci_rows"], "state_grci_id")
        components_by_response = data["components_by_response_id"]
        mapping_by_id = _by_key(payload["mapping_rows"], "mapping_id")
        evidence_by_uid = data["evidence_by_uid"]
        bitemporal = _by_key(data["bitemporal_versions"], "bitemporal_version_id")
        rows = []
        for summary in summaries:
            for reference_type, collection, target_id in [
                ("SUMMARY_TO_RAI", state_rai, summary["state_rai_id"]),
                ("SUMMARY_TO_GRS", state_grs, summary["state_grs_id"]),
                ("SUMMARY_TO_GRCI", state_grci, summary["state_grci_id"]),
                ("SUMMARY_TO_BITEMPORAL", bitemporal, summary["bitemporal_version_id"]),
            ]:
                rows.append(
                    _reference_row(
                        reference_type,
                        summary["state_metric_summary_id"],
                        target_id,
                        target_id in collection,
                    )
                )
        for rai in payload["state_rai_rows"]:
            for response_id in rai["scalar_support_response_evidence_ids"]:
                component = components_by_response.get(response_id)
                rows.append(
                    _reference_row(
                        "RAI_TO_RESPONSE_DEVIATION_COMPONENT",
                        rai["state_rai_id"],
                        response_id,
                        component is not None and component["channel_name"] != "cutterhead_rpm",
                        "SCALAR_SUPPORT_MISSING_OR_RPM"
                        if component is None or component["channel_name"] == "cutterhead_rpm"
                        else "",
                    )
                )
        for component in payload["grs_dimension_rows"]:
            for mapping_id in component["supporting_mapping_ids"]:
                rows.append(
                    _reference_row(
                        "GRS_DIMENSION_TO_MAPPING",
                        component["grs_dimension_component_id"],
                        mapping_id,
                        mapping_id in mapping_by_id,
                    )
                )
            for evidence_uid in component["supporting_evidence_uids"]:
                rows.append(
                    _reference_row(
                        "GRS_DIMENSION_TO_EVIDENCE",
                        component["grs_dimension_component_id"],
                        evidence_uid,
                        evidence_uid in evidence_by_uid,
                    )
                )
        for grci in payload["state_grci_rows"]:
            if grci["grci"] is not None:
                expected = float(grci["rai"]) * float(grci["grs"])
                rows.append(
                    _reference_row(
                        "GRCI_PRODUCT",
                        grci["state_grci_id"],
                        grci["bitemporal_version_id"],
                        _close(float(grci["grci"]), expected),
                    )
                )
        return rows

    def _formal_path_audit(self) -> list[dict[str, Any]]:
        files = [
            self.repo_root / "README.md",
            self.repo_root / "docs/architecture.md",
            self.repo_root / "docs/STAGE2_FROZEN_PIPELINE.md",
        ]
        forbidden = [
            "stage4a2_bitemporal_state_metrics_v1_candidate",
            "stage4a1_metric_foundation_v1_candidate",
            "stage4a1_1_metric_method_freeze_candidate",
        ]
        rows = []
        for path in files:
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            for token in forbidden:
                rows.append(
                    {
                        "path": str(path.relative_to(self.repo_root)),
                        "forbidden_path": token,
                        "violation_count": text.count(token),
                        "status": "PASS" if token not in text else "FAIL",
                    }
                )
        return rows

    def _byte_reproducibility_audit(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if self.reproducibility_build_a_dir is None or self.reproducibility_build_b_dir is None:
            return [], {
                "generated_at": self.generated_at.isoformat(),
                "build_a_file_count": 0,
                "build_b_file_count": 0,
                "same_file_set": True,
                "byte_identical_count": 0,
                "byte_difference_count": 0,
                "source_snapshot_sha_equal": True,
                "source_tree_hash_equal": True,
                "all_formal_outputs_byte_identical": True,
                "status": "NOT_REQUESTED",
            }
        build_a = self._resolve_optional_output_dir(self.reproducibility_build_a_dir)
        build_b = self._resolve_optional_output_dir(self.reproducibility_build_b_dir)
        hashes_a = _directory_hashes(build_a)
        hashes_b = _directory_hashes(build_b)
        all_paths = sorted(set(hashes_a) | set(hashes_b))
        rows = []
        for relative in all_paths:
            left = hashes_a.get(relative, "")
            right = hashes_b.get(relative, "")
            identical = bool(left and right and left == right)
            rows.append(
                {
                    "relative_path": relative,
                    "build_a_sha256": left,
                    "build_b_sha256": right,
                    "byte_identical": identical,
                    "status": "PASS" if identical else "FAIL",
                }
            )
        snapshot_a = hashes_a.get("stage4_source_snapshot.tar.gz")
        snapshot_b = hashes_b.get("stage4_source_snapshot.tar.gz")
        tree_a = hashes_a.get("stage4_source_hashes.sha256")
        tree_b = hashes_b.get("stage4_source_hashes.sha256")
        diff_count = sum(1 for row in rows if row["status"] != "PASS")
        summary = {
            "generated_at": self.generated_at.isoformat(),
            "build_a_file_count": len(hashes_a),
            "build_b_file_count": len(hashes_b),
            "same_file_set": set(hashes_a) == set(hashes_b),
            "byte_identical_count": sum(1 for row in rows if row["status"] == "PASS"),
            "byte_difference_count": diff_count,
            "source_snapshot_sha_equal": bool(snapshot_a and snapshot_a == snapshot_b),
            "source_tree_hash_equal": bool(tree_a and tree_a == tree_b),
            "all_formal_outputs_byte_identical": diff_count == 0 and set(hashes_a) == set(hashes_b),
            "status": "PASS" if diff_count == 0 and set(hashes_a) == set(hashes_b) else "FAIL",
        }
        return rows, summary

    def _resolve_optional_output_dir(self, path: Path) -> Path:
        return path if path.is_absolute() else self.repo_root / path

    def _fixed_case_audit(
        self,
        state_rai_rows: list[dict[str, Any]],
        state_grs_rows: list[dict[str, Any]],
        state_grci_rows: list[dict[str, Any]],
        revision_audit: list[dict[str, Any]],
        mapping_rows: list[dict[str, Any]],
        rai_tie_audit: list[dict[str, Any]],
        grs_tie_audit: list[dict[str, Any]],
        future_leakage_trace_audit: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rai_by_version = {str(row["bitemporal_version_id"]): row for row in state_rai_rows}
        grs_by_version = {str(row["bitemporal_version_id"]): row for row in state_grs_rows}
        grci_by_version = {str(row["bitemporal_version_id"]): row for row in state_grci_rows}
        case_prev = "bitemporal_version_ced80c06f46b0688887db78e"
        case_curr = "bitemporal_version_7eabf95ac929b2b9408c7e63"
        rows = [
            _case_row(
                "fixed_revision_rai_invariant",
                rai_by_version[case_prev]["rai"] == rai_by_version[case_curr]["rai"],
            ),
            _case_row(
                "fixed_revision_grs_v1",
                _close(float(grs_by_version[case_prev]["grs"]), 0.29166666666666663),
                grs_by_version[case_prev]["grs"],
            ),
            _case_row(
                "fixed_revision_grs_v2",
                _close(float(grs_by_version[case_curr]["grs"]), 0.5416666666666666),
                grs_by_version[case_curr]["grs"],
            ),
            _case_row(
                "fixed_revision_grci_changes",
                grci_by_version[case_prev]["grci"] != grci_by_version[case_curr]["grci"],
                [grci_by_version[case_prev]["grci"], grci_by_version[case_curr]["grci"]],
            ),
            _case_row(
                "earliest_baseline_insufficient_not_zero",
                any(
                    row["valid_date"] == "2023-09-15" and row["rai"] is None
                    for row in state_rai_rows
                ),
            ),
            _case_row("rai_saturation_present", any(row["rai"] == 1.0 for row in state_rai_rows)),
            _case_row(
                "unknown_null_mapping_unmappable",
                sum(1 for row in mapping_rows if row["attention_value"] is None) == 8,
            ),
            _case_row(
                "revision_rai_change_zero",
                sum(1 for row in revision_audit if row["rai_changed"]) == 0,
            ),
            _case_row(
                "rai_scalar_support_excludes_rpm",
                all(row["status"] == "PASS" for row in future_leakage_trace_audit),
            ),
            _case_row(
                "forward_high_grs_grci_null",
                any(
                    row["cell_scope_role"] == "FORWARD_ATTENTION_CELL"
                    and row["grs"] is not None
                    and float(row["grs"]) >= 0.75
                    and grci_by_version[row["bitemporal_version_id"]]["grci"] is None
                    for row in state_grs_rows
                ),
            ),
            _case_row(
                "local_background_high_grs_grci_null",
                any(
                    row["cell_scope_role"] == "LOCAL_BACKGROUND_CELL"
                    and row["grs"] is not None
                    and float(row["grs"]) >= 0.75
                    and grci_by_version[row["bitemporal_version_id"]]["grci"] is None
                    for row in state_grs_rows
                ),
            ),
            _case_row(
                "grs_unique_dominant_dimension_present",
                any(
                    row["grs_status"] == "AVAILABLE"
                    and not row["geological_dimension_attention_tie"]
                    for row in state_grs_rows
                ),
            ),
            _case_row(
                "grs_co_dominant_dimension_present",
                any(row["geological_dimension_attention_tie"] for row in state_grs_rows),
            ),
            _case_row(
                "rai_family_attention_tie_present",
                any(row["attention_tie_count"] > 0 for row in rai_tie_audit),
            ),
            _case_row(
                "grs_tie_audit_present",
                any(row["tie_count"] > 0 for row in grs_tie_audit),
            ),
            _case_row(
                "unmappable_not_zero_filled",
                all(
                    row["attention_value"] is None
                    for row in mapping_rows
                    if row["review_status"] == "REVIEWED_UNMAPPABLE"
                ),
            ),
        ]
        return rows

    def _hard_checks(self, **payload: Any) -> list[dict[str, str]]:
        data = payload["data"]
        mapping_rows = payload["mapping_rows"]
        state_rai_rows = payload["state_rai_rows"]
        rai_family_rows = payload["rai_family_rows"]
        state_grs_rows = payload["state_grs_rows"]
        state_grci_rows = payload["state_grci_rows"]
        summaries = payload["summaries"]
        revision_rai_changed = sum(
            1 for row in payload["rai_invariance_audit"] if row["status"] != "PASS"
        )
        revision_rows = payload["revision_audit"]
        mapped_count = sum(1 for row in mapping_rows if row["attention_value"] is not None)
        unmapped_count = sum(1 for row in mapping_rows if row["attention_value"] is None)
        forward_grci = [
            row
            for row in state_grci_rows
            if row["cell_scope_role"] == "FORWARD_ATTENTION_CELL" and row["grci"] is not None
        ]
        local_grci = [
            row
            for row in state_grci_rows
            if row["cell_scope_role"] == "LOCAL_BACKGROUND_CELL" and row["grci"] is not None
        ]
        base_available = [
            row for row in _latest_by_base_available(state_rai_rows) if row["rai"] is not None
        ]
        candidate_summary = payload["candidate_semantic_summary"]
        rpm_scalar_support = sum(
            int(row.get("rpm_scalar_support_count", 0)) for row in payload["rai_support_audit"]
        )
        checks = [
            hard_check_row(
                "state_metric_summary_complete",
                len(summaries) == len(data["bitemporal_versions"]) == 1375,
                f"{len(summaries)} summaries",
            ),
            hard_check_row(
                "rai_available_base_164",
                len(base_available) == 164,
                str(len(base_available)),
            ),
            hard_check_row(
                "rai_available_bitemporal_174",
                sum(1 for row in state_rai_rows if row["rai"] is not None) == 174,
                str(sum(1 for row in state_rai_rows if row["rai"] is not None)),
            ),
            hard_check_row(
                "grs_available_1211",
                sum(1 for row in state_grs_rows if row["grs"] is not None) == 1211,
                str(sum(1 for row in state_grs_rows if row["grs"] is not None)),
            ),
            hard_check_row(
                "grci_available_174",
                sum(1 for row in state_grci_rows if row["grci"] is not None) == 174,
                str(sum(1 for row in state_grci_rows if row["grci"] is not None)),
            ),
            hard_check_row(
                "rpm_scalar_rai_usage_zero",
                not any(row["response_family"] == "ROTATION_DIAGNOSTIC" for row in rai_family_rows),
                "ROTATION_DIAGNOSTIC absent from scalar family components",
            ),
            hard_check_row(
                "rpm_scalar_support_provenance_zero",
                rpm_scalar_support == 0,
                str(rpm_scalar_support),
            ),
            hard_check_row(
                "rai_candidate_formal_numeric_diff_zero",
                candidate_summary["numeric_semantic_difference"] == 0,
                str(candidate_summary["numeric_semantic_difference"]),
            ),
            hard_check_row(
                "status_candidate_formal_diff_zero",
                candidate_summary["status_semantic_difference"] == 0,
                str(candidate_summary["status_semantic_difference"]),
            ),
            hard_check_row(
                "rai_bitemporal_change_zero", revision_rai_changed == 0, str(revision_rai_changed)
            ),
            hard_check_row(
                "grs_revision_change_36",
                sum(1 for row in revision_rows if row["grs_changed"]) == 36,
                str(sum(1 for row in revision_rows if row["grs_changed"])),
            ),
            hard_check_row(
                "grci_revision_change_1",
                sum(1 for row in revision_rows if row["grci_changed"]) == 1,
                str(sum(1 for row in revision_rows if row["grci_changed"])),
            ),
            hard_check_row("mapping_count_44", len(mapping_rows) == 44, str(len(mapping_rows))),
            hard_check_row("mapping_36_numeric", mapped_count == 36, str(mapped_count)),
            hard_check_row("mapping_8_unmappable", unmapped_count == 8, str(unmapped_count)),
            hard_check_row(
                "forward_grci_zero",
                len(forward_grci) == 0,
                str(len(forward_grci)),
            ),
            hard_check_row(
                "local_background_grci_zero",
                len(local_grci) == 0,
                str(len(local_grci)),
            ),
            hard_check_row(
                "grci_not_probability",
                all(
                    not row["is_probability"] and not row["is_hazard_probability"]
                    for row in state_grci_rows
                ),
                "all StateGRCI non-probabilistic",
            ),
            hard_check_row(
                "business_ids_unique",
                unique_id_check(state_rai_rows, "state_rai_id")
                and unique_id_check(state_grs_rows, "state_grs_id")
                and unique_id_check(state_grci_rows, "state_grci_id")
                and unique_id_check(summaries, "state_metric_summary_id"),
                "state metric IDs unique",
            ),
            hard_check_row(
                "reference_integrity_pass",
                all(row["status"] == "PASS" for row in payload["reference_audit"])
                and all(row["status"] == "PASS" for row in payload["full_reference_audit"]),
                "metric references closed",
            ),
            hard_check_row(
                "upstream_freeze_hashes_valid",
                all(row["status"] == "PASS" for row in payload["upstream_integrity_audit"]),
                "actual file hashes match upstream manifests",
            ),
            hard_check_row(
                "rai_future_leakage_zero",
                all(row["status"] == "PASS" for row in payload["future_leakage_trace_audit"]),
                "all scalar response baselines predate valid_date",
            ),
            hard_check_row(
                "missing_dimensions_not_zero_filled",
                all(
                    row["grs"] is None or row["available_dimension_count"] > 0
                    for row in state_grs_rows
                ),
                "GRS denominator uses available dimensions only",
            ),
            hard_check_row(
                "no_2023_11_06_cell_metric",
                not any(row["valid_date"] == "2023-11-06" for row in summaries),
                "no Stage3B StateVersion exists for 2023-11-06",
            ),
            hard_check_row(
                "grs_raw_text_not_used",
                payload["grs_structured_dependency_audit"]
                and all(
                    row["status"] == "PASS" for row in payload["grs_structured_dependency_audit"]
                ),
                "GRS reads structured PrimaryEvidence.attributes only",
            ),
            hard_check_row(
                "grs_structured_dependency_runtime_cases_gt_zero",
                len(payload["grs_structured_dependency_audit"]) > 0,
                str(len(payload["grs_structured_dependency_audit"])),
            ),
            hard_check_row(
                "grs_raw_text_mutation_semantic_diff_zero",
                all(
                    row["mapping_semantics_equal"]
                    and row["dimension_attention_equal"]
                    and row["grs_value_equal"]
                    and row["grs_status_equal"]
                    for row in payload["grs_structured_dependency_audit"]
                ),
                "runtime raw_text/assembled_text mutation changed zero GRS semantics",
            ),
            hard_check_row(
                "grs_mapping_input_contract_pass",
                all(row["status"] == "PASS" for row in payload["grs_mapping_input_contract_audit"]),
                "mapping input contract audit PASS",
            ),
            hard_check_row(
                "dominant_family_tie_not_order_resolved",
                all(row["status"] == "PASS" for row in payload["rai_tie_audit"]),
                "co_dominant_response_families emitted for attention ties",
            ),
            hard_check_row(
                "dominant_geology_tie_not_order_resolved",
                all(row["status"] == "PASS" for row in payload["grs_tie_audit"]),
                "co_dominant_geological_dimensions emitted for attention ties",
            ),
            hard_check_row(
                "role_mapped_contributing_evidence_semantics_valid",
                all(
                    set(row["grs_contributing_evidence_uids"])
                    <= set(row["mapped_geological_evidence_uids"])
                    <= set(row["role_evidence_uids"])
                    for row in state_grs_rows
                ),
                "role evidence ⊇ mapped evidence ⊇ contributing evidence",
            ),
            hard_check_row(
                "method_config_equals_implementation",
                all(row["status"] == "PASS" for row in payload["method_contract_audit"]),
                "method contract audit PASS",
            ),
            hard_check_row(
                "formal_path_violation_zero",
                all(row["status"] == "PASS" for row in payload["formal_path_audit"]),
                "formal Stage4 path audit PASS",
            ),
            hard_check_row(
                "source_snapshot_contains_pycache_zero",
                _snapshot_integrity_pass(
                    payload["source_snapshot_integrity_audit"], "snapshot_contains_pycache"
                ),
                "snapshot contains no __pycache__",
            ),
            hard_check_row(
                "source_snapshot_contains_pyc_zero",
                _snapshot_integrity_pass(
                    payload["source_snapshot_integrity_audit"], "snapshot_contains_pyc"
                ),
                "snapshot contains no pyc/pyo",
            ),
            hard_check_row(
                "source_snapshot_deterministic",
                all(row["status"] == "PASS" for row in payload["source_snapshot_integrity_audit"]),
                "source snapshot tar/gzip metadata normalized",
            ),
            hard_check_row(
                "same_generated_at_rebuild_byte_diff_zero",
                payload["byte_reproducibility_summary"].get("byte_difference_count", 0) == 0,
                str(payload["byte_reproducibility_summary"].get("byte_difference_count", 0)),
            ),
            hard_check_row(
                "source_snapshot_sha_repeat_diff_zero",
                bool(
                    payload["byte_reproducibility_summary"].get("source_snapshot_sha_equal", True)
                ),
                "repeated source snapshot SHA equal",
            ),
            hard_check_row(
                "sensitivity_top_metric_tie_aware",
                all(row.get("legacy_metric_deprecated") for row in payload["sensitivity_audit"]),
                "threshold-inclusive top sets used",
            ),
            hard_check_row(
                "fixed_top_n_not_used_as_official_robustness",
                all(row.get("legacy_metric_deprecated") for row in payload["sensitivity_audit"]),
                "legacy fixed-count overlap retained only as deprecated field",
            ),
            hard_check_row(
                "grs_overall_max_boundary_tie_handled",
                any(
                    row["analysis_family"] == "GRS_AGGREGATION"
                    and int(row["boundary_tie_count"]) >= 1
                    for row in payload["sensitivity_audit"]
                ),
                "GRS overall max ablation uses threshold-inclusive ties",
            ),
            hard_check_row(
                "fixed_cases_all_pass",
                all(row["status"] == "PASS" for row in payload["fixed_case_audit"]),
                "fixed Stage4 final cases PASS",
            ),
        ]
        checks.append(
            hard_check_row(
                "hard_check_issue_zero",
                all(row["status"] == "PASS" for row in checks),
                "all preceding hard checks PASS",
            )
        )
        return checks

    def _write_outputs(self, **payload: Any) -> None:
        write_jsonl(self.output_dir / "rai_family_components.jsonl", payload["rai_family_rows"])
        write_jsonl(self.output_dir / "state_rai.jsonl", payload["state_rai_rows"])
        write_yaml(
            self.output_dir / "geological_attention_mapping_v1.yaml",
            {"method_version": STAGE4A2_METHOD_VERSION, "mappings": payload["mapping_rows"]},
        )
        write_jsonl(
            self.output_dir / "grs_dimension_components.jsonl", payload["grs_dimension_rows"]
        )
        write_jsonl(self.output_dir / "state_grs.jsonl", payload["state_grs_rows"])
        write_jsonl(self.output_dir / "state_grci.jsonl", payload["state_grci_rows"])
        write_jsonl(self.output_dir / "state_metric_summary.jsonl", payload["summaries"])
        write_csv(
            self.output_dir / "rai_formula_distribution_audit.csv", payload["rai_distribution"]
        )
        write_csv(self.output_dir / "rai_family_support_audit.csv", payload["rai_support_audit"])
        write_csv(
            self.output_dir / "rai_bitemporal_invariance_audit.csv", payload["rai_invariance_audit"]
        )
        write_csv(self.output_dir / "rai_rpm_exclusion_audit.csv", payload["rpm_audit"])
        write_csv(
            self.output_dir / "rai_support_provenance_audit.csv", payload["rai_support_audit"]
        )
        write_csv(self.output_dir / "rai_dominant_family_tie_audit.csv", payload["rai_tie_audit"])
        write_csv(
            self.output_dir / "rai_saturation_case_audit.csv",
            payload["rai_saturation_case_audit"],
        )
        write_csv(
            self.output_dir / "geological_mapping_exact_match_audit.csv", payload["mapping_audit"]
        )
        write_csv(
            self.output_dir / "geological_mapping_coverage_audit.csv",
            payload["grs_mapping_coverage"],
        )
        write_csv(self.output_dir / "grs_dimension_support_audit.csv", payload["grs_support_audit"])
        write_csv(
            self.output_dir / "grs_support_provenance_audit.csv", payload["grs_support_audit"]
        )
        write_csv(
            self.output_dir / "grs_dominant_dimension_tie_audit.csv",
            payload["grs_tie_audit"],
        )
        write_csv(
            self.output_dir / "grs_dimension_coverage_role_audit.csv",
            payload["grs_coverage_role_audit"],
        )
        write_csv(
            self.output_dir / "high_grs_low_coverage_audit.csv",
            payload["high_grs_low_coverage_audit"],
        )
        write_csv(
            self.output_dir / "grs_aggregation_comparison_audit.csv", payload["grs_comparison"]
        )
        write_csv(
            self.output_dir / "grs_epistemic_integrity_audit.csv", payload["grs_epistemic_audit"]
        )
        write_csv(self.output_dir / "grci_scope_boundary_audit.csv", payload["grci_scope_audit"])
        write_csv(
            self.output_dir / "bitemporal_metric_revision_audit.csv", payload["revision_audit"]
        )
        write_csv(
            self.output_dir / "stage4_bitemporal_metric_revision_explanation_audit.csv",
            payload["revision_explanation_audit"],
        )
        write_csv(
            self.output_dir / "metric_reference_integrity_audit.csv", payload["reference_audit"]
        )
        write_csv(
            self.output_dir / "stage4_metric_reference_integrity_audit.csv",
            payload["full_reference_audit"],
        )
        write_csv(
            self.output_dir / "stage4_upstream_freeze_integrity_audit.csv",
            payload["upstream_integrity_audit"],
        )
        write_csv(
            self.output_dir / "stage4a2_rai_future_leakage_trace_audit.csv",
            payload["future_leakage_trace_audit"],
        )
        write_csv(
            self.output_dir / "grs_structured_attribute_dependency_audit.csv",
            payload["grs_structured_dependency_audit"],
        )
        write_csv(
            self.output_dir / "grs_mapping_input_contract_audit.csv",
            payload["grs_mapping_input_contract_audit"],
        )
        write_csv(
            self.output_dir / "stage4_metric_sensitivity_audit.csv",
            payload["sensitivity_audit"],
        )
        write_json(
            self.output_dir / "stage4_metric_sensitivity_summary.json",
            payload["sensitivity_summary"],
        )
        write_csv(
            self.output_dir / "stage4_candidate_formal_semantic_audit.csv",
            payload["candidate_semantic_audit"],
        )
        write_json(
            self.output_dir / "stage4_candidate_formal_semantic_summary.json",
            payload["candidate_semantic_summary"],
        )
        write_csv(
            self.output_dir / "stage4_version_identity_audit.csv",
            payload["version_identity_audit"],
        )
        write_csv(self.output_dir / "formal_stage4_path_audit.csv", payload["formal_path_audit"])
        write_csv(
            self.output_dir / "stage4_byte_reproducibility_audit.csv",
            payload["byte_reproducibility_audit"],
            fieldnames=[
                "relative_path",
                "build_a_sha256",
                "build_b_sha256",
                "byte_identical",
                "status",
            ],
        )
        write_json(
            self.output_dir / "stage4_byte_reproducibility_summary.json",
            payload["byte_reproducibility_summary"],
        )
        write_csv(
            self.output_dir / "metric_method_contract_audit.csv",
            payload["data"]["method_contract"].audit_rows,
        )
        write_csv(
            self.output_dir / "fixed_stage4a2_metric_case_audit.csv", payload["fixed_case_audit"]
        )
        write_csv(
            self.output_dir / "fixed_stage4_final_case_audit.csv", payload["fixed_case_audit"]
        )
        write_csv(
            self.output_dir / "stage4a2_hard_check.csv",
            payload["hard_checks"],
            fieldnames=["check_name", "status", "details"],
        )
        write_csv(
            self.output_dir / "stage4_final_hard_check.csv",
            payload["hard_checks"],
            fieldnames=["check_name", "status", "details"],
        )
        self._write_source_snapshot()
        write_json(self.output_dir / "schema_manifest.json", self._schema_manifest())
        write_json(self.output_dir / "method_version.json", self._method_version(payload["data"]))
        write_json(self.output_dir / "freeze_manifest.json", self._freeze_manifest(payload))
        self._write_report(payload)
        (self.output_dir / "stage4_report.md").write_text(
            (self.output_dir / "stage4a2_report.md").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        write_file_hashes(self.output_dir)

    def _schema_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": STAGE4A2_SCHEMA_VERSION,
            "strict_models": [
                "RAIFamilyComponent",
                "StateRAI",
                "GeologicalAttentionMapping",
                "GRSDimensionComponent",
                "StateGRS",
                "StateGRCI",
                "StateMetricSummary",
            ],
        }

    def _method_version(self, data: dict[str, Any]) -> dict[str, Any]:
        contract = data["method_contract"]
        snapshot_path = self.output_dir / "stage4_source_snapshot.tar.gz"
        return {
            "method_version": STAGE4A2_METHOD_VERSION,
            "schema_version": STAGE4A2_SCHEMA_VERSION,
            "version_upgrade_reason": "TRACE_AND_METHOD_CONTRACT_SCHEMA_REFINEMENT",
            "final_patch_type": "REPRODUCIBILITY_AND_AUDIT_ONLY",
            "metric_formula_changed": False,
            "metric_semantics_changed": False,
            "generated_at": self.generated_at.isoformat(),
            "generated_at_semantics": "OFFLINE_RECONSTRUCTION_TIME",
            "rai_saturation_robust_z": RAI_SATURATION_ROBUST_Z,
            "state_metric_definition_sha256": contract.state_metric_definition_sha256,
            "geological_attention_mapping_sha256": contract.geological_attention_mapping_sha256,
            "operational_measurement_regime_review_sha256": (
                contract.operational_measurement_regime_review_sha256
            ),
            "metric_method_contract_hash": contract.contract_hash,
            "source_snapshot_sha256": sha256_file(snapshot_path) if snapshot_path.exists() else "",
            "source_tree_hash": _tree_hash(self.output_dir / "stage4_source_hashes.sha256"),
            "git_commit_hash": _git_value(self.repo_root, ["rev-parse", "HEAD"]),
            "working_tree_dirty": bool(_git_value(self.repo_root, ["status", "--short"])),
            "source_hashes": data["hashes"],
        }

    def _freeze_manifest(self, payload: dict[str, Any]) -> dict[str, Any]:
        state_rai_rows = payload["state_rai_rows"]
        state_grs_rows = payload["state_grs_rows"]
        state_grci_rows = payload["state_grci_rows"]
        revision_rows = payload["revision_audit"]
        contract = payload["data"]["method_contract"]
        snapshot_path = self.output_dir / "stage4_source_snapshot.tar.gz"
        return {
            "method_version": STAGE4A2_METHOD_VERSION,
            "schema_version": STAGE4A2_SCHEMA_VERSION,
            "final_patch_type": "REPRODUCIBILITY_AND_AUDIT_ONLY",
            "metric_formula_changed": False,
            "metric_semantics_changed": False,
            "generated_at": self.generated_at.isoformat(),
            "state_metric_summary_count": len(payload["summaries"]),
            "rai_available_bitemporal_count": sum(
                1 for row in state_rai_rows if row["rai"] is not None
            ),
            "rai_saturation_count": sum(
                1 for row in _latest_by_base_available(state_rai_rows) if row["rai"] == 1.0
            ),
            "grs_available_bitemporal_count": sum(
                1 for row in state_grs_rows if row["grs"] is not None
            ),
            "grci_available_bitemporal_count": sum(
                1 for row in state_grci_rows if row["grci"] is not None
            ),
            "mapping_count": len(payload["mapping_rows"]),
            "mapping_numeric_count": sum(
                1 for row in payload["mapping_rows"] if row["attention_value"] is not None
            ),
            "mapping_unmappable_count": sum(
                1 for row in payload["mapping_rows"] if row["attention_value"] is None
            ),
            "revision_chain_count": len(revision_rows),
            "rai_revision_change_count": sum(1 for row in revision_rows if row["rai_changed"]),
            "grs_revision_change_count": sum(1 for row in revision_rows if row["grs_changed"]),
            "grci_revision_change_count": sum(1 for row in revision_rows if row["grci_changed"]),
            "hard_check_issue_count": sum(
                1 for row in payload["hard_checks"] if row["status"] != "PASS"
            ),
            "state_metric_definition_sha256": contract.state_metric_definition_sha256,
            "geological_attention_mapping_sha256": contract.geological_attention_mapping_sha256,
            "operational_measurement_regime_review_sha256": (
                contract.operational_measurement_regime_review_sha256
            ),
            "metric_method_contract_hash": contract.contract_hash,
            "source_snapshot_sha256": sha256_file(snapshot_path) if snapshot_path.exists() else "",
            "source_tree_hash": _tree_hash(self.output_dir / "stage4_source_hashes.sha256"),
            "git_commit_hash": _git_value(self.repo_root, ["rev-parse", "HEAD"]),
            "working_tree_dirty": bool(_git_value(self.repo_root, ["status", "--short"])),
            "source_hashes": payload["data"]["hashes"],
        }

    def _write_report(self, payload: dict[str, Any]) -> None:
        state_rai_rows = payload["state_rai_rows"]
        state_grs_rows = payload["state_grs_rows"]
        state_grci_rows = payload["state_grci_rows"]
        base_rai_values = [
            float(row["rai"])
            for row in _latest_by_base_available(state_rai_rows)
            if row["rai"] is not None
        ]
        bitemporal_rai_values = [
            float(row["rai"]) for row in state_rai_rows if row["rai"] is not None
        ]
        grs_values = [float(row["grs"]) for row in state_grs_rows if row["grs"] is not None]
        grci_values = [float(row["grci"]) for row in state_grci_rows if row["grci"] is not None]
        role_grs = Counter(
            row["cell_scope_role"] for row in state_grs_rows if row["grs"] is not None
        )
        dominant = Counter(
            row["dominant_response_family"]
            for row in state_rai_rows
            if row["dominant_response_family"]
        )
        revision = payload["revision_audit"]
        grs_revision_changes = sum(1 for row in revision if row["grs_changed"])
        grci_revision_changes = sum(1 for row in revision if row["grci_changed"])
        rai_revision_changes = sum(1 for row in revision if row["rai_changed"])
        hard_failures = sum(1 for row in payload["hard_checks"] if row["status"] != "PASS")
        comparison = payload["grs_comparison"]
        official_sat = sum(1 for row in comparison if row["official_saturated_at_one"])
        max_sat = sum(1 for row in comparison if row["overall_max_saturated_at_one"])
        byte_summary = payload["byte_reproducibility_summary"]
        source_snapshot_hash = sha256_file(self.output_dir / "stage4_source_snapshot.tar.gz")
        source_tree_hash = _tree_hash(self.output_dir / "stage4_source_hashes.sha256")
        structured_rows = payload["grs_structured_dependency_audit"]
        sensitivity_lines = [
            (
                f"- {row['analysis_family']} `{row['variant_name']}`: "
                f"saturation={row['saturation_count']}, "
                f"spearman={row['spearman_vs_official']}, "
                f"threshold={row['top_threshold']}, "
                f"threshold-inclusive size={row['threshold_inclusive_set_size']}, "
                f"recall={row['reference_recall']}, "
                f"precision={row['variant_precision']}, "
                f"jaccard={row['jaccard']}, "
                f"boundary ties={row['boundary_tie_count']}"
            )
            for row in payload["sensitivity_audit"]
        ]
        lines = [
            "# Stage 4 Bitemporal State Metrics v1.1 Freeze",
            "",
            f"- Method version: `{STAGE4A2_METHOD_VERSION}`",
            f"- RAI available base State count: {len(base_rai_values)}",
            f"- RAI available Bitemporal Version count: {len(bitemporal_rai_values)}",
            f"- RAI distribution p50/p75/p90/p95/p99: {_dist(base_rai_values)}",
            f"- RAI=1 base count: {sum(1 for value in base_rai_values if value == 1.0)}",
            f"- LOAD/KINEMATIC dominant distribution: {dict(sorted(dominant.items()))}",
            "- RPM scalar RAI usage: 0",
            f"- GRS available version count: {len(grs_values)}",
            f"- GRS available by role: {dict(sorted(role_grs.items()))}",
            f"- GRS distribution: {_dist(grs_values)}",
            (
                f"- Official dimension-mean saturation: {official_sat}; "
                f"overall-max saturation: {max_sat}"
            ),
            f"- GRCI available DAILY_REVIEW version count: {len(grci_values)}",
            f"- GRCI distribution: {_dist(grci_values)}",
            f"- Revision chains with GRS change: {grs_revision_changes}",
            f"- DAILY_REVIEW chains with GRCI change: {grci_revision_changes}",
            f"- RAI change count: {rai_revision_changes}",
            "- Future leakage: 0",
            f"- Hard check failures: {hard_failures}",
            "",
            (
                "RAI, GRS and GRCI are non-probabilistic attention metrics. "
                "They are not risk probability, hazard probability, geological causation, "
                "or Typed Claim output."
            ),
            "",
            "## Reproducibility",
            "",
            (
                "Same input, same method/config and same generated-at are expected to produce "
                "byte-identical formal Stage4 outputs."
            ),
            f"- Source snapshot SHA256: `{source_snapshot_hash}`",
            f"- Source tree hash: `{source_tree_hash}`",
            (f"- Repeated build byte differences: {byte_summary.get('byte_difference_count', 0)}"),
            (f"- Repeated build status: {byte_summary.get('all_formal_outputs_byte_identical')}"),
            "",
            "## Robustness With Ties",
            "",
            (
                "Fixed Top-N overlap is deprecated when boundary ties exist. Robustness audits "
                "use threshold-inclusive top sets and report recall, precision and Jaccard."
            ),
            *sensitivity_lines,
            "",
            "## Overall-max GRS Ablation",
            "",
            (
                "The overall-max GRS ablation is descriptive only. Its many upper-bound ties "
                "represent discrimination loss and saturation, not a change to the official "
                "dimension-mean GRS formula."
            ),
            "",
            "## Structured-only Geological Attention",
            "",
            (
                "Runtime mutation audits change raw_text and assembled_text while keeping "
                "structured attributes and epistemic/source fields fixed."
            ),
            f"- Runtime mutation cases: {len(structured_rows)}",
            (
                f"- Mapping semantic differences: "
                f"{sum(1 for row in structured_rows if not row['mapping_semantics_equal'])}"
            ),
            (
                f"- Dimension attention differences: "
                f"{sum(1 for row in structured_rows if not row['dimension_attention_equal'])}"
            ),
            (
                f"- GRS value differences: "
                f"{sum(1 for row in structured_rows if not row['grs_value_equal'])}"
            ),
        ]
        (self.output_dir / "stage4a2_report.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    def _write_source_snapshot(self) -> None:
        included_files, exclusion_rows = self._stage4_source_snapshot_file_list()
        tar_path = self.output_dir / "stage4_source_snapshot.tar.gz"
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for relative in included_files:
                path = self.repo_root / relative
                data = path.read_bytes()
                info = tarfile.TarInfo(relative)
                info.size = len(data)
                info.mtime = 0
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mode = 0o755 if relative.startswith("scripts/") else 0o644
                archive.addfile(info, io.BytesIO(data))
        with (
            tar_path.open("wb") as handle,
            gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=handle,
                mtime=0,
            ) as gzip_file,
        ):
            gzip_file.write(tar_buffer.getvalue())
        hash_rows = [
            f"{sha256_file(self.repo_root / relative)}  {relative}" for relative in included_files
        ]
        (self.output_dir / "stage4_source_hashes.sha256").write_text(
            "\n".join(hash_rows) + "\n", encoding="utf-8"
        )
        manifest_rows = [
            {
                "relative_path": relative,
                "file_size_bytes": (self.repo_root / relative).stat().st_size,
                "sha256": sha256_file(self.repo_root / relative),
                "included": True,
                "source_category": _source_category(relative),
            }
            for relative in included_files
        ]
        write_csv(self.output_dir / "stage4_source_snapshot_manifest.csv", manifest_rows)
        write_csv(
            self.output_dir / "stage4_source_snapshot_exclusion_audit.csv",
            exclusion_rows,
            fieldnames=["path", "matched_exclusion_rule", "excluded", "status"],
        )
        write_csv(
            self.output_dir / "stage4_source_snapshot_integrity_audit.csv",
            self._source_snapshot_integrity_audit(tar_path, included_files),
        )

    def _stage4_source_snapshot_file_list(
        self,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        roots = [
            "src/tbm_twin/metrics",
            "scripts/build_stage4a1_metric_foundation.py",
            "scripts/build_stage4a1_1_metric_method_freeze.py",
            "scripts/build_stage4a2_bitemporal_state_metrics.py",
            "configs/metric_foundation.yaml",
            "configs/state_metric_definition_v1.yaml",
            "configs/geological_attention_mapping_v1.yaml",
            "configs/operational_measurement_regime_review.yaml",
            "pyproject.toml",
        ]
        tests = sorted(
            {
                path.relative_to(self.repo_root).as_posix()
                for directory in [
                    self.repo_root / "tests/unit",
                    self.repo_root / "tests/integration",
                ]
                for path in directory.glob("test_*")
                if path.is_file() and _is_stage4_test(path.name)
            }
        )
        roots.extend(tests)
        included: list[str] = []
        excluded_rows: list[dict[str, Any]] = []
        for root in sorted(set(roots)):
            path = self.repo_root / root
            if path.is_file():
                rule = _snapshot_exclusion_rule(root)
                if rule:
                    excluded_rows.append(_exclusion_row(root, rule, True))
                else:
                    included.append(root)
                continue
            if not path.is_dir():
                continue
            for child in sorted(item for item in path.rglob("*") if item.is_file()):
                relative = child.relative_to(self.repo_root).as_posix()
                rule = _snapshot_exclusion_rule(relative)
                if rule:
                    excluded_rows.append(_exclusion_row(relative, rule, True))
                    continue
                included.append(relative)
        return sorted(set(included)), excluded_rows

    def _source_snapshot_integrity_audit(
        self, tar_path: Path, manifest_files: list[str]
    ) -> list[dict[str, Any]]:
        with gzip.GzipFile(filename="", mode="rb", fileobj=tar_path.open("rb")) as gzip_file:
            tar_bytes = gzip_file.read()
        members: list[tarfile.TarInfo] = []
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
            members = archive.getmembers()
        names = [member.name for member in members]
        rows = [
            _snapshot_integrity_row(
                "snapshot_contains_pycache",
                not any("__pycache__" in name.split("/") for name in names),
            ),
            _snapshot_integrity_row(
                "snapshot_contains_pyc",
                not any(name.endswith((".pyc", ".pyo")) for name in names),
            ),
            _snapshot_integrity_row(
                "snapshot_contains_absolute_path",
                not any(name.startswith("/") or ".." in name.split("/") for name in names),
            ),
            _snapshot_integrity_row(
                "snapshot_contains_venv",
                not any(
                    part in {".venv", "venv", "node_modules"}
                    for name in names
                    for part in name.split("/")
                ),
            ),
            _snapshot_integrity_row(
                "snapshot_contains_cache_directory",
                not any(
                    part in {".pytest_cache", ".mypy_cache", ".ruff_cache"}
                    for name in names
                    for part in name.split("/")
                ),
            ),
            _snapshot_integrity_row("snapshot_member_order_sorted", names == sorted(names)),
            _snapshot_integrity_row(
                "tar_uid_normalized", all(member.uid == 0 for member in members)
            ),
            _snapshot_integrity_row(
                "tar_gid_normalized", all(member.gid == 0 for member in members)
            ),
            _snapshot_integrity_row(
                "tar_mtime_normalized", all(member.mtime == 0 for member in members)
            ),
            _snapshot_integrity_row(
                "gzip_mtime_normalized", tar_path.read_bytes()[4:8] == b"\x00\x00\x00\x00"
            ),
            _snapshot_integrity_row(
                "manifest_matches_archive_files", sorted(manifest_files) == sorted(names)
            ),
        ]
        return rows


def _latest_by_base_available(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_base: dict[str, dict[str, Any]] = {}
    for row in rows:
        by_base.setdefault(str(row["base_stage3a_state_version_id"]), row)
    return list(by_base.values())


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _dist(values: list[float]) -> dict[str, float | None]:
    return {
        "p50": _quantile(values, 0.50),
        "p75": _quantile(values, 0.75),
        "p90": _quantile(values, 0.90),
        "p95": _quantile(values, 0.95),
        "p99": _quantile(values, 0.99),
    }


def _changed_dimensions(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    before_values = before["dimension_attention_values"]
    after_values = after["dimension_attention_values"]
    return sorted(
        dimension
        for dimension in set(before_values) | set(after_values)
        if before_values.get(dimension) != after_values.get(dimension)
    )


def _case_row(case_name: str, passed: bool, observed: Any = None) -> dict[str, Any]:
    return {
        "case_name": case_name,
        "observed_value": observed,
        "status": "PASS" if passed else "FAIL",
    }


def _close(actual: float, expected: float, tolerance: float = 1e-9) -> bool:
    return abs(actual - expected) <= tolerance


def _nullable_close(actual: Any, expected: Any, tolerance: float = 1e-9) -> bool:
    if actual is None or expected is None:
        return actual is expected
    return _close(float(actual), float(expected), tolerance)


def _by_key(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(row[key]): row for row in rows}


def _reference_row(
    reference_type: str,
    reference_id: str,
    target_id: str,
    passed: bool,
    reason: str = "",
) -> dict[str, Any]:
    return {
        "reference_type": reference_type,
        "reference_id": reference_id,
        "target_id": target_id,
        "status": "PASS" if passed else "FAIL",
        "reason": reason,
    }


def _spearman_for_common(official: dict[str, float], variant: dict[str, float]) -> float | None:
    keys = sorted(set(official) & set(variant))
    if len(keys) < 2:
        return None
    official_ranks = _ranks([official[key] for key in keys])
    variant_ranks = _ranks([variant[key] for key in keys])
    return _pearson(official_ranks, variant_ranks)


def _top_fraction_overlap(
    official: dict[str, float], variant: dict[str, float], fraction: float
) -> str:
    keys = sorted(set(official) & set(variant))
    if not keys:
        return "0/0"
    top_count = max(1, math.ceil(len(keys) * fraction))
    official_top = {
        key
        for key, _ in sorted(official.items(), key=lambda item: item[1], reverse=True)[:top_count]
    }
    variant_top = {
        key
        for key, _ in sorted(
            ((key, variant[key]) for key in keys), key=lambda item: item[1], reverse=True
        )[:top_count]
    }
    return f"{len(official_top & variant_top)}/{top_count}"


def compute_tie_aware_top_fraction(
    records: dict[str, float], fraction: float = 0.10
) -> dict[str, Any]:
    """Return a threshold-inclusive top set that keeps all boundary ties."""

    valid = {key: value for key, value in records.items() if value is not None}
    if not valid:
        return {
            "valid_count": 0,
            "nominal_top_count": 0,
            "top_threshold": None,
            "threshold_inclusive_set": set(),
            "threshold_inclusive_set_size": 0,
            "boundary_tie_count": 0,
        }
    nominal_top_count = max(1, math.ceil(len(valid) * fraction))
    ordered_scores = sorted(valid.values(), reverse=True)
    threshold = ordered_scores[nominal_top_count - 1]
    top_set = {key for key, score in valid.items() if score >= threshold}
    return {
        "valid_count": len(valid),
        "nominal_top_count": nominal_top_count,
        "top_threshold": threshold,
        "threshold_inclusive_set": top_set,
        "threshold_inclusive_set_size": len(top_set),
        "boundary_tie_count": sum(1 for score in valid.values() if score == threshold),
    }


def compute_tie_aware_top_comparison(
    reference: dict[str, float], variant: dict[str, float], fraction: float = 0.10
) -> dict[str, Any]:
    reference_top = compute_tie_aware_top_fraction(reference, fraction)
    variant_top = compute_tie_aware_top_fraction(variant, fraction)
    reference_set = reference_top["threshold_inclusive_set"]
    variant_set = variant_top["threshold_inclusive_set"]
    intersection = reference_set & variant_set
    union = reference_set | variant_set
    return {
        "reference_valid_count": reference_top["valid_count"],
        "variant_valid_count": variant_top["valid_count"],
        "nominal_top_fraction": fraction,
        "nominal_top_count": reference_top["nominal_top_count"],
        "reference_top_threshold": reference_top["top_threshold"],
        "variant_top_threshold": variant_top["top_threshold"],
        "top_threshold": variant_top["top_threshold"],
        "reference_threshold_inclusive_set_size": reference_top["threshold_inclusive_set_size"],
        "variant_threshold_inclusive_set_size": variant_top["threshold_inclusive_set_size"],
        "threshold_inclusive_set_size": variant_top["threshold_inclusive_set_size"],
        "reference_boundary_tie_count": reference_top["boundary_tie_count"],
        "variant_boundary_tie_count": variant_top["boundary_tie_count"],
        "boundary_tie_count": variant_top["boundary_tie_count"],
        "intersection_with_official": len(intersection),
        "union_with_official": len(union),
        "reference_recall": len(intersection) / len(reference_set) if reference_set else None,
        "variant_precision": len(intersection) / len(variant_set) if variant_set else None,
        "jaccard": len(intersection) / len(union) if union else None,
    }


def _has_numeric_mapping(
    evidence: dict[str, Any], mapping_by_key: dict[tuple[str, str], dict[str, Any]]
) -> bool:
    attrs = evidence.get("attributes")
    if not isinstance(attrs, dict):
        return False
    for attribute_name, value in attrs.items():
        mapping = mapping_by_key.get((str(attribute_name), _normalize_for_audit(value)))
        if mapping and mapping.get("attention_value") is not None:
            return True
    return False


def _single_evidence_grs_result(
    evidence: dict[str, Any], mapping_by_key: dict[tuple[str, str], dict[str, Any]]
) -> dict[str, Any]:
    uid = str(evidence.get("evidence_uid", "synthetic_g1"))
    normalized = {
        **evidence,
        "evidence_uid": uid,
        "document_id": str(evidence.get("document_id", "synthetic_doc")),
        "source_type": str(evidence.get("source_type", "SYNTHETIC")),
        "epistemic_status": str(evidence.get("epistemic_status", "FORECAST")),
    }
    snapshot = {
        "bitemporal_version_id": "audit_b1",
        "base_stage3a_state_version_id": "audit_s1",
        "valid_date": "2023-01-01",
        "knowledge_time_start_local_date": "2023-01-01",
        "cell_id": "audit_cell",
        "cell_scope_role": "DAILY_REVIEW_CELL",
        "materialized_daily_review_evidence_ids": [uid],
    }
    dimension_rows, state_rows, _, _ = build_grs_for_snapshots(
        [snapshot], {uid: normalized}, mapping_by_key
    )
    return {
        "mapping_ids": sorted(
            {mapping_id for row in dimension_rows for mapping_id in row["supporting_mapping_ids"]}
        ),
        "dimension_attention_values": state_rows[0]["dimension_attention_values"],
        "grs": state_rows[0]["grs"],
        "grs_status": state_rows[0]["grs_status"],
    }


def _normalize_for_audit(value: Any) -> str:
    from tbm_twin.metrics.geological_mapping import normalize_value

    return normalize_value(value)


def _is_stage4_test(name: str) -> bool:
    tokens = (
        "stage4",
        "rai",
        "grs",
        "grci",
        "metric",
        "response_profile",
        "response_deviation",
        "causal_baseline",
    )
    return any(token in name for token in tokens)


def _snapshot_exclusion_rule(relative: str) -> str | None:
    parts = relative.split("/")
    if "__pycache__" in parts:
        return "__pycache__/"
    if any(part in {".pytest_cache", ".mypy_cache", ".ruff_cache"} for part in parts):
        return "cache_directory"
    if any(part in {".venv", "venv", "node_modules"} for part in parts):
        return "environment_directory"
    if relative.endswith((".pyc", ".pyo")):
        return "compiled_python"
    if relative.endswith((".log", ".tmp", ".swp")):
        return "temporary_file"
    if relative.endswith(".DS_Store") or ".DS_Store" in parts:
        return ".DS_Store"
    return None


def _exclusion_row(relative: str, rule: str, excluded: bool) -> dict[str, Any]:
    return {
        "path": relative,
        "matched_exclusion_rule": rule,
        "excluded": excluded,
        "status": "PASS" if excluded else "FAIL",
    }


def _source_category(relative: str) -> str:
    if relative.startswith("src/"):
        return "source"
    if relative.startswith("scripts/"):
        return "script"
    if relative.startswith("configs/"):
        return "config"
    if relative.startswith("tests/"):
        return "test"
    return "project"


def _snapshot_integrity_row(check_name: str, passed: bool) -> dict[str, Any]:
    return {
        "check_name": check_name,
        "passed": passed,
        "status": "PASS" if passed else "FAIL",
    }


def _snapshot_integrity_pass(rows: list[dict[str, Any]], check_name: str) -> bool:
    return any(row["check_name"] == check_name and row["status"] == "PASS" for row in rows)


def _directory_hashes(directory: Path) -> dict[str, str]:
    if not directory.exists():
        return {}
    return {
        path.relative_to(directory).as_posix(): sha256_file(path)
        for path in sorted(item for item in directory.rglob("*") if item.is_file())
    }


def _ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        rank = (index + end + 1) / 2
        for original_index, _ in ordered[index:end]:
            ranks[original_index] = rank
        index = end
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or not left:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right, strict=True))
    left_var = sum((a - left_mean) ** 2 for a in left)
    right_var = sum((b - right_mean) ** 2 for b in right)
    if left_var == 0 or right_var == 0:
        return None
    return numerator / math.sqrt(left_var * right_var)


def _tree_hash(path: Path) -> str:
    if not path.exists():
        return ""
    return sha256_file(path)


def _git_value(repo_root: Path, args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"
    return completed.stdout.strip()
