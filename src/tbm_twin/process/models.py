"""Models for operation phases and excavation episodes."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator


class OperationPhase(StrEnum):
    """Transparent weak operation labels."""

    IDLE = "IDLE"
    STARTUP = "STARTUP"
    EXCAVATING = "EXCAVATING"
    COASTDOWN = "COASTDOWN"
    DATA_GAP = "DATA_GAP"
    UNKNOWN = "UNKNOWN"


class ValidExcavationSubphase(StrEnum):
    """Optional subphase for valid excavation."""

    TRANSIENT = "TRANSIENT"
    STEADY = "STEADY"
    VARIABLE = "VARIABLE"


class EpisodeBoundaryStatus(StrEnum):
    """Whether an episode boundary is censored by the source file."""

    COMPLETE = "COMPLETE"
    LEFT_CENSORED = "LEFT_CENSORED"
    RIGHT_CENSORED = "RIGHT_CENSORED"
    BOTH_CENSORED = "BOTH_CENSORED"


class PhaseLabel(BaseModel):
    """Weak label for one normalized PLC observation."""

    model_config = ConfigDict(frozen=True)

    observation_id: str
    timestamp: datetime
    phase: OperationPhase
    subphase: ValidExcavationSubphase | None
    reason_codes: list[str]
    method_version: str

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Require timezone-aware phase times."""

        if value.tzinfo is None:
            msg = "PhaseLabel timestamp must be timezone-aware."
            raise ValueError(msg)
        return value


class PhaseInterval(BaseModel):
    """A contiguous interval with one weak operation phase."""

    model_config = ConfigDict(frozen=True)

    phase: OperationPhase
    valid_start: datetime
    valid_end: datetime
    duration_seconds: float
    observation_refs: list[str]
    reason_codes: list[str]


class ExcavationEpisode(BaseModel):
    """A continuous valid excavation event."""

    model_config = ConfigDict(frozen=True)

    episode_id: str
    asset_ids: list[str]
    context_start: datetime
    context_end: datetime
    excavation_start: datetime
    excavation_end: datetime
    context_duration_seconds: float
    core_excavation_duration_seconds: float
    interruption_duration_seconds: float
    excavating_segment_count: int
    temporal_coverage_ratio: float
    boundary_status: EpisodeBoundaryStatus
    actual_start_known: bool
    actual_end_known: bool
    phase_sequence: list[PhaseInterval]
    observation_refs: list[str]
    core_observation_refs: list[str]
    cross_midnight_observed: bool
    quality_grade: str
    quality_reason_codes: list[str]
    quality_flags: list[str]
    method_version: str
