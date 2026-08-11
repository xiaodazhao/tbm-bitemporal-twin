"""Deterministic IO helpers for Stage 5C analysis artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSONL rows."""

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_json(path: Path, payload: Any) -> None:
    """Write stable JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write stable JSONL."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    """Write deterministic CSV."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read CSV rows."""

    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_hashes(output_path: Path) -> None:
    """Write recursive SHA256 closure for an artifact directory."""

    rows: list[str] = []
    for path in sorted(output_path.rglob("*")):
        if not path.is_file() or path.name == "file_hashes.sha256":
            continue
        rel_path = path.relative_to(output_path).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest}  {rel_path}")
    (output_path / "file_hashes.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")
