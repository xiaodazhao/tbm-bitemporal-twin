# Case B：2023-11-28 双时间认识修订

## PRE：当时所知

- valid date：2023-11-28
- Cell：`cell_7f60fb415d2265a3f3a9e060`，K1014230–K1014240
- version：`bitemporal_version_42fcba905c311194b662c06a`
- knowledge interval：2023-11-28 至 2023-11-29
- RAI：NO_CELL_LINKED_OPERATIONAL_RESPONSE / unavailable
- GRS：NO_MAPPED_GEOLOGICAL_ATTENTION_DIMENSION / unavailable
- GRCI：GRCI_NOT_DEFINED_FOR_FORWARD_ATTENTION / unavailable

在这个 knowledge time 上，系统不能提前使用次日才可获得的地质资料。

## 后到证据

2023-11-29，文档 `doc_1bccaf9b3397c0d25601b19d` 的三条 FORECAST Evidence（e0002/e0003/e0004）变为可用。它们保持 FORECAST，不因进入修订状态而升级为 OBSERVED。

## POST：修订后知识

- version：`bitemporal_version_d3a220b4d0ca6257cd8a2e17`
- GRS：unavailable -> 0.625
- RAI：仍 unavailable
- GRCI：仍因 FORWARD_ATTENTION 角色而不定义
- 新增 FORECAST_GEOLOGICAL_CONDITION opportunities：24
- FORWARD_GEOLOGICAL_ATTENTION：1 条 ABSTAIN -> EXPRESSIBLE
- UNCHANGED_ABSTAIN：1 条

## 解释

这不是“旧版本错误”，而是知识在 2023-11-29 增长。双时间版本同时保留 v1 当时不能说什么，以及 v2 新增何种权威资料后可以说什么。若只保留最终状态，就会产生 hindsight leakage。
