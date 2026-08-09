from tbm_twin.state.grid import cell_bounds, cell_index_for_point


def test_point_on_ten_meter_boundary_maps_to_lower_chainage_cell() -> None:
    index = cell_index_for_point(1013200.0, origin=0.0, cell_size=10.0)

    assert cell_bounds(index, origin=0.0, cell_size=10.0) == (1013190.0, 1013200.0)
