from __future__ import annotations

from tbm_twin.evidence.models import TemporalValueConfidence
from tbm_twin.geology.time_semantics import parse_temporal_value


def test_naive_geology_time_is_localized_to_source_timezone_then_utc() -> None:
    value = parse_temporal_value("2026-01-01 08:30:00")

    assert value.value is not None
    assert value.value.isoformat() == "2026-01-01T00:30:00+00:00"
    assert value.confidence == TemporalValueConfidence.DERIVED


def test_missing_geology_time_remains_unknown_not_ingested_time() -> None:
    value = parse_temporal_value("")

    assert value.value is None
    assert value.confidence == TemporalValueConfidence.UNKNOWN
    assert value.basis == "UNKNOWN"
