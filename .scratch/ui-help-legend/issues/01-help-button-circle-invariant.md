# 01 — 页头"？"按钮在 ≤480px 视口塌成竖椭圆，问号脱离圆心

Status: resolved

## 病灶

窗口拖窄（或浏览器放大使 CSS 视口 ≤480px）时，页头"？"按钮不再是正圆、问号不在圆心。

根因（styles.css）：`@media (max-width: 480px)` 里 `.room-header button { width: auto }`
（特异性 0,1,1）压过 `.help-button { width: 36px }`（0,1,0），按钮宽度塌缩到"？"字宽
（≈16px+边框）而高度仍 36px → 竖椭圆。此外"圆 + 字"是 CSS 盒子与文字两个东西，
居中依赖浏览器对 button 的默认行为，不变量无处锚定。

用户口径：问号与黄色圆圈应该是"一张图"——随窗口伸缩永远正圆、问号恒在圆心。

## 拍板（grill 共识，2026-10-04；二轮修订见 Comments）

- 流式缩放 `clamp(28px, 5vw, 36px)`：≥720px 桌面档 36px 与旧观感一致，560–720px 线性缩放，手机 28px。
- SVG 一体图：`icons.tsx` 新增 `help` 图标，圆环 + 问号 + 点锁在同一 viewBox；
  描边用 viewBox 单位等比缩放（不用 non-scaling-stroke）。
  ~~问号用 `<text>` 沿用 `--font-display`~~ —— 一轮视觉验收推翻（全角"？"墨迹
  在各中文字体字身框内系统性偏左，text 方案跨机型无法保证墨迹居中），
  改为对称构造的几何路径，见 Comments。
- `.rules-q`（浮层头 26px 徽记）原拍板只做显式居中加固；核查发现它本就写了
  inline-flex 居中。一轮验收发现它与页头徽记同病（字体墨迹偏左），
  按 P1 意见改复用同一 help 徽记（svg 自带圆环，CSS border 移除）。
- 按钮保留 `var(--card)` 底色与既有 hover/focus，480px 媒体查询内以
  `.room-header .help-button`（0,2,0）正面钉回 28px 豁免 `width:auto`。

## 改动

- `client/src/icons.tsx`：`IconName` 加 `help`；徽记条目（环 + 问号路径 + 点，描边 viewBox 单位等比缩放）。
- `client/src/GameScreen.tsx`：按钮内容由文字"？"换 `<Icon name="help" />`，aria-label/title 不变。
- `client/src/HelpOverlay.tsx`：`.rules-q` 复用同一 help 徽记。
- `client/src/styles.css`：`.help-button` 宽高同 clamp + 去 border + svg 撑满；
  480px 档豁免；`.rules-q` 去 border、svg 撑满。
- `client/src/icons.test.tsx`：help 徽记"一张图"不变量 smoke 断言（结构级，几何由截图验收兜底）。

## Answer

实现 + 70/70 前端测试通过 + tsc 无错 + 两轮多视口截图/墨迹分析验收，
详见 Comments。验收截图存 `.scratch/ui-help-legend/shots/issue-01/`。

## Comments

### 2026-10-04 一轮视觉验收：FAIL（推翻 text 问号方案）

visual-verifier 六档视口（1024/768/640/480/360/320）取证：正圆不变量全过
（宽=高 diff 全 0，档位精确命中 clamp 预期）、SVG 单图结构、无双圈、无页头回归。
但**问号墨迹居中 FAIL**：全角"？"在衬线字体栈的字身框内墨迹系统性偏左——
canvas TextMetrics 探针实测 Noto Serif SC 的"？"墨迹在 40px 字身框内仅占 [0,19]，
墨迹中心偏左 0.2625em（36px 档预测 -4.21px vs 实测 -4.08px，定量闭环）；
探针另测 10 种中文字体全部偏左（KaiTi/SimHei -0.1625em）。`text-anchor: middle`
只能居中字身框，任何静态 x 补偿都只对栈首字体成立，跨机型无法保证不变量。
旧版 CSS 文字按钮同病（非本次改动引入），`.rules-q` 同样偏左 -3.6px。

处置：问号改对称构造的几何路径（钩形 path + 圆点，墨迹水平范围 8.9..15.1
关于 cx=12 对称），`.rules-q` 复用同一 help 徽记（P1）。验收工具留存：
`.scratch/ui-help-legend/{drive.cjs,ink_analysis.py,font_probe.cjs}`。

### 2026-10-04 二轮视觉验收：PASS（path 化后墨迹偏移归零）

六档视口两处徽记墨迹 bbox 中心偏移全部 ≤0.08px（水平 dx 恰为 0.00，
左右边距对称差 0.00），对比一轮的 -3.0~-3.9px；结构（texts=0、无裸文字、
无 CSS border 双圈）、观感（钩/点/环配比、无截断不触环）、一轮已过项
（正圆档位、无溢出、#f0c060）全部无回退。P2 意见两条：
圆点空心（描边 donut）与 320 档"离开"换行。

### 2026-10-04 三轮定点确认：PASS（圆点实心化）

采纳 P2 圆点意见：`fill="currentColor"` + r 1.05→0.9（保留同色描边，外径
1.65 单位），实心金观感替代描边空心环。1024/320 定点复验：实心无中空、
比例协调，墨迹居中指标仍达标（dx=0.00，dy ≤0.17px），无回退。
320 档"离开"换行为既有行为，不在本案范围。
产物：`shots/issue-01/` 下 v1/v2/v3 三层截图与 results*.json 全留档。

code-review 修整（提交前）：`.help-button`/`.rules-q` 的 svg 撑满规则合并为
共享选择器；徽记边长提为 `:root` 的 `--help-badge-size`（宽高/媒体查询同源引用，
正圆不变量由结构保证而非注释约束），min-height 改 0 防未来反超。

