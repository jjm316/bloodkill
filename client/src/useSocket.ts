import { useCallback, useEffect, useRef, useState } from "react";
import type { CommandAck, GameEvent, RoomState, ServerError } from "./types";

const PROTOCOL_VERSION = "4";
// 初始进房超时：从未收到过状态投影的连接，超过此时长仍未应答视为进房失败
// （房间号错误 / 服务器未启动 / 网络不通）。已收到过状态的断线重连不受影响。
const JOIN_TIMEOUT_MS = 10_000;

export function newCommandId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export interface SocketHandle {
  state: RoomState | null;
  events: GameEvent[];
  error: ServerError | null;
  closed: boolean;
  reconnecting: boolean;
  takenOver: boolean;
  /** 初始进房超时：从未收到状态且 10 秒无应答，已停止重连，只能返回大厅。 */
  failed: boolean;
  /** 服务端已确认退座（工单 13）：连接终止、不再重连，界面回大厅。 */
  left: boolean;
  send: (command: string, payload?: Record<string, unknown>) => void;
  sendHost: (action: string, payload?: Record<string, unknown>) => void;
  /** 等待普通玩家的主动退座：发 leave，等服务端 left 确认（拒绝则显示原因）。 */
  sendLeave: () => void;
}

/**
 * Opens the room socket, performs the `hello` handshake, and exposes the
 * latest authoritative room state. The server pushes a fresh projection after
 * every accepted command, so the UI never needs local rules.
 */
