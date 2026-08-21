# 实现 rank 3–9 能力与资源经济

Type: task
Blocked by: 10（测试网）、13（抑制技能窗）
Status: open

问题：rank 3–9 的能力语义已由来源 C 提供（见 [rules-corpus-user-extract.md](../rules-corpus-user-extract.md)），当前在 `content/catalog.json` 中标 `unimplemented`；rank 1 `elder` 的「本家族领袖改为等级最高者」规则、以及 `shield`/`sword`/`staff`/`fan` 资源的发放与消耗也未实现。[spec.md](../spec.md) 的 MVP 边界明确包含「能力触发、资源变化」。

输出：实现七个能力与领袖规则，接通资源经济：

| Rank | 能力 | 关键行为 |
| --- | --- | --- |
| 1 `elder` | 补领袖变更 | 取得 Quill；本家族领袖改为等级最高者（影响 `_is_leader` 终局判定） |
| 3 `harlequin` | 秘密查看 | 秘密查看两名玩家身份；clue icon 显敌对家族 |
| 4 `alchemist` | 治愈/伤害 | 自己干涉后可令被干涉者治愈或伤害 1；治愈退回已展示 token |
| 5 `mentalist` | 1 伤 + 匕首 | 指定玩家 1 伤并强制展示 rank（已展示则 affiliation）；匕首交给该玩家 |
| 6 `guardian` | 盾/剑 | 给 Shield、自己得 Sword；第 3 伤时归还 Sword 与对应 Shield |
| 7 `berserker` | 反击 | 令刚刚攻击自己的玩家承受 1 伤 |
| 8 `mage` | 法杖 | 自己与另一玩家各得 Staff；持 Staff 展示 affiliation 须展示 unknown |
| 9 `courtesan` | 扇 | 给一名玩家 Fan；该玩家成为攻击目标时他人不能干涉 |

同步：更新 catalog 各能力 `implementation` 标记与占位文案；扩展引擎 `_IMPLEMENTED_SKILL_RANKS` 为 1–9；新增/扩展 pending window 类型（harlequin 目标选择、alchemist 治愈/伤害、guardian 盾目标等）；补测试。

完成条件：九个 rank 能力均可被触发且行为符合来源 C；资源有明确发放/消耗/归还路径（`ResourceGranted`/`ResourceSpent`/`ResourceReturned` 事件）；终局领袖判定随 elder 正确变化；性质测试覆盖新分支。
