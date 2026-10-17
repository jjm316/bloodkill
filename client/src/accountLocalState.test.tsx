import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EventLog } from "./EventLogView";
import { GameScreen } from "./GameScreen";
import { useMemoMarkers } from "./memoMarkers";
import type { GameEvent, GameState, PlayerView, RoomState } from "./types";

// 工单 18（V12.01–V12.05）：备忘标记、挡刀偏好、日志筛选继续存本设备，但按
// 账号隔离；旧无账号全局键不自动导入；A 的偏好不得让 B 代发自动命令。
// seam：useMemoMarkers / useIntervention / EventLog 公共接口 + 实际命令发送边界
// （send mock / MockWebSocket.sent，断言发送者与内容，不能只看页面值）。

const ROOM = "366673";
const OTHER_ROOM = "366674";

function gameWith(gameId: string | null): GameState | null {
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
    viewer: null,
    legalActions: [],
  } as GameState;
}

describe("备忘按账号隔离（工单 18）", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("V12.01：A 写备忘 → B 打开同房同局不继承，回到 A 记录仍在", () => {
    const alice = renderHook(() => useMemoMarkers("account-a", ROOM, gameWith("g1")));
    act(() => alice.result.current.change("p2", { color: "rose", mark: "审" }));
    alice.unmount();

    const bai = renderHook(() => useMemoMarkers("account-b", ROOM, gameWith("g1")));
    expect(bai.result.current.markers).toEqual({});
    bai.unmount();

    const backToAlice = renderHook(() => useMemoMarkers("account-a", ROOM, gameWith("g1")));
    expect(backToAlice.result.current.markers["p2"]).toEqual({ color: "rose", mark: "审", touched: true });
  });

  it("V12.01：B 活跃期间换局清理只删 B 自己的旧局键，A 的同房备忘保留", () => {
    localStorage.setItem("bloodbound:account:account-a:memo:366673:g1", JSON.stringify({ p2: { color: "rose", touched: true } }));
    const bai = renderHook(({ game }) => useMemoMarkers("account-b", ROOM, game), {
      initialProps: { game: gameWith("g-old") },
    });
    act(() => bai.result.current.change("p9", { color: "beast" }));
    expect(localStorage.getItem("bloodbound:account:account-b:memo:366673:g-old")).not.toBeNull();

    bai.rerender({ game: gameWith("g-new") });
    expect(bai.result.current.markers).toEqual({});
    // B 自己的旧局键被清理，A 的同房同局键不受影响
    expect(localStorage.getItem("bloodbound:account:account-b:memo:366673:g-old")).toBeNull();
    expect(localStorage.getItem("bloodbound:account:account-a:memo:366673:g1")).not.toBeNull();
  });

  it("V12.03：旧的无账号全局备忘键不自动导入新账号；新账号写自己的键", () => {
    localStorage.setItem(`bloodbound:memo:${ROOM}:g1`, JSON.stringify({ p2: { color: "rose", touched: true } }));
    const newcomer = renderHook(() => useMemoMarkers("account-new", ROOM, gameWith("g1")));
    expect(newcomer.result.current.markers).toEqual({});

    act(() => newcomer.result.current.change("p3", { mark: 5 }));
    expect(localStorage.getItem(`bloodbound:memo:${ROOM}:g1`)).toEqual(
      JSON.stringify({ p2: { color: "rose", touched: true } }),
    );
    expect(JSON.parse(localStorage.getItem("bloodbound:account:account-new:memo:366673:g1")!)).toEqual({
      p3: { color: "gray", mark: 5, touched: true },
    });
  });

  it("V12.04：换设备不同步——清空本机存储（模拟新设备）后 A 重进读回空", () => {
    const alice = renderHook(() => useMemoMarkers("account-a", ROOM, gameWith("g1")));
    act(() => alice.result.current.change("p2", { color: "rose" }));
    alice.unmount();
    // 新设备：没有任何原设备的账号键
    localStorage.clear();
    const freshDevice = renderHook(() => useMemoMarkers("account-a", ROOM, gameWith("g1")));
    expect(freshDevice.result.current.markers).toEqual({});
    // 且不会伪装成同步：A 在新设备写的记录不影响原设备（这里原设备已无键可查，
    // 键位隔离即"各设备各记各的"，ADR 0004）
    act(() => freshDevice.result.current.change("p5", { mark: 3 }));
    expect(localStorage.getItem("bloodbound:account:account-a:memo:366673:g1")).not.toBeNull();
  });

  it("V12.03：不同房间不混用备忘（账号 + 房间 + 对局三段作用域）", () => {
    const alice = renderHook(() => useMemoMarkers("account-a", ROOM, gameWith("g1")));
    act(() => alice.result.current.change("p2", { color: "rose" }));
    alice.unmount();

    const otherRoom = renderHook(() => useMemoMarkers("account-a", OTHER_ROOM, gameWith("g1")));
    expect(otherRoom.result.current.markers).toEqual({});
  });
});

