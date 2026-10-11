# 03 诅咒药丸与终局翻牌（前端）

Status: ready-for-agent
Blocked by: 02

实现 `.scratch/seat-marker-visibility/spec.md` **Part B「前端」**。依赖 02 的协议字段（holdsCurseCard / viewer.curseAssignments / GameEnded.curseAssignments）。

要点（全量见 spec Part B）：

- types.ts 增三字段；icons.tsx 增 `curseCard` 卡背图标（描边风格）。
- Board.tsx 标记行紫色药丸「咒」，三分支标签：默认「咒」/ 审判者设备「真咒/假咒」（curseAssignments＋curseId 前缀）/ 终局全员翻「真咒/假咒」；捕获后仍显示。
- 结果面板归属行列于胜负判词上方（ended 视图与回放终局一致）。
- 事件日志：CurseDistributed 定义为技能类，文案「将诅咒卡交给了 {玩家}」。
- helpContent 图例增诅咒药丸条目。
- 测试：药丸三分支、重连投影恢复、日志行、图例；e2e 可扩展 `.scratch/e2e-curse.py`；`npm test`＋`python scripts/check.py` 门禁。
