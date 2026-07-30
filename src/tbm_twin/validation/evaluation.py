"""Episode-level evaluation against manual annotations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd


@dataclass(frozen=True)
class EpisodeEvaluationConfig:
    """Configuration for episode interval matching."""

    minimum_iou_for_match: float = 0.5
    boundary_tolerance_seconds: float = 60.0


def evaluate_episode_predictions(
    predictions: pd.DataFrame,
    annotations: pd.DataFrame,
    config: EpisodeEvaluationConfig | None = None,
) -> dict[str, Any]:
    """Evaluate predicted episodes with one-to-one temporal IoU matching."""

    config = config or EpisodeEvaluationConfig()
    pred = _prepare_intervals(
        predictions,
        id_col="system_episode_id",
        start_col="system_start_time",
        end_col="system_end_time",
    )
    gold = _prepare_intervals(
        annotations[_valid_excavation_mask(annotations)].copy(),
        id_col="manual_episode_id",
        start_col="manual_start_time",
        end_col="manual_end_time",
    )
    matches = _match_intervals(pred, gold, config.minimum_iou_for_match)
    matched_pred = {match["prediction_id"] for match in matches}
    matched_gold = {match["annotation_id"] for match in matches}
    false_positive = pred[~pred["interval_id"].isin(matched_pred)].copy()
    missed = gold[~gold["interval_id"].isin(matched_gold)].copy()
    start_errors = [abs(float(match["start_error_seconds"])) for match in matches]
    end_errors = [abs(float(match["end_error_seconds"])) for match in matches]
    duration_errors = [abs(float(match["duration_error_seconds"])) for match in matches]

    precision = len(matches) / len(pred) if len(pred) else 0.0
    recall = len(matches) / len(gold) if len(gold) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    return {
        "metrics": {
            "episode_precision": precision,
            "episode_recall": recall,
            "episode_f1": f1,
            "mean_start_boundary_error_seconds": _mean(start_errors),
            "median_start_boundary_error_seconds": _median(start_errors),
            "mean_end_boundary_error_seconds": _mean(end_errors),
            "median_end_boundary_error_seconds": _median(end_errors),
            "mean_duration_error_seconds": _mean(duration_errors),
            "over_segmentation_count": _over_segmentation_count(pred, gold),
            "under_segmentation_count": _under_segmentation_count(pred, gold),
            "false_positive_count": len(false_positive),
            "missed_episode_count": len(missed),
            "matched_episode_count": len(matches),
        },
        "matches": matches,
        "false_positive_episodes": false_positive,
        "missed_episodes": missed,
        "boundary_error_cases": _boundary_error_cases(matches, config.boundary_tolerance_seconds),
        "possible_over_segmentation": _possible_over_segmentation(pred, gold),
        "possible_under_segmentation": _possible_under_segmentation(pred, gold),
    }


def write_episode_evaluation_outputs(result: dict[str, Any], output_dir: Path) -> None:
    """Write episode evaluation metrics and error-case CSVs."""

    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([result["metrics"]]).to_csv(output_dir / "metrics.csv", index=False)
    pd.DataFrame(result["matches"]).to_csv(output_dir / "matches.csv", index=False)
    for key in [
        "false_positive_episodes",
        "missed_episodes",
        "boundary_error_cases",
        "possible_over_segmentation",
        "possible_under_segmentation",
    ]:
        value = result[key]
        frame = value if isinstance(value, pd.DataFrame) else pd.DataFrame(value)
        frame.to_csv(output_dir / f"{key}.csv", index=False)


def _prepare_intervals(
    frame: pd.DataFrame,
    *,
    id_col: str,
    start_col: str,
    end_col: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["interval_id", "date", "start", "end", "duration_seconds"])
    out = frame.copy()
    out["interval_id"] = out[id_col].astype(str)
    out["start"] = pd.to_datetime(out[start_col], utc=True, errors="coerce")
    out["end"] = pd.to_datetime(out[end_col], utc=True, errors="coerce")
    out = out.dropna(subset=["start", "end"])
    out = out[out["end"] >= out["start"]].copy()
    out["duration_seconds"] = (out["end"] - out["start"]).dt.total_seconds()
    if "date" not in out.columns:
        out["date"] = ""
    return out[["interval_id", "date", "start", "end", "duration_seconds"]]


def _valid_excavation_mask(frame: pd.DataFrame) -> pd.Series:
    if "is_valid_excavation" not in frame.columns:
        return pd.Series(True, index=frame.index)
    values = frame["is_valid_excavation"]
    if values.dtype == bool:
        return values
    normalized = values.astype(str).str.strip().str.lower()
    return normalized.isin({"true", "1", "yes", "y", "是"})


def _match_intervals(
    predictions: pd.DataFrame,
    annotations: pd.DataFrame,
    minimum_iou: float,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for pred in predictions.itertuples(index=False):
        for gold in annotations.itertuples(index=False):
            if pred.date and gold.date and pred.date != gold.date:
                continue
            iou = _interval_iou(pred.start, pred.end, gold.start, gold.end)
            if iou >= minimum_iou:
                candidates.append(
                    {
                        "prediction_id": pred.interval_id,
                        "annotation_id": gold.interval_id,
                        "date": pred.date or gold.date,
                        "iou": iou,
                        "start_error_seconds": (pred.start - gold.start).total_seconds(),
                        "end_error_seconds": (pred.end - gold.end).total_seconds(),
                        "duration_error_seconds": pred.duration_seconds - gold.duration_seconds,
                    }
                )
    candidates.sort(key=lambda item: float(item["iou"]), reverse=True)
    used_pred: set[str] = set()
    used_gold: set[str] = set()
    matches: list[dict[str, Any]] = []
    for candidate in candidates:
        pred_id = str(candidate["prediction_id"])
        gold_id = str(candidate["annotation_id"])
        if pred_id in used_pred or gold_id in used_gold:
            continue
        used_pred.add(pred_id)
        used_gold.add(gold_id)
        matches.append(candidate)
    return matches


def _interval_iou(
    pred_start: pd.Timestamp,
    pred_end: pd.Timestamp,
    gold_start: pd.Timestamp,
    gold_end: pd.Timestamp,
) -> float:
    intersection = max((min(pred_end, gold_end) - max(pred_start, gold_start)).total_seconds(), 0.0)
    union = max((max(pred_end, gold_end) - min(pred_start, gold_start)).total_seconds(), 0.0)
    return intersection / union if union > 0 else 0.0


def _over_segmentation_count(pred: pd.DataFrame, gold: pd.DataFrame) -> int:
    return len(_possible_over_segmentation(pred, gold))


def _under_segmentation_count(pred: pd.DataFrame, gold: pd.DataFrame) -> int:
    return len(_possible_under_segmentation(pred, gold))


def _possible_over_segmentation(pred: pd.DataFrame, gold: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for annotation in gold.itertuples(index=False):
        overlapping = [
            prediction.interval_id
            for prediction in pred.itertuples(index=False)
            if prediction.date == annotation.date
            and _overlap_seconds(prediction.start, prediction.end, annotation.start, annotation.end)
            > 0
        ]
        if len(overlapping) > 1:
            rows.append(
                {
                    "date": annotation.date,
                    "annotation_id": annotation.interval_id,
                    "overlapping_prediction_ids": ";".join(overlapping),
                    "count": len(overlapping),
                }
            )
    return pd.DataFrame(rows)


def _possible_under_segmentation(pred: pd.DataFrame, gold: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for prediction in pred.itertuples(index=False):
        overlapping = [
            annotation.interval_id
            for annotation in gold.itertuples(index=False)
            if prediction.date == annotation.date
            and _overlap_seconds(prediction.start, prediction.end, annotation.start, annotation.end)
            > 0
        ]
        if len(overlapping) > 1:
            rows.append(
                {
                    "date": prediction.date,
                    "prediction_id": prediction.interval_id,
                    "overlapping_annotation_ids": ";".join(overlapping),
                    "count": len(overlapping),
                }
            )
    return pd.DataFrame(rows)


def _boundary_error_cases(matches: list[dict[str, Any]], tolerance_seconds: float) -> pd.DataFrame:
    return pd.DataFrame(
        [
            match
            for match in matches
            if abs(float(match["start_error_seconds"])) > tolerance_seconds
            or abs(float(match["end_error_seconds"])) > tolerance_seconds
        ]
    )


def _overlap_seconds(
    first_start: pd.Timestamp,
    first_end: pd.Timestamp,
    second_start: pd.Timestamp,
    second_end: pd.Timestamp,
) -> float:
    return cast(
        float,
        max((min(first_end, second_end) - max(first_start, second_start)).total_seconds(), 0.0),
    )


def _mean(values: list[float]) -> float | None:
    return float(pd.Series(values).mean()) if values else None


def _median(values: list[float]) -> float | None:
    return float(pd.Series(values).median()) if values else None
