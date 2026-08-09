from __future__ import annotations

import pandas as pd

from tbm_twin.operational_freeze.chainage_regime import (
    ChainageRegimeConfig,
    ChainageRegimeState,
    classify_daily_observations,
)


def test_chainage_jump_shifted_regime_and_restored_sequence() -> None:
    state = ChainageRegimeState()
    config = ChainageRegimeConfig(chainage_jump_threshold_m=5.0, implausible_advance_m=100.0)

    day5, _, audit5 = classify_daily_observations(
        target_date="2023-11-05",
        frame=_frame("2023-11-05", [1013928.0, 1014116.0, 1014117.0, 1014119.0]),
        state=state,
        config=config,
    )
    day6, _, audit6 = classify_daily_observations(
        target_date="2023-11-06",
        frame=_frame("2023-11-06", [1014119.0, 1014129.0]),
        state=state,
        config=config,
    )
    day9, _, audit9 = classify_daily_observations(
        target_date="2023-11-09",
        frame=_frame("2023-11-09", [1013946.0, 1013949.0]),
        state=state,
        config=config,
    )

    assert day5["chainage_regime_status"].to_list() == [
        "TRUSTED",
        "SUSPECT_JUMP",
        "SUSPECT_SHIFTED_REGIME",
        "SUSPECT_SHIFTED_REGIME",
    ]
    assert audit5["trusted_daily_plc_range"]["end_chainage"] == 1013928.0
    assert day6["chainage_spatially_usable"].to_list() == [False, False]
    assert audit6["trusted_daily_plc_range"] is None
    assert audit6["spatial_scope_status"] == "UNAVAILABLE"
    assert day9["chainage_regime_status"].to_list() == ["RESTORED", "RESTORED"]
    assert audit9["trusted_daily_plc_range"]["start_chainage"] == 1013946.0


def _frame(target_date: str, chainages: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(
                f"{target_date} 00:00:00+00:00",
                periods=len(chainages),
                freq="10s",
            ),
            "source_row_number": list(range(len(chainages))),
            "observation_id": [f"obs-{target_date}-{idx}" for idx in range(len(chainages))],
            "shield_head_chainage": chainages,
        }
    )
