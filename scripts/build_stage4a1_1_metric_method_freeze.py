"""Build the formal Stage 4A1.1 metric method-freeze artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from tbm_twin.metrics.stage4a1_1_builder import Stage4A11Builder


def _parse_generated_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        msg = "--generated-at must be a timezone-aware ISO datetime"
        raise argparse.ArgumentTypeError(msg)
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-dir", default="artifacts/stage4a1_1_metric_method_freeze_v1")
    parser.add_argument("--generated-at", required=True, type=_parse_generated_at)
    args = parser.parse_args()
    result = Stage4A11Builder(
        repo_root=Path(args.repo_root).resolve(),
        generated_at=args.generated_at,
        output_dir=Path(args.output_dir),
    ).build()
    print(f"Stage 4A1.1 method freeze written to {result.output_dir}")
    print(f"hard_check_failures={result.hard_check_failures}")


if __name__ == "__main__":
    main()
