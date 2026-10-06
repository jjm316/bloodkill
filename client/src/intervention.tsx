import { useEffect, useRef, useState } from "react";
import { ConfirmDialog } from "./ConfirmDialog";
import type { GameEvent, GameState, PendingView, PlayerView } from "./types";
import { actionToCommand } from "./types";
import { useDeadlineSeconds } from "./useDeadlineSeconds";

type Send = (command: string, payload?: Record<string, unknown>) => void;
const NO_BLOCK_KEY = "bloodbound:no-block";
const NO_ASSIST_KEY = "bloodbound:no-assist";
const INTERVENTION_ACTIONS = new Set([
  "answer-intervention-request", "respond-intervention", "choose-intervention", "decline-intervention",
]);

// 只解释公开投影，不计算资格或授权；实时页与回放共用这一份阶段描述。
function describeWindow(pending: PendingView | null, players: PlayerView[]) {
  if (pending?.kind !== "intervention") return null;
  const nameOf = (id: string | null | undefined) => players.find((p) => p.playerId === id)?.displayName ?? "?";
  const names = (ids: string[]) => ids.map(nameOf).join("、");
  const responses = pending.responses ?? {};
  const answered = pending.eligiblePlayerIds.filter((id) => responses[id] !== undefined);
  const waiting = pending.eligiblePlayerIds.filter((id) => responses[id] === undefined);
  return {
    pending,
    target: nameOf(pending.targetPlayerId),
    roster: names(pending.eligiblePlayerIds),
    waiting: names(waiting),
    volunteers: names(pending.volunteerPlayerIds ?? []),
    summary: answered.length
      ? answered.map((id) => `${nameOf(id)}（${responses[id] ? "挡刀" : "不干涉"}）`).join("、")
      : "暂无表态",
    nameOf,
  };
}

type WindowDescription = NonNullable<ReturnType<typeof describeWindow>>;

/** 公开桌面提示：回放调用此入口不会读偏好、启动计时或发送命令。 */
export function InterventionSummary({ pending, players }: { pending: PendingView; players: PlayerView[] }) {
  const view = describeWindow(pending, players);
  if (!view) return null;
  if (pending.stage === "gate") {
    return <div className="pending"><strong>{view.target}</strong> 被攻击，正在确认是否需要他人挡刀…</div>;
  }
  if (pending.stage === "choice") {
    return <div className="pending"><strong>{view.target}</strong> 被攻击，{view.volunteers} 愿意挡刀，等待其选择其一或全部拒绝。</div>;
  }
  return <div className="pending"><strong>{view.target}</strong> 被攻击，干涉投票进行中：{view.summary}{view.waiting ? `；等待 ${view.waiting} 表态。` : "。"}</div>;
}

function InterventionPrompt({ view, game, events, serverTime, noAssist, noBlock, send }: {
  view: WindowDescription; game: GameState; events: GameEvent[];
  serverTime: number | undefined; noAssist: boolean; noBlock: boolean; send: Send;
}) {
  const { pending } = view;
  const remaining = useDeadlineSeconds(pending.deadline, serverTime);
  const countdown = remaining == null ? "" : `（剩 ${remaining} 秒）`;
  if (pending.stage === "gate") {
    const canAnswer = game.legalActions.some((a) => a.type === "answer-intervention-request");
    if (canAnswer && !noAssist) {
      // 匕首在攻击时已交给目标；攻击者优先取投影，缺失时才查公开事件。
      const attack = [...events].reverse().find((e) => e.eventType === "AttackDeclared" && e.payload.targetPlayerId === pending.targetPlayerId);
      const attackerId = pending.attackerPlayerId ?? (attack?.payload.attackerPlayerId as string | undefined);
      const attackerName = attackerId ? view.nameOf(attackerId) : null;
      return <ConfirmDialog
        title="是否需要他人为你挡刀？"
        body={<>{attackerName ? <>{attackerName} 对你发起攻击。</> : <>一次攻击对你发起。</>}请求挡刀将向所有有资格的玩家发起询问；若不需要或超时，你将承受这次攻击。<br />可为你挡刀的玩家：{view.roster}{countdown}</>}
        confirmText="请求挡刀" cancelText="自己承受"
        onConfirm={() => send("answer-intervention-request", { need: true })}
        onCancel={() => send("answer-intervention-request", { need: false })}
      />;
    }
    return canAnswer ? null : <div className="waiting-banner" role="status" aria-live="polite">等待 {view.target} 确认是否需要他人挡刀…{countdown}</div>;
  }
  const canRespond = game.legalActions.some((a) => a.type === "respond-intervention");
  if (pending.stage === "poll" && canRespond && !noBlock) {
    return <ConfirmDialog
      title={`是否为 ${view.target} 挡刀？`}
      body={<>为其挡刀将承受 1 点伤害并强制展示等级标记，匕首交到你手中。{countdown}</>}
      confirmText="挡刀" cancelText="不干涉"
      onConfirm={() => send("respond-intervention", { volunteer: true })}
      onCancel={() => send("respond-intervention", { volunteer: false })}
    />;
  }
  if (!canRespond) {
    if (pending.stage === "poll" && view.waiting) {
      return <div className="waiting-banner" role="status" aria-live="polite">等待 {view.waiting} 表态{countdown}</div>;
    }
    if (pending.stage === "choice") {
      return <div className="waiting-banner" role="status" aria-live="polite">{view.volunteers} 愿意挡刀，等待 {view.target} 选择{countdown}</div>;
    }
  }
  return null;
}

