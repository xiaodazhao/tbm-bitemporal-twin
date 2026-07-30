# Project Rules

1. The research object is dynamic construction state and future engineering Claim permissibility, not daily reports.
2. `ExcavationEpisode` is the primary construction-process object.
3. Dates are query and aggregation conditions only.
4. Future spatial bins may only be spatial indexes, not construction facts.
5. Fields with unverified units must not be used for physical calculation.
6. Mechanical response must not be directly interpreted as geological cause.
7. Every derived object must keep source references and method versions.
8. The old repository is read-only reference material; do not copy its architecture.
9. Every feature must have tests.
10. After modifications, run `ruff`, `mypy`, and `pytest`.

