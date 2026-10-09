"""Dry-run or execute the 152 additions to the Stage7 200-task benchmark."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.evaluation.stage7_supplemental import run_supplemental_execution
from tbm_twin.realization.providers.deepseek_adapter import (
    DEEPSEEK_RESPONSES_SUPPORTED_MODEL,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default=DEEPSEEK_RESPONSES_SUPPORTED_MODEL)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = run_supplemental_execution(
        Path.cwd(),
        provider=args.provider,
        model=args.model,
        execute=args.execute,
    )
    print(result.get("status", result.get("stage7b_status", "UNKNOWN")))


if __name__ == "__main__":
    main()
