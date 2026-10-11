# 座位卡标记可见性：资源行徽章化 + 诅咒卡归属公开

Status: resolved

来源：2026-10-11 grill-with-docs 主会话（Q1–Q9 全部拍板）＋同日侧聊 Q4 三案原型对比（方案 A 胜出，交接稿内容已全部吸收进本 spec，Temp 下交接文件可弃）。规则依据：`.scratch/blood-oath-replica/rules-corpus-user-extract.md`「产品方裁决（2026-10-11）」＋ `docs/adr/0014-curse-card-visibility.md`。

## 决策记录

| # | 问题 | 拍板 |
| --- | --- | --- |
| Q1 | 范围 | 诅咒可见性 ＋ 资源行显著度，两件都做 |
| Q2 | 对局中可见性（规则级） | 卡的归属全员公开；真/假仅审判者可见；服务端投影下发，断线重连不丢 |
| Q3 | 终局 | 全员翻开真/假归属，再呈现胜负 |
| Q4 | 资源行 | 「图标＋单字中文标签」金色药丸（侧聊原型方案 A） |
| Q5 | 记账 | ruleset 0.6→0.7 硬切＋语料裁决条目＋ADR 0014＋PROTOCOL.md/golden 同步 |
| Q6 | 诅咒徽形态 | 标记行紫色药丸「咒」，新「卡背」SVG 图标 |
| Q7 | 审判者真假显示 | 常显「真咒/假咒」，不做防偷窥遮蔽 |
| Q8 | 终局呈现 | 药丸原地翻「真咒/假咒」＋结果面板归属行（列于胜负判词上方） |
| Q9 | 分发时刻日志 | 每卡一行「将诅咒卡交给了 某某」，不含真假，归技能类 |

## Part A：资源行徽章化（纯前端）

`client/src/Board.tsx:45-57` 的 `Resources`（渲染点 Board.tsx:308）升级为金色药丸徽章：

- 图标：复用 `client/src/icons.tsx` 现有 SVG（quill/shield/sword/staff/fan，描边风格）。
- 短标签：笔 / 盾 / 剑 / 杖 / 扇（单字中文，AGENTS.md 界面中文规则）。
- 数量：count > 1 才显示 `×N`（现状无条件 ×N，改为仅 >1）。
- title 悬浮说明带规则效果，文案锚定语料勿临场发明：fan＝「他人不能替持扇者干涉」、staff＝「该玩家的身份标记全部变为问号」；与 `client/src/helpContent.ts:166-174` 图例条目对齐。
- 样式（原型验证值，类名换生产命名）：`border: 1px solid rgba(240,192,96,.38); border-radius: 999px; background: var(--gold-dim-bg); font-size: 12px; 图标 13px var(--gold-text); white-space: nowrap; padding: 1px 8px`。
- 保持「仅 count>0 渲染、空则 return null」；样式进 `client/src/styles.css`（参照 `.resources` 段 styles.css:669-687；注意 `.table-area.size-xl .resources` styles.css:1285 压缩档联动）。
- 验证点：10 人 size-lg 档（座位卡 190px / 窄桌面 144px）三枚同持（盾＋剑×2＋笔）不溢出不折行——原型已目视验证，生产实现后截图复核。
- 原型处置：`client/prototype.html`＋`client/src/prototype/`（main.tsx / resourceRowPrototype.tsx / prototype.css）先提交到 throwaway 分支 `prototype/resource-row` 存档，再从工作分支删除。

## Part B：诅咒卡归属公开（引擎/协议/前端）

### 语义（对齐 ADR 0014 与语料 2026-10-11 裁决）

- 对局中：players[] 公开谁持卡（含旁观者）；审判者 viewer 私有真/假归属；真假不进任何公开事件流。
- 终局：GameEnded 载荷带完整归属，全员翻开。

### 引擎与协议（ruleset 0.7）

- `blood_bound/engine.py:169` ruleset_version `"0.6"`→`"0.7"`，:182 checkpoint 检查同步，:158 处 changelog 注释风格补一行 0.7 说明。
- CurseDistributed 事件（engine.py:833-841）：载荷改为只含 `recipientPlayerId`（**去掉 curseId**——真假不得进公开事件流），并转为公开广播；`server/protocol.py:20-22` PRIVATE_EVENT_TYPES 收缩为 `{"CurseViewed"}`（保留字）。真假权威记录仍在引擎 `curse_assignments` 与服务端存档命令载荷（choose-skill assignments）。
- 投影（`blood_bound/projection.py`）：
  - `_public_player`（:192-209）增 `holdsCurseCard: bool`（player_id ∈ state.curse_assignments.values()），全员含旁观者可见。
  - viewer 块（:176-189）对审判者视角增 `curseAssignments: dict(state.curse_assignments)`（与 cursesToDistribute 同门控 `viewer.faction == "secret-order"`；分发前为空 dict）——投影驱动，重连不依赖事件重放。
- GameEnded（engine.py:1055-1063）：result 增 `curseAssignments: dict(state.curse_assignments)`（未分发/放弃为空 dict）。
- golden 重生成（tests/fixtures/golden-*.json，覆盖新事件载荷与投影字段）；同 bump 顺带落地挂起的 B9 golden 分支锁（`.scratch/coupling-test-hardening/spec.md:53`）。
- PROTOCOL.md：players[].holdsCurseCard、viewer.curseAssignments、GameEnded.curseAssignments、PRIVATE_EVENT_TYPES 变更；顺手修正文档陈旧的 `"resources": ["curse"]` 数组示例为计数 dict 实况（PROTOCOL.md:179/199）。
- 测试：引擎（CurseDistributed 公开且载荷无 curseId；GameEnded 带归属）、投影（全员/旁观者见 holdsCurseCard；审判者独见 curseAssignments；他人视角无真假字段）。后端测试 `.venv` unittest discover（没装 pytest，别装）。

