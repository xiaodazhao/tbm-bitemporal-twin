#!/usr/bin/env python
"""Build operation phases, excavation episodes, and spatial footprints."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tbm_twin.process.episode_builder import build_excavation_episodes, finalize_episode_quality
from tbm_twin.process.weak_labels import label_operation_phases
from tbm_twin.timeseries.normalization import load_normalized_parquet
from tbm_twin.trajectory.footprint_builder import build_spatial_footprints
from tbm_twin.validation.config import (
    load_episode_builder_config,
    load_footprint_builder_config,
    load_phase_rule_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        normalized = load_normalized_parquet(args.input)
        phase_config = load_phase_rule_config()
        episode_config = load_episode_builder_config()
        footprint_config = load_footprint_builder_config()
        labeled = label_operation_phases(normalized, phase_config)
        episodes = build_excavation_episodes(labeled, episode_config)
        footprints = build_spatial_footprints(labeled, episodes, footprint_config)
        footprint_by_episode = {footprint.episode_id: footprint for footprint in footprints}
        episodes = [
            finalize_episode_quality(
                episode,
                labeled,
                footprint_status=footprint_by_episode[episode.episode_id].consistency_status.value
                if episode.episode_id in footprint_by_episode
                else None,
                footprint_quality_flags=footprint_by_episode[episode.episode_id].quality_flags
                if episode.episode_id in footprint_by_episode
                else [],
                config=episode_config,
            )
            for episode in episodes
        ]
    except (OSError, ValueError) as exc:
        print(f"build_episodes failed: {exc}", file=sys.stderr)
        return 2

    payload = {
        "phase_intervals": [
            interval.model_dump(mode="json")
            for episode in episodes
            for interval in episode.phase_sequence
        ],
        "episodes": [episode.model_dump(mode="json") for episode in episodes],
        "spatial_footprints": [footprint.model_dump(mode="json") for footprint in footprints],
        "quality_summary": {
            "episode_count": len(episodes),
            "footprint_count": len(footprints),
            "inconsistent_footprint_count": sum(
                footprint.consistency_status.value == "INCONSISTENT" for footprint in footprints
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(episodes)} episodes to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
