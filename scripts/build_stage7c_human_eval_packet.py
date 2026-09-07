"""Build Stage7C.2A blinded human-evaluation packets."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.evaluation.stage7c_human_eval import build_human_evaluation_packet


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="artifacts/stage7c_human_eval_packet_v1_1",
    )
    parser.add_argument("--no-zip", action="store_true")
    args = parser.parse_args()
    repo_root = Path.cwd()
    summary = build_human_evaluation_packet(
        repo_root,
        repo_root / args.output_dir,
        write_audit_zip=not args.no_zip,
    )
    for key in sorted(summary):
        print(f"{key}={summary[key]}")


if __name__ == "__main__":
    main()
