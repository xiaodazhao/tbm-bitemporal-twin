from __future__ import annotations

from datetime import UTC, datetime

from tbm_twin.assets.models import SourceType
from tbm_twin.assets.registry import register_source_asset


def test_source_asset_id_is_path_independent_for_same_content(tmp_path) -> None:
    left = tmp_path / "left" / "tbm_data_20230915.csv"
    right = tmp_path / "renamed" / "tbm_data_20230915.csv"
    left.parent.mkdir()
    right.parent.mkdir()
    content = "运行时间-time,导向盾首里程\n2023-09-15 00:00:00,1\n"
    left.write_text(content, encoding="utf-8")
    right.write_text(content, encoding="utf-8")
    reconstructed_at = datetime(2026, 7, 30, tzinfo=UTC)

    first = register_source_asset(left, SourceType.PLC_CSV, ingested_time=reconstructed_at)
    second = register_source_asset(right, SourceType.PLC_CSV, ingested_time=reconstructed_at)

    assert first.asset_id == second.asset_id
    assert first.content_hash == second.content_hash


def test_source_asset_id_does_not_depend_on_reconstruction_time(tmp_path) -> None:
    path = tmp_path / "tbm_data_20230915.csv"
    path.write_text(
        "运行时间-time,导向盾首里程\n2023-09-15 00:00:00,1\n",
        encoding="utf-8",
    )

    first = register_source_asset(
        path,
        SourceType.PLC_CSV,
        ingested_time=datetime(2026, 7, 30, tzinfo=UTC),
    )
    second = register_source_asset(
        path,
        SourceType.PLC_CSV,
        ingested_time=datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert first.asset_id == second.asset_id
