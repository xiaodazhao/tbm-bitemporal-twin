# Stage 1 Real Data Validation

Legacy outputs are diagnostic references rather than PLC-informed proxy reference annotations.

## 1. 验证目的

验证真实TBM PLC CSV能否通过 Stage 1 链路：字段匹配、SourceAsset登记、PLC标准化、质量诊断、OperationPhase弱标签、ExcavationEpisode、SpatialFootprint、自动诊断和人工复核材料。

## 2. 代表日期

实际验证了三个指定日期，均找到对应文件：

- `2023-12-30`: `tbm_data_20231230.csv`
- `2023-12-28`: `tbm_data_20231228.csv`
- `2023-09-15`: `tbm_data_20230915.csv`

三个日期分别覆盖较长连续采样、多推进区间与短时段推进样本。没有替代日期。

## 3. 数据配置

新仓库没有 `.env`，旧仓库也没有 `.env`。旧仓库 `backend/config.py` 的只读线索指向本机云盘 `TBM9/TBM9_2023`，实际运行时通过显式参数传入 `--plc-data-dir`，代码中没有硬编码用户绝对路径。

验证输出目录：

```text
artifacts/stage1_validation
```

## 4. 字段匹配结果

三天均明确匹配核心字段。`shield_head_chainage` 均通过显式Catalog alias 匹配到 `导向盾首里程`。真实CSV同时存在 `导向盾中里程`、`导向盾尾里程`、`日进尺`、`开累进尺`，审计中已记录为 nearby non-anchor columns，但没有被自动选为主锚点。

`cylinder_displacement` 未匹配到真实列。多个数值通道仍保留 `unit_verified=false`，不用于物理意义结论。

详见：

```text
artifacts/stage1_validation/channel_mapping_summary.csv
```

## 5. 数据质量结果

| date | raw rows | normalized rows | quality | duplicate time | data gaps | chainage issue |
|---|---:|---:|---|---:|---:|---|
| 2023-12-30 | 4098 | 4098 | A | 0 | 0 | none |
| 2023-12-28 | 1387 | 1387 | B | 0 | 0 | one large reverse step |
| 2023-09-15 | 199 | 199 | A | 0 | 0 | none |

原始无时区PLC时间按配置 `Asia/Shanghai` localize，再转换到 `UTC`。三个日期都未发现重复时间戳或DATA_GAP。`2023-12-28` 检出一次较大里程反向，因此日级PLC质量等级降为B。

## 6. Phase分布

`UNKNOWN` 比例很低：`2023-12-30` 为约0.05%，`2023-12-28` 为约0.07%，`2023-09-15` 为0。`DATA_GAP` 比例均为0。

Phase弱标签只表达机器响应状态，不解释为地质正常、安全或设备无异常；`IDLE` 也不解释为故障或非计划停机。

## 7. Episode结果

| date | episode count | min core sec | median core sec | max core sec | context total sec | boundary status | gap crossing | long IDLE crossing |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| 2023-12-30 | 12 | 660 | 1665 | 2820 | 22820 | COMPLETE: 12 | 0 | 0 |
| 2023-12-28 | 7 | 510 | 2840 | 4380 | 19740 | LEFT_CENSORED: 1, COMPLETE: 6 | 0 | 0 |
| 2023-09-15 | 1 | 930 | 930 | 930 | 970 | COMPLETE: 1 | 0 | 0 |

Stage 1.6 后，`system_start_time/system_end_time` 表示核心EXCAVATING时间，`system_context_*` 表示包含前后STARTUP/IDLE/UNKNOWN/COASTDOWN的上下文时间。`2023-12-28` 第一个00:00开始的Episode已标记为 `LEFT_CENSORED`，不再声称真实开始边界已知。

未发现Episode跨越DATA_GAP或明显长IDLE。`2023-12-30` 和 `2023-12-28` 的Episode数量较多，可能对应多轮推进/停机节律；是否过分割需要人工复核图确认。

人工复核材料：

