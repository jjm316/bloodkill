# 体验打磨：反馈整合 / 等待房分享 / 新手规则

Type: task
Status: wontfix
批次: 第三批（P2，依赖第一、二批的主题变量与布局基线；四项互相独立，可单独取舍）
验收基准截图: .scratch/ui-review/06-board-attacker.png（双横幅重复）、10-gameover-desktop.png（终局残留"等待其他玩家行动"）、12-waiting-8p.png（bullet 名册）

## Problem Statement

（从玩家视角描述）被攻击时屏幕上同时挂着两条横幅说同一件事，只有一条带倒计时，倒计时快到了也没有任何视觉警示，经常措手不及；受伤、亮牌这些关键时刻画面毫无反应，靠读日志才知道发生了什么；对局已经结束，界面却还写着"等待其他玩家行动"。开房的人只能口播 6 位房间号，念错一位就进错房；等待名册是一列平淡的 bullet，看不出谁是谁。第一次点开链接的朋友完全不懂规则——什么是徽记、什么叫挡刀、三格亮满意味着什么——没人解释，只能边玩边猜。

## Solution

四组独立小改动：① 干涉投票的双横幅合并为一条（含目标、表态进度、倒计时），倒计时最后 10 秒进入绯红脉动的紧迫态，弹窗内倒计时同步；受伤、亮牌、浮层出现补充轻量 CSS 动效；终局后不再渲染"等待其他玩家行动"。② 等待房加"复制房间号"与"复制进房链接"（明文 HTTP 环境降级兼容），名册从 bullet 列表升级为首字头像卡片，离线灰化。③ 大厅加可折叠"怎么玩"简介，对局页加"？"？规则浮层，内容同一份中文文案。纯前端、零协议改动。

## User Stories

1. As a 投票中的玩家, I want 屏幕上只有一条干涉投票横幅, so that 我不用在两处读同一件事。
2. As a 投票中的玩家, I want 横幅上同时看到被攻击者、已表态结果和未表态名单、剩余秒数, so that 一眼掌握全局。
3. As a 投票中的玩家, I want 倒计时最后 10 秒变红并脉动, so that 我感知到紧迫并尽快表态。
4. As a 弹出挡刀确认弹窗的玩家, I want 弹窗里的倒计时同样有紧迫态, so that 决策压力被如实传达。
5. As a 玩家, I want 任一玩家受伤时其座位有短促的红色脉冲, so that 伤害的发生时刻可感知而不只是数字变化。
6. As a 玩家, I want 亮牌确认时对应槽位有短暂闪光, so that 我确认刚才的操作已生效。
7. As a 玩家, I want 弹窗与浮层出现时有约 150ms 的淡入过渡, so that 界面不生硬跳动。
8. As a 开启"减少动态效果"的玩家, I want 上述动效自动省略, so that 我的系统偏好继续有效。
9. As a 玩家, I want 对局结束后不再看到"等待其他玩家行动。", so that 结算界面不出现误导性文案。
10. As a 房主, I want 等待房里一键复制房间号, so that 口播之外多一个准确渠道。
11. As a 房主, I want 一键复制"进房链接"发给朋友, so that 朋友点开即到本房，不用手输房号。
12. As a 朋友, I want 打开只带房间号的链接时大厅自动填好房间号, so that 我只需输入姓名。
13. As a 局域网明文访问的玩家, I want 复制功能在非 HTTPS 环境下仍然可用（自动降级）, so that 家宽 IP 直连时功能不缺失。
14. As a 玩家, I want 点击复制后看到"已复制"反馈, so that 我确认不用再按一次。
15. As a 等待房玩家, I want 名册显示每人一个首字头像卡片，离线的人整体灰化, so that 一眼看出人数与在线状态。
16. As a 等待房玩家, I want 自己的卡片与房主徽标保持现有高亮语义, so that 既有阅读习惯不变。
17. As a 新玩家, I want 大厅有一个可展开的"怎么玩"（五句话以内：徽记、攻击、挡刀、亮牌、胜负）, so that 开局前心里有数。
18. As a 对局中的新玩家, I want 页头"？"按钮打开规则浮层, so that 遇到不懂的术语（徽记/等级/挡刀/备忘/日志类别颜色）随时查。
19. As a 开发者, I want 大厅简介与房内浮层共用同一份规则文案数据, so that 两处不会改漏。
20. As a 旁观者, I want 合并后的横幅与紧迫态对旁观视图同样生效, so that 查房信息与玩家一致。
21. As a 开发者, I want 动效全部用 CSS transition/animation 实现, so that 不引入 JS 动画库、复用全局 reduced-motion 降级。
22. As a 玩家, I want 本批所有改动不改变任何协议字段与命令, so that 存档、回放、规则版本不受影响。

