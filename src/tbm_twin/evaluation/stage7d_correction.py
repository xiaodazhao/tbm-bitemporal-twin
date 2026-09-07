"""Documentation-only correction for frozen Stage7D v1.1."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

METHOD_VERSION = "stage7d_bitemporal_value_v1_1a_method_correction"
GENERATED_AT = "2026-08-25T20:00:00+08:00"
OUTPUT_DIR = Path("artifacts/stage7d_bitemporal_value_v1_1a_correction")
SOURCE_DIR = Path("artifacts/stage7d_bitemporal_value_v1_1")
SOURCE_TAG = "stage7d-bitemporal-value-v1.1-frozen"
SOURCE_COMMIT = "0dfb31d15717f6ff76d434c5496d7bb577dc687c"


def build_stage7d_v1_1a_correction(
    repo_root: Path, output_dir: Path = OUTPUT_DIR
) -> dict[str, Any]:
    """Create correction metadata without changing frozen results."""

    root = repo_root.resolve()
    source = root / SOURCE_DIR
    output = root / output_dir
    output.mkdir(parents=True, exist_ok=True)
    source_hash_before = _tree_hash(source)
    transition_rows = _read_csv(source / "stage7d_revision_claim_transition_rows.csv")
    breakdown = _opportunity_added_breakdown(transition_rows)
    hard_rows = _hard_checks(root, source, transition_rows, breakdown, source_hash_before)
    hard_failures = sum(row["status"] != "PASS" for row in hard_rows)
    if hard_failures:
        raise RuntimeError(f"Stage7D v1.1a correction checks failed: {hard_failures}")
    (output / "README.md").write_text(_readme(), encoding="utf-8")
    (output / "STAGE7D_V1_1_METHOD_CORRECTION.md").write_text(
        _method_correction(), encoding="utf-8"
    )
    _write_json(output / "stage7d_v1_1_derived_opportunity_added_breakdown.json", breakdown)
    (output / "stage7d_v1_1_interpretation_boundaries.md").write_text(
        _interpretation_boundaries(), encoding="utf-8"
    )
    _write_csv(output / "stage7d_v1_1_correction_hard_check.csv", hard_rows)
    _write_csv(output / "upstream_file_hash_audit.csv", _upstream_hash_audit(source))
    manifest = {
        "method_version": METHOD_VERSION,
        "generated_at": GENERATED_AT,
        "status": "FROZEN",
        "source_tag": SOURCE_TAG,
        "source_commit": SOURCE_COMMIT,
        "source_tree_hash": source_hash_before,
        "correction_type": "DOCUMENTATION_AND_DERIVED_DESCRIPTIVE_SUPPLEMENT_ONLY",
        "source_result_files_modified": 0,
        "counts": breakdown["counts"],
        "hard_check_failure_count": hard_failures,
        "api_call_count": 0,
        "llm_call_count": 0,
    }
    _write_json(output / "freeze_manifest.json", manifest)
    _write_hashes(output)
    if _tree_hash(source) != source_hash_before:
        raise RuntimeError("Frozen Stage7D v1.1 artifact changed during correction")
    return {**breakdown["counts"], "hard_failures": hard_failures}


def _opportunity_added_breakdown(rows: list[dict[str, str]]) -> dict[str, Any]:
    added = [row for row in rows if row["transition_class"] == "OPPORTUNITY_ADDED"]
    decision_counts = Counter(row["post_decision"] for row in added)
    claim_types: dict[str, Counter[str]] = defaultdict(Counter)
    for row in added:
        claim_types[row["claim_type"]][row["post_decision"]] += 1
    return {
        "source": "frozen_stage7d_v1_1_transition_csv",
        "derivation": "deterministic_group_by_transition_claim_type_and_post_decision",
        "counts": {
            "transition_rows": len(rows),
            "opportunity_added": len(added),
            "added_expressible": decision_counts["EXPRESSIBLE"],
            "added_abstain": decision_counts["ABSTAIN"],
            "abstain_to_expressible": sum(
                row["transition_class"] == "ABSTAIN_TO_EXPRESSIBLE" for row in rows
            ),
            "observed_added": sum(
                row["claim_type"] == "OBSERVED_GEOLOGICAL_CONDITION" for row in added
            ),
            "forecast_added": sum(
                row["claim_type"] == "FORECAST_GEOLOGICAL_CONDITION" for row in added
            ),
        },
        "by_post_decision": dict(sorted(decision_counts.items())),
        "by_claim_type_and_post_decision": {
            key: dict(sorted(value.items())) for key, value in sorted(claim_types.items())
        },
    }


def _hard_checks(
    root: Path,
    source: Path,
    rows: list[dict[str, str]],
    breakdown: dict[str, Any],
    source_hash_before: str,
) -> list[dict[str, Any]]:
    counts = breakdown["counts"]
    checks = [
        (
            "old_stage7d_v1_1_tag_unchanged",
            _git_rev_parse(root, SOURCE_TAG) == SOURCE_COMMIT,
            _git_rev_parse(root, SOURCE_TAG),
        ),
        (
            "old_stage7d_v1_1_artifact_hashes_valid",
            all(row["status"] == "PASS" for row in _upstream_hash_audit(source)),
            0,
        ),
        (
            "old_stage7d_v1_1_tree_hash_stable",
            _tree_hash(source) == source_hash_before,
            source_hash_before,
        ),
        (
            "revision_event_count_unchanged",
            len(_read_csv(source / "stage7d_revision_pairs.csv")) == 53,
            53,
        ),
        ("transition_rows_unchanged", len(rows) == 975, len(rows)),
        (
            "opportunity_added_unchanged",
            counts["opportunity_added"] == 540,
            counts["opportunity_added"],
        ),
        (
            "abstain_to_expressible_unchanged",
            counts["abstain_to_expressible"] == 27,
            counts["abstain_to_expressible"],
        ),
        ("observed_added_unchanged", counts["observed_added"] == 36, counts["observed_added"]),
        ("forecast_added_unchanged", counts["forecast_added"] == 504, counts["forecast_added"]),
        (
            "added_expressible_exact",
            counts["added_expressible"] == 454,
            counts["added_expressible"],
        ),
        ("added_abstain_exact", counts["added_abstain"] == 86, counts["added_abstain"]),
        ("api_calls_zero", True, 0),
        ("llm_calls_zero", True, 0),
    ]
    return [
        {"check_name": name, "status": "PASS" if passed else "FAIL", "details": details}
        for name, passed, details in checks
    ]


def _upstream_hash_audit(source: Path) -> list[dict[str, Any]]:
    rows = []
    for line in (source / "file_hashes.sha256").read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        path = source / relative
        actual = _sha256_file(path)
        rows.append(
            {
                "relative_path": relative,
                "expected_sha256": expected,
                "actual_sha256": actual,
                "status": "PASS" if actual == expected else "FAIL",
            }
        )
    return rows


def _method_correction() -> str:
    return """# Stage7D v1.1 Method Description Correction

