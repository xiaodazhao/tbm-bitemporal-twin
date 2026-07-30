#!/usr/bin/env python
"""Normalize a raw PLC CSV into the Stage 1 Parquet contract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tbm_twin.assets.models import SourceType
from tbm_twin.assets.registry import register_source_asset
from tbm_twin.channels.catalog import load_channel_catalog
from tbm_twin.timeseries.normalization import normalize_plc_csv, write_normalized_parquet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--catalog", default=Path("configs/plc_channels.yaml"), type=Path)
    args = parser.parse_args()

    try:
        catalog = load_channel_catalog(args.catalog)
        asset = register_source_asset(
            args.input,
            SourceType.PLC_CSV,
            source_timezone=catalog.timezone.source_timezone,
            canonical_timezone=catalog.timezone.canonical_timezone,
            timezone_confidence=catalog.timezone.timezone_confidence.value,
            timezone_basis=catalog.timezone.timezone_basis.value,
        )
        result = normalize_plc_csv(args.input, asset, catalog)
        write_normalized_parquet(result, args.output)
    except (OSError, ValueError) as exc:
        print(f"normalize_plc failed: {exc}", file=sys.stderr)
        return 2

    print(f"Wrote {len(result.frame)} normalized observations to {args.output}")
    print(f"Quality grade: {result.quality_report.grade.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
