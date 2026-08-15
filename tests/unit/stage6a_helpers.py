"""Shared helpers for Stage6A tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from tbm_twin.realization.build_stage6a import build_stage6a_candidate

REPO_ROOT = Path(__file__).resolve().parents[2]
_ARTIFACT_DIR: Path | None = None


def stage6a_artifact(tmp_path_factory: Any) -> Path:
    """Build Stage6A candidate once per pytest session."""

    global _ARTIFACT_DIR
    if _ARTIFACT_DIR is None:
        output_dir = tmp_path_factory.mktemp("stage6a") / "candidate"
        build_stage6a_candidate(REPO_ROOT, output_dir=output_dir)
        _ARTIFACT_DIR = output_dir
    return _ARTIFACT_DIR


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read CSV rows."""

    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> Any:
    """Read JSON."""

    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSONL."""

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
