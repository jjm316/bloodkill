/// <reference types="vite/client" />
import engineSource from "../../blood_bound/engine.py?raw";
import protocolSource from "../../server/protocol.py?raw";
import { afterEach, describe, expect, it } from "vitest";
import { categoryOf, describeEvent, isLogVisible, loadMutedCategories, saveMutedCategories } from "./eventLog";
import type { EventCategoryId } from "./eventLog";
import type { GameEvent, PlayerView } from "./types";

const event = (eventType: string, payload: GameEvent["payload"] = {}): GameEvent => ({
  eventId: "g:1", eventType, gameId: "g", revision: 1,
  timestamp: 0, commandId: "c", payload,
});
const players = [
  { playerId: "p1", displayName: "阿玫" },
  { playerId: "p2", displayName: "阿兽" },
] as PlayerView[];

// 预期类别来自已验收的事件日志 spec，门控补充来自 ADR 0012；不从实现表生成预期。
const expectedCategories: Record<EventCategoryId, string[]> = {
  dagger: ["DaggerPassed", "AttackDeclared", "DamageApplied", "PlayerCaptured"],
  intervention: [
    "InterventionGateOpened", "InterventionGateAccepted", "InterventionGateDeclined",
    "InterventionPollOpened", "InterventionResponded", "InterventionChoiceOpened",
    "InterventionSelected", "InterventionDeclined",
  ],
  skill: [
    "SkillWindowOpened", "SkillUsed", "SkillDeclined", "HarlequinInspected",
    "DamageHealed", "TokenReturned", "IdentityMarkersObscured", "TokenReturnOpened",
  ],
  reveal: ["ClueRevealed", "RevealWindowOpened"],
  resource: ["ResourceGranted", "ResourceSpent", "ResourceReturned"],
  flow: ["PlayerJoined", "GameStarted", "GameEnded", "PhaseChanged", "ClueIconsShown"],
};

describe("事件日志完整性", () => {
  it("当前公开事件的类别准确且有独立中文描述，漏定义不能靠流程兜底通过", () => {
    for (const [category, types] of Object.entries(expectedCategories)) {
      for (const type of types) {
        expect(categoryOf(type).id, type).toBe(category);
        expect(describeEvent(event(type)), type).not.toBe("发生了一条新的对局事件");
      }
    }
  });

  it("事件清单与引擎公开事件一致，新增事件必须补上阅读行为", () => {
    const privateDefinition = protocolSource.match(/PRIVATE_EVENT_TYPES\s*=\s*frozenset\(\{([^}]+)\}\)/);
    expect(privateDefinition).not.toBeNull();
    const privateTypes = new Set([...privateDefinition![1].matchAll(/["']([^"']+)["']/g)].map((match) => match[1]));
    const actual = new Set([...engineSource.matchAll(/self\._event\(\s*\w+,\s*\w+,\s*["']([^"']+)["']/g)]
      .map((match) => match[1]).filter((type) => !privateTypes.has(type)));
    expect([...actual].sort()).toEqual(Object.values(expectedCategories).flat().sort());
  });

  it.each(["SomeFutureEvent", "toString", "constructor", "__proto__"])("未知事件 %s 使用可见的流程中文兜底", (type) => {
    expect(categoryOf(type).id).toBe("flow");
    expect(isLogVisible(type)).toBe(true);
    expect(describeEvent(event(type))).toBe("发生了一条新的对局事件");
  });

  it("只隐藏亮牌、技能、退牌窗口开启事件，其余公开事件继续显示", () => {
    const hidden = new Set(["RevealWindowOpened", "SkillWindowOpened", "TokenReturnOpened"]);
    for (const type of Object.values(expectedCategories).flat()) {
      expect(isLogVisible(type), type).toBe(!hidden.has(type));
    }
  });
});

