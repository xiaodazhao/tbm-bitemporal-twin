"""Build Stage 5B deterministic typed claim materialization candidate."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.claim_building.batch_builder import (
    DEFAULT_GENERATED_AT,
    DEFAULT_OUTPUT_DIR,
    build_stage5b_candidate,
)


def main() -> None:
    """Run the Stage 5B candidate builder."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--generated-at", default=DEFAULT_GENERATED_AT)
    args = parser.parse_args()
    build_stage5b_candidate(args.repo_root, args.output_dir, args.generated_at)


if __name__ == "__main__":
    main()
