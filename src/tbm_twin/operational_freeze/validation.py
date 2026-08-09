"""Hard-check helpers for the Stage 2E operational freeze."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from tbm_twin.evidence.models import ResponseEvidence
from tbm_twin.process.models import ExcavationEpisode, OperationPhase
from tbm_twin.trajectory.models import SpatialFootprint


def episode_integrity_rows(
    *,
    target_date: date,
    episodes: list[ExcavationEpisode],
    labeled_frame: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Return issue rows for episode-observation reference integrity."""

    rows: list[dict[str, Any]] = []
    observed_ids = set(labeled_frame["observation_id"].astype(str).to_list())
    phase_by_observation = dict(
        zip(
            labeled_frame["observation_id"].astype(str).to_list(),
            labeled_frame["operation_phase"].astype(str).to_list(),
            strict=True,
        )
    )
    core_seen: dict[str, str] = {}
    for episode in episodes:
        _check(
            episode.context_start <= episode.excavation_start,
            rows,
            target_date,
            episode,
            "context_start_after_core_start",
        )
        _check(
            episode.excavation_end <= episode.context_end,
            rows,
            target_date,
            episode,
            "core_end_after_context_end",
        )
        _check(
            episode.excavation_start <= episode.excavation_end,
            rows,
            target_date,
            episode,
            "excavation_start_after_end",
        )
        for ref in episode.observation_refs:
            _check(
                ref in observed_ids, rows, target_date, episode, f"missing_observation_ref:{ref}"
            )
        for ref in episode.core_observation_refs:
            _check(
                ref in observed_ids,
                rows,
                target_date,
                episode,
                f"missing_core_observation_ref:{ref}",
            )
            _check(
                phase_by_observation.get(ref) == OperationPhase.EXCAVATING.value,
                rows,
                target_date,
                episode,
                f"core_ref_not_excavating:{ref}",
            )
            if ref in core_seen:
                rows.append(
                    {
                        "target_date": target_date,
                        "episode_id": episode.episode_id,
                        "issue_code": f"core_ref_duplicate:{ref}",
                        "details": core_seen[ref],
                    }
                )
            core_seen[ref] = episode.episode_id
        if any(interval.phase == OperationPhase.DATA_GAP for interval in episode.phase_sequence):
            rows.append(
                {
                    "target_date": target_date,
                    "episode_id": episode.episode_id,
                    "issue_code": "episode_crosses_data_gap",
                    "details": "",
                }
            )
    return rows


def footprint_integrity_rows(
    *,
    target_date: date,
    footprints: list[SpatialFootprint],
    episode_ids: set[str],
) -> list[dict[str, Any]]:
    """Return issue rows for footprint integrity."""

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for footprint in footprints:
        if footprint.footprint_id in seen:
            rows.append(
                _issue(
                    target_date,
                    footprint.episode_id,
                    "duplicate_footprint_id",
                    footprint.footprint_id,
                )
            )
        seen.add(footprint.footprint_id)
        if footprint.episode_id not in episode_ids:
            rows.append(
                _issue(
                    target_date,
                    footprint.episode_id,
                    "missing_episode_for_footprint",
                    footprint.footprint_id,
                )
            )
        if (
            footprint.start_chainage is not None
            and footprint.end_chainage is not None
            and footprint.start_chainage > footprint.end_chainage
        ):
            rows.append(
                _issue(
                    target_date, footprint.episode_id, "reverse_footprint", footprint.footprint_id
                )
            )
    return rows


def response_integrity_rows(
    *,
    target_date: date,
    responses: list[ResponseEvidence],
    episodes_by_id: dict[str, ExcavationEpisode],
) -> list[dict[str, Any]]:
    """Return issue rows for response evidence integrity and Stage 2E semantics."""

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for response in responses:
        if response.evidence_id in seen:
            rows.append(
                _issue(
                    target_date,
                    response.episode_id,
                    "duplicate_response_evidence_id",
                    response.evidence_id,
                )
            )
        seen.add(response.evidence_id)
        episode = episodes_by_id.get(response.episode_id)
        if episode is None:
            rows.append(
                _issue(
                    target_date,
                    response.episode_id,
                    "missing_episode_for_response",
                    response.evidence_id,
                )
            )
            continue
        if set(response.core_observation_refs) - set(episode.core_observation_refs):
            rows.append(
                _issue(
                    target_date,
                    response.episode_id,
                    "response_uses_non_core_ref",
                    response.evidence_id,
                )
            )
        if (
            response.available_time is not None
            and response.valid_time is not None
            and response.available_time < response.valid_time.end
        ):
            rows.append(
                _issue(
                    target_date,
                    response.episode_id,
                    "available_time_before_valid_end",
                    response.evidence_id,
                )
            )
        if response.baseline is not None or response.deviation is not None:
            rows.append(
                _issue(
                    target_date,
                    response.episode_id,
                    "baseline_or_deviation_present",
                    response.evidence_id,
                )
            )
    return rows


def _check(
    condition: bool,
    rows: list[dict[str, Any]],
    target_date: date,
    episode: ExcavationEpisode,
    issue_code: str,
) -> None:
    if not condition:
        rows.append(
            {
                "target_date": target_date,
                "episode_id": episode.episode_id,
                "issue_code": issue_code,
                "details": "",
            }
        )


def _issue(target_date: date, episode_id: str, issue_code: str, details: str) -> dict[str, Any]:
    return {
        "target_date": target_date,
        "episode_id": episode_id,
        "issue_code": issue_code,
        "details": details,
    }
