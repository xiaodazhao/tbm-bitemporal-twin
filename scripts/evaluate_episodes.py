#!/usr/bin/env python
"""Evaluate system episodes against manual episode annotations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from tbm_twin.validation.config import load_validation_config
from tbm_twin.validation.evaluation import (
    EpisodeEvaluationConfig,
    evaluate_episode_predictions,
    write_episode_evaluation_outputs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--minimum-iou-for-match", type=float, default=None)
    parser.add_argument("--boundary-tolerance-seconds", type=float, default=None)
    args = parser.parse_args()

    try:
        defaults = load_validation_config()
        config = EpisodeEvaluationConfig(
            minimum_iou_for_match=args.minimum_iou_for_match
            if args.minimum_iou_for_match is not None
            else defaults.minimum_iou_for_match,
            boundary_tolerance_seconds=args.boundary_tolerance_seconds
            if args.boundary_tolerance_seconds is not None
            else defaults.boundary_tolerance_seconds,
        )
        predictions = pd.read_csv(args.predictions)
        annotations = pd.read_csv(args.annotations)
        result = evaluate_episode_predictions(predictions, annotations, config)
        write_episode_evaluation_outputs(result, args.output_dir)
        metrics_path = args.output_dir / "metrics.json"
        metrics_path.write_text(
            json.dumps(result["metrics"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        print(f"evaluate_episodes failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"Wrote episode evaluation to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
