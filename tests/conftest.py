from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tbm_twin.assets.models import SourceType
from tbm_twin.assets.registry import register_source_asset
from tbm_twin.channels.catalog import ChannelCatalog, load_channel_catalog
from tbm_twin.timeseries.normalization import normalize_plc_csv


@pytest.fixture
def catalog() -> ChannelCatalog:
    return load_channel_catalog(Path("configs/plc_channels.yaml"))


def write_plc_csv(path: Path, rows: list[dict[str, object]]) -> Path:
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def normalize_rows(
    tmp_path: Path, rows: list[dict[str, object]], catalog: ChannelCatalog
) -> pd.DataFrame:
    path = write_plc_csv(tmp_path / "plc.csv", rows)
    asset = register_source_asset(path, SourceType.PLC_CSV)
    return normalize_plc_csv(path, asset, catalog).frame


def base_rows() -> list[dict[str, object]]:
    return [
        {
            "运行时间-time": "2026-01-01T00:00:00+00:00",
            "导向盾首里程": 100.0,
            "掘进状态": 1,
            "推进速度": 2.0,
            "推进给定速度": 2.0,
            "推力": 10.0,
            "刀盘扭矩": 20.0,
            "刀盘实际转速": 3.0,
            "贯入度": 1.0,
        },
        {
            "运行时间-time": "2026-01-01T00:00:10+00:00",
            "导向盾首里程": 100.02,
            "掘进状态": 1,
            "推进速度": 2.0,
            "推进给定速度": 2.0,
            "推力": 10.0,
            "刀盘扭矩": 20.0,
            "刀盘实际转速": 3.0,
            "贯入度": 1.0,
        },
        {
            "运行时间-time": "2026-01-01T00:00:20+00:00",
            "导向盾首里程": 100.04,
            "掘进状态": 1,
            "推进速度": 2.0,
            "推进给定速度": 2.0,
            "推力": 10.0,
            "刀盘扭矩": 20.0,
            "刀盘实际转速": 3.0,
            "贯入度": 1.0,
        },
    ]
