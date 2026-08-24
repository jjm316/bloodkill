# 实现 rank 3–9 能力与资源经济

Type: task
Blocked by: 17、18、19、20
Status: open

问题：rank 3–9 的能力语义已由来源 C 提供（见 [rules-corpus-user-extract.md](../rules-corpus-user-extract.md)），当前在 `content/catalog.json` 中标 `unimplemented`；rank 1 `elder` 的「本家族领袖改为等级最高者」规则、以及 `shield`/`sword`/`staff`/`fan` 资源的发放与消耗也未实现。[spec.md](../spec.md) 的 MVP 边界明确包含「能力触发、资源变化」。

输出：实现九个能力（含 rank 1 领袖规则）与资源经济。能力语义以「已裁决」为准，其次按来源 C 补齐。

| Rank | 能力 | 关键行为 |
| --- | --- | --- |
| 1 `elder` | 补领袖变更 | 取得 Quill；本家族领袖改为**数字最大**者（rank 9，无 9 则 8……；影响 `_is_leader` 终局判定） |
| 3 `harlequin` | 秘密查看 | 秘密查看两名玩家身份（公开目标、秘密反馈）；clue icon 显敌对家族 |
| 4 `alchemist` | 治愈/伤害 | 仅成功响应干涉后可令被干涉者治愈或伤害 1；治愈退回一张已展示标记（退回 rank 后二次展示不可再发技能） |
| 5 `mentalist` | 1 伤 + 匕首 | 指定玩家 1 伤并强制展示 rank（已展示则身份标记）；匕首交给该玩家 |
| 6 `guardian` | 盾/剑 | 给 Shield、自己得同色 Sword；持盾者不能成为攻击/强制伤害目标但可干涉；Guardian 第 3 伤时归还 Sword 与对应 Shield |
| 7 `berserker` | 反击 | 令刚刚攻击自己的玩家承受 1 伤 |
| 8 `mage` | 法杖 | 给一名玩家 Staff；该玩家的身份标记全部变为问号（?） |
| 9 `courtesan` | 扇 | 给一名玩家 Fan；该玩家被攻击时他人不能干涉 |

已裁决（2026-08-22，产品方；实现延后，待产品方指示后开工）：

1. **身份标记模型**：每名玩家 3 张标记 = 1 等级（rank 1–9）+ 2 身份标记（红/蓝/？）。身份标记组合由 rank 决定：1/5/6 = 红红·蓝蓝，2/3/4 = ？？·？？，7/8/9 = 红？·蓝？。受伤自选展示身份或 rank；第 3 点被迫亮 rank；挡刀被迫亮 rank（并开技能窗，decline = 永久失去技能）。
2. **Elder 领袖规则**：用羽毛后领袖 = 家族**数字最大**者（rank 9）。来源 C 写「最小」，产品方裁决为「最大」，以本票为准。
3. **Guardian 盾**：持盾者不能被攻击/强制伤害目标，**但可干涉**。来源 C 写「不能响应干涉」，产品方裁决保留「可干涉」。
4. **Mage 法杖**：**一个效果**——给一名玩家 Staff，该玩家身份标记全部变为问号（?）。来源 C 的两条法杖文案合并为这一条。
5. **Courtesan 扇**：给一名玩家 Fan；该玩家被攻击时他人不能干涉（来源 C 写「无法请求干涉」，按「他人不能干涉」实现）。

同步：更新 catalog 各能力 `implementation` 标记与占位文案；扩展引擎 `_IMPLEMENTED_SKILL_RANKS` 为 1–9；把 `Player` 的单一 `affiliation` 线索改为「1 rank + 2 身份标记」（含 schema 变更与投影）；新增/扩展 pending window 类型（harlequin 目标选择、alchemist 治愈/伤害、guardian 盾目标等）；补测试。

完成条件：九个 rank 能力均可被触发且行为符合「已裁决」与来源 C；身份标记按 rank 组成正确展示（红红/蓝蓝、？？/？？、红？/蓝？）；资源有明确发放/消耗/归还路径（`ResourceGranted`/`ResourceSpent`/`ResourceReturned` 事件）；终局领袖判定随 elder 正确变化（默认最小 → 用羽毛后最大）；性质测试覆盖新分支。

## 拆分（2026-08-24）

本票转为伞票，不直接产出代码；拆为四张顺序子票：

1. [17](17-identity-markers-reveal-flow.md)：身份标记模型与自选展示流程（地基；顺带修复 15/16，重构后保留旧缺陷反而需要刻意维护）；
2. [18](18-resource-economy-elder-leader.md)：资源经济骨架（`ResourceGranted`/`ResourceSpent`/`ResourceReturned` 三路径）与 elder 领袖规则；
3. [19](19-targeted-abilities.md)：目标选择型能力 harlequin(3) / mentalist(5) / guardian(6) / mage(8) / courtesan(9)；
4. [20](20-intervention-coupled-abilities.md)：干涉耦合型能力 alchemist(4) / berserker(7)，`_IMPLEMENTED_SKILL_RANKS` 补齐 1–9。

依赖链 17 → 18 → 19 → 20。各子票 resolved 后，本票按上方完成条件整票验收关闭。

## Comments

- 2026-08-24：拆分理由——全部能力都踩在「标记模型 + 自选展示结算」这一共同地基上，按 rank 平切会产生伪中间态；地基之外的能力彼此独立，故按「一个地基 + 三批能力」拆分。quill 的消耗语义按「羽毛消耗于改写继承顺序」建模（18 票面第 3 条），如产品方改判需回到 18 调整。
