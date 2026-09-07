"""Stage 7F-A deterministic sensitivity protocol materialization."""

# ruff: noqa: RUF001

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import yaml

METHOD_VERSION = "stage7f_sensitivity_protocol_v1"
SCHEMA_VERSION = "stage7f_sensitivity_protocol.v1"
GENERATED_AT = "2026-08-28T00:00:00+08:00"
OUTPUT_DIR = Path("artifacts/stage7f_sensitivity_protocol_v1")
AUDIT_ZIP = "stage7f_sensitivity_protocol_v1_audit.zip"
STAGE7E_FINAL_TAG = "stage7e-ablation-execution-v1.1a-final-machine-results"
STAGE7E_FINAL_COMMIT = "25df4be17edb89ad669d2a7255e65b6b5fa8acbc"

CONSTRUCTION_CONFIG = Path("configs/construction_state.yaml")
METRIC_FOUNDATION_CONFIG = Path("configs/metric_foundation.yaml")
STATE_METRIC_CONFIG = Path("configs/state_metric_definition_v1.yaml")
GEOLOGY_MAPPING_CONFIG = Path("configs/geological_attention_mapping_v1.yaml")
CLAIM_CONTRACT_CONFIG = Path("configs/claim_contract_v1.yaml")
STAGE3B_DIR = Path("artifacts/stage3b_bitemporal_epistemic_state_v1_1")
STAGE3A_DIR = Path("artifacts/stage3a_initial_epistemic_state_v1_1")
STAGE4_DIR = Path("artifacts/stage4_bitemporal_state_metrics_v1_1")
STAGE5C_DIR = Path("artifacts/stage5c_claim_expressibility_analysis_v1")

PARAMETER_TYPES = {
    "MODELING_RESOLUTION",
    "EMPIRICAL_SCALING",
    "DATA_SUFFICIENCY_REQUIREMENT",
    "SEMANTIC_DOMAIN_DEFINITION",
    "NON_TUNABLE_CONTRACT_RULE",
}


def build_stage7f_protocol(
    repo_root: Path,
    output_dir: Path = OUTPUT_DIR,
    *,
    create_audit_zip: bool = True,
) -> dict[str, Any]:
    """Materialize the preregistered Stage7F protocol without executing any arm."""

    root = repo_root.resolve()
    output = root / output_dir
    output.mkdir(parents=True, exist_ok=True)
    baseline = _load_baseline(root)
    inventory = _parameter_inventory(baseline)
    arms = _arm_manifest(baseline)
    dates = _monitored_dates(root)
    identity = _baseline_identity_audit(root)
    protocol = _protocol(baseline, arms, dates, identity)
    endpoints = _endpoint_registry()
    comparison = _comparison_key_spec()
    budget = _expected_execution_budget(arms)
    hard_rows = _hard_checks(root, baseline, inventory, arms, dates, identity, protocol)

    _write_outputs(
        output,
        baseline,
        inventory,
        arms,
        dates,
        identity,
        protocol,
        endpoints,
        comparison,
        budget,
        hard_rows,
    )
    failures = sum(row["status"] != "PASS" for row in hard_rows)
    if failures:
        raise RuntimeError(f"Stage7F-A hard checks failed: {failures}")
    _write_hashes(output)
    zip_path = _write_audit_zip(root, output) if create_audit_zip else None
    return {
        "parameter_count": sum(row["sensitivity_candidate"] for row in inventory),
        "arm_count": len(arms),
        "monitored_date_count": len(dates),
        "hard_failures": failures,
        "api_calls": 0,
        "llm_calls": 0,
        "audit_zip": str(zip_path) if zip_path else "",
    }


def _load_baseline(root: Path) -> dict[str, Any]:
    construction = _read_yaml(root / CONSTRUCTION_CONFIG)
    foundation = _read_yaml(root / METRIC_FOUNDATION_CONFIG)
    metrics = _read_yaml(root / STATE_METRIC_CONFIG)
    return {
        "cell_size_m": float(construction["cell_size_m"]),
        "minimum_baseline_sample_count": int(foundation["minimum_baseline_sample_count"]),
        "saturation_robust_z": float(metrics["rai"]["saturation_robust_z"]),
    }