## Implementation Decisions

- **横幅合并**：PendingBanner 与等待横幅合并为一个组件，单条展示"目标 / 表态进度（已表态：结果列表）/ 未表态名单 / 倒计时"；三选一阶段同理。倒计时数字在剩余 ≤10 秒时追加紧迫样式类（绯红 + 脉动），ConfirmDialog 内嵌的倒计时复用同一样式。
- **动效**：座位受伤 = 一次 300ms 红色 box-shadow 脉冲（以伤害事件或投影 damage 变化为触发）；亮牌确认 = 槽位一次短促闪光；弹窗/浮层进场 = 150ms 缩放淡入。全部 CSS 实现；全局 `prefers-reduced-motion` 降级规则已存在，自动覆盖，无需逐项处理。
- **终局文案**：房间状态为"已结束"时不渲染动作区提示文案（"等待其他玩家行动。"）。
- **复制工具**：新建 `copyText` 工具——优先 `navigator.clipboard`，在非安全上下文（本项目家宽 IP 明文访问时该 API 不存在）降级为隐藏选区 + `execCommand('copy')`，再失败则弹出生成后可手动选择的文本。复制成功后按钮短暂显示"已复制"。
- **进房链接**：等待房提供两个动作——复制房间号、复制 `${origin}/?room=房间号`。相应地，入口解析放宽：URL 仅带 `room` 参数（无 `name`）时不再被丢弃，而是回到大厅并预填房间号，访客只需输入姓名。带完整 `room+name` 的自动进房行为不变。
- **名册卡片化**：等待名册由 bullet 列表改为卡片行：首字圆形头像、名字、既有徽标（你/房主/离线）；离线卡片整体降透明度灰化，替代文字后缀的视觉权重。
- **规则文案单一来源**：大厅"怎么玩"折叠块与房内"？"浮层渲染同一份中文规则文案（集中在客户端一个纯数据模块，仿事件类别映射的组织方式）；浮层为现有模态样式的复用，Escape/点击遮罩关闭。
- **遵循 ADR 0004 的 client-only 原则**：零服务端、零协议改动，改动范围仅 client/src。
- 明确不做：终局庆祝动画、音效、消息推送、多语言。

## Testing Decisions

- 好的测试只测外部行为：断言用户可见的渲染结果与可交互性，不测组件内部状态或 CSS 规则本身。
- **终局文案**：vitest + jsdom——房间状态为已结束时断言"等待其他玩家行动"不出现（先例：eventLog.test.ts、WaitingRoom.test.tsx 的渲染断言方式）。
- **复制降级**：`copyText` 单测——mock `navigator.clipboard` 缺失时走 `execCommand` 降级路径并返回成功/失败；按钮反馈以渲染断言覆盖（mock clipboard 写入后出现"已复制"）。
- **链接预填**：入口解析的单测——仅 `?room=` 时大厅房间号输入框预填、`?room=&name=` 自动进房行为不变。
- **紧迫态与横幅合并**：jsdom 断言合并后单条横幅的文案组成（目标/未表态名单/剩余秒数）；≤10 秒的样式切换属视觉，不写断言。
- **视觉/动效验收**：无头 Chrome 截图（投票中双横幅应只剩一条；名册卡片化前后对照）；动效以真实浏览器人工确认 + reduced-motion 模拟抽查。

## Out of Scope

