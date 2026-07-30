from __future__ import annotations

from tbm_twin.process.weak_labels import label_operation_phases
from tests.conftest import base_rows, normalize_rows


def test_phase_labels_excavating_idle_and_data_gap(tmp_path, catalog) -> None:
    rows = base_rows()
    rows.append(
        {
            **rows[-1],
            "运行时间-time": "2026-01-01T01:00:00+00:00",
            "掘进状态": 0,
            "推进速度": 0.0,
            "推力": 0.0,
            "刀盘扭矩": 0.0,
            "刀盘实际转速": 0.0,
        }
    )
    normalized = normalize_rows(tmp_path, rows, catalog)

    labeled = label_operation_phases(normalized)

    assert labeled["operation_phase"].iloc[0] == "EXCAVATING"
    assert "DATA_GAP" in set(labeled["operation_phase"])


def test_phase_outputs_unknown_when_signals_are_insufficient(tmp_path, catalog) -> None:
    rows = [{"运行时间-time": "2026-01-01T00:00:00+00:00", "导向盾首里程": 1.0}]
    normalized = normalize_rows(tmp_path, rows, catalog)

    labeled = label_operation_phases(normalized)

    assert labeled["operation_phase"].iloc[0] == "UNKNOWN"
