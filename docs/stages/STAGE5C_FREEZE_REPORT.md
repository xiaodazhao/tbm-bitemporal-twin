# Stage5C Freeze Report

## 1. Stage Goal

Stage5C freezes the Batch Claim Expressibility & Abstention Analysis for the
frozen Stage5B Claim universe. It measures which deterministic Claim
Opportunities are EXPRESSIBLE or ABSTAIN under the frozen Claim Contract,
epistemic boundaries, role constraints, metric availability, and upstream
provenance.

Stage5C does not use LLMs and does not generate natural-language engineering
conclusions. It does not judge geological truth, infer geological causes from
mechanical response, modify Stage5B decisions, or promote FORECAST evidence to
OBSERVED evidence.

## 2. Input Frozen Dependencies

- Stage4: `stage4-metrics-v1.1-frozen`
- Stage5A: `stage5a-claim-contract-v1.1-frozen`
- Stage5B: `stage5b-claim-builder-v1-frozen`
- Stage5B commit: `0be7a85ed6f5bcea31b82af9e1e8380037b3dd34`
- Stage5B artifact: `artifacts/stage5b_deterministic_claim_builder_v1/`
- Stage5C formal artifact: `artifacts/stage5c_claim_expressibility_analysis_v1/`

## 3. Implementation Summary

The Stage5C implementation is in `src/tbm_twin/claim_analysis/` and is run by
`scripts/run_stage5c_claim_expressibility_analysis.py`.

The loader consumes frozen Stage5B `ClaimOpportunity`, `ClaimProposal`,
`ClaimDecision`, materialized `TypedEngineeringClaim`, and abstention rows. It
also reads frozen Stage2 GeologicalEvidence, Stage3B bitemporal version lineage,
and Stage4 GRS/GRCI support metadata for audit-only attribution.

Stage5C is a deterministic descriptive analysis of frozen Claim opportunities
and decisions. It does not rebuild Claim opportunities, proposals, decisions, or
typed claims.

## 4. Frozen Universe

- Claim opportunities: 8679
- Proposals: 8679
- Decisions: 8679
- EXPRESSIBLE: 6279
- ABSTAIN: 2400
- Materialized claims: 6279
- Valid dates in Stage5B universe: 88
- Expressibility rate: 72.347%
- Abstention rate: 27.653%

The 72.347% expressibility rate is not model accuracy, risk-recognition
accuracy, or LLM correctness. It is the share of the frozen ClaimOpportunity
universe satisfying the frozen expression contract under the available evidence,
role constraints, and epistemic boundary.

The 27.653% abstention rate is not failure. It is a formal system output
covering source-value unavailability, context and role policy boundaries,
epistemic proof insufficiency, and metric unavailability.

## 5. Claim-Type Expressibility

| Claim Type | Opportunities | EXPRESSIBLE | ABSTAIN |
| --- | ---: | ---: | ---: |
| OPERATIONAL_RESPONSE_ATTENTION | 1375 | 174 | 1201 |
| GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW | 190 | 190 | 0 |
| COUPLED_ATTENTION_REVIEW | 190 | 174 | 16 |
| FORWARD_GEOLOGICAL_ATTENTION | 305 | 200 | 105 |
| OBSERVED_GEOLOGICAL_CONDITION | 970 | 758 | 212 |
| FORECAST_GEOLOGICAL_CONDITION | 5649 | 4783 | 866 |

## 6. Abstention Taxonomy

| Reason | Count | Interpretation |
| --- | ---: | --- |
| UNKNOWN_SOURCE_VALUE | 1078 | Source evidence exists, but the source value is UNKNOWN or unavailable. |
| CONTEXT_ONLY_ROLE | 880 | Context-only state role is outside standalone claim expression. |
| STATE_ROLE_NOT_ALLOWED | 305 | The Claim Contract disallows the claim type for the state role. |
| REQUIRED_EPISTEMIC_STATUS_MISSING | 105 | Required resolved epistemic proof is not materialized. |
| REQUIRED_METRIC_UNAVAILABLE | 32 | Upstream metric status is unavailable. |

Policy/context-bound abstentions are `1185 / 2400 = 49.375%` of all abstentions
when grouping `CONTEXT_ONLY_ROLE` and `STATE_ROLE_NOT_ALLOWED`.

## 7. Role-Level Analysis

Role-level tables are emitted in `state_role_expressibility.csv` and
`state_role_claim_type_matrix.csv`. These tables preserve the Stage5B frozen
universe and do not introduce fake zero-opportunity days to reconcile the
Stage3A 91-day state count with the Stage5B 88 valid-date Claim universe.

## 8. Source Epistemic vs Resolved Epistemic

Stage5C separates authoritative source epistemic status from decision
resolved-support status:

- `authoritative_source_epistemic_status` comes from frozen Stage2
  GeologicalEvidence.
- `decision_resolved_epistemic_status` comes from Stage5B
  `ClaimDecision.resolved_support_refs`.

UNKNOWN early abstentions therefore keep their source epistemic status while the
decision resolved status remains `MISSING_NOT_MATERIALIZED`.

Audit results:

- OBSERVED opportunities: 970; source OBSERVED: 970; source missing: 0
- FORECAST opportunities: 5649; source FORECAST: 5649; source missing: 0
- UNKNOWN_SOURCE_VALUE: 1078
- UNKNOWN with FORECAST source: 866
- UNKNOWN with OBSERVED source: 212
- UNKNOWN misclassified as source MISSING: 0
- FORECAST promoted to OBSERVED: 0
- OBSERVED materialized without OBSERVED proof: 0

## 9. Revision Lineage Analysis

