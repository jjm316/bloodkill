import { useEffect, useState } from "react";
import { Board } from "./Board";
import { useIntervention } from "./intervention";
import { useDeadlineSeconds } from "./useDeadlineSeconds";
import { ConfirmDialog } from "./ConfirmDialog";
import { RulesOverlay } from "./HelpOverlay";
import { EventLog } from "./EventLogView";
import { Icon } from "./icons";
import { useMemoMarkers } from "./memoMarkers";
import type { Action, GameState, PlayerView, RoomState } from "./types";
import { actionToCommand, APP_TITLE, displayStatus } from "./types";
import { useGameSocket } from "./useSocket";
import type { RoomCredentials } from "./Lobby";

const nameOf = (players: PlayerView[], id: string | null | undefined) => players.find((p) => p.playerId === id)?.displayName ?? "?";
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
function ActionsPanel({ game, intervention, hostActions, send, sendHost }: { game: GameState; intervention: ReturnType<typeof useIntervention>; hostActions: Action[]; send: (c: string, p?: Record<string, unknown>) => void; sendHost: (a: string, p?: Record<string, unknown>) => void }) {
  const actions = intervention.otherActions; const pass = actions.filter((a) => a.type === "pass-dagger"); const attack = actions.filter((a) => a.type === "attack"); const reveals = actions.filter((a) => a.type === "choose-reveal"); const returns = actions.filter((a) => a.type === "choose-return"); const skillUse = actions.filter((a) => a.type === "choose-skill" && a.use); const skillDecline = actions.find((a) => a.type === "choose-skill" && a.use === false); const curseWindow = game.pending?.kind === "skill" && game.pending.rank === "fleur-cross"; const locks = hostActions.filter((a) => a.type === "lock" || a.type === "unlock");
  if (!intervention.hasPanelActions && !locks.length) return <p className="hint">等待其他玩家行动。</p>;
  // 亮牌 / 归还的入口改为直接点击座位上闪光的槽位（issue 25）：动作面板只留提示文案。
  return <div className="actions">{pass.length > 0 && <Group label="将匕首传给">{pass.map((a) => <button key={a.targetPlayerId} onClick={() => { const c = actionToCommand(a); send(c.command, c.payload); }}>{nameOf(game.players, a.targetPlayerId)}</button>)}</Group>}{attack.length > 0 && <Group label="攻击">{attack.map((a) => <button key={a.targetPlayerId} onClick={() => { const c = actionToCommand(a); send(c.command, c.payload); }}>{nameOf(game.players, a.targetPlayerId)}</button>)}</Group>}{intervention.choiceActions}{(reveals.length > 0 || returns.length > 0) && <p className="hint">点击你座位上闪光的标记进行选择。</p>}{skillDecline && <button onClick={() => send("choose-skill", { use: false })}>放弃技能</button>}{skillUse.length > 0 && (curseWindow ? <CurseSkillUse game={game} send={send} /> : <SkillUse actions={skillUse} players={game.players} send={send} />)}{locks.map((a) => <button key={a.type} onClick={() => sendHost(a.type)}>{a.type === "lock" ? "锁定房间" : "解锁房间"}</button>)}</div>;
}
export function WaitingRoom({ state, sendHost, spectating }: { state: RoomState; sendHost: (a: string, p?: Record<string, unknown>) => void; spectating: boolean }) {
  const players = state.game?.players ?? []; const canStart = players.length >= 6 && players.length <= 12;
  const [timeoutSeconds, setTimeoutSeconds] = useState(90);
  // 单人窗口超时（ADR 0011）：三类单人窗口共用一份时限，与干涉时限分开配置。
  const [singleTimeoutSeconds, setSingleTimeoutSeconds] = useState(90);
  return <div className="waiting"><p>等待玩家加入（{players.length}/12）。分享此房间号，玩家只需房间号和姓名即可加入。</p><ul className="roster">{players.map((p) => <li key={p.playerId} className={p.playerId === state.yourPlayerId ? "self" : undefined}>{p.displayName}{p.playerId === state.yourPlayerId ? "（你）" : ""}{p.playerId === state.hostPlayerId ? "（房主）" : ""}{state.connected[p.playerId] ? "" : "（离线）"}</li>)}</ul>{spectating && <p className="hint">你正在旁观。</p>}{state.isHost && <div className="host-panel"><label className="field" htmlFor="intervention-timeout">干涉投票时限<select id="intervention-timeout" value={timeoutSeconds} onChange={(e) => setTimeoutSeconds(Number(e.target.value))}>{TIMEOUT_CHOICES.map((s) => <option key={s} value={s}>{s} 秒</option>)}</select></label><label className="field" htmlFor="single-window-timeout">单人窗口超时<select id="single-window-timeout" value={singleTimeoutSeconds} onChange={(e) => setSingleTimeoutSeconds(Number(e.target.value))}>{TIMEOUT_CHOICES.map((s) => <option key={s} value={s}>{s} 秒</option>)}</select></label><button disabled={!canStart} onClick={() => sendHost("start", { interventionTimeoutSeconds: timeoutSeconds, singleWindowTimeoutSeconds: singleTimeoutSeconds })}>开始游戏{canStart ? "" : "（需要 6–12 名玩家）"}</button>{state.hostActions.filter((a) => a.type === "lock" || a.type === "unlock").map((a) => <button key={a.type} onClick={() => sendHost(a.type)}>{a.type === "lock" ? "锁定房间" : "解锁房间"}</button>)}</div>}<p className="hint">开始对局后干涉投票时限固定为 {state.isHost ? timeoutSeconds : (state.game?.interventionTimeoutSeconds ?? 90)} 秒、单人窗口超时固定为 {state.isHost ? singleTimeoutSeconds : (state.game?.singleWindowTimeoutSeconds ?? 90)} 秒，倒计时全员可见；单人窗口到期将自动执行默认操作。</p></div>;
}
function Banner({ title, detail, onBack }: { title: string; detail: string; onBack: () => void }) { return <section className="banner" aria-labelledby="banner-title"><h2 id="banner-title">{title}</h2><p>{detail}</p><button onClick={onBack}>返回大厅</button></section>; }
const errorText = (code: string, _message: string) => ({ "room.not-found": "房间不存在，请核对房间号。", "room.locked": "房间已锁定。", "room.already-started": "游戏已经开始。", "game.player-count": "玩家人数必须为 6–12 人。", "player.name-required": "姓名不能为空。" } as Record<string, string>)[code] ?? "操作未完成，请检查当前阶段和操作条件。";

