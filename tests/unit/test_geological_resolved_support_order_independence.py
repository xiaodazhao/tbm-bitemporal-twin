"""Stage 5A geological subject ordering independence tests."""

from __future__ import annotations

from tbm_twin.claims.resolution import AuthoritativeSupportResolver
from tests.unit.test_geological_resolved_support_context_binding import (
    _lookup,
    _proposal,
    _subjects,
)


def test_subject_list_order_does_not_change_resolved_context() -> None:
    proposal = _proposal("bt_2", "sv_2", "daily_2", "cell_2", "2023-09-16")
    left = AuthoritativeSupportResolver(_lookup(_subjects())).resolve_many(
        proposal.support_refs,
        proposal,
    )[0]
    right = AuthoritativeSupportResolver(_lookup(list(reversed(_subjects())))).resolve_many(
        proposal.support_refs,
        proposal,
    )[0]

    assert left.model_dump(mode="json") == right.model_dump(mode="json")
