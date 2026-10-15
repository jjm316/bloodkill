import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GameScreen } from "./GameScreen";
import type { Account } from "./AccountEntry";
import type { GameState, PlayerView, RoomState } from "./types";

// 工单 21（V15 前端行为）：对局中收到 room.admin-closed 终止帧时，玩家得到
// 显著的中文说明（房间被管理员关闭、不产生胜负）与返回大厅路径；连接是
// 终止性的——不再自动重连撞 404。

class MockWebSocket {
  static CONNECTING = 0 as const;
  static OPEN = 1 as const;
  static CLOSING = 2 as const;
  static CLOSED = 3 as const;
  static instances: MockWebSocket[] = [];
  url: string;
  readyState: number = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }
  send(data: string): void {
    this.sent.push(data);
  }
  close(): void {
    this.readyState = MockWebSocket.CLOSED;
  }
  open(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }
  receive(message: unknown): void {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
  drop(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }
}

const ALICE: Account = { accountId: "account-a", username: "阿玫" };

function makeState(roomStatus: "waiting" | "playing", revision: number): RoomState {
  const self: PlayerView = {
    playerId: "p-a", seat: 0, displayName: ALICE.username, damage: 0, captured: false,
    holdsCurseCard: false, revealed: { markers: [null, null] }, identityMarkers: [null, null],
    resources: {},
  };
  const other: PlayerView = { ...self, playerId: "p-other", seat: 1, displayName: "别家" };
  const game: GameState = {
    gameId: "game-1", revision, status: roomStatus === "waiting" ? "setup" : "active",
    players: [self, other], daggerHolderId: "p-a",
    phase: { kind: "action" }, pending: null, result: null,
    viewer: null,
    legalActions: roomStatus === "playing" ? [{ type: "pass-dagger", targetPlayerId: "p-other" }] : [],
  };
  return {
    type: "state", roomCode: "123456", roomStatus, locked: false, isHost: true,
    yourPlayerId: "p-a", hostPlayerId: "p-a", connected: { "p-a": true },
    hostActions: [], game, serverTime: 0,
  };
}

describe("管理关闭房间的前端反馈（工单 21）", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it.each([
    ["playing", "进行中"],
    ["waiting", "等待中"],
  ])("%s 的房间被管理员关闭：中文横幅说明、返回大厅入口且不再重连", (roomStatus) => {
    const onLeave = vi.fn();
    render(
      <GameScreen
        credentials={{ code: "123456", accountId: "account-a", mode: "player" }}
        onLeave={onLeave}
      />,
    );
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.open();
      ws.receive(makeState(roomStatus as "waiting" | "playing", 5));
      ws.receive({
        type: "error", code: "room.admin-closed",
        message: "房间已被管理员关闭，请返回大厅创建或加入新的房间。", details: {},
      });
      ws.drop();
    });
    expect(screen.getByRole("heading", { name: "房间已被管理员关闭" })).toBeInTheDocument();
    const detail = screen.getByText(/该房间已被管理员关闭/);
    expect(detail.textContent).toContain("返回大厅");
    // 关闭是终止性的：连接断开后不得再排程重连
    act(() => {
      vi.advanceTimersByTime(120_000);
    });
    expect(MockWebSocket.instances).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "返回大厅" }));
    expect(onLeave).toHaveBeenCalledTimes(1);
  });
});
