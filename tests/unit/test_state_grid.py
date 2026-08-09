from tbm_twin.state.grid import (
    cell_index_for_point,
    make_cell,
    split_scope_to_cells,
    stable_cell_id,
)
from tbm_twin.state.models import (
    ChainageDirection,
    ConstructionStateConfig,
    PointBoundaryPolicy,
)


def _config() -> ConstructionStateConfig:
    return ConstructionStateConfig(
        alignment_id="boshulaling_import_right",
        chainage_direction=ChainageDirection.INCREASING,
        cell_size_m=10.0,
        grid_origin_m=0.0,
        point_boundary_policy=PointBoundaryPolicy.RIGHT_CLOSED_PREVIOUS_CELL,
        state_method_version="stage3a_initial_epistemic_state_v1_1_point_response_complete",
    )


def test_right_closed_point_boundary_maps_boundary_to_previous_cell() -> None:
    assert cell_index_for_point(1013200.0, origin=0.0, cell_size=10.0) == 101319
    assert cell_index_for_point(1013200.001, origin=0.0, cell_size=10.0) == 101320


def test_interval_split_conserves_overlap_length() -> None:
    config = _config()
    cells_by_index = {index: make_cell(index, config) for index in range(101319, 101322)}
    pieces = split_scope_to_cells(
        {
            "kind": "INTERVAL",
            "start_chainage": 1013195.0,
            "end_chainage": 1013212.0,
        },
        cells_by_index,
        origin=config.grid_origin_m,
        cell_size=config.cell_size_m,
    )

    assert [(piece[1], piece[2], piece[3]) for piece in pieces] == [
        (1013195.0, 1013200.0, 5.0),
        (1013200.0, 1013210.0, 10.0),
        (1013210.0, 1013212.0, 2.0),
    ]
    assert sum(piece[3] for piece in pieces) == 17.0


def test_cell_id_is_stable_for_same_grid_definition() -> None:
    config = _config()

    assert stable_cell_id(config, 101319) == stable_cell_id(config, 101319)
    assert stable_cell_id(config, 101319) != stable_cell_id(config, 101320)
