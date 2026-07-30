from __future__ import annotations

from tbm_twin.evidence.models import ChainageDirection
from tbm_twin.geology.chainage import (
    ChainageValidationConfig,
    parse_chainage_interval,
    parse_chainage_value,
)


def test_parse_dk_chainage_value_to_meters() -> None:
    assert parse_chainage_value("DK123+456.7") == 123456.7


def test_reversed_chainage_preserves_raw_direction_and_normalizes() -> None:
    interval = parse_chainage_interval(
        {"start_chainage": "DK10+100", "end_chainage": "DK10+050"}, ""
    )

    assert interval is not None
    assert interval.direction == ChainageDirection.DECREASING
    assert interval.raw_start_chainage == 10100.0
    assert interval.raw_end_chainage == 10050.0
    assert interval.normalized_start_chainage == 10050.0
    assert interval.normalized_end_chainage == 10100.0


def test_parse_text_chainage_range_without_fabricating_direction() -> None:
    interval = parse_chainage_interval({}, "TSP forecast DK1+020 to DK1+060, fractured rock")

    assert interval is not None
    assert interval.direction == ChainageDirection.INCREASING
    assert interval.confidence.value == "DERIVED"


def test_implausible_chainage_interval_is_not_spatially_usable() -> None:
    interval = parse_chainage_interval(
        {"start_chainage": 104018.8, "end_chainage": 1014018.8},
        "",
        ChainageValidationConfig(maximum_reasonable_interval_m=5000.0),
    )

    assert interval is not None
    assert not interval.spatial_scope_usable
    assert "IMPLAUSIBLE_INTERVAL_LENGTH" in interval.validation_flags
    assert "CHAINAGE_SCALE_MISMATCH" in interval.validation_flags
    assert interval.raw_start_chainage == 104018.8
    assert interval.raw_end_chainage == 1014018.8
    assert (
        interval.suggested_normalization
        == "review_required_no_automatic_chainage_prefix_completion"
    )


def test_chainage_parse_conflict_preserves_raw_values() -> None:
    interval = parse_chainage_interval(
        {"start_chainage": "DK10+100", "end_chainage": "DK10+130"},
        "reported range DK10+200 to DK10+230",
    )

    assert interval is not None
    assert not interval.spatial_scope_usable
    assert "CHAINAGE_PARSE_CONFLICT" in interval.validation_flags
    assert interval.raw_start_chainage == 10100.0
    assert interval.normalized_start_chainage == 10100.0