def _parameter_inventory(baseline: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        _inventory_row(
            "CELL_SIZE_M",
            "ConstructionStateCell spatial width",
            "state/grid",
            baseline["cell_size_m"],
            CONSTRUCTION_CONFIG,
            "cell_size_m",
            "Spatial discretization width for the fixed alignment grid",
            "MODELING_RESOLUTION",
            True,
            "A genuine modeling resolution; 5 m and 20 m stress finer/coarser discretization.",
        ),
        _inventory_row(
            "RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT",
            "Minimum causal historical observations for RAI baseline",
            "metrics/operational_baseline",
            baseline["minimum_baseline_sample_count"],
            METRIC_FOUNDATION_CONFIG,
            "minimum_baseline_sample_count",
            "Historical data sufficiency gate measured in prior ResponseEvidence observations",
            "DATA_SUFFICIENCY_REQUIREMENT",
            True,
            "The implementation verifies a 30-observation baseline; 20/30/40 tests sufficiency.",
        ),
        _inventory_row(
            "RAI_SATURATION_ROBUST_Z",
            "RAI robust-deviation saturation divisor",
            "metrics/rai",
            baseline["saturation_robust_z"],
            STATE_METRIC_CONFIG,
            "rai.saturation_robust_z; src/tbm_twin/metrics/rai.py:21,168",
            "Maps robust z deviation to [0,1] attention by min(z / scale, 1)",
            "EMPIRICAL_SCALING",
            True,
            "The 3.0 divisor is an explicit empirical scaling constant; 2/3/4 is preregistered.",
        ),
        _inventory_row(
            "MAD_NORMAL_CONSISTENCY_FACTOR",
            "MAD robust-scale consistency factor",
            "metrics/operational_baseline",
            1.4826,
            METRIC_FOUNDATION_CONFIG,
            "mad_scale_factor",
            "Standard statistical calibration of MAD under normality",
            "EMPIRICAL_SCALING",
            False,
            "A standard estimator calibration constant, not a project-tuned design parameter.",
        ),
        _inventory_row(
            "IQR_NORMAL_CONSISTENCY_DIVISOR",
            "IQR robust-scale consistency divisor",
            "metrics/operational_baseline",
            1.349,
            METRIC_FOUNDATION_CONFIG,
            "iqr_scale_divisor",
            "Standard statistical calibration of IQR under normality",
            "EMPIRICAL_SCALING",
            False,
            "Changing it would alter estimator calibration rather than test a focal design choice.",
        ),
        _inventory_row(
            "GRS_ORDINAL_MAPPING",
            "Geological ordinal attention mapping",
            "metrics/grs",
            "frozen mapping table",
            GEOLOGY_MAPPING_CONFIG,
            "dimensions.*.values",
            "Expert-defined ordered geological semantics",
            "SEMANTIC_DOMAIN_DEFINITION",
            False,
            "Ordinal category meanings are frozen domain semantics, not fitted hyperparameters.",
        ),
        _inventory_row(
            "GRS_DIMENSION_AGGREGATION",
            "GRS dimension aggregation",
            "metrics/grs",
            "frozen maximum attention semantics",
            STATE_METRIC_CONFIG,
            "grs",
            "Defines geological attention semantics across evidence dimensions",
            "SEMANTIC_DOMAIN_DEFINITION",
            False,
            "Perturbation would redefine the metric rather than test parameter robustness.",
        ),
        _inventory_row(
            "GRCI_COUPLING_OPERATOR",
            "GRCI coupled-attention operator",
            "metrics/grci",
            "sqrt(RAI * GRS) when both available",
            STATE_METRIC_CONFIG,
            "grci",
            "Defines coupled attention and explicitly excludes probability semantics",
            "SEMANTIC_DOMAIN_DEFINITION",
            False,
            "Changing it would create a different metric; Stage7F does not redefine GRCI.",
        ),
        _inventory_row(
            "RAI_FAMILY_AGGREGATION",
            "RAI response-family aggregation",
            "metrics/rai",
            "frozen family/operator contract",
            STATE_METRIC_CONFIG,
            "rai.family_aggregation; rai.cross_family_aggregation",
            "Defines response-channel de-duplication and family attention semantics",
            "SEMANTIC_DOMAIN_DEFINITION",
            False,
            "It is part of the frozen RAI method definition, not a scalar tuning parameter.",
        ),
        _inventory_row(
            "FORECAST_NOT_OBSERVED",
            "FORECAST must not be promoted to OBSERVED",
            "claims/contract",
            True,
            CLAIM_CONTRACT_CONFIG,
            "epistemic constraints",
            "Permanent epistemic boundary",
            "NON_TUNABLE_CONTRACT_RULE",
            False,
            "A scientific validity rule cannot be treated as a sensitivity parameter.",
        ),
        _inventory_row(
            "UNKNOWN_NOT_NORMAL",
            "UNKNOWN or missing must not be rendered as normal",
            "claims/contract",
            True,
            CLAIM_CONTRACT_CONFIG,
            "unknown handling",
            "Permanent missingness boundary",
            "NON_TUNABLE_CONTRACT_RULE",
            False,
            "Removing this rule would alter admissibility, not test robustness.",
        ),
        _inventory_row(
            "CLAIM_ROLE_RESTRICTIONS",
            "Claim state-role restrictions",
            "claims/contract",
            "frozen",
            CLAIM_CONTRACT_CONFIG,
            "claim_types.*.allowed_roles",
            "Defines where each typed Claim is admissible",
            "NON_TUNABLE_CONTRACT_RULE",
            False,
            "Role restrictions are frozen contract semantics and remain identical in every arm.",
        ),
        _inventory_row(
            "BITEMPORAL_KNOWLEDGE_BOUNDARY",
            "As-of knowledge-state mechanism",
            "state/bitemporal",
            "enabled",
            Path("src/tbm_twin/bitemporal/revision_builder.py"),
            "knowledge-time eligibility and revision lineage",
            "Prevents later evidence from contaminating earlier knowledge states",
            "NON_TUNABLE_CONTRACT_RULE",
            False,
            "Stage7D already evaluates this mechanism; disabling it is outside Stage7F.",
        ),
        _inventory_row(
            "GRID_ORIGIN_M",
            "Alignment grid origin",
            "state/grid",
            "frozen alignment origin",
            CONSTRUCTION_CONFIG,
            "grid_origin_m",
            "Identity anchor for deterministic cell geometry",
            "SEMANTIC_DOMAIN_DEFINITION",
            False,
            "Moving the origin changes spatial identity and is not a resolution perturbation.",
        ),
        _inventory_row(
            "POINT_BOUNDARY_POLICY",
            "Point-to-cell boundary policy",
            "state/linking",
            "frozen",
            CONSTRUCTION_CONFIG,
            "point_boundary_policy",
            "Defines deterministic ownership at cell boundaries",
            "SEMANTIC_DOMAIN_DEFINITION",
            False,
            "Changing boundary ownership changes spatial semantics rather than parameter scale.",
        ),
        _inventory_row(
            "MONITORED_DATE_CORPUS",
            "Full PLC-monitored construction-date corpus",
            "evaluation/stage7f",
            "91 monitored dates spanning 2023-09-15 to 2023-12-30",
            STAGE3A_DIR / "daily_construction_states.jsonl",
            "one target_date per DailyConstructionState",
            "Evaluation population",
            "SEMANTIC_DOMAIN_DEFINITION",
            False,
            "The full observed corpus is fixed and is not sampled or tuned per arm.",
        ),
    ]
    if {row["parameter_type"] for row in rows} - PARAMETER_TYPES:
        raise ValueError("Unknown Stage7F parameter type")
    return rows


