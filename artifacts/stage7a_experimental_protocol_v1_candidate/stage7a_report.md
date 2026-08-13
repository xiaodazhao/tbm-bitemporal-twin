# Stage7A Experimental Protocol Report

Decision: READY_FOR_STAGE7B_MODEL_EXECUTION

Stage7A freezes the experimental protocol, held-out benchmark, baseline
definitions, ablation plan, automatic metrics, human annotation design,
statistical analysis plan, and API budget. No real LLM API was called.

## Frozen Inputs

- Stage6B tag: `stage6b-controlled-realization-v1-frozen`
- Stage6B commit: `ecf0fc47cd2f1f4a8bb5a962c32caaa7c5284550`
- Stage6B smoke tasks excluded from main benchmark: 15

## Eligible Universe

- Universe size: 1416
- Universe reconstruction: frozen Stage6A FactLocks and Stage5B abstentions are
  sliced with Stage6B `SliceSpec` semantics into date-level and cell-level
  product tasks. Every retained task must build a nonempty Stage6B bundle.

## Held-Out Benchmark

- Target size: 48
- Actual size: 48
- Manifest hash: `79616722d91904dd81c23241a41955dd6c4eac4c1572920fecbd93eea60be773`
- Product distribution: {'all': 23, 'daily_review': 13, 'forward_attention': 6, 'metric_review': 6}
- Complexity distribution: {'HIGH': 10, 'LOW': 14, 'MEDIUM': 24}
- Epistemic distribution: {'ATTENTION_ONLY': 6, 'FORECAST_ONLY': 24, 'MIXED': 15, 'OBSERVED_ONLY': 3}

## Methods

- B0_DIRECT_LLM: fair direct-generation baseline with the same knowledge-time
  evidence snapshot, without Claim decisions, FactLocks, or deterministic
  validators.
- B1_STRUCTURED_PROMPT_LLM: same snapshot plus natural-language safety rules,
  but no deterministic Claim admissibility or FactLock.
- P_PROPOSED: frozen bitemporal state -> Claim admissibility -> FactLock ->
  RealizationUnit -> LLM plan -> deterministic validator -> composer.

## Hard Checks

- Issue count: 0

Stage7B may execute the frozen benchmark. Stage7A does not execute model calls,
human annotation, ablations, or Stage7B.
