#!/usr/bin/env python
"""Build the Stage 2E PLC operational evidence freeze."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from tbm_twin.operational_freeze import OperationalFreezeBuilder, OperationalFreezeConfig


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plc-data-dir", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/stage2_plc_operational_freeze_v2"),
    )
    parser.add_argument(
        "--reconstruction-time",
        required=True,
        help="Explicit timezone-aware ISO timestamp for offline reconstruction metadata.",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    reconstruction_time = datetime.fromisoformat(args.reconstruction_time)
    config = OperationalFreezeConfig(
        repo_root=Path.cwd(),
        output_dir=args.output_dir,
        plc_data_dir=args.plc_data_dir,
        reconstruction_time=reconstruction_time,
        overwrite=args.overwrite,
    )
    result = OperationalFreezeBuilder(config).build()
    print(
        "Stage 2E PLC operational freeze complete: "
        f"dates={result.target_date_count}, "
        f"source_assets={result.source_asset_count}, "
        f"episodes={result.episode_count}, "
        f"response_evidence={result.response_evidence_count}, "
        f"hard_checks={result.hard_check_issue_count}"
    )
    print(f"Artifacts: {result.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
