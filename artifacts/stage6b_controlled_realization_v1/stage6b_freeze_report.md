# Stage6B Freeze Decision

Decision: FROZEN

Stage6B is frozen as `stage6b-controlled-realization-v1-frozen` after independent replay and audit of the formal DeepSeek 15-task real-model smoke. No new real API request was sent during this freeze audit.

## 1. Git baseline

- Branch: `stage6b-controlled-realization`
- Baseline HEAD before freeze commit: `0119c2408a5ef1f86823287aec89f70ad507a6b2`
- Baseline tag: `stage6a-fact-lock-evidence-pack-v1-frozen`
- Working tree dirty at artifact generation: `True` because Stage6B source, tests, and freeze artifacts were staged as the freeze candidate.

## 2. Stage6B change scope

- `pyproject.toml`: STAGE6B_SOURCE_OR_TEST; allowed=true;
- `scripts/build_stage6b_controlled_realization.py`: STAGE6B_SOURCE_OR_TEST; allowed=true;
- `scripts/run_stage6b_real_model_smoke.py`: STAGE6B_SOURCE_OR_TEST; allowed=true;
- `src/tbm_twin/realization/build_stage6a.py`: STAGE6A_NEGATIVE_AUDIT_SCOPE_FIX; allowed=true; Narrows Stage6A LLM negative audit source scan to Stage6A files; does not alter frozen Stage6A artifacts or FactLock semantics.
- `src/tbm_twin/realization/build_stage6b.py`: STAGE6B_SOURCE_OR_TEST; allowed=true;
- `src/tbm_twin/realization/providers/__init__.py`: STAGE6B_SOURCE_OR_TEST; allowed=true;
- `src/tbm_twin/realization/providers/base.py`: STAGE6B_SOURCE_OR_TEST; allowed=true;
- `src/tbm_twin/realization/providers/configured_llm.py`: STAGE6B_SOURCE_OR_TEST; allowed=true;
- `src/tbm_twin/realization/providers/deepseek_adapter.py`: STAGE6B_SOURCE_OR_TEST; allowed=true;
- `src/tbm_twin/realization/providers/openai_adapter.py`: STAGE6B_SOURCE_OR_TEST; allowed=true;
- `src/tbm_twin/realization/stage6b.py`: STAGE6B_SOURCE_OR_TEST; allowed=true;
- `src/tbm_twin/realization/stage6b_models.py`: STAGE6B_SOURCE_OR_TEST; allowed=true;
- `src/tbm_twin/realization/stage6b_smoke.py`: STAGE6B_SOURCE_OR_TEST; allowed=true;
- `tests/unit/stage6b_helpers.py`: STAGE6B_SOURCE_OR_TEST; allowed=true;
- `tests/unit/test_stage6b_grouping_rendering_plan.py`: STAGE6B_SOURCE_OR_TEST; allowed=true;
- `tests/unit/test_stage6b_presentation_and_abstention.py`: STAGE6B_SOURCE_OR_TEST; allowed=true;

`src/tbm_twin/realization/build_stage6a.py` is included intentionally as a Stage6A negative-audit scope fix: Stage6B adds real provider adapters under the realization package, so the Stage6A LLM-negative audit now scans Stage6A-specific files instead of the whole realization directory. It does not change frozen Stage6A FactLock outputs or Stage6A semantics.

Unexpected upstream semantic modifications: `0`.

## 3. Frozen upstream integrity

Frozen upstream hash issues: `0`.

The audit checks formal frozen directories with available hash manifests and records missing manifest cases separately without treating them as Stage6B semantic changes. Stage6B reads upstream frozen artifacts but does not rewrite Stage4, Stage5A, Stage5B, Stage5C, or Stage6A semantics.

## 4. Official formal run identity

- Execution ID: `stage6b_smoke_execution_93ce841716abf581304e740e`
- Provider/model: `deepseek` / `deepseek-v4-flash`
- Base URL: `https://api.deepseek.com`
- Execution protocol hash: `c6e2fd9bc8ca3fa37a3a07a3eff10e0da7233aea49bb8a4027f480e5b54e76cb`
- Execution protocol file SHA256: `b17f8c9bdfe520be21c47a48b811116aeed31d459244fd045dfe795d259f3d42`
- Task manifest hash: `c8b4e8d90e4d163dcf8f432a7c7ec79ecbbf947856eba3db38e23db4c4edd662`
- Prompt template hash: `e54f22ef559d61caf51d0d4021989c96c92f3b3e1dc2adb5e7a7a1dbf0c95e0e`
- Reasoning effort: requested/applied/supported = `none` / `none` / `True`
- Temperature/top_p/max_output_tokens/max_retries: `0.0` / `1.0` / `4096` / `0`

- provider: PASS
- model: PASS
- base_url: PASS
- reasoning_effort: PASS
- temperature: PASS
- top_p: PASS
- max_output_tokens: PASS
- max_retries: PASS
- execution_protocol_hash: PASS
- execution_protocol_file_sha256: PASS
- task_manifest_hash: PASS
- prompt_template_hash: PASS

