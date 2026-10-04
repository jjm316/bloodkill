# 可用性修复：手机端溢出 / 进房失败态 / 中文元数据

Type: task
Status: resolved
批次: 第一批（P0，最先做）
验收基准截图: .scratch/ui-review/（2026-09-12 评估实测，尤其 07-mobile-board、08-mobile-lobby、09-mobile-modal、13-waiting-mobile、04-connecting-forever）

## Problem Statement

（从玩家视角描述）朋友用手机打开链接进房——这是本项目最主要的进入方式——却发现：输入姓名和房间号的输入框右半截被裁掉；进了对局，"是否为 TA 挡刀？"的确认弹窗右侧被裁，后果说明和按钮都看不全；对局桌面上挤成三列的座位还在往屏幕外溢，连"离开"按钮都找不到。输错房间号的玩家则永远停在"正在连接……"，没有任何失败提示，只能干等或关闭页面。浏览器标签页标题是英文"Blood Bound"，开多个窗口时分不清哪个是哪个房。

## Solution

三组小改动：① 大厅/弹窗等固定宽度容器改为视口自适应，座位区在窄屏改为网格强制换行，消灭一切横向溢出；② 初始连接加超时，超时后显示"无法加入房间"并可返回大厅；服务端"进不存在的房间"报错路径修复（当前必崩，见 Implementation Decisions）；③ index.html 改为中文语境（lang、标题、favicon、theme-color），进房后标题带房间号。纯样式层 + 一条服务端错误路径，不改协议、不动规则引擎。

## User Stories

1. As a 手机玩家, I want 挡刀确认弹窗在 390px 宽的屏幕上完整显示（左右留边、后果文案与"挡刀/不干涉"两个按钮完整可点）, so that 核心交互不会因为裁切而做错或做不了。
2. As a 手机玩家, I want 大厅的姓名和房间号输入框完整可见可输入, so that 我能顺利进房。
3. As a 手机玩家, I want 对局座位在窄屏下换行成网格排列、整体不产生横向滚动, so that 我能看到全部玩家。
4. As a 手机玩家, I want 顶部"离开"按钮在任何屏宽下都可见可点, so that 我随时能退出房间。
5. As a 手机玩家, I want 等待房间页的提示文案完整显示, so that 我知道怎么告诉朋友加入。
6. As a 手机玩家, I want 备忘选择器、阵营选择浮层同样不超出屏幕, so that 所有浮层功能在手机上可用。
7. As a 玩家, I want 输错房间号后在几秒内看到"无法加入房间，请核对房间号"并可以返回大厅, so that 我不会无限等待。
8. As a 玩家, I want 服务器未启动或网络不通时也得到同样的失败提示, so that 任何进不了房的情形都有出路。
9. As a 玩家, I want 断线自动重连的行为保持现状（显示"正在重新连接"并持续重试）, so that 临时网络抖动不会被误判为进房失败。
10. As a 玩家, I want 通过一键进房链接（?room=&name=）进入已不存在的房间时同样看到失败提示, so that 过期链接有明确反馈。
11. As a 玩家, I want 浏览器标签页显示"鲜血盟约", so that 我能认出这是这个游戏。
12. As a 玩家, I want 进房后标签页标题变为"鲜血盟约 #房间号", so that 我开多个窗口或手机多标签时能分清哪个房间。
13. As a 玩家, I want 浏览器收藏/历史里有可辨识的图标（匕首或血滴风格 favicon）, so that 下次能快速找到入口。
14. As a 手机玩家, I want 手机浏览器地址栏/状态栏颜色与页面深色主题一致（theme-color）, so that 界面浑然一体不突兀。
15. As a 读屏用户, I want 页面 lang 属性为 zh-CN, so that 读屏软件用正确的中文语音规则朗读。
16. As a 桌面玩家, I want 1440px 等大屏下的布局与现状一致（本轮不引入观感变化）, so that 修复不带来回归。
17. As a 键盘用户, I want 布局改动后焦点环依然清晰可见, so that 键盘导航不受影响。
18. As a 旁观者, I want 上述手机端修复对旁观视图同样生效, so that 查房体验与玩家一致。
19. As a 开发者, I want 服务端对不存在的房间返回标准错误帧而不是连接异常崩溃, so that 客户端能按协议处理且日志不被 TypeError 刷屏。
20. As a 开发者, I want 本轮不引入任何新依赖、不引 UI 框架, so that 包体与构建流程保持轻量。

## Implementation Decisions

