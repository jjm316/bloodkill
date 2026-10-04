import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Icon, type IconName } from "./icons";

// smoke 测试（spec Testing Decisions）：线性图标只断言输出 svg 且带 aria-hidden，
// 不逐个断言路径数据——造型以 mockups/icon-strip.html 参考稿为准。
// help 徽记例外：它的几何即需求本身（居中/同轴不变量），故额外断言结构，见下方 describe。

const NAMES: IconName[] = ["dagger", "shield", "sword", "staff", "fan", "lock", "quill", "help"];

describe("内联 SVG 图标", () => {
  it("8 个图标都渲染为 24 视窗的线性 svg，且对读屏隐藏", () => {
    for (const name of NAMES) {
      const { container } = render(<Icon name={name} />);
      const svg = container.querySelector("svg");
      expect(svg, name).not.toBeNull();
      expect(svg?.getAttribute("aria-hidden"), name).toBe("true");
      expect(svg?.getAttribute("viewBox"), name).toBe("0 0 24 24");
      expect(svg?.getAttribute("stroke"), name).toBe("currentColor");
      expect(svg?.childElementCount, name).toBeGreaterThan(0);
    }
  });
});

// help 徽记（页头"？"按钮）的"一张图"不变量（.scratch/ui-help-legend/issues/01）：
// 圆环、问号、点锁在同一个 viewBox 坐标系里等比缩放，问号恒在圆心。
// 问号是几何路径而非 <text>：全角"？"墨迹在各中文字体字身框内系统性偏左，
// text 方案跨机型无法保证居中（见 icons.tsx 条目注释）。
// jsdom 无布局，只断言结构——几何正确性由多视口截图 + 墨迹分析验收兜底。
describe("help 徽记图标", () => {
  it("圆环、问号路径、点共存于同一个 svg，且不走字体渲染（一张图）", () => {
    const { container } = render(<Icon name="help" />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg?.querySelectorAll("circle").length).toBe(2); // 外环 + 问号点
    expect(svg?.querySelector("path")).not.toBeNull(); // 问号钩形
    expect(svg?.querySelector("text")).toBeNull();
  });

  it("问号按几何构造居中：环与点同轴 cx=12", () => {
    const { container } = render(<Icon name="help" />);
    const circles = container.querySelectorAll("circle");
    expect(circles[0]).toHaveAttribute("cx", "12");
    expect(circles[1]).toHaveAttribute("cx", "12");
  });
});
