#!/usr/bin/env python
"""Audit raw PLC CSV columns against the channel catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from tbm_twin.channels.catalog import load_channel_catalog
from tbm_twin.timeseries.reader import read_plc_csv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--catalog", default=Path("configs/plc_channels.yaml"), type=Path)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = parser.parse_args()

    frame = read_plc_csv(args.input)
    catalog = load_channel_catalog(args.catalog)
    rows = []
    definitions = catalog.by_name
    for column in frame.columns:
        raw_name = str(column)
        match = catalog.resolve(raw_name)
        definition = definitions.get(match.canonical_name or "")
        series = frame[column]
        numeric = pd.to_numeric(series, errors="coerce")
        rows.append(
            {
                "raw_name": raw_name,
                "canonical_name": match.canonical_name,
                "match_method": match.method.value,
                "dtype": str(series.dtype),
                "missing_rate": float(series.isna().mean()) if len(series) else 1.0,
                "min": _safe_float(numeric.min()) if numeric.notna().any() else None,
                "max": _safe_float(numeric.max()) if numeric.notna().any() else None,
                "unit": definition.unit if definition else None,
                "unit_verified": definition.unit_verified if definition else None,
                "usage_level": definition.usage_level.value if definition else None,
                "warnings": match.warnings,
            }
        )

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(
                f"{row['raw_name']} -> {row['canonical_name']} "
                f"({row['match_method']}), missing={row['missing_rate']:.3f}, "
                f"min={row['min']}, max={row['max']}, unit={row['unit']}, "
                f"unit_verified={row['unit_verified']}, usage={row['usage_level']}"
            )
            for warning in row["warnings"]:
                print(f"  warning: {warning}")
    return 0


def _safe_float(value: object) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


if __name__ == "__main__":
    raise SystemExit(main())
