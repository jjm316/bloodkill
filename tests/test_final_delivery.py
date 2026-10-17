"""工单 27：更新包、管理用法与完整验收证据。

按 ``scripts/deploy-cloud.sh`` 的同一打包清单（server/、blood_bound/、
client/dist/、systemd unit）构造真实部署包，解包到独立目录模拟云端
``/opt/bloodkill`` 布局，从该目录以默认 ``./saves`` 启动真实 uvicorn，并在
部署根目录用真实 CLI 子进程（``python -m server.admin``）核对查看、重置
密码与单房清理；随后模拟一次「重新打包 → 解包覆盖 → 新进程重启」的更新，
验证账号、会话、占用、管理凭证与备份全部保留、已撤销登录与已关闭房间不
复活；最后走完整用户闭环（注册 → 建房 → 完整对局 → 正常终局 → 登录查看
回放），管理员清理另一弃局后其玩家能开下一局、其他房间不受影响。

本机无 WSL：云端布局为本地模拟目录，不声称真实 Linux 云端已测；未部署、
不触碰生产。端口使用工单 27 独占的 29300 起端口段。
"""

from __future__ import annotations

import asyncio
import atexit
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

import websockets

from server.protocol import PROTOCOL_VERSION

REPO_ROOT = Path(__file__).resolve().parents[1]
# 与 scripts/deploy-cloud.sh 第 2 步的打包清单一致；client/dist 缺失时按同一命令现构建。
_PACKAGE_CONTENTS = ("server", "blood_bound", "client/dist", "scripts/bloodkill.service")
_PACKAGE_HOME = tempfile.TemporaryDirectory(prefix="bk27-package-")
atexit.register(_PACKAGE_HOME.cleanup)
_PACKAGES: list[Path] = []


def _ensure_client_dist() -> None:
    """部署包含 client/dist；缺失时用部署脚本同一条命令构建（结果留在工作树供复用）。"""
    if (REPO_ROOT / "client" / "dist" / "index.html").is_file():
        return
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("构建部署包需要 npm 构建 client/dist；请先安装 Node.js 并运行 npm ci --prefix client。")
    subprocess.run([npm, "run", "build", "--prefix", "client", "--silent"],
                   cwd=str(REPO_ROOT), check=True, timeout=300)


def build_deploy_package() -> Path:
    """与 deploy-cloud.sh 第 1–2 步同一产线：构建前端并打包运行时文件。"""
    _ensure_client_dist()
    tarball = Path(_PACKAGE_HOME.name) / f"bloodkill-deploy-{len(_PACKAGES)}.tar.gz"
    subprocess.run(["tar", "-czf", str(tarball), *_PACKAGE_CONTENTS],
                   cwd=str(REPO_ROOT), check=True, timeout=300)
    _PACKAGES.append(tarball)
    return tarball


def pick_port(start: int = 29300, span: int = 60) -> int:
    """工单 27 独占端口段：29300 起顺序取一个当前可绑定的回环端口。"""
    for candidate in range(start, start + span):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return candidate
    raise RuntimeError("29300 起的端口段全部被占用，无法启动隔离服务")


def deployment_environment() -> dict:
    """部署进程环境：不设 BLOOD_BOUND_SAVES_DIR，存档按 ./saves 相对部署根解析（云端 systemd WorkingDirectory 行为）。"""
    environment = {key: value for key, value in os.environ.items()
                   if key != "BLOOD_BOUND_SAVES_DIR"}
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


