from __future__ import annotations

from pathlib import Path

import pandas as pd

from tbm_twin.evaluation.construction_progression_review import (
    _first_recorded_value,
    _format_chainage,
    classify_field_relation,
    scope_relation,
)
from tbm_twin.evaluation.paper_evidence_completion import (
    _episode_stratum,
    _paper_rai_status,
    _value_set,
    score_geology_field_annotations,
    score_plc_episode_annotations,
)
from tbm_twin.evaluation.paper_final_addendum import (
    _format_chainage as _format_metadata_chainage,
)
from tbm_twin.evaluation.paper_final_addendum import _intervals_intersect, _is_trusted_footprint


def test_episode_strata_keep_review_risks_separate() -> None:
    base = {
        "boundary_status": "COMPLETE",
        "quality_flags": [],
        "interruption_duration_seconds": 0.0,
        "quality_grade": "A",
    }
    assert _episode_stratum(base, {"estimated_advance_m": 1.0}) == "ROUTINE_COMPLETE"
    assert _episode_stratum({**base, "boundary_status": "LEFT_CENSORED"}, {}) == "BOUNDARY_CENSORED"
    assert _episode_stratum(base, {"estimated_advance_m": 0}) == "ZERO_ADVANCE_REVIEW"


def test_geology_value_set_supports_json_lists_and_chinese_separator() -> None:
    assert _value_set('["滴渗水", "线状出水"]') == {"滴渗水", "线状出水"}
    assert _value_set("滴渗水、线状出水") == {"滴渗水", "线状出水"}


def test_geology_scoring_does_not_invent_unreviewed_results(tmp_path: Path) -> None:
    annotations = tmp_path / "annotations.csv"
    pd.DataFrame(
        [
            {
                "field_name": "lithology",
                "predicted_value": "板岩夹变质砂岩",
                "manual_value": "板岩夹变质砂岩",
                "review_complete": True,
            },
            {
                "field_name": "water_type",
                "predicted_value": "滴渗水",
                "manual_value": "线状出水",
                "review_complete": False,
            },
        ]
    ).to_csv(annotations, index=False)
    result = score_geology_field_annotations(annotations, tmp_path / "scores")
    assert result["reviewed_field_count"] == 1
    assert result["exact_match_rate"] == 1.0


def test_plc_scoring_adds_chainage_error(tmp_path: Path) -> None:
    packet = tmp_path / "packet"
    packet.mkdir()
    pd.DataFrame(
        [
            {
                "sample_id": "sample-1",
                "system_episode_id": "episode-1",
                "excavation_start": "2023-12-30T00:00:00Z",
                "excavation_end": "2023-12-30T00:10:00Z",
                "start_chainage": 100.0,
                "end_chainage": 110.0,
            }
        ]
    ).to_csv(packet / "system_predictions.csv", index=False)
    annotations = tmp_path / "annotations.csv"
    pd.DataFrame(
        [
            {
                "sample_id": "sample-1",
                "manual_episode_id": "gold-1",
                "is_valid_excavation": True,
                "manual_start_time": "2023-12-30T00:00:10Z",
                "manual_end_time": "2023-12-30T00:09:50Z",
                "manual_start_chainage": 101.0,
                "manual_end_chainage": 109.0,
                "review_complete": True,
            }
        ]
    ).to_csv(annotations, index=False)
    result = score_plc_episode_annotations(packet, annotations, tmp_path / "scores")
    assert result["metrics"]["episode_f1"] == 1.0
    assert result["metrics"]["mean_start_chainage_error_m"] == 1.0
    assert result["metrics"]["mean_end_chainage_error_m"] == 1.0


def test_progression_scope_requires_direct_evidence_overlap() -> None:
    forecast = {"start_chainage": 100.0, "end_chainage": 120.0}
    point_inside = {"start_chainage": 110.0, "end_chainage": 110.0}
    point_same_cell_but_outside = {"start_chainage": 121.0, "end_chainage": 121.0}
    assert scope_relation(forecast, point_inside) == "DIRECT_SCOPE_OVERLAP"
    assert scope_relation(forecast, point_same_cell_but_outside) == "SHARED_DAILY_REVIEW_CELL_ONLY"


def test_field_relation_is_descriptive_not_accuracy_judgment() -> None:
    assert (
        classify_field_relation("弱风化", "弱风化", "DIRECT_SCOPE_OVERLAP") == "SAME_RECORDED_VALUE"
    )
    assert (
        classify_field_relation("Ⅴ级", "Ⅳ级", "DIRECT_SCOPE_OVERLAP") == "DIFFERENT_RECORDED_VALUE"
    )
    assert (
        classify_field_relation("破碎", "破碎", "SHARED_DAILY_REVIEW_CELL_ONLY")
        == "SPATIAL_SCALE_NOT_DIRECTLY_COMPARABLE"
    )


def test_progression_field_alias_uses_first_recorded_value() -> None:
    field, value = _first_recorded_value(
        {"suggested_grade": "Ⅴ级", "surrounding_rock_grade": "Ⅳ级"},
        ["suggested_grade", "surrounding_rock_grade"],
    )
    assert field == "suggested_grade"
    assert value == "Ⅴ级"


def test_geophysical_anomaly_is_not_a_cross_source_comparison_dimension() -> None:
    config_text = Path("configs/paper_evidence_completion.yaml").read_text(encoding="utf-8")
    progression_block = config_text.split("construction_progression_review:", 1)[1]
    assert "comparison_dimensions:" in progression_block
    assert "anomaly_level:" not in progression_block


def test_progression_figure_formats_absolute_chainage_as_route_chainage() -> None:
    assert _format_chainage(1013320.2) == "DyK1013+320.2"


def test_progression_episode_coverage_requires_actual_interval_intersection() -> None:
    assert _intervals_intersect(1013320.0, 1013321.0, 1013320.2, 1013320.2)
    assert not _intervals_intersect(1013321.0, 1013322.0, 1013320.2, 1013320.2)


def test_progression_episode_coverage_requires_trusted_usable_footprint() -> None:
    footprint = {
        "spatial_scope_usable": True,
        "chainage_regime_status": "TRUSTED",
        "trusted_spatial_scope": {"start_chainage": 1.0, "end_chainage": 2.0},
    }
    assert _is_trusted_footprint(footprint)
    assert not _is_trusted_footprint({**footprint, "chainage_regime_status": "UNRESOLVED"})


def test_paper_rai_reason_uses_historical_not_causal_terminology() -> None:
    assert _paper_rai_status("INSUFFICIENT_CAUSAL_BASELINE") == "INSUFFICIENT_HISTORICAL_BASELINE"
    assert _paper_rai_status("AVAILABLE") == "AVAILABLE"


def test_paper_metadata_formats_engineering_chainage() -> None:
    assert _format_metadata_chainage(1013090.0) == "DyK1013+090"
    assert _format_metadata_chainage(1013320.2) == "DyK1013+320.2"
