# 干涉响应者未接过匕首

Type: task
Blocked by: 10
Status: resolved

问题：10 的性质测试网络发现：`RulesEngine._choose_intervention` 只把 `phase.activePlayerId` 置为响应者，未更新 `dagger_holder_id`。干涉后匕首仍留在攻击目标手中：`phase` 说响应者行动、`legal_actions` 却只给攻击目标发行动权，且与语料验收场景 `intervention/selected-responder`「C 接过匕首并承受该点伤害」冲突。引擎其余路径（pass、attack 移交、decline 结算）均保持 `phase.activePlayerId == dagger_holder_id`，唯独此分支不一致。

复现：任意 6 人局 → attack → request-intervention → choose-intervention。结果：`dagger_holder_id` = 攻击目标，`phase.activePlayerId` = 响应者，攻击目标持有全部行动。

输出：`_choose_intervention` 中同步 `state.dagger_holder_id = responder.player_id` + 回归测试（去掉 10 中 `test_intervention_responder_takes_the_dagger` 的 `expectedFailure` 标记）。

完成条件：干涉后响应者持有匕首并可行动；攻击目标无行动权；性质测试随机走法在修复后照常通过。

## Comments

## Answer

Resolved as part of issue 17: selecting an intervention responder transfers the dagger and action phase to that responder.

- 2026-08-21：由 10 的性质测试网络（`tests/test_properties.py` 随机走法 + 分支测试）发现并立案；10 以 `@unittest.expectedFailure` 回归测试记录现状。
