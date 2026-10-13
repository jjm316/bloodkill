"""FastAPI/uvicorn authoritative web server for Blood Bound.

Run from the repository root with::

    uvicorn server.app:app --host 0.0.0.0 --port 8000

The server owns every room and never sends a player another player's identity,
curse assignment, or private events. See PROTOCOL.md and README.md.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
import uuid
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from blood_bound import Command, RuleError, SaveError, project_state

from . import admin_api
from .deadlines import DeadlineScheduler
from .accounts import Account, AccountError, AccountStore, SESSION_COOKIE, SESSION_SECONDS
from .protocol import PRIVATE_EVENT_TYPES, PROTOCOL_VERSION
from .rooms import Room, RoomManager


SAVES_DIR = Path(os.environ.get("BLOOD_BOUND_SAVES_DIR", "saves"))

app = FastAPI(title="Blood Bound server")
manager = RoomManager(SAVES_DIR)
manager.restore()
accounts = AccountStore(SAVES_DIR)


@dataclass
class Conn:
    ws: WebSocket
    room: Room
    account: Account
    # 会话凭证只在内存中把连接与其登录关联，用于退出/过期时停止该连接；
    # 不进入日志、投影或 URL。
    token: str = ""
    is_host: bool = False
    player_id: str | None = None
    # hello 完成前连接没有座位/模式，不参与投影广播（避免空视角帧）。
    ready: bool = False
    # 工单 11：座位被新连接接管后置位。旧连接被 pop 出 conns 后，其
    # ws_endpoint 循环仍可能在关闭竞态窗口里取到已入队消息；此标志保证
    # 这些迟到消息（玩家命令或房主操作）一律被拒，不再影响引擎状态。
    taken_over: bool = False


# connection id -> connection
conns: dict[str, Conn] = {}
metrics = {
    "websocketConnections": 0,
    "seatResumptions": 0,
    "seatTakeovers": 0,
    "commandsAccepted": 0,
    "commandsRejected": 0,
}

# 管理工具的回环监听（工单 19），startup 启动、shutdown 关闭。
admin_server: asyncio.AbstractServer | None = None


async def live_room_conns(room: Room) -> list[Conn]:
    """Ready connections of this room whose login session is still valid.

    An expired or revoked session is terminated here (lazy eviction at the
    next room broadcast): the connection is told why in Chinese and closed,
    so it receives no further private projections.
    """
    alive: list[Conn] = []
    expired: list[Conn] = []
    checked: dict[str, bool] = {}
    for conn in list(conns.values()):
        if conn.room is not room or not conn.ready:
            continue
        if conn.token not in checked:
            checked[conn.token] = accounts.get_session(conn.token) is not None
        if checked[conn.token]:
            alive.append(conn)
        else:
            expired.append(conn)
    for conn in expired:
        await _terminate_conn(conn, "auth.session-expired", "登录已过期，请重新登录。")
    return alive


def build_state(conn: Conn) -> dict[str, Any]:
    room = conn.room
    viewer = conn.player_id
    game = project_state(room.engine.state, viewer) if room.engine.state else None
    if game is not None and game.get("pending"):
        # The engine stays wall-clock-free; the room owns the countdown and
        # the server injects the deadline into every projection (intervention
        # and single-player windows alike, issue 05 / ADR 0011).
        game["pending"]["deadline"] = room.window_deadline
    connected = {
        player_id: any(c.room is room and c.ready and c.player_id == player_id for c in conns.values())
        for player_id in room.engine.state.players
    }
    return {
        "type": "state",
        "roomCode": room.code,
        "roomStatus": room.status,
        "locked": room.locked,
        "isHost": conn.is_host,
        "yourPlayerId": viewer,
        "hostPlayerId": room.host_player_id,
        "connected": connected,
        "hostActions": _host_actions(room, conn.is_host),
        "game": game,
        # Wall-clock anchor for deadline countdowns (engine deadlines are unix
        # seconds); clients tick locally between state broadcasts.
        "serverTime": time.time(),
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


async def broadcast(room: Room, message: dict[str, Any]) -> None:
    for conn in await live_room_conns(room):
        await send_safe(conn.ws, message)


async def send_state(conn: Conn) -> None:
    await send_safe(conn.ws, build_state(conn))


async def _terminate_conn(conn: Conn, code: str, message: str) -> None:
    """Stop an established connection whose session was revoked or expired.

    The connection is dropped from the registry first so no later broadcast or
    command can reach it, then it is told why in Chinese and closed.
    """
    for conn_id, candidate in list(conns.items()):
        if candidate is conn:
            conns.pop(conn_id, None)
    await send_safe(conn.ws, error_message(code, message))
    try:
        await conn.ws.close()
    except Exception:
        pass


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


async def _expire_window(room: Room, command_type: str, payload: dict[str, Any]) -> None:
    """Apply a window's timeout command through the normal command pipeline."""
    command = Command(
        f"{command_type}-{uuid.uuid4().hex}",
        room.game_id,
        None,
        room.engine.state.revision,
        command_type,
        payload,
    )
    try:
        events = manager.apply_command(room, command)
    except RuleError:
        # The window was already closed by players (or the game ended); the
        # scheduler's next sync cancels any stale timer.
        return
    events_view = public_events(events)
    if events_view:
        await broadcast(room, {"type": "event", "events": events_view})
    await broadcast_state(room)


