import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { GameScreen } from "./GameScreen";
import type { Account } from "./AccountEntry";
import type { GameState, PlayerView, RoomState } from "./types";

// 工单 14（V08.04/V08.05 前端行为）：大厅与房间内持续显示当前账号并提供退出登录；
// 退出撤销当前登录并回到登录页；同一浏览器切换账号后旧账号的迟到帧、待确认队列
// 不得写入新账号页面或经新账号连接发出；会话失效给出独立的重新登录入口。

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
const BAI: Account = { accountId: "account-b", username: "白桦" };

function makeState(username: string, playerId: string, roomStatus: "waiting" | "playing", revision: number): RoomState {
  const self: PlayerView = {
    playerId, seat: 0, displayName: username, damage: 0, captured: false, holdsCurseCard: false,
    revealed: { markers: [null, null] }, identityMarkers: [null, null], resources: {},
  };
  const other: PlayerView = { ...self, playerId: "p-other", seat: 1, displayName: "别家" };
  const game: GameState = {
    gameId: "game-1", revision, status: roomStatus === "waiting" ? "setup" : "active",
    players: [self, other], daggerHolderId: playerId,
    phase: { kind: "action" }, pending: null, result: null,
    viewer: roomStatus === "playing" ? { playerId, identity: { faction: "rose", rank: 5 } } as GameState["viewer"] : null,
    legalActions: roomStatus === "playing" ? [{ type: "pass-dagger", targetPlayerId: "p-other" }] : [],
  };
  return {
    type: "state", roomCode: "123456", roomStatus, locked: false, isHost: false,
    yourPlayerId: playerId, hostPlayerId: playerId, connected: { [playerId]: true },
    hostActions: [], game, serverTime: 0,
  };
}

/** 按 URL 回放固定响应的 fetch mock；log 记录全部调用供撤销/登录断言。 */
function stubFetch(responses: Record<string, (init?: RequestInit) => { ok: boolean; json: () => Promise<unknown> }>) {
  const calls: { url: string; method: string }[] = [];
  const fetcher = vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET" });
    const handler = responses[url];
    if (!handler) return Promise.resolve({ ok: true, json: async () => ({}) });
    return Promise.resolve(handler(init));
  });
  vi.stubGlobal("fetch", fetcher);
  return calls;
}

async function restoreAs(account: Account) {
  render(<App />);
  await screen.findByText(`当前账号：${account.username}`);
}

async function joinRoom() {
  fireEvent.change(screen.getByLabelText("房间号"), { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: "加入房间" }));
}

