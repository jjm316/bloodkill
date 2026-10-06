# 鲜血盟约复刻路线图

Effort: `blood-oath-replica`

## 当前状态（2026-10-06）

核对基线：`94c0c00`。以下是票据状态与当前代码的摘要；各批次的测试数字引用其完成记录，本次文档清理未重跑应用测试。

- 正式子票按 `.scratch/*/issues/*.md` 计，共 **42 张，全部 `resolved`**：本路线图 01–26 共 26 张、规则耦合 7 张、干涉请求门控 5 张，另有前端测试基建、备忘标记、审判者诅咒技能、帮助按钮各 1 张。主路线图当前没有未关闭的 frontier。
- `spec.md` 另计，共 14 份：9 份 `resolved`、1 份 `ready-for-agent`（重复测试 spec）、1 份 `wontfix`；主产品、前端测试基建、规则耦合这 3 份无 `Status:`，是规格/实施索引，不作为开放子票计数。各入口见下方「其他批次入口」。
- 6–12 人多人对局、rank 1–9 能力、资源经济、审判者诅咒技能、存档/回放与联机恢复均已实现；15/16 已由 17 修复，14 伞票与 17–20 子票均已关闭。当前 schema 为 2、ruleset 为 `0.6`、WebSocket 协议为 `v3`，见[引擎](../../blood_bound/engine.py)与[协议](../../server/PROTOCOL.md)。
- 最近完成的是[干涉请求门控批次](../intervention-request-gate/spec.md)：01–05 全部关闭，提交映射及集成证据见该 spec 的 Comments（状态收口提交 `94c0c00`）。其完成记录为后端 213、前端 101 项通过、构建通过，含四条 E2E 路径与服务端重启后的门控重连验收。
- 当前收尾重点是发布 smoke 修复/验证与重复 spec 收口；法师抹除、守护者归还的 golden 分支锁仍延期。详见「Fog」；票据关闭不代表这些收尾已完成，也不代表获准对外公开发布。

## Goal

交付一个可运行、可测试、可回放的 `Blood Bound` 基础完整版浏览器多人联机实现，覆盖 6–12 人的完整一局：建局、准备、行动、冲突结算、资源与能力、终局计分、回放与断线恢复。服务端由用户家用机自托管，通过内网穿透供朋友访问；仅个人学习/非商业使用，不对外公开发布。单人 AI 属后续计划，当前没有实施票据。

## Scope and guardrails

- 产品范围按[主规格「产品决策」](spec.md)：用户提供图片对应的基础完整版，不含扩展；桌面优先，手机/平板全面支持为后续计划，现有手机布局与交互修复见各 UI 批次。
- 素材按 2026-08-29 用户裁决，允许在个人学习用途下使用官方素材；可下载来源仍待调研。出版印次及权利方授权未核验，旧 01 票据的调查结论保留为历史依据；当前产品口径以主规格为准。
- 部署按[主规格](spec.md)、[穿透调研](research-02-public-access-tunnel.md)与[部署指引](../../docs/deployment-lan.md)：默认 cloudflared 快速隧道，frp + 国内 VPS 为备选；TLS 已由强制降为建议优先，保留 2026-08-29 的用户取舍。
- 目标质量门槛：核心规则有可执行规范；状态转换可序列化；同一 seed 可复现；关键规则有性质测试和整局回放测试。对局事实由权威引擎裁决；备忘标记、日志筛选与默认应答偏好按各自规格保留为客户端私有状态。

## Route

以下保留初始依赖路线，相关票据现均已关闭；当前收尾以「Fog」为准。

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
3. **M2 可玩的 MVP**：完成 05–08 及后续能力/交互补齐；桌面浏览器中 6–12 人可完成一局并保存/回放，UI 依赖权威服务端接口。
4. **M3 个人自托管交付**：完成 09–11；联机恢复、自托管服务、内网穿透部署指引、测试与基础可访问性具备交付记录，发布验证仍须按[检查表](../../docs/release-checklist.md)收尾。

M0–M3 的关联票据均为 `resolved`；M3 的发布 smoke 缺口仍列在「Fog」。这里的“发布”指个人自托管交付，不改变“不对外公开发布”的产品边界。

