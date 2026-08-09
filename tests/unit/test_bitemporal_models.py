from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from tbm_twin.bitemporal.models import Stage3BConfig


def test_stage3b_config_requires_timezone() -> None:
    with pytest.raises(ValueError, match="generated_at must be timezone-aware"):
        Stage3BConfig(
            repo_root=Path("."),
            generated_at=datetime.fromisoformat("2026-07-30T14:30:00"),
            knowledge_cutoff_date=date(2024, 11, 17),
        )


def test_stage3b_config_keeps_generated_at_separate_from_cutoff() -> None:
    config = Stage3BConfig(
        repo_root=Path("."),
        generated_at=datetime.fromisoformat("2026-07-30T14:30:00+08:00"),
        knowledge_cutoff_date=date(2024, 11, 17),
    )
    assert config.generated_at.date() != config.knowledge_cutoff_date
