import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { describeEvent, GameScreen } from "./GameScreen";
import { useIntervention } from "./intervention";
import { ReplayScreen } from "./ReplayScreen";
import { categoryOf } from "./eventLog";
import type { GameEvent, GameState, PlayerView, RoomState } from "./types";

// 挡刀请求门控（ADR 0012 / .scratch/intervention-request-gate/issues/04）：
// 门控弹窗、等待横幅、日志四条中文文案、事件类别与 no-assist 偏好。
// 文案锚点 = spec Q6 拍板抄本，一字不改。

// GameScreen 级用例 mock 掉 socket 层（同 HelpOverlay.test.tsx 模式）。
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

function InterventionHarness(props: Parameters<typeof useIntervention>[0]) {
  return useIntervention(props).prompt;
}

beforeEach(() => {
  localStorage.clear();
  socketMock.send.mockReset();
});
afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

const gatePlayers = [makePlayer("p0", "阿攻", 0), makePlayer("p1", "小标", 1), makePlayer("p2", "小二", 2), makePlayer("p3", "小三", 3)];

const gateEvent = (eventType: string, payload: Record<string, unknown>): GameEvent => ({
  eventId: "g:1",
  eventType,
  gameId: "g",
  revision: 1,
  timestamp: 0,
  commandId: "c",
  payload,
});

describe("describeEvent 门控事件四条文案", () => {
  it("开窗：目标正在确认是否需要他人挡刀", () => {
    expect(describeEvent(gateEvent("InterventionGateOpened", { targetPlayerId: "p1", attackerPlayerId: "p0", eligiblePlayerIds: ["p2", "p3"] }), gatePlayers)).toBe("小标 正在确认是否需要他人挡刀");
  });

  it("请求：目标请求他人挡刀", () => {
    expect(describeEvent(gateEvent("InterventionGateAccepted", { targetPlayerId: "p1" }), gatePlayers)).toBe("小标 请求他人挡刀");
  });

  it("拒绝：目标拒绝了他人挡刀（reason=target-declined）", () => {
    expect(describeEvent(gateEvent("InterventionGateDeclined", { targetPlayerId: "p1", reason: "target-declined" }), gatePlayers)).toBe("小标 拒绝了他人挡刀");
  });

  it("超时：目标未确认是否需要挡刀，视为不需要（reason=timeout）", () => {
    expect(describeEvent(gateEvent("InterventionGateDeclined", { targetPlayerId: "p1", reason: "timeout" }), gatePlayers)).toBe("小标 未确认是否需要挡刀，视为不需要");
  });

  it("三个门控事件都归「干涉」类别", () => {
    for (const eventType of ["InterventionGateOpened", "InterventionGateAccepted", "InterventionGateDeclined"]) {
      expect(categoryOf(eventType).id, eventType).toBe("intervention");
    }
  });
});

// 门控期视角夹具：p0 阿攻攻击 p1 小标，小二/小三有挡刀资格。引擎在攻击
// 瞬间把匕首抵押给目标（_attack 先移交匕首再开门控），所以门控期
// daggerHolderId 是目标 p1；攻击者名优先来自 pending.attackerPlayerId（v3
// 公开字段），兜底公开的 AttackDeclared 事件（见 GameScreen 弹窗实现）。
// 目标视角 legalActions 与 projection.py 的门控分支一致（两条 need 变体）。
const gateEvents: GameEvent[] = [
  { ...gateEvent("AttackDeclared", { attackerPlayerId: "p0", targetPlayerId: "p1" }) },
];

function makeGateGame(viewerIsTarget: boolean, deadlineOffset = 30): GameState {
  return {
    gameId: "game-1",
    revision: 12,
    status: "active",
    players: gatePlayers,
    daggerHolderId: "p1",
    phase: { kind: "intervention", stage: "gate", activePlayerId: "p1" },
    pending: {
      kind: "intervention",
      actorPlayerId: "p1",
      targetPlayerId: "p1",
      eligiblePlayerIds: ["p2", "p3"],
      rank: null,
      trigger: null,
      stage: "gate",
      attackerPlayerId: "p0",
      deadline: Date.now() / 1000 + deadlineOffset,
    },
    result: null,
    viewer: null,
    legalActions: viewerIsTarget
      ? [
          { type: "answer-intervention-request", need: true },
          { type: "answer-intervention-request", need: false },
        ]
      : [],
  };
}

