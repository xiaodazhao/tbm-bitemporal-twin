#!/usr/bin/env python
"""Score completed PLC or geological manual annotations."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.evaluation.paper_evidence_completion import (
    score_geology_field_annotations,
    score_plc_episode_annotations,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="kind", required=True)
    plc = subparsers.add_parser("plc")
    plc.add_argument("--packet-dir", required=True, type=Path)
    plc.add_argument("--annotations", required=True, type=Path)
    plc.add_argument("--output-dir", required=True, type=Path)
    geology = subparsers.add_parser("geology")
    geology.add_argument("--annotations", required=True, type=Path)
    geology.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    if args.kind == "plc":
        result = score_plc_episode_annotations(args.packet_dir, args.annotations, args.output_dir)
        print(result["metrics"])
    else:
        print(score_geology_field_annotations(args.annotations, args.output_dir))


if __name__ == "__main__":
    main()