// ---- 干预偏好（GameScreen 级，socket mock 同 interventionGate 模式）----

const socketMock = vi.hoisted(() => ({ state: null as RoomState | null, events: [] as GameEvent[], send: vi.fn() }));
vi.mock("./useSocket", () => ({
  useGameSocket: () => ({
    state: socketMock.state,
    events: socketMock.events,
    error: null,
    closed: false,
    reconnecting: false,
    takenOver: false,
    failed: false,
    send: socketMock.send,
    sendHost: vi.fn(),
  }),
}));

function makePlayer(id: string, name: string, seat: number): PlayerView {
  return {
    playerId: id, seat, displayName: name, damage: 0, captured: false, holdsCurseCard: false,
    revealed: { markers: [null, null] }, identityMarkers: [null, null], resources: {},
  };
}

const pollPlayers = [makePlayer("p0", "阿攻", 0), makePlayer("p1", "小标", 1), makePlayer("p2", "小二", 2)];

/** B（你=p2）有 respond-intervention 合法动作的 poll 投票窗口。 */
function makePollState(revision: number): RoomState {
  const game: GameState = {
    gameId: "game-1", revision, status: "active",
    players: pollPlayers, daggerHolderId: "p1",
    phase: { kind: "intervention", stage: "poll", activePlayerId: "p1" },
    pending: {
      kind: "intervention", actorPlayerId: "p1", targetPlayerId: "p1",
      eligiblePlayerIds: ["p2"], rank: null, trigger: null, stage: "poll",
      attackerPlayerId: "p0", responses: {}, deadline: Date.now() / 1000 + 90,
    },
    result: null,
    viewer: { playerId: "p2", identity: { faction: "rose", rank: 5 } } as GameState["viewer"],
    legalActions: [
      { type: "respond-intervention", volunteer: true },
      { type: "respond-intervention", volunteer: false },
    ],
  };
  return {
    type: "state", roomCode: ROOM, roomStatus: "playing", locked: false, isHost: false,
    yourPlayerId: "p2", hostPlayerId: "p0", connected: { p0: true, p1: true, p2: true },
    hostActions: [], game, serverTime: Date.now() / 1000,
  };
}

function renderAs(accountId: string) {
  return render(
    <GameScreen credentials={{ code: ROOM, accountId, mode: "player" }} onLeave={() => {}} />,
  );
}

const autoDeclines = () => socketMock.send.mock.calls.filter((c) => c[0] === "respond-intervention");

