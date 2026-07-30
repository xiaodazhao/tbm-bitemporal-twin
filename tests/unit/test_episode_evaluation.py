from __future__ import annotations

import pandas as pd

from tbm_twin.validation.evaluation import (
    EpisodeEvaluationConfig,
    evaluate_episode_predictions,
)


def test_episode_iou_matching_and_boundary_errors() -> None:
    predictions = pd.DataFrame(
        [
            {
                "date": "2023-12-30",
                "system_episode_id": "p1",
                "system_start_time": "2023-12-30T00:00:10Z",
                "system_end_time": "2023-12-30T00:10:00Z",
            }
        ]
    )
    annotations = pd.DataFrame(
        [
            {
                "date": "2023-12-30",
                "manual_episode_id": "g1",
                "manual_start_time": "2023-12-30T00:00:00Z",
                "manual_end_time": "2023-12-30T00:10:10Z",
                "is_valid_excavation": True,
            }
        ]
    )

    result = evaluate_episode_predictions(
        predictions,
        annotations,
        EpisodeEvaluationConfig(minimum_iou_for_match=0.5, boundary_tolerance_seconds=5.0),
    )

    assert result["metrics"]["episode_precision"] == 1.0
    assert result["metrics"]["episode_recall"] == 1.0
    assert result["metrics"]["mean_start_boundary_error_seconds"] == 10.0
    assert len(result["boundary_error_cases"]) == 1


def test_over_and_under_segmentation_are_episode_level() -> None:
    predictions = pd.DataFrame(
        [
            {
                "date": "2023-12-30",
                "system_episode_id": "p1",
                "system_start_time": "2023-12-30T00:00:00Z",
                "system_end_time": "2023-12-30T00:04:00Z",
            },
            {
                "date": "2023-12-30",
                "system_episode_id": "p2",
                "system_start_time": "2023-12-30T00:04:30Z",
                "system_end_time": "2023-12-30T00:10:00Z",
            },
            {
                "date": "2023-12-31",
                "system_episode_id": "p3",
                "system_start_time": "2023-12-31T00:00:00Z",
                "system_end_time": "2023-12-31T00:10:00Z",
            },
        ]
    )
    annotations = pd.DataFrame(
        [
            {
                "date": "2023-12-30",
                "manual_episode_id": "g1",
                "manual_start_time": "2023-12-30T00:00:00Z",
                "manual_end_time": "2023-12-30T00:10:00Z",
                "is_valid_excavation": True,
            },
            {
                "date": "2023-12-31",
                "manual_episode_id": "g2",
                "manual_start_time": "2023-12-31T00:00:00Z",
                "manual_end_time": "2023-12-31T00:04:00Z",
                "is_valid_excavation": True,
            },
            {
                "date": "2023-12-31",
                "manual_episode_id": "g3",
                "manual_start_time": "2023-12-31T00:04:30Z",
                "manual_end_time": "2023-12-31T00:10:00Z",
                "is_valid_excavation": True,
            },
        ]
    )

    result = evaluate_episode_predictions(predictions, annotations)

    assert result["metrics"]["over_segmentation_count"] == 1
    assert result["metrics"]["under_segmentation_count"] == 1