def _inventory_row(
    parameter_id: str,
    parameter_name: str,
    module: str,
    current_value: Any,
    source_file: Path,
    source_line_or_config_path: str,
    parameter_role: str,
    parameter_type: str,
    sensitivity_candidate: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        "parameter_id": parameter_id,
        "parameter_name": parameter_name,
        "module": module,
        "current_value": current_value,
        "source_file": source_file.as_posix(),
        "source_line_or_config_path": source_line_or_config_path,
        "parameter_role": parameter_role,
        "parameter_type": parameter_type,
        "sensitivity_candidate": sensitivity_candidate,
        "reason": reason,
    }


def _arm_manifest(baseline: dict[str, Any]) -> list[dict[str, Any]]:
    baseline_vector = {
        "CELL_SIZE_M": baseline["cell_size_m"],
        "RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT": baseline["minimum_baseline_sample_count"],
        "RAI_SATURATION_ROBUST_Z": baseline["saturation_robust_z"],
    }
    specs = [
        (
            "stage7f_baseline",
            "BASELINE_VECTOR",
            baseline_vector,
            True,
            "",
            baseline_vector,
            "STAGE3A",
            "STAGE5C",
        ),
        (
            "cell_size_m_5",
            "CELL_SIZE_M",
            5.0,
            False,
            "cell_size_m",
            baseline["cell_size_m"],
            "STAGE3A",
            "STAGE5C",
        ),
        (
            "cell_size_m_20",
            "CELL_SIZE_M",
            20.0,
            False,
            "cell_size_m",
            baseline["cell_size_m"],
            "STAGE3A",
            "STAGE5C",
        ),
        (
            "rai_history_min_samples_20",
            "RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT",
            20,
            False,
            "minimum_baseline_sample_count",
            baseline["minimum_baseline_sample_count"],
            "STAGE4A1",
            "STAGE5C",
        ),
        (
            "rai_history_min_samples_40",
            "RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT",
            40,
            False,
            "minimum_baseline_sample_count",
            baseline["minimum_baseline_sample_count"],
            "STAGE4A1",
            "STAGE5C",
        ),
        (
            "rai_saturation_robust_z_2",
            "RAI_SATURATION_ROBUST_Z",
            2.0,
            False,
            "rai.saturation_robust_z",
            baseline["saturation_robust_z"],
            "STAGE4A2",
            "STAGE5C",
        ),
        (
            "rai_saturation_robust_z_4",
            "RAI_SATURATION_ROBUST_Z",
            4.0,
            False,
            "rai.saturation_robust_z",
            baseline["saturation_robust_z"],
            "STAGE4A2",
            "STAGE5C",
        ),
    ]
    rows = []
    for arm_id, parameter_id, value, is_baseline, path, baseline_value, start, end in specs:
        override = {} if is_baseline else {parameter_id: value}
        semantic = {
            "arm_id": arm_id,
            "baseline_vector": baseline_vector,
            "override": override,
            "pipeline_start": start,
            "pipeline_end": end,
        }
        rows.append(
            {
                "arm_id": arm_id,
                "parameter_id": parameter_id,
                "parameter_value": _canonical(value),
                "is_baseline": is_baseline,
                "changed_config_path": path,
                "baseline_value": _canonical(baseline_value),
                "all_other_parameters_frozen": True,
                "expected_pipeline_start_stage": start,
                "expected_pipeline_end_stage": end,
                "llm_required": False,
                "api_required": False,
                "arm_hash": _stable_hash(semantic),
            }
        )
    return rows


