from tbm_twin.state.grid import make_cell, split_scope_to_cells
from tbm_twin.state.models import (
    ChainageDirection,
    ConstructionStateConfig,
    PointBoundaryPolicy,
)


def test_state_interval_overlap_length_is_conserved_across_cells() -> None:
    config = ConstructionStateConfig(
        alignment_id="boshulaling_import_right",
        chainage_direction=ChainageDirection.INCREASING,
        cell_size_m=10.0,
        grid_origin_m=0.0,
        point_boundary_policy=PointBoundaryPolicy.RIGHT_CLOSED_PREVIOUS_CELL,
        state_method_version="stage3a_initial_epistemic_state_v1_1_point_response_complete",
    )
    cells_by_index = {index: make_cell(index, config) for index in range(101319, 101322)}

    pieces = split_scope_to_cells(
        {"kind": "INTERVAL", "start_chainage": 1013198.0, "end_chainage": 1013214.0},
        cells_by_index,
        origin=0.0,
        cell_size=10.0,
    )

    assert sum(piece[3] for piece in pieces) == 16.0
    assert all(piece[3] > 0 for piece in pieces)
