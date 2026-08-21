# 抑制未实现位阶的技能窗

Type: task
Blocked by: 12（venv）
Status: resolved

问题：rank 3–9 的能力在 `content/catalog.json` 中标为 `unimplemented`，但引擎 `_apply_damage` 在攻击伤害展示 rank 时，对任意 rank（含 fleur-cross 审判官）都会开启技能窗；`_choose_skill use=True` 对 rank 3–9 与 fleur-cross 只是记 `skills_used`、发 `SkillUsed`，无任何效果。玩家会看到一个点了没反应的技能按钮。

输出：在 `_apply_damage` 按已实现位阶门控技能窗开启（仅 rank 1/2 开窗）；补测试覆盖 rank 3–9 与 fleur-cross 不开窗。`legal_actions` 无需改（窗口不再打开，自然无无效果选项）。

完成条件：rank 1/2 照常开窗；rank 3–9 与 fleur-cross 展示 rank 后不进入 skill pending；客户端不出现无效果的技能按钮；相关测试通过。

## Answer

已交付：

- [`blood_bound/engine.py`](../../blood_bound/engine.py) 新增模块常量 `_IMPLEMENTED_SKILL_RANKS = frozenset({1, 2})`，并在 `_apply_damage` 的技能窗开启条件追加 `target.rank in _IMPLEMENTED_SKILL_RANKS`。rank 3–9 与 fleur-cross 展示 rank 后不再进入 skill pending。
- [`tests/test_engine.py`](../../tests/test_engine.py)：修正 `test_attack_decline_reveals_and_opens_skill_window` 目标改为已实现位阶（rank 1/2）；新增 `test_unimplemented_rank_does_not_open_skill_window`（rank 3–9）与 `test_inquisitor_rank_reveal_does_not_open_skill_window`（fleur-cross）。
- 全量 `python -m unittest discover -v`：33 项全部通过。
- 实现位阶集合后续由 [14](14-abilities-resource-economy.md) 扩展为 1–9。
