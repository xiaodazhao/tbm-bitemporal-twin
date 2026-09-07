# 消融结果

## A1：Claim Gate bypass

最终状态为 `NOT_EXECUTABLE_ON_FROZEN_48_TASK_BENCHMARK`，原因 `NO_CONCRETE_GATE_BYPASS_CANDIDATES`。因此 A1 只能报告设计可执行性边界，不能报告模型性能，也不能把未执行当成零效应。

## A2：认识限定语移除

冻结目标为 31 个 sections，影响 24 个 tasks。该实验用于定位 FORECAST/OBSERVED/attention 等限定语在输出中的保护作用；最终语义影响仍需人工评价。

## A3：规划结构与映射

严格 primary parser：125/147 chunks 合法，828/989 Claim mappings 成功，32/45 tasks 完整。修正后的严格 numeric audit 为 149/149 exact、0 drift。

仅去除完整外层 Markdown JSON fence 的 secondary 离线解释：147/147 chunks、989/989 mappings、45/45 tasks；164/164 numeric exact、0 drift。它是 post-hoc secondary endpoint，不能替代严格 primary protocol compliance。

## A4：FactLock trace

总 FactLock trace coverage 为 848/1022（82.975%），遗漏 174；numeric FactLock coverage 为 162/171（94.737%），遗漏 9。已引用的 162 个 numeric FactLocks 全部 exact，numeric drift=0。

## 解释边界

`trace coverage != semantic correctness`，`numeric exact != full semantic correctness`。旧版记录的 149 个数值漂移来自 Unicode tokenizer bug，已被最终审计废弃，不得用于论文。
