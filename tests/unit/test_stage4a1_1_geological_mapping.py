from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tbm_twin.metrics.stage4a1_1_builder import Stage4A11Builder


def test_mapping_review_only_includes_scalar_dimensions_and_used_values() -> None:
    builder = Stage4A11Builder(
        repo_root=Path.cwd(),
        generated_at=datetime(2026, 8, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    inventory = [
        {
            "attribute_name": "water_type",
            "raw_value": "滴渗水",
            "normalized_serialization": "滴渗水",
            "source_type": "FACE_SKETCH",
            "evidence_type": "FACE_OBSERVATION",
            "epistemic_status": "OBSERVED",
            "evidence_count": "2",
            "used_in_stage3b_snapshot_count": "3",
            "used_in_daily_review_count": "1",
            "used_in_forward_attention_count": "2",
            "used_in_local_background_count": "0",
        },
        {
            "attribute_name": "lithology",
            "raw_value": "板岩",
            "normalized_serialization": "板岩",
            "source_type": "FACE_SKETCH",
            "evidence_type": "FACE_OBSERVATION",
            "epistemic_status": "OBSERVED",
            "evidence_count": "2",
            "used_in_stage3b_snapshot_count": "3",
            "used_in_daily_review_count": "1",
            "used_in_forward_attention_count": "2",
            "used_in_local_background_count": "0",
        },
        {
            "attribute_name": "joint_development",
            "raw_value": "UNKNOWN",
            "normalized_serialization": "UNKNOWN",
            "source_type": "FACE_SKETCH",
            "evidence_type": "FACE_OBSERVATION",
            "epistemic_status": "OBSERVED",
            "evidence_count": "1",
            "used_in_stage3b_snapshot_count": "0",
            "used_in_daily_review_count": "0",
            "used_in_forward_attention_count": "0",
            "used_in_local_background_count": "0",
        },
    ]
    review = builder._mapping_review(inventory)
    assert len(review["mappings"]) == 1
    assert review["mappings"][0]["attribute_name"] == "water_type"
    assert review["mappings"][0]["attention_value"] is None
    assert review["mappings"][0]["ordinal_rank"] is None


def test_unknown_mapping_status_is_not_zero() -> None:
    builder = Stage4A11Builder(
        repo_root=Path.cwd(),
        generated_at=datetime(2026, 8, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    review = builder._mapping_review(
        [
            {
                "attribute_name": "joint_development",
                "raw_value": "UNKNOWN",
                "normalized_serialization": "UNKNOWN",
                "source_type": "FACE_SKETCH",
                "evidence_type": "FACE_OBSERVATION",
                "epistemic_status": "OBSERVED",
                "evidence_count": "1",
                "used_in_stage3b_snapshot_count": "1",
                "used_in_daily_review_count": "1",
                "used_in_forward_attention_count": "0",
                "used_in_local_background_count": "0",
            }
        ]
    )
    assert review["mappings"][0]["mapping_status"] == "NOT_MAPPABLE_WITHOUT_INFORMATION"
    assert review["mappings"][0]["attention_value"] is None