describe("干涉决策入口：门控弹窗（被攻击者视角）", () => {
  it("标题/正文/名单行/倒计时按 Q6 拍板文案渲染（攻击者优先取 pending.attackerPlayerId）", () => {
    const serverTime = Date.now() / 1000;
    const { container } = render(<InterventionHarness game={makeGateGame(true)} serverTime={serverTime} send={vi.fn()} />);
    const dialog = container.querySelector(".modal");
    expect(dialog?.getAttribute("aria-labelledby")).toBe("modal-title");
    expect(container.querySelector("#modal-title")?.textContent).toBe("是否需要他人为你挡刀？");
    const body = container.querySelector(".modal-body")?.textContent ?? "";
    expect(body).toContain("阿攻 对你发起攻击。请求挡刀将向所有有资格的玩家发起询问；若不需要或超时，你将承受这次攻击。");
    expect(body).toContain("可为你挡刀的玩家：小二、小三");
    expect(body).toContain("（剩 30 秒）");
    expect(body).not.toContain("?");
    // 匕首已抵押给目标，绝不能把目标自己当成攻击者念出来
    expect(body).not.toContain("小标 对你发起攻击");
  });

  it("wire 缺 attackerPlayerId 时退回公开 AttackDeclared 事件点名", () => {
    const game = { ...makeGateGame(true), pending: { ...makeGateGame(true).pending!, attackerPlayerId: undefined } };
    const { container } = render(<InterventionHarness game={game} events={gateEvents} serverTime={Date.now() / 1000} send={vi.fn()} />);
    expect(container.querySelector(".modal-body")?.textContent).toContain("阿攻 对你发起攻击。");
  });

  it("wire 与事件都缺失（极端重连）时退化为不点名正文，也不误把匕首持有者当攻击者", () => {
    const game = { ...makeGateGame(true), pending: { ...makeGateGame(true).pending!, attackerPlayerId: undefined } };
    const { container } = render(<InterventionHarness game={game} serverTime={Date.now() / 1000} send={vi.fn()} />);
    const body = container.querySelector(".modal-body")?.textContent ?? "";
    expect(body).toContain("一次攻击对你发起。");
    expect(body).not.toContain("小标 对你发起攻击");
  });

  it("「请求挡刀」发送 answer-intervention-request need=true，「自己承受」发送 need=false", () => {
    const send = vi.fn();
    const { container } = render(<InterventionHarness game={makeGateGame(true)} serverTime={Date.now() / 1000} send={send} />);
    fireEvent.click(container.querySelector<HTMLButtonElement>(".modal-confirm")!);
    expect(send).toHaveBeenCalledWith("answer-intervention-request", { need: true });
    fireEvent.click(container.querySelector<HTMLButtonElement>(".modal-cancel")!);
    expect(send).toHaveBeenCalledWith("answer-intervention-request", { need: false });
  });

  it("no-assist 偏好开启时门控窗不弹，入口自动代发", () => {
    localStorage.setItem("bloodbound:no-assist", "1");
    const { container } = render(<InterventionHarness game={makeGateGame(true)} serverTime={Date.now() / 1000} send={vi.fn()} />);
    expect(container.querySelector(".modal")).toBeNull();
    expect(container.querySelector(".waiting-banner")).toBeNull();
  });
});

