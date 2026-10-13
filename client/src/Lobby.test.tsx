import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Lobby } from "./Lobby";

afterEach(() => vi.unstubAllGlobals());

it("创建回复丢失后查询真实归属并提供原房恢复入口，重复点击不再创建", async () => {
  let fail: (reason: unknown) => void = () => {};
  const pending = new Promise((_resolve, reject) => { fail = reject; });
  const fetcher = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ room: null }) })
    .mockReturnValueOnce(pending)
    .mockResolvedValueOnce({ ok: true, json: async () => ({ room: { code: "123456", status: "waiting" } }) });
  vi.stubGlobal("fetch", fetcher);
  const onJoin = vi.fn();
  render(<Lobby account={{ accountId: "real-account", username: "房主小明" }} onJoin={onJoin} onReplay={() => {}} />);
  const create = screen.getByRole("button", { name: "创建房间" });
  fireEvent.click(create);
  fireEvent.click(create);
  expect(create).toBeDisabled();
  fail(new Error("reply lost"));
  expect(await screen.findByRole("button", { name: "返回房间 123456" })).toBeInTheDocument();
  expect(fetcher.mock.calls.filter(call => call[1]?.method === "POST")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "返回房间 123456" }));
  expect(onJoin).toHaveBeenCalledWith({ code: "123456", accountId: "real-account", mode: "player" });
});

// 工单 10：大厅输入六位房号加入房间；非六位输入给中文提示且不发起加入。
it("输入六位房号加入房间；非六位输入给中文提示不发起", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ room: null }) }));
  const onJoin = vi.fn();
  render(<Lobby account={{ accountId: "joiner-account", username: "加入玩家" }} onJoin={onJoin} onReplay={() => {}} />);
  const input = screen.getByLabelText("房间号");
  fireEvent.change(input, { target: { value: "12345" } });
  fireEvent.click(screen.getByRole("button", { name: "加入房间" }));
  expect(screen.getByRole("alert")).toHaveTextContent("请输入六位数字房间号。");
  expect(onJoin).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: "加入房间" }));
  expect(onJoin).toHaveBeenCalledTimes(1);
  expect(onJoin).toHaveBeenCalledWith({ code: "123456", accountId: "joiner-account", mode: "player" });
  fireEvent.change(input, { target: { value: "1234567" } });
  expect(screen.getByLabelText("房间号")).toHaveValue("123456");
});
