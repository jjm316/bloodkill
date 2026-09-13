import { describe, expect, it } from "vitest";
import { seatPosition, seatTier, tableShape } from "./tableSeats";

// 圆桌几何契约（.scratch/ui-table-theme/spec.md Testing Decisions）：
// 等分角度、viewer 落正下方、6/12 人坐标不重叠；另加卡片级不重叠回归
// （用户故事 15），把 styles.css 圆桌段的座位宽度表镜像进测试。

const ALL_TOTALS = [6, 7, 8, 9, 10, 11, 12];

// 从坐标反解参数角（度）：atan2 前先把 y 归一化到椭圆半径，恢复的就是参数角本身
function paramAngle(x: number, y: number, total: number): number {
  const { rx, ry } = tableShape(total);
  return (Math.atan2((y - 50) / ry, (x - 50) / rx) * 180) / Math.PI;
}

const normalize = (deg: number) => ((deg % 360) + 360) % 360;

describe("seatPosition 圆桌坐标", () => {
  it("N 人沿椭圆参数角等分：相邻角差恰为 360/N", () => {
    for (const total of ALL_TOTALS) {
      const step = 360 / total;
      for (let index = 0; index < total; index++) {
        const p = seatPosition(index, total, 0);
        const angle = normalize(paramAngle(p.x, p.y, total));
        // viewerIndex=0 时 0 号座位在 90°，数组后继参数角递减
        const expected = normalize(90 - index * step);
        expect(angle, `total=${total} index=${index}`).toBeCloseTo(expected, 6);
      }
    }
  });

  it("viewer 座位无论下标几何都落在桌面正下方（x=50%, y=50%+ry）", () => {
    for (const total of ALL_TOTALS) {
      const { ry } = tableShape(total);
      for (let viewer = 0; viewer < total; viewer++) {
        const p = seatPosition(viewer, total, viewer);
        expect(p.x, `total=${total} viewer=${viewer}`).toBeCloseTo(50, 6);
        expect(p.y, `total=${total} viewer=${viewer}`).toBeCloseTo(50 + ry, 6);
      }
    }
  });

  it("数组前驱（左邻）在 viewer 左手侧、后继在右手侧", () => {
    const total = 8;
    const viewer = 3;
    const prev = seatPosition(viewer - 1, total, viewer);
    const next = seatPosition(viewer + 1, total, viewer);
    expect(prev.x).toBeLessThan(50);
    expect(prev.y).toBeGreaterThan(50);
    expect(next.x).toBeGreaterThan(50);
    expect(next.y).toBeGreaterThan(50);
  });

  it("6 人与 12 人两档：所有座位坐标两两不重叠", () => {
    for (const total of [6, 12]) {
      const points = Array.from({ length: total }, (_, i) => seatPosition(i, total, 0));
      for (let i = 0; i < points.length; i++) {
        for (let j = i + 1; j < points.length; j++) {
          const dist = Math.hypot(points[i].x - points[j].x, points[i].y - points[j].y);
          expect(dist, `total=${total} ${i}~${j}`).toBeGreaterThan(5);
        }
      }
    }
  });
});

// 卡片级不重叠（用户故事 15）：座位卡片中心即 seatPosition 点，宽高取
// styles.css 圆桌段的分档宽度与实际内容高度预算。改 CSS 座位尺寸时须同步此表。
const SEAT_WIDTHS: Record<"wide" | "mid", Record<ReturnType<typeof seatTier>, number>> = {
  // ≥1020px 视口：≤8 人（base）/ 9–10 人（lg）/ 11–12 人（xl）
  wide: { base: 208, lg: 190, xl: 170 },
  // 720–1019px 视口
  mid: { base: 168, lg: 144, xl: 120 },
};
// 普通座位高度预算：内边距16 + 名字21 + 槽位24 + 资源行16 + 间距；xl 档
// 座位用紧凑样式（槽位 20px、资源行 14px、内边距 12px），自身座位另加徽记行 20px。
const CARD_HEIGHTS: Record<ReturnType<typeof seatTier>, number> = { base: 88, lg: 88, xl: 74 };
const OWN_EXTRA = 20;
const CONTAINERS = [
  { label: "窄桌面 720px", width: 696, widths: SEAT_WIDTHS.mid },
  { label: "宽桌面 1440px", width: 1196, widths: SEAT_WIDTHS.wide },
];

describe("圆桌卡片不重叠回归", () => {
  for (const { label, width, widths } of CONTAINERS) {
    it(`${label}（容器 ${width}px）下 6–12 人卡片与桌心横幅互不重叠`, () => {
      for (const total of ALL_TOTALS) {
        const tier = seatTier(total);
        const seatW = widths[tier];
        const seatH = CARD_HEIGHTS[tier];
        const { height } = tableShape(total);
        // 座位卡片：中心点来自 seatPosition（viewer=任意，旋转不改变相对间距），尺寸按档
        const centers = Array.from({ length: total }, (_, i) => seatPosition(i, total, 0));
        const rects = centers.map((p, i) => ({
          x1: ((p.x / 100) * width) - seatW / 2,
          x2: ((p.x / 100) * width) + seatW / 2,
          y1: ((p.y / 100) * height) - (i === 0 ? seatH + OWN_EXTRA : seatH) / 2,
          y2: ((p.y / 100) * height) + (i === 0 ? seatH + OWN_EXTRA : seatH) / 2,
        }));
        const overlaps = (a: { x1: number; x2: number; y1: number; y2: number }, b: { x1: number; x2: number; y1: number; y2: number }) =>
          a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2;
        for (let i = 0; i < rects.length; i++) {
          for (let j = i + 1; j < rects.length; j++) {
            expect(overlaps(rects[i], rects[j]), `${label} total=${total} 座位 ${i}/${j}`).toBe(false);
          }
        }
        // 卡片不越出容器（左右留 4px）
        for (const r of rects) {
          expect(r.x1, `${label} total=${total} 左边界`).toBeGreaterThanOrEqual(0);
          expect(r.x2, `${label} total=${total} 右边界`).toBeLessThanOrEqual(width);
        }
        // 桌心横幅（居中，max-width min(430px, 74.6vw-190px)，高按 3 行文本 110px 预算）
        const bannerW = Math.min(430, 0.746 * width - 190);
        const banner = {
          x1: width / 2 - bannerW / 2,
          x2: width / 2 + bannerW / 2,
          y1: height / 2 - 55,
          y2: height / 2 + 55,
        };
        for (const r of rects) {
          expect(overlaps(banner, r), `${label} total=${total} 横幅与座位 ${rects.indexOf(r)}`).toBe(false);
        }
      }
    });
  }
});
