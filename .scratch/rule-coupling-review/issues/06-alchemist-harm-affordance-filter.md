# 06 炼金 harm 选项过滤盾目标（projection 小修）

Status: resolved

## 背景

耦合点 B1 的口径不一致小修（2026-10-03 批量确认附带）：刺客（projection.py:73）、感应者（projection.py:120）的合法目标列表已过滤持盾者，炼金 harm 的选项生成（projection.py:63-65）没滤——玩家可以点到持盾的被保护者，提交才报 `target.shielded`。

## 改动

- projection.py:63-65 的炼金 harm 选项过滤持盾目标，与其他技能 affordance 口径对齐。纯投影改动，引擎校验逻辑不动。

## 验收

- 持盾者不出现在炼金 harm 的可选列表；引擎行为不变（仍拒绝该命令，防御性保留）。

## Comments

- 2026-10-03（实现销案）：`projection.py` rank 4 分支改为先取 `protected`，被保护者持盾（`resources.shield`）时不追加 `mode:"harm"` 选项，与刺客（rank 2）/感应者（rank 5）目标列表口径对齐；heal 选项逻辑不动，引擎 `_apply_damage` 的 `target.shielded` 防御性拒绝原样保留。说明：正常对局中攻击在声明时即拒绝持盾目标、且干涉链内无法插入发盾命令，"持盾被保护者的炼金窗"当前只能经注入状态到达，故测试按既有防御门惯例直接注入 `resources["shield"]=1`。分支测试 `SkillBranchTests.test_alchemist_harm_affordance_filters_shielded_protected_player`（含引擎仍拒绝且不烧技能的断言）；覆盖行见 `docs/rule-branch-coverage.md` Issue 06 小节。ruleset 不动（bump 归 07），golden 为纯事件回放无 `legalActions`、无需重生成。
