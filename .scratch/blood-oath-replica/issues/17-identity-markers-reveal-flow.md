# 身份标记模型与自选展示流程（14 子票：地基）

Type: task
Blocked by: 10、13
Status: resolved

问题：引擎当前是「1 rank + 1 affiliation」的旧线索模型，伤害结算自动按 rank → affiliation 顺序展示，不符合 [14](14-abilities-resource-economy.md) 已裁决的身份标记模型（每名玩家 3 张标记 = 1 等级 + 2 身份标记，受伤**自选**展示身份或 rank；第 3 点被迫亮 rank；挡刀被迫亮 rank 并开技能窗，decline = 永久失去技能）。技能窗无一次性闩锁，且仅在 attack 触发时开启。这是 14 全部能力票的地基：18/19/20 的资源与能力语义都建立在新标记模型和新结算流程之上。

语义依据：[14](14-abilities-resource-economy.md) 票面「已裁决」与 [rules-corpus-user-extract.md](../rules-corpus-user-extract.md) 的「身份标记组成（2026-08-22 澄清）」。

输出：

1. **标记模型与 schema**：`Player.identity_markers`（2 张，取值 `rose`/`beast`/`unknown`/`wild`），组成由 rank 决定——rank 1/5/6 = 两张本家族色，2/3/4 = 两张 `unknown`，7/8/9 = 一张本家族色 + 一张 `unknown`，审判官 = 两张 `wild`；`Player.revealed` 改为 token id 集合（`rank` / `marker-0` / `marker-1`）；开局时 harlequin（rank 3）的 clue icon 改为敌对家族。`EngineState.schema_version` 升 2、`ruleset_version` 升 `0.2`（旧存档经 ruleset 校验自然拒绝，不另写迁移）。
2. **伤害结算重构**：`DamageApplied` 之后逐点结算；每点伤害若存在真实选择（≥2 张未展示标记且未被强制），开新 pending `reveal`（actor = 受伤者），由新命令 `choose-reveal {token, color?}` 继续结算；第 3 点伤害与 `trigger == "intervention"` 强制亮 rank（rank 已展示则回落为自选身份标记）；只剩 1 张可展示标记时自动展示，但 `wild` 标记必须开窗选颜色（`color` ∈ rose/beast，缺失报 `reveal.color-required`）。多点伤害（如 rank 2 技能）中途可连续开窗。结算上下文（resume dict）必须携带 `attackerPlayerId` / `protectedPlayerId` / `remaining` / `forceRank` / `followup`，供 19/20 的能力挂钩使用。
3. **技能窗闩锁与干涉触发**：`trigger ∈ {attack, intervention}` 且 rank 因该次伤害**首次**展示且 rank ∈ `_IMPLEMENTED_SKILL_RANKS` 且未闩锁时开窗，开窗即闩锁（`skill_offered`）。闩锁同时实现「decline = 永久失去技能」与「退回 rank 后二次展示不再开窗」（后者由 20 的 alchemist 检验）。`_IMPLEMENTED_SKILL_RANKS` 本票保持 `{1, 2}` 不变——后续子票逐个加入，全程维持 13 的「无无效技能按钮」不变量。
4. **随重构修复 15/16**：`_end_game` 统一清空 `dagger_holder_id`（ended 后无匕首，契约要求）；`_choose_intervention` 响应者接过匕首（`intervention/selected-responder` 场景）。去掉 `tests/test_rule_branches.py` 中两个 `@unittest.expectedFailure` 标记并把 [15](15-assassin-capture-phase.md)、[16](16-intervention-dagger-handoff.md) 标记 resolved（Answer 注明由 17 的重构修复）。
5. **同步面**：projection——公开玩家 `revealed` 改为 `{rank?, markers: [color|null, color|null]}`（`null` = 未展示；未展示标记的值不得泄露，标记组成会泄露 rank 区间信息），viewer 块增加 `identityMarkers`；persistence——`_state_to_dict` 补齐新字段；`game_loop.run_deterministic_game` 处理 reveal 窗口（确定性选 rank）；性质测试 `generate_walk` 的 pending 解析改为消费 `legal_actions`（新窗口类型随之自然覆盖），不变量断言更新（revealed ⊆ 3 张 token）；golden 6–12 全量重生成（`python -m tests.test_golden_replays`）；`domain-model-contract.md` 的 2026-08-22 注记转正为正文；`server/PROTOCOL.md` 与 `client/src/types.ts`、`Board.tsx` 的 `revealed` 形状同步。

完成条件：

- 自选展示 / 第 3 伤强制 rank / 挡刀强制 rank / 审判官 wild 选色均有分支测试；
- 标记按 rank 组成正确（同色对、双 ?、一色一 ?），投影只展示已展示标记的值；
- 闩锁行为有测试：rank 第二次展示不开窗；decline 后不再开窗；
- 15/16 断言正常通过（无 expectedFailure），15/16 票面标 resolved；
- 全量 `.venv\Scripts\python.exe -m unittest discover -v` 通过，golden 重生成后双向验证通过。

## Answer

已完成身份标记与自选揭示重构：`Player.identity_markers` 按 rank 生成两张身份标记，`revealed` 使用 `rank`、`marker-0`、`marker-1` token 集合并保存已公开值；伤害逐点结算并支持 `choose-reveal`，第三点和挡刀强制 rank，wild 标记要求颜色。schema 升至 2、ruleset 升至 0.2，投影、持久化、确定性 runner 与 golden fixtures 已同步。技能窗口仅由 attack/intervention 的首次 rank 揭示触发，decline 锁定技能。终局清空匕首并固定 ended phase；干预响应者接管匕首。15/16 expectedFailure 已移除并标记 resolved。

## Comments

- 2026-08-24：由 14 拆分出的地基子票（拆分讨论见 14 票面 Comments）。本票约占 14 总工作量的六成以上，不能再按 rank 平切——任何中间态都是「旧流程配新模型」的伪状态。15/16 的修复落在本票是因为重构后保留旧缺陷反而需要刻意维护。
