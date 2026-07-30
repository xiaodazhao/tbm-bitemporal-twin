from __future__ import annotations

from tbm_twin.assets.models import SourceType
from tbm_twin.assets.registry import register_source_asset
from tbm_twin.timeseries.normalization import normalize_plc_csv
from tests.conftest import base_rows, write_plc_csv


def test_quality_detects_gap_duplicate_reverse_jump_and_unverified_units(tmp_path, catalog) -> None:
    rows = base_rows()
    rows[1]["运行时间-time"] = rows[0]["运行时间-time"]
    rows[2]["运行时间-time"] = "2026-01-01T01:00:00+00:00"
    rows[1]["导向盾首里程"] = 99.9
    rows[2]["导向盾首里程"] = 120.0
    path = write_plc_csv(tmp_path / "plc.csv", rows)
    asset = register_source_asset(path, SourceType.PLC_CSV)

    report = normalize_plc_csv(path, asset, catalog).quality_report

    assert report.time.duplicate_timestamp_count == 2
    assert report.time.large_gap_count >= 1
    assert report.chainage.reverse_count >= 1
    assert report.chainage.large_jump_count >= 1
    assert "UNIT_UNVERIFIED:advance_speed" in report.reason_codes


def test_quality_detects_core_field_missing(tmp_path, catalog) -> None:
    rows = [{"运行时间-time": "2026-01-01T00:00:00+00:00", "导向盾首里程": 1.0}]
    path = write_plc_csv(tmp_path / "missing.csv", rows)
    asset = register_source_asset(path, SourceType.PLC_CSV)

    report = normalize_plc_csv(path, asset, catalog).quality_report

    assert "PRIMARY_HIGH_MISSING:advance_speed" in report.reason_codes
    assert report.grade.value in {"C", "D"}
