import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";

afterEach(() => vi.unstubAllGlobals());

it("默认登录可切注册；提交中不能重复注册，成功显示账号并进入大厅", async () => {
  let finish: (value: unknown) => void = () => {};
  const pending = new Promise((resolve) => { finish = resolve; });
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: false, status: 401 }).mockReturnValueOnce(pending);
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  expect(await screen.findByRole("heading", { name: "登录" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "创建房间" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "注册账号" }));
  fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "中文Alice" } });
  fireEvent.change(screen.getByLabelText("密码"), { target: { value: " Ab12 " } });
  fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: " Ab12 " } });
  fireEvent.click(screen.getByRole("button", { name: "注册并进入大厅" }));
  expect(screen.getByRole("button", { name: "正在提交……" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "正在提交……" }));
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ username: "中文Alice", password: " Ab12 ", confirmPassword: " Ab12 " });
  await act(async () => finish({ ok: true, json: async () => ({ account: { accountId: "account-1", username: "中文Alice" } }) }));
  expect(await screen.findByText("当前账号：中文Alice")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "创建房间" })).toBeInTheDocument();
});

it("注册失败给中文反馈，保留输入并可纠正后重试", async () => {
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce({ ok: false, status: 401 })
    .mockResolvedValueOnce({ ok: false, json: async () => ({ message: "用户名已被使用，请换一个用户名。" }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ account: { accountId: "new-account", username: "新的名字" } }) }));
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "注册账号" }));
  fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "重复名字" } });
  for (const label of ["密码", "确认密码"]) fireEvent.change(screen.getByLabelText(label), { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: "注册并进入大厅" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("用户名已被使用");
  expect(screen.getByLabelText("用户名")).toHaveValue("重复名字");
  fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "新的名字" } });
  fireEvent.click(screen.getByRole("button", { name: "注册并进入大厅" }));
  expect(await screen.findByText("当前账号：新的名字")).toBeInTheDocument();
});

it("登录表单支持自动填充和显隐，切换注册再返回登录清除密码且不带入身份", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 401 });
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  await screen.findByRole("heading", { name: "登录" });
  expect(screen.getByLabelText("用户名")).toHaveAttribute("autocomplete", "username");
  expect(screen.getByLabelText("密码")).toHaveAttribute("autocomplete", "current-password");
  fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "Alice" } });
  fireEvent.change(screen.getByLabelText("密码"), { target: { value: " Ab12 " } });
  fireEvent.click(screen.getByRole("button", { name: "显示密码" }));
  expect(screen.getByLabelText("密码")).toHaveAttribute("type", "text");
  fireEvent.click(screen.getByRole("button", { name: "注册账号" }));
  expect(screen.getByLabelText("密码")).toHaveValue("");
  expect(screen.getByLabelText("密码")).toHaveAttribute("type", "password");
  expect(screen.getByLabelText("密码")).toHaveAttribute("autocomplete", "new-password");
  fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "other!" } });
  fireEvent.click(screen.getByRole("button", { name: "返回登录" }));
  expect(screen.getByLabelText("密码")).toHaveValue("");
  expect(screen.queryByLabelText("确认密码")).not.toBeInTheDocument();
  expect(screen.queryByText(/当前账号/)).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("登录失败可纠正后重试，提交中阻止重复请求并显示原注册写法", async () => {
  let finish: (value: unknown) => void = () => {};
  const pending = new Promise(resolve => { finish = resolve; });
  const fetcher = vi.fn()
    .mockResolvedValueOnce({ ok: false, status: 401 })
    .mockResolvedValueOnce({ ok: false, json: async () => ({ message: "账号或密码不正确，请重新输入。" }) })
    .mockReturnValueOnce(pending);
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  await screen.findByRole("heading", { name: "登录" });
  fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "ALICE" } });
  fireEvent.change(screen.getByLabelText("密码"), { target: { value: "wrong!" } });
  const form = screen.getByLabelText("密码").closest("form")!;
  fireEvent.submit(form);
  expect(await screen.findByRole("alert")).toHaveTextContent("账号或密码不正确");
  expect(screen.queryByText(/当前账号/)).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("密码"), { target: { value: " Ab12 " } });
  fireEvent.submit(form);
  fireEvent.submit(form);
  expect(screen.getByRole("button", { name: "正在提交……" })).toBeDisabled();
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(fetcher.mock.calls[2][0]).toBe("/api/auth/login");
  expect(JSON.parse(fetcher.mock.calls[2][1].body)).toEqual({ username: "ALICE", password: " Ab12 " });
  await act(async () => finish({ ok: true, json: async () => ({ account: { accountId: "alice-account", username: "Alice" } }) }));
  expect(await screen.findByText("当前账号：Alice")).toBeInTheDocument();
});
