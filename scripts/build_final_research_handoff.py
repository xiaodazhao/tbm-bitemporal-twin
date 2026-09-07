#!/usr/bin/env python3
"""Build the Final Research Handoff Bundle v1 from frozen artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.evaluation.final_handoff import build_final_handoff


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = build_final_handoff(args.repo, args.output)
    print(output)


if __name__ == "__main__":
    main()
