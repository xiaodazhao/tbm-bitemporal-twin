"""Shared helpers for Stage 5B artifact tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from tbm_twin.claim_building.batch_builder import build_stage5b_candidate, build_stage5b_formal

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_AT = "2026-08-11T13:30:00+08:00"
_ARTIFACT_DIR: Path | None = None
_FORMAL_ARTIFACT_DIR: Path | None = None


def stage5b_artifact(tmp_path_factory: Any) -> Path:
    """Build the formal Stage 5B candidate once per pytest session."""

    global _ARTIFACT_DIR
    if _ARTIFACT_DIR is None:
        output_dir = tmp_path_factory.mktemp("stage5b") / "candidate"
        build_stage5b_candidate(REPO_ROOT, output_dir, GENERATED_AT)
        _ARTIFACT_DIR = output_dir
    return _ARTIFACT_DIR


def stage5b_formal_artifact(tmp_path_factory: Any) -> Path:
    """Build the formal Stage 5B freeze candidate once per pytest session."""

    global _FORMAL_ARTIFACT_DIR
    if _FORMAL_ARTIFACT_DIR is None:
        output_dir = tmp_path_factory.mktemp("stage5b_formal") / "formal"
        build_stage5b_formal(REPO_ROOT, output_dir)
        _FORMAL_ARTIFACT_DIR = output_dir
    return _FORMAL_ARTIFACT_DIR


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def rows_by_type(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["claim_type"]: row for row in rows}
