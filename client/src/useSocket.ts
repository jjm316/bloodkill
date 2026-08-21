import { useCallback, useEffect, useRef, useState } from "react";
import type { GameEvent, RoomState, ServerError } from "./types";

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
  takenOver: boolean;
  send: (command: string, payload?: Record<string, unknown>) => void;
  sendHost: (action: string) => void;
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
  const [takenOver, setTakenOver] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/${encodeURIComponent(code)}`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "hello", name, token: token ?? undefined }));
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
        setState(message as RoomState);
        setError(null);
      } else if (typed.type === "event") {
        const incoming = (message as { events?: GameEvent[] }).events ?? [];
        setEvents((previous) => [...previous, ...incoming]);
      } else if (typed.type === "error") {
        setError(message as ServerError);
      } else if (typed.type === "taken-over") {
        setTakenOver(true);
      }
    };
    ws.onclose = () => setClosed(true);

    return () => {
      ws.onclose = null;
      ws.close();
    };
  }, [code, name, token]);

  const send = useCallback((command: string, payload: Record<string, unknown> = {}) => {
    wsRef.current?.send(JSON.stringify({ type: "command", commandId: newCommandId(), command, payload }));
  }, []);

  const sendHost = useCallback((action: string) => {
    wsRef.current?.send(JSON.stringify({ type: "host", action }));
  }, []);

  return { state, events, error, closed, takenOver, send, sendHost };
}
