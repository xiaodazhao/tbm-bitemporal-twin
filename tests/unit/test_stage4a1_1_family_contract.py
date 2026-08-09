from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tbm_twin.metrics.stage4a1_1_builder import Stage4A11Builder


def test_response_family_contract_groups_dependent_channels() -> None:
    builder = Stage4A11Builder(
        repo_root=Path.cwd(),
        generated_at=datetime(2026, 8, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    contract = builder._family_contract()
    families = {row["family_name"]: row for row in contract["families"]}
    assert families["ADVANCE_KINEMATIC_RESPONSE"]["channels"] == [
        "advance_speed",
        "penetration",
    ]
    assert families["LOAD_RESPONSE"]["channels"] == ["total_thrust", "cutterhead_torque"]
    assert families["ROTATION_DIAGNOSTIC"]["included_in_scalar_rai"] is False


def test_rpm_channel_is_diagnostic_only_for_scalar_rai() -> None:
    builder = Stage4A11Builder(
        repo_root=Path.cwd(),
        generated_at=datetime(2026, 8, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    contract = builder._rai_eligibility_contract()
    rpm = next(row for row in contract["channels"] if row["channel_name"] == "cutterhead_rpm")
    assert rpm["included_in_scalar_rai"] is False
    assert rpm["value_correction_applied"] is False
    assert rpm["scalar_rai_eligibility"] == "DIAGNOSTIC_ONLY_UNRESOLVED_MEASUREMENT_REGIME"
