import { describe, expect, it } from "vitest";
import {
  HELP_CLUE_NOTES,
  HELP_INTRO,
  HELP_INTRO_LINK,
  HELP_LEGEND_ITEMS,
  HELP_RANKS,
  HELP_SKILL_NOTE,
  type RankMarkerKind,
} from "./helpContent";
import { displayResource } from "./types";

// 帮助文案数据防呆（.scratch/ui-help-legend/spec.md Testing Decisions）：
// 角色名与标记组成是纯数据，用静态期望表断言，防止实现时抄错行。
// 期望值来源：ADR 0005 的官方角色名、engine._markers_for 的等级→标记分组。

const EXPECTED_NAMES: Record<string, string> = {
  "1": "长老",
  "2": "刺客",
  "3": "小丑",
  "4": "炼金术师",
  "5": "感应者",
  "6": "守护者",
  "7": "狂战士",
  "8": "法师",
  "9": "交际花",
  "fleur-cross": "审判者",
};

// engine._markers_for 的分组镜像：1/5/6 双同色、2/3/4 双"？"、7/8/9 一同色一"？"、审判者双万能
const EXPECTED_MARKERS: Record<string, RankMarkerKind> = {
  "1": "double-faction",
  "2": "double-unknown",
  "3": "double-unknown",
  "4": "double-unknown",
  "5": "double-faction",
  "6": "double-faction",
  "7": "faction-unknown",
  "8": "faction-unknown",
  "9": "faction-unknown",
  "fleur-cross": "double-wild",
};

describe("helpContent 等级技能表数据", () => {
  it("恰好 10 行：等级 1–9 顺序排列 + 审判者收尾", () => {
    expect(HELP_RANKS.map((r) => r.rank)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, "fleur-cross"]);
  });

  it("角色名与官方中文名逐一对应（ADR 0005）", () => {
    for (const row of HELP_RANKS) {
      expect(row.name).toBe(EXPECTED_NAMES[String(row.rank)]);
    }
  });

  it("标记组合与引擎映射一致，效果文案非空", () => {
    for (const row of HELP_RANKS) {
      expect(row.markers).toBe(EXPECTED_MARKERS[String(row.rank)]);
      expect(row.effect.trim().length).toBeGreaterThan(0);
    }
  });

  it("只有审判者行标注仅奇数局", () => {
    expect(HELP_RANKS.filter((r) => r.oddOnly).map((r) => r.rank)).toEqual(["fleur-cross"]);
  });
});

describe("helpContent 图例与简介数据", () => {
  it("道具图例六条：匕首 + 五资源，资源名称与对局显示名统一", () => {
    expect(HELP_LEGEND_ITEMS.map((i) => i.icon)).toEqual(["dagger", "quill", "shield", "sword", "staff", "fan"]);
    expect(HELP_LEGEND_ITEMS[0].name).toBe("匕首");
    for (const item of HELP_LEGEND_ITEMS.slice(1)) {
      expect(item.name).toBe(displayResource(item.icon));
      expect(item.effect.trim().length).toBeGreaterThan(0);
    }
  });

  it("线索与徽记各压成一条短注", () => {
    expect(HELP_CLUE_NOTES.map((n) => n.kind)).toEqual(["slots", "emblems"]);
    for (const note of HELP_CLUE_NOTES) expect(note.body.trim().length).toBeGreaterThan(0);
  });

  it("简介五句话以内且末尾有指路句", () => {
    expect(HELP_INTRO.length).toBeLessThanOrEqual(5);
    for (const line of HELP_INTRO) expect(line.trim().length).toBeGreaterThan(0);
    expect(HELP_INTRO_LINK).toContain("？");
  });

  it("通用注释提及技能伤害不再产生干涉或技能窗口", () => {
    expect(HELP_SKILL_NOTE).toContain("干涉");
    expect(HELP_SKILL_NOTE).toContain("技能窗口");
  });
});
