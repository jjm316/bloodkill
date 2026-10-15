import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { MockWebSocket } from "./joinFailure.test";
import type { GameState, PlayerView, RoomState } from "./types";

// 工单 17（V11.01/V11.02/V11.04/V11.05 前端行为）：邀请链接 ?room= 深链——
// 未登录者登录/注册成功后自动进入目标房；目标在表单切换、密码错误重试与
// 刷新期间保留；占用/锁定/开局/满员/结束/不存在/超时逐项给出中文反馈、
// 可取消邀请回大厅（取消后刷新不再自动进房）、可返回原房，不自动转旁观；
// 旧式 name/token 参数只承接房号，hello 不携带旧身份字段。

const INVITE_CODE = "123456";
const ORIGINAL_CODE = "654321";

function openInvite(query = `room=${INVITE_CODE}`) {
  window.history.replaceState(null, "", `/?${query}`);
}

function stateAs(viewerName: string, code: string): RoomState {
  const self: PlayerView = {
    playerId: "p-self", seat: 0, displayName: viewerName, damage: 0, captured: false,
    holdsCurseCard: false, revealed: { markers: [null, null] }, identityMarkers: [null, null], resources: {},
  };
  const host: PlayerView = { ...self, playerId: "p-host", seat: 1, displayName: "阿玫" };
  const game: GameState = {
    gameId: "game-1", revision: 0, status: "setup", players: [self, host], daggerHolderId: null,
    phase: { kind: "action" }, pending: null, result: null, viewer: null, legalActions: [],
  };
  return {
    type: "state", roomCode: code, roomStatus: "waiting", locked: false, isHost: false,
    yourPlayerId: "p-self", hostPlayerId: "p-host", connected: { "p-self": true, "p-host": true },
    hostActions: [], game, serverTime: 0,
  };
}

type RouteHandler = () => { ok: boolean; status?: number; json: () => Promise<unknown> };

