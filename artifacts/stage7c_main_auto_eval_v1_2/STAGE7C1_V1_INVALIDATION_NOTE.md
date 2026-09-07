# Stage7C.1 v1 Invalidation Note

Stage7C.1 v1 must not be used for quantitative paper conclusions.

The v1 input binding to Stage7B was broadly correct, but the automatic evaluator itself used condition/task-level bags of values or terms where statement-level authoritative binding was required.

Invalidating causes:

- multi-cell metric overwrite;
- E3 zero-prefix regex false positives;
- forecast/observed support conflation;
- probability-negation false positives;
- coarse condition-level trace checking;
- E12 not materially implemented.

The tag `stage7c-main-auto-evaluation-v1-frozen` is intentionally preserved as historical audit state and is not moved.