"""As-of query helpers for Stage 3B bitemporal state artifacts."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from tbm_twin.bitemporal.temporal_eligibility import parse_local_date
from tbm_twin.state.io import read_jsonl


class AsOfStateQuery:
    """Query materialized Stage 3B versions by valid and knowledge date."""

    def __init__(self, artifact_dir: Path) -> None:
        self.versions = read_jsonl(artifact_dir / "bitemporal_state_versions.jsonl")
        self._by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for version in self.versions:
            key = (str(version["valid_date"]), str(version["cell_id"]))
            self._by_key.setdefault(key, []).append(version)
        for rows in self._by_key.values():
            rows.sort(
                key=lambda row: (str(row["knowledge_time_start_local_date"]), row["version_number"])
            )

    def get_state_history(self, valid_date: date | str, cell_id: str) -> list[dict[str, Any]]:
        """Return the complete version history for one valid-date cell."""

        return list(self._by_key.get((str(valid_date), cell_id), []))

    def get_state_as_known(
        self,
        valid_date: date | str,
        cell_id: str,
        knowledge_as_of_local_date: date | str,
    ) -> dict[str, Any] | None:
        """Return the version known at the supplied local knowledge date."""

        valid = parse_local_date(valid_date)
        as_of = parse_local_date(knowledge_as_of_local_date)
        if valid is None or as_of is None or as_of < valid:
            return None
        selected: dict[str, Any] | None = None
        for version in self.get_state_history(valid, cell_id):
            start = parse_local_date(version["knowledge_time_start_local_date"])
            end = parse_local_date(version["knowledge_time_end_local_date"])
            if start is None:
                continue
            if start <= as_of and (end is None or as_of < end):
                selected = version
        return selected

    def get_latest_state(
        self,
        valid_date: date | str,
        cell_id: str,
        knowledge_cutoff_date: date | str,
    ) -> dict[str, Any] | None:
        """Return the latest state available by the cutoff date."""

        return self.get_state_as_known(valid_date, cell_id, knowledge_cutoff_date)
