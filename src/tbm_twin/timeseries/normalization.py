"""PLC normalization pipeline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from tbm_twin.assets.models import SourceAsset
from tbm_twin.channels.catalog import ChannelCatalog
from tbm_twin.timeseries.models import (
    NORMALIZED_COLUMNS,
    NormalizationMetadata,
    NormalizationResult,
)
from tbm_twin.timeseries.quality import evaluate_plc_quality
from tbm_twin.timeseries.reader import read_plc_csv

NORMALIZATION_VERSION = "plc_normalization_v1"

NUMERIC_CHANNELS = {
    "shield_head_chainage",
    "daily_advance",
    "cumulative_advance",
    "cylinder_displacement",
    "advance_speed",
    "set_advance_speed",
    "total_thrust",
    "cutterhead_torque",
    "cutterhead_rpm",
    "penetration",
}


def normalize_plc_csv(
    path: Path, asset: SourceAsset, catalog: ChannelCatalog
) -> NormalizationResult:
    """Read and normalize a PLC CSV into the Stage 1 DataFrame contract."""

    raw = read_plc_csv(path)
    matches = catalog.resolve_columns([str(column) for column in raw.columns])
    raw_columns = {
        canonical: match.raw_name
        for canonical, match in matches.items()
        if match.canonical_name is not None
    }
    normalized = pd.DataFrame(index=raw.index)
    normalized["asset_id"] = asset.asset_id
    normalized["source_row_number"] = raw.index.to_series().astype(int) + 1

    for column in NORMALIZED_COLUMNS:
        if column in {"observation_id", "asset_id", "source_row_number", "quality_flags"}:
            continue
        raw_name = raw_columns.get(column)
        normalized[column] = raw[raw_name] if raw_name in raw.columns else pd.NA

    normalized["timestamp"], timezone_warnings = _parse_timestamp_series(
        normalized["timestamp"],
        source_timezone=catalog.timezone.source_timezone,
        canonical_timezone=catalog.timezone.canonical_timezone,
        timezone_confidence=catalog.timezone.timezone_confidence.value,
    )
    parse_failed_count = int(normalized["timestamp"].isna().sum())

    quality_flags: list[list[str]] = [[] for _ in range(len(normalized))]
    for position, is_bad in enumerate(normalized["timestamp"].isna().to_list()):
        if is_bad:
            quality_flags[position].append("time_parse_failed")

    for channel in NUMERIC_CHANNELS:
        before = normalized[channel].copy()
        normalized[channel] = pd.to_numeric(normalized[channel], errors="coerce")
        failed = before.notna() & normalized[channel].isna()
        for position, is_bad in enumerate(failed.to_list()):
            if is_bad:
                quality_flags[position].append(f"numeric_parse_failed:{channel}")

    valid_unsorted = normalized[normalized["timestamp"].notna()].copy()
    duplicate_mask = valid_unsorted["timestamp"].duplicated(keep=False)
    for source_row_number in (
        valid_unsorted.loc[duplicate_mask, "source_row_number"].astype(int).to_list()
    ):
        quality_flags[source_row_number - 1].append("duplicate_timestamp")

    valid_unsorted["quality_flags"] = [
        quality_flags[int(row_number) - 1] for row_number in valid_unsorted["source_row_number"]
    ]
    quality_report = evaluate_plc_quality(
        asset_id=asset.asset_id,
        raw_frame=raw,
        normalized_frame=valid_unsorted,
        catalog=catalog,
        raw_columns_by_canonical=raw_columns,
        parse_failed_count=parse_failed_count,
    )

    valid = valid_unsorted.copy()
    valid["quality_flags"] = [
        quality_flags[int(row_number) - 1] for row_number in valid["source_row_number"]
    ]
    valid = valid.sort_values(["timestamp", "source_row_number"]).reset_index(drop=True)
    valid["observation_id"] = [
        _stable_observation_id(
            asset.asset_id,
            int(row.source_row_number),
            row.timestamp.isoformat(),
        )
        for row in valid.itertuples(index=False)
    ]
    valid = valid[NORMALIZED_COLUMNS]

    metadata = NormalizationMetadata(
        asset_id=asset.asset_id,
        catalog_version=catalog.catalog_version,
        normalization_version=NORMALIZATION_VERSION,
        source_timezone=catalog.timezone.source_timezone,
        canonical_timezone=catalog.timezone.canonical_timezone,
        timezone_confidence=catalog.timezone.timezone_confidence.value,
        timezone_basis=catalog.timezone.timezone_basis.value,
        timezone_warnings=timezone_warnings,
        row_count_raw=len(raw),
        row_count_normalized=len(valid),
        warning_count=len(quality_report.reason_codes)
        + sum(len(flags) for flags in valid["quality_flags"]),
    )
    return NormalizationResult(frame=valid, quality_report=quality_report, metadata=metadata)


def write_normalized_parquet(result: NormalizationResult, output_path: Path) -> NormalizationResult:
    """Write normalized observations to Parquet and sidecar metadata JSON."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.frame.to_parquet(output_path, index=False)
    metadata_path = output_path.with_suffix(output_path.suffix + ".metadata.json")
    report_path = output_path.with_suffix(output_path.suffix + ".quality.json")
    metadata_path.write_text(result.metadata.model_dump_json(indent=2), encoding="utf-8")
    report_path.write_text(result.quality_report.model_dump_json(indent=2), encoding="utf-8")
    return result.model_copy(update={"output_path": output_path})


def load_normalized_parquet(path: Path) -> pd.DataFrame:
    """Load normalized PLC observations from Parquet."""

    return pd.read_parquet(path)


def _stable_observation_id(asset_id: str, source_row_number: int, timestamp: str) -> str:
    seed = f"{asset_id}:{source_row_number}:{timestamp}".encode()
    return f"obs-{hashlib.sha256(seed).hexdigest()[:24]}"


def _parse_timestamp_series(
    series: pd.Series,
    *,
    source_timezone: str | None,
    canonical_timezone: str,
    timezone_confidence: str,
) -> tuple[pd.Series, list[str]]:
    warnings: set[str] = set()
    canonical_zone = ZoneInfo(canonical_timezone)
    source_zone = ZoneInfo(source_timezone) if source_timezone else canonical_zone
    parsed_values: list[pd.Timestamp] = []
    for value in series.to_list():
        timestamp = pd.to_datetime(value, errors="coerce")
        if pd.isna(timestamp):
            parsed_values.append(pd.NaT)
            continue
        timestamp = pd.Timestamp(timestamp)
        if timestamp.tzinfo is None:
            if timezone_confidence != "VERIFIED":
                warnings.add(
                    f"naive_timestamp_timezone_{timezone_confidence.lower()}; "
                    "localized with configured source timezone"
                )
            timestamp = timestamp.tz_localize(source_zone)
        parsed_values.append(timestamp.tz_convert(canonical_zone))
    return pd.Series(parsed_values, index=series.index), sorted(warnings)


def write_json(path: Path, payload: object) -> None:
    """Write a JSON payload with readable indentation."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
