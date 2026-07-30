"""Manual review visualization for Stage 1 episode validation."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from tbm_twin.process.models import ExcavationEpisode, OperationPhase
from tbm_twin.validation.models import ValidationConfig

PHASE_COLORS = {
    OperationPhase.EXCAVATING.value: "#d8f3dc",
    OperationPhase.IDLE.value: "#f1f3f5",
    OperationPhase.STARTUP.value: "#fff3bf",
    OperationPhase.COASTDOWN.value: "#ffe8cc",
    OperationPhase.DATA_GAP.value: "#ffc9c9",
    OperationPhase.UNKNOWN.value: "#e7f5ff",
}


def write_episode_review_plot(
    *,
    date: str,
    labeled_frame: pd.DataFrame,
    episodes: list[ExcavationEpisode],
    output_path: Path,
    config: ValidationConfig,
) -> list[str]:
    """Write a single-date manual review plot, returning warnings on failure."""

    try:
        os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="tbm-mpl-"))
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        return [f"episode_review_plot_failed:{type(exc).__name__}:{exc}"]

    try:
        if output_path.exists() and output_path.is_dir():
            return [f"episode_review_plot_failed:IsADirectoryError:{output_path}"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        frame = labeled_frame.sort_values(["timestamp", "source_row_number"]).copy()
        times = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        chainage = pd.to_numeric(frame["shield_head_chainage"], errors="coerce")
        speed = pd.to_numeric(frame["advance_speed"], errors="coerce")
        thrust = pd.to_numeric(frame["total_thrust"], errors="coerce")

        fig, chainage_axis = plt.subplots(figsize=(14, 7))
        speed_axis = chainage_axis.twinx()
        chainage_axis.plot(
            times, chainage, color="#1f77b4", linewidth=1.2, label="shield_head_chainage"
        )
        speed_axis.plot(
            times, speed, color="#2ca02c", alpha=0.8, linewidth=1.0, label="advance_speed"
        )
        if thrust.notna().any():
            scaled_thrust = _minmax_scale(thrust)
            speed_axis.plot(
                times,
                scaled_thrust,
                color="#9467bd",
                alpha=0.55,
                linewidth=0.8,
                label="total_thrust min-max scaled",
            )

        for _, segment in frame.groupby(
            (frame["operation_phase"] != frame["operation_phase"].shift()).cumsum()
        ):
            phase = str(segment["operation_phase"].iloc[0])
            color = PHASE_COLORS.get(phase, "#ffffff")
            chainage_axis.axvspan(
                pd.Timestamp(segment["timestamp"].iloc[0]),
                pd.Timestamp(segment["timestamp"].iloc[-1]),
                color=color,
                alpha=0.25,
                linewidth=0,
            )

        for episode in episodes:
            axis_any: Any = chainage_axis
            axis_any.axvline(
                pd.Timestamp(episode.excavation_start).to_pydatetime(),
                color="#111111",
                linewidth=0.8,
                linestyle="--",
            )
            axis_any.axvline(
                pd.Timestamp(episode.excavation_end).to_pydatetime(),
                color="#111111",
                linewidth=0.8,
                linestyle=":",
            )

        chainage_diffs = chainage.diff()
        jump_times = times[chainage_diffs.abs() > config.large_jump_threshold_m]
        axis_any = chainage_axis
        for jump_time in jump_times:
            axis_any.axvline(
                pd.Timestamp(jump_time).to_pydatetime(),
                color="#d62728",
                linewidth=1.0,
                alpha=0.9,
            )

        data_gap_times = frame.loc[
            frame["operation_phase"].eq(OperationPhase.DATA_GAP.value), "timestamp"
        ]
        axis_any = chainage_axis
        for gap_time in data_gap_times:
            axis_any.axvline(
                pd.Timestamp(gap_time).to_pydatetime(),
                color="#ff0000",
                linewidth=1.2,
                alpha=0.5,
            )

        chainage_axis.set_title(
            f"{date} Stage 1 Episode Review: chainage, speed, phase bands, episode boundaries"
        )
        chainage_axis.set_xlabel("time (UTC)")
        chainage_axis.set_ylabel("shield_head_chainage")
        speed_axis.set_ylabel("advance_speed / optional min-max scaled thrust")
        lines_1, labels_1 = chainage_axis.get_legend_handles_labels()
        lines_2, labels_2 = speed_axis.get_legend_handles_labels()
        speed_axis.legend(lines_1 + lines_2, labels_1 + labels_2, loc="upper left")
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(output_path, dpi=150)
        plt.close(fig)
    except (OSError, ValueError, RuntimeError) as exc:
        return [f"episode_review_plot_failed:{type(exc).__name__}:{exc}"]
    return []


def _minmax_scale(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    min_value = numeric.min()
    max_value = numeric.max()
    if pd.isna(min_value) or pd.isna(max_value) or float(max_value - min_value) == 0.0:
        return numeric * 0.0
    return (numeric - min_value) / (max_value - min_value)
