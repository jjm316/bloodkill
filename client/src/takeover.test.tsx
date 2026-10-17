import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GameScreen } from "./GameScreen";
import { useGameSocket, type SocketHandle } from "./useSocket";
import { makeState, MockWebSocket } from "./joinFailure.test";

// 工单 11：座位接管与普通断线是两条不同路径——接管终止一切（重连、补发、
// 迟到帧），普通断线保留指数退避重连与待确认命令补发。测试在 mock WebSocket
// 网络边界观察外部行为；服务端接管语义由 tests/test_account_takeover.py 以
// 真实 uvicorn/HTTP/WS 覆盖。

let handle: SocketHandle | null = null;
function SocketHarness() {
  handle = useGameSocket("123456", "fixture-takeover-account", "player");
  return null;
}

describe("座位接管（hook 边界）", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("接管后丢弃待确认命令：迟到的 state 帧不再经旧 socket 补发", () => {
    render(<SocketHarness />);
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.open();
      ws.receive(makeState());
    });
    act(() => {
      handle?.send("pass-dagger", { targetPlayerId: "p2" });
    });
    expect(ws.sent.filter((frame) => frame.includes("pass-dagger"))).toHaveLength(1);

    act(() => {
      ws.receive({ type: "taken-over", reason: "seat taken over by a new connection" });
    });
    // close 帧未到达前，旧 socket 上挤进来的迟到投影不得触发补发。
    act(() => {
      ws.receive(makeState());
    });
    // 接管后不得再补发待确认命令。
    expect(ws.sent.filter((frame) => frame.includes("pass-dagger"))).toHaveLength(1);
    expect(handle?.takenOver).toBe(true);
  });

  it("接管后的迟到 state/event/ack 帧不更新状态、不清除接管标记", () => {
    render(<SocketHarness />);
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.open();
      ws.receive(makeState());
    });
    const revisionAtTakeover = handle?.state?.game?.revision;
    act(() => {
      ws.receive({ type: "taken-over", reason: "seat taken over by a new connection" });
    });
    const late = makeState();
    if (late.game) late.game.revision = 99;
    act(() => {
      ws.receive(late);
      ws.receive({ type: "event", events: [{ eventId: "e:1", eventType: "PlayerPassed", gameId: "game-1", revision: 99, timestamp: 0, commandId: "c", payload: {} }] });
      ws.receive({ type: "ack", commandId: "pending-1", status: "accepted", revision: 99 });
    });
    // 迟到帧不得污染接管后的状态。
    expect(handle?.state?.game?.revision).toBe(revisionAtTakeover);
    expect(handle?.events).toHaveLength(0);
    expect(handle?.takenOver).toBe(true);
  });

  it("接管后 send 不再入队或经旧 socket 发送，也不再新建 WebSocket", () => {
    render(<SocketHarness />);
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.open();
      ws.receive(makeState());
      ws.receive({ type: "taken-over", reason: "seat taken over by a new connection" });
    });
    act(() => {
      handle?.send("attack", { targetPlayerId: "p2" });
      handle?.sendHost("lock");
    });
    expect(ws.sent.filter((frame) => frame.includes("attack") || frame.includes("host"))).toHaveLength(0);
    act(() => {
      vi.advanceTimersByTime(120_000);
    });
    // 接管后不得产生新的争抢连接。
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("普通断线对照：重连后待确认命令经新 socket 补发，界面恢复", () => {
    render(<GameScreen credentials={{ code: "123456", accountId: "fixture-takeover-account", mode: "player" }} onLeave={vi.fn()} />);
    const first = MockWebSocket.instances[0];
    act(() => {
      first.open();
      first.receive(makeState());
    });
    act(() => {
      first.drop();
    });
    expect(screen.getByText("正在重新连接……")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    const second = MockWebSocket.instances[1];
    expect(second).toBeDefined();
    act(() => {
      second.open();
      second.receive(makeState());
    });
    expect(screen.queryByText("正在重新连接……")).not.toBeInTheDocument();
    expect(screen.getByText(/等待玩家加入/)).toBeInTheDocument();
  });
});

describe("座位接管（GameScreen 边界）", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("接管后的迟到投影不把界面拉回房间视图，横幅保持", () => {
    render(<GameScreen credentials={{ code: "123456", accountId: "fixture-takeover-account", mode: "player" }} onLeave={vi.fn()} />);
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.open();
      ws.receive(makeState());
      ws.receive({ type: "taken-over", reason: "seat taken over by a new connection" });
    });
    expect(screen.getByRole("heading", { name: "座位已被接管" })).toBeInTheDocument();
    const late = makeState();
    if (late.game) late.game.revision = 55;
    act(() => {
      ws.receive(late);
    });
    expect(screen.getByRole("heading", { name: "座位已被接管" })).toBeInTheDocument();
    expect(screen.getByText(/已在其他设备进入房间/)).toBeInTheDocument();
    expect(screen.queryByText(/等待玩家加入/)).not.toBeInTheDocument();
  });
});
