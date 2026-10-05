// Wire types mirroring the server protocol (see server/PROTOCOL.md).

export type RoomStatus = "waiting" | "playing" | "ended";

export interface Action {
  type: string;
  targetPlayerId?: string;
  targetPlayerIds?: string[];
  responderPlayerId?: string;
  volunteer?: boolean;
  /** answer-intervention-request：门控确认是否请求他人挡刀 */
  need?: boolean;
  use?: boolean;
  token?: string;
  color?: string;
  mode?: string;
}

export interface Identity {
  faction: string;
  rank: number | string;
}

export interface PlayerView {
  playerId: string;
  seat: number;
  displayName: string;
  damage: number;
  captured: boolean;
  revealed: { rank?: number | string; markers: [string | null, string | null] };
  identityMarkers: [string | null, string | null];
  resources: Record<string, number>;
}

export interface ViewerView {
  playerId: string;
  identity: Identity;
  identityMarkers: string[];
  resources: Record<string, number>;
  skillsUsed: string[];
  inspections: Record<string, { faction: string | null; rank: number | string | null }>;
  cursesToDistribute: string[];
  clueIcon: string | null;
  seenNeighbourClue: { playerId: string; icon: string | null } | null;
}

export interface PendingView {
  kind: string;
  actorPlayerId: string;
  targetPlayerId: string | null;
  eligiblePlayerIds: string[];
  rank: number | string | null;
  trigger: string | null;
  eligibleTokens?: string[];
  forceRank?: boolean;
  /** 干涉投票：gate = 被攻击者挡刀请求门控（ADR 0012）；poll = 逐人表态阶段；choice = 被攻击者三选一阶段 */
  stage?: string;
  /** 攻击者（公开信息；门控弹窗点名用，重连无事件回放也能渲染） */
  attackerPlayerId?: string | null;
  /** 实时公开表态：playerId -> 是否愿意挡刀 */
  responses?: Record<string, boolean>;
  volunteerPlayerIds?: string[];
  /** 服务端注入的到期时间（Unix 秒），干涉与单人窗口存在时非空 */
  deadline?: number | null;
}

export interface GameResult {
  winner: string;
  branch: string;
  capturedPlayerId: string;
  activePlayerId: string | null;
  ranking: { playerId: string; place: number; score: number }[];
  explanationKey: string;
}

export interface GameState {
  gameId: string;
  revision: number;
  status: string;
  players: PlayerView[];
  daggerHolderId: string | null;
  phase: { kind: string; stage?: string; activePlayerId?: string };
  pending: PendingView | null;
  result: GameResult | null;
  viewer: ViewerView | null;
  legalActions: Action[];
  interventionTimeoutSeconds?: number;
  singleWindowTimeoutSeconds?: number;
}

export interface RoomState {
  type: "state";
  roomCode: string;
  roomStatus: RoomStatus;
  locked: boolean;
  isHost: boolean;
  yourPlayerId: string | null;
  hostPlayerId: string | null;
  connected: Record<string, boolean>;
  hostActions: Action[];
  game: GameState | null;
  /** 服务端墙钟（Unix 秒），用于倒计时对齐 */
  serverTime: number;
}

export interface GameEvent {
  eventId: string;
  eventType: string;
  gameId: string;
  revision: number;
  timestamp: number;
  commandId: string;
  payload: Record<string, unknown>;
}

export interface ServerError {
  type: "error";
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface CommandAck {
  type: "ack";
  commandId: string;
  status: "accepted" | "rejected";
  revision: number;
  error?: Omit<ServerError, "type">;
}

export function actionToCommand(action: Action): { command: string; payload: Record<string, unknown> } {
  const { type, ...payload } = action;
  return { command: type, payload };
}

export function displayFaction(faction: string): string {
  if (faction === "rose") return "玫瑰家族";
  if (faction === "beast") return "野兽家族";
  if (faction === "secret-order") return "审判者";
  if (faction === "draw") return "平局";
  return faction;
}

export function displayClueIcon(icon: string | null | undefined): string {
  if (icon === "rose") return "玫瑰";
  if (icon === "beast") return "野兽";
  return "未知";
}

// 亮出的等级只暴露数字本身（issue 23）：对局实时显示（亮牌槽、技能横幅、
// 事件日志）不出现角色名；官方角色名仅存在于帮助浮层的静态文案（ADR 0005）。
export function displayRank(rank: number | string): string {
  if (rank === "fleur-cross") return "审判者";
  return typeof rank === "number" ? `等级${rank}` : String(rank);
}

export function playerLabel(player: PlayerView): string {
  return `${player.displayName}${player.captured ? "（已捕获）" : ""}`;
}

export function displayStatus(status: string): string {
  return ({ waiting: "等待开始", playing: "进行中", ended: "已结束" } as Record<string, string>)[status] ?? status;
}

export function displayPhase(phase: string): string {
  return ({ action: "行动阶段", intervention: "干涉投票", skill: "技能阶段", reveal: "展示身份", "token-return": "归还标记", ended: "已结束" } as Record<string, string>)[phase] ?? phase;
}

export function displayResource(resource: string): string {
  return ({ quill: "羽毛笔", shield: "盾牌", sword: "剑", staff: "法杖", fan: "扇子" } as Record<string, string>)[resource] ?? resource;
}

// 标签页标题基准：与 index.html 的 <title> 保持一致；进房后 GameScreen 附加 #房间号。
export const APP_TITLE = "鲜血盟约";
