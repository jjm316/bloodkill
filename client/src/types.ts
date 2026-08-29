// Wire types mirroring the server protocol (see server/PROTOCOL.md).

export type RoomStatus = "waiting" | "playing" | "ended";

export interface Action {
  type: string;
  targetPlayerId?: string;
  targetPlayerIds?: string[];
  responderPlayerId?: string;
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
  phase: { kind: string; activePlayerId?: string };
  pending: PendingView | null;
  result: GameResult | null;
  viewer: ViewerView | null;
  legalActions: Action[];
}

export interface RoomState {
  type: "state";
  roomCode: string;
  roomStatus: RoomStatus;
  locked: boolean;
  isHost: boolean;
  yourPlayerId: string | null;
  connected: Record<string, boolean>;
  hostActions: Action[];
  game: GameState | null;
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

export function displayRank(rank: number | string): string {
  if (rank === "fleur-cross") return "审判者";
  const names: Record<number, string> = {
    1: "长老",
    2: "刺客",
    3: "小丑",
    4: "炼金术师",
    5: "占卜师",
    6: "守护者",
    7: "狂战士",
    8: "法师",
    9: "交际花",
  };
  return typeof rank === "number" && names[rank] ? `等级${rank}·${names[rank]}` : String(rank);
}

export function playerLabel(player: PlayerView): string {
  return `${player.displayName}${player.captured ? "（已捕获）" : ""}`;
}

export function displayStatus(status: string): string {
  return ({ waiting: "等待开始", playing: "进行中", ended: "已结束" } as Record<string, string>)[status] ?? status;
}

export function displayPhase(phase: string): string {
  return ({ action: "行动阶段", intervention: "干预阶段", skill: "技能阶段", reveal: "展示身份", "token-return": "归还标记", ended: "已结束" } as Record<string, string>)[phase] ?? phase;
}

export function displayResource(resource: string): string {
  return ({ quill: "羽毛笔", shield: "盾牌", sword: "剑", staff: "法杖", fan: "扇子" } as Record<string, string>)[resource] ?? resource;
}
