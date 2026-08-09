from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from tbm_twin.state.models import Stage3AStateConfig


def test_generated_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        Stage3AStateConfig(
            repo_root=Path("."),
            output_dir=Path("artifacts/tmp"),
            generated_at=datetime(2026, 7, 30, 14, 30),
        )


def test_timezone_aware_generated_at_is_allowed() -> None:
    config = Stage3AStateConfig(
        repo_root=Path("."),
        output_dir=Path("artifacts/tmp"),
        generated_at=datetime(2026, 7, 30, 14, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert config.generated_at.tzinfo is not None
