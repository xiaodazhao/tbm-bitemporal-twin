"""Generate Parser V2 design, Gold, and sample audits."""

# ruff: noqa: E402

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.validate_stage2_raw_geology import parse_raw_geology
from tbm_twin.geology.parsers_v2 import parse_pdf_v2
from tbm_twin.geology.parsers_v2.template_inventory import (
    build_template_variants,
    inventory_pdf,
    unclassified_rows,
)

TBM9 = Path(
    "/Users/zhaoxiaoda/Library/CloudStorage/GoogleDrive-xiaodazhao0608@gmail.com/我的云端硬盘/TBM9"
)
OLD_DB = TBM9 / "DB" / "evidence_db.csv"
OUT = ROOT / "artifacts" / "stage2_parser_v2_design"
GOLD = ROOT / "tests" / "gold" / "geology"

SKETCH_SAMPLE = TBM9 / "SKETCH" / "DyK1013+184.20_伯舒拉岭进口右线DyK1013+184.2洞身素描记录表.pdf"
HSP_SAMPLE = sorted((TBM9 / "HSP").glob("DyK1013+190.20_*.pdf"))[0]
TSP_SAMPLE = sorted((TBM9 / "TSP").glob("DyK1013+124.20_*.pdf"))[0]


def main() -> None:
    """Generate all Parser V2 design artifacts."""

    OUT.mkdir(parents=True, exist_ok=True)
    GOLD.mkdir(parents=True, exist_ok=True)
    pdfs = sorted((TBM9 / "HSP").glob("*.pdf"))
    pdfs += sorted((TBM9 / "TSP").glob("*.pdf"))
    pdfs += sorted((TBM9 / "SKETCH").glob("*.pdf"))
    inventory_rows = [inventory_pdf(path) for path in pdfs]
    _write_csv(OUT / "template_inventory.csv", inventory_rows)
    variants = build_template_variants(inventory_rows)
    (OUT / "template_variants.json").write_text(
        json.dumps(variants, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_csv(OUT / "unclassified_template_audit.csv", unclassified_rows(inventory_rows))
    results = {
        "sketch": parse_pdf_v2(SKETCH_SAMPLE),
        "hsp": parse_pdf_v2(HSP_SAMPLE),
        "tsp": parse_pdf_v2(TSP_SAMPLE),
    }
    _write_gold(results)
    _write_gold_validation_report(results)
    _write_design_report(inventory_rows, variants)
    _write_v1_v2_sample_comparison(results)
    _write_legacy_mapping_audits(results)


def _write_gold(results: dict[str, Any]) -> None:
    for name, result in results.items():
        payload = result.model_dump(mode="json")
        if name == "sketch":
            filename = "sketch_dyk1013_184_2.json"
        elif name == "hsp":
            filename = "hsp_dyk1013_190_2.json"
        else:
            filename = "tsp_dyk1013_080_2.json"
        (GOLD / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _write_gold_validation_report(results: dict[str, Any]) -> None:
    lines = ["# Parser V2 Gold Validation", ""]
    for name, result in results.items():
        lines.append(f"## {name}")
        lines.append(f"- primary_evidence_count: {len(result.primary_evidence)}")
        lines.append(f"- report_assertion_count: {len(result.report_assertions)}")
        lines.append(f"- temporal: {result.document.temporal.model_dump()}")
        lines.append(
            "- ranges: "
            + json.dumps(
                [
                    [item.spatial_scope.start_chainage, item.spatial_scope.end_chainage]
                    for item in result.primary_evidence
                ],
                ensure_ascii=False,
            )
        )
        if name == "tsp":
            conflicts = [
                assertion.model_dump(mode="json")
                for assertion in result.report_assertions
                if assertion.consistency_status == "CONFLICT"
            ]
            lines.append(f"- conflicts: {json.dumps(conflicts, ensure_ascii=False)}")
        lines.append("")
    (OUT / "gold_validation_report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_design_report(inventory_rows: list[dict[str, Any]], variants: dict[str, Any]) -> None:
    db = pd.read_csv(OLD_DB)
    sonic = db[db.source_type == "sonic"]
    lines = [
        "# Stage 2 Geological Parser V2 Design Report",
        "",
        "## Current Facts",
        "- V1 parser file: src/tbm_twin/geology/document_parsers.py, 2219 lines at audit time.",
        "- Current GeologicalEvidence model is unchanged; Parser V2 uses parallel models.",
        "- Old repository parsers were read only from "
        "/Users/zhaoxiaoda/tbm-report/backend/parsers.",
        f"- Legacy evidence_db rows: {len(db)}.",
        "- Legacy sketch point: 169.",
        (
            f"- Legacy sonic segment: {len(sonic)}, from {sonic.report_id.nunique()} reports, "
            f"per-report count {sonic.groupby('report_id').size().min()}-"
            f"{sonic.groupby('report_id').size().max()}, not fixed at 4."
        ),
        "- Legacy TSP segment: 67.",
        "- Legacy TSP report_conclusion: 71.",
        "- Legacy TSP overview: 1.",
        "- Legacy report_date equals issue_date: 484/484.",
        "",
        "## V2 Boundary",
        "- V2 is parallel under src/tbm_twin/geology/parsers_v2 and is not wired into "
        "the full Stage 2 pipeline.",
        "- Main Evidence types are FACE_OBSERVATION, FORECAST_SEGMENT, and DESIGN_BACKGROUND.",
        "- TSP chapter 7 summaries are ReportAssertion records and do not enter "
        "EvidenceApplicabilityAssignment.",
        "- pdfplumber is declared as a project dependency; this runtime lacked it, so "
        "inventory records PDFPLUMBER_UNAVAILABLE and the three executable Gold parses "
        "use the PyMuPDF text layer with explicit SourceSpan text positions.",
        "",
        "## Template Inventory",
        f"- inventoried_pdf_count: {len(inventory_rows)}",
        f"- template_variant_count: {len(variants)}",
    ]
    (OUT / "design_report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_v1_v2_sample_comparison(results: dict[str, Any]) -> None:
    v1 = parse_raw_geology(
        tsp_dir=TBM9 / "TSP",
        hsp_dir=TBM9 / "HSP",
        sketch_dir=TBM9 / "SKETCH",
    )
    v1_counts: dict[str, int] = {}
    for key, path in {"sketch": SKETCH_SAMPLE, "hsp": HSP_SAMPLE, "tsp": TSP_SAMPLE}.items():
        count = sum(path.stem == ev.title for ev in v1["evidence"])
        v1_counts[key] = count
    rows = [
        {
            "sample": key,
            "source_pdf_path": str(path),
            "v1_primary_like_evidence_count": v1_counts[key],
            "v2_primary_evidence_count": len(results[key].primary_evidence),
            "v2_report_assertion_count": len(results[key].report_assertions),
            "v2_ranges": json.dumps(
                [
                    [item.spatial_scope.start_chainage, item.spatial_scope.end_chainage]
                    for item in results[key].primary_evidence
                ],
                ensure_ascii=False,
            ),
        }
        for key, path in {"sketch": SKETCH_SAMPLE, "hsp": HSP_SAMPLE, "tsp": TSP_SAMPLE}.items()
    ]
    _write_csv(OUT / "v1_v2_sample_comparison.csv", rows)


def _write_legacy_mapping_audits(results: dict[str, Any]) -> None:
    db = pd.read_csv(OLD_DB)
    primary_rows: list[dict[str, Any]] = []
    assertion_rows: list[dict[str, Any]] = []
    for row in db.to_dict("records"):
        source_type = row["source_type"]
        level = row["source_level"]
        if source_type == "sketch" and level == "point":
            target = "FACE_OBSERVATION"
        elif (source_type == "sonic" and level == "segment") or (
            source_type == "tsp" and level == "segment"
        ):
            target = "FORECAST_SEGMENT"
        elif source_type == "tsp" and level == "overview":
            target = "FACE_OBSERVATION_OR_ASSERTION_REVIEW"
        elif source_type == "tsp" and level == "report_conclusion":
            assertion_rows.append({**row, "v2_target": "ReportAssertion"})
            continue
        else:
            target = "UNMAPPED"
        primary_rows.append({**row, "v2_target": target})
    _write_csv(OUT / "legacy_primary_mapping_audit.csv", primary_rows)
    _write_csv(OUT / "legacy_assertion_mapping_audit.csv", assertion_rows)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("reason\n", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
