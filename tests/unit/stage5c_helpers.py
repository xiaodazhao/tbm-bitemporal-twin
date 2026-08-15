"""Shared helpers for Stage 5C artifact tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from tbm_twin.claim_analysis.analysis import build_stage5c_analysis

REPO_ROOT = Path(__file__).resolve().parents[2]
_ARTIFACT_DIR: Path | None = None


def stage5c_artifact(tmp_path_factory: Any) -> Path:
    """Build the Stage 5C candidate analysis once per pytest session."""

    global _ARTIFACT_DIR
    if _ARTIFACT_DIR is None:
        output_dir = tmp_path_factory.mktemp("stage5c") / "candidate"
        build_stage5c_analysis(REPO_ROOT, output_dir=output_dir)
        _ARTIFACT_DIR = output_dir
    return _ARTIFACT_DIR


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
