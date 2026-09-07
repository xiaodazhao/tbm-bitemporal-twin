"""Build the Stage7E-B v1.1 offline deterministic audit correction."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.evaluation.stage7e_audit_correction import (
    Stage7EAuditCorrectionError,
    build_stage7e_audit_correction,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="artifacts/stage7e_ablation_execution_v1_1_correction",
    )
    parser.add_argument("--generated-at")
    parser.add_argument("--no-audit-zip", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        result = build_stage7e_audit_correction(
            root,
            output_dir=root / args.output_dir,
            generated_at=args.generated_at,
            create_audit_zip=not args.no_audit_zip,
        )
    except Stage7EAuditCorrectionError as exc:
        print(f"STAGE7E_V1_1_CORRECTION_FAILED {exc}")
        raise SystemExit(1) from exc
    print(f"STAGE7E_V1_1_STATUS {result['status']}")
    print(f"STAGE7E_V1_1_HARD_CHECK_FAILURES {result['hard_check_failure_count']}")
    print("STAGE7E_V1_1_API_CALLS 0")


if __name__ == "__main__":
    main()
