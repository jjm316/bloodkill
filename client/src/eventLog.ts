// 事件日志的数据层：事件类别映射 + 屏蔽偏好存取（.scratch/event-log-categories/spec.md）。
// 事件类别是展示层概念（见 CONTEXT.md"事件类别"），不含协议含义；服务端零改动。
// 后端新增事件类型时必须在此补一行映射；漏映射的事件兜底归"流程"且照常显示。

export type EventCategoryId = "dagger" | "intervention" | "skill" | "reveal" | "resource" | "flow";

export interface EventCategory {
  id: EventCategoryId;
  /** 选项卡与行首标签共用的类别词 */
  label: string;
  /** 类别色 CSS 类（.cat-* 同时用于选项卡选中底色与行首标签底色） */
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

const FLOW: EventCategory = EVENT_CATEGORIES.find((c) => c.id === "flow")!;

const CATEGORY_OF: Record<string, EventCategoryId> = {
  // 匕首
  DaggerPassed: "dagger",
  AttackDeclared: "dagger",
  DamageApplied: "dagger",
  PlayerCaptured: "dagger",
  // 干涉
  InterventionPollOpened: "intervention",
  InterventionResponded: "intervention",
  InterventionChoiceOpened: "intervention",
  InterventionSelected: "intervention",
  InterventionDeclined: "intervention",
  // 技能（含治疗流程等技能后果）
  SkillWindowOpened: "skill",
  SkillUsed: "skill",
  SkillDeclined: "skill",
  HarlequinInspected: "skill",
  DamageHealed: "skill",
  TokenReturned: "skill",
  IdentityMarkersObscured: "skill",
  TokenReturnOpened: "skill",
  // 亮牌
  ClueRevealed: "reveal",
  RevealWindowOpened: "reveal",
  // 资源
  ResourceGranted: "resource",
  ResourceSpent: "resource",
  ResourceReturned: "resource",
  // 流程
  PlayerJoined: "flow",
  GameStarted: "flow",
  GameEnded: "flow",
  PhaseChanged: "flow",
  ClueIconsShown: "flow",
};

// 窗口开启类事件驱动当事玩家的待办 UI，不进日志（引擎照发，仅渲染层隐藏）。
const HIDDEN_EVENT_TYPES = new Set(["RevealWindowOpened", "SkillWindowOpened", "TokenReturnOpened"]);

export function categoryOf(eventType: string): EventCategory {
  const id = CATEGORY_OF[eventType];
  return (id && EVENT_CATEGORIES.find((c) => c.id === id)) || FLOW;
}

export function isLogVisible(eventType: string): boolean {
  return !HIDDEN_EVENT_TYPES.has(eventType);
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
