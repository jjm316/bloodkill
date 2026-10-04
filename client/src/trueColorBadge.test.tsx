import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Board } from "./Board";
import type { GameState, PlayerView } from "./types";
import { displayFaction } from "./types";

// 真实阵营色徽（spec 2026-10-04 拍板）：自己座位卡右上角的纯色圆点，
// 读 viewer.identity.faction（玫红=玫瑰、兽蓝=野兽、灰=审判者"不属于任何家族"）。
// 身份只下发给本人（PROTOCOL.md 隐私保证），色徽因此只可能出现在自己座位上，
// 且允许与徽记线索矛盾（小丑/审判者的徽记会骗人）。

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

function makeGame(faction: string | null): GameState {
  const players = [makePlayer("p0", 0), makePlayer("p1", 1), makePlayer("p2", 2)];
  return {
    gameId: "g-test",
    revision: 1,
    status: "active",
    players,
    daggerHolderId: "p0",
    phase: { kind: "action", activePlayerId: "p0" },
    pending: null,
    result: null,
    viewer:
      faction === null
        ? null
        : {
            playerId: "p0",
            identity: { faction, rank: 3 },
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

describe("真实阵营色徽", () => {
  it.each([
    ["rose", "rose"],
    ["beast", "beast"],
    ["secret-order", "order"],
  ])("faction %s → 自己座位卡渲染 .true-color-badge %s，悬浮文字为真实阵营", (faction, tone) => {
    const { container } = render(<Board game={makeGame(faction)} />);
    const badge = container.querySelector<HTMLElement>(".seat.self > .true-color-badge");
    expect(badge, "色徽渲染在自己（.seat.self）卡上").not.toBeNull();
    expect(badge!.className).toBe(`true-color-badge ${tone}`);
    expect(badge).toHaveAttribute("aria-label", `你的真实阵营：${displayFaction(faction)}`);
    expect(badge).toHaveAttribute("title", `你的真实阵营：${displayFaction(faction)}`);
  });

  it("别人座位永不渲染色徽（identity 只下发给本人）", () => {
    const { container } = render(<Board game={makeGame("rose")} />);
    expect(container.querySelectorAll(".seat:not(.self) .true-color-badge")).toHaveLength(0);
    expect(container.querySelectorAll(".true-color-badge")).toHaveLength(1);
  });

  it("旁观/未发牌（viewer 为 null）不渲染色徽", () => {
    const { container } = render(<Board game={makeGame(null)} />);
    expect(container.querySelectorAll(".true-color-badge")).toHaveLength(0);
  });
});
