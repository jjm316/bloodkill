# 座位卡三格线索槽与伤害显示（fe_iconchange）

Type: task
Status: resolved

问题：座位卡的「伤害格」（4 个红色 pip）被产品方本人在对局中误读为「亮出等级时显示的阵营颜色圆点」（2026-09-04 截图指认，玩家 3 亮等级开技能时其 1 点伤害的实心 pip 被当成阵营标记）。根因：pip 无任何文字/图标标识、且紧贴在亮出线索行上方，伤害又恰好总伴随亮牌发生。连带需求：亮出等级的文案「等级7·狂战士」要简化为只显示数字。分支 `fe_iconchange` 即为此项 UI 迭代而建。

## 已裁决（2026-09-04 grilling 会话，产品方确认）

1. **拆除伤害 pip 行，改为三格线索槽**。三格 = 每名玩家的三张线索 token（1 等级 + 2 身份标记，见 [17](17-identity-markers-reveal-flow.md)），槽位固定排列 [等级 | 标记0 | 标记1]。
2. **填亮的槽位数即伤害数**。依据（引擎全量核查）：伤害唯一 `+1` 点在 `_continue_damage` 且每点恰亮一张（第 3 点起强制亮 rank、技能伤害自动亮 rank）；唯一 `−1` 是 rank 4 炼金 heal，`damage -= 1` 与 `revealed.remove(token)` 原子同减（engine.py `_choose_return`）；第 4 点直接捕获终局不再亮牌。**风险登记**：issue 14 后续能力扩展若引入「加伤不亮牌 / 治疗不归还 / 亮牌不受伤」将破坏该不变量，届时必须回到本裁决补独立伤害指示。
3. **槽位编码不只靠颜色**（Accessibility High 反模式：color alone）：等级槽 = 圆角方块放裸数字（审判者放单字「审」）；玫瑰标记 = 红底「玫」、野兽标记 = 蓝底「兽」、未知标记 = 灰底「？」；未亮 = 虚线空槽。红=玫瑰 / 蓝=野兽沿用 14 号票 2026-08-22 裁决的颜色语言。
4. **等级文案全局去角色名**：`displayRank` 只产「等级N」（审判者仍「审判者」）。技能横幅、自己身份行、槽位 title 随之自动简化。事件日志维持概要（不写具体数字），与 21 号「避免手机刷屏」裁决一致。
5. **座位卡不再显示身份标记亮出后的阵营文字**（槽位替代）；「玫瑰家族/野兽家族」文字仍保留在自己身份行、结果横幅、亮牌按钮文案中。
6. **两个增强本次一起做**：甲 = 亮牌窗口与归还标记窗口中，当事玩家可选槽位金色脉冲高亮（数据源 `pending.eligibleTokens`，投影已下发）；乙 = 自己座位卡上未亮槽位以暗色文字预填真实值（wild 显示「任」），数据源 `viewer.identityMarkers` 投影，仅自己可见、不新增泄漏面。

## 实现清单

1. `client/src/types.ts`：`displayRank` 去角色名。
2. `client/src/Board.tsx`：新增 `ClueSlots` 组件（槽位渲染 + 自视预填 + 窗口高亮 + 含伤害数的 aria-label）；Seat 拆除 pip 行与文字线索行；`highlightFor` 映射 reveal/token-return 两种 pending。
3. `client/src/styles.css`：`.slot`/`.tile`/`.rose`/`.beast`/`.unknown`/`.dim`/`.hot` 样式（暗色主题下白字对比度 ≥4.5:1；脉冲动画被全局 prefers-reduced-motion 覆盖）。
4. 后端、协议、golden fixtures：零改动（投影字段 `revealed.rank`/`revealed.markers`/`damage`/`eligibleTokens`/`viewer.identityMarkers` 均已存在）。

## 完成条件

- 座位卡显示三格线索槽：亮出的等级为数字块、亮出的标记为红玫/蓝兽/灰？点，未亮为空槽；
- 无独立伤害显示，填亮槽数即伤害；被捕获座位维持既有置灰样式；
- 轮到某玩家亮牌/归还时其可选槽位高亮；自己卡未亮槽位可见暗色真实值；
- 全部亮等级场景（干涉承伤、第 3 点强制、技能伤害自动、展示窗口自选）呈现一致；
- `npm run build` 通过；后端测试不受影响（未触碰）。

## Comments

## Answer

已实现（2026-09-04）：

- 改动范围仅 `client/src` 三文件（Board.tsx / types.ts / styles.css），`npm run build`（tsc + vite）通过，dist 已更新，刷新页面即生效。
- 槽位 aria-label 携带精确伤害数（「受到 N 点伤害，已亮出……」），读屏用户不依赖视觉槽位计数。
- 工作区中另有未提交的 23 号票（干预投票超时）与 ADR 0002、`server/deadlines.py` 等他人/前会话在途工作，本次原样保留、零接触；故本票编号顺延为 24。
- 视觉验收：产品方在活跃测试中的对局里刷新即可核对完成条件；未做自动化前端测试（基建属 frontend-test-infra 规划）。
