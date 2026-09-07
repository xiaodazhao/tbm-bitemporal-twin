"""Stage 7F-A v1.1 frozen metric-semantics metadata correction."""

# ruff: noqa: RUF001

from __future__ import annotations

import copy
import csv
import math
import zipfile
from pathlib import Path
from typing import Any

from tbm_twin.evaluation.stage7f_protocol import (
    CLAIM_CONTRACT_CONFIG,
    STAGE7E_FINAL_COMMIT,
    STAGE7E_FINAL_TAG,
    STATE_METRIC_CONFIG,
    _arm_manifest,
    _baseline_identity_audit,
    _canonical,
    _comparison_key_spec,
    _endpoint_registry,
    _expected_execution_budget,
    _git,
    _git_file_sha256,
    _load_baseline,
    _monitored_dates,
    _parameter_inventory,
    _read_yaml,
    _sha256_file,
    _stable_hash,
    _write_hashes,
    _write_json,
)
from tbm_twin.evaluation.stage7f_protocol import (
    OUTPUT_DIR as V1_OUTPUT_DIR,
)

METHOD_VERSION = "stage7f_sensitivity_protocol_v1_1_metric_semantics_corrected"
SCHEMA_VERSION = "stage7f_sensitivity_protocol.v1.1"
GENERATED_AT = "2026-08-28T12:00:00+08:00"
OUTPUT_DIR = Path("artifacts/stage7f_sensitivity_protocol_v1_1")
AUDIT_ZIP = "stage7f_sensitivity_protocol_v1_1_audit.zip"
V1_TAG = "stage7f-sensitivity-protocol-v1-frozen"
V1_COMMIT = "6f7cfdc05574110f6a22387bb3218bdec1343c1d"
EXPECTED_STATE_METRIC_CONFIG_SHA256 = (
    "bd8d7a3d86d9d9a80a29077b87ace58124074b7f92a3208479e3396085a20c24"
)


def build_stage7f_protocol_v1_1(
    repo_root: Path,
    output_dir: Path = OUTPUT_DIR,
    *,
    create_audit_zip: bool = True,
) -> dict[str, Any]:
    """Correct non-tunable metadata without executing sensitivity arms."""

    root = repo_root.resolve()
    output = root / output_dir
    output.mkdir(parents=True, exist_ok=True)
    baseline = _load_baseline(root)
    metrics = _read_yaml(root / STATE_METRIC_CONFIG)
    inventory = _corrected_inventory(baseline, metrics)
    arms = _arm_manifest(baseline)
    dates = _monitored_dates(root)
    identity = _baseline_identity_audit(root)
    arm_identity = _arm_identity_audit(root, arms)
    v1_integrity = _v1_artifact_integrity(root)
    protocol = _corrected_protocol(baseline, arms, dates, identity, metrics)
    hard_rows = _hard_checks(
        root,
        baseline,
        metrics,
        inventory,
        arms,
        identity,
        arm_identity,
        v1_integrity,
        protocol,
    )
    _write_outputs(
        output,
        baseline,
        metrics,
        inventory,
        arms,
        dates,
        identity,
        arm_identity,
        v1_integrity,
        protocol,
        hard_rows,
    )
    failures = sum(row["status"] != "PASS" for row in hard_rows)
    if failures:
        raise RuntimeError(f"Stage7F-A v1.1 hard checks failed: {failures}")
    _write_hashes(output)
    zip_path = _write_audit_zip(root, output) if create_audit_zip else None
    return {
        "arm_count": len(arms),
        "arm_identity_mismatches": sum(row["status"] != "PASS" for row in arm_identity),
        "hard_failures": failures,
        "api_calls": 0,
        "llm_calls": 0,
        "audit_zip": str(zip_path) if zip_path else "",
    }


def _metric_semantics(metrics: dict[str, Any]) -> dict[str, Any]:
    grs = metrics["grs"]
    grci = metrics["grci"]
    return {
        "GRS": {
            "dimension_operator": str(grs["dimension_operator"]),
            "state_operator": str(grs["state_operator"]),
        },
        "GRCI": {
            "scope": str(grci["scope"]),
            "operator": str(grci["operator"]),
            "is_probability": bool(grci["is_probability"]),
            "is_causal_estimate": bool(grci["is_causal_estimate"]),
            "is_hazard_probability": bool(grci["is_hazard_probability"]),
        },
    }


