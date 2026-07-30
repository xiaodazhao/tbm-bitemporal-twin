"""Temporal applicability rules."""

from __future__ import annotations

from datetime import datetime

from tbm_twin.evidence.models import (
    EvidenceBase,
    TemporalApplicabilityStatus,
    TemporalExtent,
)


def temporal_status(
    evidence: EvidenceBase, evaluation_time: datetime
) -> TemporalApplicabilityStatus:
    """Evaluate evidence availability without future leakage."""

    extent = getattr(evidence, "available_time_extent", None)
    if isinstance(extent, TemporalExtent):
        return evaluate_temporal_availability(
            available_time=evidence.available_time,
            available_time_extent=extent,
            evaluation_time=evaluation_time,
        )
    if evidence.available_time is None:
        return TemporalApplicabilityStatus.AVAILABLE_TIME_UNKNOWN
    if evidence.available_time > evaluation_time:
        return TemporalApplicabilityStatus.NOT_YET_AVAILABLE
    return TemporalApplicabilityStatus.AVAILABLE


def evaluate_temporal_availability(
    *,
    available_time: datetime | None,
    available_time_extent: TemporalExtent | None,
    evaluation_time: datetime,
) -> TemporalApplicabilityStatus:
    """Evaluate availability with day-precision temporal extents."""

    if evaluation_time.tzinfo is None:
        return TemporalApplicabilityStatus.INVALID_TEMPORAL_METADATA
    if available_time_extent is not None:
        if (
            available_time_extent.latest_possible_time
            <= available_time_extent.earliest_possible_time
        ):
            return TemporalApplicabilityStatus.INVALID_TEMPORAL_METADATA
        if evaluation_time < available_time_extent.earliest_possible_time:
            return TemporalApplicabilityStatus.NOT_YET_AVAILABLE
        if evaluation_time >= available_time_extent.latest_possible_time:
            return TemporalApplicabilityStatus.AVAILABLE
        return TemporalApplicabilityStatus.UNKNOWN_WITHIN_PRECISION
    if available_time is None:
        return TemporalApplicabilityStatus.AVAILABLE_TIME_UNKNOWN
    if available_time.tzinfo is None:
        return TemporalApplicabilityStatus.INVALID_TEMPORAL_METADATA
    if available_time > evaluation_time:
        return TemporalApplicabilityStatus.NOT_YET_AVAILABLE
    return TemporalApplicabilityStatus.AVAILABLE
