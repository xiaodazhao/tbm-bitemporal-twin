#!/usr/bin/env python
"""Build ResponseEvidence from normalized PLC, episodes, and footprints."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from tbm_twin.evidence.response_builder import (
    build_response_evidence,
    response_evidence_summary,
)
from tbm_twin.process.models import ExcavationEpisode
from tbm_twin.trajectory.models import SpatialFootprint


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--normalized-plc", required=True, type=Path)
    parser.add_argument("--episodes", required=True, type=Path)
    parser.add_argument("--footprints", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        normalized = pd.read_parquet(args.normalized_plc)
        episode_items, embedded_footprint_items = _load_episode_items(args.episodes)
        footprint_items = (
            _load_footprint_items(args.footprints) if args.footprints else embedded_footprint_items
        )
        if footprint_items is None:
            msg = "Provide --footprints or pass a combined build_episodes JSON payload."
            raise ValueError(msg)
        episodes = [ExcavationEpisode.model_validate(item) for item in episode_items]
        footprints = [SpatialFootprint.model_validate(item) for item in footprint_items]
        records = build_response_evidence(normalized, episodes, footprints)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = [record.model_dump(mode="json") for record in records]
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        pd.DataFrame(response_evidence_summary(records)).to_csv(
            args.output.with_name("response_evidence_summary.csv"),
            index=False,
        )
        diagnostics = {
            "response_evidence_count": len(records),
            "quality_distribution": pd.Series([r.quality_grade.value for r in records])
            .value_counts()
            .to_dict(),
        }
        args.output.with_name("response_evidence_diagnostics.json").write_text(
            json.dumps(diagnostics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        print(f"build_response_evidence failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote ResponseEvidence to {args.output}")
    return 0


def _load_episode_items(path: Path) -> tuple[list[object], list[object] | None]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return list(payload.get("episodes", [])), list(payload.get("spatial_footprints", []))
    if isinstance(payload, list):
        return payload, None
    msg = f"Unsupported episode payload shape: {path}"
    raise ValueError(msg)


def _load_footprint_items(path: Path) -> list[object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return list(payload.get("spatial_footprints", []))
    if isinstance(payload, list):
        return payload
    msg = f"Unsupported footprint payload shape: {path}"
    raise ValueError(msg)


if __name__ == "__main__":
    raise SystemExit(main())
