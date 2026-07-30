"""Channel catalog models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ChannelUsageLevel(StrEnum):
    """How a canonical PLC channel may be used."""

    PRIMARY = "PRIMARY"
    SUPPORTING = "SUPPORTING"
    DIAGNOSTIC = "DIAGNOSTIC"
    DISABLED = "DISABLED"


class TimezoneConfidence(StrEnum):
    """Confidence in source timezone semantics."""

    VERIFIED = "VERIFIED"
    ASSUMED = "ASSUMED"
    UNKNOWN = "UNKNOWN"


class TimezoneBasis(StrEnum):
    """Basis for timezone semantics."""

    PROJECT_DOCUMENTATION = "PROJECT_DOCUMENTATION"
    DATA_PROVIDER_CONFIRMATION = "DATA_PROVIDER_CONFIRMATION"
    FILE_METADATA = "FILE_METADATA"
    LEGACY_CONFIGURATION = "LEGACY_CONFIGURATION"
    PROJECT_LOCATION_ASSUMPTION = "PROJECT_LOCATION_ASSUMPTION"
    USER_CONFIGURATION = "USER_CONFIGURATION"
    UNKNOWN = "UNKNOWN"


class ChannelDefinition(BaseModel):
    """Definition of a canonical PLC channel."""

    model_config = ConfigDict(frozen=True)

    canonical_name: str
    aliases: list[str]
    physical_quantity: str | None
    unit: str | None
    unit_verified: bool
    usage_level: ChannelUsageLevel
    required: bool
    valid_min: float | None
    valid_max: float | None
    description: str


class TimezoneDefinition(BaseModel):
    """Timezone policy for PLC timestamp normalization."""

    model_config = ConfigDict(frozen=True)

    source_timezone: str | None = None
    canonical_timezone: str = "UTC"
    timezone_confidence: TimezoneConfidence = TimezoneConfidence.UNKNOWN
    timezone_basis: TimezoneBasis = TimezoneBasis.UNKNOWN
