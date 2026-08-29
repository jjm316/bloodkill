# 鲜血盟约复刻路线图

Effort: `blood-oath-replica`

## Goal

交付一个可运行、可测试、可回放的浏览器多人联机桌游实现，覆盖目标版本的完整一局：建局、准备、轮次/阶段、玩家行动、冲突结算、资源与能力、终局计分、重放与断线恢复。服务端由用户本地启动，并可通过内网穿透供他人访问；单人 AI 只有在规则引擎稳定后进入第二阶段。

## Scope and guardrails

- 先确认“鲜血盟约”对应的具体出版版本、语言版本和扩展范围；未取得授权时不复制规则书原文、卡牌文案、插画、Logo、版图和商用素材。
- 复刻目标是规则行为兼容，不承诺复制美术或原作 UI；所有未授权内容使用占位数据和原创表现。
- 目标质量门槛：核心规则有可执行规范；状态转换可序列化；同一 seed 可复现；关键规则有性质测试和整局回放测试；UI 不允许产生规则引擎之外的隐藏状态。

## Route

```text
01 身份/版本/IP边界
 ├─> 02 规则语料与验收场景
 │    └─> 03 领域模型与状态契约
 │         └─> 04 确定性规则引擎
 │              ├─> 05 建局/回合/计分闭环
 │              ├─> 06 内容数据与占位素材
 │              └─> 07 回放/存档/迁移
 │                   └─> 08 多客户端 UI 与最小权威服务
 │                        └─> 09 联机同步与恢复硬化
 └───────────────────────────────> 10 规则测试与性质测试
 08 + 09 + 10 ─> 11 可访问性、性能与发布
```

## Milestones

1. **M0 定义目标**：完成 01，锁定版本、玩家人数、网页/自托管部署边界和授权边界。
2. **M1 可验证规则**：完成 02-04；能用 seed 跑通无 UI 的最小回合。
3. **M2 可玩的 MVP**：完成 05-08；桌面浏览器中 2 人以上可完成一局并保存/回放，UI 从一开始只依赖权威服务端接口。
4. **M3 可交付版本**：完成 09-11；多人联机、自托管服务、内网穿透部署指引、测试、性能、可访问性和网页发布达标。

## Notes

- 当前仓库没有实现代码、`CONTEXT.md` 或 ADR；技术栈先不预设，待 01/03 的产出决定。
- 所有规则计算放在纯领域层；输入、随机源、时钟和网络适配器通过接口注入。
- 先记录事件，再投影 UI/存档；这样可以复用同一套事件做回放、断线恢复和测试诊断。

## Decisions-so-far

- 2026-08-29：09 已解决；WebSocket 现以稳定 `commandId`/`expectedRevision`/`ack` 实现确认与幂等重传，客户端退避重连后以完整权威投影收敛，过期命令收到冲突与新状态。房主离开不终止房间，持 token 重连恢复管理权；协议版本不匹配显式拒绝，`/metrics` 仅提供无身份运行计数。详见 [09 票据](issues/09-online-sync-recovery.md)、[协议](../../server/PROTOCOL.md) 与 [恢复测试](../../tests/test_server_sync.py)。

- 2026-08-26: Issues 20 and 14 resolved. Rank 4 alchemist and rank 7 berserker are fully implemented with intervention context, `choose-return`, reaction damage, resource/event semantics, projection/protocol/catalog updates, and regression coverage. The rank 1--9 ability/resource scope is now complete.

- 2026-08-25：19 已完成：目标型能力统一复用 `choose-skill`；harlequin 的身份反馈仅写入施法者投影，guardian 的 shield/sword 以 ward 关系和 `ResourceReturned` 事件闭环，mage 遮蔽已公开 marker 值，fan 继续作为干涉资格门槛。frontier 推进至 20。

