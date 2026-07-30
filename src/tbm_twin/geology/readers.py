"""Readers for geological evidence source tables."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def read_geology_records(path: Path) -> list[dict[str, Any]]:
    """Read geological evidence records from CSV or JSON without mutating source data."""

    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [dict(item) for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict) and isinstance(payload.get("records"), list):
            return [dict(item) for item in payload["records"] if isinstance(item, dict)]
        msg = f"Unsupported JSON geological evidence shape: {path}"
        raise ValueError(msg)
    records = pd.read_csv(path).to_dict(orient="records")
    return [dict(item) for item in records]
