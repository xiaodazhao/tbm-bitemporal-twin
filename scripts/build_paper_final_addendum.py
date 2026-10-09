#!/usr/bin/env python
"""Build the three read-only final paper audits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tbm_twin.evaluation.paper_final_addendum import (
    PAPER_OUTPUT_DIR,
    build_paper_final_addendum,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=PAPER_OUTPUT_DIR)
    args = parser.parse_args()
    result = build_paper_final_addendum(args.repo_root, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