## Notes

- 阅读入口：[主规格](spec.md)定义产品边界，[CONTEXT.md](../../CONTEXT.md)定义领域术语；规则争议以[规则语料及其产品方裁决](rules-corpus-user-extract.md)与[ADR](../../docs/adr/)为准，早期票据中的规则描述需结合后续裁决阅读。
- 已采用 Python 3.11+ 纯领域引擎、FastAPI/uvicorn 权威服务与 React/TypeScript/Vite 客户端；实现入口见[引擎说明](../../blood_bound/README.md)、[服务端说明](../../server/README.md)与[客户端目录](../../client/)。
- 权威事件日志支撑回放、恢复和测试诊断，见[ADR-0001](../../docs/adr/0001-authoritative-event-log.md)。引擎不存墙钟；窗口时限由服务端调度，见[ADR-0011](../../docs/adr/0011-single-window-timeouts.md)。
- 当前干涉流程为请求确认 → 全员公开自愿投票 → 多人自愿时目标选择；[ADR-0012](../../docs/adr/0012-intervention-request-gate.md)仅取代 [ADR-0002](../../docs/adr/0002-intervention-volunteer-poll.md) 的“自动开启投票”。技能开窗/封印按 [ADR-0009](../../docs/adr/0009-skill-window-general-rule-and-mentalists-seal.md)，审判者被捕独赢按 [ADR-0007](../../docs/adr/0007-inquisitor-captured-solo-win.md)。

## Decisions-so-far

以下保留带日期的历史记录，其中“待实现”“frontier”“门禁失败”等均指当时状态；当前状态见文首。旧技能开窗、干涉、诅咒卡数量及部署表述以最新规则语料、ADR 和主规格的裁决为准。

- 2026-10-06：核对 `94c0c00` 的票据与代码，更新当前摘要、人数/交付边界、收尾清单和批次索引，补齐 22/23/25/26 入口。此次只清理路线图；其余任务状态及原有历史记录保留。

- 2026-08-30：22 已解决：攻击无人干涉结算后匕首归受伤目标（此前 `_after_damage` 把 `attack` 来源判回攻击者，与语料 `combat/attack-handoff`/`intervention/refused` 相反；开技能窗分支恰好正确、行为分裂）。`skill`/`reaction` 来源判定不动（rank 4/7 联动属 20）；golden fixtures 漂移后重新生成，全量 113 通过。详见 [22 票据](issues/22-attack-dagger-to-wounded-target.md)。

- 2026-08-30：21 已解决：开局"向左邻展示阵营徽记"上线——`_start` 追加单条 `ClueIconsShown` 公开事件（仅 `pairs` 展示关系，无徽记内容，无 schema/ruleset 版本变更，golden fixtures 按预期漂移后重新生成）；投影 `viewer` 块下发本人 `clueIcon` 与右邻 `seenNeighbourClue`，`players[]`/旁观者/回放零徽记；前端自己座位渲染中文徽记文案，事件日志一行"全员已向左邻展示阵营徽记"；补投影保密、审判者徽记必错与 rank 3 反转测试，全量 110/110 通过。双轴 code review 无违规。详见 [21 票据](issues/21-clue-icon-neighbour-reveal.md)。

- 2026-08-30：`setup.clue-icon` grilling 定案：补上开局"向左邻展示阵营徽记"环节——纯投影（viewer 块加本人 `clueIcon` 与右邻徽记，无 setup 阶段、无 schema bump）；新增一条批量公开事件 `ClueIconsShown` 记录展示关系（内容不进事件）；方向约定俯视顺时针=座位号递增，UI 文案不出现左右；中文术语"阵营徽记"（rank 3 敌对家族、审判者随机家族特例保留，审判者徽记必与真实所属不符，补测试钉死）。已立案 [21](issues/21-clue-icon-neighbour-reveal.md)（ready-for-agent），待产品方审阅后实现。CONTEXT.md 新增"阵营徽记""左邻/右邻"词条。

