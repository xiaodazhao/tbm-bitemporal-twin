"""Stage7E-B v1.1a metadata-only final machine-result cleanup."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tbm_twin.evaluation.stage7e_audit_correction import (
    OLD_ARTIFACT_DIR,
    OLD_COMMIT,
    OLD_TAG,
    _raw_identity,
    engineering_decimal_tokens_v2,
    numeric_value_status_v2,
)
from tbm_twin.evaluation.stage7e_execution import _load_attempts
from tbm_twin.realization.io import stable_hash

CORRECTION_DIR = Path("configs/frozen_inputs/stage7e_v1_1_correction")
OUTPUT_DIR = Path("artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup")
CORRECTION_TAG = "stage7e-ablation-execution-v1.1-audit-corrected"
CORRECTION_COMMIT = "7ffcd0921d89880d512f070596438f863666d60c"
METHOD_VERSION = "stage7e_ablation_execution_v1_1a_metadata_cleanup"
SCHEMA_VERSION = "stage7e_final_machine_result_summary.v1.1a"
AUDIT_ZIP = "stage7e_ablation_execution_v1_1a_metadata_cleanup_audit.zip"


class Stage7EMetadataCleanupError(RuntimeError):
    """Raised when immutable inputs or final result semantics do not reconcile."""


def build_stage7e_metadata_cleanup(
    repo_root: Path,
    *,
    output_dir: Path | None = None,
    generated_at: str | None = None,
    create_audit_zip: bool = True,
) -> dict[str, Any]:
    """Build final Stage7E machine-result metadata without model execution."""

    root = repo_root.resolve()
    output = output_dir or root / OUTPUT_DIR
    _require_frozen_refs(root)
    correction_identity = _correction_baseline_identity(root)
    attempts = _load_attempts(root / OLD_ARTIFACT_DIR)
    raw_identity = _raw_identity(root, attempts)
    strict_numeric_rows = _strict_numeric_audit(root)
    summary = _final_summary(root, strict_numeric_rows)
    legacy = _legacy_registry(root)
    first_hash = stable_hash({"summary": summary, "legacy": legacy})
    second_hash = stable_hash(
        {
            "summary": _final_summary(root, _strict_numeric_audit(root)),
            "legacy": _legacy_registry(root),
        }
    )
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "stage7e_final_machine_result_summary.json", summary)
    _write_json(output / "legacy_superseded_result_registry.json", legacy)
    _write_csv(output / "a3_corrected_strict_numeric_audit.csv", strict_numeric_rows)
    _write_csv(output / "old_v1_1_correction_identity_audit.csv", correction_identity)
    _write_csv(output / "raw_response_identity_audit.csv", raw_identity)
    checks = _hard_checks(
        root,
        summary,
        legacy,
        correction_identity,
        raw_identity,
        first_hash,
        second_hash,
    )
    _write_csv(output / "hard_check.csv", checks)
    timestamp = generated_at or datetime.now(tz=UTC).isoformat()
    method = {
        "method_version": METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": timestamp,
        "operation": "REFERENCE_METADATA_INTERPRETATION_CLEANUP_ONLY",
        "recommended_machine_result_summary": (
            OUTPUT_DIR / "stage7e_final_machine_result_summary.json"
        ).as_posix(),
        "source_execution_tag": OLD_TAG,
        "source_execution_commit": OLD_COMMIT,
        "source_corrected_audit_tag": CORRECTION_TAG,
        "source_corrected_audit_commit": CORRECTION_COMMIT,
        "numeric_evaluator": "engineering_decimal_tokens_v2",
        "numeric_token_pattern": r"(?<![\d.])-?\d+(?:\.\d+)?(?![\d.])",
        "semantic_replay_hash": first_hash,
        "new_api_calls": 0,
        "new_llm_calls": 0,
        "new_deepseek_calls": 0,
    }
    freeze = {
        **method,
        "status": "FINAL_MACHINE_RESULTS_FROZEN",
        "hard_check_failure_count": sum(row["status"] != "PASS" for row in checks),
        "summary": summary,
        "legacy_superseded_results": legacy,
    }
    _write_json(output / "method_version.json", method)
    _write_json(output / "freeze_manifest.json", freeze)
    (output / "README.md").write_text(_readme(summary), encoding="utf-8")
    (output / "STAGE7E_FINAL_RESULT_SEMANTICS.md").write_text(
        _result_semantics(summary), encoding="utf-8"
    )
    _write_hashes(output)
    if create_audit_zip:
        write_audit_zip(root, output)
    failures = sum(row["status"] != "PASS" for row in checks)
    if failures:
        raise Stage7EMetadataCleanupError(f"Stage7E-B v1.1a hard checks failed: {failures}")
    return {
        "status": freeze["status"],
        "hard_check_failure_count": 0,
        "semantic_replay_hash": first_hash,
        "summary": summary,
    }


def _strict_numeric_audit(root: Path) -> list[dict[str, Any]]:
    protocol = root / "artifacts/stage7e_ablation_protocol_v1_2"
    claims = {
        row["claim_id"]: row
        for row in _read_csv(protocol / "a3_typed_claim_realization_manifest.csv")
    }
    results = _read_csv(root / OLD_ARTIFACT_DIR / "a3_claim_results.csv")
    rows: list[dict[str, Any]] = []
    for result in results:
        if result["mapping_complete"] != "True":
            continue
        claim = claims[str(result["claim_id"])]
        value = json.loads(claim["claim_value"])
        expected = value.get("metric_value")
        if not isinstance(expected, (int, float)) or isinstance(expected, bool):
            continue
        sentence = str(result["sentence"])
        rows.append(
            {
                "claim_id": result["claim_id"],
                "task_id": result["task_id"],
                "request_id": result["request_id"],
                "expected_metric_value": expected,
                "model_text": sentence,
                "extracted_decimal_tokens": ";".join(
                    str(token) for token in sorted(engineering_decimal_tokens_v2(sentence))
                ),
                "numeric_status": numeric_value_status_v2(value, sentence),
                "evaluator": "engineering_decimal_tokens_v2",
            }
        )
    return sorted(rows, key=lambda row: (str(row["task_id"]), str(row["claim_id"])))


def _final_summary(root: Path, strict_numeric_rows: list[dict[str, Any]]) -> dict[str, Any]:
    old_execution = root / OLD_ARTIFACT_DIR
    correction = root / CORRECTION_DIR
    old_a3 = _read_json(old_execution / "a3_mechanistic_summary.json")
    a2 = _read_json(old_execution / "a2_mechanistic_summary.json")
    secondary = _read_json(correction / "a3_secondary_syntax_normalized_summary.json")
    a4 = _read_json(correction / "a4_corrected_numeric_summary.json")
    strict_numeric_exact = sum(row["numeric_status"] == "PASS" for row in strict_numeric_rows)
    strict_numeric_drift = sum(row["numeric_status"] == "FAIL" for row in strict_numeric_rows)
    return {
        "summary_role": "AUTHORITATIVE_STAGE7E_FINAL_MACHINE_RESULT_SUMMARY",
        "a1": {
            "execution_status": "NOT_EXECUTABLE",
            "interpretation": "DESIGN_FEASIBILITY_NOT_MODEL_PERFORMANCE",
        },
        "a2": {
            "target_sections": a2["target_section_count"],
            "affected_tasks": a2["affected_task_count"],
        },
        "a3_primary_protocol_compliance": {
            "valid_chunks": old_a3["valid_chunk_count"],
            "total_chunks": old_a3["chunk_count"],
            "claim_mappings": old_a3["mapping_complete_count"],
            "total_claims": old_a3["expected_claim_count"],
            "complete_tasks": old_a3["complete_task_count"],
            "total_tasks": 45,
        },
        "a3_corrected_strict_numeric_audit": {
            "numeric_claims": len(strict_numeric_rows),
            "numeric_exact": strict_numeric_exact,
            "numeric_drift": strict_numeric_drift,
            "evaluator": "engineering_decimal_tokens_v2",
        },
        "a3_secondary_fence_only": {
            "analysis_role": secondary["analysis_role"],
            "valid_chunks": secondary["secondary_valid_chunks"],
            "total_chunks": 147,
            "claim_mappings": secondary["secondary_claim_mappings"],
            "total_claims": 989,
            "complete_tasks": secondary["secondary_complete_tasks"],
            "total_tasks": 45,
            "numeric_claims": secondary["numeric_claim_count"],
            "numeric_exact": secondary["numeric_exact_count"],
            "numeric_drift": secondary["numeric_drift_count"],
        },
        "a4": {
            "total_fact_locks": a4["total_fact_lock_count"],
            "used_fact_locks": a4["used_fact_lock_count"],
            "omitted_fact_locks": a4["omitted_fact_lock_count"],
            "fact_lock_trace_coverage": a4["fact_lock_coverage"],
            "total_numeric_fact_locks": a4["total_numeric_fact_lock_count"],
            "used_numeric_fact_locks": a4["used_numeric_fact_lock_count"],
            "omitted_numeric_fact_locks": a4["omitted_numeric_fact_lock_count"],
            "numeric_fact_lock_trace_coverage": a4["numeric_fact_lock_coverage"],
            "referenced_numeric_token_exact": a4["used_numeric_exact_count"],
            "referenced_numeric_token_drift": a4["used_numeric_drift_count"],
            "numeric_evaluation_basis": (
                "FACTLOCK_ID_TO_DECLARING_SECTION_EXACT_FROZEN_TOKEN_PRESENCE"
            ),
            "semantic_correctness_inference": "PROHIBITED",
        },
        "human_semantic_evaluation": "DEFERRED_TO_HUMAN",
        "new_api_calls": 0,
        "new_llm_calls": 0,
        "new_deepseek_calls": 0,
    }


def _legacy_registry(root: Path) -> dict[str, Any]:
    old = _read_json(root / OLD_ARTIFACT_DIR / "a3_mechanistic_summary.json")
    return {
        "legacy_v1_reported_numeric_drift_count": old["numeric_drift_count"],
        "legacy_v1_numeric_result_status": "SUPERSEDED_BY_V1_1_CORRECTED_NUMERIC_AUDIT",
        "legacy_v1_numeric_result_reason": "UNICODE_WORD_BOUNDARY_TOKENIZER_FALSE_POSITIVE",
        "current_result_reference": "a3_corrected_strict_numeric_audit.numeric_drift",
    }


def _hard_checks(
    root: Path,
    summary: dict[str, Any],
    legacy: dict[str, Any],
    correction_identity: list[dict[str, Any]],
    raw_identity: list[dict[str, Any]],
    first_hash: str,
    second_hash: str,
) -> list[dict[str, Any]]:
    protocol = summary["a3_primary_protocol_compliance"]
    strict = summary["a3_corrected_strict_numeric_audit"]
    secondary = summary["a3_secondary_fence_only"]
    a4 = summary["a4"]
    checks = [
        _check(
            "old_stage7e_v1_tag_unchanged",
            _git_rev(root, OLD_TAG) == OLD_COMMIT,
            _git_rev(root, OLD_TAG),
        ),
        _check(
            "old_stage7e_v1_1_tag_unchanged",
            _git_rev(root, CORRECTION_TAG) == CORRECTION_COMMIT,
            _git_rev(root, CORRECTION_TAG),
        ),
        _check(
            "old_v1_1_correction_artifact_unchanged",
            all(row["identity_match"] for row in correction_identity),
            sum(not row["identity_match"] for row in correction_identity),
        ),
        _check("a3_strict_chunks_125", protocol["valid_chunks"] == 125, protocol["valid_chunks"]),
        _check(
            "a3_strict_mappings_828", protocol["claim_mappings"] == 828, protocol["claim_mappings"]
        ),
        _check("a3_strict_tasks_32", protocol["complete_tasks"] == 32, protocol["complete_tasks"]),
        _check(
            "a3_strict_numeric_claims_149",
            strict["numeric_claims"] == 149,
            strict["numeric_claims"],
        ),
        _check(
            "a3_strict_numeric_exact_149", strict["numeric_exact"] == 149, strict["numeric_exact"]
        ),
        _check(
            "a3_strict_numeric_drift_zero", strict["numeric_drift"] == 0, strict["numeric_drift"]
        ),
        _check(
            "a3_secondary_chunks_147", secondary["valid_chunks"] == 147, secondary["valid_chunks"]
        ),
        _check(
            "a3_secondary_mappings_989",
            secondary["claim_mappings"] == 989,
            secondary["claim_mappings"],
        ),
        _check(
            "a3_secondary_tasks_45", secondary["complete_tasks"] == 45, secondary["complete_tasks"]
        ),
        _check(
            "a3_secondary_numeric_164",
            secondary["numeric_claims"] == 164,
            secondary["numeric_claims"],
        ),
        _check(
            "a3_secondary_numeric_exact_164",
            secondary["numeric_exact"] == 164,
            secondary["numeric_exact"],
        ),
        _check(
            "a3_secondary_numeric_drift_zero",
            secondary["numeric_drift"] == 0,
            secondary["numeric_drift"],
        ),
        _check("a4_factlocks_1022", a4["total_fact_locks"] == 1022, a4["total_fact_locks"]),
        _check("a4_used_factlocks_848", a4["used_fact_locks"] == 848, a4["used_fact_locks"]),
        _check(
            "a4_numeric_factlocks_171",
            a4["total_numeric_fact_locks"] == 171,
            a4["total_numeric_fact_locks"],
        ),
        _check(
            "a4_used_numeric_162",
            a4["used_numeric_fact_locks"] == 162,
            a4["used_numeric_fact_locks"],
        ),
        _check(
            "a4_numeric_omitted_9",
            a4["omitted_numeric_fact_locks"] == 9,
            a4["omitted_numeric_fact_locks"],
        ),
        _check(
            "a4_numeric_exact_162",
            a4["referenced_numeric_token_exact"] == 162,
            a4["referenced_numeric_token_exact"],
        ),
        _check(
            "a4_numeric_drift_zero",
            a4["referenced_numeric_token_drift"] == 0,
            a4["referenced_numeric_token_drift"],
        ),
        _check(
            "unqualified_current_numeric_drift_149_field_count_zero",
            _unqualified_stale_149_count(summary) == 0,
            _unqualified_stale_149_count(summary),
        ),
        _check(
            "legacy_149_explicitly_superseded",
            legacy["legacy_v1_reported_numeric_drift_count"] == 149
            and legacy["legacy_v1_numeric_result_status"]
            == "SUPERSEDED_BY_V1_1_CORRECTED_NUMERIC_AUDIT",
            legacy["legacy_v1_numeric_result_status"],
        ),
        _check("raw_response_count_226", len(raw_identity) == 226, len(raw_identity)),
        _check(
            "raw_hash_mismatch_zero",
            all(row["raw_hash_match"] for row in raw_identity),
            sum(not row["raw_hash_match"] for row in raw_identity),
        ),
        _check(
            "provider_response_id_change_zero",
            not any(row["provider_response_id_changed"] for row in raw_identity),
            sum(row["provider_response_id_changed"] for row in raw_identity),
        ),
        _check(
            "request_payload_hash_change_zero",
            not any(row["request_payload_hash_changed"] for row in raw_identity),
            sum(row["request_payload_hash_changed"] for row in raw_identity),
        ),
        _check(
            "deterministic_replay_identity",
            first_hash == second_hash,
            f"{first_hash}:{second_hash}",
        ),
        _check("new_api_calls_zero", summary["new_api_calls"] == 0, summary["new_api_calls"]),
        _check("new_llm_calls_zero", summary["new_llm_calls"] == 0, summary["new_llm_calls"]),
        _check(
            "new_deepseek_calls_zero",
            summary["new_deepseek_calls"] == 0,
            summary["new_deepseek_calls"],
        ),
    ]
    return checks


def _unqualified_stale_149_count(payload: Any, path: tuple[str, ...] = ()) -> int:
    if isinstance(payload, dict):
        return sum(
            (
                1
                if key == "numeric_drift_count"
                and value == 149
                and "legacy_superseded_results" not in path
                else 0
            )
            + _unqualified_stale_149_count(value, (*path, str(key)))
            for key, value in payload.items()
        )
    if isinstance(payload, list):
        return sum(_unqualified_stale_149_count(value, path) for value in payload)
    return 0


def _correction_baseline_identity(root: Path) -> list[dict[str, Any]]:
    """Validate only the correction summaries consumed by the final builder."""

    baseline = root / CORRECTION_DIR
    expected = {}
    for line in (baseline / "file_hashes.sha256").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split(maxsplit=1)
        expected[relative] = digest
    rows = []
    for name in (
        "a3_secondary_syntax_normalized_summary.json",
        "a4_corrected_numeric_summary.json",
    ):
        path = baseline / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
        rows.append(
            {
                "path": str(CORRECTION_DIR / name),
                "frozen_sha256": expected[name],
                "current_sha256": actual,
                "exists": path.is_file(),
                "identity_match": path.is_file() and actual == expected[name],
            }
        )
    return rows


def _require_frozen_refs(root: Path) -> None:
    if _git_rev(root, OLD_TAG) != OLD_COMMIT:
        raise Stage7EMetadataCleanupError("Stage7E-B v1 tag moved")
    if _git_rev(root, CORRECTION_TAG) != CORRECTION_COMMIT:
        raise Stage7EMetadataCleanupError("Stage7E-B v1.1 corrected tag moved")


def _readme(summary: dict[str, Any]) -> str:
    strict = summary["a3_corrected_strict_numeric_audit"]
    a4 = summary["a4"]
    return f"""# Stage7E Final Machine Results

