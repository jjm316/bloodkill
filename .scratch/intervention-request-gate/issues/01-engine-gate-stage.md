# 01 引擎：intervention gate 阶段建模

Status: resolved

spec: `.scratch/intervention-request-gate/spec.md`（Q1/Q3/Q5/Q8 结论的引擎侧落地）

## 改动清单

**阶段与命令**：
- attack 校验链（持盾拒绝、审判者 3 伤限制、匕首移交目标）后计算挡刀资格集（条件不变：未捕获、非攻击方、非目标、rank 未亮、目标未持扇）。
- 资格集为空 → 静默直接结算：**短路从「不开投票」前移到「不开门控」**，不产生任何门控事件（与 0.5 现有短路行为一致；跳过理由为 UX——无人可应的求助窗没有意义。「防扇泄露」旧理由已被 2026-10-04 技能产物公开性裁决作废，不得再引用）。
- 资格集非空 → pending `kind=intervention, stage="gate"`，actor=被攻击者，context 携带 attackerPlayerId 与 eligiblePlayerIds；发 `InterventionGateOpened {targetPlayerId, attackerPlayerId, eligiblePlayerIds}`。
- 新命令 `answer-intervention-request {need: bool}`：仅门控阶段、仅被攻击者合法；`need=true` → `InterventionGateAccepted` + 既有 `InterventionPollOpened`（poll 阶段与事件字段不变）；`need=false` → `InterventionGateDeclined {reason: "target-declined"}` + 攻击立即在原目标结算（复用无人自愿结算路径）。
- `timeout-intervention` 扩展 `{stage: "gate"}`：到期 → `InterventionGateDeclined {reason: "timeout"}` + 结算（Q1:A）。
- 错误码新增：`intervention.not-gate`、`intervention.not-target`。

**零改动重申**：poll/choice 两阶段全部语义（公开唱票、答后不可反悔、恰一人强制成立、三选一可全拒）一行不动。

**版本**：`ruleset_version` 0.5 → 0.6 硬切（new_game 与 checkpoint 校验两处 + 注释，同 0.4→0.5 先例）；persistence/恢复测试锚同步。

## 验收

- 引擎层新增分支用例全部落地（清单见 spec Testing Decisions 第 1、2 条）。
- 现有干涉用例经前置 `answer-intervention-request {need:true}` 全部转绿（助手更新）。
- `python -m unittest discover` 全绿（golden 允许暂红，归 05 重生成）。

## Comments

- 2026-10-04 implemented in commit `6cb604a` (branch `gate/01-engine`, merged to `spec/intervention-request-gate`). New `InterventionGateBranchTests` cover open/silent-skip/accept-relay/decline-settle/timeout/guards/mutex; helpers migrated (`test_engine`/`test_projection`/`test_rule_branches`/`test_server_sync`/`test_server_rooms`); `game_loop` walker got a minimal accept-only gate branch (needed by non-golden walker suites; decline mixing deferred to ticket 05). Suite: 203 tests green except 14 golden subTests (expected until 05). Deviation: single atomic commit (engine change + test migrations only green together).
