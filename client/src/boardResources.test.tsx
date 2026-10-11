import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Board } from "./Board";
import type { GameState, PlayerView } from "./types";

// 资源行徽章化（spec 2026-10-11 Q4，原型方案 A）：每个持有资源一枚金色药丸
// ——图标 + 单字中文标签（笔/盾/剑/杖/扇），count>1 才标 ×N；
// 悬浮 title 带规则效果（文案锚定 helpContent 图例与语料裁决）。

function makePlayer(id: string, seat: number, resources: Record<string, number>): PlayerView {
  return {
    playerId: id,
    seat,
    displayName: `玩家${seat}`,
    damage: 0,
    captured: false,
    holdsCurseCard: false,
    revealed: { rank: undefined, markers: [null, null] },
    identityMarkers: [null, null],
    resources,
  };
}

function makeGame(resources: Record<string, number>): GameState {
  return {
    gameId: "g-test",
    revision: 1,
    status: "active",
    players: [makePlayer("p0", 0, resources), makePlayer("p1", 1, {}), makePlayer("p2", 2, {})],
    daggerHolderId: "p0",
    phase: { kind: "action", activePlayerId: "p0" },
    pending: null,
    result: null,
    viewer: {
      playerId: "p0",
      identity: { faction: "rose", rank: 3 },
      identityMarkers: ["rose"],
      resources: {},
      skillsUsed: [],
      inspections: {},
      cursesToDistribute: [],
      clueIcon: "rose",
      seenNeighbourClue: null,
    },
    legalActions: [],
  };
}

describe("资源行金色药丸", () => {
  it("五类资源各渲染一枚药丸：SVG 图标 + 单字中文标签（笔/盾/剑/杖/扇）", () => {
    const { container } = render(
      <Board game={makeGame({ quill: 1, shield: 1, sword: 1, staff: 1, fan: 1 })} />,
    );
    const pills = [...container.querySelectorAll<HTMLElement>(".resource-pill")];
    expect(pills).toHaveLength(5);
    expect(pills.map((p) => p.textContent)).toEqual(["笔", "盾", "剑", "杖", "扇"]);
    for (const pill of pills) {
      expect(pill.querySelector("svg"), "每枚药丸都带描边图标").not.toBeNull();
    }
  });

  it("count=1 不显示 ×N，count>1 才显示 ×N", () => {
    const { container } = render(<Board game={makeGame({ shield: 1, sword: 2 })} />);
    const pills = [...container.querySelectorAll<HTMLElement>(".resource-pill")];
    expect(pills).toHaveLength(2);
    const byText = (t: string) => pills.find((p) => p.textContent === t);
    expect(byText("盾"), "count=1 只有标签，无数量").toBeTruthy();
    expect(byText("剑×2"), "count>1 追加 ×N").toBeTruthy();
    expect([...pills].some((p) => p.textContent === "盾×1")).toBe(false);
  });

  it("count=0 的资源不渲染；全部为零时资源行整体不出现（return null）", () => {
    const { container } = render(<Board game={makeGame({ quill: 0, shield: 2 })} />);
    expect(container.querySelectorAll(".resource-pill")).toHaveLength(1);
    expect(container.querySelector(".resource-pill")?.textContent).toBe("盾×2");
    const empty = render(<Board game={makeGame({ quill: 0, sword: 0 })} />);
    expect(empty.container.querySelector(".resources")).toBeNull();
  });

  it("悬浮 title 带规则效果：扇、杖锚定语料裁决原文，其余对齐帮助图例", () => {
    const { container } = render(
      <Board game={makeGame({ quill: 1, shield: 1, sword: 1, staff: 1, fan: 1 })} />,
    );
    const titleOf = (label: string) =>
      [...container.querySelectorAll<HTMLElement>(".resource-pill")].find((p) => p.textContent === label)?.getAttribute("title");
    expect(titleOf("扇")).toBe("扇子——他人不能替持扇者干涉");
    expect(titleOf("杖")).toBe("法杖——该玩家的身份标记全部变为问号");
    expect(titleOf("笔")).toBe("羽毛笔——消耗后本家族领袖改由存活成员中等级数字最大者担任");
    expect(titleOf("盾")).toBe("盾牌——持有者不可被攻击，也不可被技能指定伤害");
    expect(titleOf("剑")).toBe("剑——守护标记：守护者累计 3 点伤害时与盾一同归还");
  });
});
