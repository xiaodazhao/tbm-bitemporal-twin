"""ResponseEvidence construction policy for Stage 2E."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from tbm_twin.evidence.models import BaselineMethod, ResponseEvidence
from tbm_twin.evidence.response_builder import ResponseEvidenceConfig, build_response_evidence
from tbm_twin.process.models import ExcavationEpisode
from tbm_twin.trajectory.models import SpatialFootprint


def build_no_baseline_response_evidence(
    normalized_frame: pd.DataFrame,
    episodes: list[ExcavationEpisode],
    footprints: list[SpatialFootprint],
    *,
    config: ResponseEvidenceConfig,
    reconstruction_time: datetime,
) -> list[ResponseEvidence]:
    """Build response evidence with no baseline and no deviation assessment."""

    return build_response_evidence(
        normalized_frame,
        episodes,
        footprints,
        config=config,
        baseline_mode=BaselineMethod.NO_BASELINE,
        reconstruction_time=reconstruction_time,
    )