This metadata-only artifact is the unique recommended Stage7E machine-result
summary for tables, plots, statistics, and paper drafting. It changes no model
response, request, prompt, evaluator, or experiment count and makes zero API calls.

The A3 strict protocol endpoint remains 125/147 chunks, 828/989 mappings, and
32/45 complete tasks. Re-evaluation of strictly mapped numeric Claims with
`engineering_decimal_tokens_v2` gives {strict["numeric_exact"]}/
{strict["numeric_claims"]} exact and {strict["numeric_drift"]} drift. The legacy
v1 value of 149 numeric drifts is superseded and retained only in the explicit
legacy registry.

A4 overall FactLock trace coverage is {a4["used_fact_locks"]}/
{a4["total_fact_locks"]}; numeric FactLock trace coverage is
{a4["used_numeric_fact_locks"]}/{a4["total_numeric_fact_locks"]}. Numeric
token exactness does not establish semantic correctness, which remains deferred
to human evaluation.
"""


def _result_semantics(summary: dict[str, Any]) -> str:
    a4 = summary["a4"]
    return f"""# Stage7E Final Result Semantics

## A3

The primary endpoint is strict JSON protocol compliance: 125/147 valid chunks,
828/989 Claim mappings, and 32/45 complete tasks. Among the 149 numeric Claims
available under that strict endpoint, the corrected tokenizer finds 149 exact
tokens and zero numeric drift.

