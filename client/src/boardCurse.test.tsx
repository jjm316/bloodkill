import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Board } from "./Board";
import type { GameState, PlayerView, ViewerView } from "./types";

// 诅咒药丸与终局翻牌（spec seat-marker-visibility Part B，ADR 0014）：
// 谁持卡是公开对局事实（players[].holdsCurseCard，全员含旁观者可见），
// 真/假之分仅审判者 viewer 私有，终局经 result.curseAssignments 全员翻开。
// 座位卡上以紫色「咒」药丸表达，标签按 观看者/阶段 三分支解析。

function makePlayer(id: string, seat: number, extras: Partial<PlayerView> = {}): PlayerView {
  return {
    playerId: id,
    seat,
    displayName: `玩家${seat}`,
    damage: 0,
    captured: false,
    revealed: { rank: undefined, markers: [null, null] },
    identityMarkers: [null, null],
    resources: {},
    holdsCurseCard: false,
    ...extras,
  };
}

function makeGame(players: PlayerView[], viewer: ViewerView | null, result: GameState["result"] = null): GameState {
  return {
    gameId: "g-test",
    revision: 1,
    status: "active",
    players,
    daggerHolderId: players[0].playerId,
    phase: { kind: "action", activePlayerId: players[0].playerId },
    pending: null,
    result,
    viewer,
    legalActions: [],
  };
}

// 家族玩家视角（无 curseAssignments 字段——投影只给审判者下发该键）
function familyViewer(playerId: string): ViewerView {
  return {
    playerId,
    identity: { faction: "rose", rank: 3 },
    identityMarkers: ["rose"],
    resources: {},
    skillsUsed: [],
    inspections: {},
    cursesToDistribute: [],
    clueIcon: "rose",
    seenNeighbourClue: null,
  };
}

const CURSE_TITLE = "暗置诅咒卡：真/假仅审判者可知；终局全员翻开";

// 投影形状（tests/test_projection.py 的 wire 输出）：viewer.curseAssignments 仅
// 审判者视角存在（{"true-curse-1": "p1", "false-curse-1": "p2"}），直接构造该
// 状态断言渲染——重连恢复是投影驱动的，不依赖事件重放。
function inquisitorViewer(playerId: string, assignments: Record<string, string>): ViewerView {
  return {
    playerId,
    identity: { faction: "secret-order", rank: "fleur-cross" },
    identityMarkers: ["wild", "wild"],
    resources: {},
    skillsUsed: [],
    inspections: {},
    cursesToDistribute: [],
    curseAssignments: assignments,
    clueIcon: "beast",
    seenNeighbourClue: null,
  };
}

function pillOf(container: HTMLElement, displayName: string): HTMLElement | null {
  const seat = [...container.querySelectorAll<HTMLElement>(".seat")].find((el) => el.textContent?.includes(displayName));
  return seat?.querySelector<HTMLElement>(".curse-pill") ?? null;
}

describe("座位卡诅咒药丸（默认公开分支）", () => {
  it("持卡者渲染「咒」药丸（卡背图标+单字标签+悬浮说明），未持卡者不渲染", () => {
    const game = makeGame(
      [makePlayer("p0", 0), makePlayer("p1", 1, { holdsCurseCard: true }), makePlayer("p2", 2, { holdsCurseCard: true })],
      familyViewer("p0"),
    );
    const { container } = render(<Board game={game} />);
    const pills = [...container.querySelectorAll<HTMLElement>(".curse-pill")];
    expect(pills).toHaveLength(2);
    for (const pill of pills) {
      expect(pill.textContent, "对局中默认只显「咒」，不泄露真假").toBe("咒");
      expect(pill.querySelector("svg"), "药丸带暗置卡背描边图标").not.toBeNull();
      expect(pill.getAttribute("title")).toBe(CURSE_TITLE);
    }
  });

  it("旁观者（viewer=null）同样看到持卡药丸，且药丸列在资源徽章之后同一行", () => {
    const game = makeGame([makePlayer("p0", 0, { resources: { shield: 1 }, holdsCurseCard: true })], null);
    const { container } = render(<Board game={game} />);
    const row = container.querySelector(".resources");
    expect(row, "药丸与资源徽章共用标记行").not.toBeNull();
    const cells = [...row!.children].map((el) => el.className);
    expect(cells.some((c) => c.includes("resource-pill")), "资源徽章在前").toBe(true);
    expect(cells[cells.length - 1]).toBe("curse-pill");
  });
});

describe("审判者设备：真假标签（投影驱动，重连恢复）", () => {
  it("viewer.curseAssignments 按收件人对应到座位：真咒/假咒，非持卡同行不受影响", () => {
    // 重连场景：断线重连后服务端投影直接携带归属，无任何事件重放。
    const game = makeGame(
      [makePlayer("p0", 0), makePlayer("p1", 1, { holdsCurseCard: true }), makePlayer("p2", 2, { holdsCurseCard: true })],
      inquisitorViewer("p0", { "true-curse-1": "p1", "false-curse-1": "p2" }),
    );
    const { container } = render(<Board game={game} />);
    expect(pillOf(container, "玩家1")?.textContent).toBe("真咒");
    expect(pillOf(container, "玩家2")?.textContent).toBe("假咒");
    expect(container.querySelectorAll(".curse-pill")).toHaveLength(2);
  });

  it("非审判者视角没有 curseAssignments 字段：同样的对局仍只显「咒」", () => {
    const game = makeGame(
      [makePlayer("p0", 0), makePlayer("p1", 1, { holdsCurseCard: true }), makePlayer("p2", 2, { holdsCurseCard: true })],
      familyViewer("p0"),
    );
    const { container } = render(<Board game={game} />);
    expect(pillOf(container, "玩家1")?.textContent).toBe("咒");
    expect(pillOf(container, "玩家2")?.textContent).toBe("咒");
  });
});

