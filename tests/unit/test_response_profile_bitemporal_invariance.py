from tbm_twin.metrics.response_profile import build_bitemporal_profile_bindings


def test_bitemporal_bindings_share_base_profile_for_revised_chain() -> None:
    bindings, audit = build_bitemporal_profile_bindings(
        bitemporal_versions=[
            {
                "bitemporal_version_id": "b1",
                "base_stage3a_state_version_id": "s1",
                "valid_date": "2023-01-02",
                "knowledge_time_start_local_date": "2023-01-02",
                "version_number": 1,
            },
            {
                "bitemporal_version_id": "b2",
                "base_stage3a_state_version_id": "s1",
                "valid_date": "2023-01-02",
                "knowledge_time_start_local_date": "2023-01-03",
                "version_number": 2,
            },
        ],
        profile_by_state_id={
            "s1": {
                "response_profile_id": "p1",
                "response_evidence_ids": ["r1"],
                "response_component_ids": ["dc1"],
            }
        },
    )
    assert len(bindings) == 2
    assert {row["response_profile_id"] for row in bindings} == {"p1"}
    assert audit[0]["profile_diff_count"] == 0
    assert audit[0]["status"] == "PASS"
