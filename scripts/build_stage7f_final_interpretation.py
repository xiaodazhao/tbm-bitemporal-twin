#!/usr/bin/env python3
"""Build Stage7F-B v1.1 final interpretation without rerunning arms."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.evaluation.stage7f_final_interpretation import (
    OUTPUT_DIR,
    build_final_interpretation,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--no-zip", action="store_true")
    args = parser.parse_args()
    result = build_final_interpretation(
        args.repo_root,
        args.output_dir,
        create_audit_zip=not args.no_zip,
    )
    for key, value in sorted(result.items()):
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
