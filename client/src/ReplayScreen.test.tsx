import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ReplayScreen } from "./ReplayScreen";

afterEach(() => vi.unstubAllGlobals());

async function loadReplay() {
  const view = render(<ReplayScreen onBack={vi.fn()} />);
  fireEvent.change(screen.getByPlaceholderText("6位数字房间号"), { target: { value: "123456" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "加载回放" })); });
  return view;
}

// 工单 23：回放要求登录。未登录/失效会话给出重新登录引导；
// 服务端拒绝原因（未终局/未知房）原样以简体中文显示，不回退到笼统失败文案。
it("未登录或登录已失效时给出重新登录引导，而不是笼统失败", async () => {
  const fetcher = vi.fn().mockResolvedValue({
    ok: false, status: 401,
    json: async () => ({ type: "error", code: "auth.login-required", message: "请先登录后再观看回放。", details: {} }),
  });
  vi.stubGlobal("fetch", fetcher);
  await loadReplay();
  expect(screen.getByRole("alert")).toHaveTextContent("登录已失效，请刷新页面重新登录后再观看回放。");
  expect(fetcher).toHaveBeenCalledWith("/api/rooms/123456/replay", { credentials: "same-origin" });
});

it("对局尚未正常结束时显示服务端中文原因", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: false, status: 409,
    json: async () => ({ type: "error", code: "room.not-ended", message: "该对局尚未正常结束，暂无完整回放。", details: {} }),
  }));
  await loadReplay();
  expect(screen.getByRole("alert")).toHaveTextContent("该对局尚未正常结束，暂无完整回放。");
});

it("房间不存在时显示服务端中文原因", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: false, status: 404,
    json: async () => ({ type: "error", code: "room.not-found", message: "房间不存在，请核对房间号。", details: {} }),
  }));
  await loadReplay();
  expect(screen.getByRole("alert")).toHaveTextContent("房间不存在，请核对房间号。");
});
