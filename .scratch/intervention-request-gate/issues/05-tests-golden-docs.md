# 05 测试与 golden：迁移、覆盖锁、重生成与 e2e 验收

Status: ready-for-agent

Blocked by: 01, 02, 03, 04

spec: `.scratch/intervention-request-gate/spec.md`

## 改动清单

**既有用例迁移**：
- 所有走到投票/三选一的引擎用例前置 `answer-intervention-request {need:true}`（decline_poll 等测试助手更新为「过门控」语义）。
- 服务端同步用例、性质测试的合法动作应答逻辑认新命令。

**新增覆盖**：
- 引擎：门控开窗/静默跳过/独占合法性/接受接力/拒绝结算/超时结算/期间互斥。
- 服务端：门控窗跟踪、deadline 注入、调度器到期、poll 接力、重启补发。
- 前端：见 04 验收清单。

**golden**：
- 确定性走查器（game_loop）补门控策略：以可复现规则应答门控（保证「接受开票」路径进 fixture、投票分支覆盖不缩水，拒绝路径混入）。
- golden 6–12 全部重生成，字节锁重新成立；按先例 `python -m tests.test_golden_replays` 重生成并双向验证。

**分支覆盖文档**：
- `docs/rule-branch-coverage.md` 补 `intervention.gate` 分支行（接受/拒绝/超时/静默跳过），交叉引用新测试。

**e2e 验收**（仓库惯例 chrome-devtools 驱动，脚本落 `.scratch/e2e-gate.py` 风格）：
- 完整路径一：攻击 → 目标弹门控窗 → 请求挡刀 → 志愿者弹「是否为 X 挡刀？」→ 挡刀成立（承伤、强制亮 rank、接匕首）。
- 完整路径二：攻击 → 目标点「自己承受」→ 直接结算，其他视角无弹窗、仅日志一行。
- 路径三：no-assist 偏好开启后不弹窗自动拒绝。
- 多视角核对：等待横幅、日志四条、观众无私密泄露、门控窗与单人窗口互斥。

**文档销案**：
- 全绿后：spec 与全部 issue 刷 resolved（含 commit 号）；语料 2026-10-04 裁决段的「待实施」标注摘除。

## 验收

- 后端 `python -m unittest discover` 全绿（含新 golden 锁）；前端 `npm test`、`tsc && vite build` 全绿。
- 分支覆盖文档行与新测试一一对应。
