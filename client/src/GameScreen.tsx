import { useEffect, useRef, useState } from "react";
import { Board } from "./Board";
import { ConfirmDialog } from "./ConfirmDialog";
import type { Action, GameEvent, GameState, PlayerView, RoomState } from "./types";
import { actionToCommand, displayPhase, displayStatus } from "./types";
import { useGameSocket } from "./useSocket";
import type { RoomCredentials } from "./Lobby";

const nameOf = (players: PlayerView[], id: string | null | undefined) => players.find((p) => p.playerId === id)?.displayName ?? "?";
const NO_BLOCK_KEY = "bloodbound:no-block";
const TIMEOUT_CHOICES = [30, 60, 90, 120, 180];

function Group({ label, children }: { label: string; children: React.ReactNode }) { return <div className="action-group"><span className="action-label">{label}：</span><div className="action-buttons">{children}</div></div>; }
function SkillUse({ actions, players, send }: { actions: Action[]; players: PlayerView[]; send: (c: string, p?: Record<string, unknown>) => void }) {
  const modes = actions.filter((a) => a.mode);
  if (modes.length) return <Group label="选择技能效果">{modes.map((a) => <button key={a.mode} onClick={() => send("choose-skill", { use: true, mode: a.mode })}>{a.mode === "harm" ? "强迫目标受伤" : "治疗目标并归还标记"}</button>)}</Group>;
  const targets = actions.filter((a) => a.targetPlayerId);
  if (targets.length) return <Group label="对其使用技能">{targets.map((a) => <button key={a.targetPlayerId} onClick={() => send("choose-skill", { use: true, targetPlayerId: a.targetPlayerId })}>{nameOf(players, a.targetPlayerId)}</button>)}</Group>;
  return <button onClick={() => send("choose-skill", { use: true })}>使用技能</button>;
}
// 审判者诅咒技能的两步发动（issue 01 / ADR 0003）：动作区先只有一个发动按钮，
// 点开才展开带真假标注的选择器，提交前弹确认框说明不可逆与保密性。
function CurseSkillUse({ game, send }: { game: GameState; send: (c: string, p?: Record<string, unknown>) => void }) {
  const curses = game.viewer?.cursesToDistribute ?? [];
  const self = game.viewer?.playerId;
  const recipients = game.players.filter((p) => p.playerId !== self && !p.captured);
  const [expanded, setExpanded] = useState(false);
  const [picks, setPicks] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);
  const ready = curses.length > 0 && curses.every((id) => picks[id]);
  const curseLabel = (id: string) => (id.startsWith("true-curse") ? "真诅咒交给：" : "假诅咒交给：");
  return <div className="curse-skill">
    <button onClick={() => setExpanded((open) => !open)}>发动能力：分发诅咒牌</button>
    {expanded && <div className="curse-picker">
      {curses.map((id) => <label key={id} className="field" htmlFor={`curse-${id}`}>{curseLabel(id)}<select id={`curse-${id}`} value={picks[id] ?? ""} onChange={(e) => setPicks({ ...picks, [id]: e.target.value })}><option value="">请选择</option>{recipients.map((p) => <option key={p.playerId} value={p.playerId}>{p.displayName}</option>)}</select></label>)}
      <button className="curse-confirm" disabled={!ready} onClick={() => setConfirming(true)}>分发</button>
    </div>}
    {confirming && <ConfirmDialog title="确认分发诅咒牌" body="分发后不可更改，归属对其他玩家永远保密。" confirmText="确认分发" cancelText="取消" onConfirm={() => { send("choose-skill", { use: true, assignments: picks }); setConfirming(false); }} onCancel={() => setConfirming(false)} />}
  </div>;
}
function ActionsPanel({ game, hostActions, send, sendHost }: { game: GameState; hostActions: Action[]; send: (c: string, p?: Record<string, unknown>) => void; sendHost: (a: string, p?: Record<string, unknown>) => void }) {
  const actions = game.legalActions ?? []; const pass = actions.filter((a) => a.type === "pass-dagger"); const attack = actions.filter((a) => a.type === "attack"); const responders = actions.filter((a) => a.type === "choose-intervention"); const declineAll = actions.find((a) => a.type === "decline-intervention"); const reveals = actions.filter((a) => a.type === "choose-reveal"); const returns = actions.filter((a) => a.type === "choose-return"); const skillUse = actions.filter((a) => a.type === "choose-skill" && a.use); const skillDecline = actions.find((a) => a.type === "choose-skill" && a.use === false); const curseWindow = game.pending?.kind === "skill" && game.pending.rank === "fleur-cross"; const locks = hostActions.filter((a) => a.type === "lock" || a.type === "unlock");
  // 干涉表态（respond-intervention）不进按钮区：由"是否为 X 挡刀？"模态弹窗承载。
  const buttonActions = actions.filter((a) => a.type !== "respond-intervention");
  if (!buttonActions.length && !locks.length) return <p className="hint">等待其他玩家行动。</p>;
  // 亮牌 / 归还的入口改为直接点击座位上闪光的槽位（issue 25）：动作面板只留提示文案。
  return <div className="actions">{pass.length > 0 && <Group label="将匕首传给">{pass.map((a) => <button key={a.targetPlayerId} onClick={() => { const c = actionToCommand(a); send(c.command, c.payload); }}>{nameOf(game.players, a.targetPlayerId)}</button>)}</Group>}{attack.length > 0 && <Group label="攻击">{attack.map((a) => <button key={a.targetPlayerId} onClick={() => { const c = actionToCommand(a); send(c.command, c.payload); }}>{nameOf(game.players, a.targetPlayerId)}</button>)}</Group>}{responders.length > 0 && <Group label="选择挡刀者">{responders.map((a) => <button key={a.responderPlayerId} onClick={() => { const c = actionToCommand(a); send(c.command, c.payload); }}>{nameOf(game.players, a.responderPlayerId)}</button>)}</Group>}{declineAll && <button onClick={() => send("decline-intervention")}>拒绝全部挡刀</button>}{(reveals.length > 0 || returns.length > 0) && <p className="hint">点击你座位上闪光的标记进行选择。</p>}{skillDecline && <button onClick={() => send("choose-skill", { use: false })}>放弃技能</button>}{skillUse.length > 0 && (curseWindow ? <CurseSkillUse game={game} send={send} /> : <SkillUse actions={skillUse} players={game.players} send={send} />)}{locks.map((a) => <button key={a.type} onClick={() => sendHost(a.type)}>{a.type === "lock" ? "锁定房间" : "解锁房间"}</button>)}</div>;
}
function WaitingRoom({ state, sendHost, spectating }: { state: RoomState; sendHost: (a: string, p?: Record<string, unknown>) => void; spectating: boolean }) {
  const players = state.game?.players ?? []; const canStart = players.length >= 6 && players.length <= 12;
  const [timeoutSeconds, setTimeoutSeconds] = useState(90);
  return <div className="waiting"><p>等待玩家加入（{players.length}/12）。分享此房间号，玩家只需房间号和姓名即可加入。</p><ul className="roster">{players.map((p) => <li key={p.playerId} className={p.playerId === state.yourPlayerId ? "self" : undefined}>{p.displayName}{p.playerId === state.yourPlayerId ? "（你）" : ""}{p.playerId === state.hostPlayerId ? "（房主）" : ""}{state.connected[p.playerId] ? "" : "（离线）"}</li>)}</ul>{spectating && <p className="hint">你正在旁观。</p>}{state.isHost && <div className="host-panel"><label className="field" htmlFor="intervention-timeout">干涉投票时限<select id="intervention-timeout" value={timeoutSeconds} onChange={(e) => setTimeoutSeconds(Number(e.target.value))}>{TIMEOUT_CHOICES.map((s) => <option key={s} value={s}>{s} 秒</option>)}</select></label><button disabled={!canStart} onClick={() => sendHost("start", { interventionTimeoutSeconds: timeoutSeconds })}>开始游戏{canStart ? "" : "（需要 6–12 名玩家）"}</button>{state.hostActions.filter((a) => a.type === "lock" || a.type === "unlock").map((a) => <button key={a.type} onClick={() => sendHost(a.type)}>{a.type === "lock" ? "锁定房间" : "解锁房间"}</button>)}</div>}<p className="hint">开始对局后干涉投票时限固定为 {state.isHost ? timeoutSeconds : (state.game?.interventionTimeoutSeconds ?? 90)} 秒，倒计时全员可见。</p></div>;
}
const eventNames: Record<string, string> = { PlayerJoined: "玩家加入", GameStarted: "游戏开始", ClueIconsShown: "全员展示阵营徽记", DaggerPassed: "匕首传递", AttackDeclared: "宣布攻击", InterventionPollOpened: "开启干涉投票", InterventionResponded: "干涉表态", InterventionChoiceOpened: "多人愿意挡刀", InterventionSelected: "挡刀发生", InterventionDeclined: "干涉未发生", DamageApplied: "造成伤害", ClueRevealed: "展示线索", SkillWindowOpened: "技能窗口开启", SkillUsed: "使用技能", SkillDeclined: "放弃技能", ResourceGranted: "获得资源", PlayerCaptured: "玩家被捕获", GameEnded: "游戏结束", PhaseChanged: "阶段变化" };
const declinedReasons: Record<string, string> = { "no-volunteers": "无人愿意挡刀", "target-declined": "被攻击者拒绝全部挡刀", "timeout-declined": "选择超时，视为全部拒绝" };
function describeEvent(e: GameEvent, players?: PlayerView[]) { const n = (id: unknown) => players?.find((p) => p.playerId === id)?.displayName ?? String(id); const p = e.payload; switch (e.eventType) { case "PlayerJoined": return `${n(p.playerId)} 加入了游戏`; case "GameStarted": return `共 ${p.playerCount} 名玩家`; case "ClueIconsShown": return "全员已向左邻展示阵营徽记"; case "DaggerPassed": return `${n(p.fromPlayerId)} → ${n(p.toPlayerId)}`; case "AttackDeclared": return `${n(p.attackerPlayerId)} 攻击了 ${n(p.targetPlayerId)}`; case "InterventionPollOpened": return `${n(p.targetPlayerId)} 被攻击，全员开始表态`; case "InterventionResponded": return `${n(p.playerId)} ${p.volunteer ? "愿意挡刀" : "不干涉"}`; case "InterventionChoiceOpened": { const volunteerIds: string[] = Array.isArray(p.volunteerPlayerIds) ? p.volunteerPlayerIds : []; return `${volunteerIds.map((id) => n(id)).join("、")} 愿意挡刀，等待 ${n(p.targetPlayerId)} 选择`; } case "InterventionSelected": return `${n(p.responderPlayerId)} 为 ${n(p.targetPlayerId)} 挡刀`; case "InterventionDeclined": return `${n(p.targetPlayerId)}：${declinedReasons[String(p.reason)] ?? "攻击正常结算"}`; case "DamageApplied": return `${n(p.targetPlayerId)} 受到 ${p.amount} 点伤害`; case "ClueRevealed": return `${n(p.playerId)} 展示了${String(p.kind) === "rank" ? "等级" : "身份"}线索`; case "SkillUsed": return `${n(p.playerId)} 使用了技能`; case "PlayerCaptured": return `${n(p.playerId)} 被捕获`; case "GameEnded": return "对局结束"; case "PhaseChanged": return `${displayPhase((p.from as { kind: string })?.kind ?? "?")} → ${displayPhase((p.to as { kind: string })?.kind ?? "?")}`; default: return ""; } }
function EventLog({ events, players }: { events: GameEvent[]; players?: PlayerView[] }) { if (!events.length) return null; return <details className="log"><summary>事件日志（{events.length}）</summary><ol aria-live="polite">{events.slice(-60).reverse().map((e) => <li key={e.eventId}>{eventNames[e.eventType] ?? "游戏事件"} {describeEvent(e, players)}</li>)}</ol></details>; }
function Banner({ title, detail, onBack }: { title: string; detail: string; onBack: () => void }) { return <section className="banner" aria-labelledby="banner-title"><h2 id="banner-title">{title}</h2><p>{detail}</p><button onClick={onBack}>返回大厅</button></section>; }
const errorText = (code: string, _message: string) => ({ "room.locked": "房间已锁定。", "room.already-started": "游戏已经开始。", "game.player-count": "玩家人数必须为 6–12 人。", "player.name-required": "姓名不能为空。" } as Record<string, string>)[code] ?? "操作未完成，请检查当前阶段和操作条件。";

