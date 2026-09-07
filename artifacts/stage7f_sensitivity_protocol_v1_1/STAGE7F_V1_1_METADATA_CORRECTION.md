# Stage7F-A v1.1 Metadata Correction

## Corrected GRCI description

The v1 inventory incorrectly described GRCI as `sqrt(RAI * GRS)`. The frozen config and
implementation define `RAI * GRS` with operator `NONPROBABILISTIC_CONJUNCTIVE_PRODUCT`,
available only for `DAILY_REVIEW_CELL_ONLY` when both inputs are available.

## Corrected GRS description

The v1 inventory incorrectly summarized all GRS aggregation as a maximum. The frozen method
uses `max_mapped_attention` within each geological dimension and
`mean_non_null_dimension_attention` across available dimensions.

No parameter, arm, baseline, metric implementation, Claim Contract, upstream artifact, or
experimental outcome changed. This correction only replaces two non-tunable metadata strings
with config-backed method semantics.
