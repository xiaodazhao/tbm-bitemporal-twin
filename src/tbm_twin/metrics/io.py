"""I/O helpers for Stage 4A1 metric foundation."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import yaml

from tbm_twin.state.io import (
    read_json,
    read_jsonl,
    sha256_file,
    stable_id,
    write_csv,
    write_file_hashes,
    write_json,
    write_jsonl,
)


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV file as dictionaries."""

    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML mapping."""

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = f"YAML file must contain a mapping: {path}"
        raise ValueError(msg)
    return payload


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    """Write deterministic-ish YAML for manual review."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )


__all__ = [
    "read_csv",
    "read_json",
    "read_jsonl",
    "read_yaml",
    "sha256_file",
    "stable_id",
    "write_csv",
    "write_file_hashes",
    "write_json",
    "write_jsonl",
    "write_yaml",
]
