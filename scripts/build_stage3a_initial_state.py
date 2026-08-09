#!/usr/bin/env python
"""Build Stage 3A initial daily construction state snapshots."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from tbm_twin.state import Stage3AStateBuilder, Stage3AStateConfig


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/stage3a_initial_epistemic_state_v1_1"),
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    generated_at = datetime.fromisoformat(args.generated_at)
    config = Stage3AStateConfig(
        repo_root=Path.cwd(),
        output_dir=args.output_dir,
        generated_at=generated_at,
        overwrite=args.overwrite,
    )
    result = Stage3AStateBuilder(config).build()
    print(
        "Stage 3A initial state complete: "
        f"cells={result['cell_count']}, "
        f"daily_states={result['daily_state_count']}, "
        f"versions={result['state_version_count']}, "
        f"geological_links={result['geological_link_count']}, "
        f"response_links={result['response_link_count']}, "
        f"hard_checks={result['hard_check_count']}"
    )
    print(f"Artifacts: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