```text
artifacts/stage1_validation/<date>/episode_review.csv
artifacts/stage1_validation/<date>/episode_review.png
artifacts/stage1_validation/plc_episode_reference_review.csv
```

## 8. Footprint结果

三天全部Footprint为 `MULTI_CHANNEL_CONSISTENT`，原因是同一PLC资产内的 `导向盾首里程` 与 `日进尺/开累进尺` 多个通道完成了一致性比较。未出现 `INCONSISTENT` 或 `INSUFFICIENT`。估计进尺分布：

- `2023-12-30`: 0-2 m，中位数1 m。
- `2023-12-28`: 0-2 m，中位数2 m。
- `2023-09-15`: 1 m。

少数Episode的 `estimated_advance_m=0`，已标记 `ZERO_ADVANCE_DURING_EXCAVATION`，并给出 `static_chainage_signal`、`insufficient_chainage_resolution`、`episode_boundary_issue` 等人工复核原因。此类Footprint不作为可信精确进尺使用，也不会被自动删除或改写。

## 8.1 Stage 1.5到Stage 1.6回归对比

详见：

```text
artifacts/stage1_validation/stage16_regression_comparison.csv
```

核心变化：

- Episode数量保持不变：12 / 7 / 1。
- 核心推进时长小于旧上下文时长：`2023-12-30` 从22820s降至21310s；`2023-12-28` 从19740s降至18970s；`2023-09-15` 从970s降至930s。
- 旧Footprint `CONSISTENT` 被细化为 `MULTI_CHANNEL_CONSISTENT`。
- `2023-12-28` 新增1个 `LEFT_CENSORED` Episode。
- 新增0m推进复核标记：`2023-12-30` 1个，`2023-12-28` 1个。
- Episode质量不再全部为A：`2023-12-30` 为A=9/B=3，`2023-12-28` 为A=2/B=5，`2023-09-15` 为A=1。

## 9. 与旧系统的诊断差异

旧仓库导出脚本已只读运行成功，输出到：

```text
artifacts/legacy_reference
```

旧仓库运行时提示 `DATA_ROOT` 未设置并使用云盘fallback。旧输出仍属于日报/Cell链路，只能用于粗略检查读取日期是否一致，不是Episode proxy reference。

旧系统输出固定10 m Cell数量：

- `2023-12-30`: 14 rows
- `2023-12-28`: 13 rows
- `2023-09-15`: 14 rows

新系统输出Episode数量：

- `2023-12-30`: 12 episodes
- `2023-12-28`: 7 episodes
- `2023-09-15`: 1 episode

二者对象定义不同，不比较GRCI、Cell数量、日报文本、Evidence Pack或报告质量分。

## 10. 当前限制

- 尚未完成PLC-informed proxy reference复核，因此不能声称现场真实施工事件准确率。
- 单位未验证字段仍只用于透明弱标签，不能用于物理结论。
- 三个真实日期没有跨午夜样本。
- `cylinder_displacement` 未匹配到真实字段。
- 少数0m Episode需要人工复核边界。

## 11. 人工标注计划

填写：

```text
artifacts/stage1_validation/plc_episode_reference_review.csv
```

然后运行：

```bash
python scripts/evaluate_episodes.py \
  --predictions artifacts/stage1_validation/episode_summary.csv \
  --annotations experiments/episode_annotation/episode_proxy_reference.csv \
  --output-dir artifacts/episode_evaluation
```

评价使用Episode时间区间IoU和边界误差，不使用逐采样点分类准确率冒充Episode检测性能。

## 12. Stage 1验收结论

`PASS_WITH_LIMITATIONS`

理由：三天真实数据均成功跑通，字段映射和盾首里程主锚点明确，Episode未跨DATA_GAP或长IDLE，`2023-12-28` 文件开头推进已正确标记为 `LEFT_CENSORED`，输出可追溯到资产和原始行，静态检查与测试通过。但仍存在单位未验证、缺少PLC-informed proxy reference复核、缺少跨文件Episode合并、少数0m Episode需人工复核等限制。
