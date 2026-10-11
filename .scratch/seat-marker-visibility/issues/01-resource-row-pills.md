# 01 资源行徽章化（金色药丸：图标＋单字标签）

Status: resolved

实现 `.scratch/seat-marker-visibility/spec.md` **Part A**。纯前端，不依赖 02/03，可先行。

要点（全量见 spec Part A）：

- `client/src/Board.tsx:45-57` `Resources` 折进药丸样式（渲染点 :308，保持仅 count>0 渲染）。
- 五类资源标签：笔 / 盾 / 剑 / 杖 / 扇；count > 1 才显示 `×N`。
- title 规则文案锚定语料（扇＝他人不能替持扇者干涉；杖＝身份标记全变问号）。
- 样式值、压缩档联动（styles.css:669-687 / :1285）见 spec。
- 原型处置：`client/prototype.html`＋`client/src/prototype/` 先提交到 throwaway 分支 `prototype/resource-row` 存档再删除。
- 验证：10 人 size-lg 档三枚同持截图复核不溢出；`npm test` 补资源行渲染断言；提交前 `python scripts/check.py`。

## Comments

- 2026-10-11（agent）：落地完成，提交 ac9b3be（集成分支 spec/seat-marker-visibility，ff 合并）。`Resources` 折成金色药丸（Board.tsx：短标签 笔/盾/剑/杖/扇、count>1 才 ×N、仅 count>0 渲染与全空 return null 保持）；样式值照抄原型方案 A 验证值（styles.css `.resources` 段重写）。两处已注明偏差：① xl 压缩档联动改 `.table-area.size-xl .resource-pill { font-size: 11px }`，对齐同档 `.slot` 既有值（spec 只给基础 12px；旧档 12px 规则在药丸自带 12px 后失效，保守延续，原型未覆盖 xl 档）；② 五句 title 钉进测试——扇/杖用语料原文逐字，笔/盾/剑按 helpContent 图例缩写。原型处置适配：spec 写的 `client/` 路径已过时，源文件实际在仓库根 `prototypes/`（从未被跟踪），已由协调者按意图存档至一次性分支 `prototype/resource-row`（6e3ddac），生产分支无需删除。前端单测 4 条（boardResources.test.tsx 新增），npm test 179/179、check.py 全绿。10 人 size-lg 生产截图未做（低成本复用路径不存在），DOM 断言覆盖逻辑，同值样式已经原型目视验证（prototypes/resource-row/A-*.png 含 10 人档），截图复核留给协调者验收阶段。
