import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SkillUse } from "./GameScreen";
import type { Action, PlayerView } from "./types";

// 等级3（小丑）技能窗的两人组合选择：投影为 rank 3 下发的 choose-skill 动作
// 携带 targetPlayerIds（两名玩家的组合，B11 秘密查看仅自己可见）。UI 必须提供
// 选人入口并把选中的两名玩家原样发出；若只发 {use:true} 不带目标，引擎将以
// skill.invalid-target 拒绝——即“点释放技能弹报错且无效果”的 bug 路径。

function makePlayer(id: string, seat: number): PlayerView {
  return {
    playerId: id,
    seat,
    displayName: `玩家${seat}`,
    damage: 0,
    captured: false,
    revealed: { rank: undefined, markers: [null, null] },
    identityMarkers: [null, null],
    resources: {},
  };
}

const players = [makePlayer("p0", 0), makePlayer("p1", 1), makePlayer("p2", 2), makePlayer("p3", 3)];
const pairActions: Action[] = [
  { type: "choose-skill", use: true, targetPlayerIds: ["p1", "p2"] },
  { type: "choose-skill", use: true, targetPlayerIds: ["p1", "p3"] },
  { type: "choose-skill", use: true, targetPlayerIds: ["p2", "p3"] },
];

describe("等级3（小丑）技能窗", () => {
  it("提供两名玩家的选择入口，发出的命令携带选中的 targetPlayerIds", () => {
    const send = vi.fn();
    render(<SkillUse actions={pairActions} players={players} send={send} />);

    // 选人入口：两步选择器各可选中一名其他玩家（自己 p0 不可选）
    const selectors = screen.getAllByRole("combobox");
    expect(selectors.length).toBe(2);
    fireEvent.change(selectors[0], { target: { value: "p1" } });
    fireEvent.change(selectors[1], { target: { value: "p2" } });

    fireEvent.click(screen.getByRole("button", { name: "使用技能" }));
    expect(send).toHaveBeenCalledWith("choose-skill", { use: true, targetPlayerIds: ["p1", "p2"] });
  });

  it("不允许发出不带目标的使用命令（bug 路径：引擎将拒绝 skill.invalid-target）", () => {
    const send = vi.fn();
    render(<SkillUse actions={pairActions} players={players} send={send} />);

    // 未选满两人前，使用按钮必须不可用，杜绝裸 {use:true} 命令
    const submit = screen.getByRole("button", { name: "使用技能" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(submit);
    expect(send).not.toHaveBeenCalled();
  });
});
