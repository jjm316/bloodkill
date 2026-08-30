# 攻击无人干涉后匕首退回攻击者

Type: task
Blocked by: 10
Status: resolved

问题：规则语料 `turn.dagger-holder`（"攻击后匕首交给攻击目标"）与验收场景 `combat/attack-handoff`（"B 成为匕首持有者"）、`intervention/refused`（"B 接过匕首并承受该点伤害"）规定：攻击结算后匕首归受伤目标。但 `RulesEngine._after_damage` 的持有者判定把非 intervention 来源一律交给 `attackerPlayerId`：`attack` 来源（decline 干涉或无资格者直接结算）结算后匕首退回攻击者 A，而非受伤的 B。相邻分支行为不一致——同一攻击若亮 rank 开了技能窗，`_after_damage` 提前返回、匕首恰好留在 B 手中（正确）；没开技能窗才被改判回 A。该行由 19（targeted abilities 重构）引入，10 的性质测试只校验 `phase.activePlayerId == dagger_holder_id` 一致性，两种写法都自洽，故未拦住。

复现：任意 6 人局 → attack → decline-intervention → choose-reveal 完成展示。结果：`dagger_holder_id` = 攻击者，`phase.activePlayerId` = 攻击者，受伤目标无行动权。

输出：`_after_damage` 中 `attack` 与 `intervention` 来源统一交给承伤目标（`target.player_id`）；`skill`/`reaction` 来源保持现状（rank 2/5 由 `_choose_skill` 移交目标、rank 4 harm/rank 7 reaction 的联动语义属 20 范畴，本票不动）。同步补 decline 后匕首归属断言，并按流程重新生成 golden fixtures。

完成条件：decline 与无资格者两条结算路径后受伤目标持有匕首并可行动；性质测试照常通过；golden replay 重新生成后全量测试通过。

## Comments

## Answer

已修复（2026-08-30）：

- `blood_bound/engine.py` `_after_damage`：`source in {"attack", "intervention"}` 时匕首归承伤目标，`skill`/`reaction` 来源保持原判定不变。
- 测试：`AttackBranchTests` 新增 `test_declined_attack_leaves_dagger_with_wounded_target`（decline → 完成展示 → 目标持刀且 `legal_actions` 归目标）；`test_request_with_no_eligible_resolves_damage_directly` 补直接结算后持刀断言；`RulesEngineTests` 两条 decline 用例补技能窗分支与无技能窗分支的持刀断言。golden fixtures 因走法漂移重新生成，全量 113 通过（5 skip 为原有服务器依赖）。
- 文档：`docs/rule-branch-coverage.md` 对应分支行与已知偏差清单已更新。
