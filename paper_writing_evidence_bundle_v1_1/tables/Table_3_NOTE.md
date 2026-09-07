# Table 3 主实验

- **统计单位**：method-condition / check instance
- **分母**：每方法 48 planned tasks
- **冻结来源**：`Stage7B/7C`
- **使用说明**：该 CSV 是论文制表数据，不替代权威 frozen artifact。
- **当前机器端点只支持**：execution availability、fail-closed behavior，以及 P 的 deterministic post-audit。
- **P post-audit 分母**：45 个通过计划验证并形成最终输出的任务，结果为 45/45 PASS。
- **不能用于比较**：engineering semantic correctness、factual correctness、usefulness 或 misleading risk。
- **人工语义状态**：B0、B1、P 均为 `DEFERRED_TO_HUMAN`。
- **关键边界**：输出可用率和结构拦截不能解释为工程语义 accuracy，也不能据此推断 P 的语义优越性。
