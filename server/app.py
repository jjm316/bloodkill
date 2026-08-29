"""FastAPI/uvicorn authoritative web server for Blood Bound.

Run from the repository root with::

    uvicorn server.app:app --host 0.0.0.0 --port 8000

The server owns every room and never sends a player another player's identity,
curse assignment, or private events. See PROTOCOL.md and README.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import uuid
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from blood_bound import Command, RuleError, project_state

from .protocol import PRIVATE_EVENT_TYPES, PROTOCOL_VERSION
from .rooms import Room, RoomManager


SAVES_DIR = Path(os.environ.get("BLOOD_BOUND_SAVES_DIR", "saves"))

app = FastAPI(title="Blood Bound server")
manager = RoomManager(SAVES_DIR)
manager.restore()


@dataclass
class Conn:
    ws: WebSocket
    room: Room
    is_host: bool = False
    player_id: str | None = None


# connection id -> connection
conns: dict[str, Conn] = {}
metrics = {
    "websocketConnections": 0,
    "seatResumptions": 0,
    "seatTakeovers": 0,
    "commandsAccepted": 0,
    "commandsRejected": 0,
}


def room_conns(room: Room) -> list[Conn]:
    return [conn for conn in conns.values() if conn.room is room]


def build_state(conn: Conn) -> dict[str, Any]:
    room = conn.room
    viewer = conn.player_id
    game = project_state(room.engine.state, viewer) if room.engine.state else None
    connected = {
        player_id: any(c.room is room and c.player_id == player_id for c in conns.values())
        for player_id in room.engine.state.players
    }
    return {
        "type": "state",
        "roomCode": room.code,
        "roomStatus": room.status,
        "locked": room.locked,
        "isHost": conn.is_host,
        "yourPlayerId": viewer,
        "connected": connected,
        "hostActions": _host_actions(room, conn.is_host),
        "game": game,
    }


def _host_actions(room: Room, is_host: bool) -> list[dict[str, Any]]:
    if not is_host:
        return []
    actions: list[dict[str, Any]] = []
    if room.status == "waiting":
        actions.append({"type": "start-game"})
    actions.append({"type": "lock" if not room.locked else "unlock"})
    return actions


def error_message(code: str, message: str = "", **details: Any) -> dict[str, Any]:
    return {"type": "error", "code": code, "message": message, "details": details}


def rule_error_message(error: RuleError) -> dict[str, Any]:
    return {"type": "error", "code": error.code, "message": str(error), "details": error.details}


def event_to_dict(event: Any) -> dict[str, Any]:
    return {
        "eventId": event.event_id,
        "eventType": event.event_type,
        "gameId": event.game_id,
        "revision": event.revision,
        "timestamp": event.timestamp,
        "commandId": event.command_id,
        "payload": event.payload,
    }


def public_events(events: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [
        event_to_dict(event) for event in events if event.event_type not in PRIVATE_EVENT_TYPES
    ]


async def send_safe(ws: WebSocket, message: dict[str, Any]) -> None:
    try:
        await ws.send_json(message)
    except Exception:
        pass


async def broadcast_state(room: Room) -> None:
    for conn in room_conns(room):
        await send_safe(conn.ws, build_state(conn))


async def broadcast(room: Room, message: dict[str, Any]) -> None:
    for conn in room_conns(room):
        await send_safe(conn.ws, message)


async def send_state(conn: Conn) -> None:
    await send_safe(conn.ws, build_state(conn))


async def send_command_ack(
    conn: Conn,
    command_id: str,
    status: str,
    *,
    error: RuleError | None = None,
) -> None:
    message: dict[str, Any] = {
        "type": "ack",
        "commandId": command_id,
        "status": status,
        "revision": conn.room.engine.state.revision,
    }
    if error is not None:
        message["error"] = {
            "code": error.code,
            "message": str(error),
            "details": error.details,
        }
    await send_safe(conn.ws, message)


# ---- REST -------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
async def operational_metrics() -> dict[str, int]:
    """Anonymous, process-local counters for a self-hosted server."""
    return {**metrics, "activeConnections": len(conns), "activeRooms": len(manager.rooms)}


@app.post("/api/rooms")
async def create_room() -> dict[str, str]:
    room = manager.create_room()
    return {"code": room.code, "hostToken": room.host_token, "gameId": room.game_id}


@app.get("/api/rooms/{code}")
async def room_info(code: str) -> Any:
    room = manager.get_room(code)
    if room is None:
        return JSONResponse(error_message("room.not-found", "Room not found."), status_code=404)
    return {
        "code": room.code,
        "status": room.status,
        "locked": room.locked,
        "playerCount": len(room.engine.state.players),
    }


@app.get("/api/rooms/{code}/replay")
async def replay(code: str) -> Any:
    room = manager.get_room(code)
    if room is None:
        return JSONResponse(error_message("room.not-found", "Room not found."), status_code=404)
    if room.status != "ended":
        return JSONResponse(error_message("room.not-ended", "The game has not ended."), status_code=409)
    return {"gameId": room.game_id, "steps": manager.replay(room)}


# ---- WebSocket --------------------------------------------------------


@app.websocket("/ws/{code}")
async def ws_endpoint(websocket: WebSocket, code: str) -> None:
    await websocket.accept()
    room = manager.get_room(code)
    if room is None:
        await send_safe(websocket, error_message("room.not-found", "Room not found.", code=code))
        await websocket.close()
        return

    conn_id = uuid.uuid4().hex
    conn = Conn(ws=websocket, room=room)
    conns[conn_id] = conn
    metrics["websocketConnections"] += 1
    try:
        if not await _handle_hello(conn, websocket):
            return
        while True:
            raw = await websocket.receive_json()
            await _handle_message(conn, raw)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        conns.pop(conn_id, None)
        await broadcast_state(room)


async def _handle_hello(conn: Conn, ws: WebSocket) -> bool:
    try:
        raw = await ws.receive_json()
    except Exception:
        return False
    if not isinstance(raw, dict) or raw.get("type") != "hello":
        await send_safe(ws, error_message("command.invalid-shape", "First message must be hello."))
        return False
    version = raw.get("protocolVersion")
    if version is not None and version != PROTOCOL_VERSION:
        await send_safe(
            ws,
            error_message(
                "protocol.version-mismatch",
                "Client and server protocol versions differ.",
                expected=PROTOCOL_VERSION,
                received=version,
            ),
        )
        return False
    room = conn.room
    name = str(raw.get("name") or "").strip()
    token = raw.get("token")
    conn.is_host = bool(token and token == room.host_token)
    if name:
        try:
            player_id, is_new = manager.join_or_resume(room, name)
        except RuleError as error:
            await send_safe(ws, rule_error_message(error))
            return False
        conn.player_id = player_id
        if not is_new:
            metrics["seatResumptions"] += 1
        for other_id, other in list(conns.items()):
            if other is not conn and other.room is room and other.player_id == player_id:
                await send_safe(other.ws, {"type": "taken-over", "reason": "seat taken over by a new connection"})
                try:
                    await other.ws.close()
                except Exception:
                    pass
                conns.pop(other_id, None)
                metrics["seatTakeovers"] += 1
    await broadcast_state(room)
    return True


async def _handle_message(conn: Conn, raw: Any) -> None:
    if not isinstance(raw, dict):
        await send_safe(conn.ws, error_message("command.invalid-shape", "Messages must be JSON objects."))
        return
    kind = raw.get("type")
    if kind == "command":
        await _handle_command(conn, raw)
    elif kind == "host":
        await _handle_host(conn, raw)
    else:
        await send_safe(conn.ws, error_message("command.invalid-shape", "Unknown message type."))


async def _handle_command(conn: Conn, raw: dict[str, Any]) -> None:
    room = conn.room
    command_type = raw.get("command")
    payload = raw.get("payload", {})
    raw_command_id = raw.get("commandId")
    command_id = raw_command_id if isinstance(raw_command_id, str) and raw_command_id else uuid.uuid4().hex
    expected_revision = raw.get("expectedRevision", room.engine.state.revision)
    if command_type in ("start-game", "join-game"):
        error = RuleError("command.server-managed", "This command is managed by the server.")
        await send_safe(conn.ws, rule_error_message(error))
        await send_command_ack(conn, command_id, "rejected", error=error)
        metrics["commandsRejected"] += 1
        return
    actor = conn.player_id
    if actor is None:
        error = RuleError("player.not-eligible", "Spectators cannot act.")
        await send_safe(conn.ws, rule_error_message(error))
        await send_command_ack(conn, command_id, "rejected", error=error)
        metrics["commandsRejected"] += 1
        return
    if not isinstance(command_type, str) or not command_type or not isinstance(payload, dict):
        error = RuleError("command.invalid-shape", "A command must have a type and object payload.")
        await send_safe(conn.ws, rule_error_message(error))
        await send_command_ack(conn, command_id, "rejected", error=error)
        metrics["commandsRejected"] += 1
        return
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
        error = RuleError("command.invalid-shape", "expectedRevision must be an integer.")
        await send_safe(conn.ws, rule_error_message(error))
        await send_command_ack(conn, command_id, "rejected", error=error)
        metrics["commandsRejected"] += 1
        return
    command = Command(command_id, room.game_id, actor, expected_revision, command_type, payload)
    revision_before = room.engine.state.revision
    try:
        events = manager.apply_command(room, command)
    except RuleError as error:
        await send_safe(conn.ws, rule_error_message(error))
        await send_command_ack(conn, command_id, "rejected", error=error)
        await send_state(conn)
        metrics["commandsRejected"] += 1
        return
    applied = room.engine.state.revision != revision_before
    await send_command_ack(conn, command_id, "accepted")
    metrics["commandsAccepted"] += 1
    if not applied:
        # A retransmission is acknowledged without replaying its public events.
        await send_state(conn)
        return
    events_view = public_events(events)
    if events_view:
        await broadcast(room, {"type": "event", "events": events_view})
    await broadcast_state(room)


async def _handle_host(conn: Conn, raw: dict[str, Any]) -> None:
    room = conn.room
    if not conn.is_host:
        await send_safe(conn.ws, error_message("room.not-host", "Only the host can perform this action."))
        return
    action = raw.get("action")
    if action == "start":
        try:
            events = manager.start_game(room)
        except RuleError as error:
            await send_safe(conn.ws, rule_error_message(error))
            return
        events_view = public_events(events)
        if events_view:
            await broadcast(room, {"type": "event", "events": events_view})
    elif action in ("lock", "unlock"):
        manager.set_locked(room, action == "lock")
    else:
        await send_safe(conn.ws, error_message("command.invalid-shape", "Unknown host action."))
        return
    await broadcast_state(room)


# Serve the built browser client when present (`cd client && npm run build`).
# API and WebSocket routes match before this mount, so /api and /ws win.
_CLIENT_DIST = Path(__file__).resolve().parent.parent / "client" / "dist"
if _CLIENT_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_CLIENT_DIST), html=True), name="client")
