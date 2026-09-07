# 双时间定义

- valid time：证据/状态所描述的工程现实时间。
- knowledge time：证据进入可用知识状态的重建时间边界。

同一 valid-date/cell 可以随 knowledge time 形成版本链。旧版本保存“当时所知”，新版本在 later evidence 到达后追加知识，不能回写污染旧版本。authoritative revision ordering 来自 version_number 与 supersedes lineage，不来自 ID 字典序。

历史数据库 transaction log 不可得，因此 knowledge time 是基于 submitted/document available time 的审计性重建。论文必须把这一点作为方法限制，而不能将其宣称为原生事务时间。