def _monitored_dates(root: Path) -> list[str]:
    dates: set[str] = set()
    path = root / STAGE3A_DIR / "daily_construction_states.jsonl"
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                dates.add(str(json.loads(line)["target_date"]))
    return sorted(dates)


def _baseline_identity_audit(root: Path) -> list[dict[str, Any]]:
    bindings = [
        ("construction_state_config", CONSTRUCTION_CONFIG, "STAGE7E_FINAL_GIT_TAG"),
        ("metric_foundation_config", METRIC_FOUNDATION_CONFIG, "STAGE7E_FINAL_GIT_TAG"),
        ("state_metric_config", STATE_METRIC_CONFIG, "STAGE7E_FINAL_GIT_TAG"),
        ("geology_mapping_config", GEOLOGY_MAPPING_CONFIG, "STAGE7E_FINAL_GIT_TAG"),
        ("claim_contract_config", CLAIM_CONTRACT_CONFIG, "STAGE7E_FINAL_GIT_TAG"),
        (
            "stage3b_freeze_manifest",
            STAGE3B_DIR / "freeze_manifest.json",
            "FROZEN_FILE_HASH_MANIFEST",
        ),
        (
            "stage4_freeze_manifest",
            STAGE4_DIR / "freeze_manifest.json",
            "FROZEN_FILE_HASH_MANIFEST",
        ),
        (
            "stage5c_method_version",
            STAGE5C_DIR / "method_version.json",
            "FROZEN_FILE_HASH_MANIFEST",
        ),
    ]
    rows = []
    for identity_name, path, reference_basis in bindings:
        expected = (
            _git_file_sha256(root, STAGE7E_FINAL_TAG, path)
            if reference_basis == "STAGE7E_FINAL_GIT_TAG"
            else _expected_from_file_hash_manifest(root, path)
        )
        actual = _sha256_file(root / path)
        rows.append(
            {
                "identity_name": identity_name,
                "identity_type": "CONFIG" if path.parts[0] == "configs" else "FROZEN_MANIFEST",
                "path": path.as_posix(),
                "expected_sha256": expected,
                "actual_sha256": actual,
                "status": "PASS" if expected == actual else "FAIL",
                "reference_basis": reference_basis,
                "notes": (
                    "Tracked configs bind to the final Stage7E tag; ignored frozen artifacts "
                    "bind to their self-contained file_hashes.sha256 manifest."
                ),
            }
        )
    return rows


