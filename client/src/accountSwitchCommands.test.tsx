import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { Account } from "./AccountEntry";
import type { GameState, PlayerView, RoomState } from "./types";

// 工单 18（V12.02/V12.04）：切换账号后自动挡刀命令的**实际发送者与内容**——
// A 的偏好不能让 B 的连接代发；迟到 A 帧不能驱动 B；B 自己开启后才以 B 身份
// 发出；私有猜测（备忘/偏好）不出现在命令、请求或 URL。
// seam：真实 useGameSocket + 可控 WebSocket 全局 mock（accountSession.test.tsx
// 模式），断言 ws.sent 里的 wire 帧，不只验证页面值。

class MockWebSocket {
  static CONNECTING = 0 as const;
  static OPEN = 1 as const;
  static CLOSING = 2 as const;
  static CLOSED = 3 as const;
  static instances: MockWebSocket[] = [];
  url: string;
  readyState: number = 0;
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
    this.readyState = 3;
  }
  open(): void {
    this.readyState = 1;
    this.onopen?.();
  }
  receive(message: unknown): void {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

const ALICE: Account = { accountId: "account-a", username: "阿玫" };
const BAI: Account = { accountId: "account-b", username: "白桦" };
const TARGET = "小标";

/** 以 username 为有资格挡刀者的 poll 投票窗口（legalActions：respond-intervention）。 */
function pollWindow(username: string, playerId: string, revision: number): RoomState {
  const self: PlayerView = {
    playerId, seat: 0, displayName: username, damage: 0, captured: false, holdsCurseCard: false,
    revealed: { markers: [null, null] }, identityMarkers: [null, null], resources: {},
  };
  const target: PlayerView = { ...self, playerId: "p-target", seat: 1, displayName: TARGET };
  const game: GameState = {
    gameId: "game-1", revision, status: "active",
    players: [self, target], daggerHolderId: "p-target",
    phase: { kind: "intervention", stage: "poll", activePlayerId: "p-target" },
    pending: {
      kind: "intervention", actorPlayerId: "p-target", targetPlayerId: "p-target",
      eligiblePlayerIds: [playerId], rank: null, trigger: null, stage: "poll",
      attackerPlayerId: "p-attacker", responses: {}, deadline: Date.now() / 1000 + 120,
    },
    result: null,
    viewer: { playerId, identity: { faction: "rose", rank: 5 } } as GameState["viewer"],
    legalActions: [
      { type: "respond-intervention", volunteer: true },
      { type: "respond-intervention", volunteer: false },
    ],
  };
  return {
    type: "state", roomCode: "123456", roomStatus: "playing", locked: false, isHost: false,
    yourPlayerId: playerId, hostPlayerId: "p-host", connected: { [playerId]: true },
    hostActions: [], game, serverTime: 0,
  };
}

const commandFrames = (ws: MockWebSocket) =>
  ws.sent.map((raw) => JSON.parse(raw)).filter((m) => m.type === "command");

/** 按 URL 回放固定响应的 fetch mock；log 记录全部调用供隐私断言。 */
function stubFetch(responses: Record<string, () => { ok: boolean; json: () => Promise<unknown> }>) {
  const calls: { url: string }[] = [];
  const fetcher = vi.fn((url: string) => {
    calls.push({ url });
    const handler = responses[url];
    if (!handler) return Promise.resolve({ ok: true, json: async () => ({}) });
    return Promise.resolve(handler());
  });
  vi.stubGlobal("fetch", fetcher);
  return calls;
}

const authResponses = {
  "/api/auth/session": () => ({ ok: true, json: async () => ({ account: ALICE }) }),
  "/api/account/room": () => ({ ok: true, json: async () => ({ room: null }) }),
  "/api/auth/logout": () => ({ ok: true, json: async () => ({ account: ALICE }) }),
  "/api/auth/login": () => ({ ok: true, json: async () => ({ account: BAI }) }),
};

async function login(username: string) {
  fireEvent.change(screen.getByLabelText("用户名"), { target: { value: username } });
  fireEvent.change(screen.getByLabelText("密码"), { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: "登录并进入大厅" }));
}

async function joinRoom() {
  fireEvent.change(screen.getByLabelText("房间号"), { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: "加入房间" }));
}

