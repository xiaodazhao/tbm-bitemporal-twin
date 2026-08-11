"""Small deterministic IO helpers for Stage 5B artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSONL rows, returning an empty list when a file is absent."""

    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_json(path: Path, payload: Any) -> None:
    """Write stable JSON."""

    path.write_text(
        json.dumps(_dump(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[Any]) -> None:
    """Write stable JSONL."""

    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(_dump(row), ensure_ascii=False, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    """Write deterministic CSV with stable field ordering."""

    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_hashes(output_path: Path) -> None:
    """Write SHA256 closure for files in one artifact directory."""

    rows: list[str] = []
    for path in sorted(output_path.iterdir()):
        if not path.is_file() or path.name == "file_hashes.sha256":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest}  {path.name}")
    (output_path / "file_hashes.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump(item) for item in value]
    if isinstance(value, dict):
        return {key: _dump(item) for key, item in value.items()}
    return value
