"""Ticket 19: the admin CLI inspects accounts and rooms via the running service.

Real uvicorn process + real CLI subprocess (``python -m server.admin``): the CLI
asks the running service over a loopback-only admin endpoint instead of opening
the saves itself. Output is Simplified Chinese and carries room codes, stable
account references, occupancy and online status, never credential material.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import websockets

from tests import test_accounts as account_tests
from tests import test_account_sessions as account_sessions

REPO_ROOT = Path(__file__).resolve().parents[1]
_CLI_POOL = ThreadPoolExecutor(max_workers=1)


class AdminCLITests(unittest.TestCase):
    setUp = account_tests.RegistrationHTTPTests.setUp
    start_server = account_tests.RegistrationHTTPTests.start_server
    stop_server = account_tests.RegistrationHTTPTests.stop_server
    request = account_tests.RegistrationHTTPTests.request
    register = account_tests.RegistrationHTTPTests.register

    def signup(self, name, password="123456"):
        status, body, headers = self.register(name, password)
        self.assertEqual(status, 201)
        return body["account"], headers["Set-Cookie"].split(";", 1)[0]

    def login(self, name, password="123456"):
        status, body, headers = self.request("/api/auth/login", {"username": name, "password": password})
        self.assertEqual(status, 200, body)
        return body["account"], headers["Set-Cookie"].split(";", 1)[0]

    # 借用工单 14 的真实开局场景（同一 HTTP/WS helper 形状）：把匕首交到目标手里，
    # 使其在重置前持有原本合法的动作与私有投影。适配点：本类的 create_room 额外
    # 返回 gameId，临时降维成 sessions 场景期望的单 code 形状。
    async def _prepare_playing_room_with_dagger_on(self, host_cookie, target_cookie, extra_cookies):
        original = account_sessions.AccountSessionHTTPTests._prepare_playing_room_with_dagger_on
        create_room = self.create_room
        self.create_room = lambda cookie: create_room(cookie)[0]
        try:
            return await original(self, host_cookie, target_cookie, extra_cookies)
        finally:
            self.create_room = create_room

    def create_room(self, cookie):
        status, room, _ = self.request("/api/rooms", {}, cookie)
        self.assertEqual(status, 200)
        return room["code"], room["gameId"]

    def connect(self, code, cookie):
        return websockets.connect(f"ws://127.0.0.1:{self.port}/ws/{code}", additional_headers={"Cookie": cookie}, proxy=None)

    async def hello(self, socket, **fields):
        await socket.send(json.dumps({"type": "hello", "mode": "player", "protocolVersion": "4", **fields}))
        return json.loads(await asyncio.wait_for(socket.recv(), 3))

    async def state_of(self, code, cookie, **fields):
        async with self.connect(code, cookie) as socket:
            return await self.hello(socket, **fields)

    async def fill_to(self, code, host_cookie, total, prefix):
        current = self.request(f"/api/rooms/{code}")[1]["playerCount"]
        for index in range(total - current):
            _, cookie = self.signup(f"{prefix}{index}")
            await self.state_of(code, cookie)
        async with self.connect(code, host_cookie) as socket:
            await self.hello(socket)
            await socket.send(json.dumps({"type": "host", "action": "start"}))
            while True:
                message = json.loads(await asyncio.wait_for(socket.recv(), 5))
                if message.get("type") == "state":
                    return message
                if message.get("type") == "error":
                    raise AssertionError(message)

    # ---- admin tooling helpers -------------------------------------------

    def run_cli_in(self, saves_dir, *arguments, timeout=120, environment_extra=None, input=None):
        """Run the real CLI subprocess; saves_dir=None 让 CLI 走环境变量默认解析。"""
        command = [sys.executable, "-m", "server.admin", *map(str, arguments)]
        if saves_dir is not None:
            command += ["--saves-dir", str(saves_dir)]
        environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                       **(environment_extra or {})}
        return subprocess.run(command, cwd=str(REPO_ROOT), env=environment,
                              capture_output=True, text=True, encoding="utf-8",
                              timeout=timeout, input=input)

    def run_cli(self, *arguments, timeout=120, input=None):
        return self.run_cli_in(self.tmp.name, *arguments, timeout=timeout, input=input)

    async def run_cli_online(self, *arguments, input=None):
        """Run the CLI while this coroutine's event loop keeps serving WS pings."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _CLI_POOL, lambda: self.run_cli(*arguments, input=input))

    def lines_with(self, output, needle):
        return [line for line in output.splitlines() if needle in line]

    # ---- 管理端口直连辅助 --------------------------------------------------

    def admin_port(self):
        installation = json.loads(
            (Path(self.tmp.name) / "admin" / "installation.json").read_text(encoding="utf-8"))
        return installation["adminPort"]

    def admin_token(self):
        return (Path(self.tmp.name) / "admin" / "admin-token").read_text(encoding="utf-8").strip()

    def admin_http(self, path, token=None, cookie=None, extra_headers=None):
        import urllib.error
        import urllib.request
        headers = dict(extra_headers or {})
        if token is not None:
            headers["X-Admin-Token"] = token
        if cookie is not None:
            headers["Cookie"] = cookie
        request = urllib.request.Request(f"http://127.0.0.1:{self.admin_port()}{path}", headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            response = opener.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def admin_post(self, path, payload, token=None, cookie=None, extra_headers=None):
        """对管理端口发真实 POST（重置密码的写路径）；密码只在请求体中。"""
        import urllib.error
        import urllib.request
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if token is not None:
            headers["X-Admin-Token"] = token
        if cookie is not None:
            headers["Cookie"] = cookie
        headers.update(extra_headers or {})
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.admin_port()}{path}",
            data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            response = opener.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def public_http(self, path, headers=None):
        import urllib.error
        import urllib.request
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers or {})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            response = opener.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_v13_01_real_cli_reports_accounts_rooms_occupancy_and_online(self):
        """V13.01: real processes on both ends; the CLI reflects rooms, hosts,
        occupancy and online status exactly as the running service holds them."""
        from scripts.account_client import AccountClient
        from scripts.release_smoke import websocket_smoke

        host_account, host_cookie = self.signup("管理房主")
        code_waiting, game_waiting = self.create_room(host_cookie)
        guest_account, guest_cookie = self.signup("管理玩家")
        bystander_account, _ = self.signup("管理路人")
        lock_host_account, lock_cookie = self.signup("锁定房主")
        code_locked, _ = self.create_room(lock_cookie)

        async def lock_room():
            async with self.connect(code_locked, lock_cookie) as socket:
                await self.hello(socket)
                await socket.send(json.dumps({"type": "host", "action": "lock"}))
                while True:
                    message = json.loads(await asyncio.wait_for(socket.recv(), 3))
                    if message.get("type") == "state" and message["locked"]:
                        return
        asyncio.run(lock_room())

        play_host_account, play_cookie = self.signup("进行房主")
        code_playing, _ = self.create_room(play_cookie)
        started = asyncio.run(self.fill_to(code_playing, play_cookie, 6, "进行补位"))
        self.assertEqual(started["roomStatus"], "playing")

        base = f"http://127.0.0.1:{self.port}"
        ended_sessions = [AccountClient(base).register_test_account() for _ in range(7)]
        status, ended_room = ended_sessions[0].request("/api/rooms", "POST", {})
        self.assertEqual(status, 200)
        code_ended = ended_room["code"]
        final = asyncio.run(websocket_smoke(base, ended_room, ended_sessions))
        self.assertEqual(final["status"], "ended")

        async def inspect_while_guest_online():
            async with self.connect(code_waiting, guest_cookie) as socket:
                await self.hello(socket)
                users = await self.run_cli_online("users")
                rooms = await self.run_cli_online("rooms")
                return users, rooms
        users, rooms = asyncio.run(inspect_while_guest_online())

        # ---- users：账号、稳定引用、当前占用 ----
        self.assertEqual(users.returncode, 0, users.stderr + users.stdout)
        for account in (host_account, guest_account, bystander_account,
                        lock_host_account, play_host_account):
            with self.subTest(username=account["username"]):
                self.assertTrue(self.lines_with(users.stdout, account["username"]),
                                f"users 输出必须列出 {account['username']}")
                self.assertTrue(self.lines_with(users.stdout, account["accountId"]),
                                f"users 输出必须含 {account['username']} 的稳定账号引用")
        for account, code in ((host_account, code_waiting), (guest_account, code_waiting),
                              (lock_host_account, code_locked), (play_host_account, code_playing)):
            with self.subTest(occupancy=account["username"]):
                line = self.lines_with(users.stdout, account["username"])
                self.assertTrue(any(code in entry for entry in line),
                                f"{account['username']} 的当前房间占用必须显示 {code}")
        bystander_lines = self.lines_with(users.stdout, bystander_account["username"])
        self.assertTrue(bystander_lines)
        self.assertFalse(any(code in line for code in
                             (code_waiting, code_locked, code_playing, code_ended)
                             for line in bystander_lines), "未占用账号不得显示房间号")
        # ended 房不算当前占用：终局测试账号不得挂着已结束房号。
        for session in ended_sessions:
            name = session.account["username"]
            self.assertFalse(any(code_ended in line for line in self.lines_with(users.stdout, name)),
                             "已结束房间不属于当前占用")

        # ---- rooms：房号、对局引用、状态、房主、玩家与在线 ----
        self.assertEqual(rooms.returncode, 0, rooms.stderr + rooms.stdout)
        for code in (code_waiting, code_locked, code_playing, code_ended):
            self.assertTrue(self.lines_with(rooms.stdout, code), f"rooms 输出必须列出房间 {code}")
        waiting_line = self.lines_with(rooms.stdout, code_waiting)[0]
        self.assertIn("等待中", waiting_line)
        self.assertIn("未锁定", waiting_line)
        self.assertIn("管理房主", waiting_line)
        self.assertIn(game_waiting, rooms.stdout, "rooms 输出必须含对局引用")
        locked_line = self.lines_with(rooms.stdout, code_locked)[0]
        self.assertIn("等待中", locked_line)
        self.assertIn("已锁定", locked_line)
        self.assertIn("锁定房主", locked_line)
        playing_line = self.lines_with(rooms.stdout, code_playing)[0]
        self.assertIn("进行中", playing_line)
        self.assertIn("进行房主", playing_line)
        ended_line = self.lines_with(rooms.stdout, code_ended)[0]
        self.assertIn("已结束", ended_line)
        # 在线情况：保持 WS 的玩家在线，其余离线（括号标注精确到玩家）。
        self.assertIn("管理玩家（在线）", rooms.stdout, "保持连接的玩家必须显示在线")
        self.assertNotIn("管理玩家（离线）", rooms.stdout)
        self.assertIn("管理房主（离线）", rooms.stdout, "无连接的玩家必须显示离线")
        self.assertNotIn("管理房主（在线）", rooms.stdout)

    def test_v13_02_only_local_admin_credential_grants_access(self):
        """V13.02: no token, a wrong token, account/host session cookies and the
        public app (even with forged forwarding headers) all fail to query."""
        _, host_cookie = self.signup("权限房主")
        code, _ = self.create_room(host_cookie)
        _, guest_cookie = self.signup("权限玩家")
        asyncio.run(self.state_of(code, guest_cookie))
        token = self.admin_token()
        self.assertTrue(token)

        # 管理端口：无凭证 / 错误凭证 / 普通账号会话 / 房主会话 / 伪造转发头 → 全部 401。
        self.assertEqual(self.admin_http("/admin/users")[0], 401)
        self.assertEqual(self.admin_http("/admin/users", token="wrong-admin-token")[0], 401)
        self.assertEqual(self.admin_http("/admin/users", cookie=guest_cookie)[0], 401,
                         "普通账号登录会话不能取得管理权限")
        self.assertEqual(self.admin_http("/admin/users", cookie=host_cookie)[0], 401,
                         "房主身份不能取得管理权限")
        forged = {"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1", "Forwarded": "for=127.0.0.1"}
        self.assertEqual(self.admin_http("/admin/users", token="wrong-admin-token", extra_headers=forged)[0], 401,
                         "伪造转发来源信息不能放开管理权限")
        # 对照：本机 + 正确独立管理凭证才成功。
        status, body = self.admin_http("/admin/users", token=token)
        self.assertEqual(status, 200)
        self.assertEqual({account["username"] for account in body["accounts"]},
                         {"权限房主", "权限玩家"})
        self.assertTrue(all(set(account) == {"username", "accountId", "roomCode"}
                            for account in body["accounts"]),
                        "users 只能返回允许字段，不得携带密码摘要或会话凭证")

        # 公网应用没有任何管理路由：伪造本机来源或携带正确管理凭证也不能从公网查询。
        self.assertEqual(self.public_http("/admin/users", dict(forged))[0], 404)
        self.assertEqual(self.public_http("/admin/users", {**forged, "X-Admin-Token": token})[0], 404,
                         "公网入口不得暴露管理查询，管理凭证只对本机回环监听有效")

        # CLI 层错误凭证：运行中篡改凭证文件，服务按启动时凭证校验 → 401 中文报错。
        token_path = Path(self.tmp.name) / "admin" / "admin-token"
        original = token_path.read_text(encoding="utf-8")
        token_path.write_text("tampered-token\n", encoding="utf-8")
        tampered = self.run_cli("users")
        self.assertNotEqual(tampered.returncode, 0)
        self.assertIn("管理凭证", tampered.stderr)
        self.assertNotIn(token, tampered.stdout + tampered.stderr,
                         "失败输出不得泄露真实管理凭证")
        # CLI 层无凭证：凭证文件缺失 → 中文报错、非零退出。
        token_path.unlink()
        missing = self.run_cli("rooms")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("管理凭证", missing.stderr)
        self.assertIn("admin-token", missing.stderr)
        token_path.write_text(original, encoding="utf-8")
        # 还原后 CLI 恢复可用（服务进程仍持启动时凭证）。
        recovered = self.run_cli("rooms")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)

    def start_second_server(self):
        """An independent real uvicorn instance on its own saves dir and port."""
        import socket
        import tempfile
        import time as time_module
        import urllib.error
        import urllib.request
        second = tempfile.TemporaryDirectory()
        self.addCleanup(second.cleanup)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            second_port = listener.getsockname()[1]
        log = (Path(second.name) / "server.log").open("ab")
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1",
             "--port", str(second_port)],
            env={**os.environ, "BLOOD_BOUND_SAVES_DIR": second.name},
            stdout=log, stderr=log,
        )

        def cleanup():
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                else:
                    process.terminate()
                process.wait(timeout=10)
            log.close()
        self.addCleanup(cleanup)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(100):
            try:
                with opener.open(f"http://127.0.0.1:{second_port}/health", timeout=2):
                    return second.name, second_port
            except (OSError, urllib.error.URLError):
                time_module.sleep(.05)
        self.fail("第二实例未启动")

    def test_v13_03_port_and_directory_mismatches_fail_closed_in_chinese(self):
        """V13.03: fresh dir, stopped service, and a foreign instance's port each
        fail with Chinese feedback and a non-zero status; the other instance
        keeps working, and env-based default resolution matches the service."""
        import tempfile
        # (a) 服务从未在该目录启动：管理配置缺失，明确中文报错。
        fresh = tempfile.TemporaryDirectory()
        self.addCleanup(fresh.cleanup)
        never = self.run_cli_in(fresh.name, "users")
        self.assertNotEqual(never.returncode, 0)
        self.assertIn("管理配置", never.stderr)
        self.assertIn(str(fresh.name), never.stderr, "报错应指明所查存档目录")

        # 基线：主实例在跑；环境变量方式的默认存档解析与服务一致（不带 --saves-dir）。
        _, host_cookie = self.signup("主实例房主")
        self.create_room(host_cookie)
        via_env = self.run_cli_in(None, "users", environment_extra={"BLOOD_BOUND_SAVES_DIR": self.tmp.name})
        self.assertEqual(via_env.returncode, 0, via_env.stderr)
        self.assertIn("主实例房主", via_env.stdout)

        # 非默认显式端口（等于记录端口）也能查询。
        explicit = self.run_cli("rooms", "--port", self.admin_port())
        self.assertEqual(explicit.returncode, 0, explicit.stderr)

        # (b) 服务停止后：配置仍在但端口无人监听 → 中文连接失败、非零退出。
        self.stop_server()
        stopped = self.run_cli("rooms")
        self.assertNotEqual(stopped.returncode, 0)
        self.assertIn("无法连接", stopped.stderr)
        self.assertIn("127.0.0.1", stopped.stderr)
        self.assertIn("服务可能未运行", stopped.stderr)

        # (c) 另一实例在跑：A 目录的 CLI 被手工指到 B 的管理端口 → 拒绝且不误操作。
        second_dir, _ = self.start_second_server()
        second_installation = json.loads(
            (Path(second_dir) / "admin" / "installation.json").read_text(encoding="utf-8"))
        second_admin_port = second_installation["adminPort"]
        cross = self.run_cli("rooms", "--port", second_admin_port)
        self.assertNotEqual(cross.returncode, 0)
        self.assertIn("另一个服务实例", cross.stderr)
        self.assertIn(str(second_admin_port), cross.stderr)

        # 第二实例自身仍可用（不受上述拒绝影响）。
        second_ok = self.run_cli_in(second_dir, "rooms")
        self.assertEqual(second_ok.returncode, 0, second_ok.stderr)
        self.assertIn("当前没有房间", second_ok.stdout)

    def test_v13_04_inspection_is_read_only_and_leaks_no_credentials(self):
        """V13.04: a playing room's saves/accounts/admin files, REST state and
        countdown stay byte-identical across users/rooms; no credential appears."""
        import hashlib
        host_account, host_cookie = self.signup("只读房主", password="Zhen9Du51")
        members = [(account, cookie) for account, cookie in
                   (self.signup(f"只读成员{index}", password=f"Zhen9Du5{index + 2}") for index in range(5))]
        everyone = [(host_account, host_cookie), *members]
        code, _ = self.create_room(host_cookie)
        for _, cookie in members:
            asyncio.run(self.state_of(code, cookie))

        async def start_game():
            async with self.connect(code, host_cookie) as socket:
                await self.hello(socket)
                await socket.send(json.dumps({"type": "host", "action": "start"}))
                while True:
                    message = json.loads(await asyncio.wait_for(socket.recv(), 5))
                    if message.get("type") == "state" and message["roomStatus"] == "playing":
                        return message
        started = asyncio.run(start_game())
        self.assertEqual(started["roomStatus"], "playing")

        async def open_decision_window():
            """真实攻击一次，让对局进入干涉三段窗口（计时状态可被破坏的形态）。"""
            for _, cookie in everyone:
                async with self.connect(code, cookie) as socket:
                    state = await self.hello(socket)
                    attacks = [action for action in state["game"]["legalActions"]
                               if action["type"] == "attack"]
                    if not attacks:
                        continue
                    await socket.send(json.dumps({
                        "type": "command", "command": "attack",
                        "payload": {"targetPlayerId": attacks[0]["targetPlayerId"]},
                        "expectedRevision": state["game"]["revision"],
                    }))
                    while True:
                        message = json.loads(await asyncio.wait_for(socket.recv(), 5))
                        if message.get("type") == "state" and message["game"].get("pending"):
                            return message
            self.fail("未能推进到决策窗口")
        windowed = asyncio.run(open_decision_window())
        self.assertIsNotNone(windowed["game"].get("pending"))

        def directory_digest():
            digest = {}
            for path in sorted(Path(self.tmp.name).rglob("*")):
                # server.log 是测试 fixture 的进程日志（uvicorn 会追加 access log），
                # 不属于存档、账号库或管理配置的数据面。
                if path.is_file() and path.name != "server.log":
                    digest[path.relative_to(self.tmp.name).as_posix()] = \
                        hashlib.sha256(path.read_bytes()).hexdigest()
            return digest

        room_before = self.request(f"/api/rooms/{code}")[1]
        files_before = directory_digest()
        users = self.run_cli("users")
        rooms = self.run_cli("rooms")
        self.assertEqual(users.returncode, 0, users.stderr)
        self.assertEqual(rooms.returncode, 0, rooms.stderr)
        files_after = directory_digest()
        self.assertEqual(files_before, files_after,
                         "查看命令不得写入任何存档、账号库、事件日志或管理配置文件（含计时窗口）")
        self.assertEqual(room_before, self.request(f"/api/rooms/{code}")[1])

        token = self.admin_token()
        session_value = host_cookie.split("=", 1)[1]
        combined = users.stdout + users.stderr + rooms.stdout + rooms.stderr
        for secret, label in ((token, "管理凭证"),
                              *(("Zhen9Du5" + str(index + 1), "账号密码") for index in range(6)),
                              (session_value, "登录会话")):
            self.assertNotIn(secret, combined, f"输出不得包含{label}")
        # 查看后对局照常：房主重连仍拿到同一进行中状态与同一决策窗口。
        state = asyncio.run(self.state_of(code, host_cookie))
        self.assertEqual(state["roomStatus"], "playing")
        pending = state["game"].get("pending")
        self.assertIsNotNone(pending)
        self.assertEqual((pending["kind"], pending.get("stage")),
                         (windowed["game"]["pending"]["kind"], windowed["game"]["pending"].get("stage")),
                         "查看不得重置或改变决策窗口")

    # ---- 工单 20：管理工具重置密码并撤销全部登录 --------------------------

    def test_v14_01_real_cli_reset_revokes_all_logins_and_stops_established_connections(self):
        """V14.01: 目标账号两台设备登录（其一建立进行中对局连接）；真实 CLI 重置后
        全部登录与会话失效、已建立连接停止；新密码可登录，旧密码与旧会话不可用。"""
        _, host_cookie = self.signup("重置房主")
        _, device_a = self.signup("重置玩家")
        _, device_b = self.login("重置玩家")  # 第二台设备的独立登录
        extras = [self.signup(f"重置补位{i}") for i in range(4)]
        new_password = "New9Pass1"

        async def scenario():
            sockets, target_socket, host_socket, target_state, code = await self._prepare_playing_room_with_dagger_on(
                host_cookie, device_a, [cookie for _, cookie in extras])
            try:
                target_id = target_state["yourPlayerId"]
                reset = await self.run_cli_online(
                    "reset-password", "重置玩家", input=f"{new_password}\n{new_password}\n")
                self.assertEqual(reset.returncode, 0, reset.stderr + reset.stdout)
                self.assertIn("重置玩家", reset.stdout, "成功输出必须说明处理的用户名")
                self.assertIn("已撤销", reset.stdout, "成功输出必须说明撤销范围")
                self.assertIn("2", reset.stdout, "两台设备的登录会话都必须计入撤销")
                self.assertIn("1", reset.stdout, "一条已建立连接被停止")
                for secret in (new_password, "123456"):
                    self.assertNotIn(secret, reset.stdout + reset.stderr, "输出不得回显密码")

                # 已建立的游戏 WS 连接停止：收到撤销说明（中文）后被关闭。
                message = json.loads(await asyncio.wait_for(target_socket.recv(), 3))
                self.assertEqual(message["type"], "error")
                self.assertEqual(message["code"], "auth.session-revoked")
                self.assertIn("重新登录", message["message"], "撤销原因必须是简体中文")
                with self.assertRaises(websockets.ConnectionClosed):
                    await asyncio.wait_for(target_socket.recv(), 3)
                # 后续动作失败：连接已停止，原本合法的房主操作发不出去。
                with self.assertRaises(websockets.ConnectionClosed):
                    await target_socket.send(json.dumps({"type": "host", "action": "lock"}))

                # 对照组：房主连接照常操作；目标旧连接收不到这次广播（私有帧停止）。
                await host_socket.send(json.dumps({"type": "host", "action": "lock"}))
                while True:
                    message = json.loads(await asyncio.wait_for(host_socket.recv(), 5))
                    if message.get("type") == "state" and message.get("locked"):
                        break
                with self.assertRaises(websockets.ConnectionClosed):
                    await asyncio.wait_for(target_socket.recv(), 1)

                # 全部设备登录失效：设备 B 的独立 HTTP 会话同时 401。
                self.assertEqual(self.request("/api/auth/session", cookie=device_b)[0], 401)
                # 旧密码不可登录；新密码可登录。
                self.assertEqual(
                    self.request("/api/auth/login", {"username": "重置玩家", "password": "123456"})[0], 401)
                _, new_cookie = self.login("重置玩家", new_password)
                # 座位/占用保留：新登录恢复原座位，不新建重复玩家。
                room = self.request("/api/account/room", cookie=new_cookie)[1]["room"]
                self.assertEqual(room["code"], code, "重置不能释放座位占用")
                async with self.connect(code, new_cookie) as resumed_socket:
                    resumed = await self.hello(resumed_socket)
                self.assertEqual(resumed["yourPlayerId"], target_id, "重登必须恢复原座位")
                self.assertEqual(self.request(f"/api/rooms/{code}")[1]["playerCount"], 6)
                # 其他账号不受影响：补位玩家登录仍有效，房主仍能操作。
                self.assertEqual(self.request("/api/auth/session", cookie=extras[0][1])[0], 200)
                await host_socket.send(json.dumps({"type": "host", "action": "unlock"}))
                while True:
                    message = json.loads(await asyncio.wait_for(host_socket.recv(), 5))
                    if message.get("type") == "state" and not message.get("locked"):
                        break
            finally:
                await asyncio.gather(*(socket.close() for socket in sockets), return_exceptions=True)

        asyncio.run(scenario())

    def test_v14_02_interaction_boundaries_exit_status_and_no_side_effects(self):
        """V14.02: 5/6/12/13 字符、确认不一致、取消输入与未知账号逐项验证退出
        状态与无副作用；非法输入不修改任何账号。"""
        def login_status(password):
            return self.request("/api/auth/login", {"username": "边界玩家", "password": password})[0]

        self.signup("边界玩家")
        # 5 字符 → 中文报错后重试 → 合法 8 字符成功；密码随即生效。
        five_then_ok = self.run_cli("reset-password", "边界玩家",
                                    input="12345\nNew9Pass\nNew9Pass\n")
        self.assertEqual(five_then_ok.returncode, 0, five_then_ok.stderr + five_then_ok.stdout)
        self.assertIn("6–12", five_then_ok.stdout, "长度不符的中文提示")
        self.assertEqual(login_status("New9Pass"), 200)
        self.assertEqual(login_status("123456"), 401, "旧密码必须立即失效")

        # 12 字符上界成功；6 字符下界成功。
        twelve = self.run_cli("reset-password", "边界玩家", input="Twelve9Chars\nTwelve9Chars\n")
        self.assertEqual(twelve.returncode, 0, twelve.stderr + twelve.stdout)
        self.assertEqual(login_status("Twelve9Chars"), 200)
        six = self.run_cli("reset-password", "边界玩家", input="Six9Ch\nSix9Ch\n")
        self.assertEqual(six.returncode, 0, six.stderr + six.stdout)
        self.assertEqual(login_status("Six9Ch"), 200)

        # 13 字符 → 报错 → 空输入取消：非零退出、无副作用。
        thirteen_then_cancel = self.run_cli("reset-password", "边界玩家",
                                            input="Thirteen9Char\n\n")
        self.assertNotEqual(thirteen_then_cancel.returncode, 0)
        self.assertIn("6–12", thirteen_then_cancel.stdout)
        combined = thirteen_then_cancel.stdout + thirteen_then_cancel.stderr
        self.assertIn("已取消", combined)
        self.assertEqual(login_status("Six9Ch"), 200, "取消不得修改密码")

        # 确认不一致 → 报错 → 输入流结束（EOF）按取消：非零退出、无副作用。
        mismatch = self.run_cli("reset-password", "边界玩家", input="Six9C1\nSix9C2\n")
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn("不一致", mismatch.stdout)
        self.assertIn("已取消", mismatch.stdout + mismatch.stderr)
        self.assertEqual(login_status("Six9Ch"), 200, "确认不一致不得修改密码")

        # 无任何输入（stdin 立即 EOF）：按取消处理。
        immediate_eof = self.run_cli("reset-password", "边界玩家", input="")
        self.assertNotEqual(immediate_eof.returncode, 0)
        self.assertIn("已取消", immediate_eof.stdout + immediate_eof.stderr)
        self.assertEqual(login_status("Six9Ch"), 200)

        # 未知账号：明确中文报错、非零退出、不自动创建账号。
        unknown = self.run_cli("reset-password", "不存在的账号", input="New9Pass\nNew9Pass\n")
        self.assertNotEqual(unknown.returncode, 0)
        self.assertIn("不存在", unknown.stderr)
        self.assertIn("不存在的账号", unknown.stderr)
        users = self.run_cli("users")
        self.assertEqual(users.returncode, 0, users.stderr)
        self.assertNotIn("不存在的账号", users.stdout, "重置不得自动创建账号")

    def test_v14_03_reset_preserves_host_ownership_across_restart(self):
        """V14.03: 重置进行中房间的房主：座位/房主归属不变，重启后用新密码恢复
        原房原身份；其他账号的既有登录与座位不受影响、继续操作。"""
        _, host_cookie = self.signup("重启房主")
        _, guest_cookie = self.signup("重启玩家")
        code, _ = self.create_room(host_cookie)

        async def scenario():
            async with self.connect(code, host_cookie) as host_socket, \
                    self.connect(code, guest_cookie) as guest_socket:
                guest_state = await self.hello(guest_socket)
                await self.hello(host_socket)
                guest_id = guest_state["yourPlayerId"]
                reset = await self.run_cli_online(
                    "reset-password", "重启房主", input="Restart9\nRestart9\n")
                self.assertEqual(reset.returncode, 0, reset.stderr + reset.stdout)
                # 目标（房主）的已建立连接收到撤销说明并被关闭。
                message = json.loads(await asyncio.wait_for(host_socket.recv(), 3))
                self.assertEqual(message["code"], "auth.session-revoked")
                with self.assertRaises(websockets.ConnectionClosed):
                    await asyncio.wait_for(host_socket.recv(), 3)
                # 对照：另一账号的连接照常，还收到房主被踢触发的状态广播。
                message = json.loads(await asyncio.wait_for(guest_socket.recv(), 3))
                self.assertEqual(message["type"], "state")
                self.assertEqual(message["roomCode"], code)
                return guest_id
        guest_id = asyncio.run(scenario())

        # 座位与占用保留。
        self.assertEqual(self.request(f"/api/rooms/{code}")[1]["playerCount"], 2)

        # 服务重启（同一存档目录）后：房主用新密码恢复原房与房主身份。
        self.stop_server()
        self.start_server()
        self.assertEqual(
            self.request("/api/auth/login", {"username": "重启房主", "password": "Restart9"})[0], 200)
        self.assertEqual(
            self.request("/api/auth/login", {"username": "重启房主", "password": "123456"})[0], 401,
            "旧密码在重启后同样不可用")
        _, host_new = self.login("重启房主", "Restart9")
        room = self.request("/api/account/room", cookie=host_new)[1]["room"]
        self.assertEqual((room or {}).get("code"), code, "重启后房主归属不得丢失")

        # 其他账号继续操作：既有登录跨重启仍有效，恢复原座位并收到房主操作。
        self.assertEqual(self.request("/api/auth/session", cookie=guest_cookie)[0], 200)
        guest_room = self.request("/api/account/room", cookie=guest_cookie)[1]["room"]
        self.assertEqual((guest_room or {}).get("code"), code)

        async def resume_and_operate():
            async with self.connect(code, host_new) as host_socket, \
                    self.connect(code, guest_cookie) as guest_socket:
                host_state = await self.hello(host_socket)
                guest_state = await self.hello(guest_socket)
                await host_socket.send(json.dumps({"type": "host", "action": "lock"}))
                while True:
                    message = json.loads(await asyncio.wait_for(guest_socket.recv(), 5))
                    if message.get("type") == "state" and message.get("locked"):
                        return host_state, guest_state
        host_state, guest_state = asyncio.run(resume_and_operate())
        self.assertTrue(host_state["isHost"], "重启后新密码重登必须恢复房主身份")
        self.assertTrue(any(action["type"] in ("lock", "unlock") for action in host_state["hostActions"]),
                        "房主操作权必须随归属恢复")
        self.assertEqual(guest_state["yourPlayerId"], guest_id, "其他账号恢复原座位")

    def test_v14_04_reset_leaks_nothing_and_grants_only_local_admin(self):
        """V14.04: 密码不出现在命令行、输出、日志或帮助；普通账号与错误管理
        凭证不能重置；写操作只有本机独立管理凭证可用。"""
        token = self.admin_token()
        self.assertTrue(token)
        old_password = "Secret9A"
        _, target_cookie = self.signup("泄漏玩家", password=old_password)
        _, guest_cookie = self.signup("泄漏路人")
        attempt = {"username": "泄漏玩家", "password": "Hacked9Px"}

        def login_status(password):
            return self.request("/api/auth/login", {"username": "泄漏玩家", "password": password})[0]

        # 管理端口写路径反例：无凭证 / 错误凭证 / 普通账号会话 / 伪造转发头 → 401。
        self.assertEqual(self.admin_post("/admin/reset-password", attempt)[0], 401)
        self.assertEqual(self.admin_post("/admin/reset-password", attempt, token="wrong-token")[0], 401)
        self.assertEqual(self.admin_post("/admin/reset-password", attempt, cookie=guest_cookie)[0], 401,
                         "普通账号登录会话不能执行管理写操作")
        forged = {"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1",
                  "Forwarded": "for=127.0.0.1"}
        self.assertEqual(
            self.admin_post("/admin/reset-password", attempt, token="wrong-token",
                            extra_headers=forged)[0], 401)
        # GET 方式访问写端点被拒。
        self.assertEqual(self.admin_http("/admin/reset-password", token=token)[0], 405)
        # 公网入口没有任何管理路由：伪造本机转发头 + 正确管理凭证也不能重置。
        self.assertEqual(self.public_http("/admin/reset-password", {**forged, "X-Admin-Token": token})[0], 404,
                         "公网入口不得暴露管理写操作")
        # 错误凭证不得造成任何修改。
        self.assertEqual(login_status(old_password), 200)

        # 正确凭证 + 未知账号：明确拒绝且不自动创建。
        status, body = self.admin_post("/admin/reset-password",
                                       {"username": "幽灵账号", "password": "Hacked9Px"}, token=token)
        self.assertEqual(status, 404)
        self.assertIn("不存在", body["message"])
        users = self.run_cli("users")
        self.assertNotIn("幽灵账号", users.stdout)

        # CLI 成功重置：新密码、旧密码、管理凭证、会话值都不出现在任何输出。
        new_password = "Fresh9Pwd"
        reset = self.run_cli("reset-password", "泄漏玩家",
                             input=f"{new_password}\n{new_password}\n")
        self.assertEqual(reset.returncode, 0, reset.stderr + reset.stdout)
        session_value = target_cookie.split("=", 1)[1]
        combined = reset.stdout + reset.stderr
        for secret, label in ((old_password, "旧密码"), (new_password, "新密码"),
                              (token, "管理凭证"), (session_value, "登录会话")):
            self.assertNotIn(secret, combined, f"CLI 输出不得包含{label}")
        log = (Path(self.tmp.name) / "server.log").read_text(encoding="utf-8", errors="replace")
        for secret, label in ((old_password, "旧密码"), (new_password, "新密码"), (token, "管理凭证")):
            self.assertNotIn(secret, log, f"服务日志不得包含{label}")
        self.assertEqual(login_status(new_password), 200)
        self.assertEqual(login_status(old_password), 401)

        # 帮助不提供明文密码参数；密码作为多余位置参数会被拒绝且不发生重置。
        help_output = self.run_cli("reset-password", "--help")
        self.assertEqual(help_output.returncode, 0)
        self.assertNotIn("--password", help_output.stdout)
        positional = self.run_cli("reset-password", "泄漏玩家", "Ghost9Pwd", input="")
        self.assertNotEqual(positional.returncode, 0)
        self.assertEqual(
            self.request("/api/auth/login", {"username": "泄漏玩家", "password": "Ghost9Pwd"})[0], 401,
            "命令行上塞密码不得触发重置")
        self.assertEqual(login_status(new_password), 200, "既有密码不受被拒绝的调用影响")

    def test_v14_05_persistence_failure_reports_failure_and_keeps_state_consistent(self):
        """V14.05: 账号库持久化被注入只读故障时重置不返回成功；恢复后重新查询
        与重启的结果都与实际状态一致。"""
        import stat
        _, cookie_a = self.signup("注入玩家")
        _, cookie_b = self.login("注入玩家")
        database = Path(self.tmp.name) / "accounts" / "accounts.sqlite3"

        os.chmod(database, stat.S_IREAD)  # 注入：账号库不可写（密码更新与全部撤销同事务）
        try:
            failed = self.run_cli("reset-password", "注入玩家", input="Inject9P\nInject9P\n")
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("失败", failed.stderr)
            self.assertIn("重置未完成", failed.stderr, "失败必须明确说明重置未完成")
            for secret in ("Inject9P", self.admin_token()):
                self.assertNotIn(secret, failed.stdout + failed.stderr)
        finally:
            os.chmod(database, stat.S_IREAD | stat.S_IWRITE)

        # 失败后无副作用：旧密码仍可登录、两台设备的会话都未被部分撤销。
        self.assertEqual(self.request("/api/auth/session", cookie=cookie_a)[0], 200)
        self.assertEqual(self.request("/api/auth/session", cookie=cookie_b)[0], 200)
        self.assertEqual(
            self.request("/api/auth/login", {"username": "注入玩家", "password": "123456"})[0], 200)

        # 恢复后重置成功；重启服务后重新查询与实际一致。
        ok = self.run_cli("reset-password", "注入玩家", input="Inject9P\nInject9P\n")
        self.assertEqual(ok.returncode, 0, ok.stderr + ok.stdout)
        self.stop_server()
        self.start_server()
        self.assertEqual(self.request("/api/auth/session", cookie=cookie_a)[0], 401)
        self.assertEqual(self.request("/api/auth/session", cookie=cookie_b)[0], 401)
        self.assertEqual(
            self.request("/api/auth/login", {"username": "注入玩家", "password": "123456"})[0], 401)
        _, new_cookie = self.login("注入玩家", "Inject9P")
        self.assertEqual(self.request("/api/auth/session", cookie=new_cookie)[0], 200)
