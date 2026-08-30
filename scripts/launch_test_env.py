"""本地多人手动测试环境一键启动器。

一条命令完成：关闭旧测试窗口 → 构建前端 → 确保服务端在跑（脱离终端会话）→
创建新房间 → 平铺打开 N 个独立 Chrome 窗口并自动按"1..N"进房。

用法（仓库根目录）：

    .venv/Scripts/python.exe scripts/launch_test_env.py --players 6   # 偶数局
    .venv/Scripts/python.exe scripts/launch_test_env.py --players 7   # 奇数局：含 1 名审判者
    .venv/Scripts/python.exe scripts/launch_test_env.py --no-build    # 跳过前端构建
    .venv/Scripts/python.exe scripts/launch_test_env.py --close       # 只关闭测试窗口

说明：
- 浏览器窗口使用固定 profile（.scratch/chrome-profiles/p1..pN，已 gitignore），
  重复运行复用同一批目录，不会线性增长；删掉该目录即得到全新环境。
- 每次运行都会创建一个新房间；玩家 1 是房主（窗口位于左上角），由它点"开始游戏"。
- 自动进房依赖客户端的 URL 参数入口（?room=&name=&token=），见 client/src/App.tsx。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
CLIENT_DIST = REPO_ROOT / "client" / "dist"
DEFAULT_PROFILE_ROOT = REPO_ROOT / ".scratch" / "chrome-profiles"
TASKBAR_LOGICAL_HEIGHT = 48
LAUNCH_STAGGER_SECONDS = 0.4


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
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
    )


def close_test_windows(profile_root: Path) -> int:
    """Kill any Chromium process whose command line references our profile root."""
    escaped = str(profile_root).replace("'", "''")
    script = (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.CommandLine -like '*{escaped}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    powershell(script)
    time.sleep(1.5)
    return 0


def server_health(base_url: str) -> bool:
    try:
        return http_json(f"{base_url}/health", timeout=1.0).get("status") == "ok"
    except (URLError, OSError, ValueError):
        return False


def python_server_executable() -> str:
    venv_python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    return str(venv_python if venv_python.exists() else Path(sys.executable))


def start_server_detached(port: int) -> None:
    """Start uvicorn via WMI so it survives this terminal/agent session."""
    script_dir = REPO_ROOT / ".scratch"
    script_dir.mkdir(exist_ok=True)
    log_path = script_dir / "uvicorn.log"
    cmd_path = script_dir / "run-server.cmd"
    cmd_path.write_text(
        "@echo off\r\n"
        "rem Detached game server launched by scripts/launch_test_env.py\r\n"
        f"cd /d {REPO_ROOT}\r\n"
        f"{python_server_executable()} -m uvicorn server.app:app "
        f"--host 127.0.0.1 --port {port} > {log_path} 2>&1\r\n",
        encoding="ascii",
    )
    command_line = f'cmd.exe /c "{cmd_path}"'
    script = (
        "$startup = ([WMIClass]'Win32_ProcessStartup').CreateInstance(); "
        "$startup.ShowWindow = 0; "
        "$mc = ([WMIClass]'Win32_Process').GetMethodParameters('Create'); "
        f"$mc['CommandLine'] = '{command_line}'; "
        "([WMIClass]'Win32_Process').InvokeMethod('Create', $mc, $null)"
    )
    result = powershell(script)
    if "Return=" not in result.stdout and result.returncode != 0:
        # WMIClass invocation prints nothing on success; failures surface as stderr
        raise RuntimeError(f"server spawn failed: {result.stderr.strip()}")


def ensure_server(port: int) -> None:
    base_url = f"http://127.0.0.1:{port}"
    if server_health(base_url):
        log(f"[3/5] 服务端已在运行（{base_url}），直接复用。")
        return
    log(f"[3/5] 启动服务端（独立进程，端口 {port}）……")
    start_server_detached(port)
    deadline = time.time() + 25
    while time.time() < deadline:
        if server_health(base_url):
            log(f"[3/5] 服务端就绪：{base_url}（日志 .scratch/uvicorn.log）")
            return
        time.sleep(1.0)
    raise RuntimeError("服务端 25 秒内未就绪，请查看 .scratch/uvicorn.log")


def run_build() -> None:
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("未找到 npm，无法构建前端；请改用 --no-build（需已有 client/dist）。")
    log("[2/5] 构建前端（npm run build）……")
    result = subprocess.run(
        [npm, "run", "build"],
        cwd=REPO_ROOT / "client",
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"前端构建失败：\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")


def create_room(port: int) -> tuple[str, str]:
    room = http_json(f"http://127.0.0.1:{port}/api/rooms", method="POST")
    return str(room["code"]), str(room["hostToken"])


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
    host_token: str,
    port: int,
) -> None:
    screen_w, screen_h = logical_screen_size()
    rows = math.ceil(count / cols)
    cell_w = screen_w // cols
    cell_h = (screen_h - TASKBAR_LOGICAL_HEIGHT) // rows
    log(f"[5/5] 平铺打开 {count} 个窗口（{cols} 列 × {rows} 行，每格 {cell_w}×{cell_h}）……")
    for index in range(1, count + 1):
        x, y = grid_positions(count, cols, cell_w, cell_h)[index - 1]
        url = f"http://127.0.0.1:{port}/?room={room_code}&name={index}"
        if index == 1:
            url += f"&token={host_token}"
        command_line = (
            f'"{browser}" --user-data-dir={profile_root / f"p{index}"} '
            "--no-first-run --no-default-browser-check "
            "--disable-features=Translate,TranslateUI,TranslateMessageUI "
            f"--window-position={x},{y} --window-size={cell_w},{cell_h} --app={url}"
        )
        script = (
            "$mc = ([WMIClass]'Win32_Process').GetMethodParameters('Create'); "
            f"$mc['CommandLine'] = '{command_line}'; "
            "([WMIClass]'Win32_Process').InvokeMethod('Create', $mc, $null)"
        )
        powershell(script)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--players", type=int, default=6, help="玩家数 6-12（奇数局含审判者），默认 6")
    parser.add_argument("--port", type=int, default=8000, help="服务端端口，默认 8000")
    parser.add_argument("--cols", type=int, default=None, help="平铺列数（默认：6 人及以下 3 列，更多 4 列）")
    parser.add_argument("--no-build", action="store_true", help="跳过前端构建")
    parser.add_argument("--close", action="store_true", help="只关闭测试浏览器窗口后退出")
    args = parser.parse_args()

    profile_root = DEFAULT_PROFILE_ROOT
    if args.close:
        close_test_windows(profile_root)
        log("已关闭全部测试窗口。")
        return 0

    if not 6 <= args.players <= 12:
        parser.error("--players 必须在 6-12 之间")
    cols = args.cols or (3 if args.players <= 6 else 4)

    log(f"[1/5] 关闭旧测试窗口（profile：{profile_root}）……")
    close_test_windows(profile_root)

    try:
        if args.no_build and (CLIENT_DIST / "index.html").exists():
            log("[2/5] 跳过前端构建。")
        else:
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
    room_code, host_token = create_room(args.port)

    browsers = browser_candidates()
    if not browsers:
        log("错误：未找到 Chrome/Edge，无法打开测试窗口。")
        return 1

    launch_windows(browsers[0], profile_root, args.players, cols, room_code, host_token, args.port)

    joined = wait_until_all_joined(args.port, room_code, args.players)
    if joined >= args.players:
        log(f"完成：房间 {room_code} 已有 {joined}/{args.players} 名玩家（玩家 1 = 左上角房主窗口）。")
        if args.players % 2:
            log(f"{args.players} 人为奇数局：开局后含 1 名审判者。")
    else:
        log(f"警告：40 秒内只检测到 {joined}/{args.players} 人进房；窗口可能仍在加载，请目视确认（房间 {room_code}）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
