import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WaitingRoom } from "./GameScreen";
import type { GameState, PlayerView, RoomState } from "./types";

// 等待名册「自己高亮 / 房主标记 / 离线后缀」回归测试
// （.scratch/frontend-test-infra/issues/01，标记顺序契约见 spec 现状一节）。

function makePlayer(id: string, name: string, seat: number): PlayerView {
  return {
    playerId: id,
    seat,
    displayName: name,
    damage: 0,
    captured: false,
    revealed: { markers: [null, null] },
    identityMarkers: [null, null],
    resources: {},
  };
}

function makeGame(players: PlayerView[]): GameState {
  return {
    gameId: "game-1",
    revision: 0,
    status: "waiting",
    players,
    daggerHolderId: null,
    phase: { kind: "action" },
    pending: null,
    result: null,
    viewer: null,
    legalActions: [],
  };
}

function makeRoomState(players: PlayerView[], overrides: Partial<RoomState> = {}): RoomState {
  return {
    type: "state",
    roomCode: "ABC123",
    roomStatus: "waiting",
    locked: false,
    isHost: false,
    yourPlayerId: null,
    hostPlayerId: null,
    connected: {},
    hostActions: [],
    game: makeGame(players),
    serverTime: 0,
    ...overrides,
  };
}

const sendHost = vi.fn();

function renderWaitingRoom(state: RoomState, spectating = false) {
  return render(<WaitingRoom state={state} sendHost={sendHost} spectating={spectating} />);
}

function rosterRows(): HTMLLIElement[] {
  return Array.from(document.querySelectorAll<HTMLLIElement>("ul.roster > li"));
}

function rowOf(name: string): HTMLLIElement {
  // 行文本 = 昵称 + 若干（…）标记；要求昵称后紧跟「（」，避免昵称互为前缀时选错行
  const row = rosterRows().find((li) => {
    const text = li.textContent ?? "";
    return text === name || (text.startsWith(name) && text[name.length] === "（");
  });
  if (!row) throw new Error(`名册中找不到 ${name} 的行`);
  return row;
}

describe("WaitingRoom 名册标记", () => {
  it("自己的行带 self class 且显示（你），他人行不带", () => {
    const players = [makePlayer("p1", "阿玫", 0), makePlayer("p2", "小兽", 1)];
    renderWaitingRoom(makeRoomState(players, { yourPlayerId: "p1", connected: { p1: true, p2: true } }));
    expect(rowOf("阿玫")).toHaveClass("self");
    expect(rowOf("阿玫").textContent).toContain("（你）");
    expect(rowOf("小兽")).not.toHaveClass("self");
    expect(rowOf("小兽").textContent).not.toContain("（你）");
  });

  it("房主标记在房主本人、其他玩家、旁观者三种视角都可见", () => {
    const players = [makePlayer("h", "老大哥", 0), makePlayer("p", "小兽", 1)];
    const views = [
      { state: makeRoomState(players, { yourPlayerId: "h", hostPlayerId: "h", isHost: true, connected: { h: true, p: true } }), spectating: false },
      { state: makeRoomState(players, { yourPlayerId: "p", hostPlayerId: "h", connected: { h: true, p: true } }), spectating: false },
      { state: makeRoomState(players, { yourPlayerId: null, hostPlayerId: "h", connected: { h: true, p: true } }), spectating: true },
    ];
    for (const { state, spectating } of views) {
      const { unmount } = renderWaitingRoom(state, spectating);
      expect(rowOf("老大哥").textContent).toContain("（房主）");
      unmount();
    }
  });

  it("断线玩家显示（离线），在线玩家不显示", () => {
    const players = [makePlayer("p1", "阿玫", 0), makePlayer("p2", "小兽", 1)];
    renderWaitingRoom(makeRoomState(players, { connected: { p1: true, p2: false } }));
    expect(rowOf("小兽").textContent).toContain("（离线）");
    expect(rowOf("阿玫").textContent).not.toContain("（离线）");
  });

  it("旁观者视角：没有任何行带 self，页面不含（你）", () => {
    const players = [makePlayer("p1", "阿玫", 0), makePlayer("p2", "小兽", 1)];
    const { container } = renderWaitingRoom(makeRoomState(players, { yourPlayerId: null }), true);
    for (const row of rosterRows()) expect(row).not.toHaveClass("self");
    expect(container.textContent).not.toContain("（你）");
  });

  it("自己同时是房主：（你）在（房主）之前", () => {
    const players = [makePlayer("h", "老大哥", 0), makePlayer("p", "小兽", 1)];
    renderWaitingRoom(makeRoomState(players, { yourPlayerId: "h", hostPlayerId: "h", isHost: true, connected: { h: true, p: true } }));
    const row = rowOf("老大哥");
    expect(row.textContent).toContain("（你）");
    expect(row.textContent).toContain("（房主）");
    expect(row.textContent!.indexOf("（你）")).toBeLessThan(row.textContent!.indexOf("（房主）"));
    expect(row).toHaveClass("self");
  });

  it("三个标记齐全时顺序为 昵称 →（你）→（房主）→（离线）", () => {
    const players = [makePlayer("h", "老大哥", 0), makePlayer("p", "小兽", 1)];
    renderWaitingRoom(
      makeRoomState(players, { yourPlayerId: "h", hostPlayerId: "h", isHost: true, connected: { h: false, p: true } })
    );
    expect(rowOf("老大哥").textContent).toBe("老大哥（你）（房主）（离线）");
  });
});