- 2026-08-29：内网穿透选型定案（见 [调研笔记 research-02](research-02-public-access-tunnel.md)）：默认 cloudflared 快速隧道（本机 winget 已装并完成端到端实测：协议全链路通、自动 HTTPS/WSS、手机零安装；代价是 URL 每次重启随机变、WSS 指令往返实测约 0.8–1 秒）；备选 frp + 国内轻量 VPS 明文转发（预期几十毫秒级、约百元/年）、PC 圈子 Radmin VPN（本机已装，仅 Windows 客户端、手机出局）；花生壳（5 并发<6 人下限）、natapp（HTTP 隧道人脸识别+域名强制轮换）、ngrok（拦截页+1GB/月）、ZeroTier/Tailscale 组网（免费档容量不足）不采用。用户裁定明文可接受、便利性优先，`docs/deployment-lan.md` 的强制 TLS 条款同步降级为建议。

- 2026-08-29：用户裁定产品决策：仅个人学习/非商业使用，不对外公开发布；目标版本为用户提供图片对应的出版版本（基础完整版，不涉及扩展）；允许使用官方素材（个人学习用途，素材来源待调研）；手机/平板支持为后续计划（尽量全支持，排期靠后）；部署为家用机自托管 + 内网穿透，方案待调研优缺点后选定（无域名、无 HTTPS 证书）。

- 2026-08-29：11 已按用户指示直接标记 `resolved`（跳过 code review）；Python 全量测试门禁已转绿（106/106）。详见 [11 票据](issues/11-accessibility-performance-release.md)。

- 2026-08-29：11 实现主体完成但门禁未通过，状态为 claimed；客户端具备键盘/读屏基础可访问性、移动端稳定布局和减少动态效果支持，事件日志按 ID 去重并限制 120 条；新增发布检查表、局域网/HTTPS-WSS 部署说明及 REST/WebSocket smoke 脚本。`npm run build` 与 smoke 通过，但全量 Python 测试和终局回放 smoke 仍需补齐。详见 [11 票据](issues/11-accessibility-performance-release.md)。

- 2026-08-29：09 已解决；WebSocket 现以稳定 `commandId`/`expectedRevision`/`ack` 实现确认与幂等重传，客户端退避重连后以完整权威投影收敛，过期命令收到冲突与新状态。房主离开不终止房间，持 token 重连恢复管理权；协议版本不匹配显式拒绝，`/metrics` 仅提供无身份运行计数。详见 [09 票据](issues/09-online-sync-recovery.md)、[协议](../../server/PROTOCOL.md) 与 [恢复测试](../../tests/test_server_sync.py)。

- 2026-08-26: Issues 20 and 14 resolved. Rank 4 alchemist and rank 7 berserker are fully implemented with intervention context, `choose-return`, reaction damage, resource/event semantics, projection/protocol/catalog updates, and regression coverage. The rank 1--9 ability/resource scope is now complete.

- 2026-08-25：19 已完成：目标型能力统一复用 `choose-skill`；harlequin 的身份反馈仅写入施法者投影，guardian 的 shield/sword 以 ward 关系和 `ResourceReturned` 事件闭环，mage 遮蔽已公开 marker 值，fan 继续作为干涉资格门槛。frontier 推进至 20。

- 2026-08-25：18 已完成：rank 1 elder 的 quill 按 `ResourceGranted` 后立即 `ResourceSpent(reason=leader-succession)` 建模；家族领袖默认取最小 rank，使用 elder 后仅该家族切换为最大 rank，状态写入 `maxLeaderFactions` 并纳入存档/golden replay。

- 2026-08-25：17 已完成：身份标记按 rank 生成并通过逐点 reveal 窗口自选公开，schema/ruleset 升级到 2/0.2；15/16 的终局匕首与干预交接残留一并修复。

