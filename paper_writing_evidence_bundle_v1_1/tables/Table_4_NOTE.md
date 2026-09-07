# Table 4 双时间

- **统计单位**：benchmark task 或 revision event
- **A. Benchmark alignment 分母**：48 个 held-out tasks；结果为 0/48 affected tasks。
- **B. Revision-event 分母**：53 个 authoritative revision events；RAI/GRS/GRCI 变化和 A→E 均以 53 为分母。
- **C. Transition-row 描述性 universe**：975 条 revision transition rows；其中 540 条是 OPPORTUNITY_ADDED。540 是新增机会计数，不是 revision-event 数，也不是全部 Claim opportunity 分母。
- **冻结来源**：`Stage7D`
- **使用说明**：该 CSV 是论文制表数据，不替代权威 frozen artifact。
- **主表处理**：不突出 `540/975 = 55.3846%`。如讨论该比率，必须标记为 `DESCRIPTIVE_TRANSITION_ROW_SHARE`，且明确 975 仅为 transition-row accounting universe。
- **关键边界**：不得混合 48-task benchmark、53-event revision census 和 975-row transition accounting 三种统计单位。
