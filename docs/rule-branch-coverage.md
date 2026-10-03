# 规则分支覆盖清单

对应 issue 10 的交付物：每个已实现规则分支至少一条自动化测试。测试分布在
[`tests/test_engine.py`](../tests/test_engine.py)、[`tests/test_projection.py`](../tests/test_projection.py)、
[`tests/test_rule_branches.py`](../tests/test_rule_branches.py) 与 [`tests/test_properties.py`](../tests/test_properties.py)。
性质测试的随机 sweep 对多数分支给出额外的「随机路径」覆盖，下表只列确定性测试。

标记说明：

- `注入` = 该分支的触发物（shield/fan/第二张诅咒/已用技能）当前无法经公开命令产生，
  测试直接写入权威状态以验证防御闸门；对应发放路径由 issue 14 落地后转为自然触发。
- `@expectedFailure` = 已知缺陷的回归测试；issue 15/16 修复后标记已全部移除，当前无此类用例。

Issue 23 branch additions (干涉投票模型，ADR 0002):

| Branch | Behavior | Coverage |
| --- | --- | --- |
| `attack` 自动开投票 | `InterventionPollOpened` + 资格名单 + poll 阶段 pending | `AttackBranchTests.test_attack_opens_poll_hands_dagger_and_lists_eligible` |
| `attack` 资格集为空 | 不开投票直接结算（持扇注入） | `AttackBranchTests.test_fan_target_blocks_all_intervention_responders`、`test_attack_with_no_eligible_resolves_damage_directly` |
| `respond-intervention` 守卫 | 非资格者/攻击者/目标 → `intervention.not-eligible`；重复表态 → `intervention.already-responded`；无窗口 → `intervention.not-open` | `AttackBranchTests.test_respond_guards_target_attacker_and_double_answers`、`test_respond_without_window_is_rejected` |
| 0 人自愿 | `InterventionDeclined`(no-volunteers) + 攻击正常结算 + 匕首归目标 | `AttackBranchTests.test_all_declining_attack_leaves_dagger_with_wounded_target` |
| 恰 1 人自愿 | 干涉必然发生，目标无权拒绝；承伤/亮 rank/开技能窗/匕首归承伤者 | `RulesEngineTests.test_single_volunteer_forces_intervention_without_target_consent`；`AttackBranchTests.test_intervention_damage_reveals_responder_rank_and_opens_skill_window`、`test_intervention_responder_takes_the_dagger`、`test_shield_does_not_block_volunteering_as_responder` |
| ≥2 人自愿 | 进入 choice 阶段，目标可选其一或全部拒绝 | `InterventionPollBranchTests.test_target_picks_one_volunteer_and_declines_all`、`AttackBranchTests.test_choose_non_volunteer_responder_is_rejected` |
| choice 阶段守卫 | 非 `choice` 阶段 choose/decline → `intervention.not-choice`；非目标操作 → `player.not-actor`；choice 阶段 respond → `intervention.not-poll` | `AttackBranchTests.test_choose_or_decline_during_poll_stage_is_rejected`、`InterventionPollBranchTests.test_respond_and_choose_stage_guards` |
| 投票超时 | 未表态视为不干涉后按 0/1/≥2 分支结算 | `InterventionPollBranchTests.test_poll_timeout_with_no_volunteers_resolves_the_attack`、`test_poll_timeout_keeps_a_single_volunteer_forced`、`test_poll_timeout_with_two_volunteers_opens_the_choice_stage` |
| 三选一超时 | 自动"全部拒绝"（reason=timeout-declined） | `InterventionPollBranchTests.test_choice_timeout_auto_declines_all_volunteers` |
| 超时守卫 | 阶段不匹配/无窗口 → `intervention.not-open` | `InterventionPollBranchTests.test_timeout_guards` |
| 超时配置 | start-game 携带 30/60/90/120/180，非法值 `game.invalid-timeout`，缺省 90，开始后固定 | `InterventionPollBranchTests.test_host_timeout_configuration_is_fixed_at_start`、`test_default_timeout_is_ninety_seconds`、`test_invalid_timeout_choice_is_rejected` |
| 服务端倒计时 | Room 持有窗口 deadline 并注入投影；到期定时器代发 `timeout-intervention`；重启后过期窗口立即可结算 | `DeadlineWindowTests`（test_server_sync.py） |
| 投影公开性 | pending 携带 stage/responses/volunteerPlayerIds，旁观者同见；context 不暴露 | `ProjectionBranchTests.test_pending_intervention_actions_across_poll_and_choice_stages`、`test_pending_view_hides_private_context_and_publishes_votes` |
| 默认不挡刀 | 客户端 localStorage 偏好 + 常驻开关 + 自动代发（服务端超时兜底断线） | 手动验收；代发走同一 `respond-intervention` 命令路径 |

