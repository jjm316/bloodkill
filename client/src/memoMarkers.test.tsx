import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useMemoMarkers } from "./memoMarkers";
import type { GameState } from "./types";

const ROOM = "366673";

function gameWith(gameId: string | null, clue?: { playerId: string; icon: string | null } | null): GameState | null {
  if (!gameId) return null;
  return {
    gameId,
    revision: 1,
    status: "active",
    players: [],
    daggerHolderId: null,
    phase: { kind: "action" },
    pending: null,
    result: null,
    viewer: {
      playerId: "me",
      identity: { faction: "beast", rank: 7 },
      identityMarkers: [],
      resources: {},
      skillsUsed: [],
      inspections: {},
      cursesToDistribute: [],
      clueIcon: null,
      seenNeighbourClue: clue ?? null,
    },
    legalActions: [],
  } as GameState;
}

describe("useMemoMarkers", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("自动填充右邻徽记颜色：只填色不填数、未动过", () => {
    const { result, rerender } = renderHook(({ game }) => useMemoMarkers(ROOM, game), {
      initialProps: { game: gameWith("g1") },
    });
    rerender({ game: gameWith("g1", { playerId: "p7", icon: "beast" }) });
    expect(result.current.markers["p7"]).toEqual({ color: "beast", touched: false });
  });

  it("无法判色的徽记（null）不自动填充", () => {
    const { result, rerender } = renderHook(({ game }) => useMemoMarkers(ROOM, game), {
      initialProps: { game: gameWith("g1") },
    });
    rerender({ game: gameWith("g1", { playerId: "p7", icon: null }) });
    expect(result.current.markers).toEqual({});
  });

  it("清空后本局不再被自动重填（Q9 粘性）", () => {
    const { result, rerender } = renderHook(({ game }) => useMemoMarkers(ROOM, game), {
      initialProps: { game: gameWith("g1") },
    });
    rerender({ game: gameWith("g1", { playerId: "p7", icon: null }) });
    act(() => result.current.clear("p7"));
    rerender({ game: gameWith("g1", { playerId: "p7", icon: "beast" }) });
    expect(result.current.markers["p7"]).toEqual({ touched: true });
  });

  it("换局清空后即使右邻与徽记色与上局相同也重新自动填充", () => {
    const { result, rerender } = renderHook(({ game }) => useMemoMarkers(ROOM, game), {
      initialProps: { game: gameWith("g1") },
    });
    rerender({ game: gameWith("g1", { playerId: "p7", icon: "beast" }) });
    expect(result.current.markers["p7"]).toEqual({ color: "beast", touched: false });
    rerender({ game: gameWith("g2", { playerId: "p7", icon: "beast" }) });
    expect(result.current.markers["p7"]).toEqual({ color: "beast", touched: false });
  });

  it("只选数字时颜色灰兜底，已有颜色则保留（Q8）", () => {
    const { result } = renderHook(() => useMemoMarkers(ROOM, gameWith("g1")));
    act(() => result.current.change("p3", { mark: 5 }));
    expect(result.current.markers["p3"]).toMatchObject({ color: "gray", mark: 5 });
    act(() => result.current.change("p3", { color: "rose" }));
    expect(result.current.markers["p3"]).toMatchObject({ color: "rose", mark: 5 });
    act(() => result.current.change("p3", { mark: "审" }));
    expect(result.current.markers["p3"]).toMatchObject({ color: "rose", mark: "审" });
  });

  it("备忘按房间+对局落盘，重挂载读回", () => {
    const { result, unmount } = renderHook(() => useMemoMarkers(ROOM, gameWith("g1")));
    act(() => result.current.change("p2", { color: "rose", mark: "审" }));
    unmount();
    const reopened = renderHook(() => useMemoMarkers(ROOM, gameWith("g1")));
    expect(reopened.result.current.markers["p2"]).toEqual({ color: "rose", mark: "审", touched: true });
  });

  it("gameId 变化清空备忘并删除旧局存储", () => {
    const { result, rerender } = renderHook(({ game }) => useMemoMarkers(ROOM, game), {
      initialProps: { game: gameWith("g1") },
    });
    act(() => result.current.change("p2", { color: "rose" }));
    expect(localStorage.getItem(`bloodbound:memo:${ROOM}:g1`)).not.toBeNull();
    rerender({ game: gameWith("g2") });
    expect(result.current.markers).toEqual({});
    expect(localStorage.getItem(`bloodbound:memo:${ROOM}:g1`)).toBeNull();
  });
});