## 5. Raw response completeness

- Frozen tasks: `15`
- Raw model outputs: `15`
- Attempt records: `15`
- Provider failure records: `0`
- Missing/duplicate/unexpected first attempts: `0`

- `stage6b_smoke_task_00`: raw=1, attempt=1, PASS
- `stage6b_smoke_task_01`: raw=1, attempt=1, PASS
- `stage6b_smoke_task_02`: raw=1, attempt=1, PASS
- `stage6b_smoke_task_03`: raw=1, attempt=1, PASS
- `stage6b_smoke_task_04`: raw=1, attempt=1, PASS
- `stage6b_smoke_task_05`: raw=1, attempt=1, PASS
- `stage6b_smoke_task_06`: raw=1, attempt=1, PASS
- `stage6b_smoke_task_07`: raw=1, attempt=1, PASS
- `stage6b_smoke_task_08`: raw=1, attempt=1, PASS
- `stage6b_smoke_task_09`: raw=1, attempt=1, PASS
- `stage6b_smoke_task_10`: raw=1, attempt=1, PASS
- `stage6b_smoke_task_11`: raw=1, attempt=1, PASS
- `stage6b_smoke_task_12`: raw=1, attempt=1, PASS
- `stage6b_smoke_task_13`: raw=1, attempt=1, PASS
- `stage6b_smoke_task_14`: raw=1, attempt=1, PASS

## 6. Raw -> parsed traceability

All 15 raw responses replay into strict JSON MinimalProviderPlan objects with no repair, no markdown stripping, no regex recovery, no field deletion, and no section/order correction.

Raw-to-parsed mutation count: `0`.

## 7. Parsed -> materialized traceability

All 15 parsed plans materialize with deterministic authoritative metadata. The model does not control pack ID/hash, task abstention view ID, contract hash, presentation policy version, plan ID, or plan hash.

Authoritative metadata/model-control issues: `0`.
Materialized plan hash mismatches: `0`.

## 8. Four interception case audit

The four intercepted plans are genuine raw-model section-order violations against the frozen product contract. They were not composed.

- `stage6b_smoke_task_04`: expected `geological_forecast;forward_attention;insufficiency`, model returned `forward_attention;geological_forecast`, decision `GENUINE_MODEL_CONTRACT_VIOLATION`
- `stage6b_smoke_task_07`: expected `operational_attention;geological_attention;coupled_attention;forward_attention;insufficiency`, model returned `geological_attention;coupled_attention;operational_attention;forward_attention`, decision `GENUINE_MODEL_CONTRACT_VIOLATION`
- `stage6b_smoke_task_10`: expected `operational_attention;geological_attention;coupled_attention;forward_attention;insufficiency`, model returned `geological_attention;coupled_attention;operational_attention`, decision `GENUINE_MODEL_CONTRACT_VIOLATION`
- `stage6b_smoke_task_11`: expected `geological_observed;geological_forecast;operational_attention;geological_attention;coupled_attention;insufficiency`, model returned `geological_forecast;geological_attention;operational_attention;coupled_attention`, decision `GENUINE_MODEL_CONTRACT_VIOLATION`

## 9. Validator correctness

False-positive validator interceptions: `0`.

Each intercepted plan contained a legal section subset but returned those sections in a sequence that disagreed with the frozen product contract. The validator did not invent missing sections or reject a valid optional subset.

## 10. Accepted plan audit

Accepted plan contract violations: `0`.

All 11 accepted plans satisfy required task units, section placement, section order, product type, omission policy, and deterministic plan hash checks.

## 11. Composition gate audit

Invalid plans composed: `0`.
Accepted plans not composed: `0`.
Composition gate issues: `0`.

The composer used deterministic CanonicalFactSentence / RealizationUnit content only. The model supplied plan structure, not engineering prose.

## 12. Final semantic audit

Final semantic violations: `0`.

The 11 composed outputs preserve numeric values, chainage/spatial scope, epistemic status, role semantics, indicator semantics, causation boundaries, and traceability. RAI/GRS/GRCI are not represented as probabilities, and mechanical response is not promoted into geological cause.

## 13. Post-audit reconciliation

Post-audit reconciliation issues: `0`.
Reported and recomputed post-audit pass count: `11`.
Reported and recomputed post-audit violation count: `0`.

## 14. Trace coverage

- Numerator: `358`
- Denominator: `358`
- Coverage: `1.0`
- Untraceable final facts: `0`

## 15. Accounting reconciliation