describe("终局全员翻牌（result.curseAssignments）", () => {
  const assignments = { "true-curse-1": "p1", "false-curse-1": "p2" };

  it("对局结束且归属非空：家族玩家视角药丸翻「真咒/假咒」（验收 4）", () => {
    const game = makeGame(
      [makePlayer("p0", 0), makePlayer("p1", 1, { holdsCurseCard: true }), makePlayer("p2", 2, { holdsCurseCard: true })],
      familyViewer("p0"),
      {
        winner: "rose",
        branch: "captured-leader",
        capturedPlayerId: "p3",
        activePlayerId: "p0",
        ranking: [],
        explanationKey: "game.end.captured-leader",
        curseAssignments: assignments,
      },
    );
    // makeGame 造的是 active 状态，这里直接改写为终局
    game.status = "ended";
    const { container } = render(<Board game={game} />);
    expect(pillOf(container, "玩家1")?.textContent).toBe("真咒");
    expect(pillOf(container, "玩家2")?.textContent).toBe("假咒");
  });

  it("对局结束但未分发诅咒（归属为空对象）：药丸不出现，保持供应区语义", () => {
    const game = makeGame([makePlayer("p0", 0)], familyViewer("p0"), {
      winner: "rose",
      branch: "captured-leader",
      capturedPlayerId: "p1",
      activePlayerId: "p0",
      ranking: [],
      explanationKey: "game.end.captured-leader",
      curseAssignments: {},
    });
    game.status = "ended";
    const { container } = render(<Board game={game} />);
    expect(container.querySelectorAll(".curse-pill")).toHaveLength(0);
  });

  it("持卡者被捕获后药丸仍显示（随卡半透明由 .seat.captured 承担）", () => {
    const game = makeGame(
      [makePlayer("p0", 0), makePlayer("p1", 1, { holdsCurseCard: true, captured: true })],
      inquisitorViewer("p0", assignments),
    );
    const { container } = render(<Board game={game} />);
    const pill = pillOf(container, "玩家1");
    expect(pill, "被捕获不隐藏药丸").not.toBeNull();
    expect(pill!.textContent).toBe("真咒");
    expect(pill!.closest(".seat.captured"), "药丸位于被捕获座位卡内（整卡半透明）").not.toBeNull();
  });
});

describe("结果面板诅咒归属行（ended 视图与回放终局共用 ResultBanner）", () => {
  const endedGame = (overrides: Partial<NonNullable<GameState["result"]>> = {}, holderSees: boolean = false) => {
    const game = makeGame(
      [makePlayer("p0", 0), makePlayer("p1", 1, { holdsCurseCard: true }), makePlayer("p2", 2, { holdsCurseCard: true })],
      holderSees ? inquisitorViewer("p0", { "true-curse-1": "p1", "false-curse-1": "p2" }) : familyViewer("p0"),
      {
        winner: "rose",
        branch: "captured-leader",
        capturedPlayerId: "p3",
        activePlayerId: "p0",
        ranking: [{ playerId: "p0", place: 1, score: 1 }],
        explanationKey: "game.end.captured-leader",
        curseAssignments: { "true-curse-1": "p1", "false-curse-1": "p2" },
        ...overrides,
      },
    );
    game.status = "ended";
    return game;
  };

  it("归属行「真诅咒在 X，假诅咒在 Y」列于胜负判词上方（验收 4）", () => {
    const { container } = render(<Board game={endedGame()} />);
    const banner = container.querySelector(".result");
    expect(banner).not.toBeNull();
    const line = banner!.querySelector<HTMLElement>(".curse-attribution");
    expect(line, "归属行存在").not.toBeNull();
    expect(line!.textContent).toContain("真诅咒在 玩家1");
    expect(line!.textContent).toContain("假诅咒在 玩家2");
    expect(line!.textContent).not.toContain("独赢");
    // 列于胜负判词上方：归属行是 .result 的第一个元素，判词在其后
    expect(banner!.firstElementChild).toBe(line);
    expect(banner!.textContent).toContain("对局结束，玫瑰家族获胜");
  });

  it("真诅咒触发审判者独赢：措辞点明覆盖（true-curse 分支）", () => {
    const { container } = render(
      <Board
        game={endedGame({
          winner: "secret-order",
          branch: "inquisitor-true-curse",
          explanationKey: "game.end.inquisitor-true-curse",
        })}
      />,
    );
    const line = container.querySelector<HTMLElement>(".curse-attribution");
    expect(line!.textContent).toContain("真诅咒在 玩家1（胜方领袖）");
    expect(line!.textContent).toContain("审判者独赢");
    expect(line!.textContent).toContain("家族胜利被覆盖");
    expect(line!.textContent).toContain("假诅咒在 玩家2");
  });

  it("未分发诅咒（归属空对象）：不出归属行，判词照旧", () => {
    const { container } = render(<Board game={endedGame({ curseAssignments: {} })} />);
    expect(container.querySelector(".curse-attribution")).toBeNull();
    expect(container.querySelector(".result")?.textContent).toContain("对局结束，玫瑰家族获胜");
  });
});
