import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Board } from "./Board";
import type { GameState, PlayerView } from "./types";

// 检视事实角标（ADR 0013）：小丑技能产出 viewer.inspections（两名目标的
// 阵营+等级，仅本人可见，规则共识 B11），渲染在目标座位卡备忘角标同位区。
// 只读 span：与备忘标记（私有猜测）并存且互不写入。

function makePlayer(id: string, seat: number): PlayerView {
  return {
    playerId: id,
    seat,
    displayName: `玩家${seat}`,
    damage: 0,
    captured: false,
    holdsCurseCard: false,
    revealed: { rank: undefined, markers: [null, null] },
    identityMarkers: [null, null],
    resources: {},
  };
}

function makeGame(
  inspections: Record<string, { faction: string | null; rank: number | string | null }>,
): GameState {
  return {
    gameId: "g-test",
    revision: 1,
    status: "active",
    players: [makePlayer("p0", 0), makePlayer("p1", 1), makePlayer("p2", 2)],
    daggerHolderId: "p0",
    phase: { kind: "action", activePlayerId: "p0" },
    pending: null,
    result: null,
    viewer: {
      playerId: "p0",
      identity: { faction: "rose", rank: 3 },
      identityMarkers: ["rose"],
      resources: {},
      skillsUsed: [],
      inspections,
      cursesToDistribute: [],
      clueIcon: "rose",
      seenNeighbourClue: null,
    },
    legalActions: [],
  };
}

describe("检视事实角标", () => {
  it("只在被检视目标的座位卡渲染，悬浮文字为已核实的阵营与等级", () => {
    const { container } = render(
      <Board game={makeGame({ p1: { faction: "rose", rank: 5 } })} />,
    );
    const badges = container.querySelectorAll<HTMLElement>(".seat > .fact-badge");
    expect(badges).toHaveLength(1);
    expect(badges[0].closest(".seat")?.getAttribute("aria-label")).toContain("玩家1");
    expect(badges[0].className).toBe("fact-badge rose");
    expect(badges[0].textContent).toBe("5");
    expect(badges[0]).toHaveAttribute("title", "已检视：玫瑰家族·等级5（仅你可见）");
    expect(badges[0]).toHaveAttribute("aria-label", "已检视：玫瑰家族·等级5（仅你可见）");
  });

  it("自己座位永不渲染（引擎禁止自选为检视目标）", () => {
    const { container } = render(
      <Board game={makeGame({ p0: { faction: "rose", rank: 3 }, p1: { faction: "beast", rank: 8 } })} />,
    );
    expect(container.querySelector(".seat.self > .fact-badge")).toBeNull();
    expect(container.querySelectorAll(".seat:not(.self) > .fact-badge")).toHaveLength(1);
  });

  it("审判者目标：紫底 order 色、字面「审」、文案只报审判者身份", () => {
    const { container } = render(
      <Board game={makeGame({ p2: { faction: "secret-order", rank: "fleur-cross" } })} />,
    );
    const badge = container.querySelector<HTMLElement>(".seat > .fact-badge");
    expect(badge).not.toBeNull();
    expect(badge!.className).toBe("fact-badge order");
    expect(badge!.textContent).toBe("审");
    expect(badge).toHaveAttribute("title", "已检视：审判者（仅你可见）");
  });

  it("无 viewer（回放/旁观）不渲染事实角标", () => {
    const game = makeGame({});
    game.viewer = null;
    const { container } = render(<Board game={game} />);
    expect(container.querySelectorAll(".fact-badge")).toHaveLength(0);
  });
});