/**
 * 实时干涉入口。必须在房间页面所有条件 return 之前调用，保证偏好与代发
 * 去重记录随页面存活，而不是随请求、投票弹窗的挂载重置。
 * 命令可靠发送仍由 useGameSocket 负责；本模块不维护另一份重试队列。
 */
export function useIntervention({ game, events = [], serverTime, send }: {
  game: GameState | null | undefined; events?: GameEvent[]; serverTime: number | undefined; send: Send;
}) {
  const [noBlock, setNoBlock] = useState(() => localStorage.getItem(NO_BLOCK_KEY) === "1");
  const [noAssist, setNoAssist] = useState(() => localStorage.getItem(NO_ASSIST_KEY) === "1");
  const lastAutoPollKey = useRef<string | null>(null);
  const lastAutoGateKey = useRef<string | null>(null);
  const view = describeWindow(game?.pending ?? null, game?.players ?? []);
  const respondAction = game?.legalActions.find((a) => a.type === "respond-intervention");
  const answerAction = game?.legalActions.find((a) => a.type === "answer-intervention-request");
  // 保留既有 revision + deadline 去重语义；gate 另带阶段前缀。
  const pollKey = game && view && view.pending.deadline != null ? `${game.revision}:${view.pending.deadline}` : null;
  const gateKey = game && view?.pending.stage === "gate" && view.pending.deadline != null ? `gate:${game.revision}:${view.pending.deadline}` : null;
  useEffect(() => {
    if (!noBlock || !respondAction || !pollKey || lastAutoPollKey.current === pollKey) return;
    lastAutoPollKey.current = pollKey;
    send("respond-intervention", { volunteer: false });
  }, [noBlock, respondAction, pollKey, send]);
  useEffect(() => {
    if (!noAssist || !answerAction || !gateKey || lastAutoGateKey.current === gateKey) return;
    lastAutoGateKey.current = gateKey;
    send("answer-intervention-request", { need: false });
  }, [noAssist, answerAction, gateKey, send]);

  const actions = game?.legalActions ?? [];
  const choices = actions.filter((a) => a.type === "choose-intervention");
  const declineAll = actions.some((a) => a.type === "decline-intervention");
  const nameOf = (id: string | undefined) => game?.players.find((p) => p.playerId === id)?.displayName ?? "?";
  return {
    preferences: <>
      <label className="pref-toggle" title="开启后不再弹出挡刀确认，自动视为不干涉"><input type="checkbox" checked={noBlock} onChange={(e) => { setNoBlock(e.target.checked); localStorage.setItem(NO_BLOCK_KEY, e.target.checked ? "1" : "0"); }} />默认不挡刀</label>
      <label className="pref-toggle" title="开启后被攻击时不再弹出挡刀请求确认，自动视为不需要他人挡刀"><input type="checkbox" checked={noAssist} onChange={(e) => { setNoAssist(e.target.checked); localStorage.setItem(NO_ASSIST_KEY, e.target.checked ? "1" : "0"); }} />默认不让他人挡刀</label>
    </>,
    prompt: game && view ? <InterventionPrompt view={view} game={game} events={events} serverTime={serverTime} noAssist={noAssist} noBlock={noBlock} send={send} /> : null,
    choiceActions: <>
      {choices.length > 0 && <div className="action-group"><span className="action-label">选择挡刀者：</span><div className="action-buttons">{choices.map((a) => <button key={a.responderPlayerId} onClick={() => { const c = actionToCommand(a); send(c.command, c.payload); }}>{nameOf(a.responderPlayerId)}</button>)}</div></div>}
      {declineAll && <button onClick={() => send("decline-intervention")}>拒绝全部挡刀</button>}
    </>,
    otherActions: actions.filter((a) => !INTERVENTION_ACTIONS.has(a.type)),
    // 维持既有动作区空提示：只有投票应答权时显示等待，门控应答不算空。
    hasPanelActions: actions.some((a) => a.type !== "respond-intervention"),
  };
}
