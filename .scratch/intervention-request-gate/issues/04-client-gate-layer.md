# 04 前端：门控弹窗、等待横幅、日志文案与 no-assist 偏好

Status: resolved

Blocked by: 01, 02, 03

spec: `.scratch/intervention-request-gate/spec.md`（Q6/Q7/Q10 结论的客户端落地；界面全部简体中文）

## 改动清单

**门控弹窗层**：
- 挂载条件：自己视角 `pending.kind === "intervention" && stage === "gate"` 且 `legalActions` 含 `answer-intervention-request` 且未开 `no-assist` 偏好。
- 复用既有通用确认弹窗 + 倒计时钩子（serverTime 锚定）。
- 文案（Q6 拍板）：标题「是否需要他人为你挡刀？」；正文「{攻击者名} 对你发起攻击。请求挡刀将向所有有资格的玩家发起询问；若不需要或超时，你将承受这次攻击。」；名单行「可为你挡刀的玩家：{名字列表}」；确认按钮「请求挡刀」→ `answer-intervention-request {need:true}`；取消按钮「自己承受」→ `{need:false}`；「（剩 N 秒）」。

**等待与日志**：
- 等待期横幅（复用挂起横幅）：「等待 {目标名} 确认是否需要他人挡刀…」。
- describeEvent 四条：开窗「{目标} 正在确认是否需要他人挡刀」/ 请求「{目标} 请求他人挡刀」/ 拒绝「{目标} 拒绝了他人挡刀」/ 超时「{目标} 未确认是否需要挡刀，视为不需要」。
- 三个新事件归入「干涉」类别（eventLog 分类映射）。
- 门控窗与单人窗口层的互斥关系同步（既有干涉窗互斥断言扩展到 gate）。

**偏好（Q7/Q10:A）**：
- localStorage key `bloodbound:no-assist`，界面开关「默认不让他人挡刀」，与既有「默认不挡刀」并排、相互独立。
- 开启后门控窗不弹、自动代发 `answer-intervention-request {need:false}`，以窗口 revision+deadline 为键防重复代发（沿用 no-block 机制，键按 pending stage 区分）。
- 纯客户端偏好，不进对局事件历史；帮助文案不宣传为规则。

**帮助文案**：
- helpContent 挡刀流程补门控说明（大意：被攻击者先确认是否请求挡刀，请求后才会询问其他玩家；「默认不让他人挡刀」开关的含义）。

## 验收

- vitest 新用例：弹窗渲染条件/标题/正文/名单行/按钮命令/倒计时；no-assist 代发与防重复；四条日志文案与类别；helpContent 关键词；互斥关系。
- `npm test`、`tsc && vite build` 全绿。
- e2e 手动验收（chrome-devtools，配方归 05）。

## Comments

- 2026-10-04 implemented in commit `69e2503` (branch `gate/04-client`, merged to `spec/intervention-request-gate`). `InterventionGateLayer` exported from GameScreen with Q6 copy verbatim; waiting banner; four describeEvent lines + 干涉 category + PUBLIC_EVENT_TYPES; `bloodbound:no-assist` independent toggle with stage-scoped dedup key `gate:${revision}:${deadline}`; helpContent gate note (explicitly 界面偏好非规则); stage-split render mutex. New `interventionGate.test.tsx` (17 tests). Verified on integration branch: 98/98 vitest, tsc clean, vite build clean. Deviation: modal derives attacker name from `daggerHolderId` (wire pending carries no attackerPlayerId; sound because the pending mutex freezes the dagger during gate — documented in code comment).
