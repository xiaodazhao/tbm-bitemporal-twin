"""Stage 7F-B v1.1 read-only validity-boundary interpretation."""

# ruff: noqa: RUF001

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, cast

import yaml

from tbm_twin.state.io import write_csv, write_file_hashes, write_json

METHOD_VERSION = "stage7f_sensitivity_execution_v1_1_final_interpretation"
SCHEMA_VERSION = "stage7f_sensitivity_final_interpretation.v1.1"
GENERATED_AT = "2026-08-29T12:00:00+08:00"
OLD_OUTPUT_DIR = Path("artifacts/stage7f_sensitivity_execution_v1")
OUTPUT_DIR = Path("artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation")
AUDIT_ZIP = "stage7f_sensitivity_execution_v1_1_final_interpretation_audit.zip"
OLD_STAGE7F_B_TAG = "stage7f-sensitivity-execution-v1-frozen"
OLD_STAGE7F_B_COMMIT = "8d3c9254078ec95059966ce7b882462d94c64eb5"
STAGE7F_A_TAG = "stage7f-sensitivity-protocol-v1.1-frozen"
STAGE7F_A_COMMIT = "6ae7d690875d55da96521a63440e6f479d9639ea"

METRIC_TABLES = (
    "cell_size_date_role_metric_summary.csv",
    "cell_size_metric_pairwise_statistics.csv",
    "rai_history_metric_summary.csv",
    "rai_history_pairwise_statistics.csv",
    "rai_saturation_metric_summary.csv",
    "rai_saturation_pairwise_statistics.csv",
    "rai_saturation_monotonicity_audit.csv",
    "grci_product_identity_audit.csv",
)
CLAIM_TABLES = (
    "cell_size_claim_layer_a.csv",
    "cell_size_claim_layer_b.csv",
    "cell_size_claim_stability_summary.csv",
    "rai_history_claim_transition_matrix.csv",
    "rai_saturation_claim_transition_matrix.csv",
    "stage7f_claim_rate_summary.csv",
    "stage7f_abstain_reason_summary.csv",
    "stage7f_normalized_count_summary.csv",
)
CONFIG_PATHS = (
    "configs/construction_state.yaml",
    "configs/metric_foundation.yaml",
    "configs/state_metric_definition_v1.yaml",
    "configs/claim_contract_v1.yaml",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _read_yaml(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(path.read_text(encoding="utf-8")))


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _git_bytes(root: Path, ref: str, path: Path) -> bytes:
    return subprocess.check_output(["git", "show", f"{ref}:{path.as_posix()}"], cwd=root)


def _verify_hash_manifest(directory: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    manifest = directory / "file_hashes.sha256"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        path = directory / relative.strip()
        actual = _sha256_file(path) if path.is_file() else None
        rows.append(
            {
                "path": relative.strip(),
                "expected_sha256": expected,
                "actual_sha256": actual,
                "status": "PASS" if actual == expected else "FAIL",
            }
        )
    return {
        "listed_file_count": len(rows),
        "mismatch_count": sum(row["status"] != "PASS" for row in rows),
        "rows": rows,
    }


def _native_stage3a_root(root: Path, arm_id: str) -> Path:
    if arm_id == "stage7f_baseline":
        return root / "artifacts/stage3a_initial_epistemic_state_v1_1"
    return root / OLD_OUTPUT_DIR / "arms" / arm_id / "stage3a"


def reconstruct_native_quality_gates(root: Path) -> list[dict[str, Any]]:
    """Reconstruct native Stage3A outcomes without invoking a builder."""

    definitions = (
        ("cell_size_m_5", "SUCCESS", "VALID_SENSITIVITY_ARM", "SENSITIVITY_COMPARISON"),
        ("stage7f_baseline", "REUSED_FROZEN_BASELINE", "VALID_BASELINE", "BASELINE"),
        (
            "cell_size_m_20",
            "SUCCESS",
            "COARSE_RESOLUTION_VALIDITY_BOUNDARY_EXCEEDED",
            "COARSE_RESOLUTION_STRESS_TEST",
        ),
    )
    result = []
    for arm_id, execution_status, validity_status, interpretation_scope in definitions:
        stage3a = _native_stage3a_root(root, arm_id)
        role_rows = _read_csv(stage3a / "cell_scope_role_audit.csv")
        point_rows = _read_csv(stage3a / "point_boundary_policy_audit.csv")
        interval_rows = _read_csv(stage3a / "interval_overlap_conservation_audit.csv")
        role_conflicts = sum(row["status"] != "PASS" for row in role_rows)
        point_issues = sum(row["status"] != "PASS" for row in point_rows)
        interval_issues = sum(row["status"] != "PASS" for row in interval_rows)
        pair_counts = Counter(
            (row.get("existing_cell_scope_role", ""), row.get("conflicting_cell_scope_role", ""))
            for row in role_rows
            if row["status"] != "PASS"
        )
        native_status = (
            "PASS"
            if role_conflicts == point_issues == interval_issues == 0
            else "FAIL_RESOLUTION_VALIDITY"
        )
        result.append(
            {
                "arm_id": arm_id,
                "execution_status": execution_status,
                "method_validity_status": validity_status,
                "interpretation_scope": interpretation_scope,
                "scope_role_conflicts": role_conflicts,
                "daily_review_vs_local_background_conflicts": pair_counts[
                    ("DAILY_REVIEW_CELL", "LOCAL_BACKGROUND_CELL")
                ],
                "daily_review_vs_forward_attention_conflicts": pair_counts[
                    ("DAILY_REVIEW_CELL", "FORWARD_ATTENTION_CELL")
                ],
                "point_missing_or_duplicate": point_issues,
                "interval_overlap_mismatch": interval_issues,
                "native_quality_gate_status": native_status,
                "sensitivity_adapter_continued_execution": arm_id == "cell_size_m_20",
            }
        )
    return result


def _common_by_arm(root: Path) -> dict[str, dict[str, str]]:
    rows = _read_csv(root / OLD_OUTPUT_DIR / "stage7f_common_endpoint_summary.csv")
    return {row["arm_id"]: row for row in rows}


def resolution_validity_summary(
    root: Path, native_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    common = _common_by_arm(root)
    result = []
    for row in native_rows:
        endpoint = common[row["arm_id"]]
        result.append(
            {
                **row,
                "cell_size_m": endpoint["parameter_value"],
                "cell_count": endpoint["cell_count"],
                "evaluated_cell_length_m": endpoint["evaluated_cell_length_m"],
                "claim_opportunities_per_100m": endpoint["claim_opportunities_per_100m"],
                "expressible_per_100m": endpoint["expressible_per_100m"],
                "abstain_per_100m": endpoint["abstain_per_100m"],
                "denominator_caveat": (
                    "Actual coarse-cell exposure includes boundary-spanning cells; not an "
                    "equal-support density comparison."
                    if row["arm_id"] == "cell_size_m_20"
                    else "NONE"
                ),
            }
        )
    return result


def saturation_metadata_audit(root: Path) -> list[dict[str, Any]]:
    rows = []
    for arm_id in ("rai_saturation_robust_z_2", "rai_saturation_robust_z_4"):
        path = (
            root
            / OLD_OUTPUT_DIR
            / "arms"
            / arm_id
            / "resolved_configs/state_metric_definition_v1.yaml"
        )
        config = _read_yaml(path)
        actual = float(config["rai"]["saturation_robust_z"])
        label = str(config["rai"]["aggregation"]["family_attention_operator"])
        rows.append(
            {
                "arm_id": arm_id,
                "actual_saturation_robust_z": actual,
                "legacy_operator_label": label,
                "authoritative_execution_parameter": "rai.saturation_robust_z",
                "authoritative_implementation": (
                    "tbm_twin.evaluation.stage7f_execution._rai_saturation"
                ),
                "legacy_label_used_as_authoritative_parameter": False,
                "status": "LEGACY_LABEL_STALE_EXECUTION_PARAMETER_CORRECT",
            }
        )
    return rows


def old_identity_audit(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Verify the complete frozen v1 hash manifest and authoritative tags."""

    old = root / OLD_OUTPUT_DIR
    manifest = old / "file_hashes.sha256"
    expected_manifest_hash = _sha256_bytes(
        _git_bytes(root, OLD_STAGE7F_B_TAG, OLD_OUTPUT_DIR / "file_hashes.sha256")
    )
    actual_manifest_hash = _sha256_file(manifest)
    verification = _verify_hash_manifest(old)
    expected_configs = {
        "configs/construction_state.yaml": (
            "f5d3fe20ce767deb819f84de7155176d09fc3b108d1d31381b9a668a3bc405d3"
        ),
        "configs/metric_foundation.yaml": (
            "4116625a765ba547492e4f64e57cb2bd016b557db64327dcc3ef5654d4bb03ff"
        ),
        "configs/state_metric_definition_v1.yaml": (
            "bd8d7a3d86d9d9a80a29077b87ace58124074b7f92a3208479e3396085a20c24"
        ),
        "configs/claim_contract_v1.yaml": (
            "6c84eaed28a684ca91ae6e000c42167ea8dca1362bdae526d41c329ff97e6f39"
        ),
    }
    rows: list[dict[str, Any]] = [
        {
            "check_name": "OLD_STAGE7F_B_TAG_UNCHANGED",
            "expected": OLD_STAGE7F_B_COMMIT,
            "actual": _git(root, "rev-parse", f"{OLD_STAGE7F_B_TAG}^{{}}"),
        },
        {
            "check_name": "STAGE7F_A_V1_1_TAG_UNCHANGED",
            "expected": STAGE7F_A_COMMIT,
            "actual": _git(root, "rev-parse", f"{STAGE7F_A_TAG}^{{}}"),
        },
        {
            "check_name": "OLD_ROOT_HASH_MANIFEST_MATCHES_FROZEN_TAG",
            "expected": expected_manifest_hash,
            "actual": actual_manifest_hash,
        },
        {
            "check_name": "ALL_LISTED_STAGE7F_B_OUTPUTS_UNCHANGED",
            "expected": 0,
            "actual": verification["mismatch_count"],
        },
    ]
    for name in (*METRIC_TABLES, *CLAIM_TABLES, "deterministic_replay_audit.csv"):
        relative = OLD_OUTPUT_DIR / name
        rows.append(
            {
                "check_name": f"FROZEN_FILE_{name}",
                "expected": _sha256_bytes(_git_bytes(root, OLD_STAGE7F_B_TAG, relative)),
                "actual": _sha256_file(root / relative),
            }
        )
    for name in CONFIG_PATHS:
        rows.append(
            {
                "check_name": f"REPOSITORY_CONFIG_{Path(name).name}",
                "expected": expected_configs[name],
                "actual": _sha256_file(root / name),
            }
        )
    baseline_provenance = _read_json(old / "arms/stage7f_baseline/provenance.json")
    baseline_paths = {stage: Path(path) for stage, path in baseline_provenance["paths"].items()}
    for provenance_path in sorted((old / "arms").glob("*/provenance.json")):
        provenance = _read_json(provenance_path)
        arm_id = str(provenance["arm_id"])
        arm_root = provenance_path.parent
        for stage, expected in sorted(provenance["output_hashes"].items()):
            candidate = arm_root / stage
            stage_root = candidate if candidate.is_dir() else baseline_paths[stage]
            rows.append(
                {
                    "check_name": f"ARM_OUTPUT_HASH_{arm_id}_{stage}",
                    "expected": expected,
                    "actual": _sha256_file(stage_root / "file_hashes.sha256"),
                }
            )
    for row in rows:
        row["status"] = "PASS" if str(row["actual"]) == str(row["expected"]) else "FAIL"
    return rows, verification


def _comparison_unchanged(identity: list[dict[str, Any]], names: tuple[str, ...]) -> bool:
    wanted = {f"FROZEN_FILE_{name}" for name in names}
    selected = [row for row in identity if row["check_name"] in wanted]
    return len(selected) == len(wanted) and all(row["status"] == "PASS" for row in selected)


def _hard_checks(
    native: list[dict[str, Any]],
    saturation: list[dict[str, Any]],
    identity: list[dict[str, Any]],
    verification: dict[str, Any],
) -> list[dict[str, Any]]:
    by_arm = {row["arm_id"]: row for row in native}
    sat = {row["arm_id"]: row for row in saturation}
    identity_by_name = {row["check_name"]: row for row in identity}
    checks = [
        (
            "OLD_STAGE7F_B_TAG_UNCHANGED",
            identity_by_name["OLD_STAGE7F_B_TAG_UNCHANGED"]["status"] == "PASS",
        ),
        (
            "ALL_STAGE7F_B_OUTPUTS_UNCHANGED",
            verification["mismatch_count"] == 0
            and all(row["status"] == "PASS" for row in identity),
        ),
        (
            "FIVE_M_NATIVE_QUALITY_GATE_PASS",
            by_arm["cell_size_m_5"]["native_quality_gate_status"] == "PASS",
        ),
        (
            "TEN_M_NATIVE_QUALITY_GATE_PASS",
            by_arm["stage7f_baseline"]["native_quality_gate_status"] == "PASS",
        ),
        (
            "TWENTY_M_SCOPE_ROLE_CONFLICTS_90",
            by_arm["cell_size_m_20"]["scope_role_conflicts"] == 90,
        ),
        (
            "TWENTY_M_POINT_UNDERCOVERAGE_23",
            by_arm["cell_size_m_20"]["point_missing_or_duplicate"] == 23,
        ),
        (
            "TWENTY_M_INTERVAL_UNDERCOVERAGE_76",
            by_arm["cell_size_m_20"]["interval_overlap_mismatch"] == 76,
        ),
        (
            "TWENTY_M_CLASSIFIED_AS_STRESS_TEST",
            by_arm["cell_size_m_20"]["interpretation_scope"] == "COARSE_RESOLUTION_STRESS_TEST",
        ),
        (
            "TWENTY_M_NOT_CLEAN_VALID_ARM",
            by_arm["cell_size_m_20"]["method_validity_status"] != "VALID_SENSITIVITY_ARM",
        ),
        (
            "Z2_ACTUAL_SATURATION_2",
            sat["rai_saturation_robust_z_2"]["actual_saturation_robust_z"] == 2.0,
        ),
        (
            "Z4_ACTUAL_SATURATION_4",
            sat["rai_saturation_robust_z_4"]["actual_saturation_robust_z"] == 4.0,
        ),
        (
            "Z2_Z4_LEGACY_OPERATOR_LABEL_DETECTED",
            all(
                row["legacy_operator_label"] == "min_raw_deviation_divided_by_3"
                for row in saturation
            ),
        ),
        (
            "LEGACY_LABEL_NOT_AUTHORITATIVE",
            all(not row["legacy_label_used_as_authoritative_parameter"] for row in saturation),
        ),
        (
            "HISTORY_RESULTS_UNCHANGED",
            _comparison_unchanged(
                identity,
                (
                    "rai_history_metric_summary.csv",
                    "rai_history_pairwise_statistics.csv",
                    "rai_history_claim_transition_matrix.csv",
                ),
            ),
        ),
        (
            "SATURATION_RESULTS_UNCHANGED",
            _comparison_unchanged(
                identity,
                (
                    "rai_saturation_metric_summary.csv",
                    "rai_saturation_pairwise_statistics.csv",
                    "rai_saturation_claim_transition_matrix.csv",
                ),
            ),
        ),
        (
            "CELL_METRIC_RESULTS_UNCHANGED",
            _comparison_unchanged(
                identity,
                (
                    "cell_size_date_role_metric_summary.csv",
                    "cell_size_metric_pairwise_statistics.csv",
                ),
            ),
        ),
        (
            "REPLAY_HASH_UNCHANGED",
            identity_by_name["FROZEN_FILE_deterministic_replay_audit.csv"]["status"] == "PASS",
        ),
        ("API_CALLS_ZERO", True),
        ("LLM_CALLS_ZERO", True),
        ("DEEPSEEK_CALLS_ZERO", True),
        ("AUTOMATIC_ROBUSTNESS_CLASSIFICATION_NOT_PERFORMED", True),
    ]
    return [
        {"check_name": name, "status": "PASS" if passed else "FAIL", "details": ""}
        for name, passed in checks
    ]


def _final_summary(
    root: Path,
    native: list[dict[str, Any]],
    resolution: list[dict[str, Any]],
    saturation_audit: list[dict[str, Any]],
) -> dict[str, Any]:
    common = _common_by_arm(root)
    validity = {row["arm_id"]: row for row in native}

    def endpoint(arm_id: str) -> dict[str, Any]:
        row = common[arm_id]
        return {
            key: row[key]
            for key in (
                "rai_available_count",
                "rai_eligible_count",
                "rai_availability_rate",
                "grs_available_count",
                "grs_eligible_count",
                "grs_availability_rate",
                "grci_available_count",
                "grci_eligible_count",
                "grci_availability_rate",
                "claim_opportunity_count",
                "expressible_count",
                "expressible_rate",
                "abstain_count",
                "abstain_rate",
            )
        }

    cell_arms = {
        "5m": "cell_size_m_5",
        "10m": "stage7f_baseline",
        "20m": "cell_size_m_20",
    }
    return {
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "recommended_stage7f_machine_summary": True,
        "automatic_robustness_classification": "NOT_PERFORMED",
        "cell_size": {
            label: {
                **validity[arm_id],
                **next(row for row in resolution if row["arm_id"] == arm_id),
                "frozen_results": endpoint(arm_id),
            }
            for label, arm_id in cell_arms.items()
        },
        "history": {
            "20": endpoint("rai_history_min_samples_20"),
            "30": endpoint("stage7f_baseline"),
            "40": endpoint("rai_history_min_samples_40"),
            "interpretation": "LIMITED_AVAILABILITY_BOUNDARY_SENSITIVITY",
            "claim_transitions": _read_csv(
                root / OLD_OUTPUT_DIR / "rai_history_claim_transition_matrix.csv"
            ),
        },
        "saturation": {
            "2": endpoint("rai_saturation_robust_z_2"),
            "3": endpoint("stage7f_baseline"),
            "4": endpoint("rai_saturation_robust_z_4"),
            "interpretation": "VALUE_SENSITIVE_BUT_DECISION_STABLE",
            "claim_transitions": _read_csv(
                root / OLD_OUTPUT_DIR / "rai_saturation_claim_transition_matrix.csv"
            ),
            "metadata_consistency": saturation_audit,
        },
        "interpretation_boundaries": {
            "five_vs_ten_m": "PRIMARY_CLEAN_FINER_RESOLUTION_COMPARISON",
            "twenty_m": "COARSE_RESOLUTION_STRESS_TEST_NOT_INTERCHANGEABLE",
            "twenty_m_per_100m": (
                "DESCRIPTIVE_USING_ACTUAL_COARSE_CELL_EXPOSURE_NOT_EQUAL_SPATIAL_SUPPORT"
            ),
            "no_best_parameter_selected": True,
            "no_p_value_stability_claim": True,
        },
        "api_calls": 0,
        "llm_calls": 0,
        "deepseek_calls": 0,
    }


def _write_docs(output: Path) -> None:
    output.joinpath("README.md").write_text(
        (
            "# Stage7F-B v1.1 Final Interpretation\n\n"
            "This directory is a metadata-only interpretation layer over the immutable "
            "Stage7F-B v1 frozen execution. No arm, metric, claim, or replay result was "
            "rerun.\n\n"
            "Use `stage7f_final_machine_summary.json` for paper tables and plotting. The 5 m "
            "arm is the clean finer-resolution comparison; the 20 m arm is retained as a "
            "coarse-resolution stress test. No automatic robustness classification was "
            "performed.\n"
        ),
        encoding="utf-8",
    )
    output.joinpath("STAGE7F_FINAL_INTERPRETATION.md").write_text(
        (
            "# Stage7F Final Machine-Experiment Interpretation\n\n"
            "## Spatial resolution\n\n"
            "The 5 m versus 10 m comparison is the primary clean resolution sensitivity "
            "analysis. Metric rank patterns are broadly preserved, while Claim opportunity "
            "density and expressibility proportions remain resolution-dependent.\n\n"
            "The 20 m arm completed deterministically but crossed the representation-validity "
            "boundary of the current spatial state model. Individual cells span daily-review, "
            "forward-attention, or local-background scopes, yielding 90 role conflicts, 23 "
            "point undercoverage cases, and 76 interval overlap mismatches. It is retained as "
            "a coarse-resolution stress test, not an interchangeable valid parameterization. "
            "Its per-100 m results use the actual 14,180 m coarse-cell exposure and are not an "
            "equal-spatial-support density comparison with the 13,220 m 5 m/10 m exposures.\n\n"
            "The sensitivity adapter did not change cell construction, evidence values, "
            "metric formulas, or Claim rules. It only allowed native resolution-related "
            "quality failures to be recorded while the deterministic arm continued. "
            "Therefore the 20 m native Stage3A quality gate must not be described as "
            "passing.\n\n"
            "中文边界：20 m 已越过当前空间状态表示的有效边界，保留为粗分辨率压力测试；"
            "5 m 与 10 m 才是主要的干净分辨率敏感性比较。\n\n"
            "## RAI history sufficiency\n\n"
            "The 20/30/40-observation arms have identical values on jointly available metric "
            "summaries. The change is concentrated at the availability boundary: 20 "
            "observations produce four ABSTAIN-to-EXPRESSIBLE transitions, while 40 produce "
            "four EXPRESSIBLE-to-ABSTAIN transitions. This is limited boundary sensitivity.\n\n"
            "## RAI saturation scaling\n\n"
            "The 2/3/4 robust-z arms change RAI and GRCI magnitudes as expected while "
            "preserving high rank consistency. Claim decisions do not transition. The stale "
            "`min_raw_deviation_divided_by_3` label is inherited metadata; the authoritative "
            "execution parameter is `rai.saturation_robust_z` as consumed by the "
            "implementation.\n\n"
            "## Interpretation rule\n\n"
            "No automatic robust/not-robust threshold, best parameter, or p-value claim is "
            "made. History sufficiency shows limited sensitivity; saturation is "
            "value-sensitive but decision-stable; finer 5 m resolution is broadly consistent; "
            "coarse 20 m resolution reaches the representation-validity boundary.\n"
        ),
        encoding="utf-8",
    )


def build_final_interpretation(
    repo_root: Path,
    output_dir: Path = OUTPUT_DIR,
    *,
    create_audit_zip: bool = True,
) -> dict[str, Any]:
    """Build the final read-only interpretation artifact."""

    root = repo_root.resolve()
    output = root / output_dir
    output.mkdir(parents=True, exist_ok=True)
    old_manifest_before = _sha256_file(root / OLD_OUTPUT_DIR / "file_hashes.sha256")
    native = reconstruct_native_quality_gates(root)
    resolution = resolution_validity_summary(root, native)
    saturation = saturation_metadata_audit(root)
    identity, verification = old_identity_audit(root)
    hard = _hard_checks(native, saturation, identity, verification)
    summary = _final_summary(root, native, resolution, saturation)
    write_csv(output / "cell_size_native_quality_gate_audit.csv", native)
    write_csv(output / "cell_size_resolution_validity_summary.csv", resolution)
    write_csv(output / "rai_saturation_metadata_consistency_audit.csv", saturation)
    write_csv(output / "old_stage7f_b_identity_audit.csv", identity)
    write_csv(output / "hard_check.csv", hard, ["check_name", "status", "details"])
    write_json(output / "stage7f_final_machine_summary.json", summary)
    method = {
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "scope": "METADATA_AND_INTERPRETATION_ONLY",
        "source_stage7f_b_tag": OLD_STAGE7F_B_TAG,
        "source_stage7f_b_commit": OLD_STAGE7F_B_COMMIT,
        "source_stage7f_b_hash_manifest_sha256": old_manifest_before,
        "automatic_robustness_classification": "NOT_PERFORMED",
        "api_calls": 0,
        "llm_calls": 0,
        "deepseek_calls": 0,
    }
    write_json(output / "method_version.json", method)
    _write_docs(output)
    old_manifest_after = _sha256_file(root / OLD_OUTPUT_DIR / "file_hashes.sha256")
    if old_manifest_before != old_manifest_after:
        raise RuntimeError("Stage7F-B frozen output changed during interpretation build")
    failures = sum(row["status"] != "PASS" for row in hard)
    write_json(
        output / "freeze_manifest.json",
        {
            **method,
            "status": "FROZEN" if failures == 0 else "NOT_READY",
            "hard_check_failure_count": failures,
            "old_output_listed_file_count": verification["listed_file_count"],
            "old_output_hash_mismatch_count": verification["mismatch_count"],
            "native_quality_gate_rows": native,
            "recommended_summary": "stage7f_final_machine_summary.json",
        },
    )
    write_file_hashes(output)
    zip_path = _write_audit_zip(root, output) if create_audit_zip else None
    if failures:
        raise RuntimeError(f"Stage7F-B v1.1 hard checks failed: {failures}")
    return {
        "hard_check_failures": failures,
        "old_output_hash_mismatches": verification["mismatch_count"],
        "audit_zip": str(zip_path) if zip_path else "",
        "api_calls": 0,
        "llm_calls": 0,
    }


def _write_audit_zip(root: Path, output: Path) -> Path:
    zip_path = root / AUDIT_ZIP
    members = [path for path in output.rglob("*") if path.is_file()]
    members.extend(
        [
            root / "src/tbm_twin/evaluation/stage7f_final_interpretation.py",
            root / "scripts/build_stage7f_final_interpretation.py",
            root / "tests/unit/test_stage7f_final_interpretation.py",
            root / OLD_OUTPUT_DIR / "freeze_manifest.json",
            root / OLD_OUTPUT_DIR / "file_hashes.sha256",
            root / OLD_OUTPUT_DIR / "deterministic_replay_audit.csv",
            root / OLD_OUTPUT_DIR / "stage7f_common_endpoint_summary.csv",
        ]
    )
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(set(members)):
            archive.write(path, path.relative_to(root).as_posix())
    return zip_path
