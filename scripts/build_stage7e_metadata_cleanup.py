"""Build Stage7E-B v1.1a final machine-result metadata."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.evaluation.stage7e_metadata_cleanup import (
    Stage7EMetadataCleanupError,
    build_stage7e_metadata_cleanup,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup",
    )
    parser.add_argument("--generated-at")
    parser.add_argument("--no-audit-zip", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        result = build_stage7e_metadata_cleanup(
            root,
            output_dir=root / args.output_dir,
            generated_at=args.generated_at,
            create_audit_zip=not args.no_audit_zip,
        )
    except Stage7EMetadataCleanupError as exc:
        print(f"STAGE7E_V1_1A_METADATA_CLEANUP_FAILED {exc}")
        raise SystemExit(1) from exc
    print(f"STAGE7E_V1_1A_STATUS {result['status']}")
    print(f"STAGE7E_V1_1A_HARD_CHECK_FAILURES {result['hard_check_failure_count']}")
    print("STAGE7E_V1_1A_API_CALLS 0")


if __name__ == "__main__":
    main()
