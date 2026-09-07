# 敏感性与有效性边界

## Cell size：5 m / 10 m / 20 m

- 5 m：`VALID_SENSITIVITY_ARM`，是相对 10 m 的主要更细分辨率比较。
- 10 m：`VALID_BASELINE`，156 个固定 Cell。
- 20 m：`COARSE_RESOLUTION_STRESS_TEST`，并已越过方法有效性边界。

20 m 产生 90 个 scope-role conflicts、23 个 point undercoverage 和 76 个 interval undercoverage；实际 evaluated exposure 为 14180 m，而 5/10 m 均为 13220 m。因此 20 m 的 per-100m 统计只能描述 coarse stress behaviour，不能与 5/10 m 当作等支持域 arms，也不得概括为跨全部分辨率的等稳健结论。

## RAI 历史充分性：20 / 30 / 40 observations

30 为 baseline。20 使 RAI/GRCI availability 各增加 2，并出现 4 个 ABSTAIN→EXPRESSIBLE；40 各减少 2，并出现 4 个 EXPRESSIBLE→ABSTAIN。共同可比较的 RAI/GRCI 值总体稳定，但 availability 边界会改变 Claim decision。

## RAI 饱和尺度：2 / 3 / 4

改变饱和尺度会改变 absolute RAI/GRCI values，但 rank consistency 高；Claim transitions=0，monotonicity violations=0。这表示当前合同不以数值阈值切换 Claim，不等于指标数值对参数完全不敏感。

## 最终结论

冻结结果没有执行 automatic robust/not-robust classification，也没有选择“最佳参数”。可支持的结论是：10 m 基线与 5 m finer arm 在原生质量门上有效；20 m 暴露出空间角色离散化的粗分辨率边界；history 参数影响早期可用性；saturation 参数影响数值尺度但未改变当前 Claim 决策。
