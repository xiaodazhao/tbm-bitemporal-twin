#!/usr/bin/env python
"""Normalize geological evidence from CSV or JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from tbm_twin.evidence.geology_normalizer import (
    geological_evidence_summary,
    normalize_geological_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        records = normalize_geological_evidence(args.input)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = [record.model_dump(mode="json") for record in records]
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        pd.DataFrame(geological_evidence_summary(records)).to_csv(
            args.output.with_name("geological_evidence_summary.csv"),
            index=False,
        )
        diagnostics = {
            "geological_evidence_count": len(records),
            "available_time_unknown_count": sum(
                record.available_time is None for record in records
            ),
            "spatial_scope_unknown_count": sum(
                record.chainage_interval is None for record in records
            ),
        }
        args.output.with_name("geology_parse_diagnostics.json").write_text(
            json.dumps(diagnostics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        print(f"normalize_geological_evidence failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote GeologicalEvidence to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
