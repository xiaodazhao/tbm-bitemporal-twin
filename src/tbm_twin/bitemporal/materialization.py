"""Materialization helpers for Stage 3B state versions."""

from __future__ import annotations

from typing import Any


def sorted_unique(values: list[str]) -> list[str]:
    """Return deterministic unique string values."""

    return sorted(set(values))


def materialized_snapshot(version: dict[str, Any]) -> dict[str, Any]:
    """Create a standalone materialized snapshot row for one version."""

    keys = [
        "bitemporal_version_id",
        "base_stage3a_state_version_id",
        "daily_state_id",
        "cell_id",
        "cell_scope_role",
        "valid_date",
        "knowledge_time_start_local_date",
        "knowledge_time_end_local_date",
        "version_number",
        "is_current_as_of_cutoff",
        "materialized_daily_review_evidence_ids",
        "materialized_forward_attention_evidence_ids",
        "materialized_local_background_evidence_ids",
        "materialized_observed_evidence_ids",
        "materialized_forecast_evidence_ids",
        "materialized_background_evidence_ids",
        "materialized_source_assignment_ids",
        "inherited_stage3a_geological_link_ids",
        "materialized_revision_geological_link_ids",
        "materialized_episode_ids",
        "materialized_response_evidence_ids",
        "materialized_response_link_ids",
        "state_quality_flags",
        "state_reason_codes",
        "stage3b_method_version",
    ]
    snapshot = {key: version[key] for key in keys}
    snapshot["snapshot_id"] = (
        f"snapshot_{version['bitemporal_version_id'].removeprefix('bitemporal_version_')}"
    )
    return snapshot
