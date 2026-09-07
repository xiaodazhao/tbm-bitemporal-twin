# Claim Contract 摘要

Claim admissibility 是类型化、确定性的工程领域合同，不是关键词过滤器，也不是大模型自我判断。每类 Claim 定义允许的状态角色、所需认识状态、权威 support 类型、主体/空间绑定、指标可用性和禁止语义。

核心规则：

- OBSERVED Claim 必须有 OBSERVED 权威支持。
- FORECAST 不等于 OBSERVED，不能被升级。
- LOCAL_BACKGROUND 不能直接支持当前事实 Claim。
- metric unavailable 不等于 zero。
- UNKNOWN 不等于 NORMAL。
- attention 不等于 probability。
- mechanical response 与 geological evidence 共现不等于 causality。

全部条件满足输出 EXPRESSIBLE；否则输出 ABSTAIN 及确定性原因码。proposal metadata、自然语言文本和大模型输出均不能自我授权。
