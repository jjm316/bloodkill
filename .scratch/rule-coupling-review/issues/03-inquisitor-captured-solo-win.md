# 03 审判者被捕获改判审判者独赢

Status: ready-for-agent

## 背景

ADR 0007（2026-10-03 裁决 P2）：语料两处写"审判者被捕获也独赢"，引擎实现平局（engine.py:835-837：winner="draw"、branch="inquisitor-captured"），无 ADR 记录的静默偏离。采语料改引擎。

## 改动

- engine.py:835-837：审判者被捕获 → `winner="secret-order"`；branch 维持 `"inquisitor-captured"`（语义改为独赢）。
- 注意分支顺序：该分支在家族分支/真诅咒判定之前，改后仍须确认审判者被捕获时不进真诅咒判定（审判者自己不是家族胜方领袖，现状已排除）。

## 验收

- 既有测试 `test_inquisitor_captured_is_draw` 改写为独赢断言（重命名避免误导）。
- golden 场景同步：审判者被捕获的对局 winner=secret-order。
- coverage 文档 `inquisitor-captured` 行同步（归 07 统一收尾亦可）。
