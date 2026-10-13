"""服务器终端管理命令行：在线查看账号与房间（工单 19）。

在部署根目录（或仓库根目录）运行::

    python -m server.admin users
    python -m server.admin rooms

命令不直接读改存档，而是请求正在运行的服务：管理端口、安装标识和管
理凭证来自存档目录的 ``admin/`` 子目录（``--saves-dir`` 可覆盖存档目录，
默认取环境变量 ``BLOOD_BOUND_SAVES_DIR`` 或 ``./saves``；``--port`` 可显
式指定管理端口）。请求仅发往 127.0.0.1，不走系统代理、不跟随重定向；
端口上若是最初目标之外的另一个服务实例（安装标识或存档目录不符）则拒
绝查询，避免误操作。管理凭证不进命令行参数、不出现在输出中。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import unicodedata
import urllib.error
import urllib.request

from .admin_api import AdminInstallation, canonical_saves_dir

TROUBLE_SHOOTING = "请确认服务正在运行、--saves-dir 与服务启动时的存档目录一致。"


class AdminCliError(Exception):
    """面向服务器终端的中文失败说明；出现即以非零状态退出。"""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """管理端口不应重定向；禁止任何带凭证的转发。"""

    def redirect_request(self, request, file_pointer, code, message, headers, newurl):
        return None


# 直连回环地址：显式绕过系统代理，且不跟随重定向。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def _admin_request(port: int, path: str, token: str | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if token is not None:
        request.add_header("X-Admin-Token", token)
    try:
        with _OPENER.open(request, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        try:
            body = json.load(error)
        except (ValueError, OSError):
            body = {}
        return error.code, body if isinstance(body, dict) else {}
    except urllib.error.URLError as error:
        raise AdminCliError(
            f"无法连接 127.0.0.1:{port} 上的管理端口（{error.reason}）。"
            f"服务可能未运行或端口已变化。{TROUBLE_SHOOTING}"
        ) from None
    except (TimeoutError, OSError) as error:
        raise AdminCliError(
            f"连接 127.0.0.1:{port} 上的管理端口超时或中断（{error}）。{TROUBLE_SHOOTING}"
        ) from None


def _load_installation(saves_dir: Path) -> dict:
    installation = AdminInstallation(saves_dir)
    snapshot = installation.snapshot()
    if snapshot is None:
        raise AdminCliError(
            f"存档目录 {saves_dir} 中没有可用的管理配置（admin/installation.json）。"
            "服务可能从未在此存档目录启动过；请核对 --saves-dir。"
        )
    return snapshot


def _load_token(saves_dir: Path) -> str:
    token = AdminInstallation(saves_dir).read_token()
    if not token:
        raise AdminCliError(
            f"存档目录 {saves_dir} 中没有可用的管理凭证（admin/admin-token）。"
            "请核对 --saves-dir；凭证文件只能由服务启动时生成。"
        )
    return token


def _verify_instance(port: int, identity: dict, installation: dict, saves_dir: Path) -> None:
    expected_dir = canonical_saves_dir(saves_dir)
    if (identity.get("installationId") != installation.get("installationId")
            or identity.get("savesDir") != expected_dir):
        raise AdminCliError(
            f"端口 {port} 上是另一个服务实例（安装标识或存档目录与 {saves_dir} 不匹配），已拒绝查询。"
            "请核对 --port 与 --saves-dir，避免误操作其他服务。"
        )


def _fetch_query(port: int, token: str, command: str) -> dict:
    status, body = _admin_request(port, f"/admin/{command}", token)
    if status == 401:
        raise AdminCliError("管理凭证缺失或不正确：请核对服务器存档目录中的 admin/admin-token 后重试。")
    if status != 200:
        raise AdminCliError(f"服务返回 HTTP {status}：{body.get('message', '未知错误')}")
    return body


# ---- 中文输出 ------------------------------------------------------------

_ROOM_STATUS_LABELS = {"waiting": "等待中", "playing": "进行中", "ended": "已结束"}


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(1, width - _display_width(text))


def render_users(accounts: list[dict]) -> str:
    if not accounts:
        return "当前没有注册账号。\n"
    name_width = max(_display_width("用户名"), *( _display_width(a["username"]) for a in accounts))
    reference_width = max(34, max(len(a["accountId"]) for a in accounts) + 2)
    lines = [
        f"共 {len(accounts)} 个账号：",
        _pad("用户名", name_width + 2) + _pad("账号引用", reference_width) + "房间号",
    ]
    for account in accounts:
        room = account["roomCode"] if account["roomCode"] else "（未占用）"
        lines.append(
            _pad(account["username"], name_width + 2)
            + _pad(account["accountId"], reference_width)
            + room
        )
    return "\n".join(lines) + "\n"


def render_rooms(rooms: list[dict]) -> str:
    if not rooms:
        return "当前没有房间。\n"
    summary: list[str] = []
    for status in ("waiting", "playing", "ended"):
        count = sum(1 for room in rooms if room["status"] == status)
        if count:
            summary.append(f"{_ROOM_STATUS_LABELS[status]} {count} 个")
    others = len(rooms) - sum(1 for room in rooms if room["status"] in _ROOM_STATUS_LABELS)
    if others:
        summary.append(f"其他 {others} 个")
    lines = [f"共 {len(rooms)} 个房间（{'、'.join(summary)}）："]
    for room in rooms:
        status = _ROOM_STATUS_LABELS.get(room["status"], room["status"])
        locked = "已锁定" if room["locked"] else "未锁定"
        lines.append(
            f"房间 {room['code']}｜对局 {room['gameId']}｜{status}｜{locked}｜房主 {room['hostUsername']}"
        )
        players = "、".join(
            f"{player['username']}（{'在线' if player['online'] else '离线'}）"
            for player in room["players"]
        )
        lines.append(f"  玩家 {len(room['players'])} 人：{players if players else '无'}")
    return "\n".join(lines) + "\n"


# ---- 入口 ----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    # 选项同时挂在主命令与子命令上：`--saves-dir X users` 与 `users --saves-dir X` 均可用。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--saves-dir",
        default=os.environ.get("BLOOD_BOUND_SAVES_DIR", "saves"),
        help="存档目录（默认取环境变量 BLOOD_BOUND_SAVES_DIR 或 ./saves，须与服务启动配置一致）",
    )
    common.add_argument(
        "--port",
        type=int,
        default=None,
        help="管理端口（默认使用存档目录 admin/installation.json 记录的端口）",
    )
    parser = argparse.ArgumentParser(
        prog="python -m server.admin",
        description="Blood Bound 服务器管理命令（仅服务器本机终端使用）",
        parents=[common],
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="命令")
    commands.add_parser("users", help="查看账号及其当前房间占用", parents=[common])
    commands.add_parser("rooms", help="查看房间号、状态、房主、玩家与在线情况", parents=[common])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    saves_dir = Path(args.saves_dir)
    try:
        installation = _load_installation(saves_dir)
        port = args.port if args.port is not None else installation.get("adminPort")
        if not isinstance(port, int) or port <= 0:
            raise AdminCliError(
                f"管理配置未记录有效端口（admin/installation.json 的 adminPort 缺失）。"
                "服务可能未完成启动；请先正常启动服务后重试。"
            )
        token = _load_token(saves_dir)
        status, identity = _admin_request(port, "/admin/instance")
        if status != 200 or not isinstance(identity.get("installationId"), str):
            raise AdminCliError(
                f"端口 {port} 上不是预期的管理服务（HTTP {status}）。{TROUBLE_SHOOTING}"
            )
        _verify_instance(port, identity, installation, saves_dir)
        payload = _fetch_query(port, token, args.command)
    except AdminCliError as error:
        print(f"失败：{error}", file=sys.stderr)
        return 1
    if args.command == "users":
        sys.stdout.write(render_users(payload["accounts"]))
    else:
        sys.stdout.write(render_rooms(payload["rooms"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
