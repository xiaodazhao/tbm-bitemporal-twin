# Stage6A Freeze Report

## 1. Stage Goal

Stage6A freezes the deterministic realization boundary between frozen Stage5B/Stage5C claim admissibility outputs and any future controlled realization. It projects each EXPRESSIBLE `TypedEngineeringClaim` into one immutable `LockedEngineeringFact`, preserves ABSTAIN records as non-facts, builds controlled Evidence Packs, and binds future surface realization to a machine-readable Rendering Contract.

Stage6A does not use LLMs and does not generate natural-language engineering conclusions.

## 2. Frozen Upstream

- Stage5B artifact: `artifacts/stage5b_deterministic_claim_builder_v1/`
- Stage5C artifact: `artifacts/stage5c_claim_expressibility_analysis_v1/`
- Stage5C frozen commit/tag baseline: `89bae5ca37c8802fcec6b3f53c36083a4328427f`, `stage5c-claim-expressibility-v1-frozen`
- Current source branch during freeze audit: `stage6a-fact-lock-evidence-pack`
- Source base commit before Stage6A commit: `89bae5ca37c8802fcec6b3f53c36083a4328427f`
- Upstream hash issue count: 0
- Stage5C frozen method check issue: 0

## 3. FactLock Model

`LockedEngineeringFact` is an immutable deterministic projection of a single EXPRESSIBLE typed claim. Its identity and `lock_hash` bind claim identity, time, state, cell, spatial scope, modality, value, qualifiers, authoritative support, trace references, source contract metadata, and the rendering boundary fields `allowed_rendering_semantics` and `prohibited_transformations`.

## 4. Claim Reconciliation

- EXPRESSIBLE claims consumed: 6279
- ABSTAIN records preserved as non-facts: 2400
- FactLocks generated: 6279
- FactLocks from ABSTAIN: 0
- Missing FactLocks: 0
- Orphan FactLocks: 0

## 5. Semantic Integrity

- Semantic issue count: 0
- Claim value drift: 0
- Modality drift: 0
- Spatial scope drift: 0
- Qualifier drop: 0
- Support drift: 0
- Trace loss: 0

## 6. Rendering-Boundary Locking

FactLock hashes bind both allowed and prohibited rendering semantics. Tampering with forecast/observed modality, attention probability semantics, operational-geology causation, or rendering-boundary lists invalidates validation or changes the bound hash.

## 7. Rendering Contract

- Contract ID: `stage6a_controlled_rendering_contract_v1_frozen`
- Contract hash: `f3f6920d86d20c4f1737e2a30866b1e79478538c6eba5b8e912a1f41e24fa92e`
- Schema version: `stage6a_fact_lock_evidence_pack.v1`
- Contract hash validation issue: 0

The contract allows only ordering, compatible merging, connective wording, structure, and explicit evidence-insufficiency statements. It forbids inventing values, changing units, expanding spatial/temporal scope, promoting forecast to observed, promoting unknown to normal, treating attention as probability, inferring geological cause from mechanical response, and using external knowledge for engineering claims.

## 8. Contract Hashing

The hash is recomputed from canonical `schema_version`, `may`, `must`, `must_not`, and `claim_type_policies`. The Stage6A tests verify that modifying `must_not` or a claim policy changes the hash, and that preserving `contract_id` while mutating content fails validation.

## 9. Evidence Pack

- Full pack ID: `evidence_pack_f4e9d5a9b329f00ccd6809f7`
- Locked facts in full pack: 6279
- Pack boundary issue count: 0
- Non-FactLock authoritative facts: 0
- Raw PLC exposure: 0
- ABSTAIN materialized as fact: 0

## 10. Pack Hashing

Pack hash binds task context, slice specification, selected `fact_lock_id`, selected `lock_hash`, abstention summary, and rendering contract hash.

- `P1_CLAIM_VALUE_CHANGE`: detected=true, status PASS
- `P2_MODALITY_CHANGE`: detected=true, status PASS
- `P3_SPATIAL_SCOPE_CHANGE`: detected=true, status PASS
- `P4_REQUIRED_QUALIFIER_CHANGE`: detected=true, status PASS
- `P5_RENDERING_BOUNDARY_CHANGE`: detected=true, status PASS
- `P6_RENDERING_CONTRACT_CONTENT_CHANGE`: detected=true, status PASS
- `P7_SLICE_SPEC_CHANGE`: detected=true, status PASS

## 11. Product Slicing

- `all`: 6279 facts, status PASS
- `daily_review`: 3929 facts, status PASS
- `forward_attention`: 2350 facts, status PASS
- `metric_review`: 738 facts, status PASS
- `daily_review+valid_date`: 28 facts, status PASS
- `metric_review+forecast_claim_type`: 0 facts, status PASS
- `daily_review+cell_id`: 41 facts, status PASS
- `forward_attention+daily_review_state_role`: 0 facts, status PASS
- `metric_review_repeat`: 738 facts, status PASS

Product filters are AND-composed with date, claim type, cell and state-role filters. Empty intersections are valid.

## 12. Abstention Isolation