Issue 21 branch additions:

| Branch | Behavior | Coverage |
| --- | --- | --- |
| `start` 徽记展示事件 | 追加 `ClueIconsShown`：`pairs` 为 seat 环序"每人 → 左邻"，payload 无徽记内容 | `RulesEngineTests.test_start_logs_clue_icon_showing_pairs_without_icons` |
| 徽记不变量 | rank 3 徽记恒为敌对家族；审判者徽记 ∈ {rose, beast} 而真实所属为 `wild`（必不符） | `RulesEngineTests.test_rank_three_icon_is_hostile_and_inquisitor_icon_contradicts_affiliation` |
| 徽记投影 | viewer 块含本人 `clueIcon` 与右邻 `seenNeighbourClue`，仅此两枚 | `ProjectionTests.test_viewer_sees_own_clue_icon_and_right_neighbours_icon` |
| 徽记保密 | `players[]` 条目无徽记字段；旁观者与回放投影（`viewer=None`）无徽记 | `ProjectionTests.test_projection_hides_clue_icons_of_anyone_but_self_and_right_neighbour`；`RoomManagerTests.test_replay_returns_public_spectator_steps`；性质 `ProjectionSecrecyPropertyTests` |

Issue 20 branch additions:

| Branch | Behavior | Coverage |
| --- | --- | --- |
| rank 4 direct attack | no skill window | `SkillBranchTests.test_alchemist_does_not_open_from_direct_attack` |
| rank 4 intervention harm | protected player takes skill damage via a victim-choice reveal window (ADR 0006); a newly revealed rank opens the victim's window (ADR 0009), a marker reveal does not | `SkillBranchTests.test_alchemist_harm_targets_protected_player_without_skill_window`、`test_alchemist_harm_third_point_forced_rank_opens_victim_window` |
| rank 4 intervention heal | token-return window heals damage and returns a revealed token | `SkillBranchTests.test_alchemist_heal_opens_token_return_and_returns_marker` |
| rank 7 reaction | self damage with `source=reaction`; a marker reveal opens no window, the forced third-point rank reveal opens the attacker's window with `trigger=None` (ADR 0009 B4) | `SkillBranchTests.test_berserker_reaction_damages_attacker_without_new_window`、`test_berserker_reaction_third_point_forced_rank_opens_attacker_window`、`test_berserker_window_from_skill_damage_counters_the_skill_user` |

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
| `start` 奇数局 | 审判者 + 1 诅咒 | 同上；golden 7/9/11 |
| `start` 身份发放 | 不重复 rank、随机匕首持有者、`GameStarted` | `RulesEngineTests.test_setup_is_deterministic_and_odd_games_have_one_curse` |
| `pass-dagger` 相位/持有者 | `game.not-active` / `player.not-dagger-holder` | `CommandGuardBranchTests.test_pass_by_non_holder_is_rejected`、`test_action_command_during_intervention_window_is_rejected` |
| `pass-dagger` 传给自己 | `target.not-eligible` | `CommandGuardBranchTests.test_pass_to_self_is_rejected` |
| `pass-dagger` 合法 | `DaggerPassed` + 相位 | `RulesEngineTests.test_pass_dagger_and_idempotency` |
| `attack` 相位/持有者 | `game.not-active` / `player.not-dagger-holder` | `CommandGuardBranchTests.test_action_command_during_intervention_window_is_rejected` |
| `attack` 攻击自己 | `target.not-eligible` | `CommandGuardBranchTests.test_attack_to_self_is_rejected` |
| `attack` 盾目标 | `target.shielded`（注入） | `AttackBranchTests.test_shielded_target_is_rejected` |
| `attack` 审判者攻 3 伤 | `target.already-three-damage`（注入） | `AttackBranchTests.test_inquisitor_cannot_attack_target_with_three_damage` |
| `attack` 合法 | `AttackDeclared` + `InterventionPollOpened`、匕首移交、投票资格名单 | `AttackBranchTests.test_attack_opens_poll_hands_dagger_and_lists_eligible` |
| `attack` 目标持扇/资格集空 | 不开投票、直接结算伤害（注入） | `AttackBranchTests.test_fan_target_blocks_all_intervention_responders`、`test_attack_with_no_eligible_resolves_damage_directly` |
| `respond-intervention` 窗口/资格 | `intervention.not-open` / `intervention.not-eligible`（攻击者、目标均不可表态） | `AttackBranchTests.test_respond_guards_target_attacker_and_double_answers`、`test_respond_without_window_is_rejected` |
| `respond-intervention` 不可反悔 | 二次表态 → `intervention.already-responded` | `AttackBranchTests.test_respond_guards_target_attacker_and_double_answers` |
| `respond-intervention` 表态广播 | `InterventionResponded` 逐人实时公开，全员表态后按 0/1/≥2 分支结算 | `InterventionPollBranchTests.test_responses_are_broadcast_progressively`；分支见上方 issue 23 小节 |
| `choose-intervention`/`decline-intervention` 阶段守卫 | 投票阶段使用 → `intervention.not-choice`；三选一阶段表态 → `intervention.not-poll` | `AttackBranchTests.test_choose_or_decline_during_poll_stage_is_rejected`、`InterventionPollBranchTests.test_respond_and_choose_stage_guards` |
| `choose-intervention` 非自愿者 | `intervention.not-eligible` | `AttackBranchTests.test_choose_non_volunteer_responder_is_rejected` |
| 干涉承伤（恰一人自愿/目标选定） | 响应者承伤、展示 rank、开技能窗、匕首归响应者 | `RulesEngineTests.test_single_volunteer_forces_intervention_without_target_consent`；`AttackBranchTests.test_intervention_damage_reveals_responder_rank_and_opens_skill_window`、`test_intervention_responder_takes_the_dagger` |
| `decline-intervention` 演员 | 非目标在三选一阶段操作 → `player.not-actor` | `InterventionPollBranchTests.test_respond_and_choose_stage_guards` |
| 无人自愿/拒绝全部 | 目标承伤、攻击伤害可开技能窗、结算后匕首归目标（issue 22） | `RulesEngineTests.test_attack_decline_reveals_and_opens_skill_window`；`AttackBranchTests.test_all_declining_attack_leaves_dagger_with_wounded_target` |
| `choose-skill` 窗口/演员 | `skill.not-open` / `player.not-actor` | `SkillBranchTests.test_choose_skill_without_window_is_rejected`、`test_wrong_actor_cannot_choose_skill` |
| `choose-skill` 不使用 | `SkillDeclined` | `RulesEngineTests.test_attack_decline_reveals_and_opens_skill_window` |
| `choose-skill` 已使用 | `skill.already-used`（注入） | `SkillBranchTests.test_skill_already_used_is_rejected` |
| `choose-skill` rank 1 | `SkillUsed` + Quill `ResourceGranted` | `SkillBranchTests.test_elder_skill_grants_quill` |
| `choose-skill` rank 2 目标自己 | `skill.invalid-target` | `SkillBranchTests.test_assassin_skill_cannot_target_self` |
| `choose-skill` rank 2 合法 | 2 伤、每点开受害者自选亮牌窗、窗口答完后匕首移交受害者（ADR 0006）；受害者新亮 rank 开其技能窗且移交递延到窗口关闭后（ADR 0009/B12）；hash-seed 回归 `test_assassin_skill_scenario_log_is_identical_across_hash_seeds` | `SkillBranchTests.test_assassin_skill_deals_two_damage_opens_victim_choice_windows_and_hands_dagger`、`test_assassin_victim_self_chosen_rank_reveal_opens_skill_window_and_defers_dagger`、`test_assassin_skill_scenario_log_is_identical_across_hash_seeds` |
| `choose-skill` rank 2 捕获 | 终局后相位/匕首清空（issue 15 已修） | `SkillBranchTests.test_assassin_skill_capture_leaves_ended_phase` |
| 诅咒窗口触发（ADR 0003，规则 0.4） | 亮出 fleur-cross 即开唯一技能窗口：自选亮等级（1/2 点自选）、第 3 点被迫、挡刀承伤被迫，三路一致；非感应者技能伤害新亮出同样触发（ADR 0009 D1，`trigger=None`）；被感应者封印后永不再开 | `RulesEngineTests.test_inquisitor_rank_reveal_opens_the_curse_skill_window`；`CurseBranchTests.test_self_chosen_rank_reveal_opens_the_curse_window`、`test_third_damage_forced_rank_reveal_opens_the_curse_window`、`test_intervention_damage_opens_the_curse_window`、`test_skill_damage_self_chosen_rank_reveal_opens_the_curse_window`、`test_mentalist_seal_kills_the_curse_path_and_heal_cannot_unseal` |
| `choose-skill` 诅咒放弃 | `SkillDeclined`、技能永久失去、诅咒留供应区；后续不再出现第二次窗口；家族胜利照常结算不做诅咒判定 | `RulesEngineTests.test_inquisitor_rank_reveal_opens_the_curse_skill_window`；`CurseBranchTests.test_decline_keeps_curses_in_supply_and_closes_the_window_for_good`、`test_declined_curse_never_judges_a_family_win` |
| `choose-skill` 诅咒发动 | `SkillUsed` + 每卡一条私密 `CurseDistributed`、供应区清空、归属入终局判定；无伤害、匕首与行动阶段原样恢复 | `RulesEngineTests.test_curse_distribution_rides_the_skill_command_and_stays_private`；`CurseBranchTests.test_distribute_does_not_disturb_dagger_or_open_new_windows` |
| 诅咒发动校验 | 分配键与待分发集合不符（含空）→ `curse.invalid-count`；重复收件人 → `curse.duplicate-recipient`；未知/已捕获收件人 → `target.not-found` / `target.captured`；非审判者 → `player.not-eligible`；窗口已关 → `skill.not-open`；重复发动 → `skill.already-used`（注入） | `CurseBranchTests.test_distribute_with_no_curses_is_rejected`、`test_distribute_with_wrong_assignment_keys_is_rejected`、`test_distribute_to_unknown_or_captured_recipient_is_rejected`、`test_distribute_duplicate_recipient_is_rejected`、`test_distribute_by_non_inquisitor_is_rejected`、`test_distribute_then_decline_is_rejected_as_window_closed`、`test_repeated_use_in_a_reopened_window_is_rejected` |
| 旧 `distribute-curse` 命令移除 | 旧命令 → `command.unknown`，分发仅剩技能命令一条路径 | `CurseBranchTests.test_standalone_distribute_curse_command_is_gone` |
| `_end_game` 真诅咒夺胜 | 正常家族胜方领袖持真诅咒 → 胜方改写为审判者独赢（`inquisitor-true-curse`） | `CurseBranchTests.test_winning_leader_holding_true_curse_gives_the_inquisitor_a_solo_win` |
| `_apply_damage` 技能伤害亮牌（ADR 0006，旧口径"首伤展示 rank / 后续展示 affiliation"作废） | 一切伤害源统一走受害者自选亮牌窗（第 3 点被迫 rank、wild 色选窗）；感应者技能伤害带 `forceRank` 直接亮 rank，不开窗且把该 rank 写入 `skills_used` 构成永久封印（ADR 0009 方案 A）；本批新分支行与 golden 同步归 issue 07 | `SkillBranchTests.test_assassin_skill_deals_two_damage_opens_victim_choice_windows_and_hands_dagger`、`test_mentalist_damages_target_forces_rank_and_hands_dagger`、`test_mentalist_wound_on_shown_rank_falls_back_to_victim_choice`、`test_assassin_skill_scenario_log_is_identical_across_hash_seeds`；`SkillBranchTests.test_alchemist_harm_targets_protected_player_without_skill_window` |
| `_apply_damage` 第 4 伤 | `PlayerCaptured` + `GameEnded`、立即终局 | `EndGameBranchTests` 四项；golden 全部 |
| `_after_damage` 开窗总则（ADR 0009） | 本次伤害新亮出 rank 即开技能窗（攻击/挡刀/技能/反伤，自选或被迫，`trigger` 可为 None）；唯一例外 = 感应者强制亮出（封印，永不再开）；rank 4 仅 intervention 开窗（语料"仅在自己干涉后"）；已使用/已弃用/已封印永不再开；技能伤害永不触发干涉投票 | `RulesEngineTests.test_attack_decline_reveals_and_opens_skill_window`、`test_alchemist_attack_trigger_does_not_open_skill_window`、`test_inquisitor_rank_reveal_opens_the_curse_skill_window`；`AttackBranchTests.test_intervention_damage_reveals_responder_rank_and_opens_skill_window`；`SkillBranchTests.test_assassin_victim_self_chosen_rank_reveal_opens_skill_window_and_defers_dagger`、`test_alchemist_harm_third_point_forced_rank_opens_victim_window`、`test_berserker_reaction_third_point_forced_rank_opens_attacker_window`、`test_berserker_window_from_skill_damage_counters_the_skill_user`、`test_skill_window_only_opens_once_per_rank_reveal`、`test_mentalist_seal_kills_the_curse_path_and_heal_cannot_unseal` |
| `_end_game` 捕获家族领袖 | `captured-leader`，攻击方胜 | `EndGameBranchTests.test_captured_leader_branch` |
| `_end_game` 捕获普通成员 | `captured-player`，攻击方负 | `EndGameBranchTests.test_captured_non_leader_branch` |
| `_end_game` 审判者被捕获 | `inquisitor-captured`，审判者独赢（ADR 0007，原平局作废） | `EndGameBranchTests.test_inquisitor_captured_gives_the_inquisitor_a_solo_win` |
| `_end_game` 审判者为行动者 | `inquisitor-active-capture`（注入，14 后自然可达） | `EndGameBranchTests.test_inquisitor_active_capture_branch` |
| `_is_leader` 领袖判定 | 家族存活者最低 rank | 上述 leader/non-leader 两测试 |
| 状态校验 | damage/capture、revealed、匕首持有者不变量 | 性质 `StateInvariantPropertyTests`；`RulesEngineTests.test_checkpoint_resume_continues_without_double_applying` |

