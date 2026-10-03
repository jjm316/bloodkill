# wild 万能标记色选窗增加「问号」选项

Type: task
Status: ready-for-agent

## 产品裁决

用户侧聊裁决（2026-10-03，规则共识访谈期间）：审判者 wild 标记的色选窗应提供**三个**选项——玫 / 兽 / **？**。现状只有玫、兽两选项，缺问号。原话：「wild的色选窗我认为wild的色选窗应该是还有一个问号可以供选择。……如果没有的话需要加上。」

语义：wild 亮为「？」与普通玩家的问号标记完全同价——不暴露任何阵营倾向。给审判者一个「完全不表态」的亮法（配合他本来就名不副实的开局徽记，三档误导：偏玫 / 偏兽 / 不偏）。

## 现状证据（三层都只有两色，已核实）

1. **引擎** `blood_bound/engine.py:760-763`（`_reveal_token`）：wild 标记要求 `color ∈ {"rose", "beast"}`，其余值 raise `reveal.color-required`——`unknown` 被拒。
2. **投影** `blood_bound/projection.py:102-105`：wild token 的合法动作展开为恰好两条（`color: "rose"` / `color: "beast"`）。
3. **客户端** `client/src/Board.tsx:69` 的 `COLOR_LABELS = { rose: "玫瑰", beast: "野兽" }`——问号连标签都没有；选色浮层（Board.tsx:204-219）按服务端选项渲染，无法出现第三钮。

前置查证结论（无需重查）：

- `unknown` 本就是标记值域的合法值（rank 2/3/4 双问号、7/8/9 一问号、mage 改写产生 `unknown`，见 `_markers_for` engine.py:114-124 与 engine.py:574），`revealed_values` 写入 `"unknown"` 无 schema 变化。
- `revealed_values` 的全部消费方是展示与持久化（projection.py:180-184、persistence.py:282、退牌移除 engine.py:602），**没有任何胜负/资格逻辑按标记值分支**——加问号无规则副作用。
- 桌面渲染已支持：`MARKER_DOTS.unknown = { label: "？", tone: "unknown" }`（Board.tsx:62-66）。

## 改动面

1. **引擎**：`engine.py:760` 的颜色校验集合扩为 `{"rose", "beast", "unknown"}`；`value = color` 路径不变（`unknown` 直接落 `revealed_values`）。
2. **投影**：`projection.py:102-105` wild token 展开为三条 `choose-reveal` 动作（玫/兽/？）。
3. **客户端**：`COLOR_LABELS` 增加 `unknown: "问号"`（文案与 helpContent 对齐，勿写「未知」误导为没选）；选色浮层按钮的 `tone` 用现有 `unknown` 灰样式。
4. **文档同步**（仓库红线：修复须同步文档/测试/golden）：
   - `CONTEXT.md`「线索 token」词条：审判者万能标记「亮出时由本人自选玫或兽色」→「自选玫、兽或问号」；
   - 语料 `rules-corpus-user-extract.md`：`damage.reveal` 待验收重点同步 + 「产品方裁决（2026-10-03）」小节记一笔（随主线程共识落盘一起写，勿单独重复记账）；
   - `helpContent.ts` 审判者条目补「问号」。
5. **测试与版本**：分支测试（审判者 wild 亮牌选问号 → ClueRevealed value=unknown、投影三选项）；`ruleset_version` bump；`docs/rule-branch-coverage.md` 加行；golden 重生成（`python -m tests.test_golden_replays`）；全量 `.venv\Scripts\python.exe -m unittest discover -v`。

## 协调事项

- 主线程规则共识批次（P1=a 技能伤害自选亮牌、P4 开窗总则、L4 窗口超时）会改动同一段亮牌/开窗管线（engine.py:734-805 一带）。本票宜**与该实施批次同批或其后**落地，避免同文件两轮冲突；语义上互不依赖（本票不改变「wild 必开色选窗」这一事实，只是窗里多一个选项）。
- 窗口超时（L4）落地后，wild 色选窗到期默认色**按主线程最终裁决为问号**（用户 2026-10-03 主线程原话：「也应该是默认是问号来进行选择」；本票早先"推荐为玫"已被推翻）——本票不改默认行为，超时默认由 `.scratch/rule-coupling-review/issues/05-single-window-timeouts.md` 实现。

## 完成条件

- 审判者亮 wild 标记时，浮层出现玫 / 兽 / ？三个按钮，选问号后桌面显示「？」且事件 `ClueRevealed.value = "unknown"`；
- 普通玩家标记（非 wild）行为不变；mage 改写、退牌等既有路径回归通过；
- 文档四处同步 + ruleset bump + coverage 加行 + golden 双向验证通过。

## Comments

- 2026-10-03：规则共识访谈侧聊中用户提出并拍板开票。现状核查由主线程完成（引擎/投影/客户端三层行号见上），实现留待后续批次。
- 2026-10-03（主线程共识落盘）：第 4 节文档同步中的语料与 CONTEXT.md 两项已随规则共识批次完成——语料「产品方裁决（2026-10-03）」小节已记「wild 身份标记含问号」条目并改写 `damage.reveal` 待验收与 fleur cross 行；CONTEXT.md「线索 token」词条已改"自选玫、兽或问号"。剩余：引擎/投影/客户端三处代码、helpContent 审判者条目、测试与版本（随 ruleset 0.4→0.5 批次，见 `.scratch/rule-coupling-review/spec.md`）。
