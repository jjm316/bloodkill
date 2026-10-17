import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GameScreen } from "./GameScreen";
import { makeState, MockWebSocket } from "./joinFailure.test";

// 工单 13：等待普通玩家「退出房间」是服务端真退座（leave → left 确认才回大厅）；
// 房主「返回大厅」与对局中「返回大厅」只断开连接保留座位，不发 leave、不等确认。
// 测试在 mock WebSocket 网络边界观察外部行为；服务端真退座语义由
// tests/test_account_seat_exit.py 以真实 uvicorn/HTTP/WS 覆盖（V07.01–V07.05）。

function renderGameScreen(onLeave = vi.fn()) {
  render(<GameScreen credentials={{ code: "123456", accountId: "fixture-seat-exit", mode: "player" }} onLeave={onLeave} />);
  return onLeave;
}

describe("等待玩家退座与房主返回大厅", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("等待普通玩家看到「退出房间」：点击发送 leave，收到 left 确认后才回大厅", () => {
    const onLeave = renderGameScreen();
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.open();
      ws.receive(makeState());
    });
    expect(screen.getByRole("button", { name: "退出房间" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "返回大厅" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "退出房间" }));
    expect(ws.sent.some((frame) => frame.includes('"type":"leave"'))).toBe(true);
    // 未收到确认前不离开房间视图。
    expect(onLeave).not.toHaveBeenCalled();

    act(() => {
      ws.receive({ type: "left", roomCode: "123456" });
    });
    expect(onLeave).toHaveBeenCalledTimes(1);
  });

  it("退座确认后连接关闭不触发自动重连", () => {
    const onLeave = renderGameScreen();
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.open();
      ws.receive(makeState());
    });
    fireEvent.click(screen.getByRole("button", { name: "退出房间" }));
    act(() => {
      ws.receive({ type: "left", roomCode: "123456" });
      ws.drop();
      vi.advanceTimersByTime(30_000);
    });
    expect(onLeave).toHaveBeenCalledTimes(1);
    expect(MockWebSocket.instances).toHaveLength(1); // 退座确认后不得再新建连接
  });

  it("等待房主看到「返回大厅」而非退座：点击不发 leave，直接回大厅保留座位", () => {
    const onLeave = renderGameScreen();
    const ws = MockWebSocket.instances[0];
    const hostState = makeState();
    hostState.isHost = true;
    act(() => {
      ws.open();
      ws.receive(hostState);
    });
    const button = screen.getByRole("button", { name: "返回大厅" });
    expect(screen.queryByRole("button", { name: "退出房间" })).not.toBeInTheDocument();
    fireEvent.click(button);
    expect(ws.sent.some((frame) => frame.includes('"type":"leave"'))).toBe(false);
    expect(onLeave).toHaveBeenCalledTimes(1);
  });

  it("对局中的普通玩家看到「返回大厅」：点击只断开连接，不发 leave", () => {
    const onLeave = renderGameScreen();
    const ws = MockWebSocket.instances[0];
    const playing = makeState();
    playing.roomStatus = "playing";
    act(() => {
      ws.open();
      ws.receive(playing);
    });
    fireEvent.click(screen.getByRole("button", { name: "返回大厅" }));
    expect(ws.sent.some((frame) => frame.includes('"type":"leave"'))).toBe(false);
    expect(onLeave).toHaveBeenCalledTimes(1);
  });

  it("leave 被服务端拒绝时停留在房间并显示中文原因，不回大厅", () => {
    const onLeave = renderGameScreen();
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.open();
      ws.receive(makeState());
    });
    fireEvent.click(screen.getByRole("button", { name: "退出房间" }));
    act(() => {
      ws.receive({ type: "error", code: "room.host-seat-kept", message: "房主返回大厅不会退座；你的座位和房主身份会保留。", details: {} });
    });
    expect(onLeave).not.toHaveBeenCalled();
    expect(screen.getByText(/房主返回大厅不会退座/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "退出房间" })).toBeInTheDocument();
  });
});