describe("干涉决策入口：等待横幅与其余视角", () => {
  it("非当事人（攻击者/有资格者/旁观）看到等待横幅与倒计时，不弹窗", () => {
    const serverTime = Date.now() / 1000;
    const { container } = render(<InterventionHarness game={makeGateGame(false)} serverTime={serverTime} send={vi.fn()} />);
    expect(container.querySelector(".modal")).toBeNull();
    const banner = container.querySelector(".waiting-banner");
    expect(banner?.textContent).toContain("等待 小标 确认是否需要他人挡刀…（剩 30 秒）");
    expect(banner?.getAttribute("role")).toBe("status");
  });

  it("切换到投票时显示投票等待横幅，无 pending 时不显示提示", () => {
    const serverTime = Date.now() / 1000;
    const pollGame: GameState = { ...makeGateGame(false), pending: { ...makeGateGame(false).pending!, stage: "poll" } };
    const { container, unmount } = render(<InterventionHarness game={pollGame} serverTime={serverTime} send={vi.fn()} />);
    expect(container.querySelector(".modal")).toBeNull();
    expect(container.querySelector(".waiting-banner")).not.toBeNull();
    unmount();
    const noPending: GameState = { ...makeGateGame(true), pending: null };
    const { container: empty } = render(<InterventionHarness game={noPending} serverTime={serverTime} send={vi.fn()} />);
    expect(empty.querySelector(".waiting-banner")).toBeNull();
  });
});

describe("门控期间桌面挂起条（Board PendingBanner）", () => {
  it("门控阶段不显示投票汇总，显示目标正在确认挡刀请求", () => {
    socketMock.state = makeGateRoomState(12, Date.now() / 1000 + 90);
    const { container } = renderGame();
    const banner = container.querySelector(".pending");
    expect(banner?.textContent).toContain("小标 被攻击，正在确认是否需要他人挡刀…");
    expect(banner?.textContent).not.toContain("干涉投票进行中");
    expect(banner?.textContent).not.toContain("表态");
  });
});

// GameScreen 级：以自己=小标（被攻击者）视角构造整房状态。
function makeGateRoomState(revision: number, deadline: number, viewerIsTarget = true): RoomState {
  const game = makeGateGame(viewerIsTarget);
  game.revision = revision;
  game.pending!.deadline = deadline;
  return {
    type: "state",
    roomCode: "123456",
    roomStatus: "playing",
    locked: false,
    isHost: false,
    yourPlayerId: "p1",
    hostPlayerId: "p0",
    connected: { p0: true, p1: true, p2: true, p3: true },
    hostActions: [],
    game,
    serverTime: Date.now() / 1000,
  };
}

function renderGame() {
  return render(<GameScreen credentials={{ code: "123456", name: "小标", token: null }} onLeave={() => {}} />);
}

function makePollRoomState(revision: number, deadline: number): RoomState {
  const state = makeGateRoomState(revision, deadline, false);
  state.yourPlayerId = "p2";
  state.game!.pending!.stage = "poll";
  state.game!.pending!.responses = {};
  state.game!.legalActions = [
    { type: "respond-intervention", volunteer: true },
    { type: "respond-intervention", volunteer: false },
  ];
  return state;
}

const gateSends = () => socketMock.send.mock.calls.filter((c) => c[0] === "answer-intervention-request");