- 2026-08-19：采用“先规则引擎、后界面”的分层路线；理由是桌游复杂度主要来自状态转换和边界结算。
- 2026-08-19：产品方确认必须支持多人联机；客户端采用浏览器网页，不提供安装包；服务端由用户本地启动并通过内网穿透供他人访问。首轮开发先以桌面网页为主，同时约束响应式布局以兼容手机（含 iPhone）和平板。
- 2026-08-19：01 身份研究未能从一手资料识别“鲜血盟约”的唯一桌游版本；在用户提供官方产品/规则/版权或授权入口前，规则、内容和 IP 身份均不可推断，详见 [研究笔记](research-01-identity-version-ip.md)。
- 2026-08-19：用户提供的规则摘录已将目标锁定为 `Blood Bound`：6–12 人、Rose/Beast 各 1–9 身份，以及奇数局的一名 Secret Order 审判者。出版方、印次和授权仍未核验。
- 2026-08-19：第二份用户规则来源补充奇数人数使用中立身份、并澄清法师为双方获得法杖；它与第一份来源在治疗后技能重发和护卫盾牌效果上冲突。02 只将两份来源一致的条款作为暂定规范，冲突项待产品方裁决。
- 2026-08-19：用户补充的规则书正文已裁决人数、中立审判者、羽毛、炼金治疗、护卫盾牌和法师法杖。02 只缺规则书第 8 页的诅咒卡设置比例表；该表在实现奇数局时作为版本化设置数据处理。
- 2026-08-29：用户更新诅咒规则为每名审判者对应 1 张真诅咒和 1 张假诅咒；狂战士反伤改为施加给原攻击者，且反伤正常触发线索、技能和第 4 点捕获。
- 2026-08-19：用户提供的英文规则书正文（来源 C）优先于此前中文摘录与社区解读；前述关于羽毛、治疗、护卫、法杖和干涉资格的冲突已按 C 解决。来源 C 未覆盖之处不从低优先级来源猜测补齐。
- 2026-08-19：02 的三项 needs-info 已由产品方回答，票据现为 `resolved`；可推进 03 领域模型与状态契约。
- 2026-08-19：frontier 已推进到 03；开始设计支持 6–12 人、Rose/Beast、Secret Order 审判者、私有线索、诅咒卡和独立终局分支的状态契约。
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
- 2026-09-04：[24](issues/24-clue-slots-damage-display.md) 已解决；座位卡伤害格重构为三格线索槽（等级数字块 + 红「玫」/蓝「兽」/灰「？」标记点），填亮槽数即伤害（不变量与风险登记见票面裁决 2，14 号扩展能力时须复核）；等级文案全局去角色名；亮牌/归还窗口槽位高亮、自视未亮槽位暗色预填。纯前端改动，引擎/协议零变更。

## Fog

截至文首基线，以下事项仍未收口；后续应以各项落库记录更新状态。

- **待处理：发布 smoke 修复与验收（交接 1）**。[脚本](../../scripts/release_smoke.py) 的两处 hello 仍发送 `protocolVersion: "1"`，与当前 v3 不符；只验证开局、传刀、重连和未终局回放的 409，没有终局后成功回放验证。[11 的 Comments](issues/11-accessibility-performance-release.md)记录用户已关闭该票，但未消除此缺口。修复与运行证据应进入发布专用记录，入口为[发布检查表](../../docs/release-checklist.md)；本路线图尚无其完成证据。
- **待处理：重复 spec 收口（交接 2）**。[coupling-test-hardening](../coupling-test-hardening/spec.md)仍标 `ready-for-agent`；B7/B9/C2 的主要补强已由[skill-coupling-test-hardening](../skill-coupling-test-hardening/spec.md)在 `b19e59e` 完成。按交接 2 核对重复 spec 的逐项覆盖并收口；当前不能把重复需求当作全新实现票，也不能在此代改其状态。
- **延期：golden 分支锁补全**。当前七份 6–12 人 fixtures 未包含法师抹除 `IdentityMarkersObscured`、守护者归还 `ResourceReturned`；两者已有专项行为测试，但 golden 锁仍缺。以[已完成补强 spec 的 Comments](../skill-coupling-test-hardening/spec.md)与[重复 spec 的延期说明](../coupling-test-hardening/spec.md)为入口，后者将 B9 锁挂起到后续 ruleset bump；当前 0.6 fixtures 仍未走到这两分支。本次不重生成基准，也不扩大 runner 范围。
- **既有产品后续项**：[主规格 Open questions](spec.md)仍列官方素材下载来源与穿透人工验证（WAN IP、手机侧抽查、frp+VPS 购前实测）；手机/平板全面支持、可选 AI 是后续计划。[门控 spec Further Notes](../intervention-request-gate/spec.md)另登记技能产物公开性的存量核查待办，尚非已完成批次；规则落盘与具体工作范围沿该入口收口。
- **已取消的范围**：[ui-polish](../ui-polish/spec.md)整份保持 `wontfix`，其中教学/图例已单独拆出并完成；横幅合并与紧迫态、复制分享、名册卡片化仍取消。[ui-fix-usability 的 2026-10-04 Comments](../ui-fix-usability/spec.md)同时取消第三批动效等事项；这些不是当前 frontier。

