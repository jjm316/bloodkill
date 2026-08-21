# 规则测试与性质测试

Type: task
Blocked by: 04, 05, 06, 13
Status: resolved

问题：为已实现的规则建立自动化测试网，覆盖规则分支补全、性质测试与整局 replay。范围已收缩：不含平衡模拟 CLI、性能基线、网络模拟、浏览器 E2E（后两者归 09）。性质测试用纯 stdlib 随机 sweep，不引入 Hypothesis；不配置 CI，不引入 coverage.py。

输出：规则分支覆盖清单（每个已实现分支至少一条测试）、手写 stdlib 性质测试（确定性/恢复等价/幂等/投影保密/状态不变量）、6–12 人 golden replay fixtures、可复现失败 seed。

完成条件：

- 每个已实现规则分支有至少一条自动化测试；
- 同一 seed + 命令序列 → 事件日志一致；
- checkpoint → resume 后续结果一致、无双重结算；
- 重复 `command_id` 幂等；
- 任意 viewer 投影不泄露 seed / 他人身份 / 诅咒；
- 失败时给出可复现 seed 与命令序列。

## Answer

已交付，全部纯测试、纯 stdlib（无 Hypothesis / coverage.py / CI）：

- [`tests/test_rule_branches.py`](../../tests/test_rule_branches.py)：补齐 49 项确定性分支测试。覆盖此前空白的拒绝路径（`game.not-found`/`command.id-reuse`/`game.already-ended`/`game.not-setup`/`game.seat-occupied`/`player.not-dagger-holder` 等）、注入式防御闸门（shield 目标、扇阻挡干涉、审判官 3 伤限制、技能已使用、双诅咒重复收件人——触发物由 14 发放后转自然触发）、四个终局分支（`captured-leader`/`captured-player`/`inquisitor-captured`/`inquisitor-active-capture`，末者经注入 rank 未展示的 3 伤响应者触发）与投影分支。
- [`tests/test_properties.py`](../../tests/test_properties.py)：手写 `random.Random(seed)` sweep，14 组 seed × 6–12 人各两局，随机走法只提交引擎接受的命令。五类性质：确定性（同 seed+命令序列→事件日志一致）、恢复等价（任意位置 checkpoint→resume 逐事件一致、revision 相等、无双重结算）、幂等（重复 `command_id` 返回原事件）、投影保密（任意 viewer 无 seed/他人身份/诅咒/pending context）、状态不变量（每条命令后 damage/capture/revealed/匕首/revision 连续性）。失败由 `subTest` 给出 seed，并把 seed+命令序列落盘 `.scratch/blood-oath-replica/test-failures/`（`generate_walk` 可重建）。
- [`tests/fixtures/golden-6..12.json`](../../tests/fixtures/) + [`tests/test_golden_replays.py`](../../tests/test_golden_replays.py)：6–12 人整局 golden replay fixture（完整存档文档：事件哈希链+快照校验和+命令日志），双向验证——fixture 经存档管线完整回放、当前引擎逐字节复现；规则变更导致 golden 漂移即失败，重生成 `python -m tests.test_golden_replays`。
- [`docs/rule-branch-coverage.md`](../../docs/rule-branch-coverage.md)：规则分支覆盖清单，逐分支映射到测试，并标注注入测试与已知缺陷。
- 测试网发现两个已实现规则缺陷并立案：[15](15-assassin-capture-phase.md)（rank 2 技能捕获后 `phase`/匕首残留）、[16](16-intervention-dagger-handoff.md)（干涉响应者未接过匕首，违背景 `intervention/selected-responder`）。10 以 `@unittest.expectedFailure` 回归测试记录现状，15/16 修复后去标记。
- 全量 `python -m unittest discover -v`：91 项全部通过（2 项 expected failure 为 15/16 回归测试），14.6s。

## Comments

- 2026-08-21：用户裁决 10 收缩为纯测试票。砍掉平衡模拟 CLI、性能基线/帧率预算、CI 与覆盖率；网络模拟与浏览器多窗口 E2E 后置 09。性质测试用纯 stdlib 随机 sweep（`random.Random(seed)`，失败落盘 seed）。
- 2026-08-21：前置新增 13（抑制未实现位阶技能窗），10 在其后执行，保证 10 只测试真实可达的已实现分支，不被 rank 3–9 的 no-op 窗口污染。
- 2026-08-21：完成实现并解决；测试网发现两个已实现规则缺陷，分别立案 15（rank 2 技能捕获后相位/匕首残留）与 16（干涉响应者未接过匕首），10 以 `@unittest.expectedFailure` 回归测试记录现状。防御闸门（shield/fan/双诅咒/技能复用/审判官主动捕获）以注入测试覆盖，14 落地后转为自然触发。
