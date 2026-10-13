"""仅限服务器本机的管理端点与安装配置（工单 19；close-room 属工单 21）。

运行中的服务在自己的进程内启动一个只绑定 127.0.0.1 的微型 HTTP 监听，
管理命令行（``server/admin.py``）通过它读取账号与房间现状；命令行不另
建房间管理实例，也不直接读改活动存档。管理凭证与实例标识存放在存档
目录的 ``admin/`` 子目录：``installation.json`` 记录稳定安装标识、存档
目录规范路径和当前管理端口（每次启动后写回），``admin-token`` 是独立
管理凭证。命令行据此核对目标实例，防止误连同一台机器上的另一个服务。

公网 FastAPI 应用不注册任何管理路由；即使管理端口配置错误，查询也只
会失败，不会影响另一实例的数据。查询响应只包含允许字段（allowlist），
不序列化数据库行或房间元数据，密码摘要、会话凭证不会进入输出。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
import hmac
import json
import os
import secrets
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlparse

ADMIN_DIRECTORY = "admin"
INSTALLATION_NAME = "installation.json"
TOKEN_NAME = "admin-token"
TOKEN_HEADER = "x-admin-token"

_READ_TIMEOUT = 10.0
_READ_LINE_LIMIT = 16 * 1024
_MAX_BODY_BYTES = 64 * 1024

# 工单 21：close-room 的执行器由 server.app 注入（同进程内完成备份、停用、
# 取消计时器与断开连接）；这里只做鉴权、错误映射与中文报错。
CloseExecutor = Callable[[str, str | None, int | None], Awaitable[dict[str, Any]]]


@dataclass
class AdminCloseError(Exception):
    """close-room 执行器报告的失败：HTTP 状态、错误码与中文说明。"""

    status: int
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def canonical_saves_dir(saves_dir: str | Path) -> str:
    """Norm-cased absolute path so the CLI and the service compare identical strings."""
    return os.path.normcase(os.path.abspath(str(saves_dir)))


class AdminInstallation:
    """管理子目录中的安装标识、管理凭证与端口记录。

    服务进程以 ``create=True`` 打开：首次生成安装标识与管理凭证，同目录
    重启复用既有值；命令行以 ``create=False`` 只读。写文件用临时文件加
    原子替换，读不到或损坏一律视为缺失，由调用方给出中文错误。
    """

    def __init__(self, saves_dir: str | Path, *, create: bool = False) -> None:
        self.saves_dir = Path(saves_dir)
        self.directory = self.saves_dir / ADMIN_DIRECTORY
        self.installation_path = self.directory / INSTALLATION_NAME
        self.token_path = self.directory / TOKEN_NAME
        self._identity: dict[str, Any] | None = None
        self._token: str | None = None
        if create:
            self._ensure_files()

    # ---- 服务端（create=True）--------------------------------------------

    def _ensure_files(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        data = self._read_json(self.installation_path)
        if not isinstance(data, dict) or not isinstance(data.get("installationId"), str) \
                or not isinstance(data.get("savesDir"), str):
            data = {
                "installationId": secrets.token_hex(16),
                "savesDir": canonical_saves_dir(self.saves_dir),
            }
            self._write_json(self.installation_path, data)
        self._identity = data
        self._token = self._read_token_file()
        if not self._token:
            self._write_token(secrets.token_urlsafe(32))
            self._token = self._read_token_file()

    def installation_id(self) -> str:
        assert self._identity is not None, "installation_id 只在 create=True 后可用"
        return str(self._identity["installationId"])

    def saves_dir_identity(self) -> str:
        assert self._identity is not None, "saves_dir_identity 只在 create=True 后可用"
        return str(self._identity["savesDir"])

    def record_port(self, port: int) -> None:
        """把本次启动的实际管理端口写回 installation.json（标识与路径保持不变）。"""
        data = dict(self._identity or self._read_json(self.installation_path) or {})
        data["adminPort"] = int(port)
        self._write_json(self.installation_path, data)
        self._identity = data

    def _write_token(self, token: str) -> None:
        temporary = self.token_path.with_suffix(".tmp")
        temporary.write_text(token + "\n", encoding="utf-8")
        temporary.replace(self.token_path)
        if os.name == "posix":
            # Linux 部署限制为服务用户可读写；Windows 依赖目录 ACL，不用 chmod 假装生效。
            os.chmod(self.token_path, 0o600)

    # ---- 双端共用 ---------------------------------------------------------

    def snapshot(self) -> dict[str, Any] | None:
        """CLI 读取的安装记录；文件缺失或损坏返回 None。"""
        data = self._read_json(self.installation_path)
        if not isinstance(data, dict) or not isinstance(data.get("installationId"), str) \
                or not isinstance(data.get("savesDir"), str):
            return None
        return data

    def read_token(self) -> str | None:
        """服务端返回启动时缓存的凭证（改动文件需重启生效）；CLI 读当前文件。"""
        if self._token is not None:
            return self._token
        return self._read_token_file()

    def _read_token_file(self) -> str | None:
        try:
            token = self.token_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return None
        return token or None

    # ---- 基础文件操作 -----------------------------------------------------

    @staticmethod
    def _read_json(path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(path)


class AdminEndpoint:
    """把运行中服务的账号/房间现状映射为允许字段，并执行凭证校验。

    ``accounts``/``manager``/``conns`` 是 server.app 进程内的同一批对象
    （``conns`` 为可变字典引用），因此查询结果始终反映实时内存状态，
    包含在线连接情况；查询本身只读，不触发持久化。``close_executor``
    （工单 21）由 server.app 注入：在同进程内完成预览校验通过后的备份
    与关闭，本类只负责鉴权与错误映射。
    """

    def __init__(self, *, accounts: Any, manager: Any, conns: dict[str, Any],
                 installation: AdminInstallation,
                 close_executor: CloseExecutor | None = None) -> None:
        self._accounts = accounts
        self._manager = manager
        self._conns = conns
        self._installation = installation
        self._close_executor = close_executor

    # ---- HTTP 路由 --------------------------------------------------------

    async def handle(self, method: str, path: str, headers: dict[str, str],
                     body: Any = None) -> tuple[int, dict[str, Any]]:
        target = urlparse(path)
        route, query = target.path, parse_qs(target.query)
        if route == "/admin/instance":
            if method != "GET":
                return 405, {"error": "admin.method-not-allowed", "message": "该管理接口只接受 GET。"}
            # 仅供本机命令行核对目标实例身份；不含任何凭证。
            return 200, {
                "installationId": self._installation.installation_id(),
                "savesDir": self._installation.saves_dir_identity(),
            }
        if route not in ("/admin/users", "/admin/rooms",
                         "/admin/close-room/preview", "/admin/close-room"):
            return 404, {"error": "admin.not-found", "message": "未知的管理查询。"}
        if not self._authorized(headers.get(TOKEN_HEADER)):
            return 401, {"error": "admin.auth-required", "message": "管理凭证缺失或不正确。"}
        if route in ("/admin/users", "/admin/rooms") and method != "GET":
            return 405, {"error": "admin.method-not-allowed", "message": "该管理接口只接受 GET 查询。"}
        if route == "/admin/users":
            return 200, {"accounts": self.account_rows()}
        if route == "/admin/rooms":
            return 200, {"rooms": self.room_rows()}
        if route == "/admin/close-room/preview":
            if method != "GET":
                return 405, {"error": "admin.method-not-allowed", "message": "关闭预览只接受 GET。"}
            codes = query.get("code", [])
            if len(codes) != 1 or not codes[0]:
                return 400, {"error": "admin.bad-request", "message": "请通过 ?code=房号 指定要预览的房间。"}
            return self.close_room_preview(codes[0])
        # /admin/close-room：确认执行（POST + JSON body）。
        if method != "POST":
            return 405, {"error": "admin.method-not-allowed", "message": "关闭房间必须用 POST 确认执行。"}
        if not isinstance(body, dict):
            return 400, {"error": "admin.bad-request", "message": "请求体必须是 JSON 对象。"}
        code = body.get("code")
        if not isinstance(code, str) or not code:
            return 400, {"error": "admin.bad-request", "message": "请求体缺少要关闭的房间号（code）。"}
        expected_game_id = body.get("expectedGameId")
        if expected_game_id is not None and not isinstance(expected_game_id, str):
            return 400, {"error": "admin.bad-request", "message": "expectedGameId 必须是字符串。"}
        expected_revision = body.get("expectedRevision")
        if expected_revision is not None and (isinstance(expected_revision, bool)
                                               or not isinstance(expected_revision, int)):
            return 400, {"error": "admin.bad-request", "message": "expectedRevision 必须是整数。"}
        if self._close_executor is None:
            return 503, {"error": "admin.unavailable", "message": "服务未接入关闭执行器。"}
        try:
            result = await self._close_executor(code, expected_game_id, expected_revision)
        except AdminCloseError as error:
            payload = {"error": error.code, "message": error.message}
            if error.details:
                payload["details"] = error.details
            return error.status, payload
        return 200, result

    def _authorized(self, presented: str | None) -> bool:
        expected = self._installation.read_token()
        if not expected or not isinstance(presented, str) or not presented:
            return False
        return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))

    # ---- 允许字段构建（close-room 预览复用同一路径） ---------------------

    def account_rows(self) -> list[dict[str, Any]]:
        """账号 + 当前未结束房间占用；不含密码摘要或会话凭证。"""
        rows: list[dict[str, Any]] = []
        for account in self._accounts.list_accounts():
            room = self._manager.room_for_account(account.account_id)
            rows.append({
                "username": account.username,
                "accountId": account.account_id,
                "roomCode": room.code if room is not None else None,
            })
        return rows

    def room_rows(self) -> list[dict[str, Any]]:
        """房间号、对局引用、状态、房主、玩家与在线情况（等待/进行在前）。"""
        order = {"waiting": 0, "playing": 1, "ended": 2}
        rows: list[dict[str, Any]] = []
        for room in sorted(self._manager.rooms.values(),
                           key=lambda item: (order.get(item.status, 3), item.created_at)):
            rows.append(self._room_row(room))
        return rows

    def close_room_preview(self, code: str) -> tuple[int, dict[str, Any]]:
        """close-room 预览：单房允许字段 + 修订号；拒绝不存在/已结束/已关闭。"""
        import time as time_module
        room = self._manager.get_room(code)
        if room is None:
            record = self._manager.closed_room_record(code)
            if record is not None:
                closed_at = record.get("closedAt")
                when = (time_module.strftime("%Y-%m-%d %H:%M:%S", time_module.localtime(closed_at))
                        if isinstance(closed_at, (int, float)) else "时间未知")
                payload: dict[str, Any] = {
                    "error": "room.admin-closed",
                    "message": f"房间 {code} 已于 {when} 被管理关闭，无需重复处理。",
                }
                if isinstance(record.get("backupPath"), str):
                    payload["details"] = {"backupPath": record["backupPath"]}
                return 409, payload
            return 404, {"error": "room.not-found", "message": f"房间 {code} 不存在，请核对房间号。"}
        if room.status == "ended":
            return 409, {"error": "room.ended",
                         "message": f"房间 {code} 已正常结束，无需管理关闭；回放照常保留。"}
        if room.status not in {"waiting", "playing"}:
            return 409, {"error": "room.admin-closed",
                         "message": f"房间 {code} 已被管理关闭，无需重复处理。"}
        row = self._room_row(room)
        row["revision"] = room.engine.state.revision
        return 200, row

    def _room_row(self, room: Any) -> dict[str, Any]:
        display_names = {
            player.player_id: player.display_name
            for player in room.engine.state.players.values()
        }
        players: list[dict[str, Any]] = []
        for player_id in room.seat_accounts.values():
            players.append({
                "username": display_names.get(player_id, "（未知玩家）"),
                "online": self._player_online(room, player_id),
            })
        return {
            "code": room.code,
            "gameId": room.game_id,
            "status": room.status,
            "locked": room.locked,
            "hostUsername": display_names.get(room.host_player_id, "（未知）"),
            "players": players,
        }

    def _player_online(self, room: Any, player_id: str) -> bool:
        return any(
            connection.ready and connection.room is room and connection.player_id == player_id
            for connection in self._conns.values()
        )


# ---- 回环监听（手写最小 HTTP/1.1，仅 GET、单请求、无 body） -----------------


async def start_admin_server(endpoint: AdminEndpoint) -> asyncio.AbstractServer:
    """在同一进程的事件循环上启动仅绑定 127.0.0.1 的管理监听。"""
    return await asyncio.start_server(
        _serve_client_factory(endpoint),
        host="127.0.0.1",
        port=0,
        backlog=8,
        limit=_READ_LINE_LIMIT,
    )


def _serve_client_factory(endpoint: AdminEndpoint):
    async def _serve_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        status, payload = 400, {"error": "admin.bad-request", "message": "请求格式不正确。"}
        try:
            request_line = await asyncio.wait_for(reader.readline(), _READ_TIMEOUT)
            parts = request_line.decode("latin-1", "replace").split()
            if len(parts) == 3:
                headers = await _read_headers(reader)
                body: Any = None
                if parts[0] == "POST":
                    body = await _read_body(reader, headers)
                status, payload = await endpoint.handle(parts[0], parts[1], headers, body)
        except (asyncio.TimeoutError, ValueError, ConnectionError, OSError):
            pass
        try:
            await _write_json(writer, status, payload)
            writer.close()
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass

    return _serve_client


async def _read_body(reader: asyncio.StreamReader, headers: dict[str, str]) -> Any:
    """读取并解析 POST 的 JSON body（受长度上限约束；空 body 视为无 JSON）。"""
    raw_length = headers.get("content-length", "")
    try:
        length = int(raw_length)
    except ValueError:
        raise ValueError("Content-Length 缺失或不是整数") from None
    if length <= 0:
        return None
    if length > _MAX_BODY_BYTES:
        raise ValueError("请求体过大")
    data = await asyncio.wait_for(reader.readexactly(length), _READ_TIMEOUT)
    return json.loads(data.decode("utf-8"))


async def _read_headers(reader: asyncio.StreamReader) -> dict[str, str]:
    headers: dict[str, str] = {}
    for _ in range(100):
        line = await asyncio.wait_for(reader.readline(), _READ_TIMEOUT)
        if line in (b"\r\n", b"\n", b""):
            break
        name, separator, value = line.decode("latin-1", "replace").partition(":")
        if separator:
            headers[name.strip().lower()] = value.strip()
    return headers


async def _write_json(writer: asyncio.StreamWriter, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 404: "Not Found",
              405: "Method Not Allowed", 409: "Conflict", 503: "Service Unavailable"}.get(status, "Error")
    head = (
        f"HTTP/1.1 {status} {reason}\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("ascii")
    writer.write(head + body)
    await writer.drain()