describe("退出登录与切换账号（工单 14）", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("大厅与房间内持续显示当前账号与退出登录；退出后撤销当前登录并回到登录页", async () => {
    const calls = stubFetch({
      "/api/auth/session": () => ({ ok: true, json: async () => ({ account: ALICE }) }),
      "/api/account/room": () => ({ ok: true, json: async () => ({ room: null }) }),
      "/api/auth/logout": () => ({ ok: true, json: async () => ({ account: ALICE }) }),
    });
    await restoreAs(ALICE);
    expect(screen.getByRole("button", { name: "退出登录" })).toBeInTheDocument();

    await joinRoom();
    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    act(() => {
      ws.open();
      ws.receive(makeState(ALICE.username, "p-a", "waiting", 0));
    });
    // 房间内同样持续显示当前用户名与退出登录入口
    expect(screen.getByText(`当前账号：${ALICE.username}`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "退出登录" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
    await waitFor(() => {
      expect(calls.filter((call) => call.url === "/api/auth/logout" && call.method === "POST")).toHaveLength(1);
    });
    // 回到登录页；旧账号身份不再显示，房间连接关闭
    expect(await screen.findByRole("heading", { name: "登录" })).toBeInTheDocument();
    expect(screen.queryByText(`当前账号：${ALICE.username}`)).not.toBeInTheDocument();
    expect(ws.readyState).toBe(MockWebSocket.CLOSED);
  });

  it("切换账号：当前用户名与私有显示立即切换，旧账号的迟到帧和待确认命令不进入新账号", async () => {
    stubFetch({
      "/api/auth/session": () => ({ ok: true, json: async () => ({ account: ALICE }) }),
      "/api/account/room": () => ({ ok: true, json: async () => ({ room: null }) }),
      "/api/auth/logout": () => ({ ok: true, json: async () => ({ account: ALICE }) }),
      "/api/auth/login": () => ({ ok: true, json: async () => ({ account: BAI }) }),
    });
    await restoreAs(ALICE);
    await joinRoom();
    const wsA = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    act(() => {
      wsA.open();
      wsA.receive(makeState(ALICE.username, "p-a", "playing", 3));
    });
    // A 留下一条待确认命令（发送后未收到 ack）
    fireEvent.click(screen.getByRole("button", { name: "别家" }));
    const aCommands = wsA.sent.filter((raw: string) => raw.includes('"type":"command"'));
    expect(aCommands).toHaveLength(1);

    // A 退出登录，同一浏览器登录 B，再进入同一房间
    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
    await screen.findByRole("heading", { name: "登录" });
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: BAI.username } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "登录并进入大厅" }));
    expect(await screen.findByText(`当前账号：${BAI.username}`)).toBeInTheDocument();
    expect(screen.queryByText(`当前账号：${ALICE.username}`)).not.toBeInTheDocument();

    await joinRoom();
    const wsB = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    expect(wsB).not.toBe(wsA);
    act(() => {
      wsB.open();
      wsB.receive(makeState(BAI.username, "p-b", "waiting", 5));
    });
    // B 的页面：名册显示 B，且（你）标记在 B 的座位上（私有座位归属立即切换）
    // （getByText 的 content 是元素直接子文本的合并，名册项形如「白桦（你）（房主）」）
    const rosterItemOf = (username: string) =>
      screen.getByText((content, element) => element?.tagName === "LI" && content.startsWith(username));
    expect(rosterItemOf(BAI.username).textContent).toContain("（你）");
    // A 的迟到帧（更高修订号、A 的座位与名册）到达：不得写入 B 的页面
    act(() => {
      wsA.receive(makeState(ALICE.username, "p-a", "playing", 99));
    });
    expect(rosterItemOf(BAI.username).textContent).toContain("（你）");
    expect(screen.queryByText((content, element) => element?.tagName === "LI" && content.startsWith(ALICE.username))).not.toBeInTheDocument();
    expect(screen.getByText(/等待玩家加入/)).toBeInTheDocument();
    // A 的待确认命令不得经 B 的连接发出
    expect(wsB.sent.filter((raw: string) => raw.includes('"type":"command"'))).toHaveLength(0);
  });
});

describe("会话失效的重新登录入口（工单 14）", () => {
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
    ["auth.session-expired", "登录已过期，请重新登录。"],
    ["auth.session-revoked", "当前登录已退出，请重新登录。"],
    ["auth.password-changed", "密码已修改，请重新登录。"],
  ])("对局中收到 %s 错误帧：停止重连并给出重新登录入口", (code, text) => {
    const onAuthLost = vi.fn();
    render(
      <GameScreen
        credentials={{ code: "123456", accountId: "account-a", mode: "player" }}
        onLeave={vi.fn()}
        onAuthLost={onAuthLost}
      />,
    );
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.open();
      ws.receive(makeState(ALICE.username, "p-a", "playing", 3));
      ws.receive({ type: "error", code, message: text, details: {} });
      ws.drop();
    });
    expect(screen.getByRole("heading", { name: "登录已失效" })).toBeInTheDocument();
    expect(screen.getByText(text)).toBeInTheDocument();
    // 会话失效是终止性的：不再自动重连
    act(() => {
      vi.advanceTimersByTime(120_000);
    });
    expect(MockWebSocket.instances).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "重新登录" }));
    expect(onAuthLost).toHaveBeenCalledTimes(1);
  });
});
