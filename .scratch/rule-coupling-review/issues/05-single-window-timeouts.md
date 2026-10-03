# 05 单人窗口超时兜底（reveal / skill / token-return）

Status: resolved

## 背景

ADR 0011（2026-10-03 裁决 P6+L4）：干涉投票已有超时，但三类单人窗口（亮牌/技能/退牌）没有——断线即全场停摆。加超时兜底，全程自动确定性默认，不用房主代行。

## 改动

**引擎侧**：
- 新增三类窗口的 timeout 命令（引擎命令集扩展），到期语义：
  - 亮牌窗：自动亮排序第一张（marker-0 → marker-1 → rank 确定序）
  - wild 色选窗：取**问号**（依赖 `.scratch/blood-oath-replica/issues/26-wild-color-question-option.md` 落地；该票已注明超时默认由本票实现）
  - 技能窗：视为放弃（即弃用，按 ADR 0008 写 `skills_used`，永久失去）
  - 退牌窗：自动退排序第一张（marker 先于 rank；保住"亮槽数 = 伤害数"不变量）

**服务端**：
- `server/deadlines.py` 扩展 WINDOW_PROVIDERS：三类单人窗口各挂定时器代发 timeout 命令；deadline 由 Room 持有，**引擎不存墙钟**（重放确定性约束，照既有 intervention 模式抄）。

**房间配置**：
- 房主开局单项"单人窗口超时"，三类窗口共用，预设 30/60/90/120/180 秒，**默认 90 秒**；客户端设置界面与房间创建流程同步。

## 验收

- 三类窗口各一条"到期自动默认"分支测试；超时事件进事件日志（可解释）。
- 断线玩家在窗口期掉线 → 到期自动结算，对局继续。
- 超时命令走重放确定路径（同 seed 同命令序同日志）。

## Comments

- 2026-10-03（实现销案）：引擎新增 `timeout-reveal` / `timeout-skill` / `timeout-return` 三条服务端托管命令（payload 携带 `actorPlayerId`(+`eligibleTokens`) 身份守卫，过期/错窗提交被拒）；`start-game` 新增 `singleWindowTimeoutSeconds`（缺省 90，随 `GameStarted` 事件公布）。服务端 `deadlines.single_window` provider 接入既有 WINDOW_PROVIDERS，`Room.sync_window_deadline` 泛化为按"窗口身份"（intervention 沿用裸 stage 旧键；单人窗口 = kind:actor:资格快照）起算/重起算。超时自动结算事件（ClueRevealed / SkillDeclined / TokenReturned）带 `reason=timeout`，客户端事件日志显示"（超时自动）"；等待横幅带倒计时并告知到期默认。wild 色选窗默认问号所需的引擎接受 `unknown` 色已随本票落地（wild-26 引擎前置，其投影/客户端三选项仍归该票）。ruleset 0.4 不变（bump 归 07），golden 已重生成。分支测试 `SingleWindowTimeoutBranchTests` + 服务端 `SingleWindowDeadlineTests`；覆盖行见 `docs/rule-branch-coverage.md` Issue 05 小节。
