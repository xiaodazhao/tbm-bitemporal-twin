"""Quality-aware spatial footprint estimation."""

from tbm_twin.trajectory.footprint_builder import build_spatial_footprints
from tbm_twin.trajectory.models import ConsistencyCheckResult, ConsistencyStatus, SpatialFootprint

__all__ = [
    "ConsistencyCheckResult",
    "ConsistencyStatus",
    "SpatialFootprint",
    "build_spatial_footprints",
]
