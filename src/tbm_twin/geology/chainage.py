"""Chainage parsing for geological evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from tbm_twin.evidence.models import ChainageDirection, ChainageInterval, SpatialValueConfidence

CHAINAGE_PATTERN = re.compile(r"(?:DK|K)?\s*(\d+)\s*\+\s*(\d+(?:\.\d+)?)", re.IGNORECASE)


@dataclass(frozen=True)
class ChainageValidationConfig:
    """Validation thresholds for geological chainage intervals."""

    maximum_reasonable_interval_m: float = 5000.0
    scale_ratio_threshold: float = 5.0
    prefix_consistency_check: bool = True


def parse_chainage_value(value: object) -> float | None:
    """Parse numeric or DK/K formatted chainage into meters."""

    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    try:
        return float(text)
    except ValueError:
        pass
    match = CHAINAGE_PATTERN.search(text)
    if not match:
        return None
    return float(match.group(1)) * 1000.0 + float(match.group(2))


def parse_chainage_interval(
    record: dict[str, Any],
    text: str,
    config: ChainageValidationConfig | None = None,
) -> ChainageInterval | None:
    """Parse explicit or textual chainage interval while preserving raw direction."""

    config = config or ChainageValidationConfig()
    raw_start = parse_chainage_value(record.get("start_chainage"))
    raw_end = parse_chainage_value(record.get("end_chainage"))
    normalized_start: float | None
    normalized_end: float | None
    basis = "explicit_fields"
    confidence = SpatialValueConfidence.VERIFIED
    if raw_start is None or raw_end is None:
        matches = [float(km) * 1000.0 + float(m) for km, m in CHAINAGE_PATTERN.findall(text)]
        if len(matches) >= 2:
            raw_start, raw_end = matches[0], matches[1]
            basis = "text_regex_range"
            confidence = SpatialValueConfidence.DERIVED
        elif len(matches) == 1:
            raw_start = raw_end = matches[0]
            basis = "text_regex_point"
            confidence = SpatialValueConfidence.DERIVED
    if raw_start is None and raw_end is None:
        return None
    validation_flags = _validation_flags(raw_start, raw_end, record, text, config)
    if raw_start is not None and raw_end is not None and raw_start > raw_end:
        direction = ChainageDirection.DECREASING
        normalized_start, normalized_end = raw_end, raw_start
        reason = "raw_start_greater_than_raw_end_preserved_and_normalized"
    elif raw_start == raw_end:
        direction = ChainageDirection.POINT
        normalized_start, normalized_end = raw_start, raw_end
        reason = None
    else:
        direction = ChainageDirection.INCREASING
        normalized_start, normalized_end = raw_start, raw_end
        reason = None
    spatial_scope_usable = not validation_flags
    return ChainageInterval(
        start_chainage=raw_start,
        end_chainage=raw_end,
        direction=direction,
        confidence=confidence,
        basis=basis,
        raw_start_chainage=raw_start,
        raw_end_chainage=raw_end,
        normalized_start_chainage=normalized_start,
        normalized_end_chainage=normalized_end,
        normalization_reason=reason,
        spatial_scope_usable=spatial_scope_usable,
        validation_flags=validation_flags,
        suggested_normalization=_suggested_normalization(validation_flags),
    )


def _validation_flags(
    raw_start: float | None,
    raw_end: float | None,
    record: dict[str, Any],
    text: str,
    config: ChainageValidationConfig,
) -> list[str]:
    flags: set[str] = set()
    if raw_start is None or raw_end is None:
        return []
    interval_length = abs(raw_end - raw_start)
    if interval_length > config.maximum_reasonable_interval_m:
        flags.add("IMPLAUSIBLE_INTERVAL_LENGTH")
    minimum = min(abs(raw_start), abs(raw_end))
    maximum = max(abs(raw_start), abs(raw_end))
    if minimum > 0 and maximum / minimum >= config.scale_ratio_threshold:
        flags.add("CHAINAGE_SCALE_MISMATCH")
    if raw_start > raw_end:
        flags.add("CHAINAGE_DIRECTION_CONFLICT")
    if config.prefix_consistency_check and _prefix_mismatch(record, text):
        flags.add("CHAINAGE_PREFIX_MISMATCH")
    if _explicit_text_conflict(record, text):
        flags.add("CHAINAGE_PARSE_CONFLICT")
    return sorted(flags)


def _prefix_mismatch(record: dict[str, Any], text: str) -> bool:
    raw_tokens = [str(record.get(key, "")).strip() for key in ["start_chainage", "end_chainage"]]
    digit_lengths = [
        len(token.split(".")[0])
        for token in raw_tokens
        if token and token.replace(".", "").isdigit()
    ]
    if len(digit_lengths) == 2 and abs(digit_lengths[0] - digit_lengths[1]) >= 2:
        return True
    matches = CHAINAGE_PATTERN.findall(text)
    km_prefixes = [match[0] for match in matches]
    if len(km_prefixes) < 2 or len(set(km_prefixes[:2])) <= 1:
        return False
    values = [float(km) * 1000.0 + float(m) for km, m in matches[:2]]
    return not _valid_adjacent_km_boundary_crossing(km_prefixes[:2], values, text)


def _valid_adjacent_km_boundary_crossing(
    prefixes: list[str],
    values: list[float],
    text: str,
) -> bool:
    try:
        start_km = int(prefixes[0])
        end_km = int(prefixes[1])
    except ValueError:
        return False
    if abs(end_km - start_km) != 1:
        return False
    if values[1] <= values[0]:
        return False
    length = values[1] - values[0]
    stated_length = _stated_interval_length(text)
    if stated_length is not None:
        return abs(stated_length - length) <= 1.0
    return length <= 1000.0


def _stated_interval_length(text: str) -> float | None:
    match = re.search(
        r"[\uff08(]\s*(\d+(?:\.\d+)?)\s*m\s*[\uff09)]",
        text,
        flags=re.IGNORECASE,
    )
    return float(match.group(1)) if match else None


def _explicit_text_conflict(record: dict[str, Any], text: str) -> bool:
    explicit_start = parse_chainage_value(record.get("start_chainage"))
    explicit_end = parse_chainage_value(record.get("end_chainage"))
    matches = [float(km) * 1000.0 + float(m) for km, m in CHAINAGE_PATTERN.findall(text)]
    if explicit_start is None or explicit_end is None or len(matches) < 2:
        return False
    return abs(explicit_start - matches[0]) > 1.0 or abs(explicit_end - matches[1]) > 1.0


def _suggested_normalization(flags: list[str]) -> str | None:
    if not flags:
        return None
    return "review_required_no_automatic_chainage_prefix_completion"
