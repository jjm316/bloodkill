# 规则耦合共识实施（2026-10-03）

规则共识访谈已完结（M1 元规则 + P1–P6 父裁决 + L4 叶子 + B9 + 21 条批量确认），共识权威记录在：

- **规则语料「产品方裁决（2026-10-03）」小节**：`.scratch/blood-oath-replica/rules-corpus-user-extract.md`（含改写后的规则行 `damage.reveal` / `skill.reveal-rank` / `window.single-timeout` / rank 2、4、5 行 / fleur cross 行）
- **ADR**：`docs/adr/0006`–`0011`（P1 亮牌权 / P2 被捕独赢 / P3 一律一次 / P4 开窗总则与封印 / P5 盾语义 / P6 窗口超时）
- **领域语言**：`CONTEXT.md`（新词「封印」「单人窗口超时」「捕获归因」；改「技能窗口」「终局分支」「线索 token」）
- **证据库**：`index.html`（30 耦合点卡片，含引擎行号与推演示例，基线 ruleset 0.4 @ ac31bdb）

## 实施索引（`issues/`）

| # | Issue | 对应裁决 |
| --- | --- | --- |
| 01 | 技能伤害亮牌权回归受害者自选 | P1 / ADR 0006 |
| 02 | 技能窗开窗总则重写 + 感应者封印（方案 A） | P4 / ADR 0009 |
| 03 | 审判者被捕获改判独赢 | P2 / ADR 0007 |
| 04 | 删 owner 盾检查，持盾狂战士可反伤 | P5 / ADR 0010 |
| 05 | 单人窗口超时兜底 | P6+L4 / ADR 0011 |
| 06 | 炼金 harm 选项过滤盾目标（projection 小修） | B1 小修 |
| 07 | ruleset bump 0.4→0.5 + coverage + golden + helpContent + 文档销案 | 全批收尾（依赖 01–05、26） |

## 范围外（勿在此实施）

- **wild 色选窗增加问号选项**（玫/兽/？三选）：独立工作单 `.scratch/blood-oath-replica/issues/26-wild-color-question-option.md`（其语料/CONTEXT 文档同步已随本批完成，剩引擎/投影/客户端代码）；本批 05 的"超时默认问号"依赖它落地，两边已互写衔接注记。
- P3（技能一律一次）**无引擎改动**——引擎现行为已符合，语料与 ADR 0008 已追认。

## 备注

- 引擎禁存墙钟：所有超时走 Room 持有 deadline、DeadlineScheduler 代发 timeout 命令（既有约束）。
- 全部自动默认必须确定序（marker-0 → marker-1 → rank），杜绝 set 迭代序不确定性（A2 教训）。
- 后端测试：`.venv` 的 `python -m unittest discover -v`（没装 pytest，别装）。
