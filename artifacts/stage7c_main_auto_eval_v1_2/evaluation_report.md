# Stage7C.1 v1.1 Main Comparison Deterministic Automatic Evaluation

Status: PRE-HUMAN AUTOMATIC EVALUATION.

Stage7C.1 v1 is invalidated for quantitative interpretation by the evaluator-binding audit. This v1.1 artifact corrects deterministic binding logic and preserves v1 only as historical audit material.

No human semantic evaluation has been performed.
E1/E6/E8/E9/E11 remain pending.
No final semantic superiority claim is made.
No statistical significance test is performed.

## 1. Frozen Stage7B Facts

- Stage7B execution id: `stage7b_main_execution_3ae0f791811a2e711cb9f488`
- Tasks: 48
- Conditions: 144
- B0/B1/P conditions: 48/48/48
- Actual texts: 141
- B0/B1/P texts: 48/48/45
- Proposed no-valid-output conditions: 3
- Proposed intercepted tasks: stage7_main_task_022, stage7_main_task_026, stage7_main_task_042

## 2. Automatic Evaluation Protocol

The evaluator reads frozen Stage7B outputs and frozen Stage7A/Stage6A references.
It does not call LLMs, does not rerun Stage7B, and does not repair invalid Proposed plans.
Automatic rules are conservative: if a statement cannot be deterministically judged, it is marked `REQUIRES_HUMAN_REVIEW`.
Product contracts bound: all, daily_review, forward_attention, metric_review

## 3. Automatic Results

### B0_DIRECT_LLM
- E2: FAIL=0, PASS=20, HUMAN_REVIEW=3, NOT_APPLICABLE=1247
- E3: FAIL=0, PASS=21, HUMAN_REVIEW=0, NOT_APPLICABLE=1249
- E4: FAIL=0, PASS=59, HUMAN_REVIEW=25, NOT_APPLICABLE=1186
- E5: FAIL=2, PASS=65, HUMAN_REVIEW=137, NOT_APPLICABLE=1066
- E7: FAIL=0, PASS=0, HUMAN_REVIEW=0, NOT_APPLICABLE=1270
- E10: FAIL=0, PASS=116, HUMAN_REVIEW=42, NOT_APPLICABLE=1112
- E12: FAIL=0, PASS=0, HUMAN_REVIEW=17, NOT_APPLICABLE=1253
- E13: FAIL=0, PASS=0, HUMAN_REVIEW=0, NOT_APPLICABLE=1270
- E14: FAIL=0, PASS=0, HUMAN_REVIEW=1270, NOT_APPLICABLE=0
### B1_STRUCTURED_PROMPT_LLM
- E2: FAIL=0, PASS=22, HUMAN_REVIEW=10, NOT_APPLICABLE=2165
- E3: FAIL=0, PASS=29, HUMAN_REVIEW=0, NOT_APPLICABLE=2168
- E4: FAIL=0, PASS=126, HUMAN_REVIEW=10, NOT_APPLICABLE=2061
- E5: FAIL=0, PASS=120, HUMAN_REVIEW=180, NOT_APPLICABLE=1897
- E7: FAIL=0, PASS=0, HUMAN_REVIEW=0, NOT_APPLICABLE=2197
- E10: FAIL=0, PASS=217, HUMAN_REVIEW=7, NOT_APPLICABLE=1973
- E12: FAIL=0, PASS=0, HUMAN_REVIEW=68, NOT_APPLICABLE=2129
- E13: FAIL=0, PASS=0, HUMAN_REVIEW=0, NOT_APPLICABLE=2197
- E14: FAIL=0, PASS=0, HUMAN_REVIEW=2197, NOT_APPLICABLE=0
### P_PROPOSED
- E2: FAIL=0, PASS=164, HUMAN_REVIEW=0, NOT_APPLICABLE=1786
- E3: FAIL=0, PASS=160, HUMAN_REVIEW=0, NOT_APPLICABLE=1790
- E4: FAIL=0, PASS=702, HUMAN_REVIEW=0, NOT_APPLICABLE=1248
- E5: FAIL=0, PASS=483, HUMAN_REVIEW=181, NOT_APPLICABLE=1286
- E7: FAIL=0, PASS=0, HUMAN_REVIEW=0, NOT_APPLICABLE=1950
- E10: FAIL=0, PASS=247, HUMAN_REVIEW=0, NOT_APPLICABLE=1703
- E12: FAIL=0, PASS=0, HUMAN_REVIEW=33, NOT_APPLICABLE=1917
- E13: FAIL=0, PASS=1953, HUMAN_REVIEW=0, NOT_APPLICABLE=0
- E14: FAIL=0, PASS=1654, HUMAN_REVIEW=0, NOT_APPLICABLE=296

## 4. What Is NOT Evaluated Yet

- E1 unsupported claims remain pending for human semantic evaluation.
- E6 observed-without-proof remains pending.
- E8 role boundary violations remain pending.
- E9 mechanical-to-geological causation remains pending.
- E11 unknown-to-normal promotion remains pending.
- E12 is deferred unless a statement can be uniquely mapped to a formal Stage5B abstained Claim identity.

## Hard Checks

- Hard check failure count: 0