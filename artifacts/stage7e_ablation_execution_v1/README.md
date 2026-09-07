# Stage7E-B Frozen Ablation Execution

This directory records the one-shot execution of the 226 byte-frozen Stage7E-A
v1.2 requests. P-FULL is reused from Stage7B and A1 remains non-executable.

The execution uses DeepSeek `deepseek-v4-flash`, temperature 0, top_p 1,
reasoning effort none, 4096 maximum output tokens, and zero retries. Raw provider
responses are persisted before strict JSON parsing. No JSON repair, LLM repair,
prompt mutation, request mutation, or human semantic labeling is performed.

A2 is limited to 31 unavailable attention-metric contexts in 24 affected tasks.
Its result must not be generalized to every form of missing evidence or engineering
uncertainty. A3 evaluates 989 typed Claim-to-sentence mappings in 147 chunks. A4
evaluates free task-level realization from 1022 frozen FactLocks in 48 requests.
For A4, explicit chainages in a generated section are checked against the union of
the authoritative scopes of all FactLocks cited by that section; a multi-FactLock
section is not incorrectly compared against each cited scope in isolation.

Status: `EXECUTION_COMPLETE_DETERMINISTIC_AUDIT_PASS`

Human evaluation of forecast factification, unsupported causality, epistemic
drift, unknown-to-normal transformations, attention-to-probability transformations,
and engineering usefulness remains `DEFERRED_TO_HUMAN`.
