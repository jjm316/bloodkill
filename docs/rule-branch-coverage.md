# 规则分支覆盖清单

对应 issue 10 的交付物：每个已实现规则分支至少一条自动化测试。测试分布在
[`tests/test_engine.py`](../tests/test_engine.py)、[`tests/test_projection.py`](../tests/test_projection.py)、
[`tests/test_rule_branches.py`](../tests/test_rule_branches.py) 与 [`tests/test_properties.py`](../tests/test_properties.py)。
性质测试的随机 sweep 对多数分支给出额外的「随机路径」覆盖，下表只列确定性测试。

标记说明：

- `注入` = 该分支的触发物（shield/fan/第二张诅咒/已用技能）当前无法经公开命令产生，
  测试直接写入权威状态以验证防御闸门；对应发放路径由 issue 14 落地后转为自然触发。
- `@expectedFailure` = 已知缺陷的回归测试，由 issue 15/16 修复后去掉标记。

## 引擎分支

| 分支 | 行为 | 覆盖测试 |
| --- | --- | --- |
| `apply` 游戏不匹配 | `game.not-found` | `CommandGuardBranchTests.test_command_for_another_game_is_rejected` |
| `apply` 幂等重放 | 同 `command_id` + 同体 → 返回原事件、revision 不变 | `RulesEngineTests.test_pass_dagger_and_idempotency`；性质 `IdempotencyPropertyTests` |
| `apply` 同 id 异体 | `command.id-reuse` | `CommandGuardBranchTests.test_reused_command_id_with_different_body_is_rejected` |
| `apply` 过期 revision | `game.revision-conflict` | `RulesEngineTests.test_stale_revision_is_rejected` |
| `apply` 终局后命令 | `game.already-ended` | `CommandGuardBranchTests.test_command_after_game_end_is_rejected` |
| `apply` 相位变化 | 追加 `PhaseChanged` | `RulesEngineTests.test_pass_dagger_and_idempotency` |
| `join` 非 setup | `game.not-setup` | `SetupBranchTests.test_join_after_start_is_rejected` |
| `join` 空 playerId | `player.not-eligible` | `SetupBranchTests.test_join_without_player_id_is_rejected` |
| `join` 重复玩家 | `game.duplicate-player` | `SetupBranchTests.test_duplicate_player_is_rejected` |
| `join` 第 13 人 | `game.player-count` | `SetupBranchTests.test_thirteenth_player_is_rejected` |
| `join` 座位占用/越界 | `game.seat-occupied` | `SetupBranchTests.test_seat_conflict_and_out_of_range_are_rejected` |
| `join` 自动选座 | 最小空闲座位 + `PlayerJoined` | `SetupBranchTests.test_auto_seat_assigns_lowest_free_seat` |
| `start` 非 setup | `game.not-setup` | `SetupBranchTests.test_second_start_is_rejected` |
| `start` 人数不足 | `game.player-count` | `SetupBranchTests.test_start_with_fewer_than_six_is_rejected` |
| `start` 偶数局 | 双家族各半、无诅咒 | `RulesEngineTests.test_setup_is_deterministic_and_odd_games_have_one_curse`；golden 6/8/10/12 |
| `start` 奇数局 | 审判官 + 1 诅咒 | 同上；golden 7/9/11 |
| `start` 身份发放 | 不重复 rank、随机匕首持有者、`GameStarted` | `RulesEngineTests.test_setup_is_deterministic_and_odd_games_have_one_curse` |
| `pass-dagger` 相位/持有者 | `game.not-active` / `player.not-dagger-holder` | `CommandGuardBranchTests.test_pass_by_non_holder_is_rejected`、`test_action_command_during_intervention_window_is_rejected` |
| `pass-dagger` 传给自己 | `target.not-eligible` | `CommandGuardBranchTests.test_pass_to_self_is_rejected` |
| `pass-dagger` 合法 | `DaggerPassed` + 相位 | `RulesEngineTests.test_pass_dagger_and_idempotency` |
| `attack` 相位/持有者 | `game.not-active` / `player.not-dagger-holder` | `CommandGuardBranchTests.test_action_command_during_intervention_window_is_rejected` |
| `attack` 攻击自己 | `target.not-eligible` | `CommandGuardBranchTests.test_attack_to_self_is_rejected` |
| `attack` 盾目标 | `target.shielded`（注入） | `AttackBranchTests.test_shielded_target_is_rejected` |
| `attack` 审判官攻 3 伤 | `target.already-three-damage`（注入） | `AttackBranchTests.test_inquisitor_cannot_attack_target_with_three_damage` |
| `attack` 合法 | `AttackDeclared`、匕首移交、干涉窗口与资格名单 | `AttackBranchTests.test_attack_declares_window_hands_dagger_and_lists_eligible` |
| `attack` 目标持扇 | 资格名单为空（注入） | `AttackBranchTests.test_fan_target_blocks_all_intervention_responders` |
| `request-intervention` 窗口/演员 | `intervention.not-open` / `player.not-actor` | `AttackBranchTests.test_wrong_actor_cannot_request_or_decline_intervention`、`test_choose_intervention_without_window_is_rejected` |
| `request-intervention` 无资格者 | 直接结算伤害、无 `InterventionOpened` | `AttackBranchTests.test_request_with_no_eligible_resolves_damage_directly` |
| `request-intervention` 有资格者 | `InterventionOpened` + `requested` | `ProjectionBranchTests.test_pending_intervention_actions_before_and_after_request` |
| `choose-intervention` 未请求 | `intervention.not-open` | `AttackBranchTests.test_choose_intervention_before_request_is_rejected` |
| `choose-intervention` 无资格者 | `intervention.not-eligible` | `AttackBranchTests.test_choose_ineligible_responder_is_rejected` |
| `choose-intervention` 合法 | 响应者承伤、展示 rank、无技能窗、匕首归响应者（现状缺陷 → issue 16） | `RulesEngineTests.test_intervention_requires_rank_in_supply`；`AttackBranchTests.test_intervention_damage_reveals_responder_rank_without_skill_window`；`test_intervention_responder_takes_the_dagger`（`@expectedFailure`） |
| `decline-intervention` 演员 | `player.not-actor` | `AttackBranchTests.test_wrong_actor_cannot_request_or_decline_intervention` |
| `decline-intervention` 合法 | 目标承伤、攻击伤害可开技能窗 | `RulesEngineTests.test_attack_decline_reveals_and_opens_skill_window` |
| `choose-skill` 窗口/演员 | `skill.not-open` / `player.not-actor` | `SkillBranchTests.test_choose_skill_without_window_is_rejected`、`test_wrong_actor_cannot_choose_skill` |
| `choose-skill` 不使用 | `SkillDeclined` | `RulesEngineTests.test_attack_decline_reveals_and_opens_skill_window` |
| `choose-skill` 已使用 | `skill.already-used`（注入） | `SkillBranchTests.test_skill_already_used_is_rejected` |
| `choose-skill` rank 1 | `SkillUsed` + Quill `ResourceGranted` | `SkillBranchTests.test_elder_skill_grants_quill` |
| `choose-skill` rank 2 目标自己 | `skill.invalid-target` | `SkillBranchTests.test_assassin_skill_cannot_target_self` |
| `choose-skill` rank 2 合法 | 2 伤、匕首移交、不开新窗口 | `SkillBranchTests.test_assassin_skill_deals_two_damage_hands_dagger_and_opens_no_new_window` |
| `choose-skill` rank 2 捕获 | 终局后相位/匕首残留（现状缺陷 → issue 15） | `SkillBranchTests.test_assassin_skill_capture_leaves_ended_phase`（`@expectedFailure`） |
| `distribute-curse` 无诅咒/非活跃 | `curse.invalid-count` | `CurseBranchTests.test_distribute_curse_without_curses_is_rejected` |
| `distribute-curse` 非审判官 | `player.not-eligible` | `CurseBranchTests.test_distribute_curse_by_non_inquisitor_is_rejected` |
| `distribute-curse` 分配键不符 | `curse.invalid-count` | `CurseBranchTests.test_distribute_curse_with_wrong_assignment_keys_is_rejected` |
| `distribute-curse` 未知/已捕获收件人 | `target.not-found` / `target.captured` | `CurseBranchTests.test_distribute_curse_to_unknown_recipient_is_rejected`、`test_distribute_curse_to_captured_recipient_is_rejected` |
| `distribute-curse` 重复收件人 | `curse.duplicate-recipient`（注入） | `CurseBranchTests.test_distribute_curse_duplicate_recipient_is_rejected` |
| `distribute-curse` 合法 | `CurseDistributed`、诅咒清空 | `RulesEngineTests.test_curse_distribution_is_private_to_the_inquisitor_command` |
| `_apply_damage` 首伤展示 rank / 后续展示 affiliation | `ClueRevealed` 种类 | `ProjectionTests.test_revealed_clues_appear_only_after_damage`；`SkillBranchTests.test_skill_window_only_opens_once_per_rank_reveal` |
| `_apply_damage` 第 4 伤 | `PlayerCaptured` + `GameEnded`、立即终局 | `EndGameBranchTests` 四项；golden 全部 |
| `_apply_damage` 攻击伤害开技能窗 | 仅 rank 1/2、仅 `source=attack` | `RulesEngineTests.test_attack_decline_reveals_and_opens_skill_window`、`test_unimplemented_rank_does_not_open_skill_window`、`test_inquisitor_rank_reveal_does_not_open_skill_window`；`AttackBranchTests.test_intervention_damage_reveals_responder_rank_without_skill_window` |
| `_end_game` 捕获家族领袖 | `captured-leader`，攻击方胜 | `EndGameBranchTests.test_captured_leader_branch` |
| `_end_game` 捕获普通成员 | `captured-player`，攻击方负 | `EndGameBranchTests.test_captured_non_leader_branch` |
| `_end_game` 审判官被捕获 | `inquisitor-captured`，平局 | `EndGameBranchTests.test_inquisitor_captured_is_draw` |
| `_end_game` 审判官为行动者 | `inquisitor-active-capture`（注入，14 后自然可达） | `EndGameBranchTests.test_inquisitor_active_capture_branch` |
| `_is_leader` 领袖判定 | 家族存活者最低 rank | 上述 leader/non-leader 两测试 |
| 状态校验 | damage/capture、revealed、匕首持有者不变量 | 性质 `StateInvariantPropertyTests`；`RulesEngineTests.test_checkpoint_resume_continues_without_double_applying` |

