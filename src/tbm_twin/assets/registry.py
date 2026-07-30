"""Source asset registry helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tbm_twin.assets.hashing import sha256_file, stable_asset_id
from tbm_twin.assets.models import SourceAsset, SourceType

SOURCE_ASSET_SCHEMA_VERSION = "source_asset_v1"


def register_source_asset(
    source_path: Path,
    source_type: SourceType = SourceType.PLC_CSV,
    *,
    observed_time: datetime | None = None,
    available_time: datetime | None = None,
    ingested_time: datetime | None = None,
    source_timezone: str | None = None,
    canonical_timezone: str = "UTC",
    timezone_confidence: str = "UNKNOWN",
    timezone_basis: str = "UNKNOWN",
    timezone_warnings: list[str] | None = None,
) -> SourceAsset:
    """Create a deterministic SourceAsset record for a local file."""

    path = source_path.resolve()
    if not path.exists():
        msg = f"Source file does not exist: {path}"
        raise FileNotFoundError(msg)
    content_hash = sha256_file(path)
    schema_version = SOURCE_ASSET_SCHEMA_VERSION
    return SourceAsset(
        asset_id=stable_asset_id(source_type.value, content_hash, schema_version),
        source_type=source_type,
        source_path=path,
        content_hash=content_hash,
        observed_time=observed_time,
        available_time=available_time,
        ingested_time=ingested_time or datetime.now(UTC),
        source_timezone=source_timezone,
        canonical_timezone=canonical_timezone,
        timezone_confidence=timezone_confidence,
        timezone_basis=timezone_basis,
        timezone_warnings=timezone_warnings or [],
        schema_version=schema_version,
    )
