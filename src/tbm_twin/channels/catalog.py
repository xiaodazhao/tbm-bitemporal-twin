"""YAML-backed channel catalog."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from tbm_twin.channels.models import ChannelDefinition, TimezoneDefinition
from tbm_twin.channels.resolver import ChannelMatch, MatchMethod, normalize_header


class ChannelCatalog(BaseModel):
    """A versioned collection of canonical channel definitions."""

    model_config = ConfigDict(frozen=True)

    catalog_version: str
    timezone: TimezoneDefinition = TimezoneDefinition()
    channels: list[ChannelDefinition]

    @property
    def by_name(self) -> dict[str, ChannelDefinition]:
        """Return definitions keyed by canonical channel name."""

        return {channel.canonical_name: channel for channel in self.channels}

    def resolve(self, raw_name: str) -> ChannelMatch:
        """Resolve one raw column name without fuzzy substring matching."""

        by_name = self.by_name
        if raw_name in by_name:
            return ChannelMatch(
                raw_name=raw_name,
                canonical_name=raw_name,
                method=MatchMethod.EXACT,
                warnings=[],
            )

        normalized_raw = normalize_header(raw_name)
        for channel in self.channels:
            if normalized_raw == normalize_header(channel.canonical_name):
                return ChannelMatch(
                    raw_name=raw_name,
                    canonical_name=channel.canonical_name,
                    method=MatchMethod.NORMALIZED_EXACT,
                    warnings=[],
                )

        for channel in self.channels:
            if raw_name in channel.aliases:
                return ChannelMatch(
                    raw_name=raw_name,
                    canonical_name=channel.canonical_name,
                    method=MatchMethod.ALIAS,
                    warnings=[],
                )
            if normalized_raw in {normalize_header(alias) for alias in channel.aliases}:
                return ChannelMatch(
                    raw_name=raw_name,
                    canonical_name=channel.canonical_name,
                    method=MatchMethod.ALIAS,
                    warnings=[],
                )

        suggestions = [
            channel.canonical_name
            for channel in self.channels
            for alias in [channel.canonical_name, *channel.aliases]
            if normalized_raw and normalized_raw in normalize_header(alias)
        ]
        warning = (
            f"Potential fuzzy suggestions: {', '.join(sorted(set(suggestions)))}"
            if suggestions
            else "No catalog match."
        )
        return ChannelMatch(
            raw_name=raw_name,
            canonical_name=None,
            method=MatchMethod.UNMATCHED,
            warnings=[warning],
        )

    def resolve_columns(self, raw_columns: list[str]) -> dict[str, ChannelMatch]:
        """Resolve a list of raw columns by canonical name, keeping first match by priority."""

        matches = [self.resolve(column) for column in raw_columns]
        selected: dict[str, ChannelMatch] = {}
        priority = {
            MatchMethod.EXACT: 0,
            MatchMethod.NORMALIZED_EXACT: 1,
            MatchMethod.ALIAS: 2,
            MatchMethod.UNMATCHED: 99,
        }
        for match in matches:
            if match.canonical_name is None:
                continue
            current = selected.get(match.canonical_name)
            if current is None or priority[match.method] < priority[current.method]:
                selected[match.canonical_name] = match
        return selected


def load_channel_catalog(path: Path = Path("configs/plc_channels.yaml")) -> ChannelCatalog:
    """Load a ChannelCatalog from YAML."""

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return ChannelCatalog.model_validate(data)
