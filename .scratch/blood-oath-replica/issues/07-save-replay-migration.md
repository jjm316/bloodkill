# 实现存档、回放与版本迁移

Type: task
Status: resolved
Blocked by: 04, 05

问题：定义事件日志和快照的持久化格式，支持暂停/恢复、逐步回放、分享调试链接及 schema 迁移。

输出：本地存档 API、压缩策略、校验和、重放播放器接口、迁移脚本和损坏存档错误体验。

完成条件：任意已完成对局可重放到每一步；版本升级后旧 fixture 可迁移；篡改/截断日志被检测并给出可理解错误。

## Answer

已实现版本化本地存档与回放层：

- `blood_bound.persistence` 提供 `save_game()` / `load_game()`、JSON 与由 `.gz` 后缀选择的确定性 gzip 压缩、SHA-256 事件哈希链和快照校验和。加载时验证连续 revision、元数据、哈希链、快照和确定性命令重放；损坏、截断、规则版本不兼容和无法重放的日志均返回稳定的 `SaveError` code 与可呈现消息。
- `EngineState` 现在保留不可变的已接受命令流。`ReplayPlayer` 可以逐条 `step()` 回放，暂停对局会保留 pending window；`create_debug_link()` / `load_debug_link()` 将压缩存档放在 URL fragment，供调试分享且不把 payload 发送给服务器。
- 保存 schema 为 v2，明确迁移 v1 的 `checkpoint` / `eventLog` / `commandLog` fixture，保留原有 ruleset 版本；`python -m blood_bound.migrate_save old-save.json upgraded-save.json.gz` 可生成已验证的当前格式。
- `tests/test_engine.py` 新增完整局逐步回放、暂停恢复、gzip、本地迁移、调试链接、日志篡改和截断测试。`python -m unittest discover -v` 通过 17 项，`python -m compileall -q blood_bound` 通过。

## Comments

- 2026-08-20：从 frontier 认领并完成；事件记录通过命令流的确定性重放与快照交叉验证，避免把快照当作唯一权威事实。
