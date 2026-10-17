import { useEffect, useRef, useState } from "react";
import { Board } from "./Board";
import { curseTruthOf } from "./curseReveal";
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
export function SkillUse({ actions, players, send }: { actions: Action[]; players: PlayerView[]; send: (c: string, p?: Record<string, unknown>) => void }) {
  const modes = actions.filter((a) => a.mode);
  if (modes.length) return <Group label="选择技能效果">{modes.map((a) => <button key={a.mode} onClick={() => send("choose-skill", { use: true, mode: a.mode })}>{a.mode === "harm" ? "强迫目标受伤" : "治疗目标并归还标记"}</button>)}</Group>;
  const targets = actions.filter((a) => a.targetPlayerId);
  if (targets.length) return <Group label="对其使用技能">{targets.map((a) => <button key={a.targetPlayerId} onClick={() => send("choose-skill", { use: true, targetPlayerId: a.targetPlayerId })}>{nameOf(players, a.targetPlayerId)}</button>)}</Group>;
  const pairs = actions.filter((a) => Array.isArray(a.targetPlayerIds));
  if (pairs.length) return <HarlequinInspectUse actions={pairs} players={players} send={send} />;
  return <button onClick={() => send("choose-skill", { use: true })}>使用技能</button>;
}
// 等级3（小丑）检视：投影为每个可选两人组合各下发一个动作（targetPlayerIds）。
// 组合数随人数平方增长（7 人局 15 个、11 人局 45 个），逐组合按钮墙不可用——
// 改为两步下拉选出两名不同玩家（CurseSkillUse 同族交互）；未选满前按钮禁用，
// 杜绝发出裸 {use:true} 被引擎以 skill.invalid-target 拒绝的 bug 路径。
function HarlequinInspectUse({ actions, players, send }: { actions: Action[]; players: PlayerView[]; send: (c: string, p?: Record<string, unknown>) => void }) {
  const combos = actions.map((a) => a.targetPlayerIds as string[]);
  const candidateIds = [...new Set(combos.flat())];
  const [picks, setPicks] = useState<[string, string]>(["", ""]);
  const ready =
    picks[0] !== "" && picks[1] !== "" && picks[0] !== picks[1] &&
    combos.some((ids) => ids.includes(picks[0]) && ids.includes(picks[1]));
  const options = <>
    <option value="">请选择</option>
    {candidateIds.map((id) => <option key={id} value={id}>{nameOf(players, id)}</option>)}
  </>;
  return <div className="inspect-picker">
    <label className="field" htmlFor="inspect-first">第一位检视对象<select id="inspect-first" value={picks[0]} onChange={(e) => setPicks([e.target.value, picks[1]])}>{options}</select></label>
    <label className="field" htmlFor="inspect-second">第二位检视对象<select id="inspect-second" value={picks[1]} onChange={(e) => setPicks([picks[0], e.target.value])}>{options}</select></label>
    <button className="inspect-confirm" disabled={!ready} onClick={() => send("choose-skill", { use: true, targetPlayerIds: [picks[0], picks[1]] })}>使用技能</button>
  </div>;
}
// 审判者诅咒技能的两步发动（issue 01 / ADR 0003）：动作区先只有一个发动按钮，
// 点开才展开带真假标注的选择器，提交前弹确认框说明不可逆与可见性
// （ADR 0014：持卡归属全员公开，真/假之分仅审判者可知、终局翻开）。
function CurseSkillUse({ game, send }: { game: GameState; send: (c: string, p?: Record<string, unknown>) => void }) {
  const curses = game.viewer?.cursesToDistribute ?? [];
  const self = game.viewer?.playerId;
  const recipients = game.players.filter((p) => p.playerId !== self && !p.captured);
  const [expanded, setExpanded] = useState(false);
  const [picks, setPicks] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);
  const ready = curses.length > 0 && curses.every((id) => picks[id]);
  // 分发选择器的字段标签：真假判定走共享的 curseTruthOf（./curseReveal 唯一前缀
  // 嗅探点）；标签文案是本交互专属（「真/假诅咒交给：」），与座位药丸的
  // 「真咒/假咒/咒」（cursePillLabel）是两个呈现，不再共用 curseLabel 这个名字。
  const curseFieldLabel = (id: string) => (curseTruthOf(id) === "true" ? "真诅咒交给：" : "假诅咒交给：");
  return <div className="curse-skill">
    <button onClick={() => setExpanded((open) => !open)}>发动能力：分发诅咒牌</button>
    {expanded && <div className="curse-picker">
      {curses.map((id) => <label key={id} className="field" htmlFor={`curse-${id}`}>{curseFieldLabel(id)}<select id={`curse-${id}`} value={picks[id] ?? ""} onChange={(e) => setPicks({ ...picks, [id]: e.target.value })}><option value="">请选择</option>{recipients.map((p) => <option key={p.playerId} value={p.playerId}>{p.displayName}</option>)}</select></label>)}
      <button className="curse-confirm" disabled={!ready} onClick={() => setConfirming(true)}>分发</button>
    </div>}
    {confirming && <ConfirmDialog title="确认分发诅咒牌" body="分发后不可更改；持卡归属对全员公开（座位上出现紫色「咒」药丸），真/假之分仅你可知，终局全员翻开。" confirmText="确认分发" cancelText="取消" onConfirm={() => { send("choose-skill", { use: true, assignments: picks }); setConfirming(false); }} onCancel={() => setConfirming(false)} />}
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
  return <div className="waiting"><p>等待玩家加入（{players.length}/12）。分享此房间号，好友登录账号后输入房间号即可加入。</p><ul className="roster">{players.map((p) => <li key={p.playerId} className={p.playerId === state.yourPlayerId ? "self" : undefined}>{p.displayName}{p.playerId === state.yourPlayerId ? "（你）" : ""}{p.playerId === state.hostPlayerId ? "（房主）" : ""}{state.connected[p.playerId] ? "" : "（离线）"}</li>)}</ul>{spectating && <p className="hint">你正在旁观。</p>}{state.isHost && <div className="host-panel"><label className="field" htmlFor="intervention-timeout">干涉投票时限<select id="intervention-timeout" value={timeoutSeconds} onChange={(e) => setTimeoutSeconds(Number(e.target.value))}>{TIMEOUT_CHOICES.map((s) => <option key={s} value={s}>{s} 秒</option>)}</select></label><label className="field" htmlFor="single-window-timeout">单人窗口超时<select id="single-window-timeout" value={singleTimeoutSeconds} onChange={(e) => setSingleTimeoutSeconds(Number(e.target.value))}>{TIMEOUT_CHOICES.map((s) => <option key={s} value={s}>{s} 秒</option>)}</select></label><button disabled={!canStart} onClick={() => sendHost("start", { interventionTimeoutSeconds: timeoutSeconds, singleWindowTimeoutSeconds: singleTimeoutSeconds })}>开始游戏{canStart ? "" : "（需要 6–12 名玩家）"}</button>{state.hostActions.filter((a) => a.type === "lock" || a.type === "unlock").map((a) => <button key={a.type} onClick={() => sendHost(a.type)}>{a.type === "lock" ? "锁定房间" : "解锁房间"}</button>)}</div>}<p className="hint">开始对局后干涉投票时限固定为 {state.isHost ? timeoutSeconds : (state.game?.interventionTimeoutSeconds ?? 90)} 秒、单人窗口超时固定为 {state.isHost ? singleTimeoutSeconds : (state.game?.singleWindowTimeoutSeconds ?? 90)} 秒，倒计时全员可见；单人窗口到期将自动执行默认操作。</p></div>;
}
function Banner({ title, detail, onBack, returnTo, actionText = "返回大厅" }: { title: string; detail: string; onBack: () => void; returnTo?: { code: string; onReturn: (code: string) => void }; actionText?: string }) {
  return <section className="banner" aria-labelledby="banner-title"><h2 id="banner-title">{title}</h2><p>{detail}</p>{returnTo && <button onClick={() => returnTo.onReturn(returnTo.code)}>返回房间 {returnTo.code}</button>}<button onClick={onBack}>{actionText}</button></section>;
}
const errorText = (code: string, _message: string, mode: "player" | "spectator" = "player") => ({ "room.not-found": "房间不存在，请核对房间号。", "room.locked": "房间已锁定，暂不能加入。", "room.already-started": "游戏已经开始。", "room.full": "房间已满员（12 人），不能加入。", "room.ended": mode === "spectator" ? "对局已结束，不能旁观；可观看回放。" : "对局已结束，不能加入；可观看回放。", "room.admin-closed": "房间已被管理员关闭，请返回大厅创建或加入新的房间。", "account.room-occupied": "你已有未结束房间，请返回原房间。", "spectator.seat-held": "你已有未结束房间的玩家座位，不能同时旁观。", "spectator.became-player": "当前账号已作为玩家进入房间，本旁观连接已停止。", "game.player-count": "玩家人数必须为 6–12 人。", "auth.login-required": "请先登录后进入房间。", "auth.session-expired": "登录已过期，请重新登录。", "auth.session-revoked": "当前登录已退出，请重新登录。", "auth.password-changed": "密码已修改，请重新登录。", "protocol.version-mismatch": "客户端版本已更新，请刷新页面。", "protocol.legacy-identity": "请刷新页面，房间使用当前登录账号。", "room.host-seat-kept": "房主返回大厅不会退座；你的座位和房主身份会保留，可随时返回本房间。", "room.in-progress": "对局进行中不能退出座位；返回大厅仅断开连接，你的座位会保留。", "seat.not-held": "你在此房间没有座位。" } as Record<string, string>)[code] ?? "操作未完成，请检查当前阶段和操作条件。";

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