### 前端（client/）

- types.ts：PlayerView 增 `holdsCurseCard: boolean`；ViewerView 增 `curseAssignments: Record<string,string>`；结果类型增 `curseAssignments`。
- icons.tsx：ICON_SHAPES 增 `curseCard`（暗置卡背：圆角矩形卡＋封印纹，描边风格、currentColor，IconName 补名）。
- Board.tsx 标记行：资源徽章之后，`holdsCurseCard` 时渲染紫色药丸（`--order-bg` 审判者紫系，尺寸同金色药丸）；持卡者被捕获后药丸仍显示（随卡半透明）。标签解析：
  - 默认（全员、对局中）：「咒」；
  - 审判者设备：viewer.curseAssignments 中 recipient＝该玩家 → curseId 前缀 `true-curse` 判「真咒」/「假咒」；
  - 对局已结束且 result.curseAssignments 非空（全员翻牌）：同上按前缀判真/假。
  - title：「暗置诅咒卡：真/假仅审判者可知；终局全员翻开」。
- 结果面板（ended 视图与回放终局）：归属行「真诅咒在 X，假诅咒在 Y」列于胜负判词上方；true-curse 分支措辞如「真诅咒在 X（胜方领袖）→ 审判者独赢，家族胜利被覆盖」。
- 事件日志（eventLog.ts）：CurseDistributed 进 EVENT_DEFINITIONS（技能类别），文案「将诅咒卡交给了 {玩家}」（Q9 用户定文案）。
- helpContent.ts 图例区增诅咒药丸条目（紫「咒」＝暗置诅咒卡，终局翻真假）。
- 测试：药丸三分支渲染（咒 / 审判者真假 / 终局全员翻）、审判者重连恢复（投影驱动）、日志行、图例条目；e2e 可扩展 `.scratch/e2e-curse.py` 验收。

## 验收

1. 7 人审判者局分发后：所有客户端（含旁观查房）两张座位卡出现紫色「咒」；审判者设备显示「真咒/假咒」；他人设备无真假。
2. 审判者断线重连后真/假归属仍在（投影恢复，不依赖事件重放）。
3. 事件日志两行「将诅咒卡交给了 X」（无真假信息）。
4. 终局：全员视角药丸翻「真咒/假咒」，结果面板归属行在胜负判词上方；回放终局行为一致。
5. 资源行五类徽章带中文标签，count>1 才 ×N；10 人压缩档不溢出不折行。
6. ruleset 0.7、golden 重生成、PROTOCOL.md/CONTEXT.md 同步；`python scripts/check.py` 与 client `npm test` 通过。

## 文档同步（实现时）

- CONTEXT.md「诅咒卡」词条增可见性语义，草稿：
  > 暗置指真/假不公开：卡的归属（谁持有）对全员公开（对局事实，经投影下发）；真/假之分仅审判者可见（断线重连不丢）；终局全员翻开真/假归属后再判定胜负。
- 语料裁决条目与 ADR 0014 已随本 spec 先行落盘，实现时无需再动。

## Comments

- 2026-10-11：grill-with-docs 两轮（Q1–Q4、Q5–Q9）全部拍板后发布；Q4 细节吸收自侧聊交接稿（原型三案对比，方案 A 胜出）；Q2 为规则级产品方裁决，语料与 ADR 0014 同日落盘。
- 2026-10-11（协调者）：三票全部落地销案，集成于 `spec/seat-marker-visibility`（ee7bc9cd…fccdcc4）并 ff 落 master。提交链：底座 e7bc9cd → 01 ac9b3be → 02 e981c2d（golden 重生成＋B9 golden 分支锁随 bump 落地，绊线实测）→ 03 b21aaa2 → 评审修复 1b711da/b25bde6（真假解析归一 curseReveal.ts、日志文案双层断言）→ 窄档折行修复 0aa5c19 → e2e 适配 fccdcc4。门禁：后端 260、前端 193、check.py 全绿。真机验收 9/9（7 人审判者局房间实拍＋10 人局双档实测）：旁观紫咒/审判者真假/重连投影恢复/日志无泄漏/终局翻牌＋归属行在判词上方/回放一致全部 PASS；截图与测量证据在 `prototypes/seat-marker-visibility/`（visual-verifier 终判 14/14 PASS）。实施期拍板记录：①「盾＋剑×2＋笔」组合真实引擎不可达（笔即得即耗），验收以真实可达的「盾×2＋剑＋杖」等价替代；② xl 档药丸 11px、五句资源 title 按图例缩写（01 票 Comments）；③ ViewerView.curseAssignments 可选、GameScreen 确认框文案修正、inquisitor-true-curse 判词中文名（03 票 Comments）；④ 窄档（144px 座位）药丸压缩联动 11px/padding 1px 4px/gap 1px（修复 0aa5c19，120px 档物理放不下维持 wrap 兜底属既有几何限制）；⑤ 捕获态药丸对比度 P2 建议未采纳（visual-verifier 终判注明非必须）。