function stubFetch(responses: Record<string, RouteHandler>) {
  const fetcher = vi.fn((url: string) => {
    const handler = responses[url];
    if (!handler) return Promise.resolve({ ok: true, json: async () => ({}) });
    return Promise.resolve(handler());
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

const sessionDown: RouteHandler = () => ({ ok: false, status: 401, json: async () => ({}) });
const accountOf = (username: string): RouteHandler => () => ({
  ok: true, json: async () => ({ account: { accountId: `acc-${username}`, username } }),
});

/** 未登录打开邀请后的登录页；默认登录成功返回“白桦”。 */
async function renderLoginInvite(username = "白桦", responses: Record<string, RouteHandler> = {}) {
  stubFetch({
    "/api/auth/session": sessionDown,
    "/api/auth/login": accountOf(username),
    ...responses,
  });
  const view = render(<App />);
  await screen.findByRole("heading", { name: "登录" });
  return view;
}

function fillLogin(username = "白桦", password = "123456") {
  fireEvent.change(screen.getByLabelText("用户名"), { target: { value: username } });
  fireEvent.change(screen.getByLabelText("密码"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "登录并进入大厅" }));
}

function lastSocket() {
  return MockWebSocket.instances[MockWebSocket.instances.length - 1];
}

describe("邀请链接深链（工单 17）", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState(null, "", "/");
  });

  it("未登录打开邀请：登录页提示目标，登录成功后自动进入目标房且身份是当前账号", async () => {
    openInvite();
    await renderLoginInvite();
    expect(screen.getByText(`登录或注册后将自动进入房间 ${INVITE_CODE}。`)).toBeInTheDocument();
    fillLogin();
    expect(await screen.findByText("当前账号：白桦")).toBeInTheDocument();
    const ws = lastSocket();
    expect(ws).toBeDefined();
    expect(ws.url).toContain(`/ws/${INVITE_CODE}`);
    act(() => { ws.open(); });
    const hello = JSON.parse(ws.sent[0]);
    expect(hello).toMatchObject({ type: "hello", mode: "player", protocolVersion: "4" });
    act(() => { ws.receive(stateAs("白桦", INVITE_CODE)); });
    expect(screen.getByText(/等待玩家加入/)).toBeInTheDocument();
    const rosterSelf = screen.getByText((content, element) => element?.tagName === "LI" && content.startsWith("白桦"));
    expect(rosterSelf.textContent).toContain("（你）");
  });

  it("登录/注册表单来回切换不丢目标：注册成功后进入同一目标房", async () => {
    openInvite();
    stubFetch({ "/api/auth/session": sessionDown, "/api/auth/register": accountOf("新朋友") });
    render(<App />);
    await screen.findByRole("heading", { name: "登录" });
    fireEvent.click(screen.getByRole("button", { name: "注册账号" }));
    expect(await screen.findByRole("heading", { name: "注册账号" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回登录" }));
    fireEvent.click(screen.getByRole("button", { name: "注册账号" }));
    expect(screen.getByText(`登录或注册后将自动进入房间 ${INVITE_CODE}。`)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "新朋友" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "123456" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "注册并进入大厅" }));
    expect(await screen.findByText("当前账号：新朋友")).toBeInTheDocument();
    expect(lastSocket().url).toContain(`/ws/${INVITE_CODE}`);
  });

  it("密码错误再试成功后仍进入同一目标房", async () => {
    openInvite();
    const fetcher = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: false, json: async () => ({ message: "账号或密码不正确，请重新输入。" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ account: { accountId: "acc-白桦", username: "白桦" } }) });
    vi.stubGlobal("fetch", fetcher);
    render(<App />);
    await screen.findByRole("heading", { name: "登录" });
    fillLogin();
    expect(await screen.findByRole("alert")).toHaveTextContent("账号或密码不正确");
    fillLogin();
    expect(await screen.findByText("当前账号：白桦")).toBeInTheDocument();
    expect(lastSocket().url).toContain(`/ws/${INVITE_CODE}`);
  });

  it("已登录打开邀请：会话恢复后直接进入目标房", async () => {
    openInvite();
    stubFetch({ "/api/auth/session": accountOf("白桦") });
    render(<App />);
    expect(await screen.findByText("当前账号：白桦")).toBeInTheDocument();
    const ws = lastSocket();
    expect(ws.url).toContain(`/ws/${INVITE_CODE}`);
    act(() => { ws.open(); ws.receive(stateAs("白桦", INVITE_CODE)); });
    expect(screen.getByText(/等待玩家加入/)).toBeInTheDocument();
  });

  it.each(["room=12345", "room=abcdef", "room=1234567"])(
    "非法房号参数 %s 不触发自动进房，登录后回大厅",
    async (query) => {
      openInvite(query);
      await renderLoginInvite();
      fillLogin();
      expect(await screen.findByRole("button", { name: "创建房间" })).toBeInTheDocument();
      expect(MockWebSocket.instances).toHaveLength(0);
    },
  );

  it("旧式链接携带姓名与令牌：只承接房号，进入的是自己的座位且 hello 不带旧字段", async () => {
    openInvite(`room=${INVITE_CODE}&name=${encodeURIComponent("阿玫")}&token=legacy-secret`);
    await renderLoginInvite();
    fillLogin();
    expect(await screen.findByText("当前账号：白桦")).toBeInTheDocument();
    const ws = lastSocket();
    expect(ws.url).toContain(`/ws/${INVITE_CODE}`);
    act(() => { ws.open(); });
    const hello = JSON.parse(ws.sent[0]);
    expect(hello).not.toHaveProperty("name");
    expect(hello).not.toHaveProperty("token");
    act(() => { ws.receive(stateAs("白桦", INVITE_CODE)); });
    // URL 中的 name=阿玫 不认领身份：名册里（你）在白桦座位上，阿玫是房主
    const rosterSelf = screen.getByText((content, element) => element?.tagName === "LI" && content.startsWith("白桦"));
    expect(rosterSelf.textContent).toContain("（你）");
    const rosterHost = screen.getByText((content, element) => element?.tagName === "LI" && content.startsWith("阿玫"));
    expect(rosterHost.textContent).not.toContain("（你）");
  });

  it("已有其他未结束房间：占用拒绝提示原因并提供返回原房与取消邀请；取消后刷新不再自动进目标房", async () => {
    openInvite();
    const view = await renderLoginInvite("白桦", {
      "/api/account/room": () => ({ ok: true, json: async () => ({ room: { code: ORIGINAL_CODE, status: "waiting" } }) }),
    });
    fillLogin();
    expect(await screen.findByText("当前账号：白桦")).toBeInTheDocument();
    const ws = lastSocket();
    act(() => {
      ws.open();
      ws.receive({ type: "error", code: "account.room-occupied", message: "你已有未结束房间，请返回原房间。", details: { roomCode: ORIGINAL_CODE } });
      ws.drop();
    });
    expect(screen.getByRole("heading", { name: "无法加入房间" })).toBeInTheDocument();
    expect(screen.getByText("你已有未结束房间，请返回原房间。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: `返回房间 ${ORIGINAL_CODE}` })).toBeInTheDocument();
    // 取消邀请（返回大厅）：邀请目标从地址栏清除
    fireEvent.click(screen.getByRole("button", { name: "返回大厅" }));
    expect(await screen.findByRole("button", { name: "创建房间" })).toBeInTheDocument();
    expect(window.location.search).toBe("");
    // 取消后刷新（同地址重新挂载）：会话恢复回大厅，不再自动进目标房
    const connections = MockWebSocket.instances.length;
    view.unmount();
    stubFetch({
      "/api/auth/session": accountOf("白桦"),
      "/api/account/room": () => ({ ok: true, json: async () => ({ room: { code: ORIGINAL_CODE, status: "waiting" } }) }),
    });
    render(<App />);
    expect(await screen.findByRole("button", { name: "创建房间" })).toBeInTheDocument();
    expect(MockWebSocket.instances).toHaveLength(connections);
  });

  it("占用拒绝后选择返回原房：直接进入原房且邀请目标被清除", async () => {
    openInvite();
    await renderLoginInvite("白桦", {
      "/api/account/room": () => ({ ok: true, json: async () => ({ room: { code: ORIGINAL_CODE, status: "waiting" } }) }),
    });
    fillLogin();
    expect(await screen.findByText("当前账号：白桦")).toBeInTheDocument();
    const ws = lastSocket();
    act(() => {
      ws.open();
      ws.receive({ type: "error", code: "account.room-occupied", message: "你已有未结束房间，请返回原房间。", details: { roomCode: ORIGINAL_CODE } });
      ws.drop();
    });
    fireEvent.click(screen.getByRole("button", { name: `返回房间 ${ORIGINAL_CODE}` }));
    const original = lastSocket();
    expect(original).not.toBe(ws);
    expect(original.url).toContain(`/ws/${ORIGINAL_CODE}`);
    act(() => { original.open(); original.receive(stateAs("白桦", ORIGINAL_CODE)); });
    expect(screen.getByText(/等待玩家加入/)).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });

  it.each([
    ["room.not-found", "房间不存在，请核对房间号。"],
    ["room.locked", "房间已锁定。"],
    ["room.already-started", "游戏已经开始。"],
    ["room.full", "房间已满员（12 人），不能加入。"],
    ["room.ended", "对局已结束，不能加入；可观看回放。"],
  ])("目标不可加入（%s）：中文原因与返回大厅，不自动转旁观", async (code, text) => {
    openInvite();
    await renderLoginInvite();
    fillLogin();
    expect(await screen.findByText("当前账号：白桦")).toBeInTheDocument();
    const ws = lastSocket();
    act(() => {
      ws.open();
      ws.receive({ type: "error", code, message: text, details: {} });
      ws.drop();
    });
    expect(screen.getByRole("heading", { name: "无法加入房间" })).toBeInTheDocument();
    expect(screen.getByText(text)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "返回大厅" })).toBeInTheDocument();
    // 不自动转旁观：尝试过的每条连接都是 player 模式
    for (const socket of MockWebSocket.instances) {
      expect(JSON.parse(socket.sent[0] ?? "{}")).toMatchObject({ mode: "player" });
    }
    fireEvent.click(screen.getByRole("button", { name: "返回大厅" }));
    expect(await screen.findByRole("button", { name: "创建房间" })).toBeInTheDocument();
  });

  it("请求超时：邀请路径 10 秒无应答显示连接超时并可返回大厅", async () => {
    vi.useFakeTimers();
    try {
      openInvite();
      const fetcher = vi.fn()
        .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) })
        .mockResolvedValueOnce({ ok: true, json: async () => ({ account: { accountId: "acc-白桦", username: "白桦" } }) });
      vi.stubGlobal("fetch", fetcher);
      render(<App />);
      await act(async () => {});
      fillLogin();
      await act(async () => {});
      expect(screen.getByText("当前账号：白桦")).toBeInTheDocument();
      const ws = lastSocket();
      act(() => { ws.open(); });
      act(() => { vi.advanceTimersByTime(10_000); });
      expect(screen.getByRole("heading", { name: "无法加入房间" })).toBeInTheDocument();
      expect(screen.getByText(/连接超时/)).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "返回大厅" }));
      expect(screen.getByRole("button", { name: "创建房间" })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
