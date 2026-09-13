import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Board } from "./Board";
import type { GameState, PlayerView } from "./types";

// 圆桌坐标的注入契约（ui-table-theme 移动端散架回归，2026-09-13）：
// 座位坐标必须以 CSS 变量（--seat-x/--seat-y）传递、由 ≥720px 圆桌分支的 CSS 消费；
// 绝不能直接写 left/top 内联样式——窄屏网格分支的 .seat 是 position:relative，
// left/top 百分比会变成"从网格单元格平移"，座位散架并被窗口边缘裁切。

function makePlayer(id: string, seat: number): PlayerView {
  return {
    playerId: id,
    seat,
    displayName: `玩家${seat}`,
    damage: 0,
    captured: false,
    revealed: { rank: undefined, markers: [null, null] },
    identityMarkers: [null, null],
    resources: {},
  };
}

function makeGame(count: number, viewerIndex = 0): GameState {
  const players = Array.from({ length: count }, (_, i) => makePlayer(`p${i}`, i));
  return {
    gameId: "g-test",
    revision: 1,
    status: "active",
    players,
    daggerHolderId: players[0].playerId,
    phase: { kind: "action", activePlayerId: players[0].playerId },
    pending: null,
    result: null,
    viewer: {
      playerId: players[viewerIndex].playerId,
      identity: { faction: "rose", rank: 3 },
      identityMarkers: ["rose"],
      resources: {},
      skillsUsed: [],
      inspections: {},
      cursesToDistribute: [],
      clueIcon: "rose",
      seenNeighbourClue: null,
    },
    legalActions: [],
  };
}

describe("Board 座位坐标注入", () => {
  it("座位不携带 left/top 内联样式，坐标只通过 --seat-x/--seat-y 变量传递", () => {
    const { container } = render(<Board game={makeGame(8)} />);
    const seats = container.querySelectorAll<HTMLElement>(".players .seat");
    expect(seats.length).toBe(8);
    for (const seat of seats) {
      expect(seat.style.left, "inline left 会在窄屏 relative 定位下平移网格卡片").toBe("");
      expect(seat.style.top).toBe("");
      expect(seat.style.getPropertyValue("--seat-x")).toMatch(/^[\d.]+%$/);
      expect(seat.style.getPropertyValue("--seat-y")).toMatch(/^[\d.]+%$/);
    }
  });

  it("自身座位（viewer）带 .self 类且其 --seat-y 为各座位中最大（圆桌 6 点位）", () => {
    const { container } = render(<Board game={makeGame(8, 3)} />);
    const seats = [...container.querySelectorAll<HTMLElement>(".players .seat")];
    const self = seats.find((s) => s.classList.contains("self"));
    expect(self).toBeTruthy();
    const yOf = (s: HTMLElement) => parseFloat(s.style.getPropertyValue("--seat-y"));
    expect(seats.every((s) => yOf(s) <= yOf(self!))).toBe(true);
  });
});
