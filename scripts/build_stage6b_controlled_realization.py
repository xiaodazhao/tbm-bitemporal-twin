"""CLI entrypoint for Stage6B controlled realization candidate artifacts."""

from __future__ import annotations

from pathlib import Path

from tbm_twin.realization.build_stage6b import build_stage6b_candidate


def main() -> None:
    """Build the Stage6B candidate artifact."""

    build_stage6b_candidate(Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    main()
