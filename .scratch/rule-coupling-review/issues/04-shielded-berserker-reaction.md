# 04 删 owner 盾检查：持盾狂战士可反伤

Status: resolved

## 背景

ADR 0010（2026-10-03 裁决 P5）：盾只挡"被指定为目标"。引擎 engine.py:580-581 规定持盾狂战士自己不能反伤（raise `target.shielded`），投影 projection.py:59-60 同步只给"放弃"选项——无规则出处，且挡刀开窗后被迫放弃会永久烧掉技能（ADR 0008）。

## 改动

- 删除 engine.py:580-581 的 owner 盾检查；持盾狂战士挡刀开窗后可正常发动反伤。
- projection.py:59-60 恢复反伤选项。
- **保留**：反伤目标是攻击者——攻击者持盾时反伤被拦截（有出处，耦合点 B1，不动）。

## 验收

- 持盾狂战士志愿挡刀 → 承伤 → 被迫亮 rank → 技能窗 → 反伤成功结算。
- 攻击者持盾 + 狂战士（无盾）反伤 → 仍被 `target.shielded` 拦截。
- 既有盾相关测试（B1/B2）不回归。

## Comments

- 2026-10-03 已实现（ADR 0010）。引擎 `_choose_skill` rank 7 分支删 owner 盾检查，投影 `legal_actions` 技能窗删"持盾 rank 7 只给放弃"特判（连带删了孤儿 `owner` 局部变量）。
- 新增两测试：`test_shielded_berserker_volunteer_can_react`（持盾志愿挡刀 → 承伤即被迫自动亮 rank、同命令开出技能窗 → 投影含 use=True → 反伤结算，攻击者 1 伤并进入其亮牌窗，匕首归狂战士）、`test_shielded_attacker_blocks_berserker_reaction`（B1 保留：攻击者持盾 → `target.shielded`，revision/`skills_used` 不变，失败命令不烧技能）。
- coverage 文档 rank 7 reaction 行与投影 `legal_actions` 技能窗行已同步；helpContent 本就正确（盾文案="不可被攻击，也不可被技能指定伤害"即只挡指定，狂战条目无盾限制），无需改动。
- ruleset bump 0.4→0.5 仍归 issue 07。
