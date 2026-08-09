from tbm_twin.metrics.grci import build_grci


def test_grci_only_available_for_daily_review_cell() -> None:
    versions = [
        {
            "bitemporal_version_id": "b1",
            "base_stage3a_state_version_id": "s1",
            "valid_date": "2023-01-01",
            "knowledge_time_start_local_date": "2023-01-01",
            "cell_id": "c1",
            "cell_scope_role": "DAILY_REVIEW_CELL",
        },
        {
            "bitemporal_version_id": "b2",
            "base_stage3a_state_version_id": "s2",
            "valid_date": "2023-01-01",
            "knowledge_time_start_local_date": "2023-01-01",
            "cell_id": "c2",
            "cell_scope_role": "FORWARD_ATTENTION_CELL",
        },
    ]
    rai = {vid: {"rai": 0.5} for vid in ["b1", "b2"]}
    grs = {vid: {"grs": 0.5} for vid in ["b1", "b2"]}
    rows, _ = build_grci(versions, rai, grs)
    assert rows[0]["grci"] == 0.25
    assert rows[0]["is_probability"] is False
    assert rows[1]["grci"] is None
    assert rows[1]["grci_status"] == "GRCI_NOT_DEFINED_FOR_FORWARD_ATTENTION"