The fence-only result is secondary, post-hoc, offline, and deterministic. It
recovers 147/147 chunks and 989/989 mappings without modifying inner JSON. Its
164 numeric Claims contain 164 exact frozen values and zero numeric drift.

## A4

For all {a4["used_numeric_fact_locks"]} referenced numeric FactLocks, the exact
frozen numeric token was present in the section text that declared use of the
corresponding FactLock ID.

对于 {a4["used_numeric_fact_locks"]} 条被引用的数值型 FactLock, 在声明使用相应
FactLock ID 的 section 文本中, 均检测到了对应的冻结精确数值。

This is a section-level token-presence result. It does not show that all facts
were semantically bound correctly and it is not a semantic-accuracy estimate.
Overall FactLock trace coverage is {a4["used_fact_locks"]}/{a4["total_fact_locks"]};
numeric trace coverage is {a4["used_numeric_fact_locks"]}/
{a4["total_numeric_fact_locks"]}; numeric omission is
{a4["omitted_numeric_fact_locks"]}/{a4["total_numeric_fact_locks"]}; and numeric
token drift among referenced numeric FactLocks is
{a4["referenced_numeric_token_drift"]}/{a4["used_numeric_fact_locks"]}.

Complex semantic evaluation remains `DEFERRED_TO_HUMAN`.
"""


def write_audit_zip(root: Path, output: Path) -> Path:
    zip_path = root / AUDIT_ZIP
    sources = [
        root / "src/tbm_twin/evaluation/stage7e_metadata_cleanup.py",
        root / "scripts/build_stage7e_metadata_cleanup.py",
        root / "tests/unit/test_stage7e_metadata_cleanup.py",
    ]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("git_refs.txt", _git_refs(root))
        for source in sources:
            if source.is_file():
                archive.write(source, source.relative_to(root).as_posix())
        for path in sorted(output.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())
    return zip_path


def _git_refs(root: Path) -> str:
    commands = [
        ["git", "branch", "--show-current"],
        ["git", "rev-parse", "HEAD"],
        ["git", "rev-parse", OLD_TAG],
        ["git", "rev-parse", CORRECTION_TAG],
        ["git", "tag", "--points-at", "HEAD"],
        ["git", "status", "--short"],
    ]
    blocks = []
    for command in commands:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
        blocks.append(f"$ {' '.join(command)}\n{result.stdout}{result.stderr}".rstrip())
    return "\n\n".join(blocks) + "\n"


def _git_rev(root: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


def _check(name: str, passed: bool, details: Any) -> dict[str, Any]:
    return {"check_name": name, "status": "PASS" if passed else "FAIL", "details": details}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise Stage7EMetadataCleanupError(f"expected JSON object: {path}")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row}) if rows else ["status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_hashes(output: Path) -> None:
    rows = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == "file_hashes.sha256":
            continue
        rows.append(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
            f"{path.relative_to(output).as_posix()}"
        )
    (output / "file_hashes.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")
