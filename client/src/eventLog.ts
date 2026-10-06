// 事件日志的阅读模型：同一份定义拥有类别、可见性与中文描述。
// 新增公开事件时在 EVENT_DEFINITIONS 中补齐；未知事件归流程并使用中文兜底。
import type { GameEvent, PlayerView } from "./types";
import { displayFaction, displayPhase, displayRank, displayResource } from "./types";

export type EventCategoryId = "dagger" | "intervention" | "skill" | "reveal" | "resource" | "flow";

export interface EventCategory {
  id: EventCategoryId;
  label: string;
  className: string;
}

export const EVENT_CATEGORIES: EventCategory[] = [
  { id: "dagger", label: "匕首", className: "cat-dagger" },
  { id: "intervention", label: "干涉", className: "cat-intervention" },
  { id: "skill", label: "技能", className: "cat-skill" },
  { id: "reveal", label: "亮牌", className: "cat-reveal" },
  { id: "resource", label: "资源", className: "cat-resource" },
  { id: "flow", label: "流程", className: "cat-flow" },
];

type PlayerName = (id: unknown) => string;
interface EventDefinition {
  category: EventCategoryId;
  describe: (payload: GameEvent["payload"], name: PlayerName) => string;
  hidden?: boolean;
}

const declinedReasons: Record<string, string> = {
  "no-volunteers": "无人愿意挡刀",
  "target-declined": "被攻击者拒绝全部挡刀",
  "timeout-declined": "选择超时，视为全部拒绝",
};
const timedOut = (payload: GameEvent["payload"]) => payload.reason === "timeout" ? "（超时自动）" : "";

// 窗口事件继续存在于事件缓冲，只在阅读视图中隐藏；技能名仍用等级数字（ADR 0005）。
const EVENT_DEFINITIONS: Record<string, EventDefinition> = {
  DaggerPassed: { category: "dagger", describe: (p, n) => `${n(p.fromPlayerId)} 把匕首传给了 ${n(p.toPlayerId)}` },
  AttackDeclared: { category: "dagger", describe: (p, n) => `${n(p.attackerPlayerId)} 持匕首攻击了 ${n(p.targetPlayerId)}` },
  DamageApplied: { category: "dagger", describe: (p, n) => `${n(p.targetPlayerId)} 受到 ${p.amount} 点伤害` },
  PlayerCaptured: { category: "dagger", describe: (p, n) => `${n(p.playerId)} 被捕获` },

  InterventionGateOpened: { category: "intervention", describe: (p, n) => `${n(p.targetPlayerId)} 正在确认是否需要他人挡刀` },
  InterventionGateAccepted: { category: "intervention", describe: (p, n) => `${n(p.targetPlayerId)} 请求他人挡刀` },
  InterventionGateDeclined: {
    category: "intervention",
    describe: (p, n) => p.reason === "timeout"
      ? `${n(p.targetPlayerId)} 未确认是否需要挡刀，视为不需要`
      : `${n(p.targetPlayerId)} 拒绝了他人挡刀`,
  },
  InterventionPollOpened: { category: "intervention", describe: (p, n) => `${n(p.targetPlayerId)} 被攻击，全员开始表态是否挡刀` },
  InterventionResponded: { category: "intervention", describe: (p, n) => `${n(p.playerId)} ${p.volunteer ? "愿意挡刀" : "不干涉"}` },
  InterventionChoiceOpened: {
    category: "intervention",
    describe: (p, n) => {
      const volunteers: string[] = Array.isArray(p.volunteerPlayerIds) ? p.volunteerPlayerIds : [];
      return `${volunteers.map(n).join("、")} 愿意挡刀，等待 ${n(p.targetPlayerId)} 选择`;
    },
  },
  InterventionSelected: { category: "intervention", describe: (p, n) => `${n(p.responderPlayerId)} 为 ${n(p.targetPlayerId)} 挡刀` },
  InterventionDeclined: { category: "intervention", describe: (p, n) => `${n(p.targetPlayerId)}：${declinedReasons[String(p.reason)] ?? "攻击正常结算"}` },

  SkillWindowOpened: { category: "skill", hidden: true, describe: () => "技能窗口已开启" },
  SkillUsed: {
    category: "skill",
    describe: (p, n) => p.rank === "fleur-cross"
      ? `${n(p.playerId)} 分发了诅咒牌`
      : `${n(p.playerId)} 发动了${displayRank(p.rank as number | string)}技能`,
  },
  SkillDeclined: { category: "skill", describe: (p, n) => `${n(p.playerId)} 放弃了技能${timedOut(p)}` },
  HarlequinInspected: {
    category: "skill",
    describe: (p, n) => {
      const targets: string[] = Array.isArray(p.targetPlayerIds) ? p.targetPlayerIds : [];
      return `${n(p.playerId)} 检视了 ${targets.map(n).join("、")} 的身份`;
    },
  },
  DamageHealed: { category: "skill", describe: (p, n) => `${n(p.playerId)} 恢复了 ${p.amount ?? 1} 点伤害` },
  TokenReturned: { category: "skill", describe: (p, n) => `${n(p.playerId)} 归还了身份标记${timedOut(p)}` },
  IdentityMarkersObscured: { category: "skill", describe: (p, n) => `${n(p.playerId)} 的身份标记被遮蔽为未知` },
  TokenReturnOpened: { category: "skill", hidden: true, describe: () => "归还标记窗口已开启" },

  ClueRevealed: { category: "reveal", describe: (p, n) => `${n(p.playerId)} 展示了${String(p.kind) === "rank" ? "等级" : "身份"}线索${timedOut(p)}` },
  RevealWindowOpened: { category: "reveal", hidden: true, describe: () => "亮牌窗口已开启" },

  ResourceGranted: { category: "resource", describe: (p, n) => `${n(p.playerId)} 获得了${displayResource(String(p.resource))}` },
  ResourceSpent: { category: "resource", describe: (p, n) => `${n(p.playerId)} 消耗了${displayResource(String(p.resource))}` },
  ResourceReturned: { category: "resource", describe: (p, n) => `${n(p.playerId)} 的${displayResource(String(p.resource))}已归还` },

  PlayerJoined: { category: "flow", describe: (p, n) => `${n(p.playerId)} 加入了房间` },
  GameStarted: { category: "flow", describe: (p) => `对局开始，共 ${p.playerCount} 名玩家` },
  GameEnded: {
    category: "flow",
    describe: (p) => {
      const winner = String(p.winner ?? "");
      return winner === "draw" ? "对局结束，平局" : `对局结束，${displayFaction(winner)}获胜`;
    },
  },
  PhaseChanged: { category: "flow", describe: (p) => `${displayPhase((p.from as { kind: string })?.kind ?? "?")} → ${displayPhase((p.to as { kind: string })?.kind ?? "?")}` },
  ClueIconsShown: { category: "flow", describe: () => "全员已向左邻展示阵营徽记" },
};

