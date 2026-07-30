"""Models used by Stage 1 validation outputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ValidationErrorRecord(BaseModel):
    """Structured per-date validation error."""

    model_config = ConfigDict(frozen=True)

    error_type: str
    message: str


class ValidationDateResult(BaseModel):
    """Summary of one date validation run."""

    model_config = ConfigDict(frozen=True)

    date: str
    status: Literal["success", "warning", "failed"]
    input_path: Path | None
    output_dir: Path
    error: ValidationErrorRecord | None = None
    warnings: list[str]
    metrics: dict[str, Any]


@dataclass(frozen=True)
class ValidationConfig:
    """Centralized thresholds used by validation diagnostics."""

    small_reverse_tolerance_m: float = 0.01
    large_reverse_threshold_m: float = 0.5
    large_jump_threshold_m: float = 5.0
    support_conflict_tolerance_m: float = 2.0
    zero_advance_threshold_m: float = 0.01
    rapid_phase_flip_seconds: float = 60.0
    short_episode_seconds: float = 120.0
    implausible_advance_m: float = 100.0
    max_short_idle_seconds: float = 120.0
    minimum_iou_for_match: float = 0.5
    boundary_tolerance_seconds: float = 60.0
