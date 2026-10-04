import { describe, expect, it } from "vitest";
import {
  HELP_ADVANCED_NOTES,
  HELP_CLUE_NOTES,
  HELP_GATE_NOTE,
  HELP_INTRO,
  HELP_INTRO_LINK,
  HELP_LEGEND_ITEMS,
  HELP_RANKS,
  HELP_SKILL_NOTE,
  HELP_WINDOW_TIMEOUT_NOTE,
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

  it("线索、徽记与真实阵营色各压成一条短注", () => {
    expect(HELP_CLUE_NOTES.map((n) => n.kind)).toEqual(["slots", "emblems", "self-badge"]);
    for (const note of HELP_CLUE_NOTES) expect(note.body.trim().length).toBeGreaterThan(0);
  });

  it("简介五句话以内且末尾有指路句", () => {
    expect(HELP_INTRO.length).toBeLessThanOrEqual(5);
    for (const line of HELP_INTRO) expect(line.trim().length).toBeGreaterThan(0);
    expect(HELP_INTRO_LINK).toContain("？");
  });

  it("通用注释：技能伤害不触发干涉，但新亮等级照常开窗（ADR 0006/0009）", () => {
    expect(HELP_SKILL_NOTE).toContain("干涉");
    expect(HELP_SKILL_NOTE).toContain("技能窗口");
    expect(HELP_SKILL_NOTE).toContain("感应者");
    expect(HELP_SKILL_NOTE).toContain("永不再开");
  });
});

// 2026-10 规则共识批次的 E1 清单（issue 07）：11 条高影响推论散布在
// 进阶裁定清单与等级行文案里，这里逐条锚定关键词，防实现时抄漏。
describe("helpContent 规则共识批次（E1 清单）", () => {
  const rankEffect = (rank: number | "fleur-cross") =>
    HELP_RANKS.find((row) => row.rank === rank)?.effect ?? "";

  it("进阶裁定清单六条非空", () => {
    expect(HELP_ADVANCED_NOTES.length).toBe(6);
    for (const note of HELP_ADVANCED_NOTES) expect(note.trim().length).toBeGreaterThan(0);
  });

  it("技能伤害由受害者自选亮牌（P1）", () => {
    expect(HELP_ADVANCED_NOTES[0]).toContain("受害者本人决定");
  });

  it("封印写进感应者条目：永久不可发动，炼金不可解（P4）", () => {
    expect(rankEffect(5)).toContain("封印");
    expect(rankEffect(5)).toContain("永久不可发动");
    expect(rankEffect(5)).toContain("解不开");
  });

  it("已亮等级者不能再挡刀（C1 推论）", () => {
    expect(HELP_ADVANCED_NOTES.some((note) => note.includes("已亮出等级") && note.includes("挡刀"))).toBe(true);
  });

  it("审判者被捕获独赢（P2）", () => {
    expect(rankEffect("fleur-cross")).toContain("被捕获同样由其独赢");
    expect(HELP_ADVANCED_NOTES.some((note) => note.includes("审判者") && note.includes("独赢"))).toBe(true);
  });

  it("捕获归因链四路齐全（D6）", () => {
    const attribution = HELP_ADVANCED_NOTES.find((note) => note.includes("第 4 点伤害"));
    expect(attribution).toContain("挡刀＝原攻击者");
    expect(attribution).toContain("技能＝技能使用者");
    expect(attribution).toContain("狂战士反伤＝狂战士本人");
  });

  it("技能误捕非领袖判技能方负（B13）", () => {
    expect(HELP_ADVANCED_NOTES.some((note) => note.includes("误捕非领袖"))).toBe(true);
  });

  it("诅咒发给自己是浪费（D2）", () => {
    expect(HELP_ADVANCED_NOTES.some((note) => note.includes("诅咒") && note.includes("自己"))).toBe(true);
  });

  it("技能伤害与反伤也归还守护者剑盾（B7）", () => {
    expect(rankEffect(6)).toContain("技能伤害");
    expect(rankEffect(6)).toContain("狂战士反伤");
  });

  it("扇子可以给自己（B10）", () => {
    expect(rankEffect(9)).toContain("可以是自己");
  });

  it("技能伤害不触发干涉但新亮 rank 开窗，感应者例外（A3 新表述）", () => {
    expect(HELP_SKILL_NOTE).toContain("不触发干涉投票");
    expect(HELP_SKILL_NOTE).not.toContain("不会开出新的技能窗口");
  });

  it("单人窗口超时默认三件套（L4）", () => {
    expect(HELP_WINDOW_TIMEOUT_NOTE).toContain("排序第一张");
    expect(HELP_WINDOW_TIMEOUT_NOTE).toContain("「？」");
    expect(HELP_WINDOW_TIMEOUT_NOTE).toContain("视为放弃");
  });

  it("审判者万能标记可亮问号（issue 26）", () => {
    expect(rankEffect("fleur-cross")).toContain("玫、兽或问号");
  });
});

// 挡刀请求门控（ADR 0012 / intervention-request-gate 04）：简介改为门控在前，
// 新增门关注释说明流程与「默认不让他人挡刀」偏好（界面偏好，不是规则）。
describe("helpContent 挡刀请求门控", () => {
  it("简介第三句先讲被攻击者确认，请求后才询问其他玩家", () => {
    expect(HELP_INTRO[2]).toContain("先由被攻击者确认是否请求挡刀");
    expect(HELP_INTRO[2]).toContain("请求后其他玩家才可表态挡刀");
  });

  it("门关注释覆盖：门控流程、自己承受/超时语义、偏好开关明写不是对局规则", () => {
    expect(HELP_GATE_NOTE).toContain("被攻击者先确认是否请求挡刀");
    expect(HELP_GATE_NOTE).toContain("请求后才会询问");
    expect(HELP_GATE_NOTE).toContain("视为不需要");
    expect(HELP_GATE_NOTE).toContain("「默认不让他人挡刀」");
    expect(HELP_GATE_NOTE).toContain("界面偏好");
    expect(HELP_GATE_NOTE).toContain("而非对局规则");
  });
});