Revision direction uses frozen Stage3B `version_number` and
`supersedes_bitemporal_version_id`, never lexical ordering of
`bitemporal_version_id`.

- Revision chains: 53
- Legacy lexical direction disagreements: 24
- Authoritative direction errors: 0
- Supersession mismatches: 0

Fixed reversed-ID case:

- Base state: `state_version_ed221b03b2e40479c7ba42c2`
- v1: `bitemporal_version_72e60100df4f5a214d5119f4`, `version_number=1`
- v2: `bitemporal_version_43194bb14cfc647ee8b539c8`, `version_number=2`
- v2 supersedes v1
- Opportunity delta: +8
- EXPRESSIBLE delta: +7
- ABSTAIN delta: +1

## 10. Stable Logical Matching Design

Revision comparison keys identify the same logical Claim slot rather than a
version-specific wrapper object.

Metric-backed Claim keys include claim type, base Stage3A state version, valid
date, cell, state role, source kind, and metric name. They exclude bitemporal
version ID, transient metric IDs, metric value, metric status, builder version,
and generated time.

Geological-condition keys include claim type, base Stage3A state version, valid
date, cell, state role, source kind, source evidence ID, and attribute name. They
exclude normalized value so value changes can be detected as changes.

Audit results:

- Matched logical pairs: 435
- OPPORTUNITY_ADDED: 540
- OPPORTUNITY_REMOVED: 0
- Comparison-key collisions: 0
- Transition reconciliation diff: 0
- Wrapper-ID-only false semantic support change: 0

## 11. Revision Chain Summary

Transition rows: 975

| Transition | Count |
| --- | ---: |
| OPPORTUNITY_ADDED | 540 |
| UNCHANGED_EXPRESSIBLE | 288 |
| UNCHANGED_ABSTAIN | 84 |
| ABSTAIN_TO_EXPRESSIBLE | 27 |
| RESOLVED_SUPPORT_CHANGED | 26 |
| CLAIM_VALUE_CHANGED | 10 |

The 540 added opportunities are all geological-condition Claims:

- FORECAST_GEOLOGICAL_CONDITION: 504
- OBSERVED_GEOLOGICAL_CONDITION: 36
- Added metric Claims without authoritative basis: 0

By role:

- FORWARD_ATTENTION_CELL: 408
- DAILY_REVIEW_CELL: 132

These are interpreted as later geological evidence producing revised epistemic
state support for additional geological Claim opportunities, not as proof that
the prior knowledge state was wrong.

## 12. Manually Reviewed Cases

`manual_revision_case_audit.csv` contains 13 deterministic representative cases
covering:

1. `ABSTAIN_TO_EXPRESSIBLE`
2. `CLAIM_VALUE_CHANGED`
3. `RESOLVED_SUPPORT_CHANGED`
4. `OPPORTUNITY_ADDED`
5. forecast geological additions
6. observed geological additions
7. GRS revision
8. GRCI revision
9. largest opportunity delta chain
10. small positive opportunity delta chain
11. lexical ordering conflict with authoritative ordering
12. `UNKNOWN_SOURCE_VALUE`
13. `CONTEXT_ONLY_ROLE` / `STATE_ROLE_NOT_ALLOWED`

All sampled rows preserve the same provenance route:

`Stage5B ClaimOpportunity/Proposal/Decision -> Stage3B lineage -> Stage2
GeologicalEvidence or Stage4 metric support metadata`.

Each sampled transition was traceable to frozen upstream objects. No sampled
transition required text heuristics, regenerated decisions, or lexical version
ordering.

## 13. Determinism

`stage5c_determinism_audit.csv` rebuilds the analysis twice and compares
semantic outputs while ignoring non-semantic file hash material.

- Semantic diff: 0

## 14. Tests

Fresh test run with cache cleared:

- `python -m pytest -q --cache-clear`: 298 passed, 5 warnings

Stage5C-only test run:

- `python -m pytest -q tests/unit/test_stage5c_*.py --cache-clear`: passed

Quality gates:

- `python -m ruff check .`: passed
- `python -m ruff format --check .`: passed
- `python -m mypy src`: passed

## 15. Hard Checks

`stage5c_hard_check.csv`:

- Rows: 38
- Failed rows: 0
- `issue_count`: 0

Hard checks cover upstream count reconciliation, rate integrity, abstention
reason reconciliation, epistemic boundary preservation, revision direction,
supersession, comparison-key collisions, transition reconciliation, wrapper ID
false support changes, unknown factual materialization, metric null-to-zero
interpretation, Stage4/5A/5B immutability, LLM absence, natural-language
generation absence, and determinism.

## 16. Known Limitations

Stage5C does not prove engineering correctness, human geological correctness,
real-world safety, cross-project generalizability, or superiority over all
baselines. It proves internal consistency, contract compliance, deterministic
expressibility behavior, bitemporal revision consistency, and abstention
structure for the frozen Stage5B universe.

Stage5C is not an Evidence Pack generator and does not realize textual
engineering Claims. Those belong to Stage6.

## 17. Frozen Boundaries

Frozen method version:
`stage5c_claim_expressibility_analysis_v1_frozen`

Schema version:
`stage5c_claim_expressibility_analysis.v1`

Frozen artifact:
`artifacts/stage5c_claim_expressibility_analysis_v1/`

No Stage4, Stage5A, or Stage5B frozen semantics were modified.

## 18. Next Stage

Stage6 is next: Controlled Claim Realization / Fact Lock / Evidence Pack / LLM
realization. Stage6 must consume frozen Stage5C as analysis context and must not
rewrite Stage5B admissibility decisions.
