# Blood Bound 规则语料：用户提供摘录

日期：2026-08-19  
来源 C：用户粘贴的英文规则书正文摘录（最高优先级）；来源 A：中文规则摘录；来源 B：玩法说明与角色解读；关联 URL：`https://andyventure.com/boardgame-blood-bound/`（当前未能独立读取）  
证据状态：来源 C 是当前规范依据，非官方授权/版本证明；C 未覆盖处不以 A/B 猜测补齐

## 可作为当前规范的规则

| 规则 ID | 规则摘要 | 待验收重点 |
| --- | --- | --- |
| `setup.equal-factions` | 6–12 人；偶数人数时从 Rose、Beast 各选取玩家数一半的不重复身份 | 两阵营人数相等；两张审判官不入局 |
| `setup.inquisitor` | 奇数人数时从两张审判官中随机选一张，Rose/Beast 各选取人数向下取整的一半；7/9/11 人局均放置 1 张诅咒卡 | 诅咒卡数量已由产品方裁决 |
| `setup.clue-icon` | 每位玩家只向其左手边玩家展示 clue icon | Harlequin 的 clue icon 为敌对家族；审判官虽显示 Rose/Beast clue 但真实属于 Secret Order |
| `turn.dagger-holder` | 只有匕首持有者主动行动；可传递匕首或攻击任意玩家 | 攻击后匕首交给攻击目标 |
| `damage.reveal` | 每点伤害展示一个此前未展示的标记：玩家自选等级（rank）或身份标记（红/蓝/？），身份标记组合由 rank 决定 | 第 3 点被迫展示 rank、第 4 点被捕获；仅审判官 wild 可取任意颜色身份标记 |
| `intervention.request` | 仅攻击目标可请求干涉；rank token 仍在供应区的玩家可响应 | 被选干涉者承伤并强制展示 rank；技能伤害不可干涉 |
| `skill.reveal-rank` | 因**攻击**伤害展示 rank 时，可立刻发动对应角色技能 | 技能伤害不触发技能；炼金治疗后若退回 rank，可在下次重新取得 rank 时再发动 |
| `game.end` | 任一玩家第 4 点伤害被捕获时立即结束 | 家族 active player 按领袖规则判定；审判官造成第 4 点伤害时走独立失败分支 |
| `inquisitor.attack-limit` | 审判官不能攻击已受 3 点伤害的玩家 | 禁止命令必须带可解释原因 |
| `inquisitor.curse` | 审判官查看供应区全部诅咒，暗置分发给不同玩家 | True Curse 在正常胜方领袖前时，审判官独赢；审判官被捕获也独赢 |
| `inquisitor.capture-branch` | 审判官作为 active player 造成第 4 点伤害时，审判官自身判负，其他方按该分支获胜 | 不把审判官临时归入 Rose/Beast |

## 角色能力语义

下表是来源 C 的行为改写，供引擎使用；不是原始卡牌文案或 UI 显示文本。每个家族各有一张相同规则的 1–9 身份。

| Rank | 规则 ID | 能力语义 |
| --- | --- | --- |
| 1 | `elder` | 取得 Quill；本家族领袖改为等级最高的角色。 |
| 2 | `assassin` | 指定一名玩家承受 2 点伤害，再将匕首交给该玩家。 |
| 3 | `harlequin` | 秘密查看两名玩家的角色；其 clue icon 显示敌对家族。 |
| 4 | `alchemist` | 仅在自己干涉后，可令被干涉者承受或治疗 1 点伤害；治疗时该玩家退回任一已展示 token。若退回 rank，之后重新展示 rank 时可再次使用能力。 |
| 5 | `mentalist` | 指定一名玩家承受 1 点伤害，通常强制其展示 rank；若该 rank 已展示则展示 affiliation。再将匕首交给该玩家。 |
| 6 | `guardian` | 向一名玩家给出同色 Shield，自己取得匹配 Sword。受 Shield 保护者不能成为攻击或强制伤害目标，但可干涉并正常承伤。持 Sword 的 Guardian 第 3 点伤害时，归还该 Sword 与对应 Shield。 |
| 7 | `berserker` | 令刚刚攻击自己的玩家承受 1 点伤害。 |
| 8 | `mage` | 给一名玩家 Staff；该玩家的身份标记全部变为问号（?）。 |
| 9 | `courtesan` | 向一名玩家给出 Fan；该玩家成为攻击目标时，他人不能干涉。 |
| fleur cross | `inquisitor` | 两张审判官仅 clue icon 不同，共用同一个 fleur cross rank token；查看供应区诅咒并暗置分给不同玩家；其 affiliation 为 wild，且不能攻击已受 3 点伤害者。被捕获或满足 True Curse 夺胜条件时独赢。 |

### 身份标记组成（2026-08-22 澄清）

每名玩家 3 张标记：1 张等级（rank 1–9）+ 2 张身份标记（红/蓝/？）。身份标记组合由 rank 决定：

