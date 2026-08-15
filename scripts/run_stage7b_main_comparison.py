"""Run Stage7B frozen three-method real-model benchmark.

The command is fail-closed unless --execute is explicitly supplied.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.evaluation.stage7b import (
    DEEPSEEK_RESPONSES_SUPPORTED_MODEL,
    Stage7BPreflightError,
    run_stage7b,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default=DEEPSEEK_RESPONSES_SUPPORTED_MODEL)
    parser.add_argument("--output-root", default="artifacts/stage7b_main_comparison_v1")
    parser.add_argument("--execution-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.dry_run and args.execute:
        raise SystemExit("--dry-run and --execute are mutually exclusive")
    repo_root = Path(__file__).resolve().parents[1]
    try:
        result = run_stage7b(
            repo_root,
            provider=args.provider,
            model=args.model,
            execute=args.execute,
            output_root=repo_root / args.output_root,
            execution_id=args.execution_id,
        )
    except Stage7BPreflightError as exc:
        print(f"STAGE7B_PREFLIGHT_FAILED {exc}")
        raise SystemExit(1) from exc
    if args.execute:
        print(f"STAGE7B_EXECUTION_COMPLETE {result['execution_id']}")
    else:
        print(result["stage7b_status"])


if __name__ == "__main__":
    main()
