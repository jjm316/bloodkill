# 设计领域模型与状态契约

Type: task
Blocked by: 02
Status: resolved

问题：为玩家、势力/单位、区域/版图、卡牌/能力、资源、阶段、公共区、胜利分和事件定义稳定的领域模型与不变量。

输出：状态快照 schema、命令/事件目录、合法性规则、序列化格式、错误码和状态迁移图；明确哪些值由引擎计算，哪些只是 UI 投影。

完成条件：能从初始状态重建任意场景；非法状态可被校验器拒绝；schema 有向后兼容策略和示例 fixture。

## Answer

已完成 [领域模型与状态契约](../domain-model-contract.md)。契约定义了：

- 包含私有身份和 token 所有权的 `EngineState`，以及按玩家裁剪的 `PlayerView`；
- 6--12 人、偶数双家族和奇数审判者局的不变量，伤害、捕获、匕首、资源、护盾/扇子和 pending window 约束；
- 建局、传匕首、攻击、干涉、技能和诅咒分发命令目录，以及不可由 UI 直接发出的事实事件目录；
- 干涉/技能/终局状态迁移图、稳定错误码、幂等与 revision 检查；
- `schemaVersion`/`rulesetVersion` 的向后兼容、事件追加和快照恢复策略；
- 7 人审判者局与偶数局 setup fixture 形状。

权威事件日志与可丢弃快照的架构决策记录在 [ADR-0001](../../../docs/adr/0001-authoritative-event-log.md)，领域术语记录在 [CONTEXT.md](../../../CONTEXT.md)。

## Comments

- 2026-08-20：从 frontier 认领并完成；未对来源 C 未覆盖的发言变体或未核验出版版本新增规则假设。
