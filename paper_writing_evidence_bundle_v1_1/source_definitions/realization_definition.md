# 受控实现定义

1. EXPRESSIBLE Typed Claim 确定性形成 FactLock。
2. FactLock 锁定事实值、主体、空间、认识限定、support 和禁止变换。
3. Evidence Pack 按任务切片绑定 FactLocks 与 RealizationUnits。
4. 大模型只提交 Minimal Plan：产品类型、section 顺序和既有 unit IDs。
5. 确定性 materializer 从 FactLock 生成规范句。
6. validator 拒绝未知 unit、重复、越权、省略必选项和非法 section 顺序。
7. composer 确定性组合；post-audit 检查覆盖、引用、数值、空间和认识状态。

因此 LLM 是表达规划器，不是事实计算器、风险判断器或权威文本源。非法计划 fail closed。
