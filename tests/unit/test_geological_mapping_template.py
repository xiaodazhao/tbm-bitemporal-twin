from tbm_twin.metrics.geology_inventory import build_geological_inventory


def test_geological_mapping_template_is_pending_manual_review() -> None:
    _, template, mapping_audit, _ = build_geological_inventory(
        evidence_rows=[
            {
                "evidence_uid": "g1",
                "document_id": "d1",
                "source_type": "TSP_REPORT",
                "evidence_type": "FORECAST_SEGMENT",
                "epistemic_status": "FORECAST",
                "attributes": {"surrounding_rock_grade": "Ⅴ级"},
                "source_spans": [],
            }
        ],
        document_rows=[],
        stage3b_snapshots=[],
    )
    assert template["grs_status"] == "GEOLOGICAL_ATTENTION_MAPPING_NOT_FROZEN"
    assert len(template["mappings"]) == 1
    assert template["mappings"][0]["attention_value"] is None
    assert template["mappings"][0]["review_status"] == "PENDING_MANUAL_REVIEW"
    assert mapping_audit[0]["status"] == "PASS"
