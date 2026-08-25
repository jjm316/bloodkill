# 干涉耦合型能力：rank 4 alchemist / rank 7 berserker（14 子票）

Type: task
Blocked by: 19
Status: resolved

问题：alchemist 与 berserker 的效果上下文来自干涉/攻击流程（被干涉者、刚刚攻击自己的玩家），需要 17 的结算上下文携带 `protectedPlayerId` / `attackerPlayerId` 进入技能窗；alchemist 还需新增退标记窗口。放最后实现是因为它们对地基的上下文传递要求最高。

语义依据：[14](14-abilities-resource-economy.md) 票面表格与「已裁决」第 1 条（退回 rank 后二次展示不可再发技能——由 17 的闩锁保证，本票只做检验）。

输出：

1. **rank 7 berserker**：技能窗 context 取 `attackerPlayerId`（attack 触发即攻击者，intervention 触发仍为原攻击者）；`use=True` → 该玩家承受 1 点伤害，`source = "reaction"`（盾可挡，报 `target.shielded`，`legal_actions` 此时只给 decline）；可造成第 4 点捕获（终局 active = berserker）；不开新技能窗。catalog slug：`counter-one`。
2. **rank 4 alchemist**：仅 `trigger == "intervention"` 的技能窗携带 `protectedPlayerId`（被干涉者）；`use=True` + `mode ∈ {"heal", "harm"}`：
   - `harm`：被干涉者承受 1 点伤害，`source = "skill"`，走 17 的自选展示流程，不开新技能窗；
   - `heal`：被干涉者需 `damage ≥ 1`（否则 `skill.invalid-target`）；开新 pending `token-return`（actor = 被治疗者）+ 新命令 `choose-return {token}`；结算：`damage − 1`（事件 `DamageHealed {playerId, amount, source: "skill"}`）并退回所选已展示标记（事件 `TokenReturned {playerId, token}`）；退回 rank 后二次展示不再开窗（17 闩锁）；审判官标记退回后恢复 `wild`。窗口开启事件 `TokenReturnOpened {playerId}`。
   - 无 `protectedPlayerId`（attack 直接触发）时 `use=True` 拒绝 `skill.invalid-target`，`legal_actions` 只给 decline。
3. **收尾**：`_IMPLEMENTED_SKILL_RANKS` 补齐为 1–9；catalog `ability.rank.04`/`ability.rank.07` 更新（`heal-or-harm` / `counter-one`）与双语文案；`docs/rule-branch-coverage.md` 更新（注入转自然触发标注、新分支行）；`server/PROTOCOL.md` 与客户端类型同步 `choose-return` / token-return 窗口。
4. **测试**：berserker 反击（含盾挡、反击捕获终局）；alchemist harm/heal、退 rank 二次展示不开窗、退普通标记、attack 触发拒绝、治疗 0 伤拒绝；性质测试 sweep 自然覆盖。

完成条件：

- 两个能力均可经公开命令触发且行为符合 14 裁决；
- `choose-return` 全流程有分支测试，退回 rank 的闩锁语义有回归测试；
- 全量 `.venv\Scripts\python.exe -m unittest discover -v` 通过；
- 完成后在 [14](14-abilities-resource-economy.md) 伞票 Comments 回报，由伞票按原完成条件整票验收。

## Comments

## Answer

Implemented and verified rank 4 alchemist and rank 7 berserker. Intervention resolution now carries the original attacker and protected-player context. Alchemist rank 4 is offered only for intervention-triggered windows: harm applies one skill damage to the protected player without opening another skill window; heal requires existing damage and opens a token-return window for the healed player, emitting DamageHealed and TokenReturned while preserving the rank skill lock. Berserker rank 7 applies one self-damage with source reaction on attack or intervention triggers, with no follow-up skill window. choose-return is wired through the engine, projection, persistence-compatible pending state, protocol, catalog, and localized text. Ranks 1--9 are implemented and covered by branch, property, and golden replay tests.

- 2026-08-24：由 14 拆分。berserker 的 `source = "reaction"` 沿用契约事件表中的既有枚举值，不是新增语义。