def _protocol(
    baseline: dict[str, Any],
    arms: list[dict[str, Any]],
    dates: list[str],
    identity: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "status": "FROZEN_PROTOCOL_NOT_EXECUTED",
        "scientific_question": (
            "Whether principal deterministic pipeline conclusions depend strongly on a small "
            "set of human-selected modeling parameters"
        ),
        "design": "ONE_FACTOR_AT_A_TIME",
        "baseline": baseline,
        "parameters": [
            {
                "parameter_id": "CELL_SIZE_M",
                "values": [5.0, 10.0, 20.0],
                "baseline": 10.0,
                "selection_basis": "symmetric finer/coarser spatial resolution around 10 m",
            },
            {
                "parameter_id": "RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT",
                "values": [20, 30, 40],
                "baseline": 30,
                "selection_basis": "verified prior-observation sufficiency gate around 30 samples",
            },
            {
                "parameter_id": "RAI_SATURATION_ROBUST_Z",
                "values": [2.0, 3.0, 4.0],
                "baseline": 3.0,
                "selection_basis": (
                    "one robust-z unit on either side of the empirical 3.0 saturation divisor"
                ),
            },
        ],
        "unique_execution_arm_count": len(arms),
        "full_factorial_design": False,
        "result_dependent_arm_selection": False,
        "corpus": {
            "definition": "full PLC-monitored construction-date corpus",
            "date_count": len(dates),
            "start_date": dates[0],
            "end_date": dates[-1],
            "calendar_gaps_present": True,
            "dates": dates,
        },
        "interpretation": {
            "mode": "DESCRIPTIVE_ROBUSTNESS_WITHOUT_PROGRAMMATIC_PASS_THRESHOLD",
            "p_value_stability_claim": False,
            "change_is_automatically_failure": False,
        },
        "frozen_semantics": [
            "GRS ordinal mappings",
            "GRCI definition and non-probability meaning",
            "Claim Contract and role restrictions",
            "FORECAST is not OBSERVED",
            "UNKNOWN is not NORMAL",
            "bitemporal knowledge boundary",
        ],
        "baseline_identity_audit_hash": _stable_hash(identity),
        "api_calls": 0,
        "llm_calls": 0,
        "sensitivity_outcomes_generated": False,
    }


def _endpoint_registry() -> dict[str, Any]:
    return {
        "method_version": METHOD_VERSION,
        "interpretation": "DESCRIPTIVE_ONLY_NO_AUTOMATIC_PASS_THRESHOLD",
        "common": [
            "monitored_date_count",
            "RAI_availability_rate",
            "GRS_availability_rate",
            "GRCI_availability_rate",
            "EXPRESSIBLE_rate",
            "ABSTAIN_rate",
            "ABSTAIN_reason_distribution",
        ],
        "cell_size": {
            "resolution_dependent_counts": [
                "cell_count",
                "daily_review_cell_count",
                "forward_attention_cell_count",
                "claim_opportunity_count",
                "expressible_count",
                "abstain_count",
            ],
            "normalized_counts": [
                "claim_opportunities_per_day",
                "expressible_per_day",
                "abstain_per_day",
                "claim_opportunities_per_100m",
                "expressible_per_100m",
                "abstain_per_100m",
            ],
            "date_role_metrics": {
                "metrics": ["RAI", "GRS", "GRCI"],
                "summaries": ["median", "max"],
                "pairing": "same valid_date and role with metric available in both arms",
                "statistics": [
                    "median_absolute_difference",
                    "IQR_absolute_difference",
                    "Spearman_rank_correlation",
                ],
            },
            "claim_stability": {
                "layer_a_key": ["valid_date", "claim_type", "decision"],
                "layer_b_key": [
                    "valid_date",
                    "claim_type",
                    "state_role",
                    "epistemic_status",
                    "decision",
                ],
            },
        },
        "rai_history": {
            "endpoints": [
                "RAI_availability",
                "RAI_value_stability",
                "GRCI_availability",
                "GRCI_value_stability",
                "Claim_decision_transitions",
            ],
            "hard_invariant": "GRS identity unchanged",
        },
        "rai_saturation": {
            "endpoints": [
                "RAI_rank_stability",
                "RAI_absolute_value_shift",
                "GRCI_shift",
                "RAI_related_Claim_availability",
                "RAI_related_Claim_decision_changes",
            ],
            "hard_invariants": [
                "cell structure unchanged",
                "geological evidence bindings unchanged",
                "GRS unchanged",
                "Claim Contract unchanged",
            ],
        },
    }


def _comparison_key_spec() -> dict[str, Any]:
    return {
        "method_version": METHOD_VERSION,
        "cell_size_identity_warning": "cell_id and claim_id are resolution-dependent",
        "metric_pair_key": ["valid_date", "state_role", "metric_name", "summary_statistic"],
        "metric_pair_eligibility": "metric available in baseline and comparison arm",
        "claim_layer_a_key": ["valid_date", "claim_type", "decision"],
        "claim_layer_b_key": [
            "valid_date",
            "claim_type",
            "state_role",
            "epistemic_status",
            "decision",
        ],
        "prohibited_primary_keys": ["cell_id", "claim_id", "state_version_id"],
        "raw_cell_count_interpretation": "RESOLUTION_DEPENDENT_NOT_DIRECT_STABILITY_EVIDENCE",
    }


