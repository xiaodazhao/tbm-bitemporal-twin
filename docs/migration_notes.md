# Migration Notes

旧仓库在本地的实际只读参考路径是 `./tbm-report`；需求中的 `../tbm-report` 未作为当前工作目录的兄弟路径存在。新项目不修改旧仓库。

## Referenced Knowledge

从旧仓库读取并提炼了以下知识：

- PLC字段别名：时间、盾首里程、掘进状态、推进速度、给定速度、推力、刀盘扭矩、刀盘转速、贯入度。
- 时间解析与排序经验：解析失败保留诊断，时序算法只使用有效时间。
- 采样间隔诊断：使用正时间差的中位数和P95，大缺口阈值保守处理小样本。
- PLC质量检查：重复时间戳、非单调时间、里程反向、里程大跳变、静止比例和缺失率。
- 弱推进识别：使用状态、速度、推力、扭矩和转速组合形成透明弱标签。

## Not Migrated

没有迁移旧仓库的 DailyReport、ConstructionStateCell、日报API、LLM生成/修订、PromptEvidencePack、GRCI/RAI/GRS、高GRCI Cell、前端和数据库服务。

不迁移 `ConstructionStateCell`，因为本项目第一阶段以连续 `ExcavationEpisode` 作为施工事实对象，固定空间Cell最多只能在未来作为空间索引。不迁移 GRCI 和 Evidence Pack，因为它们服务于旧的日报和生成链路，不是本阶段的证据适用性或Claim许可模型。

新旧项目不保证API兼容。旧仓库只作为只读基线和字段经验来源。

