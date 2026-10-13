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