- **宽度自适应**：所有固定 `max-width: 380px` 的居中容器（大厅、回放加载页、模态弹窗）统一改为 `min(380px, calc(100vw - 32px))` 等价的视口自适应写法，保证窄屏下左右各留 16px 边距。
- **座位区网格化**：≤480px 断点下座位容器由 flex 换行改为 CSS Grid（`repeat(auto-fill, minmax(140px, 1fr))`），座位不再被挤压成三列溢出；桌面端 flex 行为不变。`body` 加 `overflow-x: hidden` 作为兜底（不是替代上述修复）。
- **进房失败态（客户端）**：WebSocket 打开后若 10 秒内未收到首份状态投影，视为进房失败：停止重连，复用现有 Banner 组件显示"无法加入房间，请核对房间号"+ "返回大厅"。超时只作用于"从未收到过状态"的初始连接；已收到过状态的断线重连维持现有指数退避循环与"正在重新连接"提示，行为不变。
- **进房失败态（服务端）**：ws 握手路径对不存在的房间返回 `room.not-found` 错误帧后正常关闭连接。现状是 `error_message()` 调用时房间号关键字实参与函数首参同名冲突，抛 TypeError 导致错误帧从未发出（server/app.py 的 ws_endpoint 内，一行修复：房间号改经 details 的其他键传递或省略）。错误帧的外层结构（type/code/message/details）不变，不改协议字段。
- **元数据**：index.html 的 `lang` 改 `zh-CN`；`<title>` 改"鲜血盟约"；新增内联 SVG favicon（匕首/血滴意象，data URI 或静态文件均可，不引入构建步骤）；新增 `<meta name="theme-color" content="#12141a">`。前端在收到房间状态后把 `document.title` 更新为 `鲜血盟约 #房间号`，离开房间回到大厅时还原为"鲜血盟约"。
- **遵循 ADR 0004 的 client-only 边界精神**：除上述服务端单点错误路径修复外，其余改动全部落在 client/ 的样式层与元数据层；不动投影、不动事件、不动规则引擎。
- 明确不做：不重构 useSocket 的重连状态机（只加初始超时一个分支）、不调整任何视觉主题颜色（属第二批 Spec B）。

## Testing Decisions

- 好的测试只测外部行为：给定 mock 的 WebSocket 行为，断言界面出现什么、用户能点什么，不测内部状态字段。
- **客户端失败态**：vitest + jsdom，mock WebSocket 永不应答（配 fake timers 推进 10s），断言失败 Banner 出现、"返回大厅"回到大厅；先例：WaitingRoom.test.tsx 的渲染断言方式。断言"已建立过连接的断线重连不触发失败态"（先发一份 state 再静默）。
- **服务端错误帧**：现有后端 unittest discover 惯例，新增一例：对不存在房间发起 ws 连接，断言收到 `room.not-found` 错误帧且连接被正常关闭（回归：不再 TypeError）。
- **视觉验收**：jsdom 无法测真实布局，采用无头 Chrome 截图对照（复用 2026-09-12 评估的配方）：390×844 与 1440×900 两档，对大厅/等待房/对局桌面/挡刀弹窗四个界面断言无横向溢出（可用 `document.documentElement.scrollWidth <= window.innerWidth` 脚本化判据 + 人工目检截图）。
- 元数据（lang/title/favicon）不写自动化测试，进交付前人工检查单。

## Out of Scope

- 圆桌布局、主题配色、衬线标题、SVG 界面图标（第二批 Spec B）。
- 动效、横幅合并、倒计时紧迫态、复制分享（第三批 Spec C）。
- 重连策略重构、移动端专用导航/手势、多语言框架。

## Further Notes

- 评估证据与现场截图见 .scratch/ui-review/；服务端崩溃堆栈当时记录在 .scratch/uvicorn.log。
- 本 spec 与评估报告的排序结论一致：这两组修复是"手机朋友能否正常玩"的底线，故排第一批。

## Comments

### 2026-09-13 实现与验收记录

- 实现：服务端单点修复（`error_message` 的 `code=` 关键字冲突 → `roomCode=`）+ WsHandshakeTests 回归；客户端 useSocket 初始进房 10s 超时（从挂载起算，覆盖"服务器未启动"；首份状态到达即解除）、GameScreen 失败 Banner 与 `room.not-found` 文案映射、标签页标题 `鲜血盟约 #房间号`（离开还原）；CSS `--panel-max-width: min(380px, calc(100vw - 32px))`（大厅/回放加载/弹窗，banner 同族 420px 版）、≤480px 座位区 CSS Grid、`body overflow-x: hidden` 兜底；index.html `lang=zh-CN` / 标题 / 内联血滴 SVG favicon / theme-color #12141a。PROTOCOL.md 补一行 ws 不存在房间的行为说明（仅文档，帧结构未动）。
- 自动化：vitest 新增 `client/src/joinFailure.test.tsx` 三例（10s 无应答 → 失败 Banner + 返回大厅；已收过状态的断线静默 120s 不触发失败态；room.not-found 错误帧 → 立即"房间不存在"）；后端 unittest 全量 155 例通过。
- 视觉验收（Chrome DevTools 真实渲染，判据 `document.documentElement.scrollWidth <= window.innerWidth` + 人工目检截图）：390×844 与 1440×900 两档下，大厅 / 等待房 / 对局桌面 / 挡刀弹窗全部无横向溢出；390 下座位两列网格、备忘选择器浮层在屏内（8–252px）；错房间号一键链接秒级显示"无法加入房间 / 房间不存在，请核对房间号"，返回大厅后标题还原；uvicorn.log 无 TypeError。驱动脚本 `.scratch/ui-usability-visual.py`（setup/start/attack）。

### 2026-10-04 第三批（Spec C）取消

- 用户裁决：Out of Scope 中推迟到第三批 Spec C 的四项——动效、横幅合并、倒计时紧迫态、复制分享——不再推进，直接关闭（wontfix）。UI 三批至此全部收口：Spec A（本 spec）与 Spec B（圆桌主题，`ui-table-theme`）已实现，Spec C 取消，不另立 spec。若日后重启，按 `ui-polish` 的先例拆小票再立项。
