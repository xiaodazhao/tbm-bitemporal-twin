"""Summary table builders for Stage 1 validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from tbm_twin.process.models import ExcavationEpisode
from tbm_twin.trajectory.models import SpatialFootprint

PLC_REFERENCE_REVIEW_COLUMNS = [
    "date",
    "system_episode_id",
    "plc_support_label",
    "supported_core_start",
    "supported_core_end",
    "merge_candidate",
    "split_candidate",
    "signal_conflicts",
    "review_confidence",
    "review_notes",
]


def build_validation_summary_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build cross-date validation summary rows."""

    rows: list[dict[str, Any]] = []
    for result in results:
        diagnostics = result.get("diagnostics", {})
        rows.append(
            {
                "date": result["date"],
                "status": result["status"],
                "input_path": result.get("input_path"),
                "raw_row_count": _nested(diagnostics, "data_scale", "raw_row_count"),
                "normalized_row_count": _nested(diagnostics, "data_scale", "normalized_row_count"),
                "quality_grade": result.get("quality_grade"),
                "episode_count": _nested(diagnostics, "episode", "episode_count"),
                "data_gap_count": _nested(diagnostics, "time", "data_gap_count"),
                "inconsistent_footprint_count": _nested(
                    diagnostics, "footprint", "inconsistent_count"
                ),
                "insufficient_footprint_count": _nested(
                    diagnostics, "footprint", "insufficient_count"
                ),
                "error_type": _nested(result, "error", "error_type"),
                "error_message": _nested(result, "error", "message"),
            }
        )
    return rows


def build_episode_summary_rows(
    date: str,
    episodes: list[ExcavationEpisode],
    footprints: list[SpatialFootprint],
) -> list[dict[str, Any]]:
    """Build rows for episode summary and manual review."""

    footprint_by_episode = {footprint.episode_id: footprint for footprint in footprints}
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        footprint = footprint_by_episode.get(episode.episode_id)
        rows.append(
            {
                "date": date,
                "system_episode_id": episode.episode_id,
                "system_start_time": episode.excavation_start.isoformat(),
                "system_end_time": episode.excavation_end.isoformat(),
                "system_duration_seconds": episode.core_excavation_duration_seconds,
                "system_context_start": episode.context_start.isoformat(),
                "system_context_end": episode.context_end.isoformat(),
                "system_context_duration_seconds": episode.context_duration_seconds,
                "system_interruption_duration_seconds": episode.interruption_duration_seconds,
                "system_excavating_segment_count": episode.excavating_segment_count,
                "system_temporal_coverage_ratio": episode.temporal_coverage_ratio,
                "system_boundary_status": episode.boundary_status.value,
                "system_actual_start_known": episode.actual_start_known,
                "system_actual_end_known": episode.actual_end_known,
                "system_start_chainage": footprint.start_chainage if footprint else None,
                "system_end_chainage": footprint.end_chainage if footprint else None,
                "system_estimated_advance_m": footprint.estimated_advance_m if footprint else None,
                "system_quality_grade": episode.quality_grade,
                "system_quality_reason_codes": ";".join(episode.quality_reason_codes),
                "system_quality_flags": ";".join(episode.quality_flags),
                "manual_accept": "",
                "manual_start_time": "",
                "manual_end_time": "",
                "manual_split_required": "",
                "manual_merge_with_previous": "",
                "manual_notes": "",
            }
        )
    return rows


def build_footprint_summary_rows(
    date: str,
    footprints: list[SpatialFootprint],
) -> list[dict[str, Any]]:
    """Build cross-date footprint summary rows."""

    return [
        {
            "date": date,
            "episode_id": footprint.episode_id,
            "footprint_id": footprint.footprint_id,
            "start_chainage": footprint.start_chainage,
            "end_chainage": footprint.end_chainage,
            "estimated_advance_m": footprint.estimated_advance_m,
            "consistency_status": footprint.consistency_status.value,
            "quality_grade": footprint.quality_grade,
            "quality_flags": ";".join(footprint.quality_flags),
            "precise_advance_usable": footprint.consistency_status.value
            not in {"INCONSISTENT", "INSUFFICIENT"}
            and "ZERO_ADVANCE_DURING_EXCAVATION" not in footprint.quality_flags,
            "supporting_source_count": footprint.supporting_source_count,
            "consistency_checks_performed": footprint.consistency_checks_performed,
            "primary_observation_count": footprint.primary_observation_count,
        }
        for footprint in footprints
    ]


def write_manual_template(path: Path) -> None:
    """Write an empty manual annotation template."""

    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=PLC_REFERENCE_REVIEW_COLUMNS).to_csv(path, index=False)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write rows to CSV."""

    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