- 回放进度条/自动播放（已砍掉，不做）。
- 终局结算的庆祝视觉、胜方强调色块、音效。
- 规则文档的完整教程化（只做五句话简介 + 术语浮层）。
- 服务端与协议的任何改动。

## Further Notes

- 四项互相独立：若实施中需要缩小范围，可按"横幅合并与紧迫态 → 复制分享 → 规则浮层 → 名册卡片化"的顺序单独交付或砍尾。
- 评估证据见 .scratch/ui-review/（双横幅、终局残留文案、bullet 名册的实拍）。

## Comments

- **2026-09-13 用户裁决：整份废弃（wontfix）。** 理由：spec 太大、不急于实现。若日后重启，建议按 Further Notes 的独立性拆成四个小 spec 逐项立项，不要整批复活。grill 第一轮 Q1–Q11 的推荐答案与当日代码查证事实存档如下，重启时可直接引用、省一轮调查。
- 事实索引（2026-09-13 查证）：双横幅 = `client/src/Board.tsx:347` `.pending` 金边条（目标/表态汇总，无倒计时）+ `client/src/GameScreen.tsx:98-130` `.waiting-banner`（等待名单/倒计时），两处独立从同一 `game.pending` 派生，弹窗 ConfirmDialog 亦在 InterventionPollLayer 内；干涉时限房主开局定 30–180s 默认 90（`blood_bound/engine.py:19`），poll/choice/弹窗共用同一 `pending.deadline`；`prefers-reduced-motion` 全局降级规则已存在（`styles.css:733`），新 CSS 动画自动覆盖；入口解析 `App.tsx:10` `autoJoinCredentials()`——仅 `?room=` 无 name 时返回 null 整体丢弃、回大厅无预填；大厅在 `/`、无路由库，`${origin}/?room=` 命中 SPA；名册徽标是文字后缀（你）（房主）（离线），`WaitingRoom.test.tsx:122` 契约测试断言整串 textContent（卡片化必同步改）；"等待其他玩家行动。"在 `GameScreen.tsx:48` ActionsPanel；旁观者与玩家走同一组件，横幅改动自动继承；client 无任何剪贴板工具与帮助/规则浮层；damage 值在 PlayerView 上可前端 diff；等待房房号只在页头 `<strong>` 纯文本、主体 hint 不显示号码。
- 横幅位置原型：`.scratch/ui-polish/banner-position-prototype.html`（?variant=now/a/b，无头 Chrome 截图已验证）。观察：A（Board `.pending` 顶部槽位）第一眼可见、金边权重高；B（waiting-banner 位置）紧贴操作区但需下扫、样式低调。
- Q1–Q11 推荐答案摘要（未获用户逐条拍板，随 spec 一并废弃）：Q1 合并横幅留 Board `.pending` 槽位、删 waiting-banner（弹窗保留）；Q2 受伤脉冲用投影 damage 增量 diff（mount/重连/治疗减少不触发）；Q3 亮牌闪光全视角；Q4 离线=灰化+保留小字"离线"徽标；Q5 头像全员统一中性色（备忘标记已用红/蓝表阵营猜测，多彩头像语义冲突）；Q6 等待房主体加"分享"块（大房号+两复制按钮）而非塞页头；Q7 `?room=` 预填原样 trim 不校验、不清 URL、聚焦姓名框；Q8 浮层=intro 五句+terms 词条定义列表（同数据模块，大厅只渲染 intro）；Q9 紧迫态固定 ≤10 秒；Q10 文案由 agent 按 CONTEXT.md 起草、用户代码里审；Q11 已复制反馈 2s、灰化 opacity 0.45、绯红复用 danger 色系。
- **2026-10-03 教学/图例已拆出立项**：原 User Story 17–19 的"怎么玩/规则浮层"拆为 `.scratch/ui-help-legend/spec.md`（ready-for-agent），并扩展为等级技能表（含官方角色名，取舍见 ADR 0005）与标记图例（compact 方案原型已验证）。本 spec 其余三项（横幅合并与紧迫态、复制分享、名册卡片化）维持 wontfix。
