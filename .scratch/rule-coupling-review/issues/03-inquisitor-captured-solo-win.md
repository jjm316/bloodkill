# 03 审判者被捕获改判审判者独赢

Status: resolved

## 背景

ADR 0007（2026-10-03 裁决 P2）：语料两处写"审判者被捕获也独赢"，引擎实现平局（engine.py:835-837：winner="draw"、branch="inquisitor-captured"），无 ADR 记录的静默偏离。采语料改引擎。

## 改动

- engine.py:835-837：审判者被捕获 → `winner="secret-order"`；branch 维持 `"inquisitor-captured"`（语义改为独赢）。
- 注意分支顺序：该分支在家族分支/真诅咒判定之前，改后仍须确认审判者被捕获时不进真诅咒判定（审判者自己不是家族胜方领袖，现状已排除）。

## 验收

- 既有测试 `test_inquisitor_captured_is_draw` 改写为独赢断言（重命名避免误导）。
- golden 场景同步：审判者被捕获的对局 winner=secret-order。
- coverage 文档 `inquisitor-captured` 行同步（归 07 统一收尾亦可）。

## Comments

- 2026-10-03 已实现（ADR 0007）。`_end_game` else 分支 `winner="draw"` 改 `winner="secret-order"`，`branch` 维持 `inquisitor-captured`；真诅咒判定经 `winner in {"rose","beast"}` 闸门天然排除，代码注释已说明。
- `test_inquisitor_captured_is_draw` 改名 `test_inquisitor_captured_gives_the_inquisitor_a_solo_win` 并翻转断言；`test_properties.py` 终局 winner 不变量集合补 `secret-order`。
- golden 7/9/11 重生成：winner 与 GameEnded 事件载荷改写、审判者排名升至第 1（score 1）、后续 hash 链滚动；偶数局 golden 无变化。
- coverage 文档第 107 行已同步（未推迟到 07）；helpContent 两处补「审判者被捕获 = 审判者独赢」（怎么玩末句 + 审判者等级行），前端横幅/事件日志经 `displayFaction("secret-order")` 自然显示「审判者获胜」，无需改 Board.tsx。
- ruleset bump 0.4→0.5 仍归 issue 07。