ABSTAIN rows are summarized only with `semantics = not_authoritative_fact`. They do not become `LockedEngineeringFact`, do not expose unsupported source values as facts, and cannot fill UNKNOWN or missing metric values.

## 13. Provenance

- Provenance failure count: 0
- Each FactLock preserves `source_claim_id`, `source_decision_id`, `source_opportunity_id`, `source_proposal_id`, `trace_refs`, and authoritative resolved support references.

## 14. Fixed Cases

- `F1_EXPRESSIBLE_METRIC_CLAIM_FACT_LOCK`: PASS
- `F2_ABSTAIN_CLAIM_NO_FACT_LOCK`: PASS
- `F3_FORECAST_MODALITY_PRESERVED`: PASS
- `F4_OBSERVED_PROVENANCE_PRESERVED`: PASS
- `F5_GRCI_POLICY_FORBIDS_PROBABILITY`: PASS
- `F6_RAI_POLICY_FORBIDS_GEOLOGICAL_CAUSE`: PASS
- `F7_REQUIRED_QUALIFIER_PRESERVED`: PASS
- `F8_SPATIAL_SCOPE_PRESERVED`: PASS
- `F9_DETERMINISTIC_ID_AND_HASH`: PASS
- `F10_TAMPERED_VALUE_VALIDATION_FAILS`: PASS
- `F11_TAMPERED_FORECAST_TO_OBSERVED_FAILS`: PASS
- `F12_ABSTENTION_NOT_AUTHORITATIVE_FACT`: PASS
- `F13_TAMPERED_PROHIBITED_TRANSFORMATION_DETECTED`: PASS
- `F14_TAMPERED_ALLOWED_SEMANTIC_DETECTED`: PASS
- `F15_RENDERING_BOUNDARY_CHANGE_INVALIDATES_HASH`: PASS
- `F16_RENDERING_BOUNDARY_MATCHES_DETERMINISTIC_POLICY`: PASS

Manual sample opening covered forecast, observed, RAI, GRS, GRCI and forward-attention facts:

- `forecast_fact`: `FORECAST_GEOLOGICAL_CONDITION`, modality `GEOLOGICAL_FORECAST`, status PASS
- `observed_fact`: `OBSERVED_GEOLOGICAL_CONDITION`, modality `GEOLOGICAL_OBSERVED`, status PASS
- `rai_fact`: `OPERATIONAL_RESPONSE_ATTENTION`, modality `DERIVED_ATTENTION`, status PASS
- `grs_fact`: `GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW`, modality `DERIVED_ATTENTION`, status PASS
- `grci_fact`: `COUPLED_ATTENTION_REVIEW`, modality `DERIVED_ATTENTION`, status PASS
- `forward_attention_fact`: `FORWARD_GEOLOGICAL_ATTENTION`, modality `DERIVED_ATTENTION`, status PASS

## 15. Determinism

- Determinism semantic diff: 0
- Rebuild mismatch: 0
- Duplicate FactLock IDs: 0
- Duplicate semantic facts: 0

## 16. Tests

Fresh test evidence is recorded in the final freeze decision. Required commands are `python -m pytest -q --cache-clear` and `python -m pytest -q tests/unit/test_stage6a_*.py --cache-clear`.

## 17. Quality Gates

Required gates are `python -m ruff check .`, `python -m ruff format --check .`, and `python -m mypy src`.

## 18. Hard Checks

- Hard check rows: 44
- Hard check issue count: 0

## 19. Claim Type Distribution

- `COUPLED_ATTENTION_REVIEW`: 174
- `FORECAST_GEOLOGICAL_CONDITION`: 4783
- `FORWARD_GEOLOGICAL_ATTENTION`: 200
- `GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW`: 190
- `OBSERVED_GEOLOGICAL_CONDITION`: 758
- `OPERATIONAL_RESPONSE_ATTENTION`: 174

## 20. Known Limitations

Stage6A proves deterministic FactLock construction, EXPRESSIBLE claim projection, abstention isolation, provenance preservation, semantic rendering-boundary locking, content-bound rendering contract hashing, controlled evidence exposure, deterministic pack slicing, and internal semantic integrity.

Stage6A does not prove that an LLM will obey the contract, that final natural language is correct, that a human engineer endorses the text, superiority over Direct LLM or RAG baselines, cross-project generalization, or engineering safety. Those are Stage6B/Stage7 concerns.

## 21. Frozen Boundaries

Frozen artifact path: `artifacts/stage6a_fact_lock_evidence_pack_v1/`.

Stage6A may be consumed by Stage6B only through `LockedEngineeringFact`, `ControlledEvidencePack`, and `RenderingContract`. Stage6B must not read raw PLC rows, raw geological source text, Stage5 proposal metadata as authoritative facts, or ABSTAIN payloads as facts.

## 22. Stage6B Next-Step Boundary

Next stage is Stage6B Controlled Claim Realization / LLM Realization. It must consume Stage6A packs under the rendering contract and must not change Stage5A, Stage5B, Stage5C, Stage4 metrics, or Stage6A FactLocks.
