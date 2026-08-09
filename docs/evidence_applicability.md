# Evidence Applicability

`EvidenceApplicabilityAssignment` 是证据对Episode的适用性记录，不是因果判断，也不是最终工程结论。

正式 Stage 2 后续入口使用：

```text
artifacts/stage2d_applicability_v2_1/
```

V2.1 的PLC空间输入来自：

```text
artifacts/stage2_plc_operational_freeze_v2/plc_daily_scope_v2.jsonl
```

旧 `artifacts/stage2d_applicability_v2/` 使用 raw PLC min/max 空间范围，
只保留作审计比较，不作为 Stage 3 输入。

Stage 2.1 使用集中决策函数 `combine_applicability`。硬排除优先于未知状态：未来才可用、空间明确不相交、空间范围无效、认识性质不兼容等情况直接返回 `NOT_APPLICABLE`，并记录主导 reason code。可用时间未知只在没有硬排除时返回 `UNDETERMINED`。

空间关系输出 `OVERLAP`、`ADJACENT`、`AHEAD`、`BEHIND`、`DISJOINT`、`INVALID` 或 `UNKNOWN`。空间重叠只表示空间范围相交，不表示地质原因导致机械响应。

证据类型规则：

- `FORECAST`：`OVERLAP` 可继续判断，`ADJACENT` 和配置距离内 `AHEAD` 只能限定使用，`BEHIND` 不能用于目标Episode的前方提示；
- `OBSERVED`：`OVERLAP` 可继续判断，`ADJACENT` 只能限定使用，`AHEAD` 不能作为该Episode已发生观测，`BEHIND` 若未覆盖目标Episode则不适用；
- `BACKGROUND`：只能作为背景上下文，结果为限定适用；
- `UNKNOWN`：默认 `UNDETERMINED`，除非存在硬排除。