## 投影分支

| 分支 | 行为 | 覆盖测试 |
| --- | --- | --- |
| 观众投影 | 无身份、无 seed、无行动 | `ProjectionTests.test_spectator_sees_no_identity_or_seed` |
| 玩家投影 | 仅自己身份；公共玩家列表无身份字段 | `ProjectionTests.test_player_sees_only_their_own_identity` |
| 线索展示 | 伤害后才出现在投影 | `ProjectionTests.test_revealed_clues_appear_only_after_damage` |
| 诅咒视图 | 仅审判者见 `cursesToDistribute`（待分发卡 ID，分发后清空） | `ProjectionTests.test_curse_supply_is_visible_to_the_inquisitor_alone` |
| `legal_actions` 行动阶段 | 仅匕首持有者有 pass/attack；盾目标不可攻击；审判者的攻击列表过滤已受 3 伤目标（他人不受限） | `ProjectionTests.test_dagger_holder_actions_are_derived_from_authority`；`ProjectionTests.test_inquisitor_attack_actions_filter_three_damage_targets` |
| `legal_actions` 诅咒技能窗 | 审判者=放弃+发动两项，他人与观众无动作；分发完成后任何 viewer 不再有分发/技能动作 | `ProjectionTests.test_curse_window_offers_decline_and_use_to_the_inquisitor_only`、`test_after_distribution_no_viewer_has_a_curse_entry_point` |
| `legal_actions` 技能窗 | rank 2 列出目标；rank 1 无目标 | `ProjectionTests.test_rank_two_skill_window_offers_valid_targets`；`ProjectionBranchTests.test_elder_skill_window_offers_use_without_a_target` |
| `legal_actions` 干涉窗 | 投票阶段逐人 respond、三选一阶段目标专属选项 | `ProjectionBranchTests.test_pending_intervention_actions_across_poll_and_choice_stages` |
| `legal_actions` 终局/未知玩家 | 空列表 | `ProjectionBranchTests.test_legal_actions_empty_for_unknown_player_and_ended_game` |
| `_pending_view` | 不暴露私有 context；stage/responses/volunteerPlayerIds 公开 | `ProjectionBranchTests.test_pending_view_hides_private_context_and_publishes_votes` |
| 投影保密 sweep | 任意 viewer 不泄露 seed/他人身份/诅咒 | 性质 `ProjectionSecrecyPropertyTests` |

## 性质测试（tests/test_properties.py）

纯 stdlib `random.Random` sweep，14 组 seed × 6–12 人各两局；每次失败由 `subTest`
给出可复现 seed，并把 seed + 命令序列落盘到
`.scratch/blood-oath-replica/test-failures/`（`generate_walk` 可重建整条命令序列）：

- 确定性：同 seed + 命令序列 → 事件日志（revision/type/payload）一致；
- 恢复等价：任意位置 checkpoint → resume 后与不中断运行逐事件一致、revision 相等（无双重结算）；
- 幂等：走法中每条命令重复提交 → 返回原事件、revision 不变；
- 投影保密：任意 viewer（含观众）投影不含 seed、不含他人 faction/rank/clueIcon、不含 pending context，诅咒仅审判者可见；
- 状态不变量：每条命令后 damage/capture/revealed/匕首持有者/revision 连续性成立。

## 已知缺陷

当前无。历史缺陷均已关闭：issue 15/16 随 17 修复，issue 22（攻击无人干涉后匕首误退回攻击者）已于 2026-08-30 修复，见分支表 `decline-intervention` 行。
