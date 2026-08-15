# Stage7B Main Comparison Execution Decision

Decision: FROZEN

## 1. Frozen Stage7A.3 Binding
Stage7A v1.3 tag `stage7a-experimental-protocol-v1.3-frozen` at `6007afe7c1b1228d6638503afeba979ee2f66878` is bound. Main benchmark hash `e9ef8e3f9bd25f345f89f79dc753040e3bfc1f95e562902aea625a8e50334f6f` and as-of binding hash `92bdea500aef7bedb27e6133e92ec058f03ccfd48810e84aed11388838d12bc4` are verified.

## 2. Execution Protocol
Provider `deepseek`, model `deepseek-v4-flash`, base URL `https://api.deepseek.com`, temperature `0.0`, top_p `1.0`, reasoning effort `none`, max output tokens `4096`, max retries `0`.

## 3. Execution Manifest
Exactly `144` execution rows were frozen for `48` benchmark tasks, with one B0, one B1, and one P condition per task. Execution manifest hash: `75f2f9976b2cc85bdcf79a790baf07a8c623fa3fa24c2de16cdbdef9eafe34cc`.

## 4. Request Accounting
Real API request attempts: `144`. Transport successes: `144`. Transport failures: `0`. Duplicate provider attempts: `0`.

## 5. B0 Execution Results
B0 attempts: `48`. B0 outputs: `48`. Raw outputs are preserved without correction.

## 6. B1 Execution Results
B1 attempts: `48`. B1 outputs: `48`. Raw outputs are preserved without correction.

## 7. Proposed Execution Results
P attempts: `48`. P raw plans: `48`. P accepted/composed outputs: `45`.

## 8. Proposed Plan Validation
P validator intercepted `3` plans: `stage7_main_task_022`, `stage7_main_task_026`, and `stage7_main_task_042`, all for `INVALID_SECTION_ORDER`. Invalid plans were not composed and were not retried.

## 9. Proposed Composition/Post-Audit
P post-audit pass count: `45`. P post-audit failure count: `0`. Invalid plan propagated count: `0`.

## 10. Deterministic Replay
Replay made `0` API calls. P replay difference count: `0`.

## 11. Blind Evaluation Packet
Blind output packet rows: `141`. Method identity leak count: `0`.

## 12. Hard Checks
Hard check failure count: `0`.

## 13. Official Run Directory
`artifacts/stage7b_main_comparison_v1/runs/stage7b_main_execution_3ae0f791811a2e711cb9f488`

## 14. Commit/Tag
Execution commit `69507cc`; final artifact tag `stage7b-main-comparison-v1-frozen`.

## 15. Remaining Evaluation Work
Stage7C may now perform blind human evaluation, deterministic semantic analysis, and statistical comparison under the frozen Stage7 plan. No Stage7C evaluation is performed in this artifact.