- 2026-08-25：18 已完成：rank 1 elder 的 quill 按 `ResourceGranted` 后立即 `ResourceSpent(reason=leader-succession)` 建模；家族领袖默认取最小 rank，使用 elder 后仅该家族切换为最大 rank，状态写入 `maxLeaderFactions` 并纳入存档/golden replay。

- 2026-08-25：17 已完成：身份标记按 rank 生成并通过逐点 reveal 窗口自选公开，schema/ruleset 升级到 2/0.2；15/16 的终局匕首与干预交接残留一并修复。

- 2026-08-19：采用“先规则引擎、后界面”的分层路线；理由是桌游复杂度主要来自状态转换和边界结算。
- 2026-08-19：产品方确认必须支持多人联机；客户端采用浏览器网页，不提供安装包；服务端由用户本地启动并通过内网穿透供他人访问。首轮开发先以桌面网页为主，同时约束响应式布局以兼容手机（含 iPhone）和平板。
- 2026-08-19：01 身份研究未能从一手资料识别“鲜血盟约”的唯一桌游版本；在用户提供官方产品/规则/版权或授权入口前，规则、内容和 IP 身份均不可推断，详见 [研究笔记](research-01-identity-version-ip.md)。
- 2026-08-19：用户提供的规则摘录已将目标锁定为 `Blood Bound`：6–12 人、Rose/Beast 各 1–9 身份，以及奇数局的一名 Secret Order 审判官。出版方、印次和授权仍未核验。
- 2026-08-19：第二份用户规则来源补充奇数人数使用中立身份、并澄清法师为双方获得法杖；它与第一份来源在治疗后技能重发和护卫盾牌效果上冲突。02 只将两份来源一致的条款作为暂定规范，冲突项待产品方裁决。
- 2026-08-19：用户补充的规则书正文已裁决人数、中立审判官、羽毛、炼金治疗、护卫盾牌和法师法杖。02 只缺规则书第 8 页的诅咒卡设置比例表；该表在实现奇数局时作为版本化设置数据处理。
- 2026-08-29：用户更新诅咒规则为每名审判者对应 1 张真诅咒和 1 张假诅咒；狂战士反伤改为施加给原攻击者，且反伤正常触发线索、技能和第 4 点捕获。
- 2026-08-19：用户提供的英文规则书正文（来源 C）优先于此前中文摘录与社区解读；前述关于羽毛、治疗、护卫、法杖和干涉资格的冲突已按 C 解决。来源 C 未覆盖之处不从低优先级来源猜测补齐。
- 2026-08-19：02 的三项 needs-info 已由产品方回答，票据现为 `resolved`；可推进 03 领域模型与状态契约。
- 2026-08-19：frontier 已推进到 03；开始设计支持 6–12 人、Rose/Beast、Secret Order 审判官、私有线索、诅咒卡和独立终局分支的状态契约。
- 2026-08-20：03 已解决；以 `EngineState` 保存权威私有事实、以 `PlayerView` 隔离玩家投影，pending window 显式建模干涉/技能响应；事件日志是回放与恢复的事实来源，详见 [契约](domain-model-contract.md) 与 [ADR-0001](../../docs/adr/0001-authoritative-event-log.md)。
- 2026-08-20：04 已解决；后端采用 Python 3.11+ 标准库实现纯领域 `RulesEngine`，提供确定性建局、命令校验/幂等、事件批提交、攻击与干涉窗口、技能窗口、诅咒分发和终局分支，详见 [引擎票据](issues/04-deterministic-rules-engine.md) 与 [引擎说明](../../blood_bound/README.md)。
- 2026-08-20：05 已解决；新增无 UI 的 `run_deterministic_game()` smoke/golden replay runner，6--12 人均可从加入、行动、响应跑到捕获终局；结果含稳定排名和解释键，详见 [05 票据](issues/05-game-loop-scoring.md)。
- 2026-08-20：06 已解决；新增版本化 `blood_bound/content/` 数据目录和构建期校验器，用稳定规则 ID、显示键、原创占位素材 ID 与许可证记录分离内容；中英文本齐备，未证实的能力明确保留为 `unimplemented`，详见 [06 票据](issues/06-content-data-pipeline.md) 与 [内容说明](../../blood_bound/content/README.md)。
- 2026-08-20：07 已解决；摘要：v2 JSON/gzip 存档以事件哈希链、快照校验和和确定性命令回放交叉验证，支持暂停恢复、逐步回放、URL fragment 调试分享及 v1 fixture 迁移，详见 [07 票据](issues/07-save-replay-migration.md) 与 [持久化实现](../../blood_bound/persistence.py)。
- 2026-08-21：用户确认直接实现本地主机、多浏览器客户端的正式版本，不再以单设备热座为 08 的交付边界。08 已认领：采用 Python FastAPI/uvicorn、React/TypeScript/Vite 与 WebSocket；同名新连接接管旧座位，房主本地凭据管理大厅，6 位房间码、多个房间、公共观战、自动存档和最近 20 局保留。LAN 使用 HTTP/WS，内网穿透要求 HTTPS/WSS。视觉设计后置，但手机竖屏必须完整可玩。
- 2026-08-21：08 已解决；交付按玩家投影（`project_state`/`legal_actions`，不含 seed/clueIcon/他人身份/诅咒）、纯 stdlib 房间管理器 + FastAPI/uvicorn WebSocket 权威服务（同名接管、锁定、6–12 人开局、逐命令自动存档、终局保留 20 局、重启恢复）与 React/TS/Vite 客户端（大厅/等待室/对局/旁观/回放，行动按钮全部来自服务端合法行动投影，回放与对局共用 Board 组件），附协议与 LAN/HTTPS-WSS 启动说明，详见 [08 票据](issues/08-hotseat-ui.md)、[协议](../../server/PROTOCOL.md) 与 [服务端说明](../../server/README.md)。断线恢复硬化、浏览器集成测试与部署自动化后置 09。
- 2026-08-21：12 已解决；本机 Python 3.11.4 venv 建成（`.venv`），全量 31 项测试在 3.11 下通过，此前 3.8 失败的 `test_paused_game_and_debug_link_round_trip` 复绿。
- 2026-08-21：查语料确认 rank 3–9 能力语义齐全（来源 C），此前标 `unimplemented` 系实现延期而非规则缺失。拆分为两张票：13 抑制未实现位阶技能窗（10 之前做），14 实现全部能力与资源经济（10 之后做，借 10 测试网兜底）。
- 2026-08-21：10 收缩为纯测试票——规则分支补全 + 手写 stdlib 性质测试 + 整局 replay；砍掉平衡模拟 CLI、性能基线/帧率预算、CI 与覆盖率；网络模拟与浏览器多窗口 E2E 后置 09。性质测试用纯 stdlib 随机 sweep，不引入 Hypothesis。
- 2026-08-21：10 已解决；新增 49 项分支测试（[覆盖清单](../../docs/rule-branch-coverage.md)）、14 组 seed 的 stdlib 性质 sweep（确定性/恢复等价/幂等/投影保密/状态不变量，失败落盘 seed+命令序列）、6–12 人 golden replay fixtures（`tests/fixtures/`，规则变更导致漂移即失败），全量 91 项通过。测试网发现两个已实现规则缺陷并立案 15/16，详见 [10 票据](issues/10-testing-balance.md)。
- 2026-08-22：14 已锁定产品方裁决（见票面「已裁决」）——身份标记模型 = 每玩家 1 等级 + 2 身份标记（1/5/6 红红·蓝蓝、2/3/4 ？？·？？、7/8/9 红？·蓝？；受伤自选揭示、第 3 点被迫亮 rank、挡刀被迫亮 rank 并开技能窗）；Elder 领袖 = 数字最大（覆盖来源 C「最小」）；Guardian 盾保留「可干涉」（覆盖来源 C「不能响应干涉」）；Mage 法杖 = 单效果「给一人 Staff、其身份标记全变问号」；Courtesan 扇 = 「他人不能干涉」。实现延后。
- 2026-08-24：14 转为伞票并拆为顺序子票 [17](issues/17-identity-markers-reveal-flow.md)（标记模型与自选展示流程，地基，顺带修复 15/16）→ [18](issues/18-resource-economy-elder-leader.md)（资源经济骨架 + elder 领袖规则）→ [19](issues/19-targeted-abilities.md)（目标选择型能力 3/5/6/8/9）→ [20](issues/20-intervention-coupled-abilities.md)（干涉耦合型能力 4/7）。quill 按「消耗于改写继承顺序」建模（待产品方确认口径，见 18 票面）。

