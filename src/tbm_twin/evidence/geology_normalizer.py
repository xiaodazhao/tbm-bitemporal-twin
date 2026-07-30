"""Normalize geological evidence with rules and explicit field mappings."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tbm_twin.assets.models import SourceType
from tbm_twin.assets.registry import register_source_asset
from tbm_twin.evidence.models import (
    ChainageInterval,
    EvidenceType,
    GeologicalEpistemicStatus,
    GeologicalEvidence,
    GeologicalSourceType,
    SpatialScope,
    TemporalValue,
    TemporalValueConfidence,
)
from tbm_twin.evidence.quality import grade_from_reason_codes
from tbm_twin.geology.chainage import ChainageValidationConfig, parse_chainage_interval
from tbm_twin.geology.readers import read_geology_records
from tbm_twin.geology.schema_mapping import first_present
from tbm_twin.geology.time_semantics import parse_temporal_value

GEOLOGY_METHOD_VERSION = "geological_evidence_normalization_v1"


def load_geology_config(path: Path = Path("configs/geology_sources.yaml")) -> dict[str, Any]:
    """Load geology normalization configuration."""

    with path.open("r", encoding="utf-8") as handle:
        return dict(yaml.safe_load(handle) or {})


def normalize_geological_evidence(input_path: Path) -> list[GeologicalEvidence]:
    """Normalize geological evidence records from CSV or JSON."""

    config = load_geology_config()
    aliases = dict(config.get("field_aliases", {}))
    chainage_config = _chainage_config(config)
    records = read_geology_records(input_path)
    source_asset = register_source_asset(input_path, SourceType.OTHER)
    output: list[GeologicalEvidence] = []
    for index, record in enumerate(records, start=1):
        normalized = _normalize_record(
            record,
            aliases=aliases,
            source_asset_id=source_asset.asset_id,
            index=index,
            config=config,
            chainage_config=chainage_config,
        )
        output.append(normalized)
    return output


def _normalize_record(
    record: dict[str, Any],
    *,
    aliases: dict[str, list[str]],
    source_asset_id: str,
    index: int,
    config: dict[str, Any],
    chainage_config: ChainageValidationConfig,
) -> GeologicalEvidence:
    title = _as_text(first_present(record, aliases.get("title", []))) or None
    raw_text = _as_text(first_present(record, aliases.get("raw_text", []))) or ""
    if not raw_text and title:
        raw_text = title
    normalized_text = _normalize_text(raw_text)
    source_record_id = _as_text(first_present(record, aliases.get("source_record_id", []))) or str(
        index
    )
    source_type_raw = _as_text(first_present(record, aliases.get("source_type", []))) or None
    epistemic_status_raw = (
        _as_text(first_present(record, aliases.get("epistemic_status", []))) or None
    )
    source_type, source_type_basis, text_source_type = _source_type(
        source_type_raw,
        raw_text,
        title,
        config,
    )
    mapping = _epistemic_status(
        epistemic_status_raw,
        source_type,
        source_type_basis,
        text_source_type,
        config,
    )
    observed_time = parse_temporal_value(first_present(record, aliases.get("observed_time", [])))
    issued_time = parse_temporal_value(first_present(record, aliases.get("issued_time", [])))
    available_time_value = _available_time(first_present(record, aliases.get("available_time", [])))
    chainage_record = {
        "start_chainage": first_present(record, aliases.get("start_chainage", [])),
        "end_chainage": first_present(record, aliases.get("end_chainage", [])),
    }
    chainage_interval = parse_chainage_interval(chainage_record, raw_text, chainage_config)
    parse_warnings = _parse_warnings(
        raw_text,
        available_time_value,
        chainage_interval,
        mapping["after"],
        mapping["warnings"],
    )
    quality = grade_from_reason_codes(parse_warnings)
    evidence_type = _evidence_type(mapping["after"])
    available_time = available_time_value.value if available_time_value else None
    evidence_id = _stable_id(
        source_asset_id,
        source_record_id,
        evidence_type.value,
        raw_text,
        str(chainage_interval.normalized_start_chainage if chainage_interval else None),
        str(chainage_interval.normalized_end_chainage if chainage_interval else None),
    )
    spatial_scope = (
        SpatialScope(
            start_chainage=chainage_interval.normalized_start_chainage,
            end_chainage=chainage_interval.normalized_end_chainage,
            basis=chainage_interval.basis,
        )
        if chainage_interval
        else None
    )
    structured = _structured_attributes(raw_text)
    return GeologicalEvidence(
        evidence_id=f"geology-{evidence_id}",
        evidence_type=evidence_type,
        source_asset_ids=[source_asset_id],
        valid_time=None,
        available_time=available_time,
        ingested_time=datetime.now(UTC),
        spatial_scope=spatial_scope,
        quality_grade=quality,
        quality_flags=parse_warnings,
        method_version=GEOLOGY_METHOD_VERSION,
        provenance_refs=[f"record:{source_record_id}"],
        geological_source_type=source_type,
        epistemic_status=mapping["after"],
        title=title,
        raw_text=raw_text,
        normalized_text=normalized_text,
        observed_time=observed_time,
        issued_time=issued_time,
        available_time_value=available_time_value,
        chainage_interval=chainage_interval,
        structured_attributes=structured,
        source_record_id=source_record_id,
        source_type_raw=source_type_raw,
        epistemic_status_raw=epistemic_status_raw,
        epistemic_status_before_mapping=mapping["before"],
        epistemic_mapping_basis=str(mapping["basis"]),
        parse_warnings=parse_warnings,
    )


def geological_evidence_summary(records: list[GeologicalEvidence]) -> list[dict[str, Any]]:
    """Summarize geological evidence for CSV diagnostics."""

    return [
        {
            "evidence_id": record.evidence_id,
            "source_record_id": record.source_record_id,
            "source_type": record.geological_source_type.value,
            "source_type_raw": record.source_type_raw,
            "epistemic_status_before_mapping": record.epistemic_status_before_mapping.value,
            "epistemic_status": record.epistemic_status.value,
            "epistemic_mapping_basis": record.epistemic_mapping_basis,
            "available_time": record.available_time.isoformat() if record.available_time else None,
            "available_time_confidence": record.available_time_value.confidence.value
            if record.available_time_value
            else None,
            "start_chainage": record.chainage_interval.normalized_start_chainage
            if record.chainage_interval
            else None,
            "end_chainage": record.chainage_interval.normalized_end_chainage
            if record.chainage_interval
            else None,
            "spatial_scope_usable": record.chainage_interval.spatial_scope_usable
            if record.chainage_interval
            else False,
            "chainage_validation_flags": ";".join(record.chainage_interval.validation_flags)
            if record.chainage_interval
            else None,
            "quality_grade": record.quality_grade.value,
            "quality_flags": ";".join(record.quality_flags),
        }
        for record in records
    ]


def _available_time(value: object) -> TemporalValue:
    parsed = parse_temporal_value(value)
    if parsed.value is None:
        return TemporalValue(
            value=None, confidence=TemporalValueConfidence.UNKNOWN, basis="UNKNOWN"
        )
    return parsed


def _source_type(
    value: str | None,
    raw_text: str,
    title: str | None,
    config: dict[str, Any],
) -> tuple[GeologicalSourceType, str, GeologicalSourceType | None]:
    explicit = _source_type_from_text(value or "", config)
    context_text = (title or "") if explicit is not None else " ".join([raw_text, title or ""])
    context = _source_type_from_text(context_text, config)
    if explicit is not None:
        return explicit, "explicit_source_type", context
    if context is not None:
        return context, "text_source_type_hint", context
    return GeologicalSourceType.OTHER, "unrecognized_source_type", context


def _epistemic_status(
    raw_value: str | None,
    source_type: GeologicalSourceType,
    source_type_basis: str,
    text_source_type: GeologicalSourceType | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    source_status = _status_from_source_type(source_type, config)
    explicit_status = _status_from_raw(raw_value)
    text_status = _status_from_source_type(text_source_type, config) if text_source_type else None
    before = explicit_status or _legacy_epistemic_status(raw_value or "", source_type)
    warnings: list[str] = []
    basis = source_type_basis
    after = source_status
    if explicit_status and source_status != GeologicalEpistemicStatus.UNKNOWN:
        if explicit_status != source_status:
            warnings.append("EPISTEMIC_SOURCE_CONFLICT")
            after = GeologicalEpistemicStatus.UNKNOWN
            basis = "explicit_epistemic_conflicts_with_source_type"
        else:
            after = explicit_status
            basis = "explicit_epistemic_matches_source_type"
    elif explicit_status:
        after = explicit_status
        basis = "explicit_epistemic_status"
    if (
        text_status
        and source_status != GeologicalEpistemicStatus.UNKNOWN
        and text_status != source_status
        and source_type_basis == "explicit_source_type"
    ):
        warnings.append("EPISTEMIC_SOURCE_CONFLICT")
        after = GeologicalEpistemicStatus.UNKNOWN
        basis = "text_source_hint_conflicts_with_explicit_source_type"
    return {
        "before": before,
        "after": after,
        "basis": basis,
        "warnings": sorted(set(warnings)),
    }


def _evidence_type(status: GeologicalEpistemicStatus) -> EvidenceType:
    if status == GeologicalEpistemicStatus.FORECAST:
        return EvidenceType.GEOLOGICAL_FORECAST
    if status == GeologicalEpistemicStatus.OBSERVED:
        return EvidenceType.GEOLOGICAL_OBSERVATION
    if status == GeologicalEpistemicStatus.BACKGROUND:
        return EvidenceType.GEOLOGICAL_BACKGROUND
    return EvidenceType.GEOLOGICAL_UNKNOWN


def _parse_warnings(
    raw_text: str,
    available_time: TemporalValue,
    chainage_interval: ChainageInterval | None,
    epistemic_status: GeologicalEpistemicStatus,
    mapping_warnings: list[str],
) -> list[str]:
    warnings: set[str] = set(mapping_warnings)
    if not raw_text:
        warnings.add("RAW_TEXT_EMPTY")
    if available_time.value is None:
        warnings.add("AVAILABLE_TIME_UNKNOWN")
    if chainage_interval is None:
        warnings.add("SPATIAL_SCOPE_UNKNOWN")
    elif hasattr(chainage_interval, "validation_flags"):
        warnings.update(chainage_interval.validation_flags)
        if not chainage_interval.spatial_scope_usable:
            warnings.add("INVALID_SPATIAL_SCOPE")
    if epistemic_status == GeologicalEpistemicStatus.UNKNOWN:
        warnings.add("EPISTEMIC_STATUS_UNKNOWN")
    return sorted(warnings)


def _source_type_from_text(value: str, config: dict[str, Any]) -> GeologicalSourceType | None:
    text = value.lower()
    aliases = dict(config.get("source_type_aliases", {}))
    for source_type in GeologicalSourceType:
        candidates = [source_type.value, *list(aliases.get(source_type.value, []))]
        if any(str(candidate).lower() in text for candidate in candidates):
            return source_type
    return None


def _status_from_source_type(
    source_type: GeologicalSourceType | None,
    config: dict[str, Any],
) -> GeologicalEpistemicStatus:
    if source_type is None:
        return GeologicalEpistemicStatus.UNKNOWN
    mapping = dict(config.get("source_type_mapping", {}))
    if source_type.value in set(mapping.get("forecast", [])):
        return GeologicalEpistemicStatus.FORECAST
    if source_type.value in set(mapping.get("observed", [])):
        return GeologicalEpistemicStatus.OBSERVED
    if source_type.value in set(mapping.get("background", [])):
        return GeologicalEpistemicStatus.BACKGROUND
    return GeologicalEpistemicStatus.UNKNOWN


def _status_from_raw(value: str | None) -> GeologicalEpistemicStatus | None:
    if value is None:
        return None
    text = value.strip().lower()
    if text in {"forecast", "预报", "预测", "foreseen"}:
        return GeologicalEpistemicStatus.FORECAST
    if text in {"observed", "observation", "观测", "现场观测", "已揭示"}:
        return GeologicalEpistemicStatus.OBSERVED
    if text in {"background", "背景", "设计背景"}:
        return GeologicalEpistemicStatus.BACKGROUND
    if text in {"unknown", "未知"}:
        return GeologicalEpistemicStatus.UNKNOWN
    return None


def _legacy_epistemic_status(
    value: str,
    source_type: GeologicalSourceType,
) -> GeologicalEpistemicStatus:
    text = " ".join([value, source_type.value]).lower()
    if any(token in text for token in ["forecast", "预报", "预测", "tsp", "hsp", "sonic"]):
        return GeologicalEpistemicStatus.FORECAST
    if any(token in text for token in ["observed", "观测", "掌子面", "现场记录", "sketch"]):
        return GeologicalEpistemicStatus.OBSERVED
    if source_type in {
        GeologicalSourceType.DESIGN_BACKGROUND,
        GeologicalSourceType.DESIGN_GEOLOGY,
        GeologicalSourceType.REGIONAL_GEOLOGY,
    }:
        return GeologicalEpistemicStatus.BACKGROUND
    return GeologicalEpistemicStatus.UNKNOWN


def _chainage_config(config: dict[str, Any]) -> ChainageValidationConfig:
    data = dict(config.get("chainage_validation", {}))
    return ChainageValidationConfig(
        maximum_reasonable_interval_m=float(data.get("maximum_reasonable_interval_m", 5000.0)),
        scale_ratio_threshold=float(data.get("scale_ratio_threshold", 5.0)),
        prefix_consistency_check=bool(data.get("prefix_consistency_check", True)),
    )


def _structured_attributes(raw_text: str) -> dict[str, str | int | float | bool | None]:
    attrs: dict[str, str | int | float | bool | None] = {}
    for keyword in ["破碎", "裂隙", "富水", "围岩", "岩性", "可能", "推测", "预计", "建议关注"]:
        if keyword in raw_text:
            attrs[f"contains_{keyword}"] = True
    grade_match = re.search(r"[IVX]+级围岩|[ⅠⅡⅢⅣⅤ]+级围岩", raw_text)
    if grade_match:
        attrs["surrounding_rock_grade_text"] = grade_match.group(0)
    return attrs


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _as_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]
