# 目标选择型能力：rank 3/5/6/8/9（14 子票）

Type: task
Blocked by: 18
Status: open

问题：harlequin / mentalist / guardian / mage / courtesan 五个能力在 catalog 中仍标 `unimplemented`。这五个能力模式相同——技能窗内选择一个目标并施加一次性效果——依赖 17 的技能窗/结算上下文与 18 的资源事件词汇。

语义依据：[14](14-abilities-resource-economy.md) 票面表格与「已裁决」（guardian 盾可干涉、mage 法杖单效果、courtesan 扇按「他人不能干涉」实现）。

输出（每个能力：引擎分支 + `_IMPLEMENTED_SKILL_RANKS` 加入对应 rank + `legal_actions` 目标选项 + catalog `implementation` 与双语文案 + 至少一条分支测试）：

1. **rank 3 harlequin**：`choose-skill use=True` + `targetPlayerIds`（恰好 2 名其他存活玩家，否则 `skill.invalid-target`）；公开事件 `HarlequinInspected {playerId, targetPlayerIds}`（目标公开）；秘密反馈写入 `Player.inspections`（目标 faction + rank），只出现在本人 viewer 投影，事件日志与他人投影均不含反馈。catalog slug：`inspect-two`。
2. **rank 5 mentalist**：`targetPlayerId`（非自己、活体；盾目标拒绝 `target.shielded`）；1 点伤害 `source = "skill"` 且强制亮 rank（rank 已展示则回落为自选身份标记，由 17 的 `forceRank` 机制保证），不开新技能窗；结算完成后经 `followup: hand-dagger` 把匕首交给目标。slug：`damage-one-reveal-rank`。
3. **rank 6 guardian**：`targetPlayerId`（任意活体，允许自己）；`ResourceGranted` shield 给目标、sword 给自己；`Player` 记录 `shield_ward_id`；guardian 第 3 点伤害时 `ResourceReturned` 归还自己的 sword 与 ward 的 shield（挂在 17 的逐点结算上；ward 已捕获时仍归还）。slug：`grant-shield-sword`。
4. **rank 8 mage**：`targetPlayerId`（任意活体）；`ResourceGranted` staff；目标两张身份标记全部变为 `unknown`（含已展示标记的显示值；审判官的 `wild` 也变为 `unknown`）；事件 `IdentityMarkersObscured {playerId}`。slug：`grant-staff-obscure`。
5. **rank 9 courtesan**：`targetPlayerId`（任意活体）；`ResourceGranted` fan；扇的干涉阻断防御闸门（`_attack` 资格名单、`legal_actions`）已存在，本票把注入测试转为自然触发并保留注入用例。slug：`grant-fan`。

注意：15 已由 17 修复，`hand-dagger` followup 仅在 `status == "active"` 时生效；技能伤害造成第 4 点捕获时不得残留 action 相位或匕首移交。

完成条件：

- 五个能力均可经公开命令触发，行为符合 14 裁决与来源 C；
- 盾/剑/法杖/扇有明确 `ResourceGranted` 发放路径，guardian 第 3 伤归还路径有测试（sword + shield 两个 `ResourceReturned`）；
- harlequin 反馈保密有投影测试（含事件日志不含身份值的断言）；
- 性质测试随机走法能自然走到新分支（`generate_walk` 经 `legal_actions` 已覆盖），不变量在全量 sweep 下成立；
- 全量 `.venv\Scripts\python.exe -m unittest discover -v` 通过。

## Comments

- 2026-08-24：由 14 拆分。五个能力彼此无依赖，实现顺序任意；rank 3 的两两组合在 12 人局最多 55 个合法行动，属预期规模，无需分页。
