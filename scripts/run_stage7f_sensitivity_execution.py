#!/usr/bin/env python
"""Execute the frozen Stage7F-B deterministic OFAT sensitivity experiment."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.evaluation.stage7f_execution import execute_stage7f


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output = execute_stage7f(args.repo_root, args.output_dir)
    print(f"Stage7F-B deterministic sensitivity artifact: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
