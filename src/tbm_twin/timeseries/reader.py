"""Raw PLC file readers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_plc_csv(path: Path) -> pd.DataFrame:
    """Read a raw PLC CSV without mutating source values."""

    encodings = ("utf-8-sig", "utf-8", "gb18030")
    failures: list[str] = []
    for encoding in encodings:
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            failures.append(f"{encoding}: {exc}")
    msg = f"Could not decode CSV {path}. Tried: {'; '.join(failures)}"
    raise ValueError(msg)
