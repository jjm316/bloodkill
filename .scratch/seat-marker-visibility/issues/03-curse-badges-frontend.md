# 03 诅咒药丸与终局翻牌（前端）

Status: resolved
Blocked by: 02

实现 `.scratch/seat-marker-visibility/spec.md` **Part B「前端」**。依赖 02 的协议字段（holdsCurseCard / viewer.curseAssignments / GameEnded.curseAssignments）。

要点（全量见 spec Part B）：

- types.ts 增三字段；icons.tsx 增 `curseCard` 卡背图标（描边风格）。
- Board.tsx 标记行紫色药丸「咒」，三分支标签：默认「咒」/ 审判者设备「真咒/假咒」（curseAssignments＋curseId 前缀）/ 终局全员翻「真咒/假咒」；捕获后仍显示。
- 结果面板归属行列于胜负判词上方（ended 视图与回放终局一致）。
- 事件日志：CurseDistributed 定义为技能类，文案「将诅咒卡交给了 {玩家}」。
- helpContent 图例增诅咒药丸条目。
- 测试：药丸三分支、重连投影恢复、日志行、图例；e2e 可扩展 `.scratch/e2e-curse.py`；`npm test`＋`python scripts/check.py` 门禁。

## Comments

- 2026-10-11（agent）：落地完成，提交 b21aaa2（ff 并入集成分支 spec/seat-marker-visibility）。types.ts 三字段（`PlayerView.holdsCurseCard` 必填、`ViewerView.curseAssignments` 可选——协议明文仅审判者视角存在此键且 test_projection.py 断言他人视角缺席，偏差 1：可选拒绝对线上数据撒谎）、GameResult.curseAssignments 必填；icons.tsx 增 `curseCard` 卡背（圆角卡身＋圈内十字封印纹＋卡脚线，描边/currentColor，卡面无真假记号）；Board.tsx 紫药丸列资源徽章后同一 flex 行，`curseRevealOf` 三分支（终局 result 优先 → 审判者 viewer → 暗置「咒」），被捕获随 `.seat.captured` 整卡半透明，`ResultBanner` 增归属行于判词上方（独赢分支措辞「真诅咒在 X（胜方领袖）→ 审判者独赢，家族胜利被覆盖；假诅咒在 Y」），两处 `?? {}` 兜底 0.7 前旧存档回放；styles.css `.curse-pill`（紫底白字 --order-bg，尺寸同金药丸，xl 档同步 11px）＋ `.curse-attribution`（提亮紫 #b9a0e6，对卡底 ≈7.4:1）；helpContent 图例第 7 条「诅咒卡」。偏差 2：范围外小修 GameScreen CurseSkillUse 确认框文案（原文「归属对其他玩家永远保密」与 ADR 0014 归属公开直接矛盾且与本票药丸同屏冲突，改为「持卡归属对全员公开……真/假之分仅你可知，终局全员翻开」）；偏差 3：ResultBanner 判词表补 `game.end.inquisitor-true-curse` 中文名（票 02 新增分支此前落兜底「规则结算」）；偏差 4：e2e 未扩展——`.scratch/e2e-curse.py` 是协议层脚本，UI 级自动化成本高，留给协调者按 spec 验收清单人工验收。测试：新增 boardCurse.test.tsx 10 用例（含审判者投影驱动重连恢复、终局翻牌、捕获后药丸仍在、归属行位置与独赢措辞、旧局无归属行），icons/helpContent/HelpOverlay 同步更新，10 个既有测试文件 PlayerView 夹具补 `holdsCurseCard: false`；vitest 191 全绿、check.py 全绿。票 02 已落地的 CurseDistributed 日志行核对无误未重做。
