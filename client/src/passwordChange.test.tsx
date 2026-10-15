import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { Account } from "./AccountEntry";

// 工单 15（V09 前端行为）：当前账号行提供修改密码入口；表单验证旧密码并设置
// 新密码与确认（回车提交、防重复提交、中文反馈）；旧密码错误不改变当前登录；
// 成功后本机保持登录并提示其他设备需重新登录；密码不进 URL 或本地存储。

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
}

const ALICE: Account = { accountId: "account-a", username: "阿玫" };

/** 按 URL 回放固定响应的 fetch mock；calls 记录 url/method/body 供断言。 */
function stubFetch(responses: Record<string, (init?: RequestInit) => { ok: boolean; json: () => Promise<unknown> }>) {
  const calls: { url: string; method: string; body?: string }[] = [];
  const fetcher = vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET", body: typeof init?.body === "string" ? init.body : undefined });
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

function openForm() {
  fireEvent.click(screen.getByRole("button", { name: "修改密码" }));
}

function fillPasswordForm(oldPassword: string, newPassword: string, confirmation: string) {
  fireEvent.change(screen.getByLabelText("旧密码"), { target: { value: oldPassword } });
  fireEvent.change(screen.getByLabelText("新密码"), { target: { value: newPassword } });
  fireEvent.change(screen.getByLabelText("确认新密码"), { target: { value: confirmation } });
}

function passwordPosts(calls: { url: string; method: string; body?: string }[]) {
  return calls.filter((call) => call.url === "/api/auth/password" && call.method === "POST");
}

/** 本地存储（偏好等）任何键值都不得包含明文密码。 */
function assertNoPasswordInLocalStorage(passwords: string[]) {
  for (let index = 0; index < window.localStorage.length; index += 1) {
    const key = window.localStorage.key(index)!;
    const value = window.localStorage.getItem(key) ?? "";
    for (const password of passwords) {
      expect(`${key}=${value}`).not.toContain(password);
    }
  }
}

describe("修改密码（工单 15）", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    window.localStorage.clear();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("大厅与房间内提供修改密码入口；表单回车提交成功后本机保持登录并清空密码", async () => {
    const calls = stubFetch({
      "/api/auth/session": () => ({ ok: true, json: async () => ({ account: ALICE }) }),
      "/api/account/room": () => ({ ok: true, json: async () => ({ room: null }) }),
      "/api/auth/password": () => ({ ok: true, json: async () => ({ account: ALICE }) }),
    });
    await restoreAs(ALICE);
    openForm();
    // 自动填充属性：旧密码按当前密码、新密码按新密码填写
    expect(screen.getByLabelText("旧密码")).toHaveAttribute("autocomplete", "current-password");
    expect(screen.getByLabelText("新密码")).toHaveAttribute("autocomplete", "new-password");
    expect(screen.getByLabelText("确认新密码")).toHaveAttribute("autocomplete", "new-password");
    fillPasswordForm("123456", "654321", "654321");
    // 回车提交（原生表单提交路径）
    fireEvent.submit(screen.getByLabelText("旧密码").closest("form")!);
    await waitFor(() => {
      expect(passwordPosts(calls)).toHaveLength(1);
    });
    expect(JSON.parse(passwordPosts(calls)[0].body!)).toEqual({
      oldPassword: "123456", newPassword: "654321", confirmPassword: "654321",
    });
    // 成功：表单收起并显示中文成功状态；当前登录保留（不回登录页）
    expect(await screen.findByRole("status")).toHaveTextContent("密码已修改");
    expect(screen.getByText(/其他设备需要用新密码重新登录/)).toBeInTheDocument();
    expect(screen.queryByLabelText("旧密码")).not.toBeInTheDocument();
    expect(screen.getByText(`当前账号：${ALICE.username}`)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "登录" })).not.toBeInTheDocument();
    // 重新打开表单：密码字段已清空
    openForm();
    expect(screen.getByLabelText("旧密码")).toHaveValue("");
    expect(screen.getByLabelText("新密码")).toHaveValue("");
    expect(screen.getByLabelText("确认新密码")).toHaveValue("");
    // 密码不进 URL，也不写入本地存储
    expect(calls.every((call) => !call.url.includes("654321") && !call.url.includes("123456"))).toBe(true);
    assertNoPasswordInLocalStorage(["123456", "654321"]);

    // 房间内同样提供修改密码入口（共用当前账号行）
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    fireEvent.change(screen.getByLabelText("房间号"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "加入房间" }));
    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    act(() => {
      ws.open();
      ws.receive({
        type: "state", roomCode: "123456", roomStatus: "waiting", locked: false, isHost: false,
        yourPlayerId: "p-a", hostPlayerId: "p-a", connected: { "p-a": true }, hostActions: [],
        game: null, serverTime: 0,
      });
    });
    expect(screen.getByText(`当前账号：${ALICE.username}`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "修改密码" })).toBeInTheDocument();
  });

  it("旧密码错误给中文反馈且不退出当前登录；提交中防重复；取消不发请求", async () => {
    let finish: (value: unknown) => void = () => {};
    const pending = new Promise((resolve) => { finish = resolve; });
    const passwordHandler = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 400, json: async () => ({ message: "旧密码不正确，请重新输入。" }) })
      .mockReturnValueOnce(pending);
    const calls = stubFetch({
      "/api/auth/session": () => ({ ok: true, json: async () => ({ account: ALICE }) }),
      "/api/account/room": () => ({ ok: true, json: async () => ({ room: null }) }),
      "/api/auth/password": (init?: RequestInit) => passwordHandler(init),
    });
    await restoreAs(ALICE);
    openForm();
    fillPasswordForm("错误旧码", "654321", "654321");
    fireEvent.click(screen.getByRole("button", { name: "确认修改" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("旧密码不正确");
    // 失败保留输入与当前登录，可纠正后重试
    expect(screen.getByLabelText("旧密码")).toHaveValue("错误旧码");
    expect(screen.getByText(`当前账号：${ALICE.username}`)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("旧密码"), { target: { value: "123456" } });
    const form = screen.getByLabelText("旧密码").closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form); // 提交中重复回车/双击不再发第二条
    expect(screen.getByRole("button", { name: "正在修改……" })).toBeDisabled();
    expect(passwordPosts(calls)).toHaveLength(2);
    await act(async () => {
      finish({ ok: true, json: async () => ({ account: ALICE }) });
    });
    expect(await screen.findByRole("status")).toHaveTextContent("密码已修改");
    expect(passwordPosts(calls)).toHaveLength(2);
    assertNoPasswordInLocalStorage(["错误旧码", "123456", "654321"]);

    // 取消：表单收起且不发出请求
    openForm();
    fillPasswordForm("123456", "7654321", "7654321");
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByLabelText("旧密码")).not.toBeInTheDocument();
    expect(passwordPosts(calls)).toHaveLength(2);
    assertNoPasswordInLocalStorage(["7654321"]);
  });
});
