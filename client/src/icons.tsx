import type { ReactNode } from "react";

// 内联 SVG 线性图标集（.scratch/ui-table-theme/spec.md）：全项目 7 处 emoji
// （5 资源 + 匕首 + 房间锁）的替代，统一 stroke 风格、currentColor 着色，
// 不引第三方图标库、无位图。造型源：mockups/icon-strip.html（2026-09-13 拍板）。
// 玫瑰/野兽/未知标记维持"字 + 色块"现状，不走此组件（兼顾色弱辨识）。

export type IconName = "dagger" | "shield" | "sword" | "staff" | "fan" | "lock" | "quill" | "help";

const ICON_SHAPES: Record<IconName, ReactNode> = {
  dagger: (
    <>
      <path d="M12 2 L14.5 8 L12 15 L9.5 8 Z" />
      <line x1="8.5" y1="15.5" x2="15.5" y2="15.5" />
      <line x1="12" y1="15.5" x2="12" y2="19" />
      <circle cx="12" cy="20.6" r="1.1" />
    </>
  ),
  shield: <path d="M12 3 L19 6 V11 C19 16 16 19.5 12 21 C8 19.5 5 16 5 11 V6 Z" />,
  sword: (
    <>
      <polyline points="14.5 17.5 3 6 3 3 6 3 17.5 14.5" />
      <line x1="13" y1="19" x2="19" y2="13" />
      <line x1="16" y1="16" x2="20" y2="20" />
      <line x1="19" y1="21" x2="21" y2="19" />
    </>
  ),
  staff: (
    <>
      <line x1="6" y1="21" x2="15.5" y2="9.5" />
      <circle cx="17.5" cy="6.5" r="2.6" />
    </>
  ),
  fan: (
    <>
      <path d="M4.6 10.2 A 8.6 8.6 0 0 1 19.4 10.2" />
      <line x1="12" y1="18" x2="12" y2="4.6" />
      <line x1="12" y1="18" x2="5.6" y2="7.4" />
      <line x1="12" y1="18" x2="18.4" y2="7.4" />
      <path d="M8.6 13.6 A 5 5 0 0 1 15.4 13.6" />
    </>
  ),
  lock: (
    <>
      <rect x="5" y="11" width="14" height="9" rx="2" />
      <path d="M8 11 V7 a4 4 0 0 1 8 0 V11" />
      <line x1="12" y1="15" x2="12" y2="16.5" />
    </>
  ),
  quill: (
    <>
      <path d="M20 4 C13 4.5 7.5 9 5.8 15.5 L4 20 L8.5 18.2 C15 16.5 19.5 11 20 4 Z" />
      <path d="M5.8 15.5 C9.5 12.5 13.5 9.5 17.5 6.5" />
    </>
  ),
  // help 徽记：页头"？"按钮的"一张图"本体（.scratch/ui-help-legend/issues/01）——
  // 圆环、问号、点锁在同一 viewBox 里等比缩放，任何尺寸下都是正圆 + 问号居中。
  // 问号不走 <text>：实测衬线栈各中文字体的全角"？"墨迹在字身框内系统性偏左
  // （Noto Serif SC 达 0.26em，探针 10 种字体无一居中），text-anchor 只能居中字身框，
  // 跨机型无法保证墨迹居中——改为对称构造的几何路径（墨迹水平范围 8.9..15.1 关于 cx=12 对称）。
  // 描边均用 viewBox 单位随徽记等比伸缩（不用 non-scaling-stroke）；问号 1.5、环 1：
  // 36px 渲染时 ≈ 2.25px/1.5px，对应旧版字形笔画与 1.5px 边框的粗细配比。
  help: (
    <>
      <circle cx="12" cy="12" r="11" strokeWidth={1} />
      <path
        d="M 8.9 8.9 C 8.9 7.0 10.2 5.7 12 5.7 C 13.8 5.7 15.1 6.9 15.1 8.6 C 15.1 10.0 14.2 10.7 13.2 11.4 C 12.4 11.9 12 12.5 12 13.6 L 12 14.2"
        strokeWidth={1.5}
      />
      <circle cx="12" cy="17.2" r="0.9" strokeWidth={1.5} fill="currentColor" />
    </>
  ),
};

// 纯装饰图标：语义由外层 title/aria-label 承载，svg 自身 aria-hidden；
// 尺寸默认 1em，实际渲染由上下文 CSS（.dagger-icon / .resources / .room-lock）给定。
export function Icon({ name }: { name: IconName }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {ICON_SHAPES[name]}
    </svg>
  );
}