前端 vitest/RTL 基建与门控批次多视角 E2E 验收均已存在（见下方入口）；它们不等于持续运行的浏览器 E2E 框架。当前仍无测试 CI 门禁，参见重复测试 spec 的 Further Notes；是否另立自动化任务由后续范围决定。

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
- [21 设置环节：阵营徽记定向展示（setup.clue-icon）](issues/21-clue-icon-neighbour-reveal.md)
- [22 攻击无人干涉后匕首归受伤目标](issues/22-attack-dagger-to-wounded-target.md)
- [23 全员公开自愿干涉投票](issues/23-intervention-volunteer-poll.md)
- [24 座位卡三格线索槽与伤害显示（fe_iconchange）](issues/24-clue-slots-damage-display.md)
- [25 点击闪光槽位亮牌/归还](issues/25-slot-click-reveal.md)
- [26 审判者万能标记色选增加问号](issues/26-wild-color-question-option.md)

## 其他批次入口

以下引用各自主 spec；实现、验收与提交记录留在各批次。本路线图只汇总状态。

- [前端测试基建](../frontend-test-infra/spec.md)：索引无 Status，唯一子票 `resolved`；vitest + RTL + jsdom 已落地，见[01 完成记录](../frontend-test-infra/issues/01-vitest-rtl-waiting-room-tests.md)。
- [备忘标记](../memo-markers/spec.md)：spec 与唯一子票 `resolved`（`6c5ce08`）；客户端私有猜测标记，见 [ADR-0004](../../docs/adr/0004-memo-markers-client-only.md)。
- [审判者诅咒技能](../inquisitor-curse-skill/spec.md)：spec 与唯一子票 `resolved`（`f80018d`）；亮等级后发动/放弃分发，见 [ADR-0003](../../docs/adr/0003-inquisitor-curse-as-reveal-triggered-skill.md)。
- [事件日志类别](../event-log-categories/spec.md)：`resolved`（`668471c`）；六类日志与本机筛选偏好。
- [手机可用性修复](../ui-fix-usability/spec.md)与[圆桌主题](../ui-table-theme/spec.md)：均 `resolved`；窄屏、进房失败态、中文元数据与主题已完成，第三批取消记录在可用性 spec。
- [教学/图例](../ui-help-legend/spec.md)：spec 与帮助按钮子票 `resolved`；大厅简介、技能表和图例已完成，角色名范围见 [ADR-0005](../../docs/adr/0005-help-overlay-official-character-names.md)。[浮层关闭按钮](../ui-help-close/spec.md)也已 `resolved`。
- [规则耦合共识](../rule-coupling-review/spec.md)：索引无 Status，01–07 全部 `resolved`；2026-10-03 裁决实施与 ruleset 0.5 收尾，见 [07 完成记录](../rule-coupling-review/issues/07-ruleset-bump-coverage-golden-helpcontent.md)及 ADR 0006–0011。
- [技能耦合测试补强](../skill-coupling-test-hardening/spec.md)：`resolved`（`b19e59e`），B7/B9/C2 行为测试与断血验证完成；[同题重复 spec](../coupling-test-hardening/spec.md)仍 `ready-for-agent`，待交接 2 收口。
- [干涉请求门控](../intervention-request-gate/spec.md)：spec 与 01–05 全部 `resolved`；ruleset 0.6 / 协议 v3，提交映射在主 spec，测试/golden/E2E 在[05 完成记录](../intervention-request-gate/issues/05-tests-golden-docs.md)。
- [体验打磨旧 spec](../ui-polish/spec.md)：`wontfix`；教学范围已拆出，其余取消项见「Fog」。
