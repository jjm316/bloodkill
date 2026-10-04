import { useCallback, useEffect, useRef, useState } from "react";
import type { CommandAck, GameEvent, RoomState, ServerError } from "./types";

const PROTOCOL_VERSION = "3";
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
  send: (command: string, payload?: Record<string, unknown>) => void;
  sendHost: (action: string, payload?: Record<string, unknown>) => void;
}

/**
 * Opens the room socket, performs the `hello` handshake, and exposes the
 * latest authoritative room state. The server pushes a fresh projection after
 * every accepted command, so the UI never needs local rules.
 */
export function useGameSocket(code: string, name: string, token: string | null): SocketHandle {
  const [state, setState] = useState<RoomState | null>(null);
  const [events, setEvents] = useState<GameEvent[]>([]);
  const [error, setError] = useState<ServerError | null>(null);
  const [closed, setClosed] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [takenOver, setTakenOver] = useState(false);
  const [failed, setFailed] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const stateRef = useRef<RoomState | null>(null);
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
            name,
            token: token ?? undefined,
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
          setError(message as ServerError);
        } else if (typed.type === "taken-over") {
          canReconnect = false;
          setTakenOver(true);
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
  }, [code, name, token]);

  const send = useCallback((command: string, payload: Record<string, unknown> = {}) => {
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
    wsRef.current?.send(JSON.stringify({ type: "host", action, ...payload }));
  }, []);

  return { state, events, error, closed, reconnecting, takenOver, failed, send, sendHost };
}