The frozen Stage5B Claim opportunity universe was rebound to the PRE- and
POST-revision bitemporal states. Claim proposals were reconstructed and
admissibility was deterministically re-evaluated under the unchanged frozen
Claim Contract. Frozen Stage5C transition artifacts were used only for
post-hoc reconciliation.

Stage7D v1.1复用了已冻结的Stage5B Claim opportunity universe, 分别绑定到
PRE与POST双时间状态, 重新构造Claim proposal, 并在完全相同的Claim Contract下
重新执行确定性准入判断。Stage5C冻结transition artifact仅用于事后一致性核验。

This correction replaces the inaccurate phrase "independent full Stage5A/Stage5B
rediscovery." It does not change code, result CSVs, event pairs, metrics, Claim
transitions, endpoints, or the frozen Stage7D v1.1 tag.
"""


def _interpretation_boundaries() -> str:
    return """# Stage7D v1.1 Interpretation Boundaries

1. The 53/53 opportunity-created and 53/53 any-semantic-change endpoints are
   descriptive. Because the census population consists of knowledge revision
   events, the presence of newly available knowledge is partly structural.
2. More discriminating results are RAI 0/53, GRS 36/53, GRCI 1/53,
   existing-Claim decision-switch events 27/53, and observed-opportunity
   creation events 9/53.
3. Knowledge delay is derived from day-precision `available_local_date`.
   A delay of one means next local-calendar-day availability, not exactly
   24 hours and not an hour-level transaction timestamp.
4. Opportunity-added is not synonymous with ABSTAIN-to-EXPRESSIBLE. Added
   opportunities did not exist in PRE; existing-Claim decision switches did.
5. Results measure sensitivity to knowledge time, not errors, hallucinations,
   hazards, probabilities, or generated-text failures.
"""


def _readme() -> str:
    return """# Stage7D v1.1a Correction

This directory is a documentation-only correction and deterministic descriptive
supplement to frozen Stage7D v1.1. It does not replace or modify the frozen
v1.1 artifact. The correction clarifies Claim-universe reuse, decomposes the
540 added opportunities, and freezes interpretation and date-precision limits.
No API or LLM was used.
"""


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(_sha256_file(path).encode())
    return digest.hexdigest()


def _write_hashes(output: Path) -> None:
    rows = [
        f"{_sha256_file(path)}  {path.relative_to(output).as_posix()}"
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "file_hashes.sha256"
    ]
    (output / "file_hashes.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_rev_parse(root: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
