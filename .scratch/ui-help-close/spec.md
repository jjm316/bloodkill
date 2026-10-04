# 规则浮层手机端关闭方式：页头 ✕ 按钮

Type: task
Status: resolved（2026-10-04 实现：client vitest 71/71、tsc/build 干净、无头实测两视口 ✕ 点击即关、visual-verifier 9/9 PASS、双轴 code-review 无返工项）
来源: 用户反馈"手机端不方便关闭打开的说明"（2026-10-04 grill 拍板，Q1–Q4 全 A）

## Problem Statement

规则与图例浮层（`RulesOverlay`）只有两条关闭路径：Escape 键和点击遮罩。手机上两条都失效——没有键盘；≤480px 档 overlay 内边距只有 8px、浮层满宽近满屏，可点的遮罩只剩一圈 8px 细边，手指按不中。页头提示文案「Esc / 点击遮罩关闭」在触屏上恰好指向这两条死路，用户照提示找不到关闭方式。

## Solution（拍板结论）

页头右端加显式 ✕ 关闭按钮（全端可见，不只手机）；`icons.tsx` 新增 `close` 一张图 SVG（与现有图标同笔画语言、currentColor）；整行删除「Esc / 点击遮罩关闭」提示及 `.rules-esc` 样式；Escape 与点遮罩两条旧路径原样保留（代码、测试、8px 留白均不动）；范围仅 RulesOverlay——ConfirmDialog 有按钮组、大厅折叠块可再点收起、干涉投票/单窗层是必须表态的阻挡层，一律不加 ✕。

## Acceptance Criteria

1. 打开规则浮层，页头右端有 ✕ 关闭按钮，点击即关，`aria-label="关闭"`；
2. 触控目标约 36px（手机可按中）；
3. 「Esc / 点击遮罩关闭」提示不再出现；
4. Escape 关闭、点遮罩关闭两条既有路径行为不变，既有测试不回归；
5. 手机 375px 档无头截图实测：✕ 可见、不与标题重叠、页面头部其它元素不动；
6. 纯前端改动，零协议、零服务端。

## Implementation Decisions

- 图标走 `icons.tsx` 单源（延续"一张图"惯例），不用字符 ✕——字形跨机型不可靠（参见 ? 徽记 text 方案被墨迹实测推翻的先例）。
- 关闭按钮视觉上沿用页头既有语言：muted 色起步，hover/active 提亮；尺寸交给固定宽高，`min-height: 0` 覆盖全局 button 的 40px（同 `.help-button` 坑位）。
- 无 ADR、无 GLOSSARY 变更：纯 UI 供予层改动，可逆、无术语、无取舍。
