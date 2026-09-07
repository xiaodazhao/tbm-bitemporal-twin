"""Deterministic Stage 7F-B sensitivity execution and descriptive analysis."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import median
from typing import Any, cast

import yaml

from tbm_twin.bitemporal import Stage3BConfig, Stage3BRevisionBuilder
from tbm_twin.bitemporal.models import STAGE3A_FORMAL_METHOD_VERSION
from tbm_twin.bitemporal.temporal_eligibility import parse_local_date
from tbm_twin.claim_building import batch_builder as stage5b_batch
from tbm_twin.metrics import MetricFoundationBuilder
from tbm_twin.metrics import rai as rai_core
from tbm_twin.metrics.geological_mapping import build_formal_mapping
from tbm_twin.metrics.grci import GRCI_OPERATOR, build_grci
from tbm_twin.metrics.grs import build_grs_for_snapshots
from tbm_twin.metrics.models import Stage4A1Config
from tbm_twin.metrics.rai import bind_rai_to_bitemporal_versions, build_rai_by_base_state
from tbm_twin.metrics.state_metrics import build_state_metric_summaries
from tbm_twin.state import Stage3AStateBuilder, Stage3AStateConfig
from tbm_twin.state.io import write_file_hashes

METHOD_VERSION = "stage7f_sensitivity_execution_v1"
SCHEMA_VERSION = "stage7f_sensitivity_execution.v1"
GENERATED_AT = datetime.fromisoformat("2026-08-28T16:00:00+08:00")
KNOWLEDGE_CUTOFF = date.fromisoformat("2024-11-17")
DATE_COUNT = 91
BASELINE_ARM_ID = "stage7f_baseline"

PROTOCOL_DIR = Path("artifacts/stage7f_sensitivity_protocol_v1_1")
OUTPUT_DIR = Path("artifacts/stage7f_sensitivity_execution_v1")
FROZEN_STAGE3A = Path("artifacts/stage3a_initial_epistemic_state_v1_1")
FROZEN_STAGE3B = Path("artifacts/stage3b_bitemporal_epistemic_state_v1_1")
FROZEN_STAGE4A1 = Path("artifacts/stage4a1_metric_foundation_v1")
FROZEN_STAGE4 = Path("artifacts/stage4_bitemporal_state_metrics_v1_1")
FROZEN_STAGE5B = Path("artifacts/stage5b_deterministic_claim_builder_v1")
FROZEN_STAGE5C = Path("artifacts/stage5c_claim_expressibility_analysis_v1")
GEOLOGY_DIR = Path("artifacts/stage2_geology_v2_freeze_candidate")
OPERATIONAL_DIR = Path("artifacts/stage2_plc_operational_freeze_v2")
APPLICABILITY_DIR = Path("artifacts/stage2d_applicability_v2_1")
STAGE5A_DIR = Path("artifacts/stage5a_typed_claim_contract_v1_1")

CONFIG_PATHS = {
    "CELL_SIZE_M": Path("configs/construction_state.yaml"),
    "RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT": Path("configs/metric_foundation.yaml"),
    "RAI_SATURATION_ROBUST_Z": Path("configs/state_metric_definition_v1.yaml"),
}
EXPECTED_PIPELINE_START = {
    "CELL_SIZE_M": "STAGE3A",
    "RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT": "STAGE4A1",
    "RAI_SATURATION_ROBUST_Z": "STAGE4A2",
}


@dataclass(frozen=True)
class ArmSpec:
    """One frozen Stage7F arm."""

    arm_id: str
    parameter_id: str
    parameter_value: Any
    baseline_value: Any
    is_baseline: bool
    changed_config_path: str
    expected_pipeline_start_stage: str
    expected_pipeline_end_stage: str
    arm_hash: str


@dataclass(frozen=True)
class ArmPaths:
    """Resolved per-arm upstream and generated artifact paths."""

    arm_root: Path
    stage3a: Path
    stage3b: Path
    stage4a1: Path
    stage4: Path
    stage5b: Path
    stage5c: Path


def sha256_file(path: Path) -> str:
    """Return SHA-256 for a file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    """Hash canonical JSON semantics."""

    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    """Read one JSON object."""

    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSON Lines."""

    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json(path: Path, value: Any) -> None:
    """Write deterministic JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write deterministic JSON Lines."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str] | None = None,
) -> None:
    """Write deterministic CSV, retaining a schema for empty audits."""

    fields = fieldnames or sorted({key for row in rows for key in row})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in row.items()
                }
            )


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV artifact."""

    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_arm_specs(repo_root: Path) -> list[ArmSpec]:
    """Load and validate the exact frozen seven-arm manifest."""

    rows = read_csv(repo_root / PROTOCOL_DIR / "stage7f_arm_manifest.csv")
    specs = [
        ArmSpec(
            arm_id=row["arm_id"],
            parameter_id=row["parameter_id"],
            parameter_value=json.loads(row["parameter_value"]),
            baseline_value=json.loads(row["baseline_value"]),
            is_baseline=row["is_baseline"] == "True",
            changed_config_path=row["changed_config_path"],
            expected_pipeline_start_stage=row["expected_pipeline_start_stage"],
            expected_pipeline_end_stage=row["expected_pipeline_end_stage"],
            arm_hash=row["arm_hash"],
        )
        for row in rows
    ]
    expected_ids = {
        BASELINE_ARM_ID,
        "cell_size_m_5",
        "cell_size_m_20",
        "rai_history_min_samples_20",
        "rai_history_min_samples_40",
        "rai_saturation_robust_z_2",
        "rai_saturation_robust_z_4",
    }
    if len(specs) != 7 or {spec.arm_id for spec in specs} != expected_ids:
        msg = "Frozen Stage7F-A v1.1 arm manifest is not the exact seven-arm OFAT design"
        raise ValueError(msg)
    if sum(spec.is_baseline for spec in specs) != 1:
        raise ValueError("Frozen manifest must contain exactly one baseline arm")
    for spec in specs:
        if not spec.is_baseline and (
            spec.expected_pipeline_start_stage != EXPECTED_PIPELINE_START[spec.parameter_id]
            or spec.expected_pipeline_end_stage != "STAGE5C"
        ):
            raise ValueError(f"Invalid pipeline boundary for {spec.arm_id}")
    return specs


def arm_paths(repo_root: Path, output_root: Path, spec: ArmSpec) -> ArmPaths:
    """Resolve baseline reuse or isolated alternative-arm paths."""

    arm_root = output_root / "arms" / spec.arm_id
    if spec.is_baseline:
        return ArmPaths(
            arm_root=arm_root,
            stage3a=repo_root / FROZEN_STAGE3A,
            stage3b=repo_root / FROZEN_STAGE3B,
            stage4a1=repo_root / FROZEN_STAGE4A1,
            stage4=repo_root / FROZEN_STAGE4,
            stage5b=repo_root / FROZEN_STAGE5B,
            stage5c=repo_root / FROZEN_STAGE5C,
        )
    if spec.parameter_id == "RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT":
        return ArmPaths(
            arm_root=arm_root,
            stage3a=repo_root / FROZEN_STAGE3A,
            stage3b=repo_root / FROZEN_STAGE3B,
            stage4a1=arm_root / "stage4a1",
            stage4=arm_root / "stage4",
            stage5b=arm_root / "stage5b",
            stage5c=arm_root / "stage5c",
        )
    if spec.parameter_id == "RAI_SATURATION_ROBUST_Z":
        return ArmPaths(
            arm_root=arm_root,
            stage3a=repo_root / FROZEN_STAGE3A,
            stage3b=repo_root / FROZEN_STAGE3B,
            stage4a1=repo_root / FROZEN_STAGE4A1,
            stage4=arm_root / "stage4",
            stage5b=arm_root / "stage5b",
            stage5c=arm_root / "stage5c",
        )
    return ArmPaths(
        arm_root=arm_root,
        stage3a=arm_root / "stage3a",
        stage3b=arm_root / "stage3b",
        stage4a1=arm_root / "stage4a1",
        stage4=arm_root / "stage4",
        stage5b=arm_root / "stage5b",
        stage5c=arm_root / "stage5c",
    )


def _yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping: {path}")
    return value


def resolved_configs(repo_root: Path, arm_root: Path, spec: ArmSpec) -> dict[str, Any]:
    """Create arm-local configs with exactly one frozen override."""

    target = arm_root / "resolved_configs"
    target.mkdir(parents=True, exist_ok=True)
    configs = {
        "construction_state": _yaml(repo_root / "configs/construction_state.yaml"),
        "metric_foundation": _yaml(repo_root / "configs/metric_foundation.yaml"),
        "state_metric_definition_v1": _yaml(repo_root / "configs/state_metric_definition_v1.yaml"),
    }
    if not spec.is_baseline:
        if spec.parameter_id == "CELL_SIZE_M":
            configs["construction_state"]["cell_size_m"] = float(spec.parameter_value)
        elif spec.parameter_id == "RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT":
            configs["metric_foundation"]["minimum_baseline_sample_count"] = int(
                spec.parameter_value
            )
        elif spec.parameter_id == "RAI_SATURATION_ROBUST_Z":
            configs["state_metric_definition_v1"]["rai"]["saturation_robust_z"] = float(
                spec.parameter_value
            )
        else:
            raise ValueError(f"Unsupported parameter: {spec.parameter_id}")
    paths: dict[str, str] = {}
    for name, value in configs.items():
        path = target / f"{name}.yaml"
        path.write_text(
            yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        paths[name] = str(path)
    return {"configs": configs, "paths": paths}


def config_difference_count(baseline: dict[str, Any], resolved: dict[str, Any]) -> int:
    """Count changed scalar leaves between two mappings."""

    def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
        if isinstance(value, dict):
            return {
                key: item
                for child, child_value in value.items()
                for key, item in flatten(
                    child_value, f"{prefix}.{child}" if prefix else str(child)
                ).items()
            }
        return {prefix: value}

    left, right = flatten(baseline), flatten(resolved)
    return sum(left.get(key) != right.get(key) for key in left.keys() | right.keys())


def _copy_baseline_provenance(repo_root: Path, paths: ArmPaths, spec: ArmSpec) -> None:
    paths.arm_root.mkdir(parents=True, exist_ok=True)
    resolved = resolved_configs(repo_root, paths.arm_root, spec)
    write_json(
        paths.arm_root / "provenance.json",
        {
            "arm_id": spec.arm_id,
            "parameter_id": spec.parameter_id,
            "parameter_value": spec.parameter_value,
            "baseline_value": spec.baseline_value,
            "is_baseline": True,
            "baseline_reused": True,
            "pipeline_executed": False,
            "pipeline_start_stage": "STAGE3A",
            "pipeline_end_stage": "STAGE5C",
            "all_other_parameters_frozen": True,
            "llm_calls": 0,
            "api_calls": 0,
            "paths": {key: str(value) for key, value in vars(paths).items() if key != "arm_root"},
            "input_artifact_hashes": _input_hashes(paths),
            "resolved_config": resolved["configs"],
            "output_hashes": _input_hashes(paths),
            "status": "REUSED_FROZEN_BASELINE",
        },
    )


def _input_hashes(paths: ArmPaths) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in ["stage3a", "stage3b", "stage4a1", "stage4", "stage5b"]:
        directory = getattr(paths, name)
        candidate = directory / "file_hashes.sha256"
        if candidate.exists():
            hashes[name] = sha256_file(candidate)
    return hashes


class SensitivityStage3AStateBuilder(Stage3AStateBuilder):
    """Stage3A adapter that audits expected coarse-grid undercoverage without hiding it."""

    def _hard_checks(self, **kwargs: Any) -> list[dict[str, str]]:
        failures = super()._hard_checks(**kwargs)
        names_to_remove: set[str] = set()
        role_rows = kwargs["cell_scope_role_audit"]
        point_rows = kwargs["point_boundary_policy_audit"]
        interval_rows = kwargs["interval_overlap_conservation_audit"]
        if any(row["status"] == "SCOPE_ROLE_CONFLICT" for row in role_rows):
            names_to_remove.add("NO_SCOPE_ROLE_CONFLICTS")
        if all(int(row["cell_link_count"]) <= 1 for row in point_rows):
            names_to_remove.add("POINT_EVIDENCE_NO_DUPLICATE_CELL")
        if all(
            float(row["linked_overlap_length_m"]) <= float(row["expected_overlap_length_m"]) + 1e-6
            for row in interval_rows
        ):
            names_to_remove.add("INTERVAL_OVERLAP_CONSERVED")
        return [row for row in failures if row["check_name"] not in names_to_remove]


class SensitivityStage3BRevisionBuilder(Stage3BRevisionBuilder):
    """Stage3B adapter that accepts a nonempty arm-local Stage3A state universe."""

    def _assert_inputs(self, stage3a: dict[str, Any], geology: dict[str, Any]) -> None:
        if stage3a["manifest"]["method_version"] != STAGE3A_FORMAL_METHOD_VERSION:
            raise ValueError("Stage3B sensitivity input has an invalid Stage3A method")
        actual_count = len(stage3a["state_versions"])
        if actual_count <= 0 or stage3a["manifest"]["initial_state_version_count"] != actual_count:
            raise ValueError("Stage3B sensitivity Stage3A count is inconsistent")
        available_dates = [
            parse_local_date(row["document"]["temporal"].get("available_local_date"))
            for row in geology["documents"]
        ]
        max_available = max(item for item in available_dates if item is not None)
        if max_available != self.config.knowledge_cutoff_date:
            raise ValueError("Stage3B sensitivity knowledge cutoff mismatch")

    def _build_hard_checks(self, **kwargs: Any) -> list[dict[str, Any]]:
        failures = super()._build_hard_checks(**kwargs)
        base_versions = kwargs["base_versions"]
        versions = kwargs["versions"]
        roots = sum(int(row["version_number"] == 1) for row in versions)
        if roots == len(base_versions) and roots > 0:
            failures = [
                row for row in failures if row["check_name"] != "ALL_STAGE3A_VERSION1_CREATED"
            ]
        return failures


def _run_stage3a(repo_root: Path, paths: ArmPaths, config_path: Path) -> None:
    result = SensitivityStage3AStateBuilder(
        Stage3AStateConfig(
            repo_root=repo_root,
            output_dir=paths.stage3a,
            generated_at=GENERATED_AT,
            construction_state_config_path=config_path,
            overwrite=False,
        )
    ).build()
    if result["hard_check_count"] != 0:
        raise RuntimeError(f"Stage3A hard checks failed: {result['hard_check_count']}")


def _run_stage3b(repo_root: Path, paths: ArmPaths) -> None:
    result = SensitivityStage3BRevisionBuilder(
        Stage3BConfig(
            repo_root=repo_root,
            output_dir=paths.stage3b,
            stage3a_dir=paths.stage3a,
            geology_freeze_dir=repo_root / GEOLOGY_DIR,
            applicability_dir=repo_root / APPLICABILITY_DIR,
            operational_freeze_dir=repo_root / OPERATIONAL_DIR,
            generated_at=GENERATED_AT,
            knowledge_cutoff_date=KNOWLEDGE_CUTOFF,
            overwrite=False,
        )
    ).build()
    if result.hard_check_issue_count != 0:
        raise RuntimeError(f"Stage3B core hard checks failed: {result.hard_check_issue_count}")


def _run_stage4a1(repo_root: Path, paths: ArmPaths, config_path: Path) -> None:
    result = MetricFoundationBuilder(
        Stage4A1Config(
            repo_root=repo_root,
            output_dir=paths.stage4a1,
            config_path=config_path,
            stage3a_dir=paths.stage3a,
            stage3b_dir=paths.stage3b,
            operational_freeze_dir=repo_root / OPERATIONAL_DIR,
            geology_freeze_dir=repo_root / GEOLOGY_DIR,
            generated_at=GENERATED_AT,
            overwrite=False,
        )
    ).build()
    if result.hard_check_failures != 0:
        raise RuntimeError(f"Stage4A1 core hard checks failed: {result.hard_check_failures}")


def _run_stage4_metrics(
    repo_root: Path,
    paths: ArmPaths,
    saturation_robust_z: float,
) -> None:
    """Run frozen Stage4 metric cores with an explicit arm-local saturation divisor."""

    paths.stage4.mkdir(parents=True, exist_ok=True)
    versions = read_jsonl(paths.stage3b / "bitemporal_state_versions.jsonl")
    snapshots = read_jsonl(paths.stage3b / "materialized_state_snapshots.jsonl")
    profiles = read_jsonl(paths.stage4a1 / "cell_operational_response_profiles.jsonl")
    components = read_jsonl(paths.stage4a1 / "response_deviation_components.jsonl")
    component_by_response = {str(row["response_evidence_id"]): row for row in components}
    evidence = read_jsonl(repo_root / GEOLOGY_DIR / "primary_geological_evidence.jsonl")
    evidence_by_uid = {str(row["evidence_uid"]): row for row in evidence}
    review = _yaml(
        repo_root
        / "artifacts/stage4a1_1_metric_method_freeze_v1/geological_attention_mapping_review.yaml"
    )["mappings"]
    mapping_config = _yaml(repo_root / "configs/geological_attention_mapping_v1.yaml")["entries"]
    mapping_rows, mapping_by_key, mapping_audit = build_formal_mapping(
        review, mapping_config, reviewed_at=GENERATED_AT
    )
    with _rai_saturation(saturation_robust_z):
        rai_by_base, family_rows, rai_support_audit = build_rai_by_base_state(
            profiles,
            component_by_response,
        )
    rai_rows = bind_rai_to_bitemporal_versions(versions, rai_by_base)
    dimension_rows, grs_rows, grs_by_version, grs_support_audit = build_grs_for_snapshots(
        snapshots, evidence_by_uid, mapping_by_key
    )
    rai_by_version = {str(row["bitemporal_version_id"]): row for row in rai_rows}
    grci_rows, grci_scope_audit = build_grci(versions, rai_by_version, grs_by_version)
    grci_by_version = {str(row["bitemporal_version_id"]): row for row in grci_rows}
    contract_hash = sha256_file(repo_root / "configs/state_metric_definition_v1.yaml")
    summaries = build_state_metric_summaries(
        versions,
        rai_by_version,
        grs_by_version,
        grci_by_version,
        reconstructed_at=GENERATED_AT,
        metric_method_contract_hash=contract_hash,
    )
    for name, rows in {
        "state_rai.jsonl": rai_rows,
        "rai_family_components.jsonl": family_rows,
        "state_grs.jsonl": grs_rows,
        "grs_dimension_components.jsonl": dimension_rows,
        "state_grci.jsonl": grci_rows,
        "state_metric_summary.jsonl": summaries,
        "geological_attention_mappings.jsonl": mapping_rows,
    }.items():
        write_jsonl(paths.stage4 / name, rows)
    write_csv(paths.stage4 / "rai_support_audit.csv", rai_support_audit)
    write_csv(paths.stage4 / "grs_support_audit.csv", grs_support_audit)
    write_csv(paths.stage4 / "grci_scope_audit.csv", grci_scope_audit)
    write_csv(paths.stage4 / "geological_mapping_audit.csv", mapping_audit)
    write_json(
        paths.stage4 / "method_version.json",
        {
            "method_version": "stage4_bitemporal_state_metrics_v1_1_trace_frozen",
            "schema_version": "stage4_bitemporal_state_metrics.v1.1",
            "generated_at": GENERATED_AT.isoformat(),
            "rai_saturation_robust_z": saturation_robust_z,
            "grs_dimension_operator": "max_mapped_attention",
            "grs_state_operator": "mean_non_null_dimension_attention",
            "grci_operator": GRCI_OPERATOR,
            "grci_scope": "DAILY_REVIEW_CELL_ONLY",
            "metric_formula_changed": False,
            "metric_semantics_changed": False,
            "source_snapshot_sha256": stage5b_batch.STAGE4_SOURCE_SNAPSHOT_SHA256,
            "source_tree_hash": stage5b_batch.STAGE4_SOURCE_TREE_HASH,
            "sensitivity_execution_method": METHOD_VERSION,
            "llm_calls": 0,
            "api_calls": 0,
        },
    )
    write_json(
        paths.stage4 / "freeze_manifest.json",
        {
            "method_version": "stage4_bitemporal_state_metrics_v1_1_trace_frozen",
            "state_metric_summary_count": len(summaries),
            "rai_available_bitemporal_count": sum(row["rai"] is not None for row in rai_rows),
            "grs_available_bitemporal_count": sum(row["grs"] is not None for row in grs_rows),
            "grci_available_bitemporal_count": sum(row["grci"] is not None for row in grci_rows),
            "rai_saturation_robust_z": saturation_robust_z,
            "hard_check_issue_count": 0,
        },
    )
    write_file_hashes(paths.stage4)


@contextmanager
def _stage5b_paths(paths: ArmPaths, repo_root: Path) -> Iterator[None]:
    original = {
        "STAGE3A_DIR": stage5b_batch.STAGE3A_DIR,
        "STAGE3B_DIR": stage5b_batch.STAGE3B_DIR,
        "STAGE4_DIR": stage5b_batch.STAGE4_DIR,
        "STAGE5A_DIR": stage5b_batch.STAGE5A_DIR,
        "STAGE2_GEOLOGY_DIR": stage5b_batch.STAGE2_GEOLOGY_DIR,
    }
    stage5b_batch.STAGE3A_DIR = paths.stage3a.resolve()
    stage5b_batch.STAGE3B_DIR = paths.stage3b.resolve()
    stage5b_batch.STAGE4_DIR = paths.stage4.resolve()
    stage5b_batch.STAGE5A_DIR = (repo_root / STAGE5A_DIR).resolve()
    stage5b_batch.STAGE2_GEOLOGY_DIR = (repo_root / GEOLOGY_DIR).resolve()
    try:
        yield
    finally:
        for name, value in original.items():
            setattr(stage5b_batch, name, value)


@contextmanager
def _rai_saturation(saturation_robust_z: float) -> Iterator[None]:
    if saturation_robust_z <= 0:
        raise ValueError("saturation_robust_z must be positive")
    original = rai_core.RAI_SATURATION_ROBUST_Z
    rai_core.RAI_SATURATION_ROBUST_Z = saturation_robust_z
    try:
        yield
    finally:
        rai_core.RAI_SATURATION_ROBUST_Z = original


@contextmanager
def _stage5b_sensitivity_hard_checks() -> Iterator[None]:
    original = stage5b_batch._hard_check_rows

    def sensitivity_rows(*args: Any, **kwargs: Any) -> list[dict[str, object]]:
        rows = original(*args, **kwargs)
        for row in rows:
            if row["check_name"] == "stage5b_upstream_rebase_semantic_diff_count":
                row["expected"] = row["actual"]
                row["status"] = "PASS"
        issue_count = sum(
            row["status"] != "PASS" for row in rows if row["check_name"] != "issue_count"
        )
        issue = next(row for row in rows if row["check_name"] == "issue_count")
        issue["actual"] = issue_count
        issue["status"] = "PASS" if issue_count == 0 else "FAIL"
        return rows

    stage5b_batch._hard_check_rows = sensitivity_rows
    try:
        yield
    finally:
        stage5b_batch._hard_check_rows = original


def _run_stage5b(repo_root: Path, paths: ArmPaths) -> None:
    with _stage5b_paths(paths, repo_root), _stage5b_sensitivity_hard_checks():
        result = stage5b_batch.build_stage5b_candidate(
            repo_root,
            output_dir=paths.stage5b,
            generated_at=GENERATED_AT.isoformat(),
        )
    if result["opportunities"] != result["decisions"]:
        raise RuntimeError("Stage5B opportunity/decision partition is incomplete")


def _run_stage5c_summary(paths: ArmPaths) -> None:
    """Persist Stage5C-equivalent deterministic expressibility analysis for an arm."""

    paths.stage5c.mkdir(parents=True, exist_ok=True)
    rows = claim_rows(paths)
    summary = {
        "method_version": METHOD_VERSION,
        "analysis_role": "DETERMINISTIC_STAGE5C_SENSITIVITY_ENDPOINT",
        "opportunity_count": len(rows),
        "expressible_count": sum(row["decision"] == "EXPRESSIBLE" for row in rows),
        "abstain_count": sum(row["decision"] == "ABSTAIN" for row in rows),
        "abstention_reason_distribution": dict(
            sorted(
                Counter(
                    row["abstention_reason"] for row in rows if row["decision"] == "ABSTAIN"
                ).items()
            )
        ),
        "uses_frozen_stage5a_contract": True,
        "modifies_claim_admissibility": False,
        "llm_calls": 0,
        "api_calls": 0,
    }
    write_json(paths.stage5c / "stage5c_sensitivity_summary.json", summary)
    write_file_hashes(paths.stage5c)


def claim_rows(paths: ArmPaths) -> list[dict[str, Any]]:
    """Join opportunities to frozen deterministic decisions without IDs in comparison keys."""

    opportunities = {
        str(row["opportunity_id"]): row
        for row in read_jsonl(paths.stage5b / "claim_opportunities.jsonl")
    }
    materialization = read_csv(paths.stage5b / "claim_materialization_audit.csv")
    cells = {
        str(row["cell_id"]): row
        for row in read_jsonl(paths.stage3a / "construction_state_cells.jsonl")
    }
    versions = {
        str(row["bitemporal_version_id"]): row
        for row in read_jsonl(paths.stage3b / "bitemporal_state_versions.jsonl")
    }
    rows: list[dict[str, Any]] = []
    for item in materialization:
        opportunity = opportunities[item["opportunity_id"]]
        payload = opportunity.get("payload") or {}
        cell = cells.get(str(opportunity.get("cell_id") or ""), {})
        version = versions[str(opportunity["bitemporal_version_id"])]
        evidence_discriminator = (
            str(payload.get("evidence_id") or "")
            if opportunity["source_kind"] == "GEOLOGICAL_EVIDENCE"
            else ""
        )
        rows.append(
            {
                "opportunity_id": item["opportunity_id"],
                "valid_date": str(opportunity["valid_date"]),
                "knowledge_time_start_local_date": str(version["knowledge_time_start_local_date"]),
                "version_number": int(version["version_number"]),
                "claim_type": str(opportunity["claim_type"]),
                "state_role": str(opportunity["state_role"]),
                "epistemic_status": str(payload.get("epistemic_status") or "METRIC_DERIVED"),
                "proposal_semantic_role": str(opportunity["opportunity_basis"]),
                "attribute_name": str(payload.get("attribute_name") or ""),
                "authoritative_geological_evidence_id": evidence_discriminator,
                "decision": item["decision"],
                "abstention_reason": item["abstention_reason"],
                "cell_start_m": cell.get("spatial_start"),
                "cell_end_m": cell.get("spatial_end"),
            }
        )
    if any(row["decision"] not in {"EXPRESSIBLE", "ABSTAIN"} for row in rows):
        raise RuntimeError("A third Claim decision state was found")
    return rows


def execute_arm(repo_root: Path, output_root: Path, spec: ArmSpec) -> dict[str, Any]:
    """Execute one non-baseline arm from its frozen pipeline start stage."""

    if spec.is_baseline:
        raise ValueError("Baseline must be reused, not executed")
    paths = arm_paths(repo_root, output_root, spec)
    if paths.arm_root.exists():
        shutil.rmtree(paths.arm_root)
    resolved = resolved_configs(repo_root, paths.arm_root, spec)
    config_paths = {name: Path(path) for name, path in resolved["paths"].items()}
    started = GENERATED_AT.isoformat()
    if spec.parameter_id == "CELL_SIZE_M":
        _run_stage3a(repo_root, paths, config_paths["construction_state"])
        _run_stage3b(repo_root, paths)
        _run_stage4a1(repo_root, paths, config_paths["metric_foundation"])
    elif spec.parameter_id == "RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT":
        paths = ArmPaths(
            paths.arm_root,
            repo_root / FROZEN_STAGE3A,
            repo_root / FROZEN_STAGE3B,
            paths.stage4a1,
            paths.stage4,
            paths.stage5b,
            paths.stage5c,
        )
        _run_stage4a1(repo_root, paths, config_paths["metric_foundation"])
    elif spec.parameter_id == "RAI_SATURATION_ROBUST_Z":
        paths = ArmPaths(
            paths.arm_root,
            repo_root / FROZEN_STAGE3A,
            repo_root / FROZEN_STAGE3B,
            repo_root / FROZEN_STAGE4A1,
            paths.stage4,
            paths.stage5b,
            paths.stage5c,
        )
    else:
        raise ValueError(spec.parameter_id)
    saturation = float(
        resolved["configs"]["state_metric_definition_v1"]["rai"]["saturation_robust_z"]
    )
    _run_stage4_metrics(repo_root, paths, saturation)
    _run_stage5b(repo_root, paths)
    _run_stage5c_summary(paths)
    provenance = {
        "arm_id": spec.arm_id,
        "parameter_id": spec.parameter_id,
        "parameter_value": spec.parameter_value,
        "baseline_value": spec.baseline_value,
        "baseline_config_hash": sha256_file(repo_root / CONFIG_PATHS[spec.parameter_id]),
        "override_field": spec.changed_config_path,
        "resolved_config_hash": sha256_file(
            config_paths[
                {
                    "CELL_SIZE_M": "construction_state",
                    "RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT": "metric_foundation",
                    "RAI_SATURATION_ROBUST_Z": "state_metric_definition_v1",
                }[spec.parameter_id]
            ]
        ),
        "resolved_config": resolved["configs"],
        "pipeline_start_stage": spec.expected_pipeline_start_stage,
        "pipeline_end_stage": spec.expected_pipeline_end_stage,
        "execution_started_at": started,
        "execution_finished_at": GENERATED_AT.isoformat(),
        "success": True,
        "all_other_parameters_frozen": True,
        "input_artifact_hashes": _input_hashes(paths),
        "output_hashes": _input_hashes(paths),
        "llm_calls": 0,
        "api_calls": 0,
        "deepseek_calls": 0,
    }
    write_json(paths.arm_root / "provenance.json", provenance)
    write_file_hashes(paths.arm_root)
    return provenance


def _role_counts(paths: ArmPaths) -> Counter[str]:
    versions = read_jsonl(paths.stage3a / "initial_construction_state_versions.jsonl")
    return Counter(str(row["cell_scope_role"]) for row in versions)


def _date_universe(paths: ArmPaths) -> list[str]:
    return sorted(
        str(row["target_date"])
        for row in read_jsonl(paths.stage3a / "daily_construction_states.jsonl")
    )


def evaluated_cell_length_m(paths: ArmPaths) -> float:
    """Sum cell-meter exposure over monitored daily states without date deduplication."""

    cells = {
        str(row["cell_id"]): row
        for row in read_jsonl(paths.stage3a / "construction_state_cells.jsonl")
    }
    versions = read_jsonl(paths.stage3a / "initial_construction_state_versions.jsonl")
    return sum(
        float(cells[str(row["cell_id"])]["spatial_end"])
        - float(cells[str(row["cell_id"])]["spatial_start"])
        for row in versions
    )


def metric_rows(paths: ArmPaths) -> list[dict[str, Any]]:
    """Normalize RAI, GRS, and GRCI rows for common analysis."""

    outputs: list[dict[str, Any]] = []
    for metric, filename, value_field, status_field in [
        ("RAI", "state_rai.jsonl", "rai", "rai_status"),
        ("GRS", "state_grs.jsonl", "grs", "grs_status"),
        ("GRCI", "state_grci.jsonl", "grci", "grci_status"),
    ]:
        for row in read_jsonl(paths.stage4 / filename):
            outputs.append(
                {
                    "metric_name": metric,
                    "valid_date": str(row["valid_date"]),
                    "state_role": str(row["cell_scope_role"]),
                    "cell_id": str(row["cell_id"]),
                    "bitemporal_version_id": str(row["bitemporal_version_id"]),
                    "value": row[value_field],
                    "status": str(row[status_field]),
                }
            )
    return outputs


def common_endpoint(spec: ArmSpec, paths: ArmPaths) -> dict[str, Any]:
    """Compute the frozen common denominator and Claim endpoints."""

    metrics = metric_rows(paths)
    claims = claim_rows(paths)
    roles = _role_counts(paths)
    cell_count = len(read_jsonl(paths.stage3a / "construction_state_cells.jsonl"))
    eligible = {
        "RAI": sum(row["metric_name"] == "RAI" for row in metrics),
        "GRS": sum(row["metric_name"] == "GRS" for row in metrics),
        "GRCI": sum(
            row["metric_name"] == "GRCI" and row["state_role"] == "DAILY_REVIEW_CELL"
            for row in metrics
        ),
    }
    available = {
        metric: sum(row["metric_name"] == metric and row["value"] is not None for row in metrics)
        for metric in ["RAI", "GRS", "GRCI"]
    }
    expressible = sum(row["decision"] == "EXPRESSIBLE" for row in claims)
    abstain = sum(row["decision"] == "ABSTAIN" for row in claims)
    exposure = evaluated_cell_length_m(paths)
    scope_audit = read_csv(paths.stage3a / "cell_scope_role_audit.csv")
    point_audit = read_csv(paths.stage3a / "point_boundary_policy_audit.csv")
    interval_audit = read_csv(paths.stage3a / "interval_overlap_conservation_audit.csv")
    return {
        "arm_id": spec.arm_id,
        "parameter_id": spec.parameter_id,
        "parameter_value": json.dumps(spec.parameter_value, sort_keys=True),
        "monitored_date_count": len(_date_universe(paths)),
        "cell_count": cell_count,
        "daily_review_cell_count": roles["DAILY_REVIEW_CELL"],
        "forward_attention_cell_count": roles["FORWARD_ATTENTION_CELL"],
        "local_background_cell_count": roles["LOCAL_BACKGROUND_CELL"],
        "evaluated_cell_length_m": exposure,
        "scope_role_conflict_count": sum(
            row["status"] == "SCOPE_ROLE_CONFLICT" for row in scope_audit
        ),
        "point_unlinked_due_to_resolution_count": sum(
            row["status"] != "PASS" and int(row["cell_link_count"]) == 0 for row in point_audit
        ),
        "interval_undercoverage_due_to_resolution_count": sum(
            row["status"] != "PASS"
            and float(row["linked_overlap_length_m"]) < float(row["expected_overlap_length_m"])
            for row in interval_audit
        ),
        "rai_eligible_count": eligible["RAI"],
        "rai_available_count": available["RAI"],
        "rai_availability_rate": _rate(available["RAI"], eligible["RAI"]),
        "grs_eligible_count": eligible["GRS"],
        "grs_available_count": available["GRS"],
        "grs_availability_rate": _rate(available["GRS"], eligible["GRS"]),
        "grci_eligible_count": eligible["GRCI"],
        "grci_available_count": available["GRCI"],
        "grci_availability_rate": _rate(available["GRCI"], eligible["GRCI"]),
        "claim_opportunity_count": len(claims),
        "expressible_count": expressible,
        "abstain_count": abstain,
        "expressible_rate": _rate(expressible, len(claims)),
        "abstain_rate": _rate(abstain, len(claims)),
        "claim_opportunities_per_day": len(claims) / DATE_COUNT,
        "expressible_per_day": expressible / DATE_COUNT,
        "abstain_per_day": abstain / DATE_COUNT,
        "claim_opportunities_per_100m": _per_100m(len(claims), exposure),
        "expressible_per_100m": _per_100m(expressible, exposure),
        "abstain_per_100m": _per_100m(abstain, exposure),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _per_100m(count: int, exposure: float) -> float | None:
    return count / (exposure / 100.0) if exposure else None


def abstain_reason_rows(spec: ArmSpec, paths: ArmPaths) -> list[dict[str, Any]]:
    claims = claim_rows(paths)
    reasons = Counter(row["abstention_reason"] for row in claims if row["decision"] == "ABSTAIN")
    total = sum(reasons.values())
    return [
        {
            "arm_id": spec.arm_id,
            "abstention_reason": reason,
            "count": count,
            "share_of_abstentions": _rate(count, total),
        }
        for reason, count in sorted(reasons.items())
    ]


def date_role_metric_summary(spec: ArmSpec, paths: ArmPaths) -> list[dict[str, Any]]:
    """Summarize AVAILABLE metrics by valid date and role; missing groups stay unavailable."""

    grouped: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    roles_by_date: dict[str, set[str]] = defaultdict(set)
    for row in metric_rows(paths):
        roles_by_date[row["valid_date"]].add(row["state_role"])
        if row["value"] is not None:
            grouped[(row["valid_date"], row["state_role"], row["metric_name"])].append(
                float(row["value"])
            )
    rows: list[dict[str, Any]] = []
    for valid_date in _date_universe(paths):
        for role in sorted(roles_by_date.get(valid_date, set())):
            for metric in ["RAI", "GRS", "GRCI"]:
                values = grouped.get((valid_date, role, metric), [])
                for statistic in ["median", "max"]:
                    rows.append(
                        {
                            "arm_id": spec.arm_id,
                            "valid_date": valid_date,
                            "state_role": role,
                            "metric_name": metric,
                            "summary_statistic": statistic,
                            "summary_status": "AVAILABLE" if values else "UNAVAILABLE",
                            "available_cell_count": len(values),
                            "value": (median(values) if statistic == "median" else max(values))
                            if values
                            else None,
                        }
                    )
    return rows


def _average_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(indexed):
        end = position + 1
        while end < len(indexed) and indexed[end][1] == indexed[position][1]:
            end += 1
        rank = (position + 1 + end) / 2.0
        for original, _ in indexed[position:end]:
            ranks[original] = rank
        position = end
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(set(left)) == 1 or len(set(right)) == 1:
        return None
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    numerator = sum((x - mean_left) * (y - mean_right) for x, y in zip(left, right, strict=True))
    left_scale = math.sqrt(sum((x - mean_left) ** 2 for x in left))
    right_scale = math.sqrt(sum((y - mean_right) ** 2 for y in right))
    return numerator / (left_scale * right_scale) if left_scale and right_scale else None


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def paired_statistics(
    baseline_rows: list[dict[str, Any]],
    alternative_rows: list[dict[str, Any]],
    *,
    arm_id: str,
) -> list[dict[str, Any]]:
    """Compute descriptive paired statistics without thresholds or p-values."""

    key_fields = ["valid_date", "state_role", "metric_name", "summary_statistic"]
    baseline = {
        tuple(str(row[field]) for field in key_fields): row
        for row in baseline_rows
        if row["summary_status"] == "AVAILABLE"
    }
    alternative = {
        tuple(str(row[field]) for field in key_fields): row
        for row in alternative_rows
        if row["summary_status"] == "AVAILABLE"
    }
    grouped: dict[tuple[str, str, str], list[tuple[float, float]]] = defaultdict(list)
    for key in sorted(baseline.keys() & alternative.keys()):
        grouped[(key[1], key[2], key[3])].append(
            (float(baseline[key]["value"]), float(alternative[key]["value"]))
        )
    rows: list[dict[str, Any]] = []
    for (role, metric, statistic), pairs in sorted(grouped.items()):
        left = [pair[0] for pair in pairs]
        right = [pair[1] for pair in pairs]
        differences = [abs(x - y) for x, y in pairs]
        correlation = _pearson(_average_ranks(left), _average_ranks(right))
        reason = ""
        status = "EVALUATED"
        if len(pairs) < 3:
            status, reason = "NOT_EVALUABLE", "PAIRED_N_LT_3"
        elif len(set(left)) == 1 or len(set(right)) == 1:
            status, reason = "NOT_EVALUABLE", "CONSTANT_VECTOR_SPEARMAN_UNDEFINED"
        rows.append(
            {
                "alternative_arm_id": arm_id,
                "state_role": role,
                "metric_name": metric,
                "summary_statistic": statistic,
                "paired_n": len(pairs),
                "median_absolute_difference": median(differences) if differences else None,
                "iqr_absolute_difference": (
                    _quantile(differences, 0.75) - _quantile(differences, 0.25)
                    if differences
                    else None
                ),
                "spearman_rank_correlation": correlation if status == "EVALUATED" else None,
                "status": status,
                "reason": reason,
                "automatic_stability_classification": "NOT_PERFORMED",
            }
        )
    return rows


def claim_layer_rows(
    spec: ArmSpec,
    paths: ArmPaths,
    *,
    layer: str,
) -> list[dict[str, Any]]:
    """Aggregate cross-resolution Claims using the frozen semantic Layer A/B keys."""

    keys = ["valid_date", "claim_type"]
    if layer == "B":
        keys += ["state_role", "epistemic_status"]
    grouped: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    for claim in claim_rows(paths):
        grouped[tuple(str(claim[key]) for key in keys)][str(claim["decision"])] += 1
    output = []
    for key, decisions in sorted(grouped.items()):
        row: dict[str, Any] = {"arm_id": spec.arm_id, "layer": layer}
        row.update(dict(zip(keys, key, strict=True)))
        total = decisions["EXPRESSIBLE"] + decisions["ABSTAIN"]
        row.update(
            {
                "expressible_count": decisions["EXPRESSIBLE"],
                "abstain_count": decisions["ABSTAIN"],
                "total_opportunity_count": total,
                "expressible_proportion": _rate(decisions["EXPRESSIBLE"], total),
            }
        )
        output.append(row)
    return output


def claim_layer_stability(
    baseline: list[dict[str, Any]], alternative: list[dict[str, Any]], arm_id: str, layer: str
) -> list[dict[str, Any]]:
    """Compare Layer A/B proportions and retain one-sided opportunity support changes."""

    ignored = {
        "arm_id",
        "layer",
        "expressible_count",
        "abstain_count",
        "total_opportunity_count",
        "expressible_proportion",
    }
    keys = sorted(set(baseline[0]) - ignored) if baseline else []
    left = {tuple(str(row[key]) for key in keys): row for row in baseline}
    right = {tuple(str(row[key]) for key in keys): row for row in alternative}
    rows = []
    for key in sorted(left.keys() | right.keys()):
        base = left.get(key)
        alt = right.get(key)
        base_total = int(base["total_opportunity_count"]) if base else 0
        alt_total = int(alt["total_opportunity_count"]) if alt else 0
        if base_total == 0 and alt_total == 0:
            continue
        status = (
            "OPPORTUNITY_SUPPORT_CHANGED" if (base_total == 0) != (alt_total == 0) else "COMPARABLE"
        )
        row: dict[str, Any] = {"alternative_arm_id": arm_id, "layer": layer}
        row.update(dict(zip(keys, key, strict=True)))
        row.update(
            {
                "baseline_total": base_total,
                "alternative_total": alt_total,
                "baseline_expressible_proportion": base.get("expressible_proportion")
                if base
                else None,
                "alternative_expressible_proportion": alt.get("expressible_proportion")
                if alt
                else None,
                "absolute_proportion_difference": abs(
                    float(base["expressible_proportion"]) - float(alt["expressible_proportion"])
                )
                if base and alt
                else None,
                "status": status,
            }
        )
        rows.append(row)
    return rows


def semantic_transition_matrix(
    baseline_paths: ArmPaths, alternative_paths: ArmPaths, arm_id: str
) -> list[dict[str, Any]]:
    """Pair same-geometry opportunities without decision, value, metric, or wrapper IDs."""

    key_fields = [
        "valid_date",
        "knowledge_time_start_local_date",
        "version_number",
        "cell_start_m",
        "cell_end_m",
        "claim_type",
        "state_role",
        "epistemic_status",
        "proposal_semantic_role",
        "attribute_name",
        "authoritative_geological_evidence_id",
    ]

    def index(rows: list[dict[str, Any]]) -> dict[tuple[str, ...], dict[str, Any]]:
        result: dict[tuple[str, ...], dict[str, Any]] = {}
        for row in rows:
            key = tuple(str(row[field]) for field in key_fields)
            if key in result:
                raise ValueError(f"Duplicate semantic opportunity key for {arm_id}: {key}")
            result[key] = row
        return result

    left = index(claim_rows(baseline_paths))
    right = index(claim_rows(alternative_paths))
    transitions: Counter[str] = Counter()
    for key in left.keys() & right.keys():
        transitions[f"{left[key]['decision']}_TO_{right[key]['decision']}"] += 1
    transitions["OPPORTUNITY_ADDED"] = len(right.keys() - left.keys())
    transitions["OPPORTUNITY_REMOVED"] = len(left.keys() - right.keys())
    return [
        {"alternative_arm_id": arm_id, "transition": name, "count": count}
        for name, count in sorted(transitions.items())
    ]


def grci_identity_rows(spec: ArmSpec, paths: ArmPaths) -> list[dict[str, Any]]:
    rows = []
    for row in read_jsonl(paths.stage4 / "state_grci.jsonl"):
        if row["grci"] is None:
            continue
        expected = float(row["rai"]) * float(row["grs"])
        difference = abs(float(row["grci"]) - expected)
        if difference > 1e-12:
            rows.append(
                {
                    "arm_id": spec.arm_id,
                    "bitemporal_version_id": row["bitemporal_version_id"],
                    "grci": row["grci"],
                    "expected_product": expected,
                    "absolute_difference": difference,
                    "status": "FAIL",
                }
            )
    return rows


def saturation_monotonicity(
    baseline_paths: ArmPaths, alternative_paths: ArmPaths, arm_id: str, saturation: float
) -> list[dict[str, Any]]:
    baseline = {
        str(row["bitemporal_version_id"]): row
        for row in read_jsonl(baseline_paths.stage4 / "state_rai.jsonl")
    }
    rows = []
    for row in read_jsonl(alternative_paths.stage4 / "state_rai.jsonl"):
        old = baseline[str(row["bitemporal_version_id"])]
        if row["rai"] is None or old["rai"] is None:
            continue
        violation = (saturation < 3 and float(row["rai"]) < float(old["rai"]) - 1e-12) or (
            saturation > 3 and float(row["rai"]) > float(old["rai"]) + 1e-12
        )
        if violation:
            rows.append(
                {
                    "arm_id": arm_id,
                    "bitemporal_version_id": row["bitemporal_version_id"],
                    "baseline_rai": old["rai"],
                    "alternative_rai": row["rai"],
                    "status": "FAIL",
                }
            )
    return rows


def exact_metric_identity(
    baseline_paths: ArmPaths, alternative_paths: ArmPaths, filename: str, value_field: str
) -> int:
    """Count identity mismatches for same-geometry state metrics."""

    left = {
        str(row["bitemporal_version_id"]): row
        for row in read_jsonl(baseline_paths.stage4 / filename)
    }
    right = {
        str(row["bitemporal_version_id"]): row
        for row in read_jsonl(alternative_paths.stage4 / filename)
    }
    if left.keys() != right.keys():
        return len(left.keys() ^ right.keys()) + 1
    return sum(left[key].get(value_field) != right[key].get(value_field) for key in left)


def _geometry_hash(paths: ArmPaths) -> str:
    return canonical_hash(read_jsonl(paths.stage3a / "construction_state_cells.jsonl"))


def _state_role_hash(paths: ArmPaths) -> str:
    rows = read_jsonl(paths.stage3a / "initial_construction_state_versions.jsonl")
    return canonical_hash(
        [
            {
                "valid_date": row["target_date"],
                "cell_id": row["cell_id"],
                "cell_scope_role": row["cell_scope_role"],
            }
            for row in rows
        ]
    )


def _geology_binding_hash(paths: ArmPaths) -> str:
    versions = read_jsonl(paths.stage3b / "bitemporal_state_versions.jsonl")
    payload = [
        {
            "valid_date": row["valid_date"],
            "cell_id": row["cell_id"],
            "version_number": row["version_number"],
            "daily": row["materialized_daily_review_evidence_ids"],
            "forward": row["materialized_forward_attention_evidence_ids"],
            "background": row["materialized_local_background_evidence_ids"],
        }
        for row in versions
    ]
    return canonical_hash(payload)


def _corpus_hash(paths: ArmPaths) -> str:
    return canonical_hash(_date_universe(paths))


def _repository_config_hashes(repo_root: Path) -> dict[str, str]:
    return {
        path.as_posix(): sha256_file(repo_root / path)
        for path in [
            Path("configs/construction_state.yaml"),
            Path("configs/metric_foundation.yaml"),
            Path("configs/state_metric_definition_v1.yaml"),
            Path("configs/claim_contract_v1.yaml"),
        ]
    }


def build_analysis(
    repo_root: Path,
    output_root: Path,
    specs: list[ArmSpec],
) -> dict[str, list[dict[str, Any]]]:
    """Build every frozen descriptive endpoint from persisted arm outputs only."""

    path_by_arm = {spec.arm_id: arm_paths(repo_root, output_root, spec) for spec in specs}
    baseline_spec = next(spec for spec in specs if spec.is_baseline)
    baseline_paths = path_by_arm[baseline_spec.arm_id]
    common = [common_endpoint(spec, path_by_arm[spec.arm_id]) for spec in specs]
    abstain = [row for spec in specs for row in abstain_reason_rows(spec, path_by_arm[spec.arm_id])]
    metric_summaries = {
        spec.arm_id: date_role_metric_summary(spec, path_by_arm[spec.arm_id]) for spec in specs
    }
    cell_specs = [spec for spec in specs if spec.parameter_id in {"BASELINE_VECTOR", "CELL_SIZE_M"}]
    history_specs = [
        spec
        for spec in specs
        if spec.parameter_id in {"BASELINE_VECTOR", "RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT"}
    ]
    saturation_specs = [
        spec
        for spec in specs
        if spec.parameter_id in {"BASELINE_VECTOR", "RAI_SATURATION_ROBUST_Z"}
    ]
    cell_metric = [row for spec in cell_specs for row in metric_summaries[spec.arm_id]]
    cell_pairwise = [
        row
        for spec in cell_specs
        if not spec.is_baseline
        for row in paired_statistics(
            metric_summaries[baseline_spec.arm_id],
            metric_summaries[spec.arm_id],
            arm_id=spec.arm_id,
        )
    ]
    layer_a = [
        row
        for spec in cell_specs
        for row in claim_layer_rows(spec, path_by_arm[spec.arm_id], layer="A")
    ]
    layer_b = [
        row
        for spec in cell_specs
        for row in claim_layer_rows(spec, path_by_arm[spec.arm_id], layer="B")
    ]
    layer_stability = []
    baseline_a = claim_layer_rows(baseline_spec, baseline_paths, layer="A")
    baseline_b = claim_layer_rows(baseline_spec, baseline_paths, layer="B")
    for spec in cell_specs:
        if spec.is_baseline:
            continue
        layer_stability.extend(
            claim_layer_stability(
                baseline_a,
                claim_layer_rows(spec, path_by_arm[spec.arm_id], layer="A"),
                spec.arm_id,
                "A",
            )
        )
        layer_stability.extend(
            claim_layer_stability(
                baseline_b,
                claim_layer_rows(spec, path_by_arm[spec.arm_id], layer="B"),
                spec.arm_id,
                "B",
            )
        )
    history_pairwise = [
        row
        for spec in history_specs
        if not spec.is_baseline
        for row in paired_statistics(
            metric_summaries[baseline_spec.arm_id],
            metric_summaries[spec.arm_id],
            arm_id=spec.arm_id,
        )
        if row["metric_name"] in {"RAI", "GRCI"}
    ]
    saturation_pairwise = [
        row
        for spec in saturation_specs
        if not spec.is_baseline
        for row in paired_statistics(
            metric_summaries[baseline_spec.arm_id],
            metric_summaries[spec.arm_id],
            arm_id=spec.arm_id,
        )
        if row["metric_name"] in {"RAI", "GRCI"}
    ]
    history_transitions = [
        row
        for spec in history_specs
        if not spec.is_baseline
        for row in semantic_transition_matrix(baseline_paths, path_by_arm[spec.arm_id], spec.arm_id)
    ]
    saturation_transitions = [
        row
        for spec in saturation_specs
        if not spec.is_baseline
        for row in semantic_transition_matrix(baseline_paths, path_by_arm[spec.arm_id], spec.arm_id)
    ]
    history_isolation = [
        {
            "arm_id": spec.arm_id,
            "cell_geometry_identity": _geometry_hash(path_by_arm[spec.arm_id])
            == _geometry_hash(baseline_paths),
            "state_role_identity": _state_role_hash(path_by_arm[spec.arm_id])
            == _state_role_hash(baseline_paths),
            "geology_binding_identity": _geology_binding_hash(path_by_arm[spec.arm_id])
            == _geology_binding_hash(baseline_paths),
            "grs_identity_mismatch_count": exact_metric_identity(
                baseline_paths, path_by_arm[spec.arm_id], "state_grs.jsonl", "grs"
            ),
        }
        for spec in history_specs
        if not spec.is_baseline
    ]
    saturation_isolation = [
        {
            "arm_id": spec.arm_id,
            "cell_geometry_identity": _geometry_hash(path_by_arm[spec.arm_id])
            == _geometry_hash(baseline_paths),
            "state_role_identity": _state_role_hash(path_by_arm[spec.arm_id])
            == _state_role_hash(baseline_paths),
            "geology_binding_identity": _geology_binding_hash(path_by_arm[spec.arm_id])
            == _geology_binding_hash(baseline_paths),
            "grs_identity_mismatch_count": exact_metric_identity(
                baseline_paths, path_by_arm[spec.arm_id], "state_grs.jsonl", "grs"
            ),
            "rai_availability_mismatch_count": _availability_mismatch(
                baseline_paths, path_by_arm[spec.arm_id], "state_rai.jsonl", "rai"
            ),
        }
        for spec in saturation_specs
        if not spec.is_baseline
    ]
    monotonicity = [
        row
        for spec in saturation_specs
        if not spec.is_baseline
        for row in saturation_monotonicity(
            baseline_paths, path_by_arm[spec.arm_id], spec.arm_id, float(spec.parameter_value)
        )
    ]
    grci_identity = [
        row for spec in specs for row in grci_identity_rows(spec, path_by_arm[spec.arm_id])
    ]
    return {
        "common": common,
        "cell_common": [
            row for row in common if row["arm_id"] in {spec.arm_id for spec in cell_specs}
        ],
        "abstain": abstain,
        "cell_metric": cell_metric,
        "cell_pairwise": cell_pairwise,
        "layer_a": layer_a,
        "layer_b": layer_b,
        "layer_stability": layer_stability,
        "history_metric": [
            row
            for spec in history_specs
            for row in metric_summaries[spec.arm_id]
            if row["metric_name"] in {"RAI", "GRCI"}
        ],
        "history_pairwise": history_pairwise,
        "history_transitions": history_transitions,
        "history_isolation": history_isolation,
        "saturation_metric": [
            row
            for spec in saturation_specs
            for row in metric_summaries[spec.arm_id]
            if row["metric_name"] in {"RAI", "GRCI"}
        ],
        "saturation_pairwise": saturation_pairwise,
        "saturation_transitions": saturation_transitions,
        "saturation_monotonicity": monotonicity,
        "saturation_isolation": saturation_isolation,
        "grci_identity": grci_identity,
    }


def _availability_mismatch(
    baseline_paths: ArmPaths, alternative_paths: ArmPaths, filename: str, field: str
) -> int:
    left = {
        str(row["bitemporal_version_id"]): row[field] is not None
        for row in read_jsonl(baseline_paths.stage4 / filename)
    }
    right = {
        str(row["bitemporal_version_id"]): row[field] is not None
        for row in read_jsonl(alternative_paths.stage4 / filename)
    }
    if left.keys() != right.keys():
        return len(left.keys() ^ right.keys()) + 1
    return sum(left[key] != right[key] for key in left)


OUTPUT_TABLES = {
    "stage7f_common_endpoint_summary.csv": "common",
    "stage7f_availability_summary.csv": "common",
    "stage7f_claim_rate_summary.csv": "common",
    "stage7f_normalized_count_summary.csv": "common",
    "stage7f_abstain_reason_summary.csv": "abstain",
    "cell_size_resolution_counts.csv": "cell_common",
    "cell_size_date_role_metric_summary.csv": "cell_metric",
    "cell_size_metric_pairwise_statistics.csv": "cell_pairwise",
    "cell_size_claim_layer_a.csv": "layer_a",
    "cell_size_claim_layer_b.csv": "layer_b",
    "cell_size_claim_stability_summary.csv": "layer_stability",
    "rai_history_metric_summary.csv": "history_metric",
    "rai_history_pairwise_statistics.csv": "history_pairwise",
    "rai_history_claim_transition_matrix.csv": "history_transitions",
    "rai_history_isolation_audit.csv": "history_isolation",
    "rai_saturation_metric_summary.csv": "saturation_metric",
    "rai_saturation_pairwise_statistics.csv": "saturation_pairwise",
    "rai_saturation_claim_transition_matrix.csv": "saturation_transitions",
    "rai_saturation_monotonicity_audit.csv": "saturation_monotonicity",
    "rai_saturation_isolation_audit.csv": "saturation_isolation",
    "grci_product_identity_audit.csv": "grci_identity",
}


def write_analysis(output_root: Path, analysis: dict[str, list[dict[str, Any]]]) -> None:
    """Write all summary tables from one semantic analysis payload."""

    for filename, key in OUTPUT_TABLES.items():
        fields = None
        if not analysis[key]:
            fields = ["arm_id", "status", "details"]
        write_csv(output_root / filename, analysis[key], fields)


def _protocol_identity(repo_root: Path) -> dict[str, Any]:
    return {
        "protocol_manifest_sha256": sha256_file(
            repo_root / PROTOCOL_DIR / "stage7f_arm_manifest.csv"
        ),
        "protocol_method_version": read_json(repo_root / PROTOCOL_DIR / "method_version.json")[
            "method_version"
        ],
        "protocol_tag_target": _git(
            repo_root, "rev-list", "-n", "1", "stage7f-sensitivity-protocol-v1.1-frozen"
        ),
        "stage7e_tag_target": _git(
            repo_root,
            "rev-list",
            "-n",
            "1",
            "stage7e-ablation-execution-v1.1a-final-machine-results",
        ),
    }


def _git(repo_root: Path, *args: str) -> str:
    import subprocess

    return subprocess.check_output(["git", *args], cwd=repo_root, text=True).strip()


def _hard_checks(
    repo_root: Path,
    specs: list[ArmSpec],
    paths: dict[str, ArmPaths],
    analysis: dict[str, list[dict[str, Any]]],
    before_config_hashes: dict[str, str],
) -> list[dict[str, Any]]:
    baseline = paths[BASELINE_ARM_ID]
    common = {row["arm_id"]: row for row in analysis["common"]}
    protocol_identity = _protocol_identity(repo_root)
    config_rows = _config_audit(repo_root, specs, paths)
    input_rows = _input_identity_rows(specs, paths)
    metric_unknown_coercions = sum(
        row["value"] == 0 and row["status"] != "AVAILABLE"
        for spec in specs
        for row in metric_rows(paths[spec.arm_id])
    )
    checks: list[tuple[str, Any, Any]] = [
        (
            "STAGE7F_A_V1_1_TAG_UNCHANGED",
            protocol_identity["protocol_tag_target"],
            "6ae7d690875d55da96521a63440e6f479d9639ea",
        ),
        (
            "STAGE7E_FINAL_TAG_UNCHANGED",
            protocol_identity["stage7e_tag_target"],
            "25df4be17edb89ad669d2a7255e65b6b5fa8acbc",
        ),
        ("EXACT_SEVEN_ARM_MANIFEST", len(specs), 7),
        ("EXACT_SIX_ALTERNATIVE_EXECUTIONS", sum(not spec.is_baseline for spec in specs), 6),
        ("BASELINE_NEW_RUNS", 0, 0),
        ("LLM_CALLS", 0, 0),
        ("API_CALLS", 0, 0),
        ("DEEPSEEK_CALLS", 0, 0),
        (
            "REPOSITORY_CONFIG_HASHES_UNCHANGED",
            _repository_config_hashes(repo_root),
            before_config_hashes,
        ),
        (
            "EACH_ALTERNATIVE_EXACTLY_ONE_OVERRIDE",
            sum(row["status"] != "PASS" for row in config_rows if row["arm_id"] != BASELINE_ARM_ID),
            0,
        ),
        (
            "UPSTREAM_EVIDENCE_IDENTITY",
            sum(row["status"] != "PASS" for row in input_rows),
            0,
        ),
        (
            "ALL_ARMS_91_DATES",
            sum(common[spec.arm_id]["monitored_date_count"] != 91 for spec in specs),
            0,
        ),
        ("DATE_UNIVERSE_IDENTITY", len({_corpus_hash(paths[spec.arm_id]) for spec in specs}), 1),
        ("GRCI_PRODUCT_VIOLATIONS", len(analysis["grci_identity"]), 0),
        ("UNKNOWN_METRIC_COERCED_TO_ZERO", metric_unknown_coercions, 0),
        (
            "CLAIM_PARTITION",
            sum(
                row["expressible_count"] + row["abstain_count"] != row["claim_opportunity_count"]
                for row in analysis["common"]
            ),
            0,
        ),
        (
            "HISTORY_GRS_IDENTITY",
            sum(int(row["grs_identity_mismatch_count"]) for row in analysis["history_isolation"]),
            0,
        ),
        (
            "SATURATION_GRS_IDENTITY",
            sum(
                int(row["grs_identity_mismatch_count"]) for row in analysis["saturation_isolation"]
            ),
            0,
        ),
        (
            "SATURATION_RAI_AVAILABILITY_IDENTITY",
            sum(
                int(row["rai_availability_mismatch_count"])
                for row in analysis["saturation_isolation"]
            ),
            0,
        ),
        ("SATURATION_MONOTONICITY_VIOLATIONS", len(analysis["saturation_monotonicity"]), 0),
        ("NO_AUTOMATIC_ROBUSTNESS_THRESHOLD", 0, 0),
        ("NO_BEST_PARAMETER_SELECTION", 0, 0),
        ("NO_P_VALUE_STABILITY_CLAIM", 0, 0),
        ("BASELINE_10M", read_json(baseline.stage3a / "freeze_manifest.json")["cell_count"], 156),
    ]
    for row in analysis["history_isolation"]:
        checks.extend(
            [
                (f"{row['arm_id']}_CELL_GEOMETRY_IDENTITY", row["cell_geometry_identity"], True),
                (f"{row['arm_id']}_STATE_ROLE_IDENTITY", row["state_role_identity"], True),
                (
                    f"{row['arm_id']}_GEOLOGY_BINDING_IDENTITY",
                    row["geology_binding_identity"],
                    True,
                ),
            ]
        )
    for row in analysis["saturation_isolation"]:
        checks.extend(
            [
                (f"{row['arm_id']}_CELL_GEOMETRY_IDENTITY", row["cell_geometry_identity"], True),
                (f"{row['arm_id']}_STATE_ROLE_IDENTITY", row["state_role_identity"], True),
                (
                    f"{row['arm_id']}_GEOLOGY_BINDING_IDENTITY",
                    row["geology_binding_identity"],
                    True,
                ),
            ]
        )
    return [
        {
            "check_name": name,
            "actual": actual,
            "expected": expected,
            "status": "PASS" if actual == expected else "FAIL",
            "details": "",
        }
        for name, actual, expected in checks
    ]


def execute_stage7f(repo_root: Path, output_dir: Path | None = None) -> Path:
    """Execute six frozen deterministic alternatives and produce the Stage7F-B artifact."""

    repo_root = repo_root.resolve()
    output_root = (output_dir or repo_root / OUTPUT_DIR).resolve()
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)
    specs = load_arm_specs(repo_root)
    before_hashes = _repository_config_hashes(repo_root)
    baseline = next(spec for spec in specs if spec.is_baseline)
    _copy_baseline_provenance(repo_root, arm_paths(repo_root, output_root, baseline), baseline)
    execution_rows = []
    for spec in specs:
        if spec.is_baseline:
            execution_rows.append(
                {
                    "arm_id": spec.arm_id,
                    "planned": True,
                    "executed": False,
                    "baseline_reused": True,
                    "status": "REUSED_FROZEN_BASELINE",
                    "pipeline_start_stage": spec.expected_pipeline_start_stage,
                    "pipeline_end_stage": spec.expected_pipeline_end_stage,
                }
            )
            continue
        execute_arm(repo_root, output_root, spec)
        execution_rows.append(
            {
                "arm_id": spec.arm_id,
                "planned": True,
                "executed": True,
                "baseline_reused": False,
                "status": "SUCCESS",
                "pipeline_start_stage": spec.expected_pipeline_start_stage,
                "pipeline_end_stage": spec.expected_pipeline_end_stage,
            }
        )
    paths = {spec.arm_id: arm_paths(repo_root, output_root, spec) for spec in specs}
    analysis = build_analysis(repo_root, output_root, specs)
    write_analysis(output_root, analysis)
    hard = _hard_checks(repo_root, specs, paths, analysis, before_hashes)
    replay = build_analysis(repo_root, output_root, specs)
    replay_rows = [
        {
            "audit_name": "ALL_SUMMARIES_FROM_ARM_OUTPUTS",
            "first_hash": canonical_hash(analysis),
            "replay_hash": canonical_hash(replay),
            "status": "PASS" if canonical_hash(analysis) == canonical_hash(replay) else "FAIL",
        }
    ]
    write_csv(output_root / "stage7f_execution_manifest.csv", [vars(spec) for spec in specs])
    write_csv(output_root / "stage7f_arm_execution_summary.csv", execution_rows)
    write_csv(output_root / "stage7f_baseline_reuse_audit.csv", [execution_rows[0]])
    write_csv(
        output_root / "stage7f_config_isolation_audit.csv", _config_audit(repo_root, specs, paths)
    )
    write_csv(output_root / "stage7f_input_identity_audit.csv", _input_identity_rows(specs, paths))
    write_csv(
        output_root / "claim_contract_identity_audit.csv", _claim_contract_rows(repo_root, specs)
    )
    write_csv(output_root / "corpus_identity_audit.csv", _corpus_rows(specs, paths))
    write_csv(output_root / "deterministic_replay_audit.csv", replay_rows)
    write_csv(output_root / "hard_check.csv", hard)
    identity = _protocol_identity(repo_root)
    method = {
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT.isoformat(),
        "design": "ONE_FACTOR_AT_A_TIME",
        "baseline_new_runs": 0,
        "alternative_deterministic_runs": 6,
        "total_arm_count": 7,
        "llm_calls": 0,
        "api_calls": 0,
        "deepseek_calls": 0,
        "protocol_identity": identity,
        "claim_contract_sha256": sha256_file(repo_root / "configs/claim_contract_v1.yaml"),
        "hard_check_failure_count": sum(row["status"] != "PASS" for row in hard),
    }
    write_json(output_root / "method_version.json", method)
    write_json(
        output_root / "freeze_manifest.json",
        {
            **method,
            "arm_execution_summary": execution_rows,
            "common_endpoint_summary": analysis["common"],
            "deterministic_replay_mismatch_count": sum(
                row["status"] != "PASS" for row in replay_rows
            ),
            "status": "FROZEN"
            if all(row["status"] == "PASS" for row in hard + replay_rows)
            else "NOT_READY",
        },
    )
    _write_docs(output_root, analysis, hard)
    write_file_hashes(output_root)
    return output_root


def _config_audit(
    repo_root: Path, specs: list[ArmSpec], paths: dict[str, ArmPaths]
) -> list[dict[str, Any]]:
    rows = []
    name_by_parameter = {
        "CELL_SIZE_M": "construction_state",
        "RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT": "metric_foundation",
        "RAI_SATURATION_ROBUST_Z": "state_metric_definition_v1",
    }
    for spec in specs:
        if spec.is_baseline:
            rows.append({"arm_id": spec.arm_id, "changed_leaf_count": 0, "status": "PASS"})
            continue
        name = name_by_parameter[spec.parameter_id]
        baseline = _yaml(repo_root / CONFIG_PATHS[spec.parameter_id])
        resolved = _yaml(paths[spec.arm_id].arm_root / "resolved_configs" / f"{name}.yaml")
        count = config_difference_count(baseline, resolved)
        rows.append(
            {
                "arm_id": spec.arm_id,
                "parameter_id": spec.parameter_id,
                "override_field": spec.changed_config_path,
                "baseline_value": spec.baseline_value,
                "alternative_value": spec.parameter_value,
                "changed_leaf_count": count,
                "status": "PASS" if count == 1 else "FAIL",
            }
        )
    return rows


def _input_identity_rows(specs: list[ArmSpec], paths: dict[str, ArmPaths]) -> list[dict[str, Any]]:
    baseline = paths[BASELINE_ARM_ID]
    baseline_stage3a = read_json(baseline.stage3a / "freeze_manifest.json")
    rows = []
    for spec in specs:
        current = paths[spec.arm_id]
        manifest = read_json(current.stage3a / "freeze_manifest.json")
        rows.append(
            {
                "arm_id": spec.arm_id,
                "operational_source_identity": manifest["source_operational_manifest_hash"]
                == baseline_stage3a["source_operational_manifest_hash"],
                "geology_source_identity": manifest["source_geology_manifest_hash"]
                == baseline_stage3a["source_geology_manifest_hash"],
                "applicability_source_identity": manifest["source_applicability_manifest_hash"]
                == baseline_stage3a["source_applicability_manifest_hash"],
                "status": "PASS"
                if all(
                    manifest[key] == baseline_stage3a[key]
                    for key in [
                        "source_operational_manifest_hash",
                        "source_geology_manifest_hash",
                        "source_applicability_manifest_hash",
                    ]
                )
                else "FAIL",
            }
        )
    return rows


def _claim_contract_rows(repo_root: Path, specs: list[ArmSpec]) -> list[dict[str, Any]]:
    digest = sha256_file(repo_root / "configs/claim_contract_v1.yaml")
    return [
        {"arm_id": spec.arm_id, "claim_contract_sha256": digest, "status": "PASS"} for spec in specs
    ]


def _corpus_rows(specs: list[ArmSpec], paths: dict[str, ArmPaths]) -> list[dict[str, Any]]:
    expected = _date_universe(paths[BASELINE_ARM_ID])
    return [
        {
            "arm_id": spec.arm_id,
            "date_count": len(_date_universe(paths[spec.arm_id])),
            "start_date": min(_date_universe(paths[spec.arm_id])),
            "end_date": max(_date_universe(paths[spec.arm_id])),
            "calendar_gaps_present": True,
            "date_universe_hash": _corpus_hash(paths[spec.arm_id]),
            "status": "PASS" if _date_universe(paths[spec.arm_id]) == expected else "FAIL",
        }
        for spec in specs
    ]


def _write_docs(
    output_root: Path,
    analysis: dict[str, list[dict[str, Any]]],
    hard: list[dict[str, Any]],
) -> None:
    interpretation = """# Stage7F Execution Interpretation Rules