// 单人窗口（亮牌/技能/退牌）等待横幅（ADR 0011）：带服务端倒计时，
// 并直接告知"超时会替你做什么"，当事人与旁观者看到同一句话。
const SINGLE_WINDOW_TEXT: Record<string, { waiting: string; timeout: string }> = {
  reveal: { waiting: "亮出线索", timeout: "超时将自动亮出排序第一张标记（万能标记记为「？」）" },
  skill: { waiting: "决定是否使用技能", timeout: "超时视为放弃技能，将永久失去" },
  "token-return": { waiting: "归还标记", timeout: "超时将自动退回排序第一张已亮标记" },
};
export function SingleWindowLayer({ game, serverTime }: { game: GameState; serverTime: number | undefined }) {
  const pending = game.pending;
  const text = pending ? SINGLE_WINDOW_TEXT[pending.kind] : undefined;
  const remaining = useDeadlineSeconds(pending && text ? pending.deadline : null, serverTime);
  if (!pending || !text) return null;
  const countdown = remaining == null ? "" : `（剩 ${remaining} 秒）`;
  return (
    <div className="waiting-banner" role="status" aria-live="polite">
      等待 {nameOf(game.players, pending.actorPlayerId)} {text.waiting}
      {countdown}，{text.timeout}。
    </div>
  );
}

export function GameScreen({ credentials, onLeave }: { credentials: RoomCredentials; onLeave: () => void }) {
  const { state, events, error, closed, reconnecting, takenOver, failed, send, sendHost } = useGameSocket(credentials.code, credentials.name, credentials.token);
  const intervention = useIntervention({ game: state?.game, events, serverTime: state?.serverTime, send });
  const [rulesOpen, setRulesOpen] = useState(false);

  // 备忘标记（ADR 0004）：纯本机私有状态，Hook 必须位于所有条件 return 之前。
  const memos = useMemoMarkers(credentials.code, state?.game);

  // 标签页标题：进房后带房间号，多窗口/手机多标签可区分；卸载（离开房间）还原。
  // 同样必须位于条件 return 之前。
  const roomCodeOfState = state?.roomCode;
  useEffect(() => {
    if (!roomCodeOfState) return;
    document.title = `${APP_TITLE} #${roomCodeOfState}`;
    return () => {
      document.title = APP_TITLE;
    };
  }, [roomCodeOfState]);

  if (takenOver) return <Banner title="座位已被接管" detail="同名的新连接已接管此座位，请使用其他姓名重新加入，或等待连接恢复。" onBack={onLeave} />;
  if (closed && !state && !reconnecting) return <Banner title="连接已断开" detail="房间连接在收到游戏状态前已关闭。" onBack={onLeave} />;
  if (error && !state) return <Banner title="无法加入房间" detail={errorText(error.code, error.message)} onBack={onLeave} />;
  // 初始进房超时（服务器未启动/网络不通/无应答）：服务端错误帧优先给出具体原因。
  if (failed && !state) return <Banner title="无法加入房间" detail="连接超时，请核对房间号；若房间号正确，请确认服务器已启动。" onBack={onLeave} />;
  if (!state) return <div className="loading" role="status" aria-live="polite">正在连接……</div>;
  const spectating = state.yourPlayerId === null;
  const showTable = state.roomStatus === "playing" || state.roomStatus === "ended";
  const game = state.game;

  // 槽位点击入口：Board 把可点槽位映射回 choose-reveal / choose-return 动作，这里统一转成命令发送。
  const sendSlotAction = (action: Action) => {
    const c = actionToCommand(action);
    send(c.command, c.payload);
  };

  return <div className="room"><header className="room-header"><span>房间 <strong>{state.roomCode}</strong>{state.locked && <span className="room-lock" title="房间已锁定"><Icon name="lock" /></span>} {state.isHost ? "（房主）" : ""}</span><span className="status" role="status" aria-live="polite">{displayStatus(state.roomStatus)}</span>{reconnecting && <span className="hint" role="status" aria-live="polite">正在重新连接……</span>}{showTable && !spectating && intervention.preferences}<button className="help-button" onClick={() => setRulesOpen(true)} title="规则与图例" aria-label="规则与图例"><Icon name="help" /></button><button onClick={onLeave}>离开</button></header>{error && <div className="action-error" role="alert" aria-live="assertive">{errorText(error.code, error.message)}</div>}{showTable && game ? <><Board game={game} onSlotAction={sendSlotAction} memos={memos} />{intervention.prompt}<SingleWindowLayer game={game} serverTime={state.serverTime} /><ActionsPanel game={game} intervention={intervention} hostActions={state.hostActions} send={send} sendHost={sendHost} /></> : <WaitingRoom state={state} sendHost={sendHost} spectating={spectating} />}{rulesOpen && <RulesOverlay onClose={() => setRulesOpen(false)} />}<EventLog events={events} players={game?.players} /></div>;
}
