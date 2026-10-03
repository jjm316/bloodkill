# 02 技能窗开窗总则重写 + 感应者封印（方案 A）

Status: resolved

## 背景

ADR 0009（2026-10-03 裁决 P4，本批最大引擎改动）：开窗总则改为 **rank 被任何伤害（攻击/挡刀/技能/反伤，自选或被迫）新亮出即开技能窗，唯一例外 = 感应者的强制亮出**。被感应者点出等级 = 该玩家技能绝对永久封印（炼金治疗退 rank 亦不可解）。技能伤害仍**永不触发干涉投票**。

## 改动

- 重写 `_after_damage` 开窗条件（engine.py:795-801）：不再限制 `trigger ∈ {attack, intervention}`；新条件 = 本次伤害新亮出 rank 且非"感应者强制亮出"路径。
- **方案 A 封印**：感应者技能伤害强制亮出受害者 rank 时，直接把该 rank 写入受害者 `skills_used`（与已用/已弃用共用同一把永不清除的锁；不加新状态位/事件类型）。
- **匕首移交时序（B12 联动）**：刺客/感应者技能结算后"无挂起窗口才移交匕首"的条件（`state.pending is None`）须覆盖新场景——技能伤害致受害者自亮 rank 会留下挂起技能窗，验证移交发生在窗口关闭之后。
- **B4 反转**：狂战反伤打出第 3 点被迫亮 rank → 开技能窗（trigger=None 路径纳入总则）。
- **D1 连带**：fleur-cross 被非感应者伤害新亮出 → 诅咒窗开（含刺客第 2 点凑第 3 点、受害者自选亮 rank）；被感应者封印 → 诅咒胜路当场作废（`skills_used` 含 fleur-cross 即永无窗口）。

## 验收（裁决路径表逐条）

| 路径 | 窗口 |
| --- | --- |
| 攻击/挡刀伤害亮 rank（自选或第 3 点被迫） | 开（既有） |
| 技能伤害下受害者自选亮 rank（含队友刺客连招） | 开 |
| 刺客/炼金 harm 打出第 3 点被迫亮 rank | 开 |
| 狂战反伤第 3 点被迫亮 rank | 开 |
| 感应者强制亮出 | **不开 + 写 skills_used（封印）** |
| 已使用 / 已弃用 / 已被封印 | 永不再开 |
| 技能伤害 → 干涉投票 | 不触发 |
| 非感应者伤害亮 fleur-cross → 诅咒窗 | 开 |
| 被感应者封印后炼金退 rank 重亮 | 仍不开（封印不可解） |

## Comments

**2026-10-03 实施（issue 02 → resolved）**：`_after_damage` 开窗条件重写为「本次伤害新亮出 rank 且非感应者强制亮出路径」（`sealSkill` 上下文标记），`trigger ∈ {attack, intervention}` 限制删除（`SkillWindowOpened` 的 `trigger` 载荷与 `Pending.trigger` 自此可为 `None`，客户端 `types.ts` 本就按可空声明、事件日志不展示该事件）。方案 A 封印：感应者分支传 `seal_skill=True`，强制亮出后直接 `skills_used.add(str(rank))`，与已用/已弃用共用同一把锁。B12：`_choose_skill` 关闭技能窗时按窗口上下文的 `daggerToTarget` 补做匕首移交（位于 fleur-cross 提前 return 之前，刺客链中审判者自亮 rank 开诅咒窗的场景同样覆盖）；连带修复 rank 2 伤害链缺 `attackerPlayerId`（狂战从技能窗反伤技能使用者时 `_live_player(None)` 会炸，终局归因原靠 command.actor 兜底）。

**保留 rank 4 开窗门槛（`rank != 4 or trigger == "intervention"`）**：语料 rank 4 行"仅在自己干涉后"未被本批裁决改写、验收表攻击/挡刀行标注"既有"（现状即攻击触发不开），且投影层已有「rank 4 非 intervention 窗只给放弃」的防御分支——开门会造成"用不了只能弃"的陷阱窗。判定此门槛是能力自身前置条件而非伤害源限制，不属 P4"唯一例外"的推翻范围。

验收路径表逐条有测：刺客/炼金/狂战/技能伤害开窗（`test_assassin_victim_self_chosen_rank_reveal_opens_skill_window_and_defers_dagger`、`test_alchemist_harm_third_point_forced_rank_opens_victim_window`、`test_berserker_reaction_third_point_forced_rank_opens_attacker_window`、`test_berserker_window_from_skill_damage_counters_the_skill_user`）、感应者封印+不开窗（扩展 `test_mentalist_damages_target_forces_rank_and_hands_dagger`）、D1 诅咒窗（`test_skill_damage_self_chosen_rank_reveal_opens_the_curse_window` 改写自旧"技能伤害不开窗"测试）、封印不可解全链（`test_mentalist_seal_kills_the_curse_path_and_heal_cannot_unseal`：封印→炼金退 rank→三伤被迫重亮→永无窗口）。coverage 过期行已同步；ruleset 0.5 bump、golden 新分支、helpContent 归 issue 07。全量 162 测试绿，golden 字节级不变（golden runner 只走攻击伤害且先亮 marker，不经新分支）。
