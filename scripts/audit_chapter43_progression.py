#!/usr/bin/env python
"""Build the read-only Chapter 4.3 progression funnel audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tbm_twin.evaluation.chapter43_progression_audit import (
    PAPER_DIR,
    build_chapter43_progression_audit,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PAPER_DIR / "chapter43_progression_audit",
    )
    args = parser.parse_args()
    result = build_chapter43_progression_audit(args.repo_root, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
