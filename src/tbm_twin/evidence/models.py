"""Models for Stage 2 dynamic evidence and applicability."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvidenceType(StrEnum):
    """Evidence families represented in Stage 2."""

    RESPONSE = "RESPONSE"
    GEOLOGICAL_FORECAST = "GEOLOGICAL_FORECAST"
    GEOLOGICAL_OBSERVATION = "GEOLOGICAL_OBSERVATION"
    GEOLOGICAL_BACKGROUND = "GEOLOGICAL_BACKGROUND"
    GEOLOGICAL_UNKNOWN = "GEOLOGICAL_UNKNOWN"


class EvidenceQualityGrade(StrEnum):
    """Evidence-local quality grade."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"


class TimeInterval(BaseModel):
    """Timezone-aware time interval."""

    model_config = ConfigDict(frozen=True)

    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Require timezone-aware times."""

        if value.tzinfo is None:
            msg = "TimeInterval values must be timezone-aware."
            raise ValueError(msg)
        return value


class SpatialScope(BaseModel):
    """Generic spatial scope used by base evidence."""

    model_config = ConfigDict(frozen=True)

    start_chainage: float | None
    end_chainage: float | None
    basis: str


class EvidenceBase(BaseModel):
    """Stable base model for evidence records."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    evidence_type: EvidenceType
    source_asset_ids: list[str]
    valid_time: TimeInterval | None
    available_time: datetime | None
    ingested_time: datetime
    spatial_scope: SpatialScope | None
    quality_grade: EvidenceQualityGrade
    quality_flags: list[str]
    method_version: str
    provenance_refs: list[str]

    @field_validator("available_time", "ingested_time")
    @classmethod
    def require_optional_timezone(cls, value: datetime | None) -> datetime | None:
        """Require timezone-aware evidence times when present."""

        if value is not None and value.tzinfo is None:
            msg = "Evidence datetimes must be timezone-aware."
            raise ValueError(msg)
        return value


class ResponsePhaseScope(StrEnum):
    """Phase scope for response evidence."""

    CORE_EXCAVATION = "CORE_EXCAVATION"
    STARTUP = "STARTUP"
    STEADY = "STEADY"
    VARIABLE = "VARIABLE"
    FULL_CONTEXT = "FULL_CONTEXT"


class StatisticType(StrEnum):
    """Response statistic type."""

    COUNT = "count"
    VALID_COUNT = "valid_count"
    MISSING_RATE = "missing_rate"
    MEAN = "mean"
    MEDIAN = "median"
    STANDARD_DEVIATION = "standard_deviation"
    P10 = "p10"
    P90 = "p90"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    COEFFICIENT_OF_VARIATION = "coefficient_of_variation"


class UnitConfidence(StrEnum):
    """Confidence in a statistic's physical unit."""

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class DeviationDirection(StrEnum):
    """Direction relative to a transparent baseline."""

    ABOVE_BASELINE = "ABOVE_BASELINE"
    BELOW_BASELINE = "BELOW_BASELINE"
    NEAR_BASELINE = "NEAR_BASELINE"
    UNDETERMINED = "UNDETERMINED"


class BaselineMethod(StrEnum):
    """Supported response baseline methods."""

    NO_BASELINE = "NO_BASELINE"
    GLOBAL_ROBUST_BASELINE = "GLOBAL_ROBUST_BASELINE"


class ResponseBaseline(BaseModel):
    """Transparent robust baseline for one feature."""

    model_config = ConfigDict(frozen=True)

    baseline_id: str
    baseline_method: BaselineMethod
    baseline_data_scope: str
    baseline_created_at: datetime
    baseline_feature: str
    baseline_median: float | None
    baseline_mad: float | None
    sample_count: int


class ResponseStatistics(BaseModel):
    """Complete response statistics for one episode-channel pair."""

    model_config = ConfigDict(frozen=True)

    sample_count: int
    valid_count: int
    missing_rate: float
    mean: float | None
    median: float | None
    standard_deviation: float | None
    p10: float | None
    p90: float | None
    minimum: float | None
    maximum: float | None
    coefficient_of_variation: float | None


class BaselineReference(BaseModel):
    """Baseline reference embedded in one response evidence record."""

    model_config = ConfigDict(frozen=True)

    baseline_id: str
    baseline_method: BaselineMethod
    baseline_data_scope: str
    baseline_value: float | None
    sample_count: int


class DeviationAssessment(BaseModel):
    """Deviation assessment for the primary response statistic."""

    model_config = ConfigDict(frozen=True)

    statistic: str
    deviation_value: float | None
    deviation_direction: DeviationDirection
    deviation_strength: str | None


