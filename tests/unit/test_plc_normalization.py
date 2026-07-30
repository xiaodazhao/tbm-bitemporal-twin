from __future__ import annotations

from tbm_twin.assets.models import SourceType
from tbm_twin.assets.registry import register_source_asset
from tbm_twin.channels.models import TimezoneBasis, TimezoneConfidence, TimezoneDefinition
from tbm_twin.timeseries.normalization import normalize_plc_csv, write_normalized_parquet
from tests.conftest import base_rows, write_plc_csv


def test_normalization_preserves_source_row_number_asset_id_and_duplicate_flag(
    tmp_path, catalog
) -> None:
    rows = base_rows()
    rows.append({**rows[-1], "运行时间-time": "not-a-time", "导向盾首里程": 101.0})
    rows.append({**rows[-1], "运行时间-time": rows[1]["运行时间-time"], "导向盾首里程": 100.03})
    path = write_plc_csv(tmp_path / "plc.csv", rows)
    asset = register_source_asset(path, SourceType.PLC_CSV)

    result = normalize_plc_csv(path, asset, catalog)

    assert len(result.frame) == 4
    assert result.quality_report.time.parse_failed_count == 1
    assert set(result.frame["asset_id"]) == {asset.asset_id}
    assert result.frame["source_row_number"].min() == 1
    duplicate_rows = result.frame[
        result.frame["quality_flags"].map(lambda flags: "duplicate_timestamp" in flags)
    ]
    assert len(duplicate_rows) == 2


def test_normalization_writes_parquet_and_sidecars(tmp_path, catalog) -> None:
    path = write_plc_csv(tmp_path / "plc.csv", base_rows())
    asset = register_source_asset(path, SourceType.PLC_CSV)
    result = normalize_plc_csv(path, asset, catalog)
    output = tmp_path / "normalized.parquet"

    write_normalized_parquet(result, output)

    assert output.exists()
    assert output.with_suffix(".parquet.metadata.json").exists()
    assert output.with_suffix(".parquet.quality.json").exists()


def test_naive_timestamp_uses_verified_source_timezone_before_utc_conversion(
    tmp_path, catalog
) -> None:
    rows = base_rows()
    rows[0]["运行时间-time"] = "2026-01-01 08:00:00"
    rows[1]["运行时间-time"] = "2026-01-01 08:00:10"
    rows[2]["运行时间-time"] = "2026-01-01 08:00:20"
    path = write_plc_csv(tmp_path / "plc.csv", rows)
    asset = register_source_asset(path, SourceType.PLC_CSV)

    result = normalize_plc_csv(path, asset, catalog)

    assert result.frame["timestamp"].iloc[0].isoformat() == "2026-01-01T00:00:00+00:00"
    assert result.metadata.timezone_confidence == "ASSUMED"
    assert result.metadata.timezone_basis == "PROJECT_LOCATION_ASSUMPTION"
    assert result.metadata.timezone_warnings


def test_naive_timestamp_without_verified_timezone_records_warning(tmp_path, catalog) -> None:
    rows = base_rows()
    rows[0]["运行时间-time"] = "2026-01-01 08:00:00"
    rows[1]["运行时间-time"] = "2026-01-01 08:00:10"
    rows[2]["运行时间-time"] = "2026-01-01 08:00:20"
    path = write_plc_csv(tmp_path / "plc.csv", rows)
    asset = register_source_asset(path, SourceType.PLC_CSV)
    unverified = catalog.model_copy(
        update={
            "timezone": TimezoneDefinition(
                source_timezone=None,
                canonical_timezone="UTC",
                timezone_confidence=TimezoneConfidence.UNKNOWN,
                timezone_basis=TimezoneBasis.UNKNOWN,
            )
        }
    )

    result = normalize_plc_csv(path, asset, unverified)

    assert result.metadata.timezone_confidence == "UNKNOWN"
    assert result.metadata.timezone_warnings
