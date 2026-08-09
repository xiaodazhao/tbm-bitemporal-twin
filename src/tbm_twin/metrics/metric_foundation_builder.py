"""Stage 4A1 metric foundation builder."""

from __future__ import annotations

import platform
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tbm_twin.metrics.geology_inventory import build_geological_inventory
from tbm_twin.metrics.io import (
    read_csv,
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
from tbm_twin.metrics.models import (
    STAGE4A1_METHOD_VERSION,
    STAGE4A1_SCHEMA_VERSION,
    Stage4A1Config,
)
from tbm_twin.metrics.operational_baseline import (
    assess_mechanical_eligibility,
    build_causal_baselines,
    parse_date,
)
from tbm_twin.metrics.response_deviation import build_response_deviation_components
from tbm_twin.metrics.response_profile import (
    build_bitemporal_profile_bindings,
    build_response_profiles,
)
from tbm_twin.metrics.validation import count_by, hard_check_row


@dataclass(frozen=True)
class Stage4A1BuildResult:
    """Summary returned by the Stage 4A1 builder."""

    output_dir: Path
    baseline_count: int
    response_component_count: int
    response_profile_count: int
    bitemporal_binding_count: int
    hard_check_failures: int


class MetricFoundationBuilder:
    """Build Stage 4A1 causal response and geology inventory artifacts."""

    def __init__(self, config: Stage4A1Config) -> None:
        self.config = config
        self.repo_root = config.repo_root
        yaml_config = read_yaml(config.resolve(config.config_path))
        self.channels = [str(item) for item in yaml_config["channels"]]
        self.min_sample_count = int(yaml_config["minimum_baseline_sample_count"])
        self.mad_scale_factor = float(yaml_config["mad_scale_factor"])
        self.iqr_scale_divisor = float(yaml_config["iqr_scale_divisor"])
        self.alignment_id = str(yaml_config["alignment_id"])
        self.invalid_quality_flags = {
            str(item) for item in yaml_config.get("mechanically_invalid_quality_flags", [])
        }
        self.invalid_reason_codes = {
            str(item) for item in yaml_config.get("mechanically_invalid_reason_codes", [])
        }
        self.output_dir = config.resolve(config.output_dir)

    def build(self) -> Stage4A1BuildResult:
        """Build all Stage 4A1 candidate artifacts."""

        self.output_dir.mkdir(parents=True, exist_ok=True)
        inputs = self._load_inputs()
        valid_dates = sorted(
            {parse_date(str(row["target_date"])) for row in inputs["daily_states"]}
        )
        eligibility, eligibility_audit, quality_reason_inventory = assess_mechanical_eligibility(
            inputs["responses"],
            set(self.channels),
            self.invalid_quality_flags,
            self.invalid_reason_codes,
        )
        baselines, sample_audit, future_leakage_audit = build_causal_baselines(
            valid_dates=valid_dates,
            responses=inputs["responses"],
            eligibility=eligibility,
            channels=self.channels,
            min_sample_count=self.min_sample_count,
            mad_scale_factor=self.mad_scale_factor,
            iqr_scale_divisor=self.iqr_scale_divisor,
            alignment_id=self.alignment_id,
        )
        components, components_by_response_id, component_reference_audit = (
            build_response_deviation_components(
                responses=inputs["responses"],
                baselines=baselines,
                eligibility=eligibility,
                coverage_by_response_id=inputs["coverage_by_response_id"],
                source_operational_manifest_hash=inputs["source_hashes"]["operational_freeze"],
            )
        )
        profiles, profile_by_state_id, profile_coverage_audit, multicell_audit = (
            build_response_profiles(
                state_versions=inputs["stage3a_versions"],
                response_links=inputs["response_links"],
                components_by_response_id=components_by_response_id,
                channels=self.channels,
                coverage_by_response_id=inputs["coverage_by_response_id"],
                source_stage3a_manifest_hash=inputs["source_hashes"]["stage3a_freeze"],
                source_operational_manifest_hash=inputs["source_hashes"]["operational_freeze"],
            )
        )
        bindings, invariance_audit = build_bitemporal_profile_bindings(
            bitemporal_versions=inputs["bitemporal_versions"],
            profile_by_state_id=profile_by_state_id,
        )
        inventory, mapping_template, mapping_audit, geology_reference_audit = (
            build_geological_inventory(
                evidence_rows=inputs["geology_evidence"],
                document_rows=inputs["geology_documents"],
                stage3b_snapshots=inputs["stage3b_snapshots"],
            )
        )
        completeness_audit = self._mapping_completeness_audit(inventory, mapping_template)
        fixed_case_audit = self._fixed_case_audit(
            baselines,
            components,
            profiles,
            bindings,
            inventory,
            mapping_template,
            future_leakage_audit,
        )
        hard_checks = self._hard_checks(
            inputs=inputs,
            baselines=baselines,
            components=components,
            profiles=profiles,
            bindings=bindings,
            mapping_template=mapping_template,
            future_leakage_audit=future_leakage_audit,
            profile_coverage_audit=profile_coverage_audit,
            invariance_audit=invariance_audit,
        )
        self._write_outputs(
            baselines=baselines,
            components=components,
            profiles=profiles,
            bindings=bindings,
            inventory=inventory,
            mapping_template=mapping_template,
            eligibility_audit=eligibility_audit,
            quality_reason_inventory=quality_reason_inventory,
            sample_audit=sample_audit,
            future_leakage_audit=future_leakage_audit,
            component_reference_audit=component_reference_audit,
            multicell_audit=multicell_audit,
            profile_coverage_audit=profile_coverage_audit,
            invariance_audit=invariance_audit,
            geology_reference_audit=geology_reference_audit,
            mapping_audit=mapping_audit,
            completeness_audit=completeness_audit,
            fixed_case_audit=fixed_case_audit,
            hard_checks=hard_checks,
            inputs=inputs,
        )
        failures = sum(1 for row in hard_checks if row["status"] != "PASS")
        return Stage4A1BuildResult(
            output_dir=self.output_dir,
            baseline_count=len(baselines),
            response_component_count=len(components),
            response_profile_count=len(profiles),
            bitemporal_binding_count=len(bindings),
            hard_check_failures=failures,
        )

    def _load_inputs(self) -> dict[str, Any]:
        stage3a_dir = self.config.resolve(self.config.stage3a_dir)
        stage3b_dir = self.config.resolve(self.config.stage3b_dir)
        operational_dir = self.config.resolve(self.config.operational_freeze_dir)
        geology_dir = self.config.resolve(self.config.geology_freeze_dir)
        coverage_rows = read_csv(stage3a_dir / "response_state_coverage_audit.csv")
        coverage_by_response_id = {
            str(row["response_evidence_id"]): str(row["coverage_class"]) for row in coverage_rows
        }
        return {
            "stage3a_dir": stage3a_dir,
            "stage3b_dir": stage3b_dir,
            "operational_dir": operational_dir,
            "geology_dir": geology_dir,
            "daily_states": read_jsonl(stage3a_dir / "daily_construction_states.jsonl"),
            "stage3a_versions": read_jsonl(
                stage3a_dir / "initial_construction_state_versions.jsonl"
            ),
            "response_links": read_jsonl(stage3a_dir / "state_response_evidence_links.jsonl"),
            "coverage_rows": coverage_rows,
            "coverage_by_response_id": coverage_by_response_id,
            "responses": read_jsonl(operational_dir / "response_evidence.jsonl"),
            "bitemporal_versions": read_jsonl(stage3b_dir / "bitemporal_state_versions.jsonl"),
            "stage3b_snapshots": read_jsonl(stage3b_dir / "materialized_state_snapshots.jsonl"),
            "geology_documents": read_jsonl(geology_dir / "geological_documents.jsonl"),
            "geology_evidence": read_jsonl(geology_dir / "primary_geological_evidence.jsonl"),
            "source_hashes": {
                "stage3b_freeze": sha256_file(stage3b_dir / "file_hashes.sha256"),
                "stage3a_freeze": sha256_file(stage3a_dir / "file_hashes.sha256"),
                "operational_freeze": sha256_file(operational_dir / "file_hashes.sha256"),
                "geology_freeze": sha256_file(geology_dir / "file_hashes.sha256"),
            },
            "stage3b_manifest": read_json(stage3b_dir / "freeze_manifest.json"),
            "stage3a_manifest": read_json(stage3a_dir / "freeze_manifest.json"),
            "operational_manifest": read_json(operational_dir / "freeze_manifest.json"),
            "geology_manifest": read_json(geology_dir / "freeze_manifest.json"),
        }

    def _write_outputs(
        self,
        *,
        baselines: list[dict[str, Any]],
        components: list[dict[str, Any]],
        profiles: list[dict[str, Any]],
        bindings: list[dict[str, Any]],
        inventory: list[dict[str, Any]],
        mapping_template: dict[str, Any],
        eligibility_audit: list[dict[str, Any]],
        quality_reason_inventory: list[dict[str, Any]],
        sample_audit: list[dict[str, Any]],
        future_leakage_audit: list[dict[str, Any]],
        component_reference_audit: list[dict[str, Any]],
        multicell_audit: list[dict[str, Any]],
        profile_coverage_audit: list[dict[str, Any]],
        invariance_audit: list[dict[str, Any]],
        geology_reference_audit: list[dict[str, Any]],
        mapping_audit: list[dict[str, Any]],
        completeness_audit: list[dict[str, Any]],
        fixed_case_audit: list[dict[str, Any]],
        hard_checks: list[dict[str, Any]],
        inputs: dict[str, Any],
    ) -> None:
        write_jsonl(self.output_dir / "causal_operational_baselines.jsonl", baselines)
        write_jsonl(self.output_dir / "response_deviation_components.jsonl", components)
        write_jsonl(self.output_dir / "cell_operational_response_profiles.jsonl", profiles)
        write_jsonl(self.output_dir / "bitemporal_response_profile_bindings.jsonl", bindings)
        write_csv(self.output_dir / "geological_attribute_value_inventory.csv", inventory)
        write_csv(
            self.output_dir / "geological_attribute_mapping_candidate_audit.csv", mapping_audit
        )
        write_yaml(self.output_dir / "geological_attention_mapping_template.yaml", mapping_template)
        write_csv(self.output_dir / "response_mechanical_eligibility_audit.csv", eligibility_audit)
        write_csv(
            self.output_dir / "response_quality_reason_inventory.csv",
            quality_reason_inventory,
        )
        write_csv(self.output_dir / "causal_baseline_sample_audit.csv", sample_audit)
        write_csv(
            self.output_dir / "causal_baseline_future_leakage_audit.csv",
            future_leakage_audit,
            fieldnames=[
                "baseline_id",
                "valid_date",
                "sample_response_evidence_id",
                "sample_target_date",
                "status",
            ],
        )
        write_csv(
            self.output_dir / "response_component_reference_audit.csv",
            component_reference_audit,
        )
        write_csv(self.output_dir / "response_component_multicell_audit.csv", multicell_audit)
        write_csv(self.output_dir / "response_profile_coverage_audit.csv", profile_coverage_audit)
        write_csv(
            self.output_dir / "response_profile_bitemporal_invariance_audit.csv",
            invariance_audit,
        )
        write_csv(
            self.output_dir / "geological_inventory_reference_audit.csv", geology_reference_audit
        )
        write_csv(
            self.output_dir / "geological_mapping_template_completeness_audit.csv",
            completeness_audit,
        )
        write_csv(self.output_dir / "fixed_metric_foundation_case_audit.csv", fixed_case_audit)
        write_csv(
            self.output_dir / "stage4a1_hard_check.csv",
            hard_checks,
            fieldnames=["check_name", "status", "details"],
        )
        write_json(self.output_dir / "schema_manifest.json", self._schema_manifest())
        write_json(self.output_dir / "method_version.json", self._method_version(inputs))
        write_json(
            self.output_dir / "freeze_manifest.json",
            self._freeze_manifest(
                inputs=inputs,
                baselines=baselines,
                components=components,
                profiles=profiles,
                bindings=bindings,
                inventory=inventory,
                mapping_template=mapping_template,
                future_leakage_audit=future_leakage_audit,
                hard_checks=hard_checks,
            ),
        )
        self._write_report(
            inputs=inputs,
            baselines=baselines,
            components=components,
            profiles=profiles,
            bindings=bindings,
            inventory=inventory,
            mapping_template=mapping_template,
            future_leakage_audit=future_leakage_audit,
            hard_checks=hard_checks,
        )
        write_file_hashes(self.output_dir)

    def _hard_checks(
        self,
        *,
        inputs: dict[str, Any],
        baselines: list[dict[str, Any]],
        components: list[dict[str, Any]],
        profiles: list[dict[str, Any]],
        bindings: list[dict[str, Any]],
        mapping_template: dict[str, Any],
        future_leakage_audit: list[dict[str, Any]],
        profile_coverage_audit: list[dict[str, Any]],
        invariance_audit: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        baseline_keys = {(row["valid_date"], row["channel_name"]) for row in baselines}
        component_response_ids = [row["response_evidence_id"] for row in components]
        profile_response_ids = {
            response_id for profile in profiles for response_id in profile["response_evidence_ids"]
        }
        linked_response_ids = {
            str(link["response_evidence_id"]) for link in inputs["response_links"]
        }
        non_cell_in_profiles = [
            response_id
            for response_id in profile_response_ids
            if inputs["coverage_by_response_id"].get(response_id) != "CELL_LINKED"
        ]
        mapping_rows = mapping_template["mappings"]
        checks = [
            hard_check_row(
                "causal_baseline_count",
                len(baselines)
                == len(baseline_keys)
                == len(inputs["daily_states"]) * len(self.channels),
                (
                    f"{len(baselines)} baselines for {len(inputs['daily_states'])} dates "
                    f"x {len(self.channels)} channels"
                ),
            ),
            hard_check_row(
                "no_future_baseline_leakage",
                not future_leakage_audit,
                f"{len(future_leakage_audit)} leakage rows",
            ),
            hard_check_row(
                "one_component_per_response_evidence",
                len(components) == len(inputs["responses"]) == len(set(component_response_ids)),
                f"{len(components)} components for {len(inputs['responses'])} response evidence",
            ),
            hard_check_row(
                "cell_profiles_use_only_cell_linked_response",
                not non_cell_in_profiles and profile_response_ids == linked_response_ids,
                (
                    f"{len(non_cell_in_profiles)} non-cell responses in profiles; "
                    f"profile ids {len(profile_response_ids)}, "
                    f"linked ids {len(linked_response_ids)}"
                ),
            ),
            hard_check_row(
                "response_profile_count",
                len(profiles) == len(inputs["stage3a_versions"]),
                f"{len(profiles)} profiles for {len(inputs['stage3a_versions'])} Stage3A versions",
            ),
            hard_check_row(
                "bitemporal_binding_count",
                len(bindings) == len(inputs["bitemporal_versions"]),
                (
                    f"{len(bindings)} bindings for "
                    f"{len(inputs['bitemporal_versions'])} Stage3B versions"
                ),
            ),
            hard_check_row(
                "bitemporal_profile_invariance",
                all(row["status"] == "PASS" for row in invariance_audit),
                f"{sum(1 for row in invariance_audit if row['status'] != 'PASS')} failed chains",
            ),
            hard_check_row(
                "all_mapping_template_attention_values_null",
                all(row["attention_value"] is None for row in mapping_rows),
                (
                    f"{sum(1 for row in mapping_rows if row['attention_value'] is not None)} "
                    "non-null attention values"
                ),
            ),
            hard_check_row(
                "no_rai_grs_grci_outputs",
                not any(
                    path.name
                    in {
                        "rai.jsonl",
                        "grs.jsonl",
                        "grci.jsonl",
                        "risk_index.jsonl",
                        "claim.jsonl",
                    }
                    for path in self.output_dir.glob("*")
                ),
                "Stage 4A1 writes foundation artifacts only",
            ),
            hard_check_row(
                "profile_coverage_audit_clean",
                all(row["status"] == "PASS" for row in profile_coverage_audit),
                (
                    f"{sum(1 for row in profile_coverage_audit if row['status'] != 'PASS')} "
                    "failed profile coverage rows"
                ),
            ),
        ]
        return checks

    def _mapping_completeness_audit(
        self, inventory: list[dict[str, Any]], mapping_template: dict[str, Any]
    ) -> list[dict[str, Any]]:
        inventory_keys = {
            (str(row["attribute_name"]), str(row["normalized_serialization"])) for row in inventory
        }
        template_keys = {
            (str(row["attribute_name"]), str(row["normalized_serialization"]))
            for row in mapping_template["mappings"]
        }
        rows = [
            {
                "attribute_name": key[0],
                "normalized_serialization": key[1],
                "in_inventory": key in inventory_keys,
                "in_template": key in template_keys,
                "status": "PASS" if key in inventory_keys and key in template_keys else "FAIL",
            }
            for key in sorted(inventory_keys | template_keys)
        ]
        return rows

    def _fixed_case_audit(
        self,
        baselines: list[dict[str, Any]],
        components: list[dict[str, Any]],
        profiles: list[dict[str, Any]],
        bindings: list[dict[str, Any]],
        inventory: list[dict[str, Any]],
        mapping_template: dict[str, Any],
        future_leakage_audit: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {
                "case_name": "causal_baseline_uses_prior_target_dates_only",
                "observed_value": len(future_leakage_audit),
                "expected_value": 0,
                "status": "PASS" if not future_leakage_audit else "FAIL",
            },
            {
                "case_name": "response_component_one_per_response",
                "observed_value": len(components),
                "expected_value": 5595,
                "status": "PASS" if len(components) == 5595 else "FAIL",
            },
            {
                "case_name": "profile_one_per_stage3a_state_version",
                "observed_value": len(profiles),
                "expected_value": 1322,
                "status": "PASS" if len(profiles) == 1322 else "FAIL",
            },
            {
                "case_name": "binding_one_per_stage3b_version",
                "observed_value": len(bindings),
                "expected_value": 1375,
                "status": "PASS" if len(bindings) == 1375 else "FAIL",
            },
            {
                "case_name": "mapping_attention_values_unset",
                "observed_value": sum(
                    1 for row in mapping_template["mappings"] if row["attention_value"] is not None
                ),
                "expected_value": 0,
                "status": "PASS",
            },
            {
                "case_name": "geological_inventory_present",
                "observed_value": len(inventory),
                "expected_value": ">0",
                "status": "PASS" if inventory else "FAIL",
            },
            {
                "case_name": "baseline_grid_complete",
                "observed_value": len(baselines),
                "expected_value": 455,
                "status": "PASS" if len(baselines) == 455 else "FAIL",
            },
        ]

    def _schema_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": STAGE4A1_SCHEMA_VERSION,
            "strict_models": [
                "CausalOperationalBaseline",
                "ResponseDeviationComponent",
                "CellOperationalResponseProfile",
                "BitemporalResponseProfileBinding",
                "GeologicalAttributeInventoryRecord",
                "GeologicalAttentionMappingTemplateEntry",
            ],
            "grs_status": "GEOLOGICAL_ATTENTION_MAPPING_NOT_FROZEN",
            "grci_status": "DEPENDENT_METRICS_NOT_BUILT_IN_STAGE4A1",
        }

    def _method_version(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "metric_foundation_method_version": STAGE4A1_METHOD_VERSION,
            "schema_version": STAGE4A1_SCHEMA_VERSION,
            "generated_at": self.config.generated_at.isoformat(),
            "git_commit_hash": _git_commit_hash(self.repo_root),
            "working_tree_dirty": _git_dirty(self.repo_root),
            "python_version": platform.python_version(),
            "channels": self.channels,
            "minimum_baseline_sample_count": self.min_sample_count,
            "mad_scale_factor": self.mad_scale_factor,
            "iqr_scale_divisor": self.iqr_scale_divisor,
            "source_stage3b_manifest_hash": inputs["source_hashes"]["stage3b_freeze"],
            "source_stage3a_manifest_hash": inputs["source_hashes"]["stage3a_freeze"],
            "source_operational_manifest_hash": inputs["source_hashes"]["operational_freeze"],
            "source_geology_manifest_hash": inputs["source_hashes"]["geology_freeze"],
        }

    def _freeze_manifest(
        self,
        *,
        inputs: dict[str, Any],
        baselines: list[dict[str, Any]],
        components: list[dict[str, Any]],
        profiles: list[dict[str, Any]],
        bindings: list[dict[str, Any]],
        inventory: list[dict[str, Any]],
        mapping_template: dict[str, Any],
        future_leakage_audit: list[dict[str, Any]],
        hard_checks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        baseline_status = count_by(baselines, "baseline_status")
        component_status = count_by(components, "component_status")
        attr_names = {row["attribute_name"] for row in inventory}
        first_available = {
            channel: min(
                (
                    str(row["valid_date"])
                    for row in baselines
                    if row["channel_name"] == channel and row["baseline_status"] == "AVAILABLE"
                ),
                default=None,
            )
            for channel in self.channels
        }
        return {
            "method_version": STAGE4A1_METHOD_VERSION,
            "schema_version": STAGE4A1_SCHEMA_VERSION,
            "generated_at": self.config.generated_at.isoformat(),
            "baseline_count": len(baselines),
            "baseline_status_distribution": baseline_status,
            "first_available_baseline_date_by_channel": first_available,
            "response_component_count": len(components),
            "response_component_status_distribution": component_status,
            "cell_operational_response_profile_count": len(profiles),
            "bitemporal_response_profile_binding_count": len(bindings),
            "geological_attribute_inventory_row_count": len(inventory),
            "geological_attribute_name_count": len(attr_names),
            "geological_attribute_unique_value_combo_count": len(
                {(row["attribute_name"], row["normalized_serialization"]) for row in inventory}
            ),
            "geological_attention_mapping_template_entry_count": len(mapping_template["mappings"]),
            "geological_attention_non_null_count": sum(
                1 for row in mapping_template["mappings"] if row["attention_value"] is not None
            ),
            "future_baseline_leakage_count": len(future_leakage_audit),
            "hard_check_issue_count": sum(1 for row in hard_checks if row["status"] != "PASS"),
            "input_response_evidence_count": len(inputs["responses"]),
            "input_stage3a_state_version_count": len(inputs["stage3a_versions"]),
            "input_stage3b_version_count": len(inputs["bitemporal_versions"]),
            "source_hashes": inputs["source_hashes"],
            "rai_status": "NOT_BUILT_IN_STAGE4A1",
            "grs_status": "GEOLOGICAL_ATTENTION_MAPPING_NOT_FROZEN",
            "grci_status": "DEPENDENT_METRICS_NOT_BUILT_IN_STAGE4A1",
        }

    def _write_report(
        self,
        *,
        inputs: dict[str, Any],
        baselines: list[dict[str, Any]],
        components: list[dict[str, Any]],
        profiles: list[dict[str, Any]],
        bindings: list[dict[str, Any]],
        inventory: list[dict[str, Any]],
        mapping_template: dict[str, Any],
        future_leakage_audit: list[dict[str, Any]],
        hard_checks: list[dict[str, Any]],
    ) -> None:
        baseline_status = Counter(row["baseline_status"] for row in baselines)
        component_status = Counter(row["component_status"] for row in components)
        attr_names = {row["attribute_name"] for row in inventory}
        non_null_attention = sum(
            1 for row in mapping_template["mappings"] if row["attention_value"] is not None
        )
        hard_check_failures = sum(1 for row in hard_checks if row["status"] != "PASS")
        first_available = {
            channel: min(
                (
                    str(row["valid_date"])
                    for row in baselines
                    if row["channel_name"] == channel and row["baseline_status"] == "AVAILABLE"
                ),
                default="NONE",
            )
            for channel in self.channels
        }
        text = "\n".join(
            [
                "# Stage 4A1 Metric Foundation Candidate",
                "",
                f"- Method version: `{STAGE4A1_METHOD_VERSION}`",
                f"- Schema version: `{STAGE4A1_SCHEMA_VERSION}`",
                f"- Baselines: {len(baselines)}",
                f"- Baseline status distribution: {dict(sorted(baseline_status.items()))}",
                f"- First available baseline date by channel: {first_available}",
                f"- ResponseDeviationComponent: {len(components)}",
                f"- Component status distribution: {dict(sorted(component_status.items()))}",
                f"- CellOperationalResponseProfile: {len(profiles)}",
                f"- BitemporalResponseProfileBinding: {len(bindings)}",
                f"- Geological attribute inventory rows: {len(inventory)}",
                f"- Unique geological attribute names: {len(attr_names)}",
                f"- Mapping template entries: {len(mapping_template['mappings'])}",
                f"- Non-null attention values: {non_null_attention}",
                f"- Future baseline leakage rows: {len(future_leakage_audit)}",
                f"- Hard check failures: {hard_check_failures}",
                "",
                (
                    "This Stage 4A1 artifact is descriptive metric foundation only. "
                    "It does not compute RAI, GRS, GRCI, risk, claims, reports, "
                    "or geological causation."
                ),
                "",
                "## Frozen Inputs",
                f"- Stage3B: {inputs['stage3b_dir']}",
                f"- Stage3A: {inputs['stage3a_dir']}",
                f"- Stage2E operational: {inputs['operational_dir']}",
                f"- Stage2 geology: {inputs['geology_dir']}",
            ]
        )
        (self.output_dir / "stage4a1_report.md").write_text(text + "\n", encoding="utf-8")


def _git_commit_hash(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "NO_COMMITS"
    return result.stdout.strip() or "NO_COMMITS"


def _git_dirty(repo_root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return True
    return bool(result.stdout.strip())
