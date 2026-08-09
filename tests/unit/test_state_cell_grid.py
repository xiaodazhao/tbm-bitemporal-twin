from tbm_twin.state.grid import generate_cells_for_scopes
from tbm_twin.state.models import (
    ChainageDirection,
    ConstructionStateConfig,
    PointBoundaryPolicy,
)


def test_construction_state_grid_uses_ten_meter_trusted_scope_union() -> None:
    config = ConstructionStateConfig(
        alignment_id="boshulaling_import_right",
        chainage_direction=ChainageDirection.INCREASING,
        cell_size_m=10.0,
        grid_origin_m=0.0,
        point_boundary_policy=PointBoundaryPolicy.RIGHT_CLOSED_PREVIOUS_CELL,
        state_method_version="stage3a_initial_epistemic_state_v1_1_point_response_complete",
    )

    cells = generate_cells_for_scopes(
        [
            {"kind": "INTERVAL", "start_chainage": 1013190.0, "end_chainage": 1013200.0},
            {"kind": "INTERVAL", "start_chainage": 1013200.0, "end_chainage": 1013230.0},
        ],
        config,
    )

    assert len(cells) == 4
    assert cells[0].spatial_start == 1013190.0
    assert cells[-1].spatial_end == 1013230.0
    assert {cell.cell_size_m for cell in cells} == {10.0}