class EvidenceQualityComponents(BaseModel):
    """Separated quality components for Stage 2.1 evidence."""

    model_config = ConfigDict(frozen=True)

    measurement_quality: EvidenceQualityGrade
    temporal_scope_quality: EvidenceQualityGrade
    spatial_scope_quality: EvidenceQualityGrade
    measurement_reason_codes: list[str]
    temporal_scope_reason_codes: list[str]
    spatial_scope_reason_codes: list[str]


class ResponseEvidence(EvidenceBase):
    """PLC response statistics over one PLC-inferred episode and one channel."""

    episode_id: str
    phase_scope: ResponsePhaseScope
    channel_name: str
    unit: str | None
    unit_confidence: UnitConfidence
    statistics: ResponseStatistics
    baseline: BaselineReference | None
    deviation: DeviationAssessment | None
    temporal_coverage_ratio: float
    quality_components: EvidenceQualityComponents
    core_observation_refs: list[str]


class TemporalValueConfidence(StrEnum):
    """Confidence in a geological time value."""

    VERIFIED = "VERIFIED"
    DERIVED = "DERIVED"
    ASSUMED = "ASSUMED"
    UNKNOWN = "UNKNOWN"


class TemporalRole(StrEnum):
    """Semantic role of a document temporal candidate."""

    OBSERVED = "OBSERVED"
    DOCUMENTED = "DOCUMENTED"
    ISSUED = "ISSUED"
    SUBMITTED = "SUBMITTED"
    AVAILABLE = "AVAILABLE"
    FILENAME_DATE = "FILENAME_DATE"
    LEGACY_REPORT_DATE = "LEGACY_REPORT_DATE"
    LEGACY_ISSUE_DATE = "LEGACY_ISSUE_DATE"
    IRRELEVANT = "IRRELEVANT"


class TemporalPrecision(StrEnum):
    """Precision of a temporal value or extent."""

    SECOND = "SECOND"
    MINUTE = "MINUTE"
    HOUR = "HOUR"
    DAY = "DAY"
    UNKNOWN = "UNKNOWN"


class TemporalConfidence(StrEnum):
    """Confidence attached to document temporal extraction."""

    VERIFIED = "VERIFIED"
    DERIVED = "DERIVED"
    ASSUMED = "ASSUMED"
    UNKNOWN = "UNKNOWN"


class TemporalValue(BaseModel):
    """A temporal value with confidence and basis."""

    model_config = ConfigDict(frozen=True)

    value: datetime | None
    confidence: TemporalValueConfidence
    basis: str


class TemporalExtent(BaseModel):
    """Temporal extent for imprecise document dates."""

    model_config = ConfigDict(frozen=True)

    earliest_possible_time: datetime
    latest_possible_time: datetime
    precision: TemporalPrecision
    source_timezone: str
    timezone_confidence: TemporalConfidence
    timezone_basis: str
    value_confidence: TemporalConfidence
    basis: str
    candidate_ids: list[str]

    @field_validator("earliest_possible_time", "latest_possible_time")
    @classmethod
    def require_extent_timezone(cls, value: datetime) -> datetime:
        """Require timezone-aware extent bounds."""

        if value.tzinfo is None:
            msg = "TemporalExtent bounds must be timezone-aware."
            raise ValueError(msg)
        return value


class TemporalCandidate(BaseModel):
    """Candidate date/time expression extracted from one PDF page."""

    model_config = ConfigDict(frozen=True)

    candidate_id: str
    semantic_role: TemporalRole
    raw_expression: str
    parsed_value: datetime | None
    source_local_date: date | None = None
    precision: TemporalPrecision
    source_type: str
    source_page: int | None
    source_context: str
    extraction_rule: str
    confidence: TemporalConfidence
    basis: str


class ChainageDirection(StrEnum):
    """Direction semantics of a chainage interval."""

    INCREASING = "INCREASING"
    DECREASING = "DECREASING"
    POINT = "POINT"
    UNKNOWN = "UNKNOWN"


class SpatialValueConfidence(StrEnum):
    """Confidence in a geological spatial value."""

    VERIFIED = "VERIFIED"
    DERIVED = "DERIVED"
    ASSUMED = "ASSUMED"
    UNKNOWN = "UNKNOWN"


class ChainageInterval(BaseModel):
    """Geological chainage interval with raw and normalized values."""

    model_config = ConfigDict(frozen=True)

    start_chainage: float | None
    end_chainage: float | None
    direction: ChainageDirection
    confidence: SpatialValueConfidence
    basis: str
    raw_start_chainage: float | None
    raw_end_chainage: float | None
    normalized_start_chainage: float | None
    normalized_end_chainage: float | None
    normalization_reason: str | None
    spatial_scope_usable: bool = True
    validation_flags: list[str] = Field(default_factory=list)
    suggested_normalization: str | None = None


class GeologicalEpistemicStatus(StrEnum):
    """Epistemic status at evidence production time."""

    FORECAST = "FORECAST"
    OBSERVED = "OBSERVED"
    BACKGROUND = "BACKGROUND"
    UNKNOWN = "UNKNOWN"