## Fog

- 目标已识别为 `Blood Bound` 基础 1–9 身份集合；出版方、印次、扩展和授权尚未确认。
- 规则书正文确定首版实现 6–12 人；桌面优先 UI 必须支持 12 人房间的响应窗口与信息布局。
- 02、03、04、05、06、07、08、10、12、13 已解决；14 已拆分为 17 → 18 → 19 → 20 四张子票（见 14 票面「拆分」），frontier 推进到 17；14 全部子票关闭后回到 09「联机同步与恢复硬化」。15（rank 2 技能捕获后相位/匕首残留）与 16（干涉响应者未接过匕首）将由 17 的地基重构顺带修复并摘除 expectedFailure 标记。
- rank 3–9 能力语义已由来源 C 提供但引擎未实现；shield/sword/staff/fan 资源经济同样未实现，二者由 14 统一补齐。14 已锁定能力语义与身份标记模型（见票面「已裁决」），实现延后；15/16 缺陷仍待修。
- 是否有权使用官方卡牌/插画/文字未知。
- 已引入 FastAPI/uvicorn + React/TypeScript/Vite 与单服务器构建模式；尚无浏览器端多窗口自动化测试基线（后置 09）。服务端运行需 Python 3.11+，已用本机 3.11.4 venv（`.venv`）解决。

