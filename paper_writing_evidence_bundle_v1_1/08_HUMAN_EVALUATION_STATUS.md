# 人工评价状态

当前仍有两个独立的人工评价工作包未完成。论文可以保留明确占位，但不得生成或推测任何分数。

## A. B0/B1/P 工程语义人工评价

已冻结 `stage7c_human_eval_packet_v1_1`：48 tasks、144 conditions、141 个实际文本；P 的 3 个 fail-closed 条件保留在 48-task 可用性分母，但不进入文本质量包。评价采用 method-label-blinded 设计、两位评审者、12 个校准条目和两套随机批次。

待评端点：

- E1 unsupported claim
- E5 forecast factualization
- E6 observed without proof
- E7 hindsight leakage
- E8 role boundary violation
- E9 mechanical-geological causation
- E10 attention-probability promotion
- E11 unknown-to-normal
- E12 other admissibility violation
- overall semantic error
- factual support
- epistemic correctness
- engineering usefulness
- clarity
- misleading risk

**状态**：`DEFERRED_TO_HUMAN`。

## B. Human Claim Gold

目的：比较人类工程判断与 deterministic Claim Contract 在主张准入上的一致性，识别合同过严、过松或认识边界分歧。

**状态**：`NOT_YET_EXECUTED`。

## 写作规则

正文、表格和摘要中不得用 0、N/A 或估计值替代上述结果。可写“协议与盲评包已冻结，人工结果待补”，并在结果和局限性中显式保留占位。
