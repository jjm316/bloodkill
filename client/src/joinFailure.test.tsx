import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GameScreen } from "./GameScreen";
import type { GameState, PlayerView, RoomState } from "./types";

// 进房失败态（.scratch/ui-fix-usability/spec.md）：mock WebSocket 观察外部行为——
// 初始连接 10 秒无状态应答 → 失败 Banner + 可返回大厅；已收到过状态的断线只重连、
// 永不进入失败态；服务端 room.not-found 错误帧 → 立即显示具体原因。

export class MockWebSocket {
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

export function makeState(): RoomState {
  const player: PlayerView = {
    playerId: "p1",
    seat: 0,
    displayName: "阿玫",
    damage: 0,
    captured: false,
    holdsCurseCard: false,
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
  render(<GameScreen credentials={{ code: "123456", accountId: "fixture-ui-account", mode: "player" }} onLeave={onLeave} />);
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

// 工单 10：账号加入房间——加入阶段的房间错误帧必须终止初始重连并给出中文原因；
// 已进入对局后的 error（如房主操作被拒）不影响断线重连。
describe("账号加入拒绝", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("锁定房间拒绝后停止初始重连：不再建立新的 WebSocket，只保留返回大厅入口", () => {
    renderGameScreen();
    const first = MockWebSocket.instances[0];
    act(() => {
      first.open();
    });
    act(() => {
      first.receive({ type: "error", code: "room.locked", message: "房间已锁定，暂不能加入。", details: {} });
      first.drop();
    });
    expect(screen.getByRole("heading", { name: "无法加入房间" })).toBeInTheDocument();
    expect(screen.getByText("房间已锁定。")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(120_000);
    });
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it.each([
    ["room.full", "房间已满员（12 人），不能加入。"],
    ["room.ended", "对局已结束，不能加入；可观看回放。"],
    ["account.room-occupied", "你已有未结束房间，请返回原房间。"],
  ])("%s 显示中文原因并可返回大厅", (code, text) => {
    renderGameScreen();
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.open();
      ws.receive({ type: "error", code, message: text, details: {} });
      ws.drop();
    });
    expect(screen.getByRole("heading", { name: "无法加入房间" })).toBeInTheDocument();
    expect(screen.getByText(text)).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("对局中收到房主操作被拒的 error 不停止断线重连", () => {
    renderGameScreen();
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.open();
      ws.receive(makeState());
    });
    act(() => {
      ws.receive({ type: "error", code: "room.not-host", message: "只有房主可以执行此操作。", details: {} });
    });
    expect(screen.getByText("操作未完成，请检查当前阶段和操作条件。")).toBeInTheDocument();
    act(() => {
      ws.drop();
      vi.advanceTimersByTime(1_000);
    });
    expect(MockWebSocket.instances.length).toBeGreaterThan(1);
  });

  it("座位被接管显示已在其他设备进入房间，而不是旧的姓名文案", () => {
    renderGameScreen();
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.open();
      ws.receive(makeState());
      ws.receive({ type: "taken-over", reason: "seat taken over by a new connection" });
      ws.drop();
    });
    expect(screen.getByRole("heading", { name: "座位已被接管" })).toBeInTheDocument();
    expect(screen.getByText(/已在其他设备进入房间/)).toBeInTheDocument();
    expect(screen.queryByText(/使用其他姓名/)).not.toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(MockWebSocket.instances).toHaveLength(1);
  });
});
