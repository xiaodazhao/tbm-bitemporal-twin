"""Build Stage7C.1 deterministic automatic evaluation artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.evaluation.stage7c import build_stage7c_auto_eval


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="artifacts/stage7c_main_auto_eval_v1_2",
        help="Stage7C.1 output artifact directory.",
    )
    parser.add_argument(
        "--no-zip",
        action="store_true",
        help="Skip audit ZIP creation.",
    )
    args = parser.parse_args()
    repo_root = Path.cwd()
    summary = build_stage7c_auto_eval(
        repo_root,
        repo_root / args.output_dir,
        write_audit_zip=not args.no_zip,
    )
    for key in sorted(summary):
        print(f"{key}={summary[key]}")


if __name__ == "__main__":
    main()
