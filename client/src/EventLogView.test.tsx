import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EventLog } from "./EventLogView";
import type { GameEvent, PlayerView } from "./types";

const players = [
  { playerId: "p1", displayName: "阿玫" },
  { playerId: "p2", displayName: "阿兽" },
] as PlayerView[];
const event = (eventType: string, payload: GameEvent["payload"] = {}, revision = 1): GameEvent => ({
  eventId: `g:${revision}`, eventType, gameId: "g", revision,
  timestamp: 0, commandId: `c:${revision}`, payload,
});
const mixed = [
  event("AttackDeclared", { attackerPlayerId: "p1", targetPlayerId: "p2" }, 1),
  event("ResourceSpent", { playerId: "p2", resource: "shield" }, 2),
];
function openLog() {
  fireEvent.click(screen.getByText(/^事件日志（/));
}
function rows() {
  return within(screen.getByRole("list")).queryAllByRole("listitem");
}

afterEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

describe("事件日志阅读视图", () => {
  it("六类标签、中文描述、倒序与过滤后计数一起呈现", () => {
    render(<EventLog events={[
      ...mixed,
      event("InterventionGateAccepted", { targetPlayerId: "p2" }, 3),
      event("SkillUsed", { playerId: "p1", rank: 3 }, 4),
      event("ClueRevealed", { playerId: "p2", kind: "rank" }, 5),
      event("GameStarted", { playerCount: 6 }, 6),
    ]} players={players} />);
    openLog();
    expect(screen.getByText("事件日志（6）")).toBeInTheDocument();
    expect(rows().map((row) => row.textContent)).toEqual([
      "流程对局开始，共 6 名玩家",
      "亮牌阿兽 展示了等级线索",
      "技能阿玫 发动了等级3技能",
      "干涉阿兽 请求他人挡刀",
      "资源阿兽 消耗了盾牌",
      "匕首阿玫 持匕首攻击了 阿兽",
    ]);
  });

  it("取消类别即时隐藏历史与新事件，重新勾选恢复全部该类记录", () => {
    const view = render(<EventLog events={mixed} players={players} />);
    openLog();
    fireEvent.click(screen.getByRole("button", { name: "匕首" }));
    expect(screen.getByRole("button", { name: "匕首" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "全选" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("事件日志（1）")).toBeInTheDocument();
    expect(rows()[0]).toHaveTextContent("阿兽 消耗了盾牌");
    const next = [...mixed, event("DaggerPassed", { fromPlayerId: "p2", toPlayerId: "p1" }, 3)];
    view.rerender(<EventLog events={next} players={players} />);
    expect(rows()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "匕首" }));
    expect(screen.getByText("事件日志（3）")).toBeInTheDocument();
    expect(rows()[0]).toHaveTextContent("阿兽 把匕首传给了 阿玫");
    expect(screen.getByRole("button", { name: "全选" })).toHaveAttribute("aria-pressed", "true");
  });

  it("全选支持全部屏蔽与恢复，并随类别选中态联动", () => {
    render(<EventLog events={mixed} players={players} />);
    openLog();
    fireEvent.click(screen.getByRole("button", { name: "全选" }));
    expect(screen.getByText("已屏蔽全部类别")).toBeInTheDocument();
    expect(screen.getByText("事件日志（0）")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "资源" }));
    expect(screen.queryByText("已屏蔽全部类别")).not.toBeInTheDocument();
    expect(rows()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "全选" }));
    expect(rows()).toHaveLength(2);
    expect(screen.getByRole("button", { name: "全选" })).toHaveAttribute("aria-pressed", "true");
  });

  it("筛选在重新挂载和换局后保留，是设备阅读偏好", () => {
    const first = render(<EventLog events={mixed} players={players} />);
    openLog();
    fireEvent.click(screen.getByRole("button", { name: "匕首" }));
    first.unmount();
    render(<EventLog events={mixed.map((e) => ({ ...e, gameId: "new-game" }))} players={players} />);
    openLog();
    expect(screen.getByRole("button", { name: "匕首" })).toHaveAttribute("aria-pressed", "false");
    expect(rows().map((row) => row.textContent)).toEqual(["资源阿兽 消耗了盾牌"]);
  });

  it("过滤隐藏窗口后取最近 60 条倒序展示，不修改事件缓冲", () => {
    const events = Array.from({ length: 65 }, (_, i) => event("DamageApplied", { targetPlayerId: "p1", amount: i + 1 }, i + 1));
    const hidden = ["RevealWindowOpened", "SkillWindowOpened", "TokenReturnOpened"].map((type, i) => event(type, {}, 66 + i));
    const frozen = Object.freeze([...events, ...hidden]);
    render(<EventLog events={frozen as unknown as GameEvent[]} players={players} />);
    openLog();
    expect(screen.getByText("事件日志（60）")).toBeInTheDocument();
    expect(rows()).toHaveLength(60);
    expect(rows()[0]).toHaveTextContent("阿玫 受到 65 点伤害");
    expect(rows()[59]).toHaveTextContent("阿玫 受到 6 点伤害");
    expect(frozen[0].revision).toBe(1);
  });

  it("类别过滤先于 60 条上限，较早但被选中的事件仍可阅读", () => {
    localStorage.setItem("bloodbound:event-log-filter", JSON.stringify(["dagger"]));
    const events = [
      event("GameStarted", { playerCount: 6 }, 1),
      ...Array.from({ length: 65 }, (_, i) => event("DamageApplied", { targetPlayerId: "p1", amount: 1 }, i + 2)),
    ];
    render(<EventLog events={events} players={players} />);
    openLog();
    expect(rows().map((row) => row.textContent)).toEqual(["流程对局开始，共 6 名玩家"]);
    expect(screen.getByText("事件日志（1）")).toBeInTheDocument();
  });

  it("无事件到收到事件的更新保持可用，不把空日志误报为全屏蔽", () => {
    const view = render(<EventLog events={[]} />);
    expect(screen.queryByText(/^事件日志（/)).not.toBeInTheDocument();
    view.rerender(<EventLog events={[event("RevealWindowOpened")]} />);
    openLog();
    expect(screen.getByText("事件日志（0）")).toBeInTheDocument();
    expect(screen.queryByText("已屏蔽全部类别")).not.toBeInTheDocument();
    view.rerender(<EventLog events={mixed} players={players} />);
    expect(rows()).toHaveLength(2);
  });

  it("未知事件仍显示在流程中，使用中文兜底且不会暴露原始 payload", () => {
    render(<EventLog events={[event("SomeFutureEvent", { secret: "private-payload" })]} />);
    openLog();
    expect(rows().map((row) => row.textContent)).toEqual(["流程发生了一条新的对局事件"]);
    expect(screen.queryByText(/SomeFutureEvent|private-payload/)).not.toBeInTheDocument();
  });

  it("本机存储不可用时仍可筛选，在本次挂载中生效", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("unavailable"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("unavailable"); });
    render(<EventLog events={mixed} players={players} />);
    openLog();
    fireEvent.click(screen.getByRole("button", { name: "匕首" }));
    expect(rows().map((row) => row.textContent)).toEqual(["资源阿兽 消耗了盾牌"]);
  });
});
