# 01 技能伤害亮牌权回归受害者自选

Status: resolved

## 背景

ADR 0006（2026-10-03 裁决 P1）：技能造成的伤害（刺客 2 点、感应者 1 点、炼金 harm 1 点）每一点回归 `damage.reveal` 通用规则——开**受害者自选**亮牌窗；感应者（rank 5）按技能文本维持**强制亮 rank**。

现状缺陷（engine.py:734-736）：凡 `source="skill"` 的伤害完全剥夺选择——rank 未亮则第 1 点直接亮 rank，否则 `next(iter(available))` 自动亮一张标记（迭代序随 PYTHONHASHSEED 翻转，耦合点 A2）；wild 标记被强制定为玫色（A7）。

## 改动

- 删除 `_apply_damage` 中 skill 源的自动亮牌分支，让技能伤害走通用亮牌管线（自选窗 / 第 3 点被迫 rank / wild 色选窗）。
- 感应者技能伤害需带 `forceRank` 语义（其"强制亮 rank"来自技能文本，不是通用第 3 点规则）；刺杀者与炼金 harm 不带。
- 与 02 联动：受害者自选亮出 rank 时将开技能窗（旧规则不开）——本 issue 只管亮牌管线，开窗条件归 02。

## 验收

- 刺客打 0 伤新玩家：第 1、2 点各开一个受害者自选窗；无任何 `next(iter(...))` 参与路径。
- 炼金 harm：开受害者自选窗。
- 感应者打 rank 未亮者：直接亮 rank、无亮牌窗（强制语义保持）。
- PYTHONHASHSEED=0…5 各跑一遍刺客场景，日志一致（A2 回归）。
- 既有测试 `test_assassin_skill_deals_two_damage_hands_dagger_and_opens_no_new_window` 的"无窗"断言需按新规则拆分：亮牌窗该开、技能窗归 02 的总则判定。

## Comments

- 2026-10-03 已实现（ADR 0006）。`_continue_damage` 的 skill 自动亮牌分支删除，技能伤害并入通用受害者自选管线；感应者（rank 5）伤害带 `force_rank=True`（强制亮 rank 不开窗，rank 已亮则回落自选窗）；刺客/感应者的"匕首交给受害者"（B12）改由伤害上下文 `daggerToTarget` 标记在 `_after_damage` 链尾生效——受害者自选窗挂起期间旧的手动移交永远不会触发，不改就丢规则。
- 新增/拆分测试：刺客双自选窗（`test_assassin_skill_deals_two_damage_opens_victim_choice_windows_and_hands_dagger`）、感应者强制亮 + 已亮回落自选两测、炼金 harm 开窗断言并入既有测试、`test_skill_damage_does_not_open_the_curse_window` 改为受害者自选 rank（02 落地时此断言翻转）、PYTHONHASHSEED=0..5 子进程回归（`assassin_skill_scenario_log`）。
- ruleset bump 0.4→0.5、golden 重生成、helpContent、coverage 批量加行归 issue 07；本次仅同步 coverage 文档中被改名/失效的行与第 102 行旧口径。
