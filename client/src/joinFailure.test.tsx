import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GameScreen } from "./GameScreen";
import type { GameState, PlayerView, RoomState } from "./types";

// 进房失败态（.scratch/ui-fix-usability/spec.md）：mock WebSocket 观察外部行为——
// 初始连接 10 秒无状态应答 → 失败 Banner + 可返回大厅；已收到过状态的断线只重连、
// 永不进入失败态；服务端 room.not-found 错误帧 → 立即显示具体原因。

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

  // 测试侧手动驱动事件：真实浏览器里这些由网络层触发
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

function makeState(): RoomState {
  const player: PlayerView = {
    playerId: "p1",
    seat: 0,
    displayName: "阿玫",
    damage: 0,
    captured: false,
    revealed: { markers: [null, null] },
    identityMarkers: [null, null],
    resources: {},
  };
  const game: GameState = {
    gameId: "game-1",
    revision: 0,
    status: "waiting",
    players: [player],
    daggerHolderId: null,
    phase: { kind: "action" },
    pending: null,
    result: null,
    viewer: null,
    legalActions: [],
  };
  return {
    type: "state",
    roomCode: "123456",
    roomStatus: "waiting",
    locked: false,
    isHost: false,
    yourPlayerId: "p1",
    hostPlayerId: "p1",
    connected: { p1: true },
    hostActions: [],
    game,
    serverTime: 0,
  };
}

function renderGameScreen(onLeave = vi.fn()) {
  render(<GameScreen credentials={{ code: "123456", name: "阿玫", token: null }} onLeave={onLeave} />);
  return onLeave;
}

describe("进房失败态", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("连接建立但服务器 10 秒无应答：显示无法加入房间并可返回大厅", () => {
    const onLeave = renderGameScreen();
    expect(screen.getByText("正在连接……")).toBeInTheDocument();

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.open();
    });
    act(() => {
      vi.advanceTimersByTime(9_999);
    });
    expect(screen.getByText("正在连接……")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByRole("heading", { name: "无法加入房间" })).toBeInTheDocument();
    expect(screen.getByText(/请核对房间号/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "返回大厅" }));
    expect(onLeave).toHaveBeenCalledTimes(1);
  });

  it("已收到过状态的断线重连不触发失败态：一直显示正在重新连接", () => {
    renderGameScreen();
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.open();
    });
    act(() => {
      ws.receive(makeState());
    });
    expect(screen.getByText(/等待玩家加入/)).toBeInTheDocument();

    act(() => {
      ws.drop();
    });
    expect(screen.getByText("正在重新连接……")).toBeInTheDocument();

    // 远超 10 秒的重连静默期（期间重连尝试全部无应答）也不进入失败态
    act(() => {
      vi.advanceTimersByTime(120_000);
    });
    expect(screen.queryByRole("heading", { name: "无法加入房间" })).not.toBeInTheDocument();
    expect(screen.getByText("正在重新连接……")).toBeInTheDocument();
    expect(screen.getByText(/等待玩家加入/)).toBeInTheDocument();
  });

  it("服务端 room.not-found 错误帧：立即显示房间不存在，而不是无限连接", () => {
    renderGameScreen();
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.open();
    });
    act(() => {
      ws.receive({ type: "error", code: "room.not-found", message: "Room not found.", details: {} });
      ws.drop();
    });

    expect(screen.getByRole("heading", { name: "无法加入房间" })).toBeInTheDocument();
    expect(screen.getByText("房间不存在，请核对房间号。")).toBeInTheDocument();
  });
});
