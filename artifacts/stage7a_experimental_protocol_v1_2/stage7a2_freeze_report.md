# Stage7A Experimental Protocol Freeze Report

Decision: READY_FOR_STAGE7B_MODEL_EXECUTION

Stage7A freezes the experimental protocol, true held-out benchmark, baseline
input serialization, prompt templates, proposed-method reference inputs,
annotation sampling plan, evaluation protocol, and computed hard checks. No real
LLM API was called.

## Frozen Inputs

- Stage6B tag: `stage6b-controlled-realization-v1-frozen`
- Stage6B commit: `ecf0fc47cd2f1f4a8bb5a962c32caaa7c5284550`
- Stage6B official smoke tasks: 15

## True Held-Out Construction

- Original eligible universe: 1416
- Exact smoke task exclusions inside reproduced universe:
  0
- Smoke content-overlap exclusions: 134
- Final true held-out universe: 1282

Main benchmark tasks have zero shared Stage6B smoke FactLock IDs and zero shared
Stage6B smoke RealizationUnit IDs.

## Knowledge-Time Binding

Benchmark tasks bind Stage3B bitemporal state versions, valid dates, and
knowledge boundaries from frozen `bitemporal_state_versions.jsonl`. Historical
database transaction logs are unavailable in the source project, so snapshots
record the explicit limitation `HISTORICAL_DATABASE_TRANSACTION_LOG_UNAVAILABLE`
where Stage3B used reconstructed local-date knowledge boundaries.

## Held-Out Benchmark

- Target size: 48
- Actual size: 48
- Manifest hash: `e9ef8e3f9bd25f345f89f79dc753040e3bfc1f95e562902aea625a8e50334f6f`
- Product distribution: {'all': 12, 'daily_review': 12, 'forward_attention': 12, 'metric_review': 12}
- Complexity distribution: {'HIGH': 4, 'LOW': 21, 'MEDIUM': 23}
- Epistemic distribution: {'ATTENTION_ONLY': 12, 'FORECAST_ONLY': 21, 'MIXED': 14, 'OBSERVED_ONLY': 1}

## Baselines

B0 and B1 receive identical BenchmarkEvidenceSnapshot-derived payloads. B1
differs only by prompt-level constraints. Neither B0 nor B1 receives Claim
decisions, FactLocks, RealizationUnits, validator results, or Stage6B
prohibited-transformation machinery.

## Proposed Method Reference

The proposed method is tied to the same frozen knowledge state and evidence
universe, with extra method-derived constraints represented separately in
`stage7_proposed_preclaim_reference.jsonl`. Its source-equivalence audit is
reconstructed from actual Stage6B FactLock, EvidencePack, and RealizationUnit
provenance rather than copied from the baseline pre-Claim snapshot.

## Hard Checks

- Issue count: 0

Stage7B may execute the frozen benchmark. Stage7A does not execute model calls,
human annotation, ablations, or Stage7B.
