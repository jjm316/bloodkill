"""服务器终端管理命令行：在线查看账号与房间、重置密码（工单 19/20）。

在部署根目录（或仓库根目录）运行::

    python -m server.admin users
    python -m server.admin rooms
    python -m server.admin reset-password 用户名

命令不直接读改存档，而是请求正在运行的服务：管理端口、安装标识和管
理凭证来自存档目录的 ``admin/`` 子目录（``--saves-dir`` 可覆盖存档目录，
默认取环境变量 ``BLOOD_BOUND_SAVES_DIR`` 或 ``./saves``；``--port`` 可显
式指定管理端口）。请求仅发往 127.0.0.1，不走系统代理、不跟随重定向；
端口上若是最初目标之外的另一个服务实例（安装标识或存档目录不符）则拒
绝操作，避免误连。管理凭证不进命令行参数、不出现在输出中；重置密码
的新密码经隐藏输入读取（终端走 getpass，管道走等价的逐行读取），不进
命令行参数、不回显、不写入输出或日志，提交时只经本机回环请求体传输。
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import unicodedata
import urllib.error
import urllib.request

from .accounts import AccountError, validate_new_password
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


def _admin_request(port: int, path: str, token: str | None = None, *,
                   method: str = "GET", payload: dict | None = None,
                   timeout: float = 10) -> tuple[int, dict]:
    """对回环管理端口发一次请求；POST 的请求体只含允许经回环传输的数据。"""
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=headers)
    if token is not None:
        request.add_header("X-Admin-Token", token)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
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


_CLOSE_ROOM_TIMEOUT = 30  # 关闭要在锁内完成整房备份与存档搬移，放宽到 30 秒。


def _admin_post(port: int, path: str, token: str, payload: dict,
                timeout: float = _CLOSE_ROOM_TIMEOUT) -> tuple[int, dict]:
    """POST 写操作：统一走 _admin_request，默认用较长的关闭超时。"""
    return _admin_request(port, path, token, method="POST", payload=payload, timeout=timeout)


def run_close_room(port: int, token: str, room_code: str) -> int:
    """预览 → 再次输入房号确认 → 备份并关闭（工单 21）。"""
    from urllib.parse import quote
    status, preview = _admin_request(
        port, f"/admin/close-room/preview?code={quote(room_code)}", token)
    if status == 401:
        print("失败：管理凭证缺失或不正确：请核对服务器存档目录中的 admin/admin-token 后重试。",
              file=sys.stderr)
        return 1
    if status != 200:
        # 不存在 / 已正常结束 / 已被管理关闭：服务端已给出中文原因。
        print(f"失败：{preview.get('message', '未知错误')}", file=sys.stderr)
        return 1
    sys.stdout.write(render_close_preview(preview))
    sys.stdout.write(f"再次输入房号 {room_code} 确认关闭（其他输入或直接回车取消）：")
    sys.stdout.flush()
    try:
        answer = input()
    except EOFError:
        answer = ""
    if answer.strip() != room_code:
        print(f"已取消：输入与房间号不一致，未关闭房间 {room_code}。", file=sys.stderr)
        return 1
    status, result = _admin_post(port, "/admin/close-room", token, {
        "code": room_code,
        "expectedGameId": preview.get("gameId"),
        "expectedRevision": preview.get("revision"),
    })
    if status != 200:
        print(f"失败：{result.get('message', '未知错误')}", file=sys.stderr)
        return 1
    players = "、".join(result.get("affectedPlayers", []))
    print(f"已关闭房间 {result['code']}。")
    print(f"受影响玩家 {len(result.get('affectedPlayers', []))} 人：{players if players else '无'}")
    print(f"备份已写入：{result['backupPath']}")
    return 0


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
        lines.append(_render_room_line(room))
        players = "、".join(
            f"{player['username']}（{'在线' if player['online'] else '离线'}）"
            for player in room["players"]
        )
        lines.append(f"  玩家 {len(room['players'])} 人：{players if players else '无'}")
    return "\n".join(lines) + "\n"


# ---- 重置密码（工单 20）--------------------------------------------------


def _read_secret(prompt: str) -> str | None:
    """读一行秘密输入；返回 None 表示取消（空输入或输入流结束）。

    终端交互走 ``getpass``（不回显；Windows 控制台同样适用）；stdin 是管
    道或重定向时不存在回显媒介，逐行读取与隐藏输入等价：密码同样不进命
    令行参数、不写入输出或日志。提示语由本函数打印（getpass 只负责取值），
    保证中文提示在 Windows 控制台上按 UTF-8 正常显示。
    """
    sys.stdout.write(prompt)
    sys.stdout.flush()
    if sys.stdin.isatty():
        value = getpass.getpass("")
    else:
        value = sys.stdin.readline()
        if value == "":
            return None
    value = value.rstrip("\r\n")
    return value if value else None


def _prompt_new_password() -> str | None:
    """交互读取并校验新密码；校验失败的中文提示后可重试，空输入取消。

    形状判定与提示复用账号校验器（与服务端同一权威），CLI 校验仅为
    提前反馈；确认一致由本函数的二次读入循环完成，不走带确认的包装。
    """
    while True:
        password = _read_secret("请输入新密码（6–12 个字符，直接回车取消）：")
        if password is None:
            return None
        try:
            validate_new_password(password)
        except AccountError as error:
            print(f"{error}，请重新输入。")
            continue
        confirmation = _read_secret("请再次输入新密码确认（直接回车取消）：")
        if confirmation is None:
            return None
        if password != confirmation:
            print("两次输入的密码不一致，请重新输入。")
            continue
        return password


def _reset_password_command(port: int, token: str, username: str) -> int:
    password = _prompt_new_password()
    if password is None:
        print("已取消：未修改任何账号。", file=sys.stderr)
        return 1
    status, body = _admin_request(
        port, "/admin/reset-password", token,
        method="POST", payload={"username": username, "password": password})
    if status == 401:
        raise AdminCliError("管理凭证缺失或不正确：请核对服务器存档目录中的 admin/admin-token 后重试。")
    if status == 404:
        raise AdminCliError(f"账号「{username}」不存在，未修改任何账号；管理工具不会自动创建账号。")
    if status != 200:
        raise AdminCliError(f"重置未完成：{body.get('message', f'服务返回 HTTP {status}。')}")
    sys.stdout.write(render_reset_success(
        str(body.get("username", username)),
        int(body.get("revokedSessions", 0)),
        int(body.get("stoppedConnections", 0)),
    ))
    return 0


def render_reset_success(username: str, revoked_sessions: int, stopped_connections: int) -> str:
    return (
        f"已重置账号「{username}」的密码；该账号全部登录已撤销（所有设备）。\n"
        f"共撤销登录会话 {revoked_sessions} 个，停止已建立的房间连接 {stopped_connections} 条。\n"
        "座位与房主归属保持不变；该账号需用新密码重新登录。\n"
    )


def _render_room_line(room: dict) -> str:
    status = _ROOM_STATUS_LABELS.get(room["status"], room["status"])
    locked = "已锁定" if room["locked"] else "未锁定"
    return f"房间 {room['code']}｜对局 {room['gameId']}｜{status}｜{locked}｜房主 {room['hostUsername']}"


def render_close_preview(preview: dict) -> str:
    """close-room 预览：写入前显示目标房间的当前信息（工单 21）。"""
    lines = [
        "将要关闭的房间：",
        _render_room_line(preview),
    ]
    players = "、".join(
        f"{player['username']}（{'在线' if player['online'] else '离线'}）"
        for player in preview["players"]
    )
    lines.append(f"  玩家 {len(preview['players'])} 人：{players if players else '无'}")
    lines.append(
        "关闭将先备份该房存档，再停止其操作与计时器、断开全部连接并释放玩家占用；"
        "这不是正常终局，不产生胜负或身份揭晓。"
        )
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
    reset = commands.add_parser(
        "reset-password", help="重置账号密码并撤销其全部登录（新密码经隐藏输入，不进参数）", parents=[common])
    reset.add_argument("username", metavar="用户名", help="要重置密码的账号用户名")
    close_parser = commands.add_parser(
        "close-room", help="预览、确认并备份关闭一个未结束房间", parents=[common])
    close_parser.add_argument("room_code", metavar="房间号")
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
        if args.command == "reset-password":
            # 防误连核对通过后才提示输入新密码（工单 20）。
            return _reset_password_command(port, token, args.username)
        if args.command == "close-room":
            return run_close_room(port, token, args.room_code)
        payload = _fetch_query(port, token, args.command)
    except AdminCliError as error:
        print(f"失败：{error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已取消：未修改任何账号。", file=sys.stderr)
        return 130
    if args.command == "users":
        sys.stdout.write(render_users(payload["accounts"]))
    else:
        sys.stdout.write(render_rooms(payload["rooms"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
