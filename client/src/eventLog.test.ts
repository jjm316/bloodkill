import { afterEach, describe, expect, it } from "vitest";
import { EVENT_CATEGORIES, categoryOf, isLogVisible, loadMutedCategories, saveMutedCategories } from "./eventLog";

// 引擎当前全部公开事件（blood_bound/engine.py 的 _event 调用，私有 CurseDistributed/CurseViewed 不广播故不在内）。
// 本测试就是 spec 第 26 条说的"映射表完整性核对"的自动化形态：引擎加事件而漏补映射时会在这里红。
const PUBLIC_EVENT_TYPES = [
  "PlayerJoined", "GameStarted", "ClueIconsShown", "DaggerPassed", "AttackDeclared",
  "InterventionGateOpened", "InterventionGateAccepted", "InterventionGateDeclined",
  "InterventionPollOpened", "InterventionResponded", "InterventionChoiceOpened", "InterventionSelected", "InterventionDeclined",
  "SkillDeclined", "SkillUsed", "ResourceGranted", "ResourceSpent", "HarlequinInspected",
  "TokenReturnOpened", "IdentityMarkersObscured", "DamageHealed", "TokenReturned", "ResourceReturned",
  "DamageApplied", "PlayerCaptured", "RevealWindowOpened", "ClueRevealed", "SkillWindowOpened",
  "GameEnded", "PhaseChanged",
];

describe("事件类别映射", () => {
  it("引擎全部公开事件都有映射，不会兜底成未知", () => {
    for (const eventType of PUBLIC_EVENT_TYPES) {
      expect(categoryOf(eventType).id, eventType).toEqual(expect.stringMatching(/^(dagger|intervention|skill|reveal|resource|flow)$/));
    }
  });

  it("每条事件恰属一个类别：映射值都是合法类别 id", () => {
    const ids = new Set(EVENT_CATEGORIES.map((c) => c.id));
    for (const eventType of PUBLIC_EVENT_TYPES) {
      expect(ids.has(categoryOf(eventType).id as never), eventType).toBe(true);
    }
  });

  it("未映射的新事件兜底归流程", () => {
    expect(categoryOf("SomeFutureEvent").id).toBe("flow");
  });

  it("三种窗口开启事件在日志中隐藏，其余可见", () => {
    expect(isLogVisible("RevealWindowOpened")).toBe(false);
    expect(isLogVisible("SkillWindowOpened")).toBe(false);
    expect(isLogVisible("TokenReturnOpened")).toBe(false);
    expect(isLogVisible("ClueRevealed")).toBe(true);
    expect(isLogVisible("SomeFutureEvent")).toBe(true);
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