def _expected_execution_budget(arms: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "unique_arm_count": len(arms),
        "baseline_arm_count": 1,
        "alternative_arm_count": len(arms) - 1,
        "new_deterministic_pipeline_runs_expected": len(arms) - 1,
        "frozen_baseline_reuse_count": 1,
        "full_factorial_arm_count_if_prohibited_design_were_used": 27,
        "full_factorial_planned": False,
        "api_calls": 0,
        "llm_calls": 0,
        "stage7f_a_pipeline_runs_executed": 0,
        "stage7f_a_outcomes_generated": 0,
    }


def _implementation_parameter_usage(root: Path) -> dict[str, bool]:
    state_grid = (root / "src/tbm_twin/state/grid.py").read_text(encoding="utf-8")
    foundation = (root / "src/tbm_twin/metrics/metric_foundation_builder.py").read_text(
        encoding="utf-8"
    )
    baseline = (root / "src/tbm_twin/metrics/operational_baseline.py").read_text(encoding="utf-8")
    rai = (root / "src/tbm_twin/metrics/rai.py").read_text(encoding="utf-8")
    return {
        "cell_size_m_used_by_grid": "cell_size=config.cell_size_m" in state_grid,
        "minimum_sample_count_loaded": (
            'yaml_config["minimum_baseline_sample_count"]' in foundation
        ),
        "minimum_sample_count_gates_history": "len(values) < min_sample_count" in baseline,
        "rai_saturation_constant_verified": "RAI_SATURATION_ROBUST_Z = 3.0" in rai,
        "rai_saturation_formula_verified": ("raw_deviation / RAI_SATURATION_ROBUST_Z" in rai),
    }


def _hard_checks(
    root: Path,
    baseline: dict[str, Any],
    inventory: list[dict[str, Any]],
    arms: list[dict[str, Any]],
    dates: list[str],
    identity: list[dict[str, Any]],
    protocol: dict[str, Any],
) -> list[dict[str, str]]:
    candidate_types = {row["parameter_type"] for row in inventory if row["sensitivity_candidate"]}
    nonbaseline = [row for row in arms if not row["is_baseline"]]
    tag_commit = _git(root, "rev-parse", STAGE7E_FINAL_TAG)
    implementation = _implementation_parameter_usage(root)
    checks: list[tuple[str, bool, Any]] = [
        ("stage7e_final_tag_unchanged", tag_commit == STAGE7E_FINAL_COMMIT, tag_commit),
        ("baseline_config_identified", len(baseline) == 3, baseline),
        ("cell_baseline_exact_10m", baseline["cell_size_m"] == 10.0, baseline["cell_size_m"]),
        (
            "rai_history_baseline_exact_30_observations",
            baseline["minimum_baseline_sample_count"] == 30,
            baseline["minimum_baseline_sample_count"],
        ),
        (
            "rai_saturation_baseline_exact_3",
            baseline["saturation_robust_z"] == 3.0,
            baseline["saturation_robust_z"],
        ),
        (
            "candidate_parameters_sourced_from_real_config",
            candidate_types
            == {"MODELING_RESOLUTION", "DATA_SUFFICIENCY_REQUIREMENT", "EMPIRICAL_SCALING"},
            sorted(candidate_types),
        ),
        (
            "candidate_parameters_consumed_by_implementation",
            all(implementation.values()),
            implementation,
        ),
        (
            "semantic_and_contract_rules_not_tunable",
            not any(
                row["sensitivity_candidate"]
                for row in inventory
                if row["parameter_type"]
                in {
                    "SEMANTIC_DOMAIN_DEFINITION",
                    "NON_TUNABLE_CONTRACT_RULE",
                }
            ),
            0,
        ),
        (
            "claim_contract_unchanged",
            all(
                row["status"] == "PASS"
                for row in identity
                if row["path"] == CLAIM_CONTRACT_CONFIG.as_posix()
            ),
            0,
        ),
        ("api_calls_zero", protocol["api_calls"] == 0, protocol["api_calls"]),
        ("llm_calls_zero", protocol["llm_calls"] == 0, protocol["llm_calls"]),
        ("result_dependent_selection_absent", not protocol["result_dependent_arm_selection"], 0),
        ("ofat_design_exact", protocol["design"] == "ONE_FACTOR_AT_A_TIME", protocol["design"]),
        (
            "all_non_target_parameters_frozen",
            all(row["all_other_parameters_frozen"] for row in arms),
            len(arms),
        ),
        (
            "each_alternative_changes_one_parameter",
            all(row["parameter_id"] != "BASELINE_VECTOR" for row in nonbaseline),
            len(nonbaseline),
        ),
        ("unique_arm_count_exact_7", len(arms) == 7, len(arms)),
        ("arm_hashes_unique", len({row["arm_hash"] for row in arms}) == len(arms), len(arms)),
        (
            "monitored_date_corpus_exact_91",
            len(dates) == 91 and dates[0] == "2023-09-15" and dates[-1] == "2023-12-30",
            f"{len(dates)}:{dates[0]}:{dates[-1]}",
        ),
        (
            "monitored_dates_have_calendar_gaps",
            len(dates) < (_date_ordinal(dates[-1]) - _date_ordinal(dates[0]) + 1),
            "calendar_gaps_present",
        ),
        (
            "baseline_identity_all_match",
            all(row["status"] == "PASS" for row in identity),
            len(identity),
        ),
        ("sensitivity_outcomes_not_generated", not protocol["sensitivity_outcomes_generated"], 0),
        ("full_factorial_not_planned", not protocol["full_factorial_design"], 0),
    ]
    return [
        {
            "check_name": name,
            "status": "PASS" if passed else "FAIL",
            "details": _canonical(details),
        }
        for name, passed, details in checks
    ]


