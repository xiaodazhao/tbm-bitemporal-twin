"""Project settings loaded from environment variables."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel


class Settings(BaseModel):
    """Runtime settings for local scripts."""

    tbm_data_root: Path | None = None
    plc_data_dir: Path | None = None
    artifact_dir: Path = Path("./artifacts")


def load_settings() -> Settings:
    """Load settings from `.env` without requiring real local paths."""

    load_dotenv()
    import os

    return Settings(
        tbm_data_root=Path(os.environ["TBM_DATA_ROOT"]) if os.getenv("TBM_DATA_ROOT") else None,
        plc_data_dir=Path(os.environ["PLC_DATA_DIR"]) if os.getenv("PLC_DATA_DIR") else None,
        artifact_dir=Path(os.getenv("ARTIFACT_DIR", "./artifacts")),
    )
