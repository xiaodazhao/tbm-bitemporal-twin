from tbm_twin.metrics.geological_mapping import build_formal_mapping


def test_formal_mapping_preserves_null_unmappable() -> None:
    rows, by_key, audit = build_formal_mapping(
        [
            {
                "mapping_id": "review1",
                "attribute_name": "water_type",
                "normalized_serialization": "null",
            }
        ],
        [
            {
                "attribute_name": "water_type",
                "normalized_serialization": None,
                "dimension_name": "WATER_ATTENTION",
                "ordinal_rank": None,
                "ordinal_scale_max": None,
                "attention_value": None,
                "mapping_basis": "MISSING_SOURCE_INFORMATION",
                "review_status": "REVIEWED_UNMAPPABLE",
            }
        ],
    )
    assert rows[0]["attention_value"] is None
    assert rows[0]["review_status"] == "REVIEWED_UNMAPPABLE"
    assert ("water_type", "null") in by_key
    assert audit[0]["status"] == "PASS"
