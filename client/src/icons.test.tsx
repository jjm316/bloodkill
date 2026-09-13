import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Icon, type IconName } from "./icons";

// smoke 测试（spec Testing Decisions）：只断言图标输出 svg 且带 aria-hidden，
// 不逐个断言路径数据——造型以 mockups/icon-strip.html 参考稿为准。

const NAMES: IconName[] = ["dagger", "shield", "sword", "staff", "fan", "lock", "quill"];

describe("内联 SVG 图标", () => {
  it("7 个图标都渲染为 24 视窗的线性 svg，且对读屏隐藏", () => {
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
