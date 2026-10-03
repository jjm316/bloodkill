---
status: accepted
date: 2026-10-03
---

# 审判者被捕获改判审判者独赢

规则语料两处写明"审判者被捕获也独赢"（`inquisitor.curse` 待验收重点、fleur cross 行），但引擎实现的是平局：审判者被捕获时 winner="draw"、branch="inquisitor-captured"（engine.py:835-837），测试 `test_inquisitor_captured_is_draw` 与 golden、coverage 文档同口径——而翻遍 ADR 找不到任何"改成平局"的裁决记录，属实现期的静默偏离。产品方裁定（2026-10-03 规则共识访谈）：采语料，审判者被捕获时**审判者独赢**（winner=secret-order）。

## Considered Options

- **维持平局（追认引擎）**：全员无胜者的"同归于尽"语义；被否决——无裁决记录支撑，且语料来源 C 原文两处一致写独赢。
- **采语料改引擎（独赢）**：对局形态变为"钓捕"——审判者可刻意暴露求捕，家族猎杀前必须确认目标身份，审判者从被动躲藏者变成主动挑衅者。产品方明确选择此形态。

## Consequences

- 引擎终局分支、测试断言、golden、coverage 全部改写；ruleset 版本随本批共识整体 bump（0.4 → 0.5）。
- 帮助文案须补"审判者被捕获 = 审判者独赢"，玩家才能理解为什么不能随手打死疑似审判者。
- 战略连带：家族对审判者的反制手段仍是法师法杖（剥夺 wild 自选色，耦合点 B9 维持）与感应者封印（ADR 0009——封印同时废掉诅咒胜路）。
