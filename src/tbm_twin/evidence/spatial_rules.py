"""Spatial applicability rules."""

from __future__ import annotations

from tbm_twin.evidence.models import ChainageInterval, SpatialApplicabilityStatus
from tbm_twin.trajectory.models import SpatialFootprint


def spatial_relation(
    interval: ChainageInterval | None,
    footprint: SpatialFootprint | None,
    *,
    adjacent_tolerance_m: float,
    ahead_context_limit_m: float,
) -> SpatialApplicabilityStatus:
    """Classify relation between geological interval and episode footprint."""

    if (
        interval is None
        or footprint is None
        or not interval.spatial_scope_usable
        or interval.normalized_start_chainage is None
        or interval.normalized_end_chainage is None
        or footprint.start_chainage is None
        or footprint.end_chainage is None
    ):
        if interval is not None and not interval.spatial_scope_usable:
            return SpatialApplicabilityStatus.INVALID
        return SpatialApplicabilityStatus.UNKNOWN
    start = interval.normalized_start_chainage
    end = interval.normalized_end_chainage
    target_start = min(footprint.start_chainage, footprint.end_chainage)
    target_end = max(footprint.start_chainage, footprint.end_chainage)
    if end >= target_start and start <= target_end:
        return SpatialApplicabilityStatus.OVERLAP
    if (
        abs(start - target_end) <= adjacent_tolerance_m
        or abs(target_start - end) <= adjacent_tolerance_m
    ):
        return SpatialApplicabilityStatus.ADJACENT
    if start > target_end and start - target_end <= ahead_context_limit_m:
        return SpatialApplicabilityStatus.AHEAD
    if end < target_start:
        return SpatialApplicabilityStatus.BEHIND
    return SpatialApplicabilityStatus.DISJOINT
