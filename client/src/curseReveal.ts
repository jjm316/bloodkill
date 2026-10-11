// 诅咒卡真假解析的唯一共享点（ADR 0014，spec seat-marker-visibility）。
// 诅咒卡 ID 以 "true-curse" 前缀判真咒，其余（"false-curse…"）判假咒；此前该
// 前缀嗅探散落在 Board（药丸翻牌、终局归属）与 GameScreen（分发选择器）三处，
// 收敛到这里，禁止在他处重复实现。
import type { GameState, PlayerView, ViewerView } from "./types";

/** 诅咒卡真假："true"＝真咒，"false"＝假咒。 */
export type CurseTruth = "true" | "false";

/** 诅咒卡 ID → 真假。唯一的 "true-curse" 前缀嗅探点。 */
export function curseTruthOf(curseId: string): CurseTruth {
  return curseId.startsWith("true-curse") ? "true" : "false";
}

/** 诅咒药丸标签（ADR 0014）：翻牌态三分支「真咒/假咒」，null＝暗置只显「咒」。 */
export const cursePillLabel = (reveal: CurseTruth | null): string =>
  reveal === "true" ? "真咒" : reveal === "false" ? "假咒" : "咒";

const nameOf = (players: PlayerView[], playerId: string | null | undefined): string => {
  const player = players.find((p) => p.playerId === playerId);
  return player ? player.displayName : "?";
};

// 诅咒药丸翻牌态解析（spec seat-marker-visibility Part B）：返回
// "true" / "false" / null（null＝保持暗置只显「咒」）。归属来源二选一：
// 终局翻牌优先（result.curseAssignments，GameEnded 载荷全员可见，未分发为空
// 对象时不生效）；其余对局查 viewer.curseAssignments（仅审判者视角携带此字段，
// 投影驱动、重连不丢）。收件人＝该玩家且其卡 ID 经 curseTruthOf 判真咒，
// 否则假咒。
export function curseRevealOf(player: PlayerView, viewer: ViewerView | null, result: GameState["result"], ended: boolean): CurseTruth | null {
  // ?? {} 兜底旧存档回放：ruleset 0.7 之前的终局 result 没有 curseAssignments 键
  const endedAssignments = ended && result ? result.curseAssignments ?? {} : {};
  const assignments = endedAssignments && Object.keys(endedAssignments).length > 0 ? endedAssignments : viewer?.curseAssignments ?? {};
  const entry = Object.entries(assignments).find(([, recipient]) => recipient === player.playerId);
  if (!entry) return null;
  return curseTruthOf(entry[0]);
}

// 诅咒归属行（ADR 0014）：终局 GameEnded 载荷带完整归属（未分发/放弃为空对象）。
// 排在胜负判词上方；true-curse 触发独赢时（engine branch inquisitor-true-curse）
// 措辞点明家族胜利被覆盖。归属视图与回放终局共用（同走 ResultBanner）。
export function curseAttributionOf(result: NonNullable<GameState["result"]>, players: PlayerView[]): string | null {
  // ?? {} 兜底旧存档回放：ruleset 0.7 之前的终局 result 没有 curseAssignments 键
  const entries = Object.entries(result.curseAssignments ?? {});
  if (entries.length === 0) return null;
  const holderOf = (truth: CurseTruth) => {
    const entry = entries.find(([curseId]) => curseTruthOf(curseId) === truth);
    return entry ? nameOf(players, entry[1]) : null;
  };
  const truth = holderOf("true");
  const lie = holderOf("false");
  const stole = result.explanationKey === "game.end.inquisitor-true-curse";
  const truthPart = truth ? (stole ? `真诅咒在 ${truth}（胜方领袖）→ 审判者独赢，家族胜利被覆盖` : `真诅咒在 ${truth}`) : null;
  if (truthPart && lie) return `${truthPart}；假诅咒在 ${lie}`;
  return truthPart ?? (lie ? `假诅咒在 ${lie}` : null);
}