const descriptions: [string, GameEvent["payload"], string][] = [
  ["DaggerPassed", { fromPlayerId: "p1", toPlayerId: "p2" }, "阿玫 把匕首传给了 阿兽"],
  ["AttackDeclared", { attackerPlayerId: "p1", targetPlayerId: "p2" }, "阿玫 持匕首攻击了 阿兽"],
  ["DamageApplied", { targetPlayerId: "p2", amount: 1 }, "阿兽 受到 1 点伤害"],
  ["PlayerCaptured", { playerId: "p2" }, "阿兽 被捕获"],
  ["InterventionGateOpened", { targetPlayerId: "p2" }, "阿兽 正在确认是否需要他人挡刀"],
  ["InterventionGateAccepted", { targetPlayerId: "p2" }, "阿兽 请求他人挡刀"],
  ["InterventionGateDeclined", { targetPlayerId: "p2" }, "阿兽 拒绝了他人挡刀"],
  ["InterventionGateDeclined", { targetPlayerId: "p2", reason: "timeout" }, "阿兽 未确认是否需要挡刀，视为不需要"],
  ["InterventionPollOpened", { targetPlayerId: "p2" }, "阿兽 被攻击，全员开始表态是否挡刀"],
  ["InterventionResponded", { playerId: "p1", volunteer: true }, "阿玫 愿意挡刀"],
  ["InterventionResponded", { playerId: "p1", volunteer: false }, "阿玫 不干涉"],
  ["InterventionChoiceOpened", { targetPlayerId: "p2", volunteerPlayerIds: ["p1"] }, "阿玫 愿意挡刀，等待 阿兽 选择"],
  ["InterventionSelected", { responderPlayerId: "p1", targetPlayerId: "p2" }, "阿玫 为 阿兽 挡刀"],
  ["InterventionDeclined", { targetPlayerId: "p2", reason: "no-volunteers" }, "阿兽：无人愿意挡刀"],
  ["InterventionDeclined", { targetPlayerId: "p2", reason: "target-declined" }, "阿兽：被攻击者拒绝全部挡刀"],
  ["InterventionDeclined", { targetPlayerId: "p2", reason: "timeout-declined" }, "阿兽：选择超时，视为全部拒绝"],
  ["InterventionDeclined", { targetPlayerId: "p2", reason: "future-reason" }, "阿兽：攻击正常结算"],
  ["SkillUsed", { playerId: "p1", rank: 3 }, "阿玫 发动了等级3技能"],
  ["SkillUsed", { playerId: "p1", rank: "fleur-cross" }, "阿玫 分发了诅咒牌"],
  ["SkillDeclined", { playerId: "p1" }, "阿玫 放弃了技能"],
  ["HarlequinInspected", { playerId: "p1", targetPlayerIds: ["p2", "p1"] }, "阿玫 检视了 阿兽、阿玫 的身份"],
  ["DamageHealed", { playerId: "p1" }, "阿玫 恢复了 1 点伤害"],
  ["DamageHealed", { playerId: "p1", amount: 2 }, "阿玫 恢复了 2 点伤害"],
  ["TokenReturned", { playerId: "p1" }, "阿玫 归还了身份标记"],
  ["IdentityMarkersObscured", { playerId: "p1" }, "阿玫 的身份标记被遮蔽为未知"],
  ["ClueRevealed", { playerId: "p1", kind: "rank" }, "阿玫 展示了等级线索"],
  ["ClueRevealed", { playerId: "p1", kind: "marker-0" }, "阿玫 展示了身份线索"],
  ["ResourceGranted", { playerId: "p1", resource: "fan" }, "阿玫 获得了扇子"],
  ["ResourceSpent", { playerId: "p1", resource: "shield" }, "阿玫 消耗了盾牌"],
  ["ResourceReturned", { playerId: "p1", resource: "sword" }, "阿玫 的剑已归还"],
  ["PlayerJoined", { playerId: "p1" }, "阿玫 加入了房间"],
  ["GameStarted", { playerCount: 6 }, "对局开始，共 6 名玩家"],
  ["GameEnded", { winner: "rose" }, "对局结束，玫瑰家族获胜"],
  ["GameEnded", { winner: "beast" }, "对局结束，野兽家族获胜"],
  ["GameEnded", { winner: "secret-order" }, "对局结束，审判者获胜"],
  ["GameEnded", { winner: "draw" }, "对局结束，平局"],
  ["PhaseChanged", { from: { kind: "action" }, to: { kind: "reveal" } }, "行动阶段 → 展示身份"],
  ["PhaseChanged", { from: { kind: "setup" }, to: { kind: "action" } }, "开局准备 → 行动阶段"],
  ["ClueIconsShown", {}, "全员已向左邻展示阵营徽记"],
];

describe("事件日志中文描述", () => {
  it.each(descriptions)("%s 的描述保留玩家姓名与原有文案", (type, payload, text) => {
    expect(describeEvent(event(type, payload), players)).toBe(text);
  });

  it.each([
    ["ClueRevealed", { playerId: "p1", kind: "rank", reason: "timeout" }, "阿玫 展示了等级线索（超时自动）"],
    ["SkillDeclined", { playerId: "p1", reason: "timeout" }, "阿玫 放弃了技能（超时自动）"],
    ["TokenReturned", { playerId: "p1", reason: "timeout" }, "阿玫 归还了身份标记（超时自动）"],
  ] as [string, GameEvent["payload"], string][])("%s 的超时自动标注保持可解释", (type, payload, text) => {
    expect(describeEvent(event(type, payload), players)).toBe(text);
  });
});

describe("屏蔽偏好存取", () => {
  afterEach(() => localStorage.clear());

  it("存取往返一致", () => {
    saveMutedCategories(["dagger", "flow"]);
    expect([...loadMutedCategories()].sort()).toEqual(["dagger", "flow"]);
  });

  it("无存储时默认全选（空屏蔽集）", () => {
    expect(loadMutedCategories().size).toBe(0);
  });

  it("存储里的非法/未知 id 被过滤，坏 JSON 不抛错", () => {
    localStorage.setItem("bloodbound:event-log-filter", JSON.stringify(["dagger", "nope", 42]));
    expect([...loadMutedCategories()]).toEqual(["dagger"]);
    localStorage.setItem("bloodbound:event-log-filter", "{not json");
    expect(loadMutedCategories().size).toBe(0);
  });
});
