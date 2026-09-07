# 双时间结果

## A. 48-task benchmark alignment：零重叠诊断

Stage7D v1 将 48 个 held-out benchmark tasks 与 53 条 Stage3B revision chains 对齐，得到 affected tasks=0、later evidence=0。这个 null result 的含义是：当前 held-out 任务没有落在修订事件覆盖的 date-cell 上，因此主生成实验不能直接估计 revision-aware 与 final-state-only 的差异。

它不能解释为“双时间没有用”。把无重叠设计产生的零效应写成方法无效，会混淆实验支持域与研究机制。

## B. 全量 revision census

Stage7D v1.1 对全部 53 个 revision events 做 paired census，覆盖 14 个 valid dates、51 个 revised cells、72 条 later-evidence links 和 34 条唯一后到证据：

- RAI changed：0/53。地质后到证据不应反向改变机械响应指标。
- GRS changed：36/53（67.925%）。
- GRCI changed：1/53（1.887%），因为仅 DAILY_REVIEW 且 RAI/GRS 同时可用时才定义。
- 既有 Claim decision `ABSTAIN_TO_EXPRESSIBLE`：27。
- 新增 Claim opportunities：540，其中 504 FORECAST、36 OBSERVED；修正后 454 EXPRESSIBLE、86 ABSTAIN。
- 所有 53 个事件均出现至少一种 Claim semantic change。

## 认识论解释

pre-revision 版本不是“错误状态”，它忠实表示当时可知道什么；post-revision 也不是对过去的篡改，而是保留旧版本后新增一个知识区间。研究价值在于同时回答“当时能说什么”和“后来知道了什么”，而不是只保存最终历史。
