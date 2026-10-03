// 教学/图例的静态中文文案（.scratch/ui-help-legend/spec.md）：大厅"怎么玩"
// 折叠块与房内"规则与图例"浮层共用这一份数据，两处说法永远一致。
// 规则事实依据：blood_bound/engine.py（技能分派、标记组合、终局分支）与
// CONTEXT.md 词条；后端 content/locales 的等级 2、审判者与全部资源描述为
// 开发占位，不在此搬运。
// 角色名是官方中文名，仅允许出现在本模块的静态帮助文案——对局实时显示
// （亮牌槽、技能横幅、事件日志）维持纯"等级N"（ADR 0005）。

import type { IconName } from "./icons";

// 大厅简介（五句话：徽记、攻击、挡刀、亮牌、胜负）；浮层"怎么玩"区同源。
export const HELP_INTRO: string[] = [
  "开局每人把阵营徽记给左邻看，你看到的是右邻的徽记——它只是线索，不一定可信。",
  "持匕首者轮流行事：把匕首传给别人，或宣布攻击一名玩家。",
  "有人被攻击时其他玩家可表态挡刀（替其承受 1 点伤害并亮出一条线索），被攻击者从志愿者中挑选，也可全部拒绝。",
  "受伤必须亮牌：座位前三格线索槽填亮几格，就是受了几点伤；受到第 4 点伤害即被捕获。",
  "各家族保护本族领袖：捕获敌方领袖即刻获胜，捕错普通人则对手获胜——先弄清敌我。",
];

// 大厅简介末尾的指路句（进房后才有"？"按钮，所以只在大厅渲染）。
export const HELP_INTRO_LINK =
  "进入房间后，点页头的「？」按钮可随时查看九级技能表与标记图例。";

// 等级 → 身份标记组合的类别（engine._markers_for 的镜像分组）：
// 1/5/6 双同色、2/3/4 双"？"、7/8/9 一同色一"？"、审判者双万能。
// 渲染时"同色"给出玫/兽两个变体，玩家看到的实际颜色随其阵营。
export type RankMarkerKind = "double-faction" | "double-unknown" | "faction-unknown" | "double-wild";

export interface HelpRankRow {
  rank: number | "fleur-cross";
  /** 官方角色名（ADR 0005：仅存在于帮助文案） */
  name: string;
  /** 审判者行标注"仅奇数局" */
  oddOnly?: boolean;
  markers: RankMarkerKind;
  effect: string;
}

export const HELP_RANKS: HelpRankRow[] = [
  {
    rank: 1,
    name: "长老",
    markers: "double-faction",
    effect:
      "本家族的初始领袖（存活者中等级数字最小者）。发动后取得并立刻消耗羽毛笔：本家族领袖改由存活成员中等级数字最大者担任。",
  },
  {
    rank: 2,
    name: "刺客",
    markers: "double-unknown",
    effect: "指定一名玩家承受 2 点伤害，随后匕首交给该玩家。",
  },
  {
    rank: 3,
    name: "小丑",
    markers: "double-unknown",
    effect: "秘密检视任意两名玩家的身份（阵营与等级），情报只有你自己可见。",
  },
  {
    rank: 4,
    name: "炼金术师",
    markers: "double-unknown",
    effect:
      "仅在为他人挡刀承伤后才能发动：令原被攻击者承受 1 点伤害，或治疗其 1 点伤害并令其退回一张已亮出的线索。",
  },
  {
    rank: 5,
    name: "感应者",
    markers: "double-faction",
    effect: "指定一名未持盾的玩家承受 1 点伤害（通常迫其亮出等级），随后匕首交给该玩家。",
  },
  {
    rank: 6,
    name: "守护者",
    markers: "double-faction",
    effect:
      "为目标放置盾牌，自己持有剑作为守护标记；守护者本人累计 3 点伤害时，剑与盾一同归还。",
  },
  {
    rank: 7,
    name: "狂战士",
    markers: "faction-unknown",
    effect: "被攻击或替人挡刀承伤后发动：让原攻击者承受 1 点反伤。",
  },
  {
    rank: 8,
    name: "法师",
    markers: "faction-unknown",
    effect: "授予目标法杖：其身份标记（包括已亮出的）全部被遮蔽为「？」。",
  },
  {
    rank: 9,
    name: "交际花",
    markers: "faction-unknown",
    effect: "授予目标扇子：其被攻击时无人可为其挡刀，干涉表决直接跳过。",
  },
  {
    rank: "fleur-cross",
    name: "审判者",
    oddOnly: true,
    markers: "double-wild",
    effect:
      "亮出等级后发动（仅一次）：将真诅咒与假诅咒暗置分发给两名不同玩家，或放弃（诅咒留在供应区）。终局时若胜方领袖持有真诅咒，审判者夺取胜利独赢，假诅咒无任何效果。其两张身份标记为万能，亮出时自选玫或兽。",
  },
];

// 等级表下方的通用规则注释（spec：至少一处提及）。
export const HELP_SKILL_NOTE = "技能造成的伤害不产生新的干涉投票，也不会开出新的技能窗口。";

export interface HelpLegendItem {
  icon: IconName;
  name: string;
  effect: string;
}

// 道具图例六条：名称与对局内资源显示名（displayResource）统一，
// 玩家把图标、名字、效果对上号，不制造第二套名字。
export const HELP_LEGEND_ITEMS: HelpLegendItem[] = [
  {
    icon: "dagger",
    name: "匕首",
    effect: "行动权的标志。轮到你持匕首时，选择把匕首传给任意一人，或宣布攻击一名玩家。",
  },
  {
    icon: "quill",
    name: "羽毛笔",
    effect: "等级 1（长老）技能取得并立刻消耗：本家族领袖改由存活成员中等级数字最大者担任。",
  },
  {
    icon: "shield",
    name: "盾牌",
    effect: "持有盾牌的玩家不可被攻击，也不可被技能指定伤害；但仍可志愿为他人挡刀承伤。",
  },
  {
    icon: "sword",
    name: "剑",
    effect:
      "等级 6（守护者）技能的守护标记：施放时目标获得盾牌，剑由守护者自己持有；守护者累计 3 点伤害时，剑与盾一同归还。",
  },
  {
    icon: "staff",
    name: "法杖",
    effect: "等级 8（法师）技能授予目标：其身份标记（包括已亮出的）全部被遮蔽为「？」，阵营线索被抹去。",
  },
  {
    icon: "fan",
    name: "扇子",
    effect: "持有扇子的玩家被攻击时，无人可为其挡刀——干涉表决直接跳过，攻击立即结算。",
  },
];

// 线索与徽记两行短注（compact 拍板版）：visual 由浮层按 kind 渲染，
// 文案停留在此处与全部帮助内容同源。
export interface HelpClueNote {
  kind: "slots" | "emblems";
  title: string;
  body: string;
}

export const HELP_CLUE_NOTES: HelpClueNote[] = [
  {
    kind: "slots",
    title: "线索标记",
    body: "座位前三格槽，受伤后逐格填亮，填亮几格 = 受了几点伤。玫（红）/ 兽（蓝）＝阵营身份标记，亮出后才对所有人可见；？（灰）＝看不出阵营：部分等级自带，或被法杖遮蔽后变成。",
  },
  {
    kind: "emblems",
    title: "阵营徽记",
    body: "开局每人的徽记只给左邻看，你看到的是右邻的。徽记通常与真实阵营一致，但只是线索不是事实：小丑的徽记恒为敌对家族，审判者的必然与其真实所属不符。",
  },
];
