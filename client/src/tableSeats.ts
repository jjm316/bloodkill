// 圆桌座位几何（.scratch/ui-table-theme/spec.md）：纯函数、与组件分离，
// 组织方式仿事件类别映射表（eventLog.ts）——布局观感不可单测，可测的是坐标数学。
//
// 方位约定（视觉基准 mockups/after-board-desktop.html，2026-09-13 grill 拍板）：
// 座位沿一张椭圆参数角等分排布，viewer 自己的座位旋转到正下方（6 点位）；
// 参数角沿数组顺序递减，因此数组后继在 viewer 右手侧、数组前驱（引擎
// seenNeighbourClue 的展示者，即 UI 里的"左邻"）落在 viewer 左手边。
// 屏幕坐标 y 向下：参数角 90° = 桌面正下方。

export interface SeatPoint {
  /** 相对桌面容器的水平百分比 */
  x: number;
  /** 相对桌面容器的垂直百分比 */
  y: number;
}

export interface TableShape {
  /** 椭圆水平半径（容器宽度的百分比） */
  rx: number;
  /** 椭圆垂直半径（容器高度的百分比） */
  ry: number;
  /** 桌面容器高度（px），配合 CSS 座位宽度分档保证 6–12 人卡片不重叠 */
  height: number;
}

export type SeatTier = "base" | "lg" | "xl";

// 人数分档的单一出处：Board 的 CSS 类、tableShape 的高度、测试的宽度预算都按档取值
export function seatTier(totalSeats: number): SeatTier {
  if (totalSeats >= 11) return "xl";
  if (totalSeats >= 9) return "lg";
  return "base";
}

// 半径/高度分档推导（约束：相邻卡片在最小支持视口 720px 也不重叠）：
// - 横向贴合：(0.5+rx)·容器宽 + 座位宽/2 ≤ 容器宽
// - 相邻弦长：45° 弧段（弦最短处）dx/dy 至少一轴净距 ≥ 座位宽/高
// - 桌心横幅：110px 高的横幅不碰 k=±1 座位（6 人时其参数角 30°/150° 偏高，需更高容器）
// 座位宽度与 11–12 人紧凑卡片尺寸由 styles.css 圆桌段按同一分档给出。
export function tableShape(totalSeats: number): TableShape {
  const n = Math.max(2, totalSeats);
  switch (seatTier(n)) {
    case "xl":
      return { rx: 40.5, ry: 32.3, height: 690 };
    case "lg":
      return { rx: 39.0, ry: 32.3, height: 680 };
    default:
      return n <= 6 ? { rx: 37.3, ry: 32.3, height: 650 } : { rx: 37.3, ry: 32.3, height: 620 };
  }
}

// 座位序号为 players 数组下标；viewerIndex 为 viewer 在数组中的下标（回放/旁观
// 无 viewer 时传 0，即 0 号座位在正下方）。坐标为容器百分比，供绝对定位 left/top 使用。
export function seatPosition(index: number, totalSeats: number, viewerIndex = 0): SeatPoint {
  const { rx, ry } = tableShape(totalSeats);
  const step = 360 / Math.max(1, totalSeats);
  const angle = 90 - (index - viewerIndex) * step;
  const rad = (angle * Math.PI) / 180;
  return { x: 50 + rx * Math.cos(rad), y: 50 + ry * Math.sin(rad) };
}
