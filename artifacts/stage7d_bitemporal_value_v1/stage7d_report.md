# Stage7D Bitemporal Value Experiment Report

## Design

The frozen 48 Stage7A tasks were evaluated under exact-as-of and final-history
state binding. The only ablated variable is knowledge-time filtering.

## Primary results

- Affected tasks: 0 / 48
- Affected state bindings: 0 / 201
- Paired Claim decision changes: 0 / 1341
- Hindsight-enabled Claims: 0 / 1341
- Newly enabled observed Claims: 0
- Metric changes: {"GRCI": 0, "GRS": 0, "RAI": 0}

## Claim transition matrix

- EXPRESSIBLE → EXPRESSIBLE: 1022
- EXPRESSIBLE → ABSTAIN: 0
- ABSTAIN → EXPRESSIBLE: 0
- ABSTAIN → ABSTAIN: 319
- Opportunity added: 0
- Opportunity removed: 0

## Secondary results

- Later evidence count: 0
- Median evidence delay: None days
- Unknown → known transitions: 0

## Frozen-sample null result

The zero primary effect is a valid result. For all 201 task-cell bindings, the
frozen Stage7A `knowledge_as_of` boundary already selected the latest
authoritative state version. The experiment did not move the boundary, resample
tasks, or change contracts to manufacture an effect.

The Stage7A binding manifest contains 105 opportunity IDs
outside the corresponding product slice because its frozen manifest unioned
all active abstentions. Stage7D preserves that manifest and separately
reconciles the task-scoped Claim universe used by both experimental arms.

## Corpus-level descriptive context

- Bitemporal state versions: 1375
- Revision chains: 53
- Dates with revisions: 14
- Cells with revisions: 51
- GRS-changing chains: 36
- GRCI-changing chains: 1
- RAI-changing chains: 0

## Deterministic cases

- No affected task exists in the frozen sample; no case was fabricated.

## Interpretation boundary

Knowledge revision is normal. The value of bitemporal state is preserving both
what was known then and what became known later. RAI, GRS, and GRCI remain
non-probabilistic attention indices. This single-project experiment does not
prove cross-project generalization.

API calls: 0. LLM calls: 0.
