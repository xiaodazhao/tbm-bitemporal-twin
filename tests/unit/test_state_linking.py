from tbm_twin.state.grid import make_cell
from tbm_twin.state.linking import (
    map_trusted_point_response_to_cell,
    split_assignment_to_role_cells,
    split_trusted_response_to_daily_cells,
)
from tbm_twin.state.models import (
    CellScopeRole,
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


def test_assignment_links_only_to_matching_cell_role() -> None:
    config = _config()
    cells_by_index = {index: make_cell(index, config) for index in range(101319, 101321)}
    first_cell = cells_by_index[101319]
    assignment = {
        "applicability_role": "DAILY_REVIEW",
        "overlap_scope": {
            "kind": "INTERVAL",
            "start_chainage": 1013195.0,
            "end_chainage": 1013210.0,
        },
    }

    pieces = split_assignment_to_role_cells(
        assignment,
        cells_by_index=cells_by_index,
        cell_roles={first_cell.cell_id: CellScopeRole.DAILY_REVIEW_CELL},
        config=config,
    )

    assert len(pieces) == 1
    assert pieces[0][0].cell_id == first_cell.cell_id
    assert pieces[0][3] == 5.0


def test_response_links_require_trusted_interval_scope() -> None:
    config = _config()
    cells_by_index = {101319: make_cell(101319, config)}

    pieces = split_trusted_response_to_daily_cells(
        {
            "kind": "POINT",
            "start_chainage": 1013200.0,
            "end_chainage": 1013200.0,
        },
        cells_by_index=cells_by_index,
        cell_roles={},
        config=config,
    )

    assert pieces == []


def test_trusted_point_response_links_to_unique_daily_review_cell_with_zero_length() -> None:
    config = _config()
    cell = make_cell(101319, config)

    pieces = split_trusted_response_to_daily_cells(
        {
            "kind": "POINT",
            "start_chainage": 1013200.0,
            "end_chainage": 1013200.0,
        },
        cells_by_index={101319: cell},
        cell_roles={cell.cell_id: CellScopeRole.DAILY_REVIEW_CELL},
        config=config,
    )

    assert len(pieces) == 1
    assert pieces[0].cell.cell_id == cell.cell_id
    assert pieces[0].trusted_overlap_kind == "POINT"
    assert pieces[0].spatial_relation == "POINT_IN_CELL"
    assert pieces[0].length == 0.0


def test_trusted_point_response_can_be_located_without_daily_review_assignment() -> None:
    config = _config()
    cell = make_cell(101319, config)

    piece = map_trusted_point_response_to_cell(
        {
            "kind": "POINT",
            "start_chainage": 1013200.0,
            "end_chainage": 1013200.0,
        },
        cells_by_index={101319: cell},
        cell_roles={cell.cell_id: CellScopeRole.LOCAL_BACKGROUND_CELL},
        config=config,
    )
    linked = split_trusted_response_to_daily_cells(
        {
            "kind": "POINT",
            "start_chainage": 1013200.0,
            "end_chainage": 1013200.0,
        },
        cells_by_index={101319: cell},
        cell_roles={cell.cell_id: CellScopeRole.LOCAL_BACKGROUND_CELL},
        config=config,
    )

    assert piece is not None
    assert piece.mapped_cell_role == CellScopeRole.LOCAL_BACKGROUND_CELL
    assert linked == []
