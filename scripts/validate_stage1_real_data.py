#!/usr/bin/env python
"""Run Stage 1.5 validation on real PLC CSV files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tbm_twin.validation.runner import DEFAULT_DATES, run_stage1_validation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plc-data-dir", type=Path, default=None)
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/stage1_validation"))
    parser.add_argument("--dates", default=",".join(DEFAULT_DATES))
    args = parser.parse_args()

    dates = [item.strip() for item in args.dates.split(",") if item.strip()]
    result = run_stage1_validation(
        plc_data_dir=args.plc_data_dir,
        dates=dates,
        artifact_dir=args.artifact_dir,
    )
    print(
        "Stage 1.6 validation complete: "
        f"success={result['success_count']}, "
        f"warning={result['warning_count']}, "
        f"failed={result['failed_count']}"
    )
    print(f"Artifacts: {result['artifact_dir']}")
    return 1 if result["failed_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