describe("干预偏好按账号隔离（工单 18）", () => {
  beforeEach(() => {
    localStorage.clear();
    socketMock.send.mockReset();
    socketMock.events = [];
  });

  it("V12.01/V12.02：A 开启默认不挡刀 → B 在实际 poll 窗口不代发且开关未选；回到 A 仍代发", () => {
    // A 进入 poll 窗口并开启「默认不挡刀」：A 自己的连接发出一次 volunteer:false
    socketMock.state = makePollState(13);
    const alice = renderAs("account-a");
    expect(screen.getByRole("checkbox", { name: "默认不挡刀" })).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: "默认不挡刀" }));
    expect(screen.getByRole("checkbox", { name: "默认不挡刀" })).toBeChecked();
    expect(autoDeclines()).toEqual([["respond-intervention", { volunteer: false }]]);
    alice.unmount();
    socketMock.send.mockReset();

    // 同一浏览器切到 B（App 以 accountId 为 key 重挂载）：同房同窗口
    socketMock.state = makePollState(13);
    const bai = renderAs("account-b");
    // B 的开关是自己的默认值，不继承 A
    expect(screen.getByRole("checkbox", { name: "默认不挡刀" })).not.toBeChecked();
    // B 的实际命令边界：没有任何 respond-intervention 代发，弹窗仍显示等 B 手动选择
    expect(autoDeclines()).toEqual([]);
    expect(socketMock.send).not.toHaveBeenCalled();
    expect(screen.getByText("是否为 小标 挡刀？")).toBeInTheDocument();
    bai.unmount();

    // 回到 A：偏好仍在，A 的窗口继续按 A 的偏好代发
    socketMock.state = makePollState(13);
    renderAs("account-a");
    expect(screen.getByRole("checkbox", { name: "默认不挡刀" })).toBeChecked();
    expect(autoDeclines()).toEqual([["respond-intervention", { volunteer: false }]]);
  });

  it("V12.01：默认不让他人挡刀偏好同样按账号隔离（A 开 → B 不继承不代发）", () => {
    localStorage.setItem("bloodbound:account:account-a:no-assist", "1");
    // B 首次渲染：开关未选，不代发
    socketMock.state = makePollState(13);
    const bai = renderAs("account-b");
    expect(screen.getByRole("checkbox", { name: "默认不让他人挡刀" })).not.toBeChecked();
    expect(socketMock.send).not.toHaveBeenCalled();
    bai.unmount();
    // A 渲染：开关已选（写盘读盘往返成立）
    renderAs("account-a");
    expect(screen.getByRole("checkbox", { name: "默认不让他人挡刀" })).toBeChecked();
  });

  it("V12.03：旧的无账号全局偏好键不自动导入新账号", () => {
    localStorage.setItem("bloodbound:no-block", "1");
    localStorage.setItem("bloodbound:no-assist", "1");
    socketMock.state = makePollState(13);
    renderAs("account-new");
    expect(screen.getByRole("checkbox", { name: "默认不挡刀" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "默认不让他人挡刀" })).not.toBeChecked();
    // 新账号看到的仍是弹窗，且无任何代发
    expect(socketMock.send).not.toHaveBeenCalled();
    expect(screen.getByText("是否为 小标 挡刀？")).toBeInTheDocument();
  });
});

// ---- 日志筛选（V12.05）：阅读偏好按账号隔离，只影响本机显示 ----

const logPlayers = [
  { playerId: "p1", displayName: "阿玫" },
  { playerId: "p2", displayName: "阿兽" },
] as PlayerView[];
const logEvent = (eventType: string, payload: GameEvent["payload"], revision: number): GameEvent => ({
  eventId: `g:${revision}`, eventType, gameId: "g1", revision, timestamp: 0, commandId: `c:${revision}`, payload,
});
const mixedLog = [
  logEvent("AttackDeclared", { attackerPlayerId: "p1", targetPlayerId: "p2" }, 1),
  logEvent("ResourceSpent", { playerId: "p2", resource: "shield" }, 2),
];

function openLog() {
  fireEvent.click(screen.getByText(/^事件日志（/));
}

function renderLog(accountId: string) {
  return render(<EventLog accountId={accountId} events={mixedLog} players={logPlayers} />);
}

describe("日志筛选按账号隔离（工单 18）", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("V12.05：A 屏蔽匕首 → B 全部可见 → 回到 A 筛选恢复，事件事实不变", () => {
    const alice = renderLog("account-a");
    openLog();
    fireEvent.click(screen.getByRole("button", { name: "匕首" }));
    expect(screen.getByRole("button", { name: "匕首" })).toHaveAttribute("aria-pressed", "false");
    alice.unmount();

    const bai = renderLog("account-b");
    openLog();
    expect(screen.getByRole("button", { name: "匕首" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("事件日志（2）")).toBeInTheDocument();
    bai.unmount();

    renderLog("account-a");
    openLog();
    expect(screen.getByRole("button", { name: "匕首" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("事件日志（1）")).toBeInTheDocument();
    // 筛选只影响本机显示：被屏蔽的匕首事件仍是事件流事实，未被改写
    expect(mixedLog[0].eventType).toBe("AttackDeclared");
    expect(mixedLog[0].revision).toBe(1);
  });

  it("V12.03：旧的无账号全局筛选键不自动导入新账号", () => {
    localStorage.setItem("bloodbound:event-log-filter", JSON.stringify(["dagger"]));
    renderLog("account-new");
    openLog();
    expect(screen.getByRole("button", { name: "匕首" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("事件日志（2）")).toBeInTheDocument();
  });
});
