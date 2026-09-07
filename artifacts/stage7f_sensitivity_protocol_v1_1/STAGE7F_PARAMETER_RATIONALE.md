# Stage7F 参数选择与冻结语义

敏感性参数仍只有三个：ConstructionStateCell 采用 5/10/20 m，RAI 历史充分性采用
20/30/40 个先前观测样本，RAI robust-z 饱和尺度采用 2/3/4。实验设计仍是一个共享
baseline 加六个单参数替代 arm 的 OFAT，不进行全因子调优。

GRS ordinal mapping、维度内 `max_mapped_attention` 聚合以及跨非空维度的
`mean_non_null_dimension_attention` state aggregation 都属于冻结指标语义，不参与扰动。
GRCI 的 `NONPROBABILISTIC_CONJUNCTIVE_PRODUCT` 定义为 RAI 与 GRS 的乘积，只在
`DAILY_REVIEW_CELL_ONLY` scope 且两者均可用时计算；它不是概率、因果估计或灾害概率，
也不是 sensitivity parameter。Claim Contract 与双时间知识边界继续保持冻结。

未来 Stage7F-B 只能按冻结 manifest 执行描述性 robustness，不得依据结果选择 arm 或设置
任意自动 PASS threshold。