- task_count: recomputed `15`, reported `15`, expected `15`, PASS
- provider_request_attempt_count: recomputed `15`, reported `15`, expected `15`, PASS
- provider_transport_success_count: recomputed `15`, reported `15`, expected `15`, PASS
- provider_transport_failure_count: recomputed `0`, reported `0`, expected `0`, PASS
- real_api_request_attempt_count: recomputed `15`, reported `15`, expected `15`, PASS
- real_api_transport_success_count: recomputed `15`, reported `15`, expected `15`, PASS
- real_api_transport_failure_count: recomputed `0`, reported `0`, expected `0`, PASS
- parse_valid_count: recomputed `15`, reported `15`, expected `15`, PASS
- schema_valid_count: recomputed `15`, reported `15`, expected `15`, PASS
- plan_accepted_count: recomputed `11`, reported `11`, expected `11`, PASS
- validator_interception_count: recomputed `4`, reported `4`, expected `4`, PASS
- composition_count: recomputed `11`, reported `11`, expected `11`, PASS
- post_audit_pass_count: recomputed `11`, reported `11`, expected `11`, PASS
- post_audit_violation_count: recomputed `0`, reported `0`, expected `0`, PASS

Accounting reconciliation issues: `0`.

## 16. Raw-model violation taxonomy

- UNKNOWN_UNIT: 0
- OUT_OF_TASK_UNIT: 0
- DUPLICATE_UNIT_REFERENCE: 0
- REQUIRED_UNIT_OMISSION: 0
- INVALID_SECTION: 0
- INVALID_SECTION_ORDER: 4
- PRODUCT_TYPE_MISMATCH: 0
- SCHEMA_ERROR: 0
- PARSE_ERROR: 0

Final taxonomy: only `INVALID_SECTION_ORDER = 4` is non-zero.

## 17. Deterministic replay

Replay used saved raw responses only and made zero API calls.

- parsed_plans_diff: diff `0`, PASS
- materialized_plans_diff: diff `0`, PASS
- validation_diff: diff `0`, PASS
- composition_semantic_diff: diff `0`, PASS
- post_audit_diff: diff `0`, PASS

Deterministic replay issue count: `0`.

## 18. Tests / lint / mypy

- `python -m pytest -q --cache-clear`: 368 passed, 5 warnings in 79.46s
- `python -m pytest -q tests/unit/test_stage6b_*.py --cache-clear`: 37 passed in 5.76s
- `python -m ruff check .`: PASS
- `python -m ruff format --check .`: PASS
- `python -m mypy src`: PASS: no issues found in 135 source files

## 19. Freeze hard checks

- formal_run_exists: actual `1`, expected `1`, PASS
- formal_run_identity_mismatch: actual `0`, expected `0`, PASS
- task_manifest_hash_issue: actual `0`, expected `0`, PASS
- execution_protocol_hash_issue: actual `0`, expected `0`, PASS
- prompt_template_hash_issue: actual `0`, expected `0`, PASS
- missing_raw_attempt_count: actual `0`, expected `0`, PASS
- duplicate_task_attempt_count: actual `0`, expected `0`, PASS
- raw_to_parsed_mutation_count: actual `0`, expected `0`, PASS
- authoritative_metadata_model_control_count: actual `0`, expected `0`, PASS
- materialized_plan_hash_mismatch_count: actual `0`, expected `0`, PASS
- reported_validator_interception_count: actual `4`, expected `4`, PASS
- false_positive_validator_interception_count: actual `0`, expected `0`, PASS
- invalid_plan_composed_count: actual `0`, expected `0`, PASS
- accepted_plan_contract_violation_count: actual `0`, expected `0`, PASS
- accepted_plan_not_composed_count: actual `0`, expected `0`, PASS
- final_semantic_violation_count: actual `0`, expected `0`, PASS
- untraceable_final_fact_count: actual `0`, expected `0`, PASS
- trace_coverage: actual `1.0`, expected `1.0`, PASS
- post_audit_reconciliation_issue: actual `0`, expected `0`, PASS
- accounting_reconciliation_issue: actual `0`, expected `0`, PASS
- deterministic_replay_issue_count: actual `0`, expected `0`, PASS
- real_api_call_count_during_freeze_audit: actual `0`, expected `0`, PASS
- unexpected_upstream_semantic_modification_count: actual `0`, expected `0`, PASS
- frozen_upstream_hash_issue: actual `0`, expected `0`, PASS
- freeze_issue_count: actual `0`, expected `0`, PASS

## 20. Frozen artifact

Formal frozen artifact directory:

`artifacts/stage6b_controlled_realization_v1/`

It contains hash-bound copies of the official run metadata, frozen task manifest, prompt payloads, raw model outputs, parsed plans, materialized plans, validation records, composition results, post-audit records, independent audit CSVs, `method_version.json`, `freeze_manifest.json`, `stage6b_freeze_report.md`, and `file_hashes.sha256`.

The 11/15 result is only a first-attempt domain-plan acceptance rate in the frozen 15-task real-model smoke. It is not DeepSeek general accuracy, not system accuracy, and not proof of universal engineering correctness. All four invalid plans were blocked before composition; all 11 composed outputs passed deterministic post-realization audit.

Stage7 was not started.
