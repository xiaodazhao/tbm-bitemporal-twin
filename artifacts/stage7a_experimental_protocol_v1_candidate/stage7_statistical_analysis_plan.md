# Stage7 Statistical Analysis Plan

The main comparison is paired: B0, B1, and P are evaluated on the same frozen
benchmark tasks and knowledge snapshots.

Primary endpoints:

1. Severe Engineering Semantic Error Rate
2. Unsupported Claim Rate
3. Epistemic Violation Rate
4. Final Semantic Violation Rate
5. Trace Coverage
6. Claim Coverage

Binary per-task error indicators use McNemar tests. Paired per-task error
counts/rates use Wilcoxon signed-rank tests plus paired bootstrap 95% confidence
intervals. Three-method omnibus comparisons use Friedman tests where applicable,
with Holm-corrected post-hoc paired comparisons. Small-count comparisons use
exact methods when appropriate. Report effect sizes, 95% confidence intervals,
and exact n; do not report p-values alone.
