"""Static 10m grid helpers for Stage 3A state cells."""

from __future__ import annotations

import math
from typing import Any

from tbm_twin.state.models import ConstructionStateCell, ConstructionStateConfig


def cell_index_for_point(point: float, *, origin: float, cell_size: float) -> int:
    """Map a point to exactly one right-closed cell."""

    return math.ceil((point - origin) / cell_size) - 1


def cell_index_for_start(start: float, *, origin: float, cell_size: float) -> int:
    """Return the first cell that can overlap an interval starting at ``start``."""

    return math.floor((start - origin) / cell_size)


def cell_index_for_end(end: float, *, origin: float, cell_size: float) -> int:
    """Return the last cell that can overlap an interval ending at ``end``."""

    return math.ceil((end - origin) / cell_size) - 1


def cell_bounds(index: int, *, origin: float, cell_size: float) -> tuple[float, float]:
    """Return deterministic cell bounds."""

    start = origin + index * cell_size
    return round(start, 3), round(start + cell_size, 3)


def generate_cells_for_scopes(
    scopes: list[dict[str, Any]],
    config: ConstructionStateConfig,
) -> list[ConstructionStateCell]:
    """Generate the static grid covering the trusted Stage 2 scope union."""

    starts: list[float] = []
    ends: list[float] = []
    for scope in scopes:
        starts.append(float(scope["start_chainage"]))
        ends.append(float(scope["end_chainage"]))
    if not starts:
        return []
    first = cell_index_for_start(
        min(starts),
        origin=config.grid_origin_m,
        cell_size=config.cell_size_m,
    )
    last = cell_index_for_end(
        max(ends),
        origin=config.grid_origin_m,
        cell_size=config.cell_size_m,
    )
    return [make_cell(index, config) for index in range(first, last + 1)]


def make_cell(index: int, config: ConstructionStateConfig) -> ConstructionStateCell:
    """Build one static cell."""

    start, end = cell_bounds(index, origin=config.grid_origin_m, cell_size=config.cell_size_m)
    return ConstructionStateCell(
        cell_id=stable_cell_id(config, index),
        alignment_id=config.alignment_id,
        cell_index=index,
        spatial_start=start,
        spatial_end=end,
        cell_size_m=config.cell_size_m,
        grid_origin_m=config.grid_origin_m,
        chainage_direction=config.chainage_direction.value,
        interval_convention="RIGHT_CLOSED_OPEN_LEFT",
        point_boundary_policy=config.point_boundary_policy.value,
        cell_method_version=config.state_method_version,
    )


def split_scope_to_cells(
    scope: dict[str, Any],
    cells_by_index: dict[int, ConstructionStateCell],
    *,
    origin: float,
    cell_size: float,
) -> list[tuple[ConstructionStateCell, float, float, float]]:
    """Split an overlap scope to cells."""

    kind = scope.get("kind")
    start = float(scope["start_chainage"])
    end = float(scope["end_chainage"])
    if kind == "POINT":
        index = cell_index_for_point(start, origin=origin, cell_size=cell_size)
        cell = cells_by_index[index]
        return [(cell, start, end, 1.0)]
    if kind != "INTERVAL" or end <= start:
        return []
    first = cell_index_for_start(start, origin=origin, cell_size=cell_size)
    last = cell_index_for_end(end, origin=origin, cell_size=cell_size)
    pieces: list[tuple[ConstructionStateCell, float, float, float]] = []
    for index in range(first, last + 1):
        cell = cells_by_index[index]
        overlap_start = max(start, cell.spatial_start)
        overlap_end = min(end, cell.spatial_end)
        length = round(overlap_end - overlap_start, 6)
        if length > 0:
            pieces.append((cell, round(overlap_start, 3), round(overlap_end, 3), length))
    return pieces


def stable_cell_id(config: ConstructionStateConfig, index: int) -> str:
    """Stable cell identifier."""

    from tbm_twin.state.io import stable_id

    return "cell_" + stable_id(
        config.alignment_id,
        str(config.grid_origin_m),
        str(config.cell_size_m),
        str(index),
        config.point_boundary_policy.value,
    )
