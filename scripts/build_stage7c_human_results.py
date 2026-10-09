"""Build the Stage 7C partitioned human-evaluation result freeze."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.evaluation.stage7c_human_results import build_stage7c_human_results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewer-a", required=True)
    parser.add_argument("--reviewer-b", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument(
        "--output-dir",
        default="artifacts/stage7c_partitioned_human_evaluation_v1",
    )
    args = parser.parse_args()
    root = Path.cwd()
    summary = build_stage7c_human_results(
        root,
        Path(args.reviewer_a),
        Path(args.reviewer_b),
        Path(args.mapping),
        Path(args.output_dir),
    )
    for key in sorted(summary):
        print(f"{key}={summary[key]}")


if __name__ == "__main__":
    main()
