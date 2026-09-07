"""Build the Stage7D deterministic bitemporal-value experiment artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.evaluation.stage7d import OUTPUT_DIR, build_stage7d_bitemporal_value


def main() -> None:
    """Run the read-only Stage7D analysis."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--no-zip", action="store_true")
    args = parser.parse_args()
    result = build_stage7d_bitemporal_value(
        args.repo_root,
        args.output_dir,
        create_audit_zip=not args.no_zip,
    )
    for key, value in sorted(result.items()):
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