export function GameScreen({ credentials, onLeave, onReturnToRoom, onAuthLost }: { credentials: RoomCredentials; onLeave: () => void; onReturnToRoom?: (code: string) => void; onAuthLost?: () => void }) {
  const { state, events, error, closed, reconnecting, takenOver, failed, left, send, sendHost, sendLeave } = useGameSocket(credentials.code, credentials.accountId, credentials.mode);
  // 干预偏好按账号隔离（工单 18）：A 的偏好不得驱动 B 的自动挡刀命令。
  const intervention = useIntervention({ accountId: credentials.accountId, game: state?.game, events, serverTime: state?.serverTime, send });
  const [rulesOpen, setRulesOpen] = useState(false);

  // 备忘标记（ADR 0004）：纯本机私有状态，Hook 必须位于所有条件 return 之前。
  // 按账号隔离（工单 18）：存储键含 credentials.accountId，App 层以 accountId
  // 为 key 重挂载，切账号后各读各的，互不继承。
  const memos = useMemoMarkers(credentials.accountId, credentials.code, state?.game);

  // 工单 13：服务端确认退座（left 帧）后才回大厅——真退座不伪装成本地离开。
  const onLeaveRef = useRef(onLeave);
  onLeaveRef.current = onLeave;
  useEffect(() => {
    if (left) onLeaveRef.current();
  }, [left]);

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

  // 会话失效（工单 14）：过期/撤销的 auth.* 终止帧已停止重连（useSocket），
  // 这里给出独立的重新登录入口，而不是伪装成普通进房失败。
  const sessionLost = failed && error !== null && error.code.startsWith("auth.");
  if (sessionLost && onAuthLost) return <Banner title="登录已失效" detail={errorText(error!.code, error!.message)} onBack={onAuthLost} actionText="重新登录" />;
  if (takenOver) return <Banner title="座位已被接管" detail="已在其他设备进入房间，本设备已停止操作和自动重连；账号仍保持登录，可返回大厅查看房间。" onBack={onLeave} />;
  // 旁观停止（工单 16）：账号成为玩家后服务端终止了本旁观连接（useSocket
  // 已停止重连），给出独立说明而不是伪装成进房失败或断线。
  const spectatorStopped = failed && error !== null && error.code === "spectator.became-player";
  if (spectatorStopped) return <Banner title="旁观已停止" detail={errorText(error.code, error.message, credentials.mode)} onBack={onLeave} />;
  // 管理关闭（工单 21）：终止帧到达即说明房间已被管理员关闭，不是断线，
  // 给出独立说明与返回大厅路径，而不是伪装成重连中。
  if (error && error.code === "room.admin-closed") return <Banner title="房间已被管理员关闭" detail="该房间已被管理员关闭并停止运行；不会产生胜负或身份揭晓，你可以返回大厅创建或加入新的房间。" onBack={onLeave} />;
  if (closed && !state && !reconnecting) return <Banner title="连接已断开" detail="房间连接在收到游戏状态前已关闭。" onBack={onLeave} />;
  // 一房占用拒绝（工单 12）与旁观互斥拒绝（工单 16）：错误帧携带 details.roomCode，
  // 失败页直接提供返回原房入口。
  const occupiedRoomCode = error && !state && (error.code === "account.room-occupied" || error.code === "spectator.seat-held") && typeof error.details?.roomCode === "string" && /^\d{6}$/.test(error.details.roomCode)
    ? error.details.roomCode
    : undefined;
  if (error && !state) return <Banner title="无法加入房间" detail={errorText(error.code, error.message, credentials.mode)} onBack={onLeave} returnTo={occupiedRoomCode && onReturnToRoom ? { code: occupiedRoomCode, onReturn: onReturnToRoom } : undefined} />;
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

  // 工单 13：只有「等待阶段的普通玩家」退出房间是真退座（服务端释放座位）；
  // 房主与对局中/旁观的离开都是「返回大厅」——仅断开连接，座位与占用保留。
  const seatExit = state.roomStatus === "waiting" && !spectating && !state.isHost;

  return <div className="room"><header className="room-header"><span>房间 <strong>{state.roomCode}</strong>{state.locked && <span className="room-lock" title="房间已锁定"><Icon name="lock" /></span>} {state.isHost ? "（房主）" : ""}</span><span className="status" role="status" aria-live="polite">{displayStatus(state.roomStatus)}</span>{reconnecting && <span className="hint" role="status" aria-live="polite">正在重新连接……</span>}{showTable && !spectating && intervention.preferences}<button className="help-button" onClick={() => setRulesOpen(true)} title="规则与图例" aria-label="规则与图例"><Icon name="help" /></button><button onClick={seatExit ? sendLeave : onLeave}>{seatExit ? "退出房间" : "返回大厅"}</button></header>{error && <div className="action-error" role="alert" aria-live="assertive">{errorText(error.code, error.message, credentials.mode)}</div>}{showTable && game ? <><Board game={game} onSlotAction={sendSlotAction} memos={memos} />{intervention.prompt}<SingleWindowLayer game={game} serverTime={state.serverTime} /><ActionsPanel game={game} intervention={intervention} hostActions={state.hostActions} send={send} sendHost={sendHost} /></> : <WaitingRoom state={state} sendHost={sendHost} spectating={spectating} />}{rulesOpen && <RulesOverlay onClose={() => setRulesOpen(false)} />}<EventLog accountId={credentials.accountId} events={events} players={game?.players} /></div>;
}
