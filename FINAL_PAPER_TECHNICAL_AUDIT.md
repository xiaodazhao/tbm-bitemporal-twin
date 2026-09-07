# FINAL PAPER TECHNICAL AUDIT

## 1. Executive conclusion

**PASS WITH PAPER CORRECTIONS**

The frozen machine results reconcile with authoritative objects, bounded GRS mapping
perturbations cause no claim-decision migration, and no formal experiment must be rerun.
The paper must correct two descriptions: the 44 entries are the **frozen reviewed mapping
registry used by role-selected state snapshots**, not all raw Evidence values occurring in
those source fields; and the legacy internal field
`daily_excavated_scope` is a **cell-aligned review scope**, not actual daily excavation.

## 2. Repository and freeze identity

- Branch: `paper-final-technical-audit`
- HEAD at audit start: `0b6aa8237d3543904590b8df78d0fb272144ab70`
- HEAD tags: `paper-writing-evidence-bundle-v1.1-frozen`
- Working tree dirty: `True` (pre-existing untracked paper/audit
  packages plus this audit branch's outputs)
- Python: `3.13.5`
- Dependencies: `pyproject.toml; no lock file present`
- Frozen mapping version: `stage4a2_bitemporal_state_metrics_v1_family_rai_ordinal_grs`
- Stage7B model/provider: `deepseek-v4-flash` / `deepseek`

## 3. Paper-number reconciliation

| metric | paper expected | recomputed | match | authoritative source |
|---|---:|---:|---|---|
| `evidence.plc_observations` | 328217 | 328217 | True | `artifacts/stage2_plc_operational_freeze_v2/normalized_observations/*.parquet` |
| `evidence.excavation_events` | 1119 | 1119 | True | `artifacts/stage2_plc_operational_freeze_v2/excavation_episodes.jsonl` |
| `evidence.mechanical` | 5595 | 5595 | True | `artifacts/stage2_plc_operational_freeze_v2/response_evidence.jsonl` |
| `evidence.geological_documents` | 223 | 223 | True | `artifacts/stage2_geology_v2_freeze_candidate/geological_documents.jsonl` |
| `evidence.geological_total` | 659 | 659 | True | `artifacts/stage2_geology_v2_freeze_candidate/primary_geological_evidence.jsonl` |
| `evidence.geological_observed` | 278 | 278 | True | `artifacts/stage2_geology_v2_freeze_candidate/primary_geological_evidence.jsonl` |
| `evidence.geological_forecast` | 381 | 381 | True | `artifacts/stage2_geology_v2_freeze_candidate/primary_geological_evidence.jsonl` |
| `evidence.source_spans` | 4713 | 4713 | True | `artifacts/stage2_geology_v2_freeze_candidate/source_spans.jsonl` |
| `state.cells` | 156 | 156 | True | `artifacts/stage3a_initial_epistemic_state_v1_1/construction_state_cells.jsonl` |
| `state.initial_versions` | 1322 | 1322 | True | `artifacts/stage3a_initial_epistemic_state_v1_1/initial_construction_state_versions.jsonl` |
| `state.total_bitemporal_versions` | 1375 | 1375 | True | `artifacts/stage3b_bitemporal_epistemic_state_v1_1/bitemporal_state_versions.jsonl` |
| `state.revision_events` | 53 | 53 | True | `artifacts/stage3b_bitemporal_epistemic_state_v1_1/knowledge_revision_events.jsonl` |
| `metric.rai_available` | 174 | 174 | True | `artifacts/stage4_bitemporal_state_metrics_v1_1/state_rai.jsonl` |
| `metric.grs_available` | 1211 | 1211 | True | `artifacts/stage4_bitemporal_state_metrics_v1_1/state_grs.jsonl` |
| `metric.grci_available` | 174 | 174 | True | `artifacts/stage4_bitemporal_state_metrics_v1_1/state_grci.jsonl` |
| `claim.total_opportunities` | 8679 | 8679 | True | `artifacts/stage5b_deterministic_claim_builder_v1/claim_opportunities.jsonl` |
| `claim.allow` | 6279 | 6279 | True | `artifacts/stage5b_deterministic_claim_builder_v1/claim_decisions.jsonl` |
| `claim.reject` | 2400 | 2400 | True | `artifacts/stage5b_deterministic_claim_builder_v1/claim_decisions.jsonl` |

Closure checks: allow + reject = total is `True`;
abstention reasons close to rejected decisions is `True`.

## 4. GRS mapping audit

- Frozen unique mapping entries: **44**.
- Numeric / reviewed-unmappable: **36 / 8**.
- Frozen mapping entries observed in data: **44**.
- Values in the same configured source fields but outside the registry: **11** unique, **219** occurrences.
- Unmapped values entering formal frozen snapshot scoring: **0**.
- Per-value engineering rationale recorded: **0**; ordering labels exist,
  but detailed rationale is `RATIONALE_NOT_RECORDED`.
- Registry: `supplementary/grs_mapping_registry.csv` and `.md`.

The paper may say “44 frozen reviewed mapping entries.” It should not say “all structured
geological values were mapped.”

## 5. GRS mapping sensitivity

- One-step alias-group arms: **38**.
- Arms with numerical GRS change: **38**.
- Maximum absolute GRS delta: **0.333333333333**.
- Claim-decision migrations: **0**.
- Arms changing revision-event conclusions: **2**.

This demonstrates claim-level stability only under the tested bounded perturbations; it does
not establish scientific validity of the ordinal mapping. Two arms each change one event's
binary “GRS changed” classification while leaving every Claim decision unchanged; the frozen
36/53 result therefore remains the primary endpoint. In both affected arms the same event
changes from “GRS changed” to “unchanged,” so the arm-level count is 35/53.

## 6. Spatial semantic audit

The event footprint, trusted daily PLC range, aligned review scope, forward scope, claim
scope, and FactLock scope are separate in the formal chain. **No frozen-output true violation
was detected by the targeted scan** (`true_violation_count=0`).
`0` hits require manual paper wording review.
The internal name `daily_excavated_scope` is misleading: in all relevant states it is generated
with ten-metre alignment and must be described as the daily review scope. See
`audit/spatial_semantics_lineage.md`.

## 7. Bitemporal integrity audit

Stage3B contains 53 authoritative revision events with predecessor IDs, non-overlapping
knowledge intervals, and materialized as-of snapshots. Stage7D recomputation reports 53/53
events with a claim spatial or admissibility effect. Geological epistemic status remains on
the source Evidence object: later role changes do not promote FORECAST to OBSERVED.

## 8. Claim-admissibility integrity

Stage5B has 8,679 decisions and closes exactly to 6,279 EXPRESSIBLE plus 2,400 ABSTAIN.
Only EXPRESSIBLE decisions are materialized. Stage6A FactLocks retain resolved authoritative
support, spatial containment, qualifiers, and missing values. Mechanical response is not used
as geological cause, and GRCI remains a non-probabilistic, non-causal attention product.

## 9. 20 m resolution failure mechanism

The 20 m arm has **90** date-cell role conflicts across
**57** cell identities, plus
**23** point and
**76** interval failures. Coarse cells cross
native review/forward/background boundaries while the model requires one support role per cell.
This is a spatial aggregation validity limit, not a hidden metric formula bug. See
`audit/spatial_resolution_failure_analysis.md`.

## 10. Reproducibility status

The paper's machine counts can be reconstructed from frozen objects without an API call.
`441` manifest entries were checked; unexpected hash issues:
**0**. Stage7E corrected summaries explicitly supersede the historical
numeric-tokenizer false positives, and the result manifest points only to the corrected endpoint.

Quality gates passed: 9/9 audit invariants, 687/687 full tests, Ruff check and format, and Mypy over 153 source files. 5 warnings are third-party SWIG deprecations.

## 11. Files generated

- `scripts/audit_final_paper_technical.py`
- `tests/unit/test_final_paper_technical_audit.py`
- `supplementary/grs_mapping_registry.csv|json|md`
- `supplementary/grs_unmapped_relevant_values.csv`
- `supplementary/grs_mapping_sensitivity.csv|md`
- `supplementary/grs_mapping_sensitivity_revision_audit.csv`
- `audit/repository_freeze_identity.json`
- `audit/audit_command_log.md`
- `audit/quality_gate_results.json`
- `audit/freeze_hash_validation.csv`
- `audit/final_technical_hard_check.csv`
- `audit/spatial_semantics_lineage.md`
- `audit/spatial_semantics_text_scan.csv`
- `audit/spatial_resolution_failure_analysis.md`
- `audit/spatial_resolution_20m_examples.json`
- `paper_artifacts/paper_results_manifest.json|md`
- `FINAL_PAPER_TECHNICAL_AUDIT.md`

## 12. Changes made

Only the audit script, deterministic tests, supplementary exports, paper manifest, and this
report were added. **Formal pipeline unchanged.** No frozen result, parser, metric formula,
claim contract, prompt, raw model response, or tag was modified.

## 13. Remaining work before submission

1. Human evaluation remains deferred.
2. Correct manuscript wording for the 44-entry mapping registry and the cell-aligned review scope.
3. Package the generated registry, sensitivity table, lineage, and results manifest as supplement.
