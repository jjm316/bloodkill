import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GameScreen } from "./GameScreen";
import { HowToPlayBlock, RulesOverlay } from "./HelpOverlay";
import { HELP_INTRO } from "./helpContent";
import { Lobby } from "./Lobby";
import type { GameState, PlayerView, RoomState } from "./types";

// 教学/图例外显行为测试（.scratch/ui-help-legend/spec.md Testing Decisions）：
// 只断言用户可见的渲染结果与可交互性——浮层开合、等级表/图例条目、
// 大厅折叠块的内容口径。

describe("RulesOverlay 浮层", () => {
  it("三个分区齐全：怎么玩 / 等级技能表 / 标记图例", () => {
    render(<RulesOverlay onClose={() => {}} />);
    expect(screen.getByRole("dialog", { name: "规则与图例" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "怎么玩" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "等级技能表" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "标记图例" })).toBeInTheDocument();
    expect(screen.getByText(HELP_INTRO[0])).toBeInTheDocument();
  });

  it("等级表渲染 10 行，审判者行带仅奇数局标注", () => {
    const { container } = render(<RulesOverlay onClose={() => {}} />);
    const rows = container.querySelectorAll("ul.rank-list > li.rank-row");
    expect(rows.length).toBe(10);
    expect(screen.getByText("长老")).toBeInTheDocument();
    expect(screen.getByText("交际花")).toBeInTheDocument();
    const inquisitor = rows[rows.length - 1];
    expect(inquisitor.textContent).toContain("审判者");
    expect(inquisitor.textContent).toContain("仅奇数局");
    expect(inquisitor.textContent).toContain("真诅咒");
  });

  it("图例含 6 条道具条目与线索/徽记两条短注", () => {
    const { container } = render(<RulesOverlay onClose={() => {}} />);
    const items = container.querySelectorAll("ul.legend-list > li.legend-row");
    expect(items.length).toBe(6);
    for (const name of ["匕首", "羽毛笔", "盾牌", "剑", "法杖", "扇子"]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
    const notes = container.querySelectorAll("ul.clue-notes > li.clue-note");
    expect(notes.length).toBe(2);
    expect(notes[0].textContent).toContain("填亮几格");
    expect(notes[1].textContent).toContain("左邻");
  });

  it("Escape 与点击遮罩关闭，点击浮层内容不关闭", () => {
    const onClose = vi.fn();
    const { container } = render(<RulesOverlay onClose={onClose} />);
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(container.querySelector(".modal-overlay")!);
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  // .scratch/ui-help-close/spec.md：手机没有 Esc、遮罩只剩 8px 细边按不中，
  // 页头 ✕ 是主关闭路径；旧提示文案指向的两条路径在触屏上不成立，整行移除。
  it("页头 ✕ 关闭按钮点击即关，Esc 提示不再出现", () => {
    const onClose = vi.fn();
    render(<RulesOverlay onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Esc / 点击遮罩关闭")).toBeNull();
  });
});

describe("大厅怎么玩折叠块", () => {
  it("展开后渲染简介与指路句，不含等级表与图例内容", () => {
    const { container } = render(<Lobby onJoin={() => {}} onReplay={() => {}} />);
    const details = container.querySelector("details.how-to") as HTMLDetailsElement;
    expect(details).not.toBeNull();
    fireEvent.click(screen.getByText("怎么玩"));
    expect(details.open).toBe(true);
    for (const line of HELP_INTRO) expect(screen.getByText(line)).toBeInTheDocument();
    expect(screen.getByText(/九级技能表与标记图例/)).toBeInTheDocument();
    // 两处内容口径的回归锚点：等级表角色名与图例道具名不出现在大厅
    for (const overlayOnly of ["长老", "炼金术师", "交际花", "等级技能表", "盾牌", "法杖", "扇子"]) {
      expect(container.textContent).not.toContain(overlayOnly);
    }
  });

  it("HowToPlayBlock 单独渲染同样只有简介", () => {
    const { container } = render(<HowToPlayBlock />);
    expect(container.textContent).toContain(HELP_INTRO[0]);
    expect(container.textContent).not.toContain("长老");
  });
});

// GameScreen 入口：mock 掉 socket 层，等待房状态下页头"？"按钮可开浮层。
const socketMock = vi.hoisted(() => ({ state: null as RoomState | null }));
vi.mock("./useSocket", () => ({
  useGameSocket: () => ({
    state: socketMock.state,
    events: [],
    error: null,
    closed: false,
    reconnecting: false,
    takenOver: false,
    failed: false,
    send: vi.fn(),
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

function makeWaitingRoomState(): RoomState {
  const game: GameState = {
    gameId: "game-1",
    revision: 0,
    status: "waiting",
    players: [makePlayer("p1", "阿玫", 0)],
    daggerHolderId: null,
    phase: { kind: "action" },
    pending: null,
    result: null,
    viewer: null,
    legalActions: [],
  };
  return {
    type: "state",
    roomCode: "123456",
    roomStatus: "waiting",
    locked: false,
    isHost: true,
    yourPlayerId: "p1",
    hostPlayerId: "p1",
    connected: { p1: true },
    hostActions: [],
    game,
    serverTime: 0,
  };
}

describe("对局页页头？入口", () => {
  beforeEach(() => {
    socketMock.state = makeWaitingRoomState();
  });

  it("等待房点？打开规则浮层，Escape 关闭", () => {
    render(<GameScreen credentials={{ code: "123456", name: "阿玫", token: null }} onLeave={() => {}} />);
    expect(screen.queryByRole("dialog", { name: "规则与图例" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "规则与图例" }));
    expect(screen.getByRole("dialog", { name: "规则与图例" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "规则与图例" })).toBeNull();
  });

  it("点击遮罩同样关闭浮层", () => {
    const { container } = render(<GameScreen credentials={{ code: "123456", name: "阿玫", token: null }} onLeave={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "规则与图例" }));
    fireEvent.click(container.querySelector(".modal-overlay")!);
    expect(screen.queryByRole("dialog", { name: "规则与图例" })).toBeNull();
  });
});