describe("「默认不让他人挡刀」偏好（Q7/Q10:A）", () => {
  beforeEach(() => {
    localStorage.clear();
    socketMock.send.mockReset();
  });

  afterEach(() => localStorage.clear());

  it("偏好开启：门控窗不弹，自动代发一次 need=false", () => {
    localStorage.setItem("bloodbound:no-assist", "1");
    socketMock.state = makeGateRoomState(12, Date.now() / 1000 + 90);
    const { container } = renderGame();
    expect(container.querySelector(".modal")).toBeNull();
    expect(gateSends()).toEqual([["answer-intervention-request", { need: false }]]);
  });

  it("防重复：同一窗口（revision+deadline 不变）重渲染不重复代发，新窗口再代发一次", () => {
    localStorage.setItem("bloodbound:no-assist", "1");
    const deadline = Date.now() / 1000 + 90;
    socketMock.state = makeGateRoomState(12, deadline);
    const view = renderGame();
    expect(gateSends()).toHaveLength(1);
    // 服务器重播同一窗口（状态对象全新、键不变）
    socketMock.state = makeGateRoomState(12, deadline);
    view.rerender(<GameScreen credentials={{ code: "123456", name: "小标", token: null }} onLeave={() => {}} />);
    expect(gateSends()).toHaveLength(1);
    // 下一次攻击开出新门控窗（revision 与 deadline 都变了）
    socketMock.state = makeGateRoomState(20, deadline + 95);
    view.rerender(<GameScreen credentials={{ code: "123456", name: "小标", token: null }} onLeave={() => {}} />);
    expect(gateSends()).toHaveLength(2);
    expect(gateSends()[1]).toEqual(["answer-intervention-request", { need: false }]);
  });

  it("代发键按 stage 区分：poll 阶段不代发门控命令", () => {
    localStorage.setItem("bloodbound:no-assist", "1");
    const pollState = makeGateRoomState(12, Date.now() / 1000 + 90);
    pollState.game!.pending!.stage = "poll";
    pollState.game!.legalActions = [
      { type: "respond-intervention", volunteer: true },
      { type: "respond-intervention", volunteer: false },
    ];
    socketMock.state = pollState;
    renderGame();
    expect(gateSends()).toHaveLength(0);
  });

  it("偏好关闭（默认）：不代发，弹出门控确认窗", () => {
    socketMock.state = makeGateRoomState(12, Date.now() / 1000 + 90);
    const { container } = renderGame();
    expect(gateSends()).toHaveLength(0);
    expect(container.querySelector("#modal-title")?.textContent).toBe("是否需要他人为你挡刀？");
  });

  it("页头开关与「默认不挡刀」并排且相互独立，写入 bloodbound:no-assist", () => {
    socketMock.state = makeGateRoomState(12, Date.now() / 1000 + 90);
    const { container } = renderGame();
    const toggles = Array.from(container.querySelectorAll<HTMLLabelElement>("label.pref-toggle"));
    expect(toggles.map((t) => t.textContent)).toEqual(["默认不挡刀", "默认不让他人挡刀"]);
    const noAssistInput = toggles[1].querySelector("input")!;
    expect(noAssistInput.checked).toBe(false);
    fireEvent.click(noAssistInput);
    expect(noAssistInput.checked).toBe(true);
    expect(localStorage.getItem("bloodbound:no-assist")).toBe("1");
    expect(localStorage.getItem("bloodbound:no-block")).toBeNull();
    // 打开后当前门控窗立即收起并代发
    expect(gateSends()).toEqual([["answer-intervention-request", { need: false }]]);
    expect(container.querySelector(".modal")).toBeNull();
  });
});

describe("门控/投票/单人窗口互斥（渲染顺序）", () => {
  beforeEach(() => {
    localStorage.clear();
    socketMock.send.mockReset();
  });

  afterEach(() => localStorage.clear());

  it("gate 阶段：只弹门控窗，投票窗与单人窗口横幅都不出现", () => {
    socketMock.state = makeGateRoomState(12, Date.now() / 1000 + 90);
    const { container } = renderGame();
    expect(container.querySelectorAll(".modal")).toHaveLength(1);
    expect(container.querySelector("#modal-title")?.textContent).toBe("是否需要他人为你挡刀？");
    expect(container.textContent).not.toContain("是否为");
    expect(container.querySelector(".waiting-banner")).toBeNull();
  });

  it("poll 阶段：门控窗不再出现，有资格者看到的是投票窗", () => {
    const pollState = makeGateRoomState(13, Date.now() / 1000 + 90, false);
    pollState.yourPlayerId = "p2";
    pollState.game!.pending!.stage = "poll";
    pollState.game!.pending!.eligiblePlayerIds = ["p2"];
    pollState.game!.pending!.responses = {};
    pollState.game!.legalActions = [
      { type: "respond-intervention", volunteer: true },
      { type: "respond-intervention", volunteer: false },
    ];
    socketMock.state = pollState;
    const { container } = renderGame();
    expect(container.querySelector("#modal-title")?.textContent).toBe("是否为 小标 挡刀？");
    expect(container.textContent).not.toContain("是否需要他人为你挡刀");
  });
});