const UNKNOWN_EVENT: EventDefinition = {
  category: "flow",
  describe: () => "发生了一条新的对局事件",
};

function definitionOf(eventType: string): EventDefinition {
  return Object.prototype.hasOwnProperty.call(EVENT_DEFINITIONS, eventType)
    ? EVENT_DEFINITIONS[eventType]
    : UNKNOWN_EVENT;
}

export function categoryOf(eventType: string): EventCategory {
  const id = definitionOf(eventType).category;
  return EVENT_CATEGORIES.find((category) => category.id === id)!;
}

export function isLogVisible(eventType: string): boolean {
  return !definitionOf(eventType).hidden;
}

export function describeEvent(event: GameEvent, players?: PlayerView[]): string {
  const name: PlayerName = (id) => players?.find((player) => player.playerId === id)?.displayName ?? String(id);
  return definitionOf(event.eventType).describe(event.payload, name);
}

// 屏蔽偏好：设备级全局阅读偏好，跨房间、跨对局保留（与备忘标记按对局清空刻意不同）。
const PREF_KEY = "bloodbound:event-log-filter";

export function loadMutedCategories(): Set<EventCategoryId> {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(PREF_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return new Set();
    const known = new Set(EVENT_CATEGORIES.map((c) => c.id));
    return new Set(parsed.filter((x): x is EventCategoryId => typeof x === "string" && known.has(x as EventCategoryId)));
  } catch {
    return new Set();
  }
}

export function saveMutedCategories(muted: Iterable<EventCategoryId>): void {
  try {
    localStorage.setItem(PREF_KEY, JSON.stringify([...muted]));
  } catch {
    // 隐私模式等存储不可用场景：屏蔽仅在本次会话生效
  }
}
