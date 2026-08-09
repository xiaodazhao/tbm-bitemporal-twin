from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tbm_twin.metrics.stage4a1_1_builder import Stage4A11Builder


def _response(response_id: str, episode_id: str, date: str, channel: str, median: float) -> dict:
    return {
        "evidence_id": response_id,
        "episode_id": episode_id,
        "target_date": date,
        "channel_name": channel,
        "statistics": {"median": median, "sample_count": 1},
    }


def test_rpm_regime_shift_uses_ratio_without_value_correction() -> None:
    builder = Stage4A11Builder(
        repo_root=Path.cwd(),
        generated_at=datetime(2026, 8, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    responses = [
        _response("a1", "e1", "2023-11-30", "advance_speed", 10.0),
        _response("p1", "e1", "2023-11-30", "penetration", 2.0),
        _response("r1", "e1", "2023-11-30", "cutterhead_rpm", 5.0),
        _response("a2", "e2", "2023-12-01", "advance_speed", 10.0),
        _response("p2", "e2", "2023-12-01", "penetration", 2.0),
        _response("r2", "e2", "2023-12-01", "cutterhead_rpm", 83.0),
    ]
    daily, _ = builder._build_daily_regime_audit(responses)
    rpm_rows = {row["target_date"]: row for row in daily if row["channel_name"] == "cutterhead_rpm"}
    assert rpm_rows["2023-11-30"]["rpm_consistency_ratio_median"] == 1.0
    assert rpm_rows["2023-12-01"]["rpm_consistency_ratio_median"] == 16.6
    assert rpm_rows["2023-12-01"]["response_median"] == 83.0
    assert rpm_rows["2023-12-01"]["regime_status"] == "SCALE_REGIME_SHIFT"