## 投影分支

| 分支 | 行为 | 覆盖测试 |
| --- | --- | --- |
| 观众投影 | 无身份、无 seed、无行动 | `ProjectionTests.test_spectator_sees_no_identity_or_seed` |
| 玩家投影 | 仅自己身份；公共玩家列表无身份字段 | `ProjectionTests.test_player_sees_only_their_own_identity` |
| 线索展示 | 伤害后才出现在投影 | `ProjectionTests.test_revealed_clues_appear_only_after_damage` |
| 诅咒视图 | 仅审判官见 `cursesToDistribute` | `ProjectionTests.test_inquisitor_gets_private_curse_assignment_view` |
| `legal_actions` 行动阶段 | 仅匕首持有者有 pass/attack；盾目标不可攻击 | `ProjectionTests.test_dagger_holder_actions_are_derived_from_authority` |
| `legal_actions` 技能窗 | rank 2 列出目标；rank 1 无目标 | `ProjectionTests.test_rank_two_skill_window_offers_valid_targets`；`ProjectionBranchTests.test_elder_skill_window_offers_use_without_a_target` |
| `legal_actions` 干涉窗 | 请求前后选项集合 | `ProjectionBranchTests.test_pending_intervention_actions_before_and_after_request` |
| `legal_actions` 终局/未知玩家 | 空列表 | `ProjectionBranchTests.test_legal_actions_empty_for_unknown_player_and_ended_game` |
| `_pending_view` | 不暴露私有 context | `ProjectionBranchTests.test_pending_view_hides_private_context` |
| 投影保密 sweep | 任意 viewer 不泄露 seed/他人身份/诅咒 | 性质 `ProjectionSecrecyPropertyTests` |

## 性质测试（tests/test_properties.py）

纯 stdlib `random.Random` sweep，14 组 seed × 6–12 人各两局；每次失败由 `subTest`
给出可复现 seed，并把 seed + 命令序列落盘到
`.scratch/blood-oath-replica/test-failures/`（`generate_walk` 可重建整条命令序列）：

- 确定性：同 seed + 命令序列 → 事件日志（revision/type/payload）一致；
- 恢复等价：任意位置 checkpoint → resume 后与不中断运行逐事件一致、revision 相等（无双重结算）；
- 幂等：走法中每条命令重复提交 → 返回原事件、revision 不变；
- 投影保密：任意 viewer（含观众）投影不含 seed、不含他人 faction/rank/clueIcon、不含 pending context，诅咒仅审判官可见；
- 状态不变量：每条命令后 damage/capture/revealed/匕首持有者/revision 连续性成立。

## 已知缺陷

- issue 15：rank 2 技能捕获后 `phase`/匕首残留 —— `test_assassin_skill_capture_leaves_ended_phase`（`@expectedFailure`）
- issue 16：干涉响应者未接过匕首 —— `test_intervention_responder_takes_the_dagger`（`@expectedFailure`）
