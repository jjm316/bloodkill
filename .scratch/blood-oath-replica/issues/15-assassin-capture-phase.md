# rank 2 刺客技能捕获后的相位/匕首残留

Type: task
Blocked by: 10
Status: open

问题：10 的性质测试网络发现：`RulesEngine._choose_skill` 的 rank 2 分支在 `_apply_damage` 返回后无条件写回 `dagger_holder_id` 与 `phase = action`。当刺客技能的 2 点伤害造成目标第 4 点伤害时，`_end_game` 已把状态置为 `status=ended`/`phase=ended`，随后这两行又把相位改回 `action`、匕首指向已捕获玩家。违反领域契约「`status = ended` 后不存在匕首」；`project_state` 会向 UI 展示一个不存在的 action 相位与已捕获的匕首持有者。正常攻击路径由 `_end_game` 最后写入相位，不受影响——该残留仅由 rank 2 技能路径引入。

复现（`probe-0`，6 人局）：join p0–p5 → start → 对 p0 两次攻击结算（decline intervention/skill，共 2 伤）→ 攻击 p2（rank 2）结算 → p2 选择 `choose-skill use=true targetPlayerId=p0`。结果：`status=ended`、`phase={"kind":"action","activePlayerId":"p0"}`、`dagger_holder_id=p0`（已捕获）。

输出：最小修复 + 回归测试。修复候选：rank 2 分支仅在 `state.status == "active"` 时更新匕首/相位；或由 `_end_game` 统一清空 `dagger_holder_id`（该残留也存在于正常攻击终局路径，只是相位未被覆盖）。回归测试即去掉 10 中 `test_assassin_skill_capture_phase_residue` 的 `expectedFailure` 标记，性质测试恢复「ended 后相位为 ended」断言。

完成条件：rank 2 技能捕获后 `phase.kind == "ended"`；`status=ended` 时匕首不指向已捕获玩家（或为空）；相关测试正常通过。

## Comments

- 2026-08-21：由 10 的性质测试网络（`tests/test_properties.py` 状态不变量 sweep）发现并立案；10 以 `@unittest.expectedFailure` 回归测试记录现状。
