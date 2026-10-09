#!/usr/bin/env python
"""Build the offline paper-evidence completion artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.evaluation.paper_evidence_completion import (
    DEFAULT_CONFIG,
    DEFAULT_OUTPUT_DIR,
    build_paper_evidence_completion,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    result = build_paper_evidence_completion(args.repo_root, args.output_dir, args.config)
    for key, value in sorted(result.items()):
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
