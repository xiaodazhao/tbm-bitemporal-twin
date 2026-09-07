# 指标定义

## RAI

施工响应关注指标。通道先相对严格早期因果历史计算 robust-z，再以 Episode 内 `median(|z|)` 聚合；总推力/扭矩组成 LOAD，掘进速度/贯入度组成 KINEMATIC。族内取 max，族值按 `min(d/3,1)` 饱和，最终 RAI 取两族 max。历史样本下限 30；两族都完整才可用。RPM 不进入标量。RAI 非概率且不表明地质原因。

## GRS

地质证据关注指标。结构化属性由冻结 ordinal mapping 映射。维度内为 `max_mapped_attention`；状态级为 `mean_non_null_dimension_attention`。未知/不可映射值不补零。GRS 非风险概率。

## GRCI

`GRCI = RAI × GRS`，算子为 `NONPROBABILISTIC_CONJUNCTIVE_PRODUCT`。仅对 DAILY_REVIEW_CELL 且两者可用时定义。非概率、非因果、非危险度。