class DeploymentLayoutTests(unittest.TestCase):
    """每个测试独立解包一份部署目录，并从那里启动服务与 CLI（真实子进程）。"""

    def setUp(self):
        holder = tempfile.TemporaryDirectory(prefix="bk27-opt-")
        self.addCleanup(holder.cleanup)
        self.deploy_root = Path(holder.name) / "bloodkill"
        self.deploy_root.mkdir(parents=True)
        self.extract_package(build_deploy_package())
        self.port = pick_port()
        self.start_deployed_server()
        self.addCleanup(self.stop_deployed_server)

    # ---- 部署目录与真实服务 ------------------------------------------------

    def extract_package(self, tarball: Path) -> None:
        """与 deploy-cloud.sh 第 4 步同序：解包覆盖部署根（saves/ 不在打包清单，不受影响）。"""
        subprocess.run(["tar", "-xzf", str(tarball), "-C", str(self.deploy_root)],
                       check=True, timeout=120)

    def start_deployed_server(self):
        """从部署根启动真实 uvicorn；重启复用同一端口（云端固定 8000 的行为）。"""
        self.log_path = self.deploy_root / "server.log"
        self.log = self.log_path.open("ab")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.app:app",
             "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=str(self.deploy_root), env=deployment_environment(),
            stdout=self.log, stderr=self.log,
        )
        for _ in range(200):
            try:
                self.request("/health")
                return
            except OSError:
                time.sleep(.05)
        self.fail("部署目录中的服务未启动（详见部署根 server.log）")

    def stop_deployed_server(self):
        if self.process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            else:
                self.process.terminate()
            self.process.wait(timeout=10)
        self.log.close()

    # ---- HTTP / WS 辅助 ----------------------------------------------------

    def request(self, path, data=None, cookie=None):
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        outgoing = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers,
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            response = opener.open(outgoing)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response), response.headers

    def signup(self, name, password="123456"):
        status, body, headers = self.request("/api/auth/register", {
            "username": name, "password": password, "confirmPassword": password})
        self.assertEqual(status, 201, body)
        return body["account"], headers["Set-Cookie"].split(";", 1)[0]

    def login(self, name, password):
        return self.request("/api/auth/login", {"username": name, "password": password})

    def create_room(self, cookie):
        status, room, _ = self.request("/api/rooms", {}, cookie)
        self.assertEqual(status, 200, room)
        return room["code"], room["gameId"]

    def connect(self, code, cookie):
        return websockets.connect(f"ws://127.0.0.1:{self.port}/ws/{code}",
                                  additional_headers={"Cookie": cookie}, proxy=None)

    async def hello(self, socket, **fields):
        await socket.send(json.dumps({"type": "hello", "mode": "player",
                                      "protocolVersion": PROTOCOL_VERSION, **fields}))
        return json.loads(await asyncio.wait_for(socket.recv(), 3))

    async def seat_of(self, code, cookie):
        async with self.connect(code, cookie) as socket:
            return await self.hello(socket)

    # ---- 管理命令行（部署根目录运行） ---------------------------------------

    def run_cli(self, *arguments, input=None, timeout=120):
        """真实 CLI 子进程；默认 ./saves 相对部署根解析，与文档本地/云端用法一致。"""
        command = [sys.executable, "-m", "server.admin", *map(str, arguments)]
        return subprocess.run(command, cwd=str(self.deploy_root),
                              env=deployment_environment(),
                              capture_output=True, text=True, encoding="utf-8",
                              timeout=timeout, input=input)

    def backup_path_from(self, output: str) -> Path:
        self.assertIn("备份已写入：", output)
        return Path(output.split("备份已写入：", 1)[1].splitlines()[0].strip())

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    # ---- V21.01 打包/实际命令 ------------------------------------------------

    def test_v21_01_admin_commands_run_from_deployment_package_directory(self):
        """V21.01：从真实部署内容的独立目录启动临时服务，按文档运行查看、
        密码重置和单房清理，校验互动输出、备份可读取及非默认配置。"""
        from blood_bound import load_game

        # 部署包内容与云端布局：运行时代码、引擎包、静态站点与 unit 都在部署根。
        for relative in ("server/admin.py", "server/app.py", "server/requirements.txt",
                         "blood_bound/__init__.py", "client/dist/index.html",
                         "scripts/bloodkill.service"):
            self.assertTrue((self.deploy_root / relative).is_file(), f"部署包缺少 {relative}")
        saves = self.deploy_root / "saves"
        self.assertTrue((saves / "accounts" / "accounts.sqlite3").is_file(),
                        "不设环境变量时存档必须默认落在部署根 ./saves")

        host_account, host_cookie = self.signup("交付房主")
        code, game_id = self.create_room(host_cookie)
        guest_account, guest_cookie = self.signup("交付玩家")
        seated = asyncio.run(self.seat_of(code, guest_cookie))
        self.assertEqual(seated["roomStatus"], "waiting")
        self.signup("交付路人")

        # users：默认配置（./saves 相对部署根）。
        users = self.run_cli("users")
        self.assertEqual(users.returncode, 0, users.stderr + users.stdout)
        self.assertIn("共 3 个账号", users.stdout)
        host_lines = [line for line in users.stdout.splitlines() if "交付房主" in line]
        self.assertTrue(host_lines and code in host_lines[0], "users 必须显示房主的当前占用房号")
        self.assertIn(host_account["accountId"], users.stdout)
        self.assertTrue(any("（未占用）" in line for line in users.stdout.splitlines()
                            if "交付路人" in line), "未占用账号必须如实标注")

        # rooms：非默认配置（显式 --saves-dir 与 --port，端口读 installation.json 记录值）。
        installation = json.loads(
            (saves / "admin" / "installation.json").read_text(encoding="utf-8"))
        rooms = self.run_cli("rooms", "--saves-dir", str(saves),
                             "--port", str(installation["adminPort"]))
        self.assertEqual(rooms.returncode, 0, rooms.stderr + rooms.stdout)
        room_line = [line for line in rooms.stdout.splitlines() if code in line][0]
        self.assertIn("等待中", room_line)
        self.assertIn("交付房主", room_line)
        self.assertIn(game_id, rooms.stdout, "rooms 输出必须含对局引用")

        # reset-password：互动隐藏输入（stdin 管道等价安全），中文成功说明。
        new_password = "交付新密码9"
        reset = self.run_cli("reset-password", "交付玩家",
                             input=f"{new_password}\n{new_password}\n")
        self.assertEqual(reset.returncode, 0, reset.stderr + reset.stdout)
        self.assertIn("请输入新密码（6–12 个字符，直接回车取消）：", reset.stdout,
                      "互动输入提示必须出现")
        self.assertIn("请再次输入新密码确认（直接回车取消）：", reset.stdout)
        self.assertIn("已重置账号「交付玩家」的密码；该账号全部登录已撤销（所有设备）。", reset.stdout)
        self.assertIn("座位与房主归属保持不变", reset.stdout)
        self.assertNotIn("123456", reset.stdout, "输出不得出现任何密码")
        self.assertNotIn(new_password, reset.stdout, "输出不得出现任何密码")
        self.assertEqual(self.login("交付玩家", "123456")[0], 401, "旧密码必须失效")
        self.assertEqual(self.login("交付玩家", new_password)[0], 200, "新密码必须可用")

        # close-room：预览 → 再次输入同一房号确认 → 备份并关闭。
        close = self.run_cli("close-room", code, input=f"{code}\n")
        self.assertEqual(close.returncode, 0, close.stderr + close.stdout)
        self.assertIn("将要关闭的房间：", close.stdout)
        self.assertIn(f"再次输入房号 {code} 确认关闭（其他输入或直接回车取消）：", close.stdout,
                      "确认提示必须出现")
        self.assertIn(f"已关闭房间 {code}。", close.stdout)
        self.assertIn("受影响玩家 2 人：", close.stdout)
        self.assertIn("备份已写入：", close.stdout)
        backup_path = self.backup_path_from(close.stdout)
        self.assertTrue(backup_path.is_absolute())
        self.assertEqual(backup_path.parent.parent, saves,
                         "备份必须落在部署存档目录的 admin-backup 下")
        for name in ("game.json.gz", "meta.json", "closure.json"):
            self.assertTrue((backup_path / name).is_file(), f"备份缺少 {name}")
        closure = json.loads((backup_path / "closure.json").read_text(encoding="utf-8"))
        self.assertEqual(closure["code"], code)
        self.assertEqual(closure["gameId"], game_id)
        self.assertFalse(closure.get("result"), "管理关闭不得伪造胜负结果")
        engine = load_game(backup_path / "game.json.gz")
        self.assertNotEqual(engine.state.status, "ended", "备份存档可读取且不是正常终局")

        # 清理只改变目标房间：占用释放，房主能开下一局。
        self.assertEqual(self.request(f"/api/rooms/{code}")[0], 404)
        self.assertIsNone(self.request("/api/account/room", cookie=host_cookie)[1]["room"])
        users_after = self.run_cli("users")
        self.assertEqual(users_after.returncode, 0, users_after.stderr + users_after.stdout)
        for name in ("交付房主", "交付玩家"):
            self.assertTrue(all("（未占用）" in line for line in users_after.stdout.splitlines()
                                if name in line), f"{name} 的占用必须已释放")
        status, next_room, _ = self.request("/api/rooms", {}, host_cookie)
        self.assertEqual(status, 200, next_room)
        self.assertNotEqual(next_room["code"], code, "被清理房的房主必须能开新房间")

    # ---- V21.02 更新/重启 ----------------------------------------------------

    def test_v21_02_redeploy_preserves_data_and_never_resurrects(self):
        """V21.02：更新前保存有效/已撤销登录、正常/关闭房间和备份；重新打包、
        解包覆盖并以新进程重启后分别验证仍有效、仍撤销、不复活、不丢数据。"""
        saves = self.deploy_root / "saves"

        # 更新前状态。
        _, kept_cookie = self.signup("留存玩家")
        _, _, headers = self.login("留存玩家", "123456")
        revoked_cookie = headers["Set-Cookie"].split(";", 1)[0]
        logout_status, _, _ = self.request("/api/auth/logout", {}, revoked_cookie)
        self.assertEqual(logout_status, 200, "第二台设备登录后退出，制造已撤销登录")

        _, host_cookie = self.signup("留存房主")
        code, _ = self.create_room(host_cookie)
        _, member_cookie = self.signup("留存成员")
        member_seated = asyncio.run(self.seat_of(code, member_cookie))
        member_player_id = member_seated["yourPlayerId"]
        self.assertTrue(member_player_id)

        _, closed_cookie = self.signup("留存弃局房主")
        closed_code, _ = self.create_room(closed_cookie)
        _, quitter_cookie = self.signup("留存弃局玩家")
        asyncio.run(self.seat_of(closed_code, quitter_cookie))
        close = self.run_cli("close-room", closed_code, input=f"{closed_code}\n")
        self.assertEqual(close.returncode, 0, close.stderr + close.stdout)
        backup_path = self.backup_path_from(close.stdout)

        protected = [saves / "accounts" / "accounts.sqlite3",
                     saves / "admin" / "admin-token", *sorted(backup_path.iterdir())]
        protected_before = {str(path.relative_to(saves)): self.digest(path) for path in protected}
        installation_before = json.loads(
            (saves / "admin" / "installation.json").read_text(encoding="utf-8"))
        inventory_before = {str(path.relative_to(saves))
                            for path in saves.rglob("*") if path.is_file()}

        # 模拟更新：重新打包 → 解包覆盖部署根 → 新进程重启（systemctl restart 对应）。
        self.extract_package(build_deploy_package())
        self.stop_deployed_server()
        self.start_deployed_server()

        # 会话：有效仍有效，已撤销仍撤销。
        self.assertEqual(self.request("/api/auth/session", cookie=kept_cookie)[0], 200,
                         "未过期的登录在更新后必须仍然有效")
        self.assertEqual(self.request("/api/auth/session", cookie=revoked_cookie)[0], 401,
                         "更新不得复活已撤销的登录")

        # 房间：正常房恢复（座位与房主归属不变），已关闭房不复活。
        status, room, _ = self.request(f"/api/rooms/{code}")
        self.assertEqual((status, room["status"], room["playerCount"]), (200, "waiting", 2))
        occupied = self.request("/api/account/room", cookie=host_cookie)[1]["room"]
        self.assertEqual((occupied["code"], occupied["status"]), (code, "waiting"))
        host_resumed = asyncio.run(self.seat_of(code, host_cookie))
        self.assertTrue(host_resumed["isHost"], "房主归属不得因更新丢失")
        member_resumed = asyncio.run(self.seat_of(code, member_cookie))
        self.assertEqual(member_resumed["yourPlayerId"], member_player_id,
                         "既有座位归属不得因更新丢失")
        self.assertEqual(self.request(f"/api/rooms/{closed_code}")[0], 404,
                          "已管理关闭的房间不得复活")
        self.assertIsNone(self.request("/api/account/room", cookie=closed_cookie)[1]["room"])
        self.assertIsNone(self.request("/api/account/room", cookie=quitter_cookie)[1]["room"])

        # 数据与凭证：账号库、管理凭证、备份字节不变；重复关闭仍明确报告。
        for relative, before in protected_before.items():
            self.assertEqual(self.digest(saves / relative), before,
                             f"更新不得改动 {relative}")
        installation_after = json.loads(
            (saves / "admin" / "installation.json").read_text(encoding="utf-8"))
        self.assertEqual(installation_after["installationId"], installation_before["installationId"],
                         "同目录重启必须复用安装标识")
        inventory_after = {str(path.relative_to(saves))
                           for path in saves.rglob("*") if path.is_file()}
        self.assertTrue(inventory_before <= inventory_after, "更新不得丢失存档目录中的既有文件")
        repeat = self.run_cli("close-room", closed_code, input=f"{closed_code}\n")
        self.assertEqual(repeat.returncode, 1, "重复处理必须非零退出")
        self.assertIn("被管理关闭", repeat.stderr)
        users = self.run_cli("users")
        self.assertEqual(users.returncode, 0, users.stderr + users.stdout)
        for name in ("留存玩家", "留存房主", "留存成员", "留存弃局房主", "留存弃局玩家"):
            self.assertIn(name, users.stdout, f"更新不得丢失账号 {name}")

    # ---- V21.03 用户闭环 ----------------------------------------------------

    def test_v21_03_user_loop_replay_and_admin_close_scopes_to_target_room(self):
        """V21.03：账号从注册进房到对局结束并查看回放；管理员清理另一弃局后
        其玩家能开下一局，其他房间仍可继续。"""
        from scripts.account_client import AccountClient
        from scripts.release_smoke import validate_replay, websocket_smoke

        base = f"http://127.0.0.1:{self.port}"
        # 完整用户闭环：注册 → 建房 → 完整对局至正常终局 → 参与账号登录查看公开回放。
        sessions = [AccountClient(base).register_test_account() for _ in range(7)]
        status, ended_room = sessions[0].request("/api/rooms", "POST", {})
        self.assertEqual(status, 200, ended_room)
        final = asyncio.run(websocket_smoke(base, ended_room, sessions))
        self.assertEqual(final["status"], "ended")
        replay_status, replay = sessions[1].request(f"/api/rooms/{ended_room['code']}/replay")
        self.assertEqual(replay_status, 200)
        validate_replay(replay, final)

        # 弃局房与对照房。
        _, abandon_cookie = self.signup("闭环弃局房主")
        abandon_code, _ = self.create_room(abandon_cookie)
        _, quitter_cookie = self.signup("闭环弃局玩家")
        abandon_seated = asyncio.run(self.seat_of(abandon_code, quitter_cookie))
        self.assertEqual(abandon_seated["roomStatus"], "waiting")
        _, control_cookie = self.signup("闭环对照房主")
        control_code, _ = self.create_room(control_cookie)
        _, control_member_cookie = self.signup("闭环对照玩家")
        asyncio.run(self.seat_of(control_code, control_member_cookie))

        # 管理员清理弃局（真实 CLI，stdin 传入同一房号确认）。
        close = self.run_cli("close-room", abandon_code, input=f"{abandon_code}\n")
        self.assertEqual(close.returncode, 0, close.stderr + close.stdout)
        self.assertIn(f"已关闭房间 {abandon_code}。", close.stdout)
        self.assertIn("受影响玩家 2 人：", close.stdout)
        self.assertIn("闭环弃局房主", close.stdout)
        self.assertIn("闭环弃局玩家", close.stdout)

        # 被清理房的玩家能开下一局，原房主也能加入新房间。
        self.assertIsNone(self.request("/api/account/room", cookie=abandon_cookie)[1]["room"])
        self.assertIsNone(self.request("/api/account/room", cookie=quitter_cookie)[1]["room"])
        status, next_room, _ = self.request("/api/rooms", {}, quitter_cookie)
        self.assertEqual(status, 200, next_room)
        joined = asyncio.run(self.seat_of(next_room["code"], abandon_cookie))
        self.assertEqual(joined["roomStatus"], "waiting")
        self.assertTrue(joined["yourPlayerId"], "释放占用后必须能进新房间入座")

        # 其他房间不受影响：对照房照常等待、可锁定；终局回放照常可读。
        status, room, _ = self.request(f"/api/rooms/{control_code}")
        self.assertEqual((status, room["status"], room["playerCount"]), (200, "waiting", 2))

        async def lock_control():
            async with self.connect(control_code, control_cookie) as socket:
                await self.hello(socket)
                await socket.send(json.dumps({"type": "host", "action": "lock"}))
                while True:
                    message = json.loads(await asyncio.wait_for(socket.recv(), 5))
                    if message.get("type") == "error":
                        raise AssertionError(message)
                    if message.get("type") == "state" and message.get("locked"):
                        return
        asyncio.run(lock_control())
        again_status, replay_again = sessions[2].request(f"/api/rooms/{ended_room['code']}/replay")
        self.assertEqual(again_status, 200, "管理员清理不得影响其他房间的回放")
        validate_replay(replay_again, final)

        # rooms 视图与占用一致：弃局房不再列出，对照房仍在。
        rooms = self.run_cli("rooms")
        self.assertEqual(rooms.returncode, 0, rooms.stderr + rooms.stdout)
        self.assertNotIn(abandon_code, rooms.stdout, "被清理房不得再出现在 rooms 视图")
        self.assertIn(control_code, rooms.stdout, "对照房必须仍在 rooms 视图")


if __name__ == "__main__":
    unittest.main()
