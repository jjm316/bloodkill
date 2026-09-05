# 亮牌 / 归还改为直接点击座位上的闪光槽位（issue 25）

Type: task
Status: resolved

问题：亮牌窗口开启时，可选槽位已有金色脉冲（issue 24 增强甲），但真正的选择入口却在底部动作面板的按钮组（「选择要展示的标记」「选择归还的标记」），玩家要"先看上面闪、再去下面找按钮"，两步割裂；且槽位自带的原生 `title` 悬停气泡（系统级文字框）观感差，与按钮式 hover 反馈混淆。

## 已裁决（2026-09-05 grilling 会话，产品方确认）

1. **点击闪光槽位即完成选择**：轮到本人亮牌 / 归还时，直接点击自己座位上脉冲的槽位发送 `choose-reveal` / `choose-return`，底部按钮组删除；动作面板只留一行提示文案（「点击你座位上闪光的标记进行选择。」），仅在窗口存在时显示。
2. **wild「任」标记的阵营选择就地浮层**：点击 wild 槽位后在该槽位旁弹出小浮层（「亮出身份标记 N 时选择阵营：」+ 玫瑰 / 野兽两个带色点的按钮），点其中一个才真正发送；点浮层外 / Esc / 滚动 / 改变窗口大小即取消。非 wild 槽位单击直接发送（含 forceRank 只剩等级的情形）。
3. **归还窗口（rank 4 炼金治疗）同一套交互**：与亮牌共用同一 `eligibleTokens` 高亮与槽位点击机制，避免留下两套交互；底部「选择归还的标记」按钮组一并删除。
4. **悬停语义分态**：自己座位的三格任何状态都去掉原生 `title` 气泡（信息移入 `aria-label`）；仅 hot（可点）态给按钮式反馈——`cursor: pointer` + hover / active 时描边加粗提亮（3px #ffd84d）+ `brightness(1.2)`；非 hot 态保持静态外观、无 hover 效果（不可点的东西不假装可点）。其他玩家座位的槽位维持 `title` 气泡与 `role="img"`（读牌信息有用，且永远不可点）。
5. **无障碍与移动端顺带升级**：自己座位槽位渲染为真 `<button>`（键盘 Tab 聚焦、Enter 触发；非 hot 态 `disabled` 但样式复位保持原外观）；容器 `role` 由 `img` 改为 `group` 以免按钮被读屏树吞掉；触屏点按天然等效点击。
6. 协议、引擎、golden、ruleset 零改动（命令仍是 `choose-reveal {token, color?}` / `choose-return {token}`）；回放页 `ReplayScreen` 复用 Board 不传 `onSlotAction`，槽位自动退回纯展示 span，热态高亮同步熄灭。

## 实现清单（全部完成）

1. `client/src/Board.tsx`：`ClueSlots` 增加 `selfActions`（token → 合法动作分组）与 `onSlotAction`；单动作直发、双动作（wild 颜色变体）开浮层；自座 `button` 化 + aria-label；他人座保持 span+title；`Board` 从 `legalActions` 构建 `slotActions` 仅下发当事玩家。
2. `client/src/GameScreen.tsx`：删除两个底部按钮组与 `tokenLabel`，窗口期渲染提示行；`sendSlotAction` 把槽位动作转回命令发送。
3. `client/src/styles.css`：`.slot` 抵消全局按钮样式（min-height/padding/font-family）；`.slot:disabled` 复位透明度；`.slot.hot` cursor + hover/active 反馈；`.slot-picker*` 浮层样式。
4. 驱动脚本 `.scratch/e2e25.py`：复用 e2e-curse 连接骨架，`open` 开局、`hit <name>` 攻击后停在 reveal/token-return 窗口不代答，供浏览器验收。

## 验证记录（2026-09-05，真实浏览器 + WS 驱动 7 人局）

- 构建 `npm run build` 通过；后端 154 测试全绿（未触碰服务端）。
- 审判者 P4 两刀验收（房间 667901）：① 三槽全 hot、enabled、无 title、aria-label 就位、cursor=pointer；hover 实测 3px #ffd84d + brightness(1.2)，脉冲动画仍在；② 点 wild 槽弹浮层（玫瑰/野兽带色点、焦点落首按钮），点外取消生效，点「玫瑰」后 marker-0 变红玫点、窗口结算、提示行消失；③ 第二刀后点等级槽**直接发送**（无浮层）亮出「审」，诅咒技能窗口正常开启，UI 点「放弃技能」收尾；④ 他人 18 个槽仍为带 title 的 span（role=img）。
- 过程中抓到并修复一个真 bug：ActionsPanel 单行 JSX 内插入的 `//` 注释被当可见文字渲染，已移到 return 之前。
- 归还窗口未做独立浏览器验收（场上无人持法杖，无法低成本铺到）；其与亮牌共用同一段分组/发送代码（`choose-return` 每槽恰 1 动作 → 直发路径，已被③覆盖等价路径），风险登记于此。
- 干涉承伤 / 第 3 点 forceRank 的单槽直发路径与③同理走 `pickSlot` 单动作分支，未单独铺局。

## Comments

**2026-09-05 code-review 修复（bcb0983 评审跟进）**：两轴评审（Standards/Spec）发现两个真实视觉 bug，均已修复并浏览器回归：

1. 全局 `button:hover:not(:disabled)` 填色（特异性 (0,2,1)）压过 `.slot` 的透明底，亮牌窗口 hover 空 hot 槽会被填成灰圆 → 全局规则改为 `:not(.slot)` 排除槽位。实测 hover 背景 rgba(0,0,0,0)、金色 3px 描边反馈保留。备注：并行备忘标记会话随后把该规则进一步扩展为 `:not(.slot):not(.memo-badge)`（徽章彩底同理），该扩展随其功能提交。
2. `.slot.hot` 的金色脉冲 outline (0,2,0) 盖过全局 `button:focus-visible` (0,1,1)，键盘焦点不可辨 → 新增 `.slot.hot:focus-visible { outline: 3px solid #72b7ff; }`。实测聚焦 hot 槽为蓝环、未聚焦为金脉冲，Enter 开浮层 / Esc 关闭链路通畅。

教训：验收 hover 类修复要量 `background` 的计算值，不能只看 outline（首轮验收即因此漏掉 bug 1）。评审判断题清单（sendSlotAction 第 4 份拷贝、slotInteraction 数据捆、"基数即 wild 语义"等）记录在案，暂不动。
