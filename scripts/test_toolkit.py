"""本地测试工具箱：一条命令管理"服务端 + 前端构建 + 多窗口测试局"。

子命令（不带子命令时默认等价于 up）：

    up        关闭旧测试窗口 → 构建前端 → 确保服务端在跑 → 建新房 →
              平铺打开 N 个独立 Chrome 窗口并自动按"1..N"进房
    serve     只启动服务端（独立进程，脱离终端会话）
    restart   重启服务端（房间从 saves/ 自动恢复，进行中对局可断线重连）
    down      关闭服务端；--clear-saves 连存档一起清掉
    build     只构建前端（npm run build）
    status    查看服务端/存档/测试窗口状态
    close     只关闭测试浏览器窗口

常用示例（仓库根目录）：

    .venv/Scripts/python.exe scripts/test_toolkit.py up               # 默认 7 人：奇数局，含审判者
    .venv/Scripts/python.exe scripts/test_toolkit.py up --players 6   # 偶数局
    .venv/Scripts/python.exe scripts/test_toolkit.py restart
    .venv/Scripts/python.exe scripts/test_toolkit.py down
    .venv/Scripts/python.exe scripts/test_toolkit.py status

scripts/ 目录下另有同名中文双击 bat 薄壳（测试工具箱-*.bat），双击即可执行对应子命令。

说明：
- 浏览器窗口使用固定 profile（.scratch/chrome-profiles/p1..pN，已 gitignore），
  重复运行复用同一批目录，不会线性增长；删掉该目录即得到全新环境。
- 服务端通过 WMI 脱管启动（父进程 WmiPrvSE），不随终端/会话关闭；
  日志固定在 .scratch/uvicorn.log。
- status 与 up/serve 复用运行中的服务端时，若 server/ 与 blood_bound/
  下的代码比进程新，会提示 restart（不自动重启）。
- 每次运行 up 注册独立测试账号，玩家 1 创建房间并立即占座；它位于左上角，由它点"开始游戏"。
- 测试数据固定在 .scratch/toolkit-saves，与真实 saves 隔离；账号凭证只经本地 CDP 安装为 HttpOnly Cookie，URL 仅带 ?room=。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
CLIENT_DIST = REPO_ROOT / "client" / "dist"
SAVES_DIR = REPO_ROOT / ".scratch" / "toolkit-saves"
DEFAULT_PROFILE_ROOT = REPO_ROOT / ".scratch" / "chrome-profiles"
SERVER_CODE_ROOTS = (REPO_ROOT / "server", REPO_ROOT / "blood_bound")
STALE_TOLERANCE_SECONDS = 2.0
TASKBAR_LOGICAL_HEIGHT = 48
LAUNCH_STAGGER_SECONDS = 0.4
sys.path.insert(0, str(REPO_ROOT))
from scripts.account_client import AccountClient


def log(message: str) -> None:
    print(message, flush=True)


def http_json(url: str, method: str = "GET", timeout: float = 3.0) -> dict:
    request = Request(url, method=method, data=b"" if method == "POST" else None)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def browser_candidates() -> list[Path]:
    import os

    paths: list[Path] = []
    for env_key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env_key)
        if not base:
            continue
        for browser, relative in (
            ("chrome.exe", "Google/Chrome/Application/chrome.exe"),
            ("msedge.exe", "Microsoft/Edge/Application/msedge.exe"),
        ):
            paths.append(Path(base) / relative)
    return [path for path in paths if path.exists()]


def powershell(script: str) -> subprocess.CompletedProcess[str]:
    # 本机命令（netstat/taskkill/PowerShell）输出为 ANSI/GBK 编码，只解析其中的
    # ASCII 数字与关键字，因此用 errors="replace" 防止中文 Windows 下解码崩溃。
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
    )


def wmi_spawn(command_line: str, hidden: bool = False) -> subprocess.CompletedProcess[str]:
    """Create a detached process via the legacy WMIClass interface.

    Invoke-CimMethod with embedded objects fails (ReturnValue=21); WMIClass works.
    """
    script = ""
    if hidden:
        script += (
            "$startup = ([WMIClass]'Win32_ProcessStartup').CreateInstance(); "
            "$startup.ShowWindow = 0; "
        )
    script += (
        "$mc = ([WMIClass]'Win32_Process').GetMethodParameters('Create'); "
        f"$mc['CommandLine'] = '{command_line}'; "
        "([WMIClass]'Win32_Process').InvokeMethod('Create', $mc, $null)"
    )
    return powershell(script)


def where_commandline_like(escaped_fragment: str) -> str:
    return "$_.CommandLine -like '*" + escaped_fragment + "*'"


def close_test_windows(profile_root: Path) -> None:
    """Kill any Chromium process whose command line references our profile root."""
    escaped = str(profile_root).replace("'", "''")
    script = (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ {where_commandline_like(escaped)} }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    powershell(script)
    time.sleep(1.5)


def count_test_windows(profile_root: Path) -> int:
    escaped = str(profile_root).replace("'", "''")
    script = (
        "(Get-CimInstance Win32_Process | "
        f"Where-Object {{ {where_commandline_like(escaped)} }}).Count"
    )
    result = powershell(script)
    text = result.stdout.strip()
    return int(text) if text.isdigit() else 0


def server_health(base_url: str) -> bool:
    try:
        return http_json(f"{base_url}/health", timeout=1.0).get("status") == "ok"
    except (URLError, OSError, ValueError):
        return False


def port_listener_pids(port: int) -> set[int]:
    result = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=30,
    )
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
            try:
                pids.add(int(parts[4]))
            except ValueError:
                continue
    return pids


def find_server_pids(port: int) -> list[int]:
    pids = port_listener_pids(port)
    if not pids:
        return []
    require_owned_server(port)
    return sorted(pids)


def require_owned_server(port: int) -> None:
    try:
        marker = json.loads((SAVES_DIR / "server.json").read_text(encoding="utf-8"))
        pid = marker["pid"]
        valid = (marker["port"] == port and marker["savesDir"] == str(SAVES_DIR.resolve())
                 and marker["repoRoot"] == str(REPO_ROOT.resolve())
                 and pid in port_listener_pids(port)
                 and marker["started"] == process_start_time(pid))
    except (OSError, ValueError, KeyError):
        valid = False
    if not valid:
        raise RuntimeError("此端口的服务不属于当前隔离工具箱，拒绝注册账号或修改服务；请换端口启动工具箱。")


def record_server_owner(port: int) -> None:
    pids = port_listener_pids(port)
    if len(pids) != 1:
        raise RuntimeError("无法确认工具箱监听进程归属。")
    pid = next(iter(pids))
    started = process_start_time(pid)
    if started is None:
        raise RuntimeError("无法确认工具箱进程启动时间。")
    (SAVES_DIR / "server.json").write_text(json.dumps({"port": port, "pid": pid, "started": started,
        "savesDir": str(SAVES_DIR.resolve()), "repoRoot": str(REPO_ROOT.resolve())}), encoding="utf-8")


def newest_server_code_mtime() -> tuple[float, Path] | None:
    """SERVER_CODE_ROOTS 各包里最新 .py 的 (mtime, 路径)；无文件返回 None。"""
    newest: tuple[float, Path] | None = None
    for root in SERVER_CODE_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            mtime = path.stat().st_mtime
            if newest is None or mtime > newest[0]:
                newest = (mtime, path)
    return newest


def process_start_time(pid: int) -> float | None:
    """监听进程的创建时刻（Unix 秒）；进程已消失或输出异常时返回 None。"""
    result = powershell(
        f"Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' | "
        "ForEach-Object { ([DateTimeOffset]$_.CreationDate).ToUnixTimeMilliseconds() }"
    )
    text = result.stdout.strip()
    try:
        return float(text) / 1000 if text else None
    except ValueError:
        return None


def stale_server_warning(
    newest: tuple[float, Path] | None,
    started: float | None,
    port: int,
) -> str | None:
    """代码最新 mtime 晚于进程创建时刻（含容差）时给出 restart 提示。"""
    if newest is None or started is None:
        return None
    mtime, path = newest
    if mtime <= started + STALE_TOLERANCE_SECONDS:
        return None
    try:
        shown = path.relative_to(REPO_ROOT)
    except ValueError:
        shown = path
    return (
        f"警告：服务端代码比运行进程新（最新修改：{shown}），"
        f"界面可能不反映最新代码；请执行 .venv/Scripts/python.exe "
        f"scripts/test_toolkit.py restart --port {port}"
    )


def report_stale_server(port: int, listener_pids: set[int] | None = None) -> None:
    """在复用运行中服务端的出口打印陈旧提示；诊断失败一律静默。"""
    try:
        pids = port_listener_pids(port) if listener_pids is None else listener_pids
        starts = [
            start
            for start in (process_start_time(pid) for pid in sorted(pids))
            if start is not None
        ]
        warning = stale_server_warning(
            newest_server_code_mtime(), min(starts) if starts else None, port,
        )
        if warning:
            log(warning)
    except Exception:
        pass  # 陈旧提示是诊断信息，自身出错（进程查询超时、文件竞态）不得阻断宿主子命令


def stop_server(port: int, timeout: float = 15.0) -> int:
    """Kill the detached server process tree and wait for the port to free up."""
    pids = find_server_pids(port)
    for pid in pids:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            errors="replace",
        )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not port_listener_pids(port) and not server_health(base_url):
            break
        time.sleep(0.5)
    return len(pids)


def python_server_executable() -> str:
    venv_python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    return str(venv_python if venv_python.exists() else Path(sys.executable))


def start_server_detached(port: int) -> None:
    """Start uvicorn via WMI so it survives this terminal/agent session."""
    script_dir = REPO_ROOT / ".scratch"
    script_dir.mkdir(exist_ok=True)
    SAVES_DIR.mkdir(parents=True, exist_ok=True)
    marker_path = SAVES_DIR / "server.json"
    if marker_path.exists():
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if marker.get("port") != port and port_listener_pids(marker["port"]):
            raise RuntimeError("隔离数据目录已有其他工具箱服务使用，请先停止该工具箱服务。")
    log_path = script_dir / "uvicorn.log"
    cmd_path = script_dir / "run-server.cmd"
    cmd_path.write_text(
        "@echo off\r\n"
        "rem Detached game server launched by scripts/test_toolkit.py\r\n"
        f'set "BLOOD_BOUND_SAVES_DIR={SAVES_DIR}"\r\n'
        f"cd /d {REPO_ROOT}\r\n"
        f"{python_server_executable()} -m uvicorn server.app:app "
        f"--host 127.0.0.1 --port {port} > {log_path} 2>&1\r\n",
        encoding="ascii",
    )
    command_line = f'cmd.exe /c "{cmd_path}"'
    result = wmi_spawn(command_line, hidden=True)
    if "Return=" not in result.stdout and result.returncode != 0:
        # WMIClass invocation prints nothing on success; failures surface as stderr
        raise RuntimeError(f"服务端进程拉起失败：{result.stderr.strip()}")


def wait_server_ready(port: int, timeout: float = 25.0) -> None:
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if server_health(base_url):
            return
        time.sleep(1.0)
    raise RuntimeError(f"服务端 {int(timeout)} 秒内未就绪，请查看 .scratch/uvicorn.log")


def ensure_server(port: int) -> None:
    base_url = f"http://127.0.0.1:{port}"
    if server_health(base_url):
        require_owned_server(port)
        log(f"[3/5] 服务端已在运行（{base_url}），直接复用。")
        report_stale_server(port)
        return
    log(f"[3/5] 启动服务端（独立进程，端口 {port}）……")
    start_server_detached(port)
    wait_server_ready(port)
    record_server_owner(port)
    log(f"[3/5] 服务端就绪：{base_url}（日志 .scratch/uvicorn.log）")


def run_build() -> None:
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("未找到 npm，无法构建前端。")
    result = subprocess.run(
        [npm, "run", "build"],
        cwd=REPO_ROOT / "client",
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"前端构建失败：\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")


def create_room(port: int, session: AccountClient) -> str:
    require_owned_server(port)
    status, room = session.request("/api/rooms", method="POST")
    if status != 200:
        raise RuntimeError(f"创建测试房间失败（HTTP {status}）")
    return str(room["code"])


def install_browser_session(debug_port: int, session: AccountClient, room_code: str) -> None:
    from websockets.sync.client import connect
    deadline = time.monotonic() + 10
    targets = []
    while time.monotonic() < deadline:
        try:
            targets = http_json(f"http://127.0.0.1:{debug_port}/json/list")
            if targets:
                break
        except (URLError, OSError, ValueError):
            pass
        time.sleep(.1)
    target = next((target for target in targets if target.get("type") == "page"), None)
    if target is None:
        raise RuntimeError("测试浏览器未就绪。")
    with connect(target["webSocketDebuggerUrl"], proxy=None) as channel:
        name, value = session.cookie_header.split("=", 1)
        for index, method, params in [(1, "Network.setCookie", {"name": name, "value": value,
                "url": session.base, "path": "/", "httpOnly": True, "sameSite": "Strict"}),
                (2, "Page.navigate", {"url": f"{session.base}/?room={room_code}"})]:
            channel.send(json.dumps({"id": index, "method": method, "params": params}))
            while True:
                result = json.loads(channel.recv(timeout=5))
                if result.get("id") == index:
                    if "error" in result or result.get("result", {}).get("success") is False:
                        raise RuntimeError("测试浏览器登录初始化失败。")
                    break


def logical_screen_size() -> tuple[int, int]:
    """Primary screen size in DIP (the unit Chrome's --window-* flags use)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except OSError:
        pass
    width = ctypes.windll.user32.GetSystemMetrics(0)
    height = ctypes.windll.user32.GetSystemMetrics(1)
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
    except OSError:
        dpi = 96
    scale = (dpi or 96) / 96
    return int(width / scale), int(height / scale)


def grid_positions(count: int, cols: int, cell_w: int, cell_h: int) -> list[tuple[int, int]]:
    return [
        ((index % cols) * cell_w, (index // cols) * cell_h)
        for index in range(count)
    ]


def launch_windows(
    browser: Path,
    profile_root: Path,
    count: int,
    cols: int,
    room_code: str,
    sessions: list[AccountClient],
    port: int,
) -> None:
    screen_w, screen_h = logical_screen_size()
    rows = math.ceil(count / cols)
    cell_w = screen_w // cols
    cell_h = (screen_h - TASKBAR_LOGICAL_HEIGHT) // rows
    log(f"[5/5] 平铺打开 {count} 个窗口（{cols} 列 × {rows} 行，每格 {cell_w}×{cell_h}）……")
    for index in range(1, count + 1):
        x, y = grid_positions(count, cols, cell_w, cell_h)[index - 1]
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            debug_port = listener.getsockname()[1]
        command_line = (
            f'"{browser}" --user-data-dir={profile_root / f"p{index}"} '
            "--no-first-run --no-default-browser-check "
            f"--remote-debugging-address=127.0.0.1 --remote-debugging-port={debug_port} "
            "--disable-features=Translate,TranslateUI,TranslateMessageUI "
            f"--window-position={x},{y} --window-size={cell_w},{cell_h} --app=about:blank"
        )
        wmi_spawn(command_line)
        install_browser_session(debug_port, sessions[index - 1], room_code)
        time.sleep(LAUNCH_STAGGER_SECONDS)


def wait_until_all_joined(port: int, room_code: str, count: int, timeout: float = 40.0) -> int:
    deadline = time.time() + timeout
    last = 0
    while time.time() < deadline:
        try:
            last = int(http_json(f"http://127.0.0.1:{port}/api/rooms/{room_code}")["playerCount"])
            if last >= count:
                return last
        except (URLError, OSError, ValueError, KeyError):
            pass
        time.sleep(1.0)
    return last


def count_saved_rooms() -> int:
    if not SAVES_DIR.exists():
        return 0
    return len(list(SAVES_DIR.glob("g-*.json.gz")))


def clear_saves() -> int:
    if not SAVES_DIR.exists():
        return 0
    removed = 0
    for path in SAVES_DIR.iterdir():
        if path.is_file() and (path.name.startswith("g-") or path.name.endswith(".meta.json")):
            path.unlink()
            removed += 1
    return removed


def cmd_up(args: argparse.Namespace) -> int:
    if not 6 <= args.players <= 12:
        log("错误：--players 必须在 6-12 之间")
        return 1
    cols = args.cols or (3 if args.players <= 6 else 4)
    profile_root = DEFAULT_PROFILE_ROOT

    log(f"[1/5] 关闭旧测试窗口（profile：{profile_root}）……")
    close_test_windows(profile_root)

    try:
        if args.no_build and (CLIENT_DIST / "index.html").exists():
            log("[2/5] 跳过前端构建。")
        else:
            log("[2/5] 构建前端（npm run build）……")
            run_build()
    except RuntimeError as error:
        log(f"错误：{error}")
        return 1

    try:
        ensure_server(args.port)
    except (RuntimeError, OSError) as error:
        log(f"错误：{error}")
        return 1

    log("[4/5] 创建新房间……")
    require_owned_server(args.port)
    sessions = [AccountClient(f"http://127.0.0.1:{args.port}").register_test_account() for _ in range(args.players)]
    room_code = create_room(args.port, sessions[0])

    browsers = browser_candidates()
    if not browsers:
        log("错误：未找到 Chrome/Edge，无法打开测试窗口。")
        return 1

    launch_windows(browsers[0], profile_root, args.players, cols, room_code, sessions, args.port)

    join_timeout = 40.0
    joined = wait_until_all_joined(args.port, room_code, args.players, timeout=join_timeout)
    if joined >= args.players:
        log(f"完成：房间 {room_code} 已有 {joined}/{args.players} 名玩家（玩家 1 = 左上角房主窗口）。")
        if args.players % 2:
            log(f"{args.players} 人为奇数局：开局后含 1 名审判者。")
    else:
        log(f"警告：{int(join_timeout)} 秒内只检测到 {joined}/{args.players} 人进房；窗口可能仍在加载，请目视确认（房间 {room_code}）。")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    base_url = f"http://127.0.0.1:{args.port}"
    if server_health(base_url):
        require_owned_server(args.port)
        log(f"服务端已在运行（{base_url}），无需重复启动。")
        report_stale_server(args.port)
        return 0
    log(f"启动服务端（独立进程，端口 {args.port}）……")
    try:
        start_server_detached(args.port)
        wait_server_ready(args.port)
        record_server_owner(args.port)
    except (RuntimeError, OSError) as error:
        log(f"错误：{error}")
        return 1
    log(f"完成：服务端就绪 {base_url}（日志 .scratch/uvicorn.log）。隔离房间将从 {SAVES_DIR} 自动恢复。")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    log(f"重启服务端（端口 {args.port}）……")
    killed = stop_server(args.port)
    if killed:
        log(f"已停止旧进程（{killed} 个），等待端口释放……")
    else:
        log("服务端本来就没在跑。")
    try:
        start_server_detached(args.port)
        wait_server_ready(args.port)
        record_server_owner(args.port)
    except (RuntimeError, OSError) as error:
        log(f"错误：{error}")
        return 1
    log(f"完成：服务端已重启 http://127.0.0.1:{args.port}，存档房间（{count_saved_rooms()} 个）自动恢复。")
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    killed = stop_server(args.port)
    if killed:
        log(f"完成：已关闭服务端（结束 {killed} 个进程），端口 {args.port} 已释放。")
    else:
        log("服务端本来就没在跑。")
    if args.clear_saves:
        removed = clear_saves()
        log(f"已清空隔离房间存档：删除 {SAVES_DIR} 下 {removed} 个文件（账号与服务归属记录保留）。")
    return 0


def cmd_build(_args: argparse.Namespace) -> int:
    log("构建前端（npm run build）……")
    try:
        run_build()
    except RuntimeError as error:
        log(f"错误：{error}")
        return 1
    log("完成：前端已构建到 client/dist。")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    base_url = f"http://127.0.0.1:{args.port}"
    if server_health(base_url):
        pids = port_listener_pids(args.port)
        pid_text = f"，PID {'/'.join(str(pid) for pid in sorted(pids))}" if pids else ""
        log(f"服务端：运行中（{base_url}{pid_text}）")
        report_stale_server(args.port, pids)
    else:
        log(f"服务端：未运行（端口 {args.port}）")
    log(f"隔离存档房间：{count_saved_rooms()} 个（{SAVES_DIR}，服务端重启后自动恢复）")
    log(f"测试浏览器窗口：{count_test_windows(DEFAULT_PROFILE_ROOT)} 个（profile：.scratch/chrome-profiles）")
    return 0


def cmd_close(_args: argparse.Namespace) -> int:
    close_test_windows(DEFAULT_PROFILE_ROOT)
    log("已关闭全部测试窗口。")
    return 0


def _add_port(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", type=int, default=8000, help="服务端端口，默认 8000")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", metavar="子命令")

    up = sub.add_parser("up", help="关闭旧窗口→构建→确保服务端→建房→平铺开窗自动进房")
    up.add_argument("--players", type=int, default=7, help="玩家数 6-12（奇数局含审判者），默认 7")
    _add_port(up)
    up.add_argument("--cols", type=int, default=None, help="平铺列数（默认：6 人及以下 3 列，更多 4 列）")
    up.add_argument("--no-build", action="store_true", help="跳过前端构建")
    up.set_defaults(func=cmd_up)

    serve = sub.add_parser("serve", help="只启动服务端（独立进程）")
    _add_port(serve)
    serve.set_defaults(func=cmd_serve)

    restart = sub.add_parser("restart", help="重启服务端（存档房间自动恢复）")
    _add_port(restart)
    restart.set_defaults(func=cmd_restart)

    down = sub.add_parser("down", help="关闭服务端")
    _add_port(down)
    down.add_argument("--clear-saves", action="store_true", help="顺带清空隔离工具箱的房间存档，保留账号")
    down.set_defaults(func=cmd_down)

    build = sub.add_parser("build", help="只构建前端")
    build.set_defaults(func=cmd_build)

    status = sub.add_parser("status", help="查看服务端/存档/测试窗口状态")
    _add_port(status)
    status.set_defaults(func=cmd_status)

    close = sub.add_parser("close", help="只关闭测试浏览器窗口")
    close.set_defaults(func=cmd_close)

    return parser


def normalize_argv(argv: list[str]) -> list[str]:
    """兼容旧用法：不带子命令时默认按 up 处理（python scripts/test_toolkit.py --players 7）"""
    if not argv or argv[0].startswith("-"):
        return ["up", *argv]
    return list(argv)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(normalize_argv(list(sys.argv[1:] if argv is None else argv)))
    try:
        return args.func(args)
    except (RuntimeError, OSError, ValueError) as error:
        log(f"错误：{error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
