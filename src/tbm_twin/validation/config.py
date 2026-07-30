"""Load centralized validation and episode-detection configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tbm_twin.process.episode_builder import EpisodeBuilderConfig
from tbm_twin.process.weak_labels import PhaseRuleConfig
from tbm_twin.trajectory.footprint_builder import FootprintBuilderConfig
from tbm_twin.validation.models import ValidationConfig


def load_detection_config(path: Path = Path("configs/episode_detection.yaml")) -> dict[str, Any]:
    """Load episode detection configuration from YAML."""

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return dict(data or {})


def load_phase_rule_config(path: Path = Path("configs/episode_detection.yaml")) -> PhaseRuleConfig:
    """Load PhaseRuleConfig from centralized YAML."""

    data = load_detection_config(path).get("phase_rules", {})
    return PhaseRuleConfig(**data)


def load_episode_builder_config(
    path: Path = Path("configs/episode_detection.yaml"),
) -> EpisodeBuilderConfig:
    """Load EpisodeBuilderConfig from centralized YAML."""

    data = load_detection_config(path).get("episode_builder", {})
    return EpisodeBuilderConfig(**data)


def load_validation_config(path: Path = Path("configs/episode_detection.yaml")) -> ValidationConfig:
    """Load validation thresholds from centralized YAML."""

    data = load_detection_config(path)
    diagnostics = dict(data.get("diagnostics", {}))
    episode_builder = dict(data.get("episode_builder", {}))
    evaluation = dict(data.get("episode_evaluation", {}))
    return ValidationConfig(
        **diagnostics,
        max_short_idle_seconds=float(
            episode_builder.get("max_short_idle_seconds", ValidationConfig.max_short_idle_seconds)
        ),
        minimum_iou_for_match=float(
            evaluation.get("minimum_iou_for_match", ValidationConfig.minimum_iou_for_match)
        ),
        boundary_tolerance_seconds=float(
            evaluation.get(
                "boundary_tolerance_seconds",
                ValidationConfig.boundary_tolerance_seconds,
            )
        ),
    )


def load_footprint_builder_config(
    path: Path = Path("configs/episode_detection.yaml"),
) -> FootprintBuilderConfig:
    """Load FootprintBuilderConfig from centralized YAML."""

    diagnostics = dict(load_detection_config(path).get("diagnostics", {}))
    return FootprintBuilderConfig(
        support_conflict_tolerance_m=float(
            diagnostics.get(
                "support_conflict_tolerance_m",
                FootprintBuilderConfig.support_conflict_tolerance_m,
            )
        ),
        zero_advance_threshold_m=float(
            diagnostics.get(
                "zero_advance_threshold_m",
                FootprintBuilderConfig.zero_advance_threshold_m,
            )
        ),
    )
