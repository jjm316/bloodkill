import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Board } from "./Board";
import type { GameState, PlayerView } from "./types";

function game(winner = "rose", count = 7): GameState {
  const players: PlayerView[] = Array.from({ length: count }, (_, index) => ({
    playerId: `p${index}`, seat: index, displayName: `玩家${index}`,
    damage: index === 0 ? 4 : 0, captured: index === 0,
    revealed: { markers: [null, null] }, identityMarkers: [null, null], resources: {}, holdsCurseCard: false,
    identity: index === count - 1 && count % 2 === 1
      ? { faction: "secret-order", rank: "fleur-cross" }
      : { faction: index % 2 === 0 ? "rose" : "beast", rank: index + 1 },
  }));
  return {
    gameId: "g1", revision: 30, status: "ended", players, daggerHolderId: null,
    phase: { kind: "ended" }, pending: null, legalActions: [],
    viewer: {
      playerId: "p0", identity: players[0].identity!, identityMarkers: [], resources: {}, skillsUsed: [],
      inspections: {}, cursesToDistribute: [], clueIcon: "beast", seenNeighbourClue: null,
    },
    result: {
      winner, branch: "captured-leader", capturedPlayerId: "p0", activePlayerId: "p1",
      explanationKey: "game.end.captured-leader", curseAssignments: {},
      ranking: players.map((player, index) => ({ playerId: player.playerId, place: count - index, score: Number(player.identity?.faction === winner) })),
    },
  };
}

describe("终局阵营对照", () => {
  it.each(["rose", "beast", "secret-order"])("%s 获胜时逐人展示真实身份及引擎胜负", (winner) => {
    const state = game(winner);
    render(<Board game={state} />);
    const dialog = screen.getByRole("dialog");
    for (const player of state.players) {
      const row = within(dialog).getByText(player.displayName).closest("li")!;
      expect(row).toHaveTextContent(player.identity!.rank === "fleur-cross" ? "审判者" : `等级${player.identity!.rank}`);
      expect(row).toHaveTextContent(player.identity!.faction === winner ? "胜利" : "失败");
      expect(row.querySelector(".endgame-verdict.won") !== null).toBe(player.identity!.faction === winner);
    }
    expect(within(dialog).getByRole("region", { name: "玫瑰家族" })).toHaveClass("rose");
    expect(within(dialog).getByRole("region", { name: "野兽家族" })).toHaveClass("beast");
    expect(within(dialog).getByRole("region", { name: "审判者" })).toHaveClass("order");
    expect(within(dialog).getByText(winner === "rose" ? "你胜利了 · 玫瑰家族" : "你失败了 · 玫瑰家族")).toBeInTheDocument();
    if (winner === "secret-order") expect(dialog).toHaveTextContent("审判者独赢");
  });

  it("个人胜负取 score，不取被捕获状态、家族推断或 place", () => {
    const state = game();
    state.result!.ranking[0].score = 0;
    state.result!.ranking[1].score = 1;
    render(<Board game={state} />);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("玩家0").closest("li")).toHaveTextContent("失败");
    expect(within(dialog).getByText("玩家1").closest("li")).toHaveTextContent("胜利");
    expect(within(dialog).getByText("玩家0").closest("li")).toHaveTextContent("等级1");
  });

  it("关闭后可再次查看，同一终局更新不重复打开；回放重新进入末帧会打开", () => {
    const state = game();
    const { rerender } = render(<Board game={state} />);
    fireEvent.click(screen.getByRole("button", { name: "关闭，查看棋盘" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "查看结果" })).toHaveFocus();
    rerender(<Board game={{ ...state, revision: 31 }} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "查看结果" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    rerender(<Board game={{ ...state, status: "active", result: null }} />);
    expect(screen.queryByRole("button", { name: "查看结果" })).toBeNull();
    rerender(<Board game={state} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("键盘可聚焦名单阅读，并在名单与关闭按钮之间循环", () => {
    render(<Board game={game("rose", 11)} />);
    const roster = screen.getByRole("region", { name: "玩家结算名单" });
    const close = screen.getByRole("button", { name: "关闭，查看棋盘" });
    expect(roster).toHaveAttribute("tabindex", "0");
    expect(roster).toHaveFocus();
    fireEvent.keyDown(roster, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(close, { key: "Tab" });
    expect(roster).toHaveFocus();
    fireEvent.keyDown(roster, { key: "Tab", shiftKey: true });
    expect(close).toHaveFocus();
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(roster).toHaveFocus();
    fireEvent.keyDown(roster, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("偶数局隐藏审判者组，旁观者没有本人胜负，重新挂载可查看完整结算", () => {
    const state = { ...game("beast", 12), viewer: null };
    const first = render(<Board game={state} />);
    expect(within(screen.getByRole("dialog")).queryByRole("region", { name: "审判者" })).toBeNull();
    expect(screen.getByRole("dialog").querySelector(".endgame-personal")).toBeNull();
    expect(within(screen.getByRole("dialog")).getAllByRole("listitem")).toHaveLength(12);
    first.unmount();
    render(<Board game={state} />);
    expect(screen.getByRole("dialog")).toHaveTextContent("全员身份已揭晓");
  });

  it("旧回放平局和缺失身份明确展示，不猜家族或把平局写为获胜", () => {
    const state = game("draw");
    state.viewer = null;
    state.players.forEach((player) => delete player.identity);
    render(<Board game={state} />);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("对局结束，平局");
    expect(dialog).not.toHaveTextContent("平局获胜");
    expect(within(dialog).getAllByRole("listitem")).toHaveLength(7);
    expect(within(dialog).getByRole("region", { name: "身份未记录" })).toBeInTheDocument();
    expect(dialog).toHaveTextContent("等级未记录");
  });
});