# Reusable deadline machinery (server/deadlines.py): every state broadcast
# re-arms one timer per room for the engine's current expiry window.
deadline_scheduler = DeadlineScheduler(_expire_window)


async def broadcast_state(room: Room) -> None:
    await deadline_scheduler.sync(room)
    for conn in await live_room_conns(room):
        await send_safe(conn.ws, build_state(conn))


# ---- REST -------------------------------------------------------------


@app.post("/api/auth/register")
async def register_account(request: Request) -> JSONResponse:
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        return JSONResponse(error_message("auth.invalid-origin", "请从本站页面提交注册。"), status_code=403)
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        return JSONResponse(error_message("auth.invalid-input", "注册信息格式不正确，请重新填写。"), status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse(error_message("auth.invalid-input", "注册信息格式不正确，请重新填写。"), status_code=400)
    try:
        account, token = await run_in_threadpool(accounts.register, payload.get("username"), payload.get("password"), payload.get("confirmPassword"))
    except AccountError as error:
        return JSONResponse(error_message(error.code, str(error)), status_code=error.status)
    except sqlite3.Error:
        return JSONResponse(error_message("auth.service-unavailable", "服务暂时不可用，请稍后重试。"), status_code=503)
    response = JSONResponse({"account": account.public()}, status_code=201)
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/auth/login")
async def login_account(request: Request) -> JSONResponse:
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        return JSONResponse(error_message("auth.invalid-origin", "请从本站页面提交登录。"), status_code=403)
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        return JSONResponse(error_message("auth.invalid-input", "登录信息格式不正确，请重新填写。"), status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse(error_message("auth.invalid-input", "登录信息格式不正确，请重新填写。"), status_code=400)
    try:
        account, token = await run_in_threadpool(accounts.login, payload.get("username"), payload.get("password"))
    except AccountError as error:
        return JSONResponse(error_message(error.code, str(error)), status_code=error.status)
    except sqlite3.Error:
        return JSONResponse(error_message("auth.service-unavailable", "服务暂时不可用，请稍后重试。"), status_code=503)
    response = JSONResponse({"account": account.public()})
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/auth/session")
def current_account(request: Request) -> JSONResponse:
    account = accounts.get_session(request.cookies.get(SESSION_COOKIE))
    if account is None:
        response = JSONResponse(error_message("auth.login-required", "请先登录。"), status_code=401)
    else:
        response = JSONResponse({"account": account.public()})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/auth/logout")
async def logout_account(request: Request) -> JSONResponse:
    """Revoke the current login only: other devices' sessions stay valid.

    The revoked session's established room connections are stopped (told why
    in Chinese, then closed) without removing seats or host ownership.
    """
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        return JSONResponse(error_message("auth.invalid-origin", "请从本站页面退出登录。"), status_code=403)
    token = request.cookies.get(SESSION_COOKIE)
    account = accounts.get_session(token)
    if account is None or not await run_in_threadpool(accounts.revoke_session, token):
        return JSONResponse(error_message("auth.login-required", "请先登录。"), status_code=401)
    for conn in [conn for conn in list(conns.values()) if conn.token == token]:
        await _terminate_conn(conn, "auth.session-revoked", "当前登录已退出，请重新登录。")
    response = JSONResponse({"account": account.public()})
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
async def operational_metrics() -> dict[str, int]:
    """Anonymous, process-local counters for a self-hosted server."""
    return {**metrics, "activeConnections": len(conns), "activeRooms": len(manager.rooms)}


@app.post("/api/rooms")
async def create_room(request: Request) -> Any:
    account = accounts.get_session(request.cookies.get(SESSION_COOKIE))
    if account is None:
        return JSONResponse(error_message("auth.login-required", "请先登录。"), status_code=401)
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        return JSONResponse(error_message("auth.invalid-origin", "请从本站页面创建房间。"), status_code=403)
    body = await request.body()
    if body and body.strip() != b"{}":
        return JSONResponse(error_message("protocol.legacy-identity", "请刷新页面，房间使用当前登录账号。"), status_code=400)
    try:
        room = manager.create_room(account)
    except RuleError as error:
        return JSONResponse(rule_error_message(error), status_code=409)
    except (OSError, SaveError):
        return JSONResponse(error_message("room.create-failed", "创建房间失败，请稍后重试。"), status_code=503)
    return {"code": room.code, "gameId": room.game_id}


@app.get("/api/account/room")
async def account_room(request: Request) -> Any:
    account = accounts.get_session(request.cookies.get(SESSION_COOKIE))
    if account is None:
        return JSONResponse(error_message("auth.login-required", "请先登录。"), status_code=401)
    room = manager.room_for_account(account.account_id)
    return {"room": {"code": room.code, "status": room.status} if room else None}


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


@app.on_event("startup")
async def _arm_restored_deadlines() -> None:
    # After a restart a restored room may hold an already-expired window; sync
    # arms it with delay 0 so the timeout lands through the normal pipeline.
    for room in manager.rooms.values():
        await deadline_scheduler.sync(room)


@app.on_event("startup")
async def _start_admin_listener() -> None:
    # 管理工具（工单 19）走同一进程的回环监听：共享内存状态（含在线连接），
    # 只绑定 127.0.0.1；公网应用不注册任何管理路由。安装标识与管理凭证在
    # 存档目录的 admin/ 子目录，端口每次启动后写回，供 server.admin CLI 核对。
    global admin_server
    installation = admin_api.AdminInstallation(SAVES_DIR, create=True)
    endpoint = admin_api.AdminEndpoint(
        accounts=accounts, manager=manager, conns=conns, installation=installation,
    )
    admin_server = await admin_api.start_admin_server(endpoint)
    installation.record_port(admin_server.sockets[0].getsockname()[1])


@app.on_event("shutdown")
async def _stop_admin_listener() -> None:
    if admin_server is not None:
        admin_server.close()
        await admin_server.wait_closed()


@app.websocket("/ws/{code}")
async def ws_endpoint(websocket: WebSocket, code: str) -> None:
    await websocket.accept()
    token = websocket.cookies.get(SESSION_COOKIE)
    account = accounts.get_session(token)
    if account is None:
        await send_safe(websocket, error_message("auth.login-required", "请先登录。"))
        await websocket.close()
        return
    room = manager.get_room(code)
    if room is None:
        # details 键名不能是 code：error_message 首参同名，关键字传参会 TypeError。
        await send_safe(websocket, error_message("room.not-found", "Room not found.", roomCode=code))
        await websocket.close()
        return

    conn_id = uuid.uuid4().hex
    conn = Conn(ws=websocket, room=room, account=account, token=token or "")
    conns[conn_id] = conn
    metrics["websocketConnections"] += 1
    try:
        if not await _handle_hello(conn, websocket):
            return
        while True:
            raw = await websocket.receive_json()
            if accounts.get_session(conn.token) is None:
                # 过期/已撤销的登录：已建立的连接不能再发送任何合法动作。
                await _terminate_conn(conn, "auth.session-expired", "登录已过期，请重新登录。")
                return
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
    if accounts.get_session(conn.token) is None:
        # accept 与 hello 之间登录可能已过期/撤销：同样按未登录拒绝。
        await send_safe(ws, error_message("auth.login-required", "请先登录。"))
        return False
    if not isinstance(raw, dict) or raw.get("type") != "hello":
        await send_safe(ws, error_message("command.invalid-shape", "First message must be hello."))
        return False
    version = raw.get("protocolVersion")
    if version != PROTOCOL_VERSION:
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
    if "name" in raw or "token" in raw:
        await send_safe(ws, error_message("protocol.legacy-identity", "请刷新页面，房间使用当前登录账号。"))
        return False
    mode = raw.get("mode")
    if mode not in {"player", "spectator"}:
        await send_safe(ws, error_message("command.invalid-shape", "请选择加入房间或旁观。"))
        return False
    conn.is_host = conn.account.account_id == room.host_account_id
    if mode == "player":
        try:
            player_id, is_new = manager.join_or_resume(room, conn.account)
        except RuleError as error:
            await send_safe(ws, rule_error_message(error))
            return False
        conn.player_id = player_id
        if not is_new:
            metrics["seatResumptions"] += 1
        for other_id, other in list(conns.items()):
            if other is not conn and other.room is room and other.player_id == player_id:
                other.taken_over = True
                await send_safe(other.ws, {"type": "taken-over", "reason": "seat taken over by a new connection"})
                try:
                    await other.ws.close()
                except Exception:
                    pass
                conns.pop(other_id, None)
                metrics["seatTakeovers"] += 1
    conn.ready = True
    await broadcast_state(room)
    return True


async def _handle_message(conn: Conn, raw: Any) -> None:
    if not isinstance(raw, dict):
        await send_safe(conn.ws, error_message("command.invalid-shape", "Messages must be JSON objects."))
        return
    if conn.taken_over:
        # 工单 11：被接管的旧连接不再有任何操作权。迟到消息一律拒绝；
        # 命令拒绝仍带 ack，客户端发件箱不会卡住（连接本身已被关闭）。
        error = RuleError("seat.taken-over", "座位已由其他设备进入，本连接已停止操作。")
        await send_safe(conn.ws, rule_error_message(error))
        if raw.get("type") == "command":
            raw_command_id = raw.get("commandId")
            command_id = raw_command_id if isinstance(raw_command_id, str) and raw_command_id else uuid.uuid4().hex
            await send_command_ack(conn, command_id, "rejected", error=error)
            metrics["commandsRejected"] += 1
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
    if command_type in (
        "start-game",
        "join-game",
        "timeout-intervention",
        "timeout-reveal",
        "timeout-skill",
        "timeout-return",
    ):
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
    if conn.account.account_id != room.host_account_id:
        await send_safe(conn.ws, error_message("room.not-host", "只有房主可以执行此操作。"))
        return
    action = raw.get("action")
    if action == "start":
        timeout_seconds = raw.get("interventionTimeoutSeconds")
        if timeout_seconds is not None and (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int)):
            await send_safe(conn.ws, error_message("command.invalid-shape", "interventionTimeoutSeconds must be an integer."))
            return
        single_timeout_seconds = raw.get("singleWindowTimeoutSeconds")
        if single_timeout_seconds is not None and (isinstance(single_timeout_seconds, bool) or not isinstance(single_timeout_seconds, int)):
            await send_safe(conn.ws, error_message("command.invalid-shape", "singleWindowTimeoutSeconds must be an integer."))
            return
        try:
            events = manager.start_game(
                room,
                intervention_timeout_seconds=timeout_seconds,
                single_window_timeout_seconds=single_timeout_seconds,
            )
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