def _corrected_inventory(baseline: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    rows = copy.deepcopy(_parameter_inventory(baseline))
    semantics = _metric_semantics(metrics)
    grs = semantics["GRS"]
    grci = semantics["GRCI"]
    for row in rows:
        if row["parameter_id"] == "GRS_DIMENSION_AGGREGATION":
            row["current_value"] = (
                f"within-dimension {grs['dimension_operator']}; "
                f"across non-null dimensions {grs['state_operator']}"
            )
            row["parameter_role"] = (
                "Aggregates mapped geological evidence by maximum attention within each "
                "dimension and arithmetic mean across available dimensions"
            )
            row["reason"] = (
                "Changing either operator would redefine GRS rather than test parameter robustness."
            )
        elif row["parameter_id"] == "GRCI_COUPLING_OPERATOR":
            row["current_value"] = f"RAI * GRS when both available in {grci['scope']}"
            row["parameter_role"] = (
                "Nonprobabilistic conjunctive attention product; computed only for "
                "daily-review cells when both RAI and GRS are available"
            )
            row["reason"] = (
                "Changing the operator would redefine GRCI rather than test parameter robustness."
            )
    return rows


def _corrected_protocol(
    baseline: dict[str, Any],
    arms: list[dict[str, Any]],
    dates: list[str],
    identity: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    from tbm_twin.evaluation.stage7f_protocol import _protocol

    protocol = copy.deepcopy(_protocol(baseline, arms, dates, identity))
    protocol.update(
        {
            "method_version": METHOD_VERSION,
            "schema_version": SCHEMA_VERSION,
            "generated_at": GENERATED_AT,
            "status": "FROZEN_PROTOCOL_METADATA_CORRECTED_NOT_EXECUTED",
            "supersedes_protocol_version": "stage7f_sensitivity_protocol_v1",
            "correction_scope": "NON_TUNABLE_GRS_GRCI_METADATA_DESCRIPTIONS_ONLY",
            "frozen_metric_semantics": _metric_semantics(metrics),
        }
    )
    return protocol


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _arm_identity_audit(root: Path, v1_1_arms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    v1_rows = {
        row["arm_id"]: row for row in _read_csv(root / V1_OUTPUT_DIR / "stage7f_arm_manifest.csv")
    }
    fields = [
        "arm_id",
        "parameter_id",
        "parameter_value",
        "is_baseline",
        "changed_config_path",
        "baseline_value",
        "all_other_parameters_frozen",
        "expected_pipeline_start_stage",
        "expected_pipeline_end_stage",
        "llm_required",
        "api_required",
        "arm_hash",
    ]
    audit = []
    for arm in v1_1_arms:
        old = v1_rows.get(str(arm["arm_id"]), {})
        normalized = {key: str(value) for key, value in arm.items()}
        mismatches = [field for field in fields if old.get(field, "") != normalized.get(field, "")]
        audit.append(
            {
                "arm_id": arm["arm_id"],
                "v1_present": bool(old),
                "v1_1_present": True,
                "parameter_id_match": old.get("parameter_id") == normalized["parameter_id"],
                "parameter_value_match": (
                    old.get("parameter_value") == normalized["parameter_value"]
                ),
                "baseline_value_match": old.get("baseline_value") == normalized["baseline_value"],
                "ofat_isolation_match": (
                    old.get("changed_config_path") == normalized["changed_config_path"]
                    and old.get("all_other_parameters_frozen")
                    == normalized["all_other_parameters_frozen"]
                ),
                "arm_hash_match": old.get("arm_hash") == normalized["arm_hash"],
                "mismatch_fields": ";".join(mismatches),
                "status": "PASS" if old and not mismatches else "FAIL",
            }
        )
    return audit


def _v1_artifact_integrity(root: Path) -> dict[str, Any]:
    manifest = root / V1_OUTPUT_DIR / "file_hashes.sha256"
    expected_manifest_hash = _git_file_sha256(root, V1_TAG, V1_OUTPUT_DIR / manifest.name)
    actual_manifest_hash = _sha256_file(manifest)
    file_checks = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        expected, filename = line.split(maxsplit=1)
        actual = _sha256_file(root / V1_OUTPUT_DIR / filename.strip())
        file_checks.append(expected == actual)
    return {
        "tag_commit": _git(root, "rev-parse", V1_TAG),
        "expected_manifest_sha256": expected_manifest_hash,
        "actual_manifest_sha256": actual_manifest_hash,
        "manifest_matches_tag": expected_manifest_hash == actual_manifest_hash,
        "listed_file_count": len(file_checks),
        "listed_files_valid": all(file_checks),
    }


def _grci_numeric_sanity(rai: float, grs: float) -> float:
    return rai * grs


def _grs_state_numeric_sanity(values: list[float | None]) -> float | None:
    available = [value for value in values if value is not None]
    return sum(available) / len(available) if available else None


def _implementation_semantics_exact(root: Path) -> dict[str, bool]:
    grci = (root / "src/tbm_twin/metrics/grci.py").read_text(encoding="utf-8")
    grs = (root / "src/tbm_twin/metrics/grs.py").read_text(encoding="utf-8")
    return {
        "grci_product_implementation": ('value = float(rai["rai"]) * float(grs["grs"])' in grci),
        "grci_daily_review_scope": 'role == "DAILY_REVIEW_CELL"' in grci,
        "grs_dimension_max": "max_value = max(item[0] for item in mapped)" in grs,
        "grs_state_non_null_mean": "grs = sum(available) / len(available)" in grs,
    }


def _hard_checks(
    root: Path,
    baseline: dict[str, Any],
    metrics: dict[str, Any],
    inventory: list[dict[str, Any]],
    arms: list[dict[str, Any]],
    identity: list[dict[str, Any]],
    arm_identity: list[dict[str, Any]],
    v1_integrity: dict[str, Any],
    protocol: dict[str, Any],
) -> list[dict[str, str]]:
    semantics = _metric_semantics(metrics)
    grs = semantics["GRS"]
    grci = semantics["GRCI"]
    grci_value = _grci_numeric_sanity(0.315043708909733, 0.5416666666666666)
    grs_value = _grs_state_numeric_sanity([0.0, 0.6666666667, 0.75, 0.75, None, None])
    implementation = _implementation_semantics_exact(root)
    checks: list[tuple[str, bool, Any]] = [
        ("old_v1_tag_unchanged", v1_integrity["tag_commit"] == V1_COMMIT, v1_integrity),
        (
            "old_v1_artifact_unchanged",
            v1_integrity["manifest_matches_tag"] and v1_integrity["listed_files_valid"],
            v1_integrity,
        ),
        (
            "stage7e_final_tag_unchanged",
            _git(root, "rev-parse", STAGE7E_FINAL_TAG) == STAGE7E_FINAL_COMMIT,
            STAGE7E_FINAL_COMMIT,
        ),
        ("baseline_cell_10", baseline["cell_size_m"] == 10.0, baseline["cell_size_m"]),
        (
            "history_30",
            baseline["minimum_baseline_sample_count"] == 30,
            baseline["minimum_baseline_sample_count"],
        ),
        ("saturation_3", baseline["saturation_robust_z"] == 3.0, baseline["saturation_robust_z"]),
        ("arm_count_7", len(arms) == 7, len(arms)),
        (
            "arm_identity_v1_v1_1_exact",
            all(row["status"] == "PASS" for row in arm_identity),
            sum(row["status"] != "PASS" for row in arm_identity),
        ),
        ("ofat_unchanged", protocol["design"] == "ONE_FACTOR_AT_A_TIME", protocol["design"]),
        (
            "grci_operator_exact",
            grci["operator"] == "NONPROBABILISTIC_CONJUNCTIVE_PRODUCT",
            grci["operator"],
        ),
        ("grci_scope_exact", grci["scope"] == "DAILY_REVIEW_CELL_ONLY", grci["scope"]),
        ("grci_probability_false", grci["is_probability"] is False, grci["is_probability"]),
        (
            "grci_causal_estimate_false",
            grci["is_causal_estimate"] is False,
            grci["is_causal_estimate"],
        ),
        (
            "grci_hazard_probability_false",
            grci["is_hazard_probability"] is False,
            grci["is_hazard_probability"],
        ),
        (
            "grci_numeric_product_sanity",
            math.isclose(grci_value, 0.1706486756594387, rel_tol=0.0, abs_tol=1e-15),
            grci_value,
        ),
        (
            "grs_dimension_operator_exact",
            grs["dimension_operator"] == "max_mapped_attention",
            grs["dimension_operator"],
        ),
        (
            "grs_state_operator_exact",
            grs["state_operator"] == "mean_non_null_dimension_attention",
            grs["state_operator"],
        ),
        (
            "grs_non_null_mean_sanity",
            grs_value is not None
            and math.isclose(grs_value, 0.541666666675, rel_tol=0.0, abs_tol=1e-15),
            grs_value,
        ),
        ("implementation_semantics_exact", all(implementation.values()), implementation),
        (
            "state_metric_config_hash_unchanged",
            _sha256_file(root / STATE_METRIC_CONFIG) == EXPECTED_STATE_METRIC_CONFIG_SHA256,
            _sha256_file(root / STATE_METRIC_CONFIG),
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
        (
            "baseline_identity_all_match",
            all(row["status"] == "PASS" for row in identity),
            len(identity),
        ),
        (
            "sensitivity_parameter_count_3",
            sum(row["sensitivity_candidate"] for row in inventory) == 3,
            sum(row["sensitivity_candidate"] for row in inventory),
        ),
        (
            "no_sensitivity_outcome_generated",
            protocol["sensitivity_outcomes_generated"] is False,
            0,
        ),
        ("api_calls_zero", protocol["api_calls"] == 0, protocol["api_calls"]),
        ("llm_calls_zero", protocol["llm_calls"] == 0, protocol["llm_calls"]),
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
    metrics: dict[str, Any],
    inventory: list[dict[str, Any]],
    arms: list[dict[str, Any]],
    dates: list[str],
    identity: list[dict[str, Any]],
    arm_identity: list[dict[str, Any]],
    v1_integrity: dict[str, Any],
    protocol: dict[str, Any],
    hard_rows: list[dict[str, Any]],
) -> None:
    (output / "README.md").write_text(_readme(), encoding="utf-8")
    (output / "STAGE7F_PARAMETER_RATIONALE.md").write_text(_rationale(), encoding="utf-8")
    (output / "STAGE7F_V1_1_METADATA_CORRECTION.md").write_text(
        _correction_note(), encoding="utf-8"
    )
    _write_csv(output / "stage7f_parameter_inventory.csv", inventory)
    _write_json(output / "stage7f_sensitivity_protocol.json", protocol)
    _write_csv(output / "stage7f_arm_manifest.csv", arms)
    _write_csv(output / "stage7f_v1_v1_1_arm_identity_audit.csv", arm_identity)
    _write_csv(output / "stage7f_baseline_identity_audit.csv", identity)
    endpoints = _endpoint_registry()
    endpoints["method_version"] = METHOD_VERSION
    comparison = _comparison_key_spec()
    comparison["method_version"] = METHOD_VERSION
    _write_json(output / "stage7f_endpoint_registry.json", endpoints)
    _write_json(output / "stage7f_comparison_key_spec.json", comparison)
    _write_json(output / "stage7f_expected_execution_budget.json", _expected_execution_budget(arms))
    _write_csv(output / "hard_check.csv", hard_rows)
    method = {
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "correction_type": "NON_TUNABLE_METRIC_METADATA_DEFINITION_CORRECTION",
        "v1_commit": V1_COMMIT,
        "v1_tag": V1_TAG,
        "v1_artifact_manifest_sha256": v1_integrity["actual_manifest_sha256"],
        "stage7e_final_commit": STAGE7E_FINAL_COMMIT,
        "stage7e_final_tag": STAGE7E_FINAL_TAG,
        "frozen_metric_semantics": _metric_semantics(metrics),
        "api_calls": 0,
        "llm_calls": 0,
    }
    _write_json(output / "method_version.json", method)
    _write_json(
        output / "freeze_manifest.json",
        {
            **method,
            "status": "FROZEN_PROTOCOL_METADATA_CORRECTED_NOT_EXECUTED",
            "baseline": baseline,
            "counts": {
                "unique_arms": len(arms),
                "arm_identity_mismatches": sum(row["status"] != "PASS" for row in arm_identity),
                "sensitivity_parameters": sum(row["sensitivity_candidate"] for row in inventory),
                "monitored_dates": len(dates),
            },
            "arm_manifest_hash": _stable_hash(arms),
            "protocol_hash": _stable_hash(protocol),
            "hard_check_failure_count": sum(row["status"] != "PASS" for row in hard_rows),
            "sensitivity_outcomes_generated": 0,
            "pipeline_runs_executed": 0,
        },
    )


def _readme() -> str:
    return """# Stage7F-A v1.1 参数敏感性协议元数据修正

本目录仅修正 Stage7F-A v1 参数盘点中 GRS/GRCI 的非可调方法描述。7 个 OFAT arm、
10/30/3 baseline、91 个 PLC 监测施工日期、评价端点和比较键均保持不变。真实 Stage4
配置与实现没有修改，旧 v1 artifact 和 tag 保持冻结。本轮没有运行敏感性 arm，没有生成
实验 outcome，也没有调用 API/LLM。
"""


def _rationale() -> str:
    return """# Stage7F 参数选择与冻结语义

敏感性参数仍只有三个：ConstructionStateCell 采用 5/10/20 m，RAI 历史充分性采用
20/30/40 个先前观测样本，RAI robust-z 饱和尺度采用 2/3/4。实验设计仍是一个共享
baseline 加六个单参数替代 arm 的 OFAT，不进行全因子调优。

GRS ordinal mapping、维度内 `max_mapped_attention` 聚合以及跨非空维度的
`mean_non_null_dimension_attention` state aggregation 都属于冻结指标语义，不参与扰动。
GRCI 的 `NONPROBABILISTIC_CONJUNCTIVE_PRODUCT` 定义为 RAI 与 GRS 的乘积，只在
`DAILY_REVIEW_CELL_ONLY` scope 且两者均可用时计算；它不是概率、因果估计或灾害概率，
也不是 sensitivity parameter。Claim Contract 与双时间知识边界继续保持冻结。

未来 Stage7F-B 只能按冻结 manifest 执行描述性 robustness，不得依据结果选择 arm 或设置
任意自动 PASS threshold。
"""


def _correction_note() -> str:
    return """# Stage7F-A v1.1 Metadata Correction

## Corrected GRCI description

The v1 inventory incorrectly described GRCI as `sqrt(RAI * GRS)`. The frozen config and
implementation define `RAI * GRS` with operator `NONPROBABILISTIC_CONJUNCTIVE_PRODUCT`,
available only for `DAILY_REVIEW_CELL_ONLY` when both inputs are available.

## Corrected GRS description

The v1 inventory incorrectly summarized all GRS aggregation as a maximum. The frozen method
uses `max_mapped_attention` within each geological dimension and
`mean_non_null_dimension_attention` across available dimensions.

No parameter, arm, baseline, metric implementation, Claim Contract, upstream artifact, or
experimental outcome changed. This correction only replaces two non-tunable metadata strings
with config-backed method semantics.
"""


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"CSV requires schema rows: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_audit_zip(root: Path, output: Path) -> Path:
    zip_path = root / AUDIT_ZIP
    if zip_path.exists():
        zip_path.unlink()
    extra = [
        root / "src/tbm_twin/evaluation/stage7f_protocol_v1_1.py",
        root / "scripts/build_stage7f_sensitivity_protocol_v1_1.py",
        root / "tests/unit/test_stage7f_sensitivity_protocol_v1_1.py",
    ]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.iterdir()):
            if path.is_file():
                archive.write(path, path.relative_to(root))
        for path in extra:
            archive.write(path, path.relative_to(root))
    return zip_path
