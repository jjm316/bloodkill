# 01 资源行徽章化（金色药丸：图标＋单字标签）

Status: ready-for-agent

实现 `.scratch/seat-marker-visibility/spec.md` **Part A**。纯前端，不依赖 02/03，可先行。

要点（全量见 spec Part A）：

- `client/src/Board.tsx:45-57` `Resources` 折进药丸样式（渲染点 :308，保持仅 count>0 渲染）。
- 五类资源标签：笔 / 盾 / 剑 / 杖 / 扇；count > 1 才显示 `×N`。
- title 规则文案锚定语料（扇＝他人不能替持扇者干涉；杖＝身份标记全变问号）。
- 样式值、压缩档联动（styles.css:669-687 / :1285）见 spec。
- 原型处置：`client/prototype.html`＋`client/src/prototype/` 先提交到 throwaway 分支 `prototype/resource-row` 存档再删除。
- 验证：10 人 size-lg 档三枚同持截图复核不溢出；`npm test` 补资源行渲染断言；提交前 `python scripts/check.py`。
