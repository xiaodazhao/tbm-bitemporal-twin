from tbm_twin.state.io import stable_id


def test_state_version_id_recipe_does_not_include_generated_at() -> None:
    base = stable_id(
        "daily_state_x",
        "cell_y",
        "1",
        "stage3a_initial_epistemic_state_v1_1_point_response_complete",
    )

    assert base == stable_id(
        "daily_state_x",
        "cell_y",
        "1",
        "stage3a_initial_epistemic_state_v1_1_point_response_complete",
    )
    assert base != stable_id(
        "daily_state_x",
        "cell_y",
        "1",
        "stage3a_initial_epistemic_state_v1_1_point_response_complete",
        "2026-07-30T14:30:00+08:00",
    )