## Tickets

- [01 身份、版本与 IP 边界](issues/01-identity-version-ip.md)
- [02 规则语料与验收场景](issues/02-rules-corpus-acceptance.md)
- [03 领域模型与状态契约](issues/03-domain-model-contract.md)
- [04 确定性规则引擎](issues/04-deterministic-rules-engine.md)
- [05 建局、回合与终局计分闭环](issues/05-game-loop-scoring.md)
- [06 内容数据与原创占位素材管线](issues/06-content-data-pipeline.md)
- [07 存档、回放与版本迁移](issues/07-save-replay-migration.md)
- [08 多客户端 UI 与最小权威服务](issues/08-hotseat-ui.md)
- [09 联机同步与断线恢复](issues/09-online-sync-recovery.md)
- [10 规则测试与性质测试](issues/10-testing-balance.md)
- [11 可访问性、性能与发布](issues/11-accessibility-performance-release.md)
- [12 venv 环境](issues/12-venv-environment.md)
- [13 抑制未实现位阶技能窗](issues/13-unimplemented-skill-window.md)
- [14 实现全部能力与资源经济](issues/14-abilities-resource-economy.md)
- [15 rank 2 刺客技能捕获后的相位/匕首残留](issues/15-assassin-capture-phase.md)
- [16 干涉响应者未接过匕首](issues/16-intervention-dagger-handoff.md)
- [17 身份标记模型与自选展示流程（14 子票：地基）](issues/17-identity-markers-reveal-flow.md)
- [18 资源经济骨架与 elder 领袖规则（14 子票）](issues/18-resource-economy-elder-leader.md)
- [19 目标选择型能力：rank 3/5/6/8/9（14 子票）](issues/19-targeted-abilities.md)
- [20 干涉耦合型能力：rank 4 alchemist / rank 7 berserker（14 子票）](issues/20-intervention-coupled-abilities.md)
