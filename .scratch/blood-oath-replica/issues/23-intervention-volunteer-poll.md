# 干涉改为全员公开自愿投票模型

Type: task
Blocked by: 无
Status: resolved

问题：现状干涉 pending 的唯一操作者是被攻击者（`blood_bound/engine.py` `_attack` 写入 `Pending("intervention", target, target, eligible)`，`projection.py` 仅向 actor 发合法操作）：目标点"请求干预"后可从全部有资格玩家中任点一人强制承伤，被点名者无拒绝权，其余玩家全程无感知、无操作。产品方 2026-09-04 裁定改为全员公开自愿投票模型（规则语料"产品方裁决（2026-09-04）"、`docs/adr/0002-intervention-volunteer-poll.md`）。

需求：

1. 攻击声明后自动开启干涉投票，删除目标的"请求"步骤。有资格玩家（存活、非攻击方、非目标、rank 未展示、目标未持扇）逐人表态；资格集为空（如目标持扇）时不开投票、直接结算，维持现状。
2. 表态实时公开：逐人表态事件即时广播，全员可见谁干涉、谁不干涉、谁未表态；答后不可反悔。全员表态完毕后攻击才实际结算——无人自愿→按攻击正常结算；恰一人自愿→干涉必然发生，被攻击者无权拒绝；≥2 人自愿→被攻击者从自愿者中选一人承伤，或全部拒绝（拒绝则攻击正常结算）。
3. 干涉超时：房主在等待界面"开始对局"旁下拉配置（30/60/90/120/180 秒，默认 90），对局开始后固定；倒计时全员可见（等待横幅显示"等待 X、Y 表态（剩 N 秒）"）。投票阶段到期未表态者视为不干涉；目标三选一阶段到期自动"全部拒绝"。超时等待机制必须抽象为可复用组件（后续其他窗口按需接入），本期只接入干涉投票与目标三选一两处。
4. 默认不挡刀：客户端 localStorage 偏好，游戏界面角落常驻勾选开关"默认不挡刀"，对局中随时可改。开启后不弹确认，客户端收到投票状态即自动代发"不干涉"；若在投票进行中才开启且本人尚未表态，立即代发。已表态不因开关变化撤销。
5. 交互与复用：干涉确认用模态弹窗"是否为 X 挡刀？"（挡刀 / 不干涉两键）。弹窗实现为带确认和取消按钮的通用组件，每次使用只改按钮文案与点击后的行为逻辑。
6. 干涉承伤后果不变：承伤者强制展示 rank + 开技能窗（rank 4 炼金术师仅此场景可用）+ 匕首交给承伤者。
7. 术语：面向用户文案统一"干涉/挡刀"（弹窗文案"是否为 X 挡刀？"），客户端现有"干预"字样全部改掉；协议与规则 ID 仍用英文 intervention。

输出：

- engine：多操作者 pending（逐人表态收集 + 0/1/≥2 分支结算）、新表态命令、`request-intervention` 移除、`decline-intervention`/`choose-intervention` 收窄为 ≥2 分支目标专属、超时抽象与到期结算、事件与 PROTOCOL.md 及协议版本更新。
- projection：按玩家分发投票合法操作、实时表态名单与倒计时等待视图。
- server：房主开局超时配置的下发与广播沿用现有公开事件机制。
- client：通用确认弹窗组件、干涉投票模态、实时表态列表 + 等待倒计时横幅、默认不挡刀开关（localStorage）、等待界面房主超时下拉、清除"干预"文案。
- 文档与测试：CONTEXT.md 词条已更新（干涉投票/挡刀/干涉超时）；`docs/rule-branch-coverage.md` 补齐投票分支（0/1/≥2 自愿、两阶段超时、资格集为空、默认不挡刀代发、不可反悔）；单测覆盖全部分支；golden 按流程重建。旧存档不做兼容（ADR 0002 已裁决）。

完成条件：0/1/≥2 自愿、投票与三选一两阶段超时、资格集为空直结算、默认不挡刀代发、答后不可反悔等分支均有测试；golden 重生成后全量测试通过（`.venv` 的 unittest discover）；rule-branch-coverage 与 PROTOCOL.md 同步；用测试工具箱多窗口实测投票、倒计时与默认不挡刀表现正常。

## Answer

已实现（2026-09-04）：

- engine（ruleset 0.2 → 0.3，旧存档不兼容）：`_attack` 资格集为空直接结算，否则开 poll 阶段 pending（context 记 stage/responses，**不记墙钟**——重放确定性禁止真实时间进权威状态）；新命令 `respond-intervention`（逐人表态，`intervention.already-responded` 不可反悔）与服务器托管的 `timeout-intervention`（投票到期未表态视为不干涉、三选一到期自动全部拒绝）；`_close_poll` 按 0/1/≥2 分支结算，`choose/decline-intervention` 收窄为 choice 阶段目标专属；`start-game` 接受 `interventionTimeoutSeconds`（30/60/90/120/180，缺省 90，非法值 `game.invalid-timeout`）；`request-intervention` 与 `InterventionOpened` 移除。
- projection：poll 阶段向每个未表态的有资格玩家发 respond 操作；pending view 公开 stage/responses/volunteerPlayerIds（旁观者同见），context 仍不暴露；顶层新增 `interventionTimeoutSeconds`。
- server：协议版本 2；`Room` 持有并持久化窗口 deadline（meta 落盘，重启后过期窗口由 `@app.on_event("startup")` 立即结算），`build_state` 注入 `pending.deadline` 与 `serverTime`；`server/deadlines.py` 为可复用到期调度抽象（WINDOW_PROVIDERS 插件式接入，本期只挂干涉 poll/choice 两处）；host `start` 动作携带超时配置。
- client：`ConfirmDialog` 通用确认弹窗（只改文案与点击行为）；干涉投票模态"是否为 X 挡刀？"（挡刀/不干涉）；等待横幅"等待 X、Y 表态（剩 N 秒）"（serverTime 对齐的本地倒计时）；默认不挡刀 localStorage 常驻开关（进行中开启且未表态立即代发，每投票只代发一次）；等待室房主干涉时限下拉；事件文案全部改为 干涉/挡刀，清除"干预"。
- 测试与文档：`InterventionPollBranchTests`（11 用例）+ `DeadlineWindowTests`（5 用例）覆盖 0/1/≥2、两阶段超时、守卫、配置、恢复；既有测试迁移到投票模型；golden 6–12 人重生成，全量 140 通过；PROTOCOL.md、rule-branch-coverage.md、domain-model-contract、server/README 同步。
- 待用户手动验收：测试工具箱多窗口实测投票弹窗、倒计时与默认不挡刀的实际表现。