def _write_outputs(
    output: Path,
    baseline: dict[str, Any],
    inventory: list[dict[str, Any]],
    arms: list[dict[str, Any]],
    dates: list[str],
    identity: list[dict[str, Any]],
    protocol: dict[str, Any],
    endpoints: dict[str, Any],
    comparison: dict[str, Any],
    budget: dict[str, Any],
    hard_rows: list[dict[str, Any]],
) -> None:
    (output / "README.md").write_text(_readme(), encoding="utf-8")
    (output / "STAGE7F_PARAMETER_RATIONALE.md").write_text(_rationale(), encoding="utf-8")
    _write_csv(output / "stage7f_parameter_inventory.csv", inventory)
    _write_json(output / "stage7f_sensitivity_protocol.json", protocol)
    _write_csv(output / "stage7f_arm_manifest.csv", arms)
    _write_csv(output / "stage7f_baseline_identity_audit.csv", identity)
    _write_json(output / "stage7f_endpoint_registry.json", endpoints)
    _write_json(output / "stage7f_comparison_key_spec.json", comparison)
    _write_json(output / "stage7f_expected_execution_budget.json", budget)
    _write_csv(output / "hard_check.csv", hard_rows)
    method = {
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "stage7e_final_commit": STAGE7E_FINAL_COMMIT,
        "stage7e_final_tag": STAGE7E_FINAL_TAG,
        "baseline": baseline,
        "design": "ONE_FACTOR_AT_A_TIME",
        "corpus_date_count": len(dates),
        "api_calls": 0,
        "llm_calls": 0,
    }
    _write_json(output / "method_version.json", method)
    _write_json(
        output / "freeze_manifest.json",
        {
            **method,
            "status": "FROZEN_PROTOCOL_NOT_EXECUTED",
            "counts": {
                "inventory_parameters": len(inventory),
                "sensitivity_parameters": sum(row["sensitivity_candidate"] for row in inventory),
                "unique_arms": len(arms),
                "baseline_arms": sum(row["is_baseline"] for row in arms),
                "alternative_arms": sum(not row["is_baseline"] for row in arms),
                "monitored_dates": len(dates),
            },
            "baseline_identity_hash": _stable_hash(identity),
            "arm_manifest_hash": _stable_hash(arms),
            "protocol_hash": _stable_hash(protocol),
            "hard_check_failure_count": sum(row["status"] != "PASS" for row in hard_rows),
            "sensitivity_outcomes_generated": 0,
            "pipeline_runs_executed": 0,
        },
    )


def _readme() -> str:
    return """# Stage7F-A 参数敏感性与稳健性实验协议

本目录冻结参数盘点、OFAT 实验臂、基线身份、比较键、评价端点和未来执行预算。
本阶段没有执行任何敏感性实验，没有计算相关系数、指标漂移或 Claim 变化，也没有调用
LLM/API。研究总体是 2023-09-15 至 2023-12-30 范围内有 PLC 记录的 91 个施工日期；
该总体包含日历空档。空间尺度改变后，cell/claim 原始数量属于分辨率依赖结果，不能直接
解释为方法不稳定，主要比较采用日期/角色聚合、规范化计数和语义 Claim profile。

冻结的三个参数为 5/10/20 m cell 尺度、20/30/40 个历史观测样本要求、2/3/4 robust-z
饱和尺度。一个共享 baseline 与六个单参数替代臂组成 7 个唯一 arm。GRS ordinal 映射、
GRCI 定义、双时间知识边界和 Claim Contract 在所有 arm 中保持不变。
"""


