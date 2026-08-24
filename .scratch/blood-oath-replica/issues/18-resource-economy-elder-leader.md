# 资源经济骨架与 elder 领袖规则（14 子票）

Type: task
Blocked by: 17
Status: open

问题：资源经济只有 rank 1 发放 quill 的雏形，`ResourceSpent`/`ResourceReturned` 两条事件路径不存在；elder 的「本家族领袖改为数字最大者」规则未实现，`_is_leader` 始终按最小 rank 判定。本票落地资源事件词汇与 elder 完整行为，为 19（guardian/mage/courtesan 的发放与归还）提供公共路径。

语义依据：[14](14-abilities-resource-economy.md) 票面「已裁决」第 2 条（Elder 领袖 = 数字最大者，来源 C 的「最小」已被产品方推翻）。

输出：

1. **资源事件三条路径**：`ResourceGranted {playerId, resource, amount}`（已有）；新增 `ResourceSpent {playerId, resource, amount, reason}` 与 `ResourceReturned {playerId, resource, amount, reason}`；域校验追加资源计数非负。契约文档命令/事件表同步。
2. **elder（rank 1）完整行为**：技能 use → `ResourceGranted` quill → 立即 `ResourceSpent` quill（`reason: "leader-succession"`）→ 该家族领袖规则永久翻转为数字最大（`EngineState` 记录翻转旗标，如 `max_leader_factions`；`_is_leader` 对翻转家族取存活成员 max rank，未翻转家族保持 min）。终局分支 `captured-leader` / `captured-player` 随之正确变化。
3. **建模裁决记录**：「用羽毛后领袖改为数字最大」按「羽毛消耗于改写继承顺序」实现——这是五个资源中唯一自然的消耗语义，使 `ResourceSpent` 有真实路径，同时满足「默认最小 → 用羽毛后最大」的判定要求。若产品方日后改判为「持羽毛期间最大」，只需把旗标判定改为检查存活家族成员的 quill 持有，事件形状不变。
4. **测试**：quill 发放 + 消耗事件序列与净持有归零；翻转前后 `_is_leader` 终局判定（默认最小 → 翻转后最大，含 rank 9 已捕获/缺席时回落 8 的语义）；catalog `ability.rank.01` 的 `implementation` 改为 `grant-quill-leader-max`（或同义 slug）并更新双语文案。

完成条件：

- `ResourceGranted`/`ResourceSpent` 在 elder 路径上成对出现，事件 payload 含稳定字段；
- elder 使用技能后，其家族按最大 rank 判定领袖的终局测试通过（翻转前后各一条）；
- 全量 `.venv\Scripts\python.exe -m unittest discover -v` 通过。

## Comments

- 2026-08-24：由 14 拆分。quill 的消耗建模是本票唯一的解释性裁决，已按上述第 3 条锁定并留有待确认注记；实现者不要改为「永久持有 quill」模型，除非产品方明确改判。
