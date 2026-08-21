// Wire types mirroring the server protocol (see server/PROTOCOL.md).

export type RoomStatus = "waiting" | "playing" | "ended";

export interface Action {
  type: string;
  targetPlayerId?: string;
  responderPlayerId?: string;
  use?: boolean;
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
  revealed: { rank?: number | string; affiliation?: string };
  resources: Record<string, number>;
}

export interface ViewerView {
  playerId: string;
  identity: Identity;
  resources: Record<string, number>;
  skillsUsed: string[];
  cursesToDistribute: string[];
}

export interface PendingView {
  kind: string;
  actorPlayerId: string;
  targetPlayerId: string | null;
  eligiblePlayerIds: string[];
  rank: number | string | null;
  trigger: string | null;
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

export function actionToCommand(action: Action): { command: string; payload: Record<string, unknown> } {
  const { type, ...payload } = action;
  return { command: type, payload };
}

export function displayFaction(faction: string): string {
  if (faction === "rose") return "Rose";
  if (faction === "beast") return "Beast";
  if (faction === "secret-order") return "Secret Order";
  return faction;
}

export function displayRank(rank: number | string): string {
  if (rank === "fleur-cross") return "Fleur Cross";
  return `Rank ${rank}`;
}

export function playerLabel(player: PlayerView): string {
  return `${player.displayName}${player.captured ? " (captured)" : ""}`;
}
