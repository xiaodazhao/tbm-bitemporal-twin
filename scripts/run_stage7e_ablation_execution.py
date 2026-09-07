"""Run or replay the frozen Stage7E-B ablation execution."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.evaluation.stage7e_execution import (
    Stage7EExecutionError,
    replay_stage7e,
    run_stage7e,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--replay", action="store_true")
    parser.add_argument("--output-dir", default="artifacts/stage7e_ablation_execution_v1")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / args.output_dir
    try:
        if args.replay:
            result = replay_stage7e(root, output)
        else:
            result = run_stage7e(root, execute=args.execute, output_dir=output)
    except Stage7EExecutionError as exc:
        print(f"STAGE7E_EXECUTION_FAILED {exc}")
        raise SystemExit(1) from exc
    print(f"STAGE7E_STATUS {result['status']}")
    print(f"STAGE7E_ACTUAL_ATTEMPTS {result['actual_attempts']}")


if __name__ == "__main__":
    main()
