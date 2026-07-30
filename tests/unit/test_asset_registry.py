from __future__ import annotations

from tbm_twin.assets.models import SourceType
from tbm_twin.assets.registry import register_source_asset


def test_same_file_content_generates_same_asset_id(tmp_path) -> None:
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    first.write_text("timestamp,value\n2026-01-01T00:00:00+00:00,1\n", encoding="utf-8")
    second.write_text(first.read_text(encoding="utf-8"), encoding="utf-8")

    asset_a = register_source_asset(first, SourceType.PLC_CSV)
    asset_b = register_source_asset(second, SourceType.PLC_CSV)

    assert asset_a.asset_id == asset_b.asset_id
    assert asset_a.content_hash == asset_b.content_hash


def test_source_asset_keeps_timezone_audit_fields(tmp_path) -> None:
    path = tmp_path / "a.csv"
    path.write_text("timestamp,value\n2026-01-01 08:00:00,1\n", encoding="utf-8")

    asset = register_source_asset(
        path,
        SourceType.PLC_CSV,
        source_timezone="Asia/Shanghai",
        canonical_timezone="UTC",
        timezone_confidence="ASSUMED",
        timezone_basis="PROJECT_LOCATION_ASSUMPTION",
        timezone_warnings=["naive_timestamp_timezone_assumed"],
    )

    assert asset.timezone_confidence == "ASSUMED"
    assert asset.timezone_basis == "PROJECT_LOCATION_ASSUMPTION"
    assert asset.timezone_warnings == ["naive_timestamp_timezone_assumed"]