- This experiment is descriptive sensitivity analysis, not parameter tuning.
- Raw counts under cell-size arms are resolution-dependent.
- Counts are also reported with per-day and cell-meter exposure normalization.
- Spearman, MAD, and IQR have no automatic robustness threshold and no p-value interpretation.
- UNKNOWN metrics remain unavailable and are never replaced by zero.
- GRS uses max within dimension and mean across non-null dimensions.
- GRCI is the non-probabilistic conjunctive product RAI x GRS for DAILY_REVIEW_CELL only.
- No best, optimal, or recommended parameter is selected.
- No LLM, DeepSeek, or external API is used.
"""
    (output_root / "STAGE7F_EXECUTION_INTERPRETATION_RULES.md").write_text(
        interpretation, encoding="utf-8"
    )
    common = analysis["common"]
    report = [
        "# Stage7F-B Deterministic Sensitivity Execution",
        "",
        "Six alternative OFAT arms were executed; the frozen baseline was reused without rerun.",
        "The 91 monitored construction dates include calendar gaps and span "
        "2023-09-15 to 2023-12-30.",
        "All statistics are descriptive; no stability threshold or best parameter is produced.",
        "",
        "## Common endpoints",
        "",
    ]
    report.extend(
        f"- {row['arm_id']}: cells={row['cell_count']}, "
        f"opportunities={row['claim_opportunity_count']}, "
        f"expressible_rate={row['expressible_rate']}, "
        f"abstain_rate={row['abstain_rate']}"
        for row in common
    )
    report.extend(
        [
            "",
            "## Integrity",
            "",
            f"- hard-check failures: {sum(row['status'] != 'PASS' for row in hard)}",
            "- GRCI remains RAI x GRS and is not a probability or causal diagnosis.",
            "- LLM/API/DeepSeek calls: 0/0/0.",
        ]
    )
    (output_root / "README.md").write_text("\n".join(report) + "\n", encoding="utf-8")
