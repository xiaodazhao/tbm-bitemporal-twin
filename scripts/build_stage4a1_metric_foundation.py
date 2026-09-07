"""Build the formal Stage 4A1 metric foundation artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from tbm_twin.metrics import MetricFoundationBuilder
from tbm_twin.metrics.models import Stage4A1Config


def _parse_generated_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        msg = "--generated-at must be a timezone-aware ISO datetime"
        raise argparse.ArgumentTypeError(msg)
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-dir", default="artifacts/stage4a1_metric_foundation_v1")
    parser.add_argument("--generated-at", required=True, type=_parse_generated_at)
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()
    config = Stage4A1Config(
        repo_root=repo_root,
        output_dir=Path(args.output_dir),
        generated_at=args.generated_at,
    )
    result = MetricFoundationBuilder(config).build()
    print(f"Stage 4A1 metric foundation written to {result.output_dir}")
    print(f"baselines={result.baseline_count}")
    print(f"response_components={result.response_component_count}")
    print(f"response_profiles={result.response_profile_count}")
    print(f"bitemporal_bindings={result.bitemporal_binding_count}")
    print(f"hard_check_failures={result.hard_check_failures}")


if __name__ == "__main__":
    main()
