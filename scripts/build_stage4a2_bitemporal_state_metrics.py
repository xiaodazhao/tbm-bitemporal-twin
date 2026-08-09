"""Build Stage 4A2 bitemporal state metrics candidate artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from tbm_twin.metrics.stage4a2_builder import Stage4A2Builder


def _parse_generated_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        msg = "--generated-at must be a timezone-aware ISO datetime"
        raise argparse.ArgumentTypeError(msg)
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-dir", default="artifacts/stage4_bitemporal_state_metrics_v1_1")
    parser.add_argument("--generated-at", required=True, type=_parse_generated_at)
    parser.add_argument("--repro-build-a", type=Path)
    parser.add_argument("--repro-build-b", type=Path)
    args = parser.parse_args()
    result = Stage4A2Builder(
        repo_root=Path(args.repo_root).resolve(),
        generated_at=args.generated_at,
        output_dir=Path(args.output_dir),
        reproducibility_build_a_dir=args.repro_build_a,
        reproducibility_build_b_dir=args.repro_build_b,
    ).build()
    print(f"Stage 4A2 metrics written to {result.output_dir}")
    print(f"hard_check_failures={result.hard_check_failures}")


if __name__ == "__main__":
    main()