class GeologicalSourceType(StrEnum):
    """Supported geological source types."""

    TSP_REPORT = "TSP_REPORT"
    HSP_REPORT = "HSP_REPORT"
    SONIC_FORECAST = "SONIC_FORECAST"
    FIELD_OBSERVATION = "FIELD_OBSERVATION"
    FACE_SKETCH = "FACE_SKETCH"
    EXCAVATED_FACE_RECORD = "EXCAVATED_FACE_RECORD"
    DESIGN_GEOLOGY = "DESIGN_GEOLOGY"
    REGIONAL_GEOLOGY = "REGIONAL_GEOLOGY"
    DESIGN_BACKGROUND = "DESIGN_BACKGROUND"
    OTHER = "OTHER"


class GeologicalEvidence(EvidenceBase):
    """Rule-normalized geological evidence without LLM-derived facts."""

    document_id: str | None = None
    source_asset_id: str | None = None
    source_pdf_path: str | None = None
    geological_source_type: GeologicalSourceType
    source_level: str | None = None
    epistemic_status: GeologicalEpistemicStatus
    title: str | None
    raw_text: str
    normalized_text: str
    observed_time: TemporalValue | None
    issued_time: TemporalValue | None
    available_time_value: TemporalValue | None
    observed_time_extent: TemporalExtent | None = None
    document_time_extent: TemporalExtent | None = None
    issued_time_extent: TemporalExtent | None = None
    submitted_time_extent: TemporalExtent | None = None
    available_time_extent: TemporalExtent | None = None
    chainage_interval: ChainageInterval | None
    face_chainage: float | None = None
    structured_attributes: dict[str, str | int | float | bool | None]
    source_record_id: str | None
    source_page_refs: list[int] = Field(default_factory=list)
    source_text_refs: list[str] = Field(default_factory=list)
    source_type_raw: str | None = None
    epistemic_status_raw: str | None = None
    epistemic_status_before_mapping: GeologicalEpistemicStatus = GeologicalEpistemicStatus.UNKNOWN
    epistemic_mapping_basis: str = "UNKNOWN"
    parse_warnings: list[str]


class ApplicabilityTargetType(StrEnum):
    """Target type for applicability."""

    EPISODE = "EPISODE"
    SPATIAL_FOOTPRINT = "SPATIAL_FOOTPRINT"


class TemporalApplicabilityStatus(StrEnum):
    """Temporal availability status."""

    AVAILABLE = "AVAILABLE"
    NOT_YET_AVAILABLE = "NOT_YET_AVAILABLE"
    UNKNOWN_WITHIN_PRECISION = "UNKNOWN_WITHIN_PRECISION"
    AVAILABLE_TIME_UNKNOWN = "AVAILABLE_TIME_UNKNOWN"
    INVALID_TEMPORAL_METADATA = "INVALID_TEMPORAL_METADATA"


class SpatialApplicabilityStatus(StrEnum):
    """Spatial relation status."""

    OVERLAP = "OVERLAP"
    ADJACENT = "ADJACENT"
    AHEAD = "AHEAD"
    BEHIND = "BEHIND"
    DISJOINT = "DISJOINT"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class EpistemicApplicabilityStatus(StrEnum):
    """Epistemic compatibility status."""

    EPISTEMICALLY_COMPATIBLE = "EPISTEMICALLY_COMPATIBLE"
    COMPATIBLE_WITH_QUALIFICATION = "COMPATIBLE_WITH_QUALIFICATION"
    EPISTEMICALLY_INCOMPATIBLE = "EPISTEMICALLY_INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"


class QualityApplicabilityStatus(StrEnum):
    """Evidence and target quality status."""

    ACCEPTABLE = "ACCEPTABLE"
    QUALIFIED = "QUALIFIED"
    LOW_QUALITY = "LOW_QUALITY"


class ApplicabilityResult(StrEnum):
    """Non-boolean applicability result."""

    APPLICABLE = "APPLICABLE"
    APPLICABLE_WITH_QUALIFICATION = "APPLICABLE_WITH_QUALIFICATION"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNDETERMINED = "UNDETERMINED"


class EvidenceApplicabilityAssignment(BaseModel):
    """Applicability of one evidence record to one target at evaluation time."""

    model_config = ConfigDict(frozen=True)

    assignment_id: str
    evidence_id: str
    evidence_type: EvidenceType
    evidence_epistemic_status: str | None
    target_id: str
    target_type: ApplicabilityTargetType
    evaluation_time: datetime
    temporal_status: TemporalApplicabilityStatus
    spatial_status: SpatialApplicabilityStatus
    epistemic_status: EpistemicApplicabilityStatus
    quality_status: QualityApplicabilityStatus
    result: ApplicabilityResult
    dominant_reason_code: str
    reason_codes: list[str]
    method_version: str
