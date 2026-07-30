from __future__ import annotations

from tbm_twin.channels.resolver import MatchMethod


def test_channel_catalog_alias_and_normalized_matching(catalog) -> None:
    assert catalog.resolve("导向盾首里程").canonical_name == "shield_head_chainage"
    match = catalog.resolve(" CutterHead_RPM ")
    assert match.canonical_name == "cutterhead_rpm"
    assert match.method == MatchMethod.NORMALIZED_EXACT


def test_channel_catalog_does_not_auto_select_fuzzy_substrings(catalog) -> None:
    match = catalog.resolve("foo_推进速度_bar")
    assert match.canonical_name is None
    assert match.method == MatchMethod.UNMATCHED
    assert match.warnings
