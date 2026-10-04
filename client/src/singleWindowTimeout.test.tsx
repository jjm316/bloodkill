import { fireEvent, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { describeEvent, SingleWindowLayer, WaitingRoom } from "./GameScreen";
import type { GameState, PlayerView, RoomState } from "./types";

// 单人窗口超时（ADR 0011 / issue 05）：开局配置、等待横幅、事件日志标注。

function makePlayer(id: string, name: string, seat: number): PlayerView {
  return {
    playerId: id,
    seat,
    displayName: name,
    damage: 0,
    captured: false,
    revealed: { markers: [null, null] },
    identityMarkers: [null, null],
    resources: {},
  };
}

function makeGame(pending: GameState["pending"], players: PlayerView[]): GameState {
  return {
    gameId: "game-1",
    revision: 10,
    status: "active",
    players,
    daggerHolderId: players[0]?.playerId ?? null,
    phase: { kind: "reveal" },
    pending,
    result: null,
    viewer: null,
    legalActions: [],
  };
}

function makeRoomState(players: PlayerView[], overrides: Partial<RoomState> = {}): RoomState {
  return {
    type: "state",
    roomCode: "123456",
    roomStatus: "waiting",
    locked: false,
    isHost: true,
    yourPlayerId: players[0]?.playerId ?? null,
    hostPlayerId: players[0]?.playerId ?? null,
    connected: {},
    hostActions: [],
    game: makeGame(null, players),
    serverTime: 0,
    ...overrides,
  };
}

describe("WaitingRoom 单人窗口超时配置", () => {
  const sendHost = vi.fn();

  beforeEach(() => {
    sendHost.mockClear();
  });

  it("房主开始游戏时同时上送干涉与单人窗口两份时限", () => {
    const players = Array.from({ length: 6 }, (_, i) => makePlayer(`p${i}`, `P${i}`, i));
    const { container } = render(<WaitingRoom state={makeRoomState(players)} sendHost={sendHost} spectating={false} />);
    const single = container.querySelector<HTMLSelectElement>("#single-window-timeout");
    expect(single).not.toBeNull();
    fireEvent.change(single!, { target: { value: "120" } });
    fireEvent.click(container.querySelector<HTMLButtonElement>("button:not([disabled])")!);
    expect(sendHost).toHaveBeenCalledWith("start", { interventionTimeoutSeconds: 90, singleWindowTimeoutSeconds: 120 });
  });

  it("提示句对非房主展示对局内固定值", () => {
    const players = [makePlayer("p0", "阿玫", 0)];
    const { container } = render(
      <WaitingRoom
        state={makeRoomState(players, { isHost: false, game: makeGame(null, players) })}
        sendHost={sendHost}
        spectating={false}
      />
    );
    const hint = container.querySelector("p.hint");
    expect(hint?.textContent).toContain("单人窗口超时固定为 90 秒");
  });
});

describe("SingleWindowLayer 等待横幅", () => {
  const players = [makePlayer("p0", "阿玫", 0), makePlayer("p1", "小兽", 1)];

  it("亮牌窗口：显示等待对象、倒计时与超时默认说明", () => {
    const serverTime = Date.now() / 1000;
    const game = makeGame({ kind: "reveal", actorPlayerId: "p1", targetPlayerId: "p1", eligiblePlayerIds: [], rank: null, trigger: null, deadline: serverTime + 30 }, players);
    const { container } = render(<SingleWindowLayer game={game} serverTime={serverTime} />);
    const banner = container.querySelector(".waiting-banner");
    expect(banner?.textContent).toContain("等待 小兽 亮出线索（剩 30 秒）");
    expect(banner?.textContent).toContain("超时将自动亮出排序第一张标记");
  });

  it("技能与退牌窗口各有对应文案", () => {
    const serverTime = Date.now() / 1000;
    const skillGame = makeGame({ kind: "skill", actorPlayerId: "p1", targetPlayerId: "p1", eligiblePlayerIds: [], rank: 2, trigger: "attack", deadline: serverTime + 90 }, players);
    const { container: skillContainer, unmount } = render(<SingleWindowLayer game={skillGame} serverTime={serverTime} />);
    expect(skillContainer.querySelector(".waiting-banner")?.textContent).toContain("决定是否使用技能");
    expect(skillContainer.querySelector(".waiting-banner")?.textContent).toContain("超时视为放弃技能");
    unmount();
    const returnGame = makeGame({ kind: "token-return", actorPlayerId: "p1", targetPlayerId: "p1", eligiblePlayerIds: ["marker-0"], rank: null, trigger: null, deadline: serverTime + 90 }, players);
    const { container } = render(<SingleWindowLayer game={returnGame} serverTime={serverTime} />);
    expect(container.querySelector(".waiting-banner")?.textContent).toContain("归还标记");
    expect(container.querySelector(".waiting-banner")?.textContent).toContain("超时将自动退回排序第一张已亮标记");
  });

  it("干涉窗口（poll 与 gate 两阶段）与无窗口时不渲染", () => {
    const serverTime = Date.now() / 1000;
    const interventionGame = makeGame({ kind: "intervention", actorPlayerId: "p0", targetPlayerId: "p0", eligiblePlayerIds: [], rank: null, trigger: null, deadline: serverTime + 90 }, players);
    const { container, unmount } = render(<SingleWindowLayer game={interventionGame} serverTime={serverTime} />);
    expect(container.querySelector(".waiting-banner")).toBeNull();
    unmount();
    // 门控阶段（ADR 0012）同样是 intervention pending：单人窗口层不得抢渲染，
    // 门控弹窗/横幅由 InterventionGateLayer 承载（互斥关系的另一半）。
    const gateGame = makeGame({ kind: "intervention", actorPlayerId: "p0", targetPlayerId: "p0", eligiblePlayerIds: [], rank: null, trigger: null, stage: "gate", deadline: serverTime + 90 }, players);
    const { container: gateContainer } = render(<SingleWindowLayer game={gateGame} serverTime={serverTime} />);
    expect(gateContainer.querySelector(".waiting-banner")).toBeNull();
    unmount();
    const { container: empty } = render(<SingleWindowLayer game={makeGame(null, players)} serverTime={serverTime} />);
    expect(empty.querySelector(".waiting-banner")).toBeNull();
  });
});

describe("describeEvent 超时自动标注", () => {
  const players = [makePlayer("p1", "阿玫", 0)];
  const event = (eventType: string, payload: Record<string, unknown>) => ({
    eventId: "g:1",
    eventType,
    gameId: "g",
    revision: 1,
    timestamp: 0,
    commandId: "c",
    payload,
  });

  it("reason=timeout 的亮牌/放弃/归还事件带（超时自动）后缀", () => {
    expect(describeEvent(event("ClueRevealed", { playerId: "p1", kind: "marker-0", value: "unknown", reason: "timeout" }), players)).toBe("阿玫 展示了身份线索（超时自动）");
    expect(describeEvent(event("SkillDeclined", { playerId: "p1", rank: 2, reason: "timeout" }), players)).toBe("阿玫 放弃了技能（超时自动）");
    expect(describeEvent(event("TokenReturned", { playerId: "p1", token: "marker-0", reason: "timeout" }), players)).toBe("阿玫 归还了身份标记（超时自动）");
  });

  it("玩家主动操作的事件不带后缀", () => {
    expect(describeEvent(event("ClueRevealed", { playerId: "p1", kind: "rank", value: 3 }), players)).toBe("阿玫 展示了等级线索");
    expect(describeEvent(event("SkillDeclined", { playerId: "p1", rank: 2 }), players)).toBe("阿玫 放弃了技能");
  });
});
