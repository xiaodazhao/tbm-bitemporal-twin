from tbm_twin.metrics.geology_inventory import build_geological_inventory


def test_geological_inventory_uses_structured_attributes_only() -> None:
    inventory, _, _, reference_audit = build_geological_inventory(
        evidence_rows=[
            {
                "evidence_uid": "g1",
                "document_id": "d1",
                "source_type": "FACE_SKETCH",
                "evidence_type": "FACE_OBSERVATION",
                "epistemic_status": "OBSERVED",
                "attributes": {"lithology": "板岩夹变质砂岩", "water_state": None},
                "source_spans": [{"span_id": "span1"}],
                "raw_text": "should not be inventoried",
            }
        ],
        document_rows=[{"document_id": "d1", "available_time_extent": {"start": "2023-01-02"}}],
        stage3b_snapshots=[{"materialized_daily_review_evidence_ids": ["g1"]}],
    )
    names = {row["attribute_name"] for row in inventory}
    assert names == {"lithology", "water_state"}
    assert {row["attribute_name"] for row in reference_audit} == names
    assert all(row["source"] == "attributes" for row in reference_audit)
