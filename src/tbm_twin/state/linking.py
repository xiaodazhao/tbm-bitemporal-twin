"""Evidence-to-state linking helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tbm_twin.state.grid import cell_index_for_point, split_scope_to_cells
from tbm_twin.state.models import CellScopeRole, ConstructionStateCell, ConstructionStateConfig

ROLE_TO_CELL_ROLE = {
    "DAILY_REVIEW": CellScopeRole.DAILY_REVIEW_CELL,
    "FORWARD_ATTENTION": CellScopeRole.FORWARD_ATTENTION_CELL,
    "LOCAL_BACKGROUND": CellScopeRole.LOCAL_BACKGROUND_CELL,
}


@dataclass(frozen=True)
class ResponseCellPiece:
    """Trusted operational response scope mapped to one state cell."""

    cell: ConstructionStateCell
    start: float
    end: float
    length: float
    trusted_overlap_kind: str
    spatial_relation: str
    mapped_cell_role: CellScopeRole | None


def cell_role_for_assignment(role: str) -> CellScopeRole:
    """Return the only allowed cell role for an applicability role."""

    return ROLE_TO_CELL_ROLE[role]


def split_assignment_to_role_cells(
    assignment: dict[str, Any],
    *,
    cells_by_index: dict[int, ConstructionStateCell],
    cell_roles: dict[str, CellScopeRole],
    config: ConstructionStateConfig,
) -> list[tuple[ConstructionStateCell, float, float, float]]:
    """Split a non-NOT assignment overlap to matching-role cells."""

    target_role = cell_role_for_assignment(str(assignment["applicability_role"]))
    pieces = split_scope_to_cells(
        assignment["overlap_scope"],
        cells_by_index,
        origin=config.grid_origin_m,
        cell_size=config.cell_size_m,
    )
    return [piece for piece in pieces if cell_roles.get(piece[0].cell_id) == target_role]


def map_trusted_point_response_to_cell(
    scope: dict[str, Any],
    *,
    cells_by_index: dict[int, ConstructionStateCell],
    cell_roles: dict[str, CellScopeRole],
    config: ConstructionStateConfig,
) -> ResponseCellPiece | None:
    """Map a trusted POINT response to the single right-closed cell."""

    if scope.get("kind") != "POINT":
        return None
    point = float(scope["start_chainage"])
    index = cell_index_for_point(
        point,
        origin=config.grid_origin_m,
        cell_size=config.cell_size_m,
    )
    cell = cells_by_index.get(index)
    if cell is None:
        return None
    return ResponseCellPiece(
        cell=cell,
        start=point,
        end=point,
        length=0.0,
        trusted_overlap_kind="POINT",
        spatial_relation="POINT_IN_CELL",
        mapped_cell_role=cell_roles.get(cell.cell_id),
    )


def split_trusted_response_to_daily_cells(
    scope: dict[str, Any],
    *,
    cells_by_index: dict[int, ConstructionStateCell],
    cell_roles: dict[str, CellScopeRole],
    config: ConstructionStateConfig,
) -> list[ResponseCellPiece]:
    """Split trusted response scope to daily-review cells only."""

    if scope.get("kind") == "POINT":
        piece = map_trusted_point_response_to_cell(
            scope,
            cells_by_index=cells_by_index,
            cell_roles=cell_roles,
            config=config,
        )
        if piece and piece.mapped_cell_role == CellScopeRole.DAILY_REVIEW_CELL:
            return [piece]
        return []
    if scope.get("kind") != "INTERVAL" or float(scope["end_chainage"]) <= float(
        scope["start_chainage"]
    ):
        return []
    pieces = split_scope_to_cells(
        scope,
        cells_by_index,
        origin=config.grid_origin_m,
        cell_size=config.cell_size_m,
    )
    return [
        ResponseCellPiece(
            cell=cell,
            start=start,
            end=end,
            length=length,
            trusted_overlap_kind="INTERVAL",
            spatial_relation="INTERVAL_OVERLAP",
            mapped_cell_role=cell_roles.get(cell.cell_id),
        )
        for cell, start, end, length in pieces
        if cell_roles.get(cell.cell_id) == CellScopeRole.DAILY_REVIEW_CELL
    ]
