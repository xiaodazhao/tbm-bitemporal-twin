#!/usr/bin/env python
"""Validate Stage 2 evidence over Stage 1 artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from tbm_twin.evidence.applicability import applicability_summary, assign_evidence_to_episode
from tbm_twin.evidence.geology_normalizer import (
    geological_evidence_summary,
    normalize_geological_evidence,
)
from tbm_twin.evidence.response_builder import (
    build_response_evidence,
    response_evidence_summary,
)
from tbm_twin.process.models import ExcavationEpisode
from tbm_twin.trajectory.models import SpatialFootprint
from tbm_twin.validation.stage2_diagnostics import (
    evidence_level_applicability_summary,
    stage2_diagnostics,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1-artifact-dir", required=True, type=Path)
    parser.add_argument("--geology-input", required=True, type=Path)
    parser.add_argument("--dates", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    dates = [date.strip() for date in args.dates.split(",") if date.strip()]
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        episodes, footprints, normalized = _load_stage1(args.stage1_artifact_dir, dates)
        response_records = build_response_evidence(normalized, episodes, footprints)
        geology_records = normalize_geological_evidence(args.geology_input)
        footprint_by_episode = {footprint.episode_id: footprint for footprint in footprints}
        assignments = []
        for response in response_records:
            episode = next(item for item in episodes if item.episode_id == response.episode_id)
            assignments.append(
                assign_evidence_to_episode(
                    response,
                    episode,
                    footprint_by_episode.get(episode.episode_id),
                    evaluation_time=episode.excavation_end,
                )
            )
        for geology in geology_records:
            for episode in episodes:
                assignments.append(
                    assign_evidence_to_episode(
                        geology,
                        episode,
                        footprint_by_episode.get(episode.episode_id),
                        evaluation_time=episode.excavation_end,
                    )
                )

        _write_json(
            args.output_dir / "response_evidence.json",
            [record.model_dump(mode="json") for record in response_records],
        )
        pd.DataFrame(response_evidence_summary(response_records)).to_csv(
            args.output_dir / "response_evidence_summary.csv",
            index=False,
        )
        _write_json(
            args.output_dir / "geological_evidence.json",
            [record.model_dump(mode="json") for record in geology_records],
        )
        pd.DataFrame(geological_evidence_summary(geology_records)).to_csv(
            args.output_dir / "geological_evidence_summary.csv",
            index=False,
        )
        _write_json(
            args.output_dir / "applicability_assignments.json",
            [record.model_dump(mode="json") for record in assignments],
        )
        summary = applicability_summary(assignments)
        pd.DataFrame(summary).to_csv(args.output_dir / "applicability_summary.csv", index=False)
        diagnostics = stage2_diagnostics(
            responses=response_records,
            geology=geology_records,
            assignments=assignments,
        )
        _write_diagnostic_tables(
            args.output_dir,
            summary,
            diagnostics,
            response_records,
            geology_records,
            assignments,
        )
        _write_report(args.output_dir / "stage21_validation_report.md", diagnostics)
        _write_report(args.output_dir / "stage2_validation_report.md", diagnostics)
    except (OSError, ValueError, StopIteration) as exc:
        print(f"validate_stage2_evidence failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote Stage 2 validation to {args.output_dir}")
    return 0


def _load_stage1(
    artifact_dir: Path,
    dates: list[str],
) -> tuple[list[ExcavationEpisode], list[SpatialFootprint], pd.DataFrame]:
    episodes: list[ExcavationEpisode] = []
    footprints: list[SpatialFootprint] = []
    frames: list[pd.DataFrame] = []
    for date in dates:
        date_dir = artifact_dir / date
        episodes.extend(
            ExcavationEpisode.model_validate(item)
            for item in json.loads((date_dir / "episodes.json").read_text(encoding="utf-8"))
        )
        footprints.extend(
            SpatialFootprint.model_validate(item)
            for item in json.loads(
                (date_dir / "spatial_footprints.json").read_text(encoding="utf-8")
            )
        )
        frames.append(pd.read_parquet(date_dir / "normalized_plc.parquet"))
    return episodes, footprints, pd.concat(frames, ignore_index=True)


def _write_diagnostic_tables(
    output_dir: Path,
    applicability_rows: list[dict[str, Any]],
    diagnostics: dict[str, Any],
    response_records: list[Any],
    geology_records: list[Any],
    assignments: list[Any],
) -> None:
    frame = pd.DataFrame(applicability_rows)
    frame[frame["temporal_status"].eq("NOT_YET_AVAILABLE")].to_csv(
        output_dir / "temporal_leakage_check.csv",
        index=False,
    )
    frame[["spatial_status", "result"]].value_counts().reset_index(name="count").to_csv(
        output_dir / "spatial_relation_summary.csv",
        index=False,
    )
    frame[["epistemic_status", "result"]].value_counts().reset_index(name="count").to_csv(
        output_dir / "epistemic_status_summary.csv",
        index=False,
    )
    pd.DataFrame(
        [
            {
                "evidence_id": record.evidence_id,
                "quality_grade": record.quality_grade.value,
                "quality_flags": ";".join(record.quality_flags),
            }
            for record in geology_records
        ]
    ).to_csv(output_dir / "evidence_quality_summary.csv", index=False)
    matrix_columns = [
        "evidence_type",
        "evidence_epistemic_status",
        "temporal_status",
        "spatial_status",
        "result",
    ]
    frame[matrix_columns].value_counts(dropna=False).reset_index(name="count").to_csv(
        output_dir / "applicability_result_matrix.csv",
        index=False,
    )
    evidence_level_rows = evidence_level_applicability_summary(
        assignments=assignments,
        evidence_ids=[record.evidence_id for record in response_records],
        evidence_family="RESPONSE",
    ) + evidence_level_applicability_summary(
        assignments=assignments,
        evidence_ids=[record.evidence_id for record in geology_records],
        evidence_family="GEOLOGICAL",
    )
    pd.DataFrame(evidence_level_rows).to_csv(
        output_dir / "evidence_level_applicability_summary.csv",
        index=False,
    )
    pd.DataFrame(_epistemic_mapping_audit(geology_records)).to_csv(
        output_dir / "epistemic_mapping_audit.csv",
        index=False,
    )
    pd.DataFrame(_chainage_anomaly_audit(geology_records)).to_csv(
        output_dir / "chainage_anomaly_audit.csv",
        index=False,
    )
    _write_json(
        output_dir / "temporal_validation_status.json",
        {
            "historically_evaluable_geological_evidence_count": diagnostics[
                "historically_evaluable_geological_evidence_count"
            ],
            "real_data_temporal_applicability_validation": diagnostics[
                "real_data_temporal_applicability_validation"
            ],
            "detected_future_leakage_count": diagnostics["detected_future_leakage_count"],
            "interpretation": (
                "No geological evidence has confirmed available_time in the real data; zero "
                "future leakage only shows unknown-time evidence was not unconditionally used."
            ),
        },
    )
    _write_json(output_dir / "stage2_diagnostics.json", diagnostics)


def _write_report(path: Path, diagnostics: dict[str, Any]) -> None:
    lines = [
        "# Stage 2.1 Validation",
        "",
        (
            "Stage 2.1 builds structured evidence over PLC-inferred episodes. It does not "
            "independently verify the occurrence of construction events."
        ),
        "",
        f"- response evidence count: {diagnostics['response_evidence_count']}",
        f"- geological evidence count: {diagnostics['geological_evidence_count']}",
        f"- available_time unknown: {diagnostics['available_time_unknown_count']}",
        f"- spatial scope unknown: {diagnostics['spatial_scope_unknown_count']}",
        f"- epistemic UNKNOWN: {diagnostics['epistemic_status_unknown_count']}",
        f"- detected future leakage count: {diagnostics['detected_future_leakage_count']}",
        (
            "- historically evaluable geological evidence count: "
            f"{diagnostics['historically_evaluable_geological_evidence_count']}"
        ),
        (
            "- real-data temporal applicability validation: "
            f"{diagnostics['real_data_temporal_applicability_validation']}"
        ),
        "",
        (
            "Real data contains no geological evidence with confirmed available_time when this "
            "count is zero; detected future leakage of 0 only means unknown-time evidence was not "
            "unconditionally used, not that historical temporal applicability is empirically "
            "proven."
        ),
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _epistemic_mapping_audit(records: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": record.evidence_id,
            "source_record_id": record.source_record_id,
            "source_type_raw": record.source_type_raw,
            "source_type": record.geological_source_type.value,
            "epistemic_status_before_mapping": record.epistemic_status_before_mapping.value,
            "epistemic_status_after_mapping": record.epistemic_status.value,
            "epistemic_mapping_basis": record.epistemic_mapping_basis,
            "has_conflict": "EPISTEMIC_SOURCE_CONFLICT" in record.parse_warnings,
            "parse_warnings": ";".join(record.parse_warnings),
        }
        for record in records
    ]


def _chainage_anomaly_audit(records: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        interval = record.chainage_interval
        if interval is None:
            rows.append(
                {
                    "evidence_id": record.evidence_id,
                    "source_record_id": record.source_record_id,
                    "spatial_scope_usable": False,
                    "validation_flags": "SPATIAL_SCOPE_UNKNOWN",
                    "raw_start_chainage": None,
                    "raw_end_chainage": None,
                    "normalized_start_chainage": None,
                    "normalized_end_chainage": None,
                    "normalization_reason": None,
                    "suggested_normalization": None,
                }
            )
            continue
        if not interval.validation_flags:
            continue
        rows.append(
            {
                "evidence_id": record.evidence_id,
                "source_record_id": record.source_record_id,
                "spatial_scope_usable": interval.spatial_scope_usable,
                "validation_flags": ";".join(interval.validation_flags),
                "raw_start_chainage": interval.raw_start_chainage,
                "raw_end_chainage": interval.raw_end_chainage,
                "normalized_start_chainage": interval.normalized_start_chainage,
                "normalized_end_chainage": interval.normalized_end_chainage,
                "normalization_reason": interval.normalization_reason,
                "suggested_normalization": interval.suggested_normalization,
            }
        )
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