export function useGameSocket(code: string, accountId: string, mode: "player" | "spectator"): SocketHandle {
  const [state, setState] = useState<RoomState | null>(null);
  const [events, setEvents] = useState<GameEvent[]>([]);
  const [error, setError] = useState<ServerError | null>(null);
  const [closed, setClosed] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [takenOver, setTakenOver] = useState(false);
  const [failed, setFailed] = useState(false);
  const [left, setLeft] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const stateRef = useRef<RoomState | null>(null);
  // 工单 11：座位被新设备接管后，本连接的一切活动终止——不再重连、不再
  // 补发待确认命令、迟到的旧 socket 帧一律忽略，避免污染接管后的状态。
  const takenOverRef = useRef(false);
  const pendingCommandsRef = useRef(
    new Map<string, { command: string; payload: Record<string, unknown>; expectedRevision: number }>(),
  );

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    let disposed = false;
    let reconnectTimer: number | undefined;
    let joinTimer: number | undefined;
    let reconnectAttempt = 0;
    let canReconnect = true;
    takenOverRef.current = false;
    setTakenOver(false);
    setLeft(false);

    const flushPendingCommands = () => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      for (const [commandId, command] of pendingCommandsRef.current) {
        ws.send(JSON.stringify({ type: "command", commandId, ...command }));
      }
    };

    const connect = () => {
      if (disposed || !canReconnect) return;
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/${encodeURIComponent(code)}`);
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttempt = 0;
        setClosed(false);
        ws.send(
          JSON.stringify({
            type: "hello",
            mode,
            clientRevision: stateRef.current?.game?.revision,
            protocolVersion: PROTOCOL_VERSION,
          }),
        );
      };
      ws.onmessage = (event) => {
        let message: unknown;
        try {
          message = JSON.parse(String(event.data));
        } catch {
          return;
        }
        if (typeof message !== "object" || message === null) return;
        const typed = message as { type?: string };
        if (typed.type === "taken-over") {
          // 接管是终止性的：丢弃待确认命令（旧连接没有资格补发），停止重连。
          canReconnect = false;
          takenOverRef.current = true;
          pendingCommandsRef.current.clear();
          setTakenOver(true);
          return;
        }
        if (takenOverRef.current) return; // 旧 socket 的迟到帧不得污染接管后的状态
        if (typed.type === "left") {
          // 工单 13：服务端确认退座——终止性事件：停止重连并主动关闭，
          // 后续 close 不触发退避重连；界面据 left 状态回大厅。
          canReconnect = false;
          setLeft(true);
          ws.close();
          return;
        }
        if (typed.type === "state") {
          const next = message as RoomState;
          if (joinTimer !== undefined) {
            window.clearTimeout(joinTimer);
            joinTimer = undefined;
          }
          stateRef.current = next;
          setState(next);
          setReconnecting(false);
          flushPendingCommands();
        } else if (typed.type === "event") {
          const incoming = (message as { events?: GameEvent[] }).events ?? [];
          setEvents((previous) => {
            const seen = new Set(previous.map((event) => event.eventId));
            const next = incoming.filter((event) => {
              if (seen.has(event.eventId)) return false;
              seen.add(event.eventId);
              return true;
            });
            return [...previous, ...next].slice(-120);
          });
        } else if (typed.type === "ack") {
          const ack = message as CommandAck;
          pendingCommandsRef.current.delete(ack.commandId);
          if (ack.status === "accepted") {
            setError(null);
          } else if (ack.error) {
            setError({ type: "error", ...ack.error });
          }
        } else if (typed.type === "error") {
          const failure = message as ServerError;
          setError(failure);
          // 加入阶段（尚未收到任何状态投影）的房间错误是终止性的：
          // 锁定、开局、满员、结束、占用等拒绝后不再自动重连，避免反复撞墙。
          // spectator.*（工单 16）同样是终止性的：占座互斥拒绝、账号成为
          // 玩家后的旁观停止都不允许再以旁观身份重连。
          // 已进入房间后的命令错误（如房主操作被拒）不影响断线重连。
          // 管理关闭（工单 21）同样终止：房间已不存在，重连只会撞 404。
          if (
            !stateRef.current ||
            failure.code.startsWith("auth.") ||
            failure.code.startsWith("protocol.") ||
            failure.code.startsWith("spectator.") ||
            failure.code === "room.admin-closed"
          ) {
            canReconnect = false;
            setFailed(true);
            ws.close();
          }
        }
      };
      ws.onclose = () => {
        if (disposed || !canReconnect) return;
        setClosed(true);
        setReconnecting(true);
        const delay = Math.min(1_000 * 2 ** reconnectAttempt, 10_000);
        reconnectAttempt += 1;
        reconnectTimer = window.setTimeout(connect, delay);
      };
    };

    connect();

    // 初始进房超时：只武装在从未收到过状态的连接上（含连不上、握手无应答；
    // 计时从挂载起算而非从 ws 打开起算，服务器未启动也能按时失败）。
    // 首份状态到达即解除；此后断线走原有指数退避重连，不会进入失败态。
    if (!stateRef.current) {
      joinTimer = window.setTimeout(() => {
        // canReconnect 必须先于 close() 置 false：onclose 依赖它跳过重连排程
        canReconnect = false;
        if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
        setFailed(true);
        wsRef.current?.close();
      }, JOIN_TIMEOUT_MS);
    }

    return () => {
      disposed = true;
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
      if (joinTimer !== undefined) window.clearTimeout(joinTimer);
      wsRef.current?.close();
    };
  }, [code, accountId, mode]);

  const send = useCallback((command: string, payload: Record<string, unknown> = {}) => {
    if (takenOverRef.current) return; // 座位已被接管：本连接没有资格再发命令
    const commandId = newCommandId();
    pendingCommandsRef.current.set(commandId, {
      command,
      payload,
      expectedRevision: stateRef.current?.game?.revision ?? 0,
    });
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      const pending = pendingCommandsRef.current.get(commandId);
      if (pending) ws.send(JSON.stringify({ type: "command", commandId, ...pending }));
    }
  }, []);

  const sendHost = useCallback((action: string, payload: Record<string, unknown> = {}) => {
    if (takenOverRef.current) return; // 座位已被接管：房主操作同样停止
    wsRef.current?.send(JSON.stringify({ type: "host", action, ...payload }));
  }, []);

  // 工单 13：等待普通玩家的主动退座。没有命令载荷/确认重传语义：服务端
  // 以 left 帧确认或错误帧拒绝（拒绝时 error 已显示，界面停留在房间）。
  const sendLeave = useCallback(() => {
    if (takenOverRef.current) return; // 座位已被接管：本连接没有资格退座
    wsRef.current?.send(JSON.stringify({ type: "leave" }));
  }, []);

  return { state, events, error, closed, reconnecting, takenOver, failed, left, send, sendHost, sendLeave };
}