describe("干涉投票的操作与本机偏好", () => {
  it("默认不挡刀自动代发，重播不重复，新窗口再次代发", () => {
    localStorage.setItem("bloodbound:no-block", "1");
    const deadline = Date.now() / 1000 + 90;
    socketMock.state = makePollRoomState(13, deadline);
    const view = renderGame();
    expect(view.container.querySelector(".modal")).toBeNull();
    expect(socketMock.send.mock.calls).toEqual([["respond-intervention", { volunteer: false }]]);
    socketMock.state = makePollRoomState(13, deadline);
    view.rerender(<GameScreen credentials={{ code: "123456", name: "小标", token: null }} onLeave={() => {}} />);
    expect(socketMock.send).toHaveBeenCalledTimes(1);
    socketMock.state = makePollRoomState(24, deadline + 95);
    view.rerender(<GameScreen credentials={{ code: "123456", name: "小标", token: null }} onLeave={() => {}} />);
    expect(socketMock.send.mock.calls).toEqual([
      ["respond-intervention", { volunteer: false }],
      ["respond-intervention", { volunteer: false }],
    ]);
  });

  it("在当前投票打开默认不挡刀立即代发，另一个偏好保持独立", () => {
    socketMock.state = makePollRoomState(13, Date.now() / 1000 + 90);
    const view = renderGame();
    expect(view.container.querySelector(".modal")).not.toBeNull();
    fireEvent.click(view.getByRole("checkbox", { name: "默认不挡刀" }));
    expect(view.container.querySelector(".modal")).toBeNull();
    expect(socketMock.send.mock.calls).toEqual([["respond-intervention", { volunteer: false }]]);
    expect(localStorage.getItem("bloodbound:no-block")).toBe("1");
    expect(localStorage.getItem("bloodbound:no-assist")).toBeNull();
    expect(view.getByRole("checkbox", { name: "默认不让他人挡刀" })).not.toBeChecked();
  });

  it.each([["挡刀", true], ["不干涉", false]] as const)("点击%s按合法动作发送表态", (label, volunteer) => {
    socketMock.state = makePollRoomState(13, Date.now() / 1000 + 90);
    const view = renderGame();
    fireEvent.click(view.getByRole("button", { name: label }));
    expect(socketMock.send.mock.calls).toEqual([["respond-intervention", { volunteer }]]);
  });

  it("同时开启两个偏好，门控到投票只发送各自的拒绝命令", () => {
    localStorage.setItem("bloodbound:no-block", "1");
    localStorage.setItem("bloodbound:no-assist", "1");
    const deadline = Date.now() / 1000 + 90;
    socketMock.state = makeGateRoomState(12, deadline);
    const view = renderGame();
    expect(socketMock.send.mock.calls).toEqual([["answer-intervention-request", { need: false }]]);
    socketMock.state = makePollRoomState(13, deadline + 90);
    view.rerender(<GameScreen credentials={{ code: "123456", name: "小标", token: null }} onLeave={() => {}} />);
    expect(socketMock.send.mock.calls).toEqual([
      ["answer-intervention-request", { need: false }],
      ["respond-intervention", { volunteer: false }],
    ]);
  });

  it("初始无状态时保持 Hook 顺序，短暂失去状态后不重复代发同一窗口", () => {
    localStorage.setItem("bloodbound:no-block", "1");
    const deadline = Date.now() / 1000 + 90;
    socketMock.state = null;
    const view = renderGame();
    expect(view.getByRole("status").textContent).toBe("正在连接……");
    socketMock.state = makePollRoomState(13, deadline);
    const rerender = () => view.rerender(<GameScreen credentials={{ code: "123456", name: "小标", token: null }} onLeave={() => {}} />);
    rerender();
    expect(socketMock.send).toHaveBeenCalledTimes(1);
    socketMock.state = null;
    rerender();
    socketMock.state = makePollRoomState(13, deadline);
    rerender();
    expect(socketMock.send).toHaveBeenCalledTimes(1);
  });
});

function makeChoiceRoomState(viewerId: string | null): RoomState {
  const state = makeGateRoomState(14, Date.now() / 1000 + 90, false);
  state.yourPlayerId = viewerId;
  state.game!.pending!.stage = "choice";
  state.game!.pending!.volunteerPlayerIds = ["p2", "p3"];
  state.game!.pending!.responses = { p2: true, p3: true };
  state.game!.legalActions = viewerId === "p1" ? [
    { type: "choose-intervention", responderPlayerId: "p2" },
    { type: "choose-intervention", responderPlayerId: "p3" },
    { type: "decline-intervention" },
  ] : [];
  return state;
}

