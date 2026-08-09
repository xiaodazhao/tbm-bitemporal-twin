"""I/O helpers for Stage 2E freeze artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel

CSV_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest for one file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    """Return SHA-256 for normalized text."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_csv_with_encoding(path: Path) -> tuple[pd.DataFrame, str]:
    """Read a PLC CSV and return the encoding that succeeded."""

    failures: list[str] = []
    for encoding in CSV_ENCODINGS:
        try:
            return pd.read_csv(path, encoding=encoding), encoding
        except UnicodeDecodeError as exc:
            failures.append(f"{encoding}: {exc}")
    msg = f"Could not decode CSV {path}. Tried: {'; '.join(failures)}"
    raise ValueError(msg)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write dictionaries as JSON Lines."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(jsonable(row), ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a deterministic JSON document."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    """Write CSV rows with stable column order."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in fieldnames})


def jsonable(value: Any) -> Any:
    """Convert Pydantic/Python values to JSON-compatible objects."""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    if pd.isna(value) if not isinstance(value, list | tuple | dict) else False:
        return None
    return value


def csv_value(value: Any) -> str | int | float | None:
    """Convert nested values for CSV cells."""

    converted = jsonable(value)
    if isinstance(converted, dict | list):
        return json.dumps(converted, ensure_ascii=False, sort_keys=True)
    if isinstance(converted, bool):
        return str(converted)
    if converted is None or isinstance(converted, str | int | float):
        return converted
    return str(converted)


def verify_hash_manifest(directory: Path) -> list[dict[str, Any]]:
    """Verify a `file_hashes.sha256` file using paths relative to its directory."""

    manifest = directory / "file_hashes.sha256"
    rows: list[dict[str, Any]] = []
    if not manifest.exists():
        return [
            {
                "path": str(manifest),
                "expected_sha256": None,
                "actual_sha256": None,
                "unchanged": False,
                "reason": "missing_file_hashes_manifest",
            }
        ]
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, rel = line.split(None, 1)
        rel = rel.strip()
        path = directory / rel
        actual = sha256_file(path) if path.exists() else None
        rows.append(
            {
                "path": str(path),
                "expected_sha256": expected,
                "actual_sha256": actual,
                "unchanged": actual == expected,
                "reason": "OK" if actual == expected else "hash_mismatch_or_missing",
            }
        )
    return rows


def hash_directory_files(directory: Path) -> dict[str, str]:
    """Hash every file in a directory, excluding `file_hashes.sha256`."""

    hashes: dict[str, str] = {}
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        if path.name == "file_hashes.sha256":
            continue
        hashes[path.relative_to(directory).as_posix()] = sha256_file(path)
    return hashes


def write_file_hashes(directory: Path) -> dict[str, str]:
    """Write `file_hashes.sha256` for all freeze outputs."""

    hashes = hash_directory_files(directory)
    content = "".join(f"{digest}  {rel}\n" for rel, digest in sorted(hashes.items()))
    (directory / "file_hashes.sha256").write_text(content, encoding="utf-8")
    return hashes


def count_jsonl(path: Path) -> int:
    """Count non-empty JSONL rows."""

    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def file_size(path: Path) -> int:
    """Return file size in bytes."""

    return os.stat(path).st_size
