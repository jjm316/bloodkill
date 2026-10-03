# 07 ruleset bump 0.4→0.5 + coverage + golden + helpContent + 文档销案

Status: ready-for-agent

依赖：01–05 与 `.scratch/blood-oath-replica/issues/26-wild-color-question-option.md` 完成后收尾（06 可独立先行）。26 的 wild 问号分支同批进 golden 与 coverage。

## 改动清单

**版本与覆盖**：
- `ruleset_version` 0.4 → 0.5（硬切，同 0.2→0.3、0.3→0.4 先例；进行中旧存档不兼容）。
- `docs/rule-branch-coverage.md`：**改写第 102 行**（旧口径"技能伤害首伤展示 rank / 后续展示 affiliation"作废，按 ADR 0006 新规则书写）；为本批新分支加行（技能伤害自选亮牌、技能伤害/反伤亮 rank 开窗、感应者封印、审判者被捕独赢、持盾反伤、三类窗口超时默认）。

**golden**：覆盖上述新分支的回放同步（重点：技能伤害亮牌窗、封印写 `skills_used`、超时命令确定性）。

**帮助文案（helpContent，E1 清单 11 条）**：
1. 技能伤害亮牌由受害者自选（P1）
2. 封印：被感应者点出等级 = 技能永久封印，炼金不可解；用过/弃过也不再开窗（P4+P3）
3. 已亮 rank 的玩家不能再挡刀（C1 推论）
4. 审判者被捕获 = 审判者独赢，别随手打死疑似审判者（P2）
5. 捕获归因链：攻击=攻击者、挡刀=原攻击者、技能=使用者、反伤=狂战士（D6）
6. 技能误捕非领袖 = 技能方阵营负（B13）
7. 诅咒发给自己 = 浪费（D2）
8. 技能伤害/反伤也触发守护者剑盾归还（B7）
9. 扇可以给自己（B10）
10. 技能伤害不触发干涉投票，但新亮出 rank 会开技能窗（感应者例外）（A3 新表述）
11. 单人窗口超时会替你做什么（自动亮/退排序第一张、色选取问号、技能窗视为放弃）（L4，随 05 上线）

**文档销案**：
- `.scratch/blood-oath-replica/rule-conflicts-from-chinese-manual.md` 第 7 条：P4 新总则下"反伤可触发技能窗口"为**正确**，矛盾销案（加标注，不删原文）。

## 验收

- `python -m unittest discover -v` 全绿；golden 全绿。
- coverage 文档行数与新增分支测试一一对应。
