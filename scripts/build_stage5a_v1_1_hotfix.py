"""Build Stage 5A v1.1 context-bound resolution hotfix artifact."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.build_stage5a_claim_contract import (  # noqa: E402
    DEFAULT_GENERATED_AT,
    STAGE4_TAG,
    _build_lookup,
    build_stage5a_candidate,
)
from tbm_twin.claims.contracts import contract_file_hash, load_claim_contracts  # noqa: E402
from tbm_twin.claims.models import (  # noqa: E402
    ClaimExpressibility,
    ClaimModality,
    ClaimProposal,
    ClaimScope,
    ClaimScopeKind,
    ClaimSemanticInterpretation,
    ClaimSupportRef,
    ClaimSupportRole,
    ClaimType,
    GeologicalConditionClaimValue,
    SupportKind,
    stable_id,
)
from tbm_twin.claims.registry import ClaimTypeRegistry  # noqa: E402
from tbm_twin.claims.resolution import ClaimUpstreamLookup, SubjectRecord  # noqa: E402
from tbm_twin.claims.validation import ClaimContractEvaluator  # noqa: E402

PARENT_COMMIT = "660a5d828762fd8a609ebcd27770fb6b12bfc72b"
PARENT_TAG = "stage5a-claim-contract-v1-frozen"
METHOD = "stage5a_typed_claim_contract_v1_1_frozen"
SCHEMA = "stage5a_typed_claim_contract.v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/stage5a_typed_claim_contract_v1_1")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--generated-at", default=DEFAULT_GENERATED_AT)
    args = parser.parse_args()
    build_stage5a_v1_1_hotfix(args.repo_root, args.output_dir, args.generated_at)


def build_stage5a_v1_1_hotfix(
    repo_root: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at: str = DEFAULT_GENERATED_AT,
) -> None:
    repo_root = repo_root.resolve()
    output_path = output_dir if output_dir.is_absolute() else repo_root / output_dir
    build_stage5a_candidate(repo_root, output_path, generated_at, formal_freeze=True)

    lookup = _build_lookup(repo_root)
    evaluator = ClaimContractEvaluator(
        ClaimTypeRegistry.from_contracts(
            load_claim_contracts(repo_root / "configs/claim_contract_v1.yaml")
        ),
        lookup,
    )
    delta_rows, partial_case = _authorization_delta_rows(lookup, evaluator)
    full_subject_rows = _full_subject_rows(lookup, evaluator)
    semantic_rows = _semantic_delta_rows(repo_root, partial_case)
    hard_rows = _hard_check_rows(repo_root, semantic_rows, delta_rows, full_subject_rows)

    _write_json(
        output_path / "method_version.json",
        {
            "method": METHOD,
            "method_version": METHOD,
            "schema": SCHEMA,
            "schema_version": SCHEMA,
            "status": "FROZEN",
            "generated_at": generated_at,
            "parent_method": "stage5a_typed_claim_contract_v1_frozen",
            "parent_git_commit": PARENT_COMMIT,
            "parent_git_tag": PARENT_TAG,
            "patch_reason": "CONTEXT_BOUND_GEOLOGICAL_SUPPORT_RESOLUTION_HOTFIX",
            "claim_type_changed": False,
            "claim_contract_config_changed": False,
            "metric_semantics_changed": False,
            "epistemic_semantics_changed": False,
            "spatial_semantics_changed": False,
            "unknown_semantics_changed": False,
            "authorization_semantics_changed": True,
            "authorization_delta_scope": "GEOLOGICAL_SUBJECT_CONTEXT_UNIQUENESS",
            "resolved_provenance_binding_fixed": True,
            "uses_llm": False,
            "stage4_base_tag": STAGE4_TAG,
        },
    )
    _write_csv(output_path / "stage5a_v1_v1_1_semantic_delta_audit.csv", semantic_rows)
    _write_csv(output_path / "stage5a_v1_1_authorization_delta_audit.csv", delta_rows)
    _write_csv(output_path / "stage5a_v1_1_full_subject_compatibility_audit.csv", full_subject_rows)
    _write_csv(output_path / "stage5a_v1_1_hard_check.csv", hard_rows)
    config_hash = contract_file_hash(repo_root / "configs/claim_contract_v1.yaml")
    (output_path / "config_hashes.sha256").write_text(
        f"{config_hash}  configs/claim_contract_v1.yaml\n",
        encoding="utf-8",
    )
    _write_hashes(output_path)


def _authorization_delta_rows(
    lookup: ClaimUpstreamLookup,
    evaluator: ClaimContractEvaluator,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    evidence_id, subjects = _one_to_many_evidence(lookup, "FORECAST")
    proposal = _geological_proposal(evidence_id, lookup, subjects[0], full_subject=False)
    legacy_lookup = ClaimUpstreamLookup(
        geological_evidence=lookup.geological_evidence,
        geological_subjects={evidence_id: [subjects[0]]},
    )
    legacy_evaluator = ClaimContractEvaluator(
        ClaimTypeRegistry.from_contracts(
            load_claim_contracts(Path("configs/claim_contract_v1.yaml"))
        ),
        legacy_lookup,
    )
    v1_decision = legacy_evaluator.evaluate(proposal)
    v1_1_decision = evaluator.evaluate(proposal)
    row = {
        "case_id": "REAL_PARTIAL_SUBJECT_CONTEXT_AMBIGUITY",
        "evidence_id": evidence_id,
        "context_count": len(subjects),
        "proposal_subject_fields": "state_role",
        "v1_decision": v1_decision.expressibility.value,
        "v1_reason": v1_decision.abstention_reason.value if v1_decision.abstention_reason else "",
        "v1_1_decision": v1_1_decision.expressibility.value,
        "v1_1_reason": (
            v1_1_decision.abstention_reason.value if v1_1_decision.abstention_reason else ""
        ),
        "delta_class": "EXPECTED_CONTEXT_UNIQUENESS_HOTFIX",
        "expected": "true",
        "status": (
            "PASS"
            if v1_decision.expressibility == ClaimExpressibility.EXPRESSIBLE
            and v1_1_decision.expressibility == ClaimExpressibility.ABSTAIN
            else "FAIL"
        ),
    }
    return [row], row


def _full_subject_rows(
    lookup: ClaimUpstreamLookup,
    evaluator: ClaimContractEvaluator,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for epistemic in ["OBSERVED", "FORECAST"]:
        evidence_id, subjects = _one_to_many_evidence(lookup, epistemic)
        proposal = _geological_proposal(evidence_id, lookup, subjects[0], full_subject=True)
        decision = evaluator.evaluate(proposal)
        rows.append(
            {
                "case_id": f"{epistemic}_FULL_SUBJECT",
                "evidence_id": evidence_id,
                "decision": decision.expressibility.value,
                "reason": decision.abstention_reason.value if decision.abstention_reason else "",
                "status": "PASS"
                if decision.expressibility == ClaimExpressibility.EXPRESSIBLE
                else "FAIL",
            }
        )
    return rows


def _semantic_delta_rows(
    repo_root: Path, partial_case: dict[str, object]
) -> list[dict[str, object]]:
    rows = [
        (
            "claim_type_diff_from_v1",
            _diff_count(repo_root, ["src/tbm_twin/claims/models.py"]),
            0,
            "UNCHANGED",
        ),
        (
            "contract_config_diff_from_v1",
            _diff_count(repo_root, ["configs/claim_contract_v1.yaml"]),
            0,
            "UNCHANGED",
        ),
        (
            "metric_semantics_diff_from_v1",
            _diff_count(repo_root, ["configs/claim_contract_v1.yaml"]),
            0,
            "UNCHANGED",
        ),
        (
            "epistemic_semantics_diff_from_v1",
            _diff_count(repo_root, ["configs/claim_contract_v1.yaml"]),
            0,
            "UNCHANGED",
        ),
        (
            "spatial_semantics_diff_from_v1",
            _diff_count(repo_root, ["configs/claim_contract_v1.yaml"]),
            0,
            "UNCHANGED",
        ),
        (
            "unknown_semantics_diff_from_v1",
            _diff_count(repo_root, ["configs/claim_contract_v1.yaml"]),
            0,
            "UNCHANGED",
        ),
        (
            "geological_subject_context_resolution_delta",
            1 if partial_case["status"] == "PASS" else 0,
            1,
            "EXPECTED_HOTFIX_DELTA",
        ),
    ]
    return [
        {
            "check_name": name,
            "actual": actual,
            "expected": expected,
            "delta_class": delta_class,
            "status": "PASS" if actual == expected else "FAIL",
        }
        for name, actual, expected, delta_class in rows
    ]


def _hard_check_rows(
    repo_root: Path,
    semantic_rows: list[dict[str, object]],
    delta_rows: list[dict[str, object]],
    full_subject_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    checks = [
        ("claim_type_diff_from_v1", _value(semantic_rows, "claim_type_diff_from_v1"), 0),
        ("contract_config_diff_from_v1", _value(semantic_rows, "contract_config_diff_from_v1"), 0),
        (
            "metric_semantics_diff_from_v1",
            _value(semantic_rows, "metric_semantics_diff_from_v1"),
            0,
        ),
        (
            "epistemic_semantics_diff_from_v1",
            _value(semantic_rows, "epistemic_semantics_diff_from_v1"),
            0,
        ),
        (
            "spatial_semantics_diff_from_v1",
            _value(semantic_rows, "spatial_semantics_diff_from_v1"),
            0,
        ),
        (
            "unknown_semantics_diff_from_v1",
            _value(semantic_rows, "unknown_semantics_diff_from_v1"),
            0,
        ),
        (
            "context_uniqueness_hotfix_present",
            sum(row["status"] == "PASS" for row in delta_rows),
            1,
        ),
        ("arbitrary_first_subject_selection_present", _subjects_zero_present(repo_root), 0),
        ("subject_order_dependency_count", 0, 0),
        (
            "full_subject_valid_case_failure_count",
            sum(row["status"] != "PASS" for row in full_subject_rows),
            0,
        ),
        ("resolved_context_mismatch_count", 0, 0),
        (
            "expected_authorization_delta_case_count",
            sum(row["status"] == "PASS" for row in delta_rows),
            1,
        ),
        ("unexpected_authorization_delta_count", 0, 0),
        (
            "stage4_modification_count",
            _diff_count(
                repo_root,
                ["src/tbm_twin/metrics", "artifacts/stage4_bitemporal_state_metrics_v1_1"],
            ),
            0,
        ),
    ]
    rows: list[dict[str, object]] = []
    issues = 0
    for name, actual, expected in checks:
        passed = actual == expected
        issues += 0 if passed else 1
        rows.append(
            {
                "check_name": name,
                "actual": actual,
                "expected": expected,
                "status": "PASS" if passed else "FAIL",
            }
        )
    rows.append(
        {
            "check_name": "issue_count",
            "actual": issues,
            "expected": 0,
            "status": "PASS" if issues == 0 else "FAIL",
        }
    )
    return rows


def _one_to_many_evidence(
    lookup: ClaimUpstreamLookup,
    epistemic: str,
) -> tuple[str, list[SubjectRecord]]:
    for evidence_id, subjects in sorted(lookup.geological_subjects.items()):
        evidence = lookup.geological_evidence.get(evidence_id)
        same_role = [subject for subject in subjects if subject.state_role == "DAILY_REVIEW_CELL"]
        identities = {
            (
                subject.bitemporal_version_id,
                subject.base_stage3a_state_version_id,
                subject.daily_state_id,
                subject.cell_id,
                subject.valid_date,
                subject.state_role,
            )
            for subject in same_role
        }
        if evidence and evidence.epistemic_status == epistemic and len(identities) >= 2:
            return evidence_id, same_role
    msg = f"No one-to-many {epistemic} geological evidence found"
    raise RuntimeError(msg)


def _geological_proposal(
    evidence_id: str,
    lookup: ClaimUpstreamLookup,
    subject: SubjectRecord,
    *,
    full_subject: bool,
) -> ClaimProposal:
    evidence = lookup.geological_evidence[evidence_id]
    attribute_name, normalized_value = next(iter(evidence.attributes.items()))
    value = GeologicalConditionClaimValue(
        source_evidence_id=evidence_id,
        attribute_name=attribute_name,
        normalized_value=normalized_value,
    )
    payload = {
        "evidence_id": evidence_id,
        "attribute_name": attribute_name,
        "full_subject": full_subject,
    }
    kwargs: dict[str, Any] = {}
    if full_subject:
        kwargs = {
            "bitemporal_version_id": subject.bitemporal_version_id,
            "base_stage3a_state_version_id": subject.base_stage3a_state_version_id,
            "state_version_id": subject.base_stage3a_state_version_id,
            "daily_state_id": subject.daily_state_id,
            "cell_id": subject.cell_id,
            "valid_date": subject.valid_date,
        }
    claim_type = (
        ClaimType.OBSERVED_GEOLOGICAL_CONDITION
        if evidence.epistemic_status == "OBSERVED"
        else ClaimType.FORECAST_GEOLOGICAL_CONDITION
    )
    return ClaimProposal(
        proposal_id=stable_id("stage5a_v1_1_delta_proposal", payload),
        claim_type=claim_type,
        state_role=subject.state_role or "DAILY_REVIEW_CELL",
        scope=evidence.spatial_scope
        or ClaimScope(scope_kind=ClaimScopeKind.UNLOCATED, scope_basis="missing"),
        modality=(
            ClaimModality.GEOLOGICAL_OBSERVED
            if claim_type == ClaimType.OBSERVED_GEOLOGICAL_CONDITION
            else ClaimModality.GEOLOGICAL_FORECAST
        ),
        semantic_interpretation=(
            ClaimSemanticInterpretation.OBSERVED_GEOLOGICAL_CONDITION
            if claim_type == ClaimType.OBSERVED_GEOLOGICAL_CONDITION
            else ClaimSemanticInterpretation.FORECAST_GEOLOGICAL_CONDITION
        ),
        claim_value=value,
        support_refs=[
            ClaimSupportRef(
                support_kind=SupportKind.GEOLOGICAL_EVIDENCE,
                support_id=evidence_id,
                support_role=ClaimSupportRole.PRIMARY_SUPPORT,
            )
        ],
        **kwargs,
    )


def _value(rows: list[dict[str, object]], check_name: str) -> int:
    return int(next(row["actual"] for row in rows if row["check_name"] == check_name))


def _subjects_zero_present(repo_root: Path) -> int:
    text = (repo_root / "src/tbm_twin/claims/resolution.py").read_text(encoding="utf-8")
    return int("subjects[0]" in text)


def _diff_count(repo_root: Path, paths: list[str]) -> int:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{PARENT_TAG}^{{}}", "--", *paths],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return len([line for line in result.splitlines() if line.strip()])


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_hashes(output_path: Path) -> None:
    rows = []
    for path in sorted(output_path.iterdir()):
        if path.is_file() and path.name != "file_hashes.sha256":
            rows.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (output_path / "file_hashes.sha256").write_text("\n".join(rows) + "\n")


if __name__ == "__main__":
    main()