| Rank | 红方身份标记 | 蓝方身份标记 |
| --- | --- | --- |
| 1 长老 | 红 红 | 蓝 蓝 |
| 2 刺客 | ? ? | ? ? |
| 3 小丑 | ? ? | ? ? |
| 4 炼金术师 | ? ? | ? ? |
| 5 感应者 | 红 红 | 蓝 蓝 |
| 6 守护者 | 红 红 | 蓝 蓝 |
| 7 狂战士 | 红 ? | 蓝 ? |
| 8 法师 | 红 ? | 蓝 ? |
| 9 交际花 | 红 ? | 蓝 ? |

受伤后玩家自选展示身份或 rank（通常先亮身份、尤其 `?` 藏阵营）；前 2 点可各亮 1 张身份，第 3 点被迫亮 rank；挡刀（干涉）被迫亮 rank 并开技能窗（decline = 永久失去技能）。

### 产品方裁决（2026-08-22）

来源 C 文本与产品方裁定冲突处，以产品方裁定为准：

- **Elder 领袖**：来源 C 写「羽毛 = 家族中除你外最小等级者代领」，产品方裁定为「领袖改为数字最大者（rank 9）」。上表 rank 1 已按「数字最大」书写。
- **Guardian 盾**：来源 C 写「持盾者不能响应干涉」，产品方裁定保留「可干涉」（不能成为攻击/强制伤害目标，但可响应干涉并正常承伤）。上表 rank 6 已按此书写。
- **Mage 法杖**：来源 C 有两条法杖文案，产品方裁定为「一个效果——给一名玩家 Staff，该玩家身份标记全变问号」。上表 rank 8 已按此书写。
- **Courtesan 扇**：来源 C 写「被攻击时无法请求干涉」，产品方裁定为「他人不能为该玩家干涉」。上表 rank 9 已按此书写。

引擎数据应使用原创规则 ID、原创显示文案和可替换资源；不得导入或展示原始卡牌文本、插画或 Logo。

## 暂定验收场景

以下场景只覆盖两份来源一致的核心规则。`Given` 中的角色/标记均为测试 fixture 的规则 ID，不要求复制原作显示文本。

### `setup/even-player-factions`

Given 8 名玩家和确定性随机源  
When 创建基础对局  
Then 红、蓝阵营各发出 4 张不重复身份，恰有一名玩家持有匕首，且每个玩家的左邻已获得其表象阵营投影。

### `setup/odd-player-inquisitor`

Given 7 名玩家和已提供的诅咒卡数量配置  
When 创建审判官对局  
Then Rose 与 Beast 各发出 3 张不重复身份，并从两张审判官中随机发出 1 张；准备 1 张诅咒卡与 fleur cross rank token。

### `turn/pass-dagger`

Given A 持有匕首且对局未结束  
When A 向 B 传递匕首  
Then 只产生传递事件，B 成为下一位可行动者，任何玩家均不失去生命或展示新线索。

### `combat/attack-handoff`

Given A 持有匕首，B 尚未展示任何线索且未请求干涉  
When A 攻击 B  
Then B 成为匕首持有者、受到 1 点伤害，并从尚未展示的线索中展示恰好一张。

### `combat/third-and-fourth-damage`

Given B 已展示两张线索且累计受到 2 点伤害  
When B 再受到 1 点可结算的伤害  
Then B 的三张线索均公开而 B 仍存活。  
When B 随后受到第 4 点伤害  
Then 对局立即结束，不再接受任何传递、攻击或技能命令。

### `intervention/selected-responder`

Given A 攻击 B，B 请求干涉，C 和 D 的 rank token 均仍在供应区  
When B 选择 C  
Then C 接过匕首并承受该点伤害，且 C 必须展示等级线索；B 不承受该点伤害，D 不受影响。

### `intervention/refused`

Given A 攻击 B，B 请求干涉且有至少一名响应者  
When B 拒绝全部响应  
Then B 接过匕首并承受该点伤害；该攻击中不再开启第二次干涉。

### `skill/reveal-rank-from-attack`

Given B 因攻击伤害选择或被要求展示等级线索，且其技能可用  
When 伤害展示结算完成  
Then 立即产生唯一一次该身份的可选技能窗口；任何由该技能造成的伤害均不创建新的干涉或技能窗口。

### `game/end-on-leader`

Given X 的阵营领袖仍为最小等级身份，active player A 属于敌对阵营，且 X 已受 3 点伤害  
When X 受到第 4 点伤害而被捕获  
Then A 的阵营获胜，并附带“active player 捕获敌方领袖”的可解释结果。

### `game/end-inquisitor-true-curse`

Given 正常家族胜方已经确定，且该胜方当前领袖持有 True Curse  
When 公开诅咒卡  
Then 审判官独赢，家族胜利被覆盖。

### `game/end-inquisitor-active-capture`

Given 审判官是 active player，目标玩家已受 3 点伤害  
When 审判官的攻击造成目标第 4 点伤害并使其被捕获  
Then 审判官按独立分支判负，其他方按该分支获胜。

## 未决项

- 规则书第 8 页诅咒卡比例已裁决：7/9/11 人局均为 1 张。
- 两张审判官仅 clue icon 不同，共用同一 fleur cross rank token；其 affiliation 为 wild。
- 审判官作为 active player 造成第 4 点伤害时走独立分支：审判官判负，其他方获胜。
- 发言模式：来源 A 提供“公开自由发言”或“全程禁言”两个变体；来源 C 未定义此项，应作为房间规则配置而非引擎隐含行为。
