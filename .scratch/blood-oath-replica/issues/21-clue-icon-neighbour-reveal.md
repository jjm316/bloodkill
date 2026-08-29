# 设置环节：阵营徽记定向展示（setup.clue-icon）

Type: task
Status: resolved

问题：规则 `setup.clue-icon`（[规则语料](../rules-corpus-user-extract.md)；中文说明书第 6 页设置步骤 5"每个玩家向左边玩家展示自己的线索标记，注意不要暴露自己的其他信息"）在当前线上实现中完全缺失：引擎 `_start` 已生成并持久化 `clueIcon`（rank 3 反转、审判官随机玫瑰/野兽），但投影不下发、前端无展示环节，连玩家自己都看不到自己的徽记（rank 3 与审判官不知道自己该展示什么）。参考照片：`pictures/《鲜血盟约》说明书_6/7_*.jpg`。

语义依据：说明书第 7 页明确审判官角色卡也显示野兽或玫瑰家族标记，同样参与展示；[domain-model-contract](../domain-model-contract.md) PlayerView 段落明确允许包含 clue icons（不在必须隐藏清单内）。

## 已裁决（2026-08-30 grilling 会话，产品方确认）

1. **形态：纯投影，不加 setup 阶段**。线下该步骤无选择、无顺序、全员同时完成，不值得状态机；信息永久有效（"看过就记住"），投影从 GameStarted 起永久可见。无 schema/ruleset 版本变更（`clueIcon` 一直在存档中，引擎状态结构不变，旧局恢复天然兼容）。
2. **公开事件只记展示关系，不记内容**："谁向谁展示"是线下公开事实（座位公开后信息量为零），只有内容私密。开局追加**一条**批量事件 `ClueIconsShown`，payload 携带 `pairs: [{fromPlayerId, toPlayerId}, ...]`（N 条，无任何徽记内容），日志一行"全员已向左邻展示阵营徽记"，避免手机刷屏。
3. **中文术语：阵营徽记**。不用"阵营"（rank 3 的徽记是敌对家族、审判官徽记是随机家族，叫"阵营"会与身份面板自相矛盾）；不用"线索标记"（与"身份标记"字面撞车）。CONTEXT.md 已立词条（阵营徽记、左邻/右邻）。
4. **方向约定：俯视桌面顺时针 = 座位号递增**；"左邻" = 按 seat 排序后的下一位，每人向左邻展示，因此每名玩家看到的是**上一位（右邻）**的徽记。邻接关系按 seat 排序后循环相邻定义（容忍座位空洞）。UI 文案不出现"左右"，只说"你看到了某某的阵营徽记"。
5. **UI 呈现：自己座位卡身份区一段短文案**（手机优先、无悬停依赖），如"你的徽记：玫瑰 · 已看到 某某 的：野兽"；不在邻座卡上加图标（后置）。全部 UI 文案使用中文（AGENTS.md）。
6. **审判官不变量**：审判官 `clueIcon ∈ {rose, beast}` 而真实 affiliation 为 `wild`，徽记必然与真实所属不符——构造性成立，补显式测试钉死。rank 3 恒为敌对家族徽记，按现状展示。

## 实现清单

1. **引擎**（`blood_bound/engine.py`）：`_start` 在 `GameStarted` 后追加一条 `ClueIconsShown` 事件（`pairs` 按 seat 排序：每名玩家 → 其左邻）。徽记值本身不进事件。
2. **投影**（`blood_bound/projection.py`）：`viewer` 块新增 `clueIcon`（自己的徽记，所有玩家含审判官）与 `seenNeighbourClue`（`{playerId, icon}`，右邻的徽记）；旁观者 `viewer=None` 自然不可见。公开 `players[]` 条目保持不含任何 clueIcon。性质测试 `ProjectionSecrecyPropertyTests.test_no_projection_leaks_seed_identity_or_curse` 只查 `players[]` 条目与 seed 字符串，与新字段不冲突（需全量跑确认）。模块 docstring 中"clue icon 不属于投影"的注释同步更正。
3. **前端**（`client/src`）：`types.ts` 补 viewer 字段类型；`Board.tsx` 自己座位身份区渲染徽记文案；`GameScreen.tsx` 事件名表补 `ClueIconsShown`；文案全中文。
4. **文档与协议**：`server/PROTOCOL.md` 补事件类型；`docs/rule-branch-coverage.md` 补 `_start` 新事件分支行；[domain-model-contract](../domain-model-contract.md) PlayerView 段落补一句"viewer 块含本人 clueIcon 与右邻徽记"。
5. **测试**：投影用例（自己可见自己+右邻、非右邻关系的投影不含他人徽记、旁观者不可见）；回放投影 `viewer=None` 不含徽记（`rooms.replay` 用 `project_state(state, None)`，天然满足，补断言防回归）；审判官徽记必错不变量；rank 3 反转展示。golden replay fixtures 若因新事件漂移，按规则变更流程同步（当前 fixtures 记录事件签名，新事件会使其失败，属预期漂移）。

## 完成条件

- 开局后每名玩家在 UI 上能看到自己的阵营徽记与右邻徽记，且仅自己可见；
- 开局事件日志恰好新增一行展示关系记录，payload 无徽记内容；
- 全量 `.venv\Scripts\python.exe -m unittest discover -v` 通过；性质测试与回放投影无徽记泄漏；
- 完成后在 map.md Decisions-so-far 回报。

## Comments

## Answer

已实现（2026-08-30）：

- 引擎 `_start` 在 `GameStarted` 后追加一条 `ClueIconsShown`：`pairs` 按 seat 环序"每人 → 左邻"，payload 只有展示关系，无任何徽记值；无 schema/ruleset 版本变更，旧存档恢复天然兼容。
- 投影 `viewer` 块新增 `clueIcon`（本人）与 `seenNeighbourClue`（`{playerId, icon}`，右邻 = seat 环序上一位）；`players[]`、旁观者投影、回放步骤均无徽记字段；模块 docstring 同步更正。
- 前端：`types.ts` 补类型与 `displayClueIcon`；`Board.tsx` 自己座位身份区渲染"你的徽记：X · 已看到 某某 的：Y"；`GameScreen.tsx` 事件表补 `ClueIconsShown`，日志一行"全员已向左邻展示阵营徽记"；文案全中文，座位卡不出现左右。
- 测试：开局事件关系/无内容（结构化校验 pair 键与取值 ⊆ 玩家）、本人+右邻可见且全视图递归扫描仅此两处徽记字段、旁观者/回放（`viewer=None`）零徽记、性质 sweep 逐 viewer 校验右邻语义、rank 3 反转与审判官徽记必错不变量（20 组 seed 扫描）。golden replay fixtures 因新事件按预期漂移，已按流程重新生成。全量 `unittest discover` 110/110 通过，`npm run build` 通过。
- 文档：`server/PROTOCOL.md`（事件行、viewer 形状、隐私保证）、`docs/rule-branch-coverage.md`（Issue 21 分支表）、[domain-model-contract.md](../domain-model-contract.md)（PlayerView 段 + 事件清单）已更新。
- 双轴 code review（Standards/Spec）无违规项；两条加固建议（结构化 payload 断言、递归徽记字段扫描）已落地。