/** 服务端墙钟锚定 + 本地每秒跳动的倒计时；仅在干涉窗口存在时启用。 */
function useDeadlineSeconds(deadline: number | null | undefined, serverTime: number | undefined) {
  const offsetRef = useRef(0);
  const [remaining, setRemaining] = useState<number | null>(null);
  useEffect(() => { if (typeof serverTime === "number") offsetRef.current = serverTime - Date.now() / 1000; }, [serverTime]);
  useEffect(() => {
    if (deadline == null) { setRemaining(null); return; }
    const tick = () => setRemaining(Math.max(0, Math.round(deadline - (Date.now() / 1000 + offsetRef.current))));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [deadline]);
  return remaining;
}

function InterventionPollLayer({ game, serverTime, noBlock, send }: { game: GameState; serverTime: number | undefined; noBlock: boolean; send: (c: string, p?: Record<string, unknown>) => void }) {
  const pending = game.pending;
  const isIntervention = pending?.kind === "intervention";
  const respondAction = game.legalActions.find((a) => a.type === "respond-intervention");
  const remaining = useDeadlineSeconds(isIntervention ? pending.deadline : null, serverTime);
  const countdown = remaining == null ? "" : `（剩 ${remaining} 秒）`;
  const names = (ids: string[]) => ids.map((id) => nameOf(game.players, id)).join("、");
  // 未表态者列表：有资格但还没答的人
  const waitingIds = isIntervention && pending.stage === "poll"
    ? pending.eligiblePlayerIds.filter((id) => pending.responses?.[id] === undefined)
    : [];
  // 表态确认弹窗：本人有表态权且未开"默认不挡刀"时弹出（开关开启时由上层自动代发）
  if (isIntervention && pending.stage === "poll" && respondAction && !noBlock) {
    return <ConfirmDialog
      title={`是否为 ${nameOf(game.players, pending.targetPlayerId)} 挡刀？`}
      body={<>为其挡刀将承受 1 点伤害并强制展示等级标记，匕首交到你手中。{countdown}</>}
      confirmText="挡刀"
      cancelText="不干涉"
      onConfirm={() => send("respond-intervention", { volunteer: true })}
      onCancel={() => send("respond-intervention", { volunteer: false })}
    />;
  }
  // 等待横幅：投票阶段等未表态者，三选一阶段等被攻击者
  if (isIntervention && !respondAction) {
    if (pending.stage === "poll" && waitingIds.length > 0) {
      return <div className="waiting-banner" role="status" aria-live="polite">等待 {names(waitingIds)} 表态{countdown}</div>;
    }
    if (pending.stage === "choice") {
      return <div className="waiting-banner" role="status" aria-live="polite">{names(pending.volunteerPlayerIds ?? [])} 愿意挡刀，等待 {nameOf(game.players, pending.targetPlayerId)} 选择{countdown}</div>;
    }
  }
  return null;
}

export function GameScreen({ credentials, onLeave }: { credentials: RoomCredentials; onLeave: () => void }) {
  const { state, events, error, closed, reconnecting, takenOver, send, sendHost } = useGameSocket(credentials.code, credentials.name, credentials.token);
  const [noBlock, setNoBlock] = useState(() => localStorage.getItem(NO_BLOCK_KEY) === "1");
  const lastAutoPollKey = useRef<string | null>(null);
  const pending = state?.game?.pending ?? null;
  const respondAction = state?.game?.legalActions.find((a) => a.type === "respond-intervention");
  const pollKey = state?.game && pending?.kind === "intervention" && pending.deadline != null ? `${state.game.revision}:${pending.deadline}` : null;

  // "默认不挡刀"：开关开启时收到表态权即自动代发"不干涉"；对局中随时可改，
  // 已表态不受影响（代发只对当前未表态的投票生效，每个投票只代发一次）。
  // 必须位于所有条件 return 之前，保证 Hook 顺序稳定。
  useEffect(() => {
    if (!noBlock || !respondAction || !pollKey) return;
    if (lastAutoPollKey.current === pollKey) return;
    lastAutoPollKey.current = pollKey;
    send("respond-intervention", { volunteer: false });
  }, [noBlock, respondAction, pollKey, send]);

  if (takenOver) return <Banner title="座位已被接管" detail="同名的新连接已接管此座位，请使用其他姓名重新加入，或等待连接恢复。" onBack={onLeave} />;
  if (closed && !state && !reconnecting) return <Banner title="连接已断开" detail="房间连接在收到游戏状态前已关闭。" onBack={onLeave} />;
  if (error && !state) return <Banner title="无法加入房间" detail={errorText(error.code, error.message)} onBack={onLeave} />;
  if (!state) return <div className="loading" role="status" aria-live="polite">正在连接……</div>;
  const spectating = state.yourPlayerId === null;
  const showTable = state.roomStatus === "playing" || state.roomStatus === "ended";
  const game = state.game;

  const toggleNoBlock = (value: boolean) => {
    setNoBlock(value);
    localStorage.setItem(NO_BLOCK_KEY, value ? "1" : "0");
  };

  // 槽位点击入口：Board 把可点槽位映射回 choose-reveal / choose-return 动作，这里统一转成命令发送。
  const sendSlotAction = (action: Action) => {
    const c = actionToCommand(action);
    send(c.command, c.payload);
  };

  return <div className="room"><header className="room-header"><span>房间 <strong>{state.roomCode}</strong>{state.locked ? " 🔒" : ""} {state.isHost ? "（房主）" : ""}</span><span className="status" role="status" aria-live="polite">{displayStatus(state.roomStatus)}</span>{reconnecting && <span className="hint" role="status" aria-live="polite">正在重新连接……</span>}{showTable && !spectating && <label className="pref-toggle" title="开启后不再弹出挡刀确认，自动视为不干涉"><input type="checkbox" checked={noBlock} onChange={(e) => toggleNoBlock(e.target.checked)} />默认不挡刀</label>}<button onClick={onLeave}>离开</button></header>{error && <div className="action-error" role="alert" aria-live="assertive">{errorText(error.code, error.message)}</div>}{showTable && game ? <><Board game={game} onSlotAction={sendSlotAction} />{pending?.kind === "intervention" && <InterventionPollLayer game={game} serverTime={state.serverTime} noBlock={noBlock} send={send} />}<ActionsPanel game={game} hostActions={state.hostActions} send={send} sendHost={sendHost} /></> : <WaitingRoom state={state} sendHost={sendHost} spectating={spectating} />}<EventLog events={events} players={game?.players} /></div>;
}
