"""Build the formal frozen Stage 5B deterministic claim materialization artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.claim_building.batch_builder import (
    FORMAL_GENERATED_AT,
    FORMAL_OUTPUT_DIR,
    build_stage5b_formal,
)


def main() -> None:
    """Run the Stage 5B formal freeze builder."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=FORMAL_OUTPUT_DIR)
    parser.add_argument("--generated-at", default=FORMAL_GENERATED_AT)
    args = parser.parse_args()
    build_stage5b_formal(args.repo_root, args.output_dir, args.generated_at)


if __name__ == "__main__":
    main()