describe("干涉三选一保持现有动作入口", () => {
  it.each([["小二", "p2"], ["小三", "p3"]])("目标选择%s发送对应命令", (label, responderPlayerId) => {
    socketMock.state = makeChoiceRoomState("p1");
    const view = renderGame();
    const button = view.getByRole("button", { name: label });
    expect(button.closest(".actions .action-group")?.textContent).toContain("选择挡刀者：");
    expect(view.container.querySelector(".modal")).toBeNull();
    expect(view.container.querySelector(".waiting-banner")?.textContent).toContain("小二、小三 愿意挡刀，等待 小标 选择");
    fireEvent.click(button);
    expect(socketMock.send.mock.calls).toEqual([["choose-intervention", { responderPlayerId }]]);
  });

  it("目标可以拒绝全部挡刀", () => {
    socketMock.state = makeChoiceRoomState("p1");
    const view = renderGame();
    const button = view.getByRole("button", { name: "拒绝全部挡刀" });
    expect(button.closest(".actions")).not.toBeNull();
    fireEvent.click(button);
    expect(socketMock.send.mock.calls).toEqual([["decline-intervention"]]);
  });

  it.each(["p0", "p2", null])("非目标视角 %s 只见公开提示，没有选择按钮或代发", (viewerId) => {
    localStorage.setItem("bloodbound:no-assist", "1");
    localStorage.setItem("bloodbound:no-block", "1");
    socketMock.state = makeChoiceRoomState(viewerId);
    const view = renderGame();
    expect(view.container.querySelector(".pending")?.textContent).toContain("等待其选择其一或全部拒绝");
    expect(view.queryByRole("button", { name: "拒绝全部挡刀" })).toBeNull();
    expect(view.queryByRole("button", { name: "小二" })).toBeNull();
    expect(socketMock.send).not.toHaveBeenCalled();
  });
});

describe("回放只消费公开干涉提示", () => {
  it("请求、投票、选择快照可切换，不读本机偏好或启用实时交互", async () => {
    localStorage.setItem("bloodbound:no-assist", "1");
    localStorage.setItem("bloodbound:no-block", "1");
    const steps = [
      makeGateRoomState(12, Date.now() / 1000 + 90).game!,
      makePollRoomState(13, Date.now() / 1000 + 90).game!,
      makeChoiceRoomState("p1").game!,
    ].map((game) => ({ ...game, viewer: null, legalActions: [] }));
    steps[1].pending!.responses = { p2: true };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ steps }) }));
    const storageReads = vi.spyOn(Storage.prototype, "getItem");
    const intervals = vi.spyOn(window, "setInterval");
    try {
      const view = render(<ReplayScreen onBack={vi.fn()} />);
      fireEvent.change(view.getByPlaceholderText("6位数字房间号"), { target: { value: "123456" } });
      await act(async () => { fireEvent.click(view.getByRole("button", { name: "加载回放" })); });
      expect(view.getByRole("region", { name: "对局桌面" })).toBeInTheDocument();
      expect(view.container.querySelector(".pending")?.textContent).toContain("正在确认是否需要他人挡刀");
      fireEvent.click(view.getByRole("button", { name: "下一步" }));
      expect(view.container.querySelector(".pending")?.textContent).toContain("小二（挡刀）；等待 小三 表态");
      fireEvent.click(view.getByRole("button", { name: "下一步" }));
      expect(view.container.querySelector(".pending")?.textContent).toContain("小二、小三 愿意挡刀，等待其选择其一或全部拒绝");
      expect(view.container.querySelector(".modal")).toBeNull();
      expect(view.queryByRole("checkbox")).toBeNull();
      expect(view.queryByRole("button", { name: "拒绝全部挡刀" })).toBeNull();
      expect(storageReads).not.toHaveBeenCalled();
      expect(intervals).not.toHaveBeenCalled();
      expect(socketMock.send).not.toHaveBeenCalled();
    } finally {
      storageReads.mockRestore();
      intervals.mockRestore();
    }
  });
});
