"""FastAPI/uvicorn authoritative web server for Blood Bound.

Run from the repository root with::

    uvicorn server.app:app --host 0.0.0.0 --port 8000

The server owns every room and never sends a player another player's identity,
curse assignment, or private events. See PROTOCOL.md and README.md.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
import uuid
from typing import Any, Callable

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
    # Conn 是 dataclass（自动生成 __eq__），过期判定必须按对象身份比对，
    # 不能用 in（值相等会把仍在线的同类连接误判为过期）。
    await _stop_conns(lambda conn: any(conn is stale for stale in expired),
                      "auth.session-expired", "登录已过期，请重新登录。")
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


def _origin_rejection(request: Request, action: str) -> JSONResponse | None:
    """跨站表单守门：请求带 Origin 且非本站时返回中文 403（action 为中文动作短语）。"""
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        return JSONResponse(error_message("auth.invalid-origin", f"请从本站页面{action}。"), status_code=403)
    return None


async def _request_json_object(request: Request, noun: str) -> dict[str, Any] | JSONResponse:
    """读 JSON 对象请求体；解析失败或不是对象时返回中文 400（noun 为中文主体名词）。"""
    message = f"{noun}格式不正确，请重新填写。"
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        return JSONResponse(error_message("auth.invalid-input", message), status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse(error_message("auth.invalid-input", message), status_code=400)
    return payload


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


def _drop_conn(conn: Conn) -> None:
    """按对象身份从连接注册表移除连接（「按对象移除」的唯一扫描）。"""
    for conn_id, candidate in list(conns.items()):
        if candidate is conn:
            conns.pop(conn_id, None)


async def _terminate_conn(conn: Conn, code: str, message: str) -> None:
    """Stop an established connection whose session was revoked or expired.

    The connection is dropped from the registry first so no later broadcast or
    command can reach it, then it is told why in Chinese and closed.
    """
    _drop_conn(conn)
    await send_safe(conn.ws, error_message(code, message))
    try:
        await conn.ws.close()
    except Exception:
        pass


async def _stop_conns(predicate: Callable[[Conn], bool], code: str, message: str) -> int:
    """按谓词停止一批已建立的连接：逐条发中文原因帧后关闭，返回终止数。

    「过滤注册表 → 逐条终止」的唯一管线：退出登录、改密停其他设备、
    管理重置停连、旁观转玩家停旁观、管理关房与广播惰性踢出共用；
    各路径的错误码、中文文案与排除语义（如不停当前设备）由调用方
    以谓词与参数保持原样。
    """
    stopped = 0
    for conn in [conn for conn in list(conns.values()) if predicate(conn)]:
        await _terminate_conn(conn, code, message)
        stopped += 1
    return stopped


async def _stop_account_spectators(account_id: str, *, exclude: Conn | None = None) -> None:
    """Ticket 16: an account that becomes a player loses its spectator conns.

    Established spectator connections of this account (any room) are told why
    in Chinese and closed, so "spectate first, join later" cannot keep a live
    spectator view next to a player seat. Connections still handshaking are
    not stopped here: their own hello check runs after the seat commit and
    rejects them. The player connection itself is passed as `exclude`.
    """
    await _stop_conns(
        lambda conn: conn is not exclude
        and conn.account.account_id == account_id
        and conn.ready
        and conn.player_id is None,
        "spectator.became-player", "当前账号已作为玩家进入房间，本旁观连接已停止。")


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



# ---- 管理关闭（工单 21） --------------------------------------------------


async def admin_close_room(code: str, expected_game_id: str | None,
                           expected_revision: int | None) -> dict[str, Any]:
    """close-room 执行器：同进程内校验、备份、停用、取消计时并断开连接。

    与预览共用 :func:`server.admin_api.close_target_rejection` 的目标判定；
    校验在 :meth:`RoomManager.admin_close` 的锁内再次发生，这里的早期校验
    只负责给出可操作的中文错误（不存在/已结束/已关闭/目标变化）。目标变
    化用预览时记下的对局引用与修订号双重核对，防止把确认落到预览之后变
    化的房间（或复用了同一房号的新房间）上。
    """
    from .admin_api import AdminCloseError, close_target_rejection

    rejection = close_target_rejection(manager, code)
    if rejection is not None:
        status, error_code, message, details = rejection
        raise AdminCloseError(status, error_code, message, details)
    room = manager.get_room(code)
    assert room is not None  # 判定通过即存在可关闭的未结束房间。
    if expected_game_id is not None and room.game_id != expected_game_id:
        raise AdminCloseError(409, "admin.target-changed",
                              f"房间 {code} 的当前对局（{room.game_id}）与预览时（{expected_game_id}）不一致，"
                              "房号可能已被新房间使用；已拒绝关闭，请重新预览确认。")
    if expected_revision is not None and room.engine.state.revision != expected_revision:
        raise AdminCloseError(409, "admin.target-changed",
                              f"房间 {code} 在预览后已发生变化（修订号 {expected_revision} → "
                              f"{room.engine.state.revision}）；已拒绝关闭，请重新预览确认。")
    try:
        result = manager.admin_close(room)
    except RuleError as error:
        status = 503 if error.code in {"admin.backup-failed", "admin.close-failed"} else 409
        raise AdminCloseError(status, error.code, str(error), error.details) from None
    # 工单 22 故障注入钩子：关闭已提交、回复尚未发出的边界（验证用真实
    # 进程终止在此模拟「关闭成功但回复丢失」）。
    from .rooms import admin_close_fault_pause
    admin_close_fault_pause("after-commit", SAVES_DIR, room.game_id)
    # 计时器走既有调度器机制：窗口已被清空，sync 即取消该房已武装的定时。
    await deadline_scheduler.sync(room)
    # 通知并断开该房全部连接（含真实决策窗口内的）：每条连接先收到中文
    # 关闭原因再被关闭，与撤销登录的终止管线一致。
    await _stop_conns(lambda conn: conn.room is room,
                      "room.admin-closed", "房间已被管理员关闭，请返回大厅创建或加入新的房间。")
    return result


# ---- REST -------------------------------------------------------------


@app.post("/api/auth/register")
async def register_account(request: Request) -> JSONResponse:
    rejection = _origin_rejection(request, "提交注册")
    if rejection is not None:
        return rejection
    payload = await _request_json_object(request, "注册信息")
    if isinstance(payload, JSONResponse):
        return payload
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
    rejection = _origin_rejection(request, "提交登录")
    if rejection is not None:
        return rejection
    payload = await _request_json_object(request, "登录信息")
    if isinstance(payload, JSONResponse):
        return payload
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
    rejection = _origin_rejection(request, "退出登录")
    if rejection is not None:
        return rejection
    token = request.cookies.get(SESSION_COOKIE)
    account = accounts.get_session(token)
    if account is None or not await run_in_threadpool(accounts.revoke_session, token):
        return JSONResponse(error_message("auth.login-required", "请先登录。"), status_code=401)
    await _stop_conns(lambda conn: conn.token == token,
                      "auth.session-revoked", "当前登录已退出，请重新登录。")
    response = JSONResponse({"account": account.public()})
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/auth/password")
async def change_password(request: Request) -> JSONResponse:
    """验证旧密码后设置新密码（工单 15）。

    当前登录保留原有效期；同账号其他设备的登录全部撤销，其已建立的
    房间 WebSocket 收到 auth.password-changed 中文说明后关闭。不改座位
    与房主归属；任何校验或存储失败都不改变原密码与会话。
    """
    rejection = _origin_rejection(request, "修改密码")
    if rejection is not None:
        return rejection
    payload = await _request_json_object(request, "密码修改信息")
    if isinstance(payload, JSONResponse):
        return payload
    try:
        account, revoked = await run_in_threadpool(
            accounts.change_password,
            request.cookies.get(SESSION_COOKIE),
            payload.get("oldPassword"),
            payload.get("newPassword"),
            payload.get("confirmPassword"),
        )
    except AccountError as error:
        return JSONResponse(error_message(error.code, str(error)), status_code=error.status)
    except sqlite3.Error:
        return JSONResponse(error_message("auth.service-unavailable", "服务暂时不可用，请稍后重试。"), status_code=503)
    # 只停止被撤销登录（其他设备）已建立的连接；当前设备的连接照常使用。
    await _stop_conns(
        lambda conn: hashlib.sha256(conn.token.encode()).hexdigest() in revoked,
        "auth.password-changed", "密码已修改，请重新登录。")
    response = JSONResponse({"account": account.public()})
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
    rejection = _origin_rejection(request, "创建房间")
    if rejection is not None:
        return rejection
    body = await request.body()
    if body and body.strip() != b"{}":
        return JSONResponse(error_message("protocol.legacy-identity", "请刷新页面，房间使用当前登录账号。"), status_code=400)
    try:
        room = manager.create_room(account)
    except RuleError as error:
        return JSONResponse(rule_error_message(error), status_code=409)
    except (OSError, SaveError):
        return JSONResponse(error_message("room.create-failed", "创建房间失败，请稍后重试。"), status_code=503)
    # 工单 16：建房即占座，同样停止该账号已建立的旁观连接。
    await _stop_account_spectators(account.account_id)
    return {"code": room.code, "gameId": room.game_id}


@app.get("/api/account/room")
async def account_room(request: Request) -> Any:
    account = accounts.get_session(request.cookies.get(SESSION_COOKIE))
    if account is None:
        return JSONResponse(error_message("auth.login-required", "请先登录。"), status_code=401)
    room = manager.room_for_account(account.account_id)
    return {"room": {"code": room.code, "status": room.status} if room else None}


@app.get("/api/rooms/{code}")
async def room_info(code: str, request: Request) -> Any:
    # 规格替代旧匿名访问：服务端必须校验身份，未登录不区分房间是否存在。
    account = accounts.get_session(request.cookies.get(SESSION_COOKIE))
    if account is None:
        return JSONResponse(error_message("auth.login-required", "请先登录。"), status_code=401)
    room = manager.get_room(code)
    if room is None:
        return JSONResponse(error_message("room.not-found", "房间不存在，请核对房间号。"), status_code=404)
    return {
        "code": room.code,
        "status": room.status,
        "locked": room.locked,
        "playerCount": len(room.engine.state.players),
    }


@app.get("/api/rooms/{code}/replay")
async def replay(code: str, request: Request) -> Any:
    account = accounts.get_session(request.cookies.get(SESSION_COOKIE))
    if account is None:
        return JSONResponse(error_message("auth.login-required", "请先登录后再观看回放。"), status_code=401)
    room = manager.get_room(code)
    if room is None:
        return JSONResponse(error_message("room.not-found", "房间不存在，请核对房间号。"), status_code=404)
    if room.status != "ended":
        # 将来的管理关闭也不是正常终局，同样落在这里被拒绝。
        return JSONResponse(error_message("room.not-ended", "该对局尚未正常结束，暂无完整回放。"), status_code=409)
    return {"gameId": room.game_id, "steps": manager.replay(room)}


# ---- WebSocket --------------------------------------------------------


@app.on_event("startup")
async def _arm_restored_deadlines() -> None:
    # After a restart a restored room may hold an already-expired window; sync
    # arms it with delay 0 so the timeout lands through the normal pipeline.
    for room in manager.rooms.values():
        await deadline_scheduler.sync(room)


async def _stop_account_connections(account_id: str) -> int:
    """停止某账号全部已建立的房间连接（管理重置密码后，工单 20）。

    与退出登录同一终止管线（中文说明帧后关闭），不撤销座位、不改房主归属；
    返回停止的连接数。会话已在存储层撤销：即使此处遗漏，消息级校验与广播
    惰性踢出也会兜底停止旧连接。
    """
    return await _stop_conns(lambda conn: conn.account.account_id == account_id,
                             "auth.session-revoked", "管理员已重置该账号密码，请用新密码重新登录。")


@app.on_event("startup")
async def _start_admin_listener() -> None:
    # 管理工具（工单 19/20）走同一进程的回环监听：共享内存状态（含在线连接），
    # 只绑定 127.0.0.1；公网应用不注册任何管理路由。安装标识与管理凭证在
    # 存档目录的 admin/ 子目录，端口每次启动后写回，供 server.admin CLI 核对。
    global admin_server
    installation = admin_api.AdminInstallation(SAVES_DIR, create=True)
    endpoint = admin_api.AdminEndpoint(
        accounts=accounts, manager=manager, conns=conns, installation=installation,
        stop_account_connections=_stop_account_connections,
        close_executor=admin_close_room,
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
        await send_safe(websocket, error_message("room.not-found", "房间不存在，请核对房间号。", roomCode=code))
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
            if conn.room.status == "closed":
                # 管理关闭的竞态窗口里的迟到消息：连接已被终止流程关闭，
                # 这里保证它不再进入任何处理路径。
                await _terminate_conn(conn, "room.admin-closed", "房间已被管理员关闭，请返回大厅创建或加入新的房间。")
                return
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
        await send_safe(ws, error_message("command.invalid-shape", "进入房间的第一条消息必须是 hello 握手。"))
        return False
    version = raw.get("protocolVersion")
    if version != PROTOCOL_VERSION:
        await send_safe(
            ws,
            error_message(
                "protocol.version-mismatch",
                "客户端与服务端的协议版本不一致，请刷新页面。",
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
    if mode == "spectator":
        # 工单 16：账号存在未结束玩家座位时禁止同时旁观（服务端校验，
        # 覆盖跨设备与直接请求）；在原房应走玩家恢复路径，details 提供入口。
        occupied = manager.room_for_account(conn.account.account_id)
        if occupied is not None:
            await send_safe(ws, error_message(
                "spectator.seat-held",
                "你已有未结束房间的玩家座位，不能同时旁观；请返回原房间。",
                roomCode=occupied.code,
            ))
            return False
        if room.status == "closed":
            # 工单 22：已关闭房间不再可旁观——关闭竞态窗口里排队的旁观
            # hello 同样只能拿到明确拒绝。
            await send_safe(ws, error_message(
                "room.admin-closed", "房间已被管理员关闭，请返回大厅创建或加入新的房间。"))
            return False
        if room.status == "ended":
            # 旁观只针对未结束房间；已结束对局走公开回放入口（工单 23）。
            await send_safe(ws, error_message("room.ended", "对局已结束，不能旁观；可观看回放。"))
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
        # 工单 16：占座成功即停止该账号已建立的旁观连接（含恢复路径，幂等）。
        await _stop_account_spectators(conn.account.account_id, exclude=conn)
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
        await send_safe(conn.ws, error_message("command.invalid-shape", "消息必须是 JSON 对象。"))
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
    elif kind == "leave":
        await _handle_leave(conn)
    else:
        await send_safe(conn.ws, error_message("command.invalid-shape", "未知的消息类型。"))


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
        "leave-game",
        "timeout-intervention",
        "timeout-reveal",
        "timeout-skill",
        "timeout-return",
    ):
        error = RuleError("command.server-managed", "该命令由服务端托管，不能直接发送。")
        await send_safe(conn.ws, rule_error_message(error))
        await send_command_ack(conn, command_id, "rejected", error=error)
        metrics["commandsRejected"] += 1
        return
    actor = conn.player_id
    if actor is None:
        error = RuleError("player.not-eligible", "旁观者不能进行玩家操作。")
        await send_safe(conn.ws, rule_error_message(error))
        await send_command_ack(conn, command_id, "rejected", error=error)
        metrics["commandsRejected"] += 1
        return
    if not isinstance(command_type, str) or not command_type or not isinstance(payload, dict):
        error = RuleError("command.invalid-shape", "命令必须包含类型和对象参数。")
        await send_safe(conn.ws, rule_error_message(error))
        await send_command_ack(conn, command_id, "rejected", error=error)
        metrics["commandsRejected"] += 1
        return
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
        error = RuleError("command.invalid-shape", "expectedRevision 必须是整数。")
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


async def _handle_leave(conn: Conn) -> None:
    """工单 13：等待普通玩家的主动退座（真释放座位与占用）。

    房主与对局中的离开由 manager.exit_seat 明确拒绝（那些路径只断开连接，
    保留座位）；成功退座时全员收到 PlayerLeft 事件与更新名册，退座者得到
    `left` 确认帧后由服务端关闭连接——客户端不等关闭事件即可回大厅。
    """
    room = conn.room
    if conn.player_id is None:
        # 旁观者没有座位可退（旁观范围属工单 16）：按无座位明确拒绝。
        error = RuleError("seat.not-held", "你在此房间没有座位。")
        await send_safe(conn.ws, rule_error_message(error))
        return
    try:
        events = manager.exit_seat(room, conn.account)
    except RuleError as error:
        await send_safe(conn.ws, rule_error_message(error))
        return
    # 先确认退座者并移出连接注册表，再向剩余成员广播退座事件与名册；
    # 退座者不需要收到自己的 PlayerLeft 事件。
    _drop_conn(conn)
    await send_safe(conn.ws, {"type": "left", "roomCode": room.code})
    try:
        await conn.ws.close()
    except Exception:
        pass
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
            await send_safe(conn.ws, error_message("command.invalid-shape", "interventionTimeoutSeconds 必须是整数。"))
            return
        single_timeout_seconds = raw.get("singleWindowTimeoutSeconds")
        if single_timeout_seconds is not None and (isinstance(single_timeout_seconds, bool) or not isinstance(single_timeout_seconds, int)):
            await send_safe(conn.ws, error_message("command.invalid-shape", "singleWindowTimeoutSeconds 必须是整数。"))
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
        try:
            manager.set_locked(room, action == "lock")
        except RuleError as error:
            await send_safe(conn.ws, rule_error_message(error))
            return
    else:
        await send_safe(conn.ws, error_message("command.invalid-shape", "未知的房主操作。"))
        return
    await broadcast_state(room)


# Serve the built browser client when present (`cd client && npm run build`).
# API and WebSocket routes match before this mount, so /api and /ws win.
_CLIENT_DIST = Path(__file__).resolve().parent.parent / "client" / "dist"
if _CLIENT_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_CLIENT_DIST), html=True), name="client")
