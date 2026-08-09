# Response Evidence

`ResponseEvidence` 从PLC标准化观测和 `ExcavationEpisode.core_observation_refs` 构造。它默认只使用核心 `EXCAVATING` 观测，不使用Episode前后的STARTUP、COASTDOWN、IDLE或UNKNOWN上下文。

正式 Stage 2E V2 输出位于：

```text
artifacts/stage2_plc_operational_freeze_v2/
```

旧 `artifacts/stage2_plc_operational_freeze/` predates chainage regime
governance，只保留作审计比较，不作为 Stage 3 输入。

Stage 2.1 后，每条证据绑定一个Episode和一个机械响应通道。统计量不再拆成多条证据，而是保存在同一个 `ResponseStatistics` 对象中，包括样本数、有效样本数、缺失率、均值、中位数、分位数、最小值、最大值和变异系数。

单位语义保持保守：未由项目资料确认的单位输出 `unit=None` 和 `unit_confidence=UNVERIFIED`。响应统计可与透明的全局稳健baseline比较，输出偏离方向和强度，但不推断地质原因。

质量评价拆成三类：

- `measurement_quality`：通道缺失率、有效样本数、单位状态等；
- `temporal_scope_quality`：Episode边界截断、核心观测覆盖、内部中断等；
- `spatial_scope_quality`：Footprint一致性、0m推进冲突、空间范围不可用等。

0m推进冲突不会自动降低普通机械统计的 `measurement_quality`。它只限制进尺相关、空间归一化或每米归一化特征的空间质量。

V2 中 `raw_spatial_scope` 只用于来源审计；后续空间分配必须使用
`trusted_spatial_scope`。当 chainage regime 判为 `SUSPECT_SHIFTED_REGIME`、
`SUSPECT_JUMP` 或 `UNRESOLVED` 且无可信范围时，ResponseEvidence仍保留，
但其空间范围不得进入Stage 3空间分配。`RESTORED` 表示异常后重新建立可信性，
不是不可用标记。
