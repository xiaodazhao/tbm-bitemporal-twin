"""I/O helpers for Stage 3A state artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON document."""

    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSON Lines."""

    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write deterministic JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write JSON Lines."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(jsonable(row), ensure_ascii=False, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    """Write CSV with stable columns."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fieldnames or sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in fields})


def sha256_file(path: Path) -> str:
    """Hash one file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(*parts: str) -> str:
    """Short deterministic ID body."""

    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


def hash_directory_files(directory: Path) -> dict[str, str]:
    """Hash all output files except file_hashes.sha256."""

    hashes: dict[str, str] = {}
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        if path.name == "file_hashes.sha256":
            continue
        hashes[path.relative_to(directory).as_posix()] = sha256_file(path)
    return hashes


def write_file_hashes(directory: Path) -> dict[str, str]:
    """Write a hash manifest."""

    hashes = hash_directory_files(directory)
    content = "".join(f"{digest}  {rel}\n" for rel, digest in sorted(hashes.items()))
    (directory / "file_hashes.sha256").write_text(content, encoding="utf-8")
    return hashes


def verify_hash_manifest(directory: Path) -> list[dict[str, Any]]:
    """Verify a freeze directory's hash manifest."""

    rows = []
    for line in (directory / "file_hashes.sha256").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, rel = line.split(None, 1)
        path = directory / rel.strip()
        actual = sha256_file(path) if path.exists() else None
        rows.append(
            {
                "path": rel.strip(),
                "expected_sha256": expected,
                "actual_sha256": actual,
                "valid": actual == expected,
            }
        )
    return rows


def jsonable(value: Any) -> Any:
    """Convert common objects into JSON-compatible values."""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    return value


def csv_value(value: Any) -> str | int | float | bool | None:
    """Serialize nested CSV values."""

    converted = jsonable(value)
    if isinstance(converted, dict | list):
        return json.dumps(converted, ensure_ascii=False, sort_keys=True)
    if converted is None or isinstance(converted, str | int | float | bool):
        return converted
    return str(converted)