def _rationale() -> str:
    return """# Stage7F 参数选择依据

## 科学目的

Stage7F 检查冻结确定性 pipeline 的主要描述是否依赖少数人为建模选择。它不是参数调优，
不寻找“最好”设置，也不根据输出追加实验值。Stage7F-A 仅预注册协议，Stage7F-B 才可按
冻结 manifest 执行。

## 1. ConstructionStateCell 尺度：5 / 10 / 20 m

真实 baseline 来自 `configs/construction_state.yaml` 的 `cell_size_m = 10.0`。5 m 与 20 m
分别提供更细和更粗的二倍分辨率扰动。cell identity、raw cell count 与依赖 cell 的 Claim
数量会自然改变，因此它们是 resolution-dependent counts；跨 arm 的主要比较使用日期/角色
摘要、每日期或每 100 m 规范化计数，以及不依赖 cell/claim ID 的语义聚合键。

## 2. RAI 历史充分性：20 / 30 / 40 observations

真实参数是 `minimum_baseline_sample_count = 30`，代码按目标日期之前的历史
ResponseEvidence 观测数量判断基线是否充分；它不是 30 日窗口。20/40 是围绕 30 的固定
样本充分性压力测试。该 arm 保持 10 m cell、地质证据、GRS/GRCI 公式与 Claim Contract
不变，并将 GRS identity unchanged 设为硬不变量。

## 3. RAI 饱和尺度：2 / 3 / 4 robust z

真实公式将非负 robust deviation 按 `min(z / 3.0, 1.0)` 映射为 attention。3.0 是明确的
经验 scaling，而不是物理常数。协议选择 2/3/4，而不是在结果后从 2.5/3/3.5 与 2/3/4
之间择优：相对 baseline 各移动一个完整 robust-z 单位，形成方向对称、解释清楚且足够宽的
压力测试。该 arm 只改变 RAI scaling，cell、地质绑定、GRS 与 Claim Contract 必须一致。

## 排除项

- GRS 的 0.25/0.50/0.75/1.00 是人工冻结的 ordinal domain semantics，不是拟合超参数。
- GRCI 是 coupled attention 而非概率；改变算子会定义新指标。
- FORECAST/OBSERVED、UNKNOWN handling、role restriction 是不可调 Claim Contract 规则。
- 双时间机制已由 Stage7D 单独验证，本轮不设置 on/off arm。
- MAD/IQR consistency constants 是稳健统计尺度校准，不作为项目参数调优。

## 解释规则

只做描述性 robustness。报告 median absolute difference、absolute difference IQR 与 Spearman
rank correlation；不能只给 Pearson，也不使用任意 p-value 或固定 Spearman 阈值自动宣布
PASS。变化并不自动等于失败，应区分合理的 resolution dependence 与工程 attention pattern、
availability、Claim admissibility 的实质变化。
"""


def _write_audit_zip(root: Path, output: Path) -> Path:
    zip_path = root / AUDIT_ZIP
    if zip_path.exists():
        zip_path.unlink()
    extra = [
        root / "src/tbm_twin/evaluation/stage7f_protocol.py",
        root / "scripts/build_stage7f_sensitivity_protocol.py",
        root / "tests/unit/test_stage7f_sensitivity_protocol.py",
    ]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.iterdir()):
            if path.is_file():
                archive.write(path, path.relative_to(root))
        for path in extra:
            archive.write(path, path.relative_to(root))
    return zip_path


def _write_hashes(output: Path) -> None:
    rows = []
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name != "file_hashes.sha256":
            rows.append(f"{_sha256_file(path)}  {path.name}")
    (output / "file_hashes.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"CSV requires schema rows: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping in {path}")
    return value


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_file_sha256(root: Path, ref: str, path: Path) -> str:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path.as_posix()}"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def _expected_from_file_hash_manifest(root: Path, path: Path) -> str:
    manifest = root / path.parent / "file_hashes.sha256"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2 and Path(parts[1].strip()).name == path.name:
            return parts[0]
    raise ValueError(f"No hash for {path.name} in {manifest}")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _date_ordinal(value: str) -> int:
    from datetime import date

    return date.fromisoformat(value).toordinal()
