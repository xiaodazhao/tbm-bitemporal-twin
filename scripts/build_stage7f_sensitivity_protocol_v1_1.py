#!/usr/bin/env python3
"""Build the Stage7F-A v1.1 metric-semantics metadata correction."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.evaluation.stage7f_protocol_v1_1 import (
    OUTPUT_DIR,
    build_stage7f_protocol_v1_1,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--no-zip", action="store_true")
    args = parser.parse_args()
    result = build_stage7f_protocol_v1_1(
        args.repo_root,
        args.output_dir,
        create_audit_zip=not args.no_zip,
    )
    for key, value in sorted(result.items()):
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