describe("切换账号的自动挡刀命令发送者与内容（工单 18）", () => {
  beforeEach(() => {
    localStorage.clear();
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
  });
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("V12.02：A 设默认不挡刀 → B 在实际窗口不代发，迟到 A 帧不驱动 B；B 开启后才以 B 发出；回 A 偏好仍在", async () => {
    stubFetch(authResponses);
    render(<App />);
    await screen.findByText(`当前账号：${ALICE.username}`);

    // A 进房并在真实投票窗口开启「默认不挡刀」：A 的连接发出 volunteer:false
    await joinRoom();
    const wsA = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    act(() => {
      wsA.open();
      wsA.receive(pollWindow(ALICE.username, "p-a", 13));
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "默认不挡刀" }));
    const aCommands = commandFrames(wsA);
    expect(aCommands).toHaveLength(1);
    expect(aCommands[0]).toMatchObject({ command: "respond-intervention", payload: { volunteer: false } });
    expect(screen.queryByText(`是否为 ${TARGET} 挡刀？`)).not.toBeInTheDocument();

    // 同一浏览器：A 退出 → 登录 B → 进同一房间
    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
    await screen.findByRole("heading", { name: "登录" });
    await login(BAI.username);
    expect(await screen.findByText(`当前账号：${BAI.username}`)).toBeInTheDocument();
    await joinRoom();
    const wsB = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    expect(wsB).not.toBe(wsA);
    act(() => {
      wsB.open();
      wsB.receive(pollWindow(BAI.username, "p-b", 14));
    });

    // B 的实际命令边界：A 的偏好没有让 B 代发——B 的连接没有任何 command 帧，
    // 弹窗仍在等 B 手动选择，B 的开关是自己的默认值
    expect(commandFrames(wsB)).toHaveLength(0);
    expect(screen.getByText(`是否为 ${TARGET} 挡刀？`)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "默认不挡刀" })).not.toBeChecked();

    // 迟到的 A 帧（A 视角的投票窗口、带 respond-intervention 合法动作、更高修订号）
    // 从 A 的旧连接到达：不得驱动 B 的动作或写入 B 的页面
    act(() => {
      wsA.receive(pollWindow(ALICE.username, "p-a", 99));
    });
    expect(commandFrames(wsB)).toHaveLength(0);
    expect(screen.getByText(`是否为 ${TARGET} 挡刀？`)).toBeInTheDocument();

    // B 自己开启偏好后，才以 B 的身份发出自己的拒绝命令
    fireEvent.click(screen.getByRole("checkbox", { name: "默认不挡刀" }));
    const bCommands = commandFrames(wsB);
    expect(bCommands).toHaveLength(1);
    expect(bCommands[0]).toMatchObject({ command: "respond-intervention", payload: { volunteer: false } });
    expect(localStorage.getItem("bloodbound:account:account-b:no-block")).toBe("1");

    // 回到 A：A 的偏好仍在本设备（A 自己的作用域），A 的窗口继续按 A 的偏好代发
    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
    await screen.findByRole("heading", { name: "登录" });
    await login(BAI.username);
    await screen.findByText(`当前账号：${BAI.username}`);
    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
    await screen.findByRole("heading", { name: "登录" });
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url === "/api/auth/login") return Promise.resolve({ ok: true, json: async () => ({ account: ALICE }) });
      if (url === "/api/account/room") return Promise.resolve({ ok: true, json: async () => ({ room: null }) });
      if (url === "/api/auth/logout") return Promise.resolve({ ok: true, json: async () => ({ account: BAI }) });
      return Promise.resolve({ ok: true, json: async () => ({}) });
    }));
    await login(ALICE.username);
    expect(await screen.findByText(`当前账号：${ALICE.username}`)).toBeInTheDocument();
    await joinRoom();
    const wsA2 = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    act(() => {
      wsA2.open();
      wsA2.receive(pollWindow(ALICE.username, "p-a", 15));
    });
    expect(screen.getByRole("checkbox", { name: "默认不挡刀" })).toBeChecked();
    expect(commandFrames(wsA2)).toEqual([
      expect.objectContaining({ command: "respond-intervention", payload: { volunteer: false } }),
    ]);
    expect(commandFrames(wsB)).toHaveLength(1); // B 的连接没有因 A 回来而多发
  });

  it("V12.04：私有猜测与偏好不出现在命令帧、请求或 URL 中", async () => {
    const calls = stubFetch(authResponses);
    // 本设备上有 A 的备忘角标与偏好（私有猜测，ADR 0004 只存本机）
    localStorage.setItem(
      "bloodbound:account:account-a:memo:123456:game-1",
      JSON.stringify({ "p-target": { color: "rose", mark: "审", touched: true } }),
    );
    localStorage.setItem("bloodbound:account:account-a:no-block", "1");
    localStorage.setItem("bloodbound:account:account-a:no-assist", "1");

    render(<App />);
    await screen.findByText(`当前账号：${ALICE.username}`);
    await joinRoom();
    const wsA = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    act(() => {
      wsA.open();
      wsA.receive(pollWindow(ALICE.username, "p-a", 13));
    });
    // 自动代发立即发生（A 的偏好）；wire 帧只含表态本身，不含任何备忘/偏好字段
    const frames = wsA.sent.map((raw) => JSON.parse(raw));
    const commands = frames.filter((m) => m.type === "command");
    expect(commands).toHaveLength(1);
    expect(commands[0]).toMatchObject({ command: "respond-intervention", payload: { volunteer: false } });
    const serialized = JSON.stringify(frames);
    expect(serialized).not.toContain("memo");
    expect(serialized).not.toContain("no-block");
    expect(serialized).not.toContain("no-assist");
    expect(serialized).not.toContain("审");
    // HTTP 请求 URL 同样不携带私有猜测
    expect(calls.every((call) => !/memo|no-block|no-assist|审/.test(call.url))).toBe(true);
  });
});
