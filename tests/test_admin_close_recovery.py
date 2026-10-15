"""Ticket 22: interrupted admin close — recovery, no resurrection, consistency.

Real uvicorn processes (real ``taskkill /T /F`` termination, same saves dir
restart), real CLI subprocesses (``python -m server.admin close-room``) and
real WebSocket connections. To interrupt the close at an exact boundary the
server subprocess is started with the verification-only fault hook
``BLOOD_BOUND_ADMIN_CLOSE_FAULT=<before-backup|after-backup|after-commit>``:
the close pauses at that boundary, drops a marker file into the saves dir and
waits for a release file. The test observes the marker (deterministic
synchronisation — no timing luck), then either really kills the process tree
(fault injection) or writes the release file to gate a deterministic
interleaving of close vs queued player traffic.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import websockets

from tests import test_accounts as account_tests  # noqa: F401  (同手法基线)
from tests.account_fixtures import account as fixture_account
from tests.test_server_rooms import command as room_command, resolve_reveal_windows

REPO_ROOT = Path(__file__).resolve().parents[1]
_CLI_POOL = ThreadPoolExecutor(max_workers=1)
# 本工单测试独占的公共端口段（29240–29259）；服务重启复用同一端口。
_PORT_POOL = iter(range(29240, 29260))

FAULT_ENV = "BLOOD_BOUND_ADMIN_CLOSE_FAULT"
MARKER_PREFIX = ".admin-close-fault"


def marker_path(saves_dir, point):
    return Path(saves_dir) / f"{MARKER_PREFIX}.{point}.marker"


def release_path(saves_dir, point):
    return Path(saves_dir) / f"{MARKER_PREFIX}.{point}.release"


class ClosedRoomRecoveryTests(unittest.TestCase):
    """V16.01–V16.05：清理中断后的恢复与关闭房间不复活。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.port = next(_PORT_POOL)
        self.process = None
        self.log = None
        self.addCleanup(self.stop_server)

    # ---- 服务进程（支持故障注入环境变量与真实整树终止） --------------------

    def start_server(self, extra_env=None):
        # 同一测试内重启前先清掉旧进程：旧进程存活会使新 uvicorn 绑定失败，
        # 而健康检查打到旧进程上造成“假启动”。
        self.stop_server()
        self.log_path = Path(self.tmp.name) / "server.log"
        self.log = self.log_path.open("ab")
        environment = {**os.environ, "BLOOD_BOUND_SAVES_DIR": self.tmp.name,
                       **(extra_env or {})}
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.app:app",
             "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=str(REPO_ROOT), env=environment, stdout=self.log, stderr=self.log)
        for _ in range(200):
            if self.process.poll() is not None:
                self.fail(f"uvicorn 启动后即退出（端口 {self.port} 被其他进程占用？）："
                          f"{self.log_path.read_text(encoding='utf-8', errors='replace')[-2000:]}")
            try:
                self.request("/health")
                return
            except OSError:
                time.sleep(0.05)
        self.fail("隔离 HTTP 服务未启动")

    def stop_server(self):
        """真实整树终止（工单 22 的故障注入手段，不是 mock）。"""
        if self.process is None:
            return
        if os.name == "nt" and self.process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            self.process.wait(timeout=10)
        elif self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)
        if self.log is not None:
            self.log.close()
        self.process = None

    def request(self, path, data=None, cookie=None):
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        import urllib.error
        import urllib.request
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            response = opener.open(request)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response), response.headers

    # ---- 账号/房间/WS 辅助（与工单 21 测试同一手法） ------------------------

    def signup(self, name, password="123456"):
        status, body, headers = self.request("/api/auth/register", {
            "username": name, "password": password, "confirmPassword": password})
        self.assertEqual(status, 201, body)
        return body["account"], headers["Set-Cookie"].split(";", 1)[0]

    def create_room(self, cookie):
        status, room, _ = self.request("/api/rooms", {}, cookie)
        self.assertEqual(status, 200, room)
        return room["code"], room["gameId"]

    def connect(self, code, cookie, mode="player"):
        return websockets.connect(f"ws://127.0.0.1:{self.port}/ws/{code}",
                                  additional_headers={"Cookie": cookie}, proxy=None)

    async def hello(self, socket, **fields):
        await socket.send(json.dumps({"type": "hello", "mode": "player",
                                      "protocolVersion": "4", **fields}))
        return json.loads(await asyncio.wait_for(socket.recv(), 3))

    async def state_of(self, code, cookie, **fields):
        async with self.connect(code, cookie) as socket:
            return await self.hello(socket, **fields)

    async def fill_and_start(self, code, host_cookie, total, prefix, start_payload=None):
        """Join accounts until the room holds `total` seats, then start via the host."""
        member_cookies = []
        current = self.request(f"/api/rooms/{code}")[1]["playerCount"]
        for index in range(total - current):
            _, cookie = self.signup(f"{prefix}{index}")
            member_cookies.append(cookie)
            await self.state_of(code, cookie)
        host_message = {"type": "host", "action": "start", **(start_payload or {})}
        async with self.connect(code, host_cookie) as socket:
            await self.hello(socket)
            await socket.send(json.dumps(host_message))
            while True:
                message = json.loads(await asyncio.wait_for(socket.recv(), 5))
                if message.get("type") == "state" and message["roomStatus"] == "playing":
                    return message, member_cookies
                if message.get("type") == "error":
                    raise AssertionError(message)

    # ---- CLI 子进程辅助 -----------------------------------------------------

    def run_cli(self, *arguments, confirmation=None, timeout=180):
        command = [sys.executable, "-m", "server.admin", *map(str, arguments)]
        command += ["--saves-dir", str(self.tmp.name)]
        environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        return subprocess.run(command, cwd=str(REPO_ROOT), env=environment,
                              capture_output=True, text=True, encoding="utf-8",
                              input=None if confirmation is None else confirmation,
                              timeout=timeout)

    async def run_cli_online(self, *arguments, confirmation=None):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_CLI_POOL, partial(self.run_cli, *arguments, confirmation=confirmation))

    def lines_with(self, output, needle):
        return [line for line in output.splitlines() if needle in line]

    # ---- 管理端口直连辅助 ---------------------------------------------------

    def admin_port(self):
        installation = json.loads(
            (Path(self.tmp.name) / "admin" / "installation.json").read_text(encoding="utf-8"))
        return installation["adminPort"]

    def admin_token(self):
        return (Path(self.tmp.name) / "admin" / "admin-token").read_text(encoding="utf-8").strip()

    def admin_http(self, path, token=None, method="GET", data=None):
        import urllib.error
        import urllib.request
        headers = {}
        if token is not None:
            headers["X-Admin-Token"] = token
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"http://127.0.0.1:{self.admin_port()}{path}",
                                         headers=headers, method=method,
                                         data=json.dumps(data).encode() if data is not None else None)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            response = opener.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def occupancy_of(self, cookie):
        return self.request("/api/account/room", cookie=cookie)[1]["room"]

    async def expect_close_notice(self, socket):
        """关闭终止帧及其后的连接关闭。

        关闭前排队的正常帧（命令 ack、公开事件、状态广播）先排空——它们
        属于关闭之前的合法流量；关键不变量是：随后必须是关闭终止帧，且
        服务端关闭连接后不再有任何帧。
        """
        deadline = asyncio.get_running_loop().time() + 5
        message = None
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            self.assertGreater(remaining, 0, "关闭通知超时未到达")
            message = json.loads(await asyncio.wait_for(socket.recv(), remaining))
            if message.get("type") == "error":
                break
        self.assertEqual(message.get("code"), "room.admin-closed", message)
        with self.assertRaises(websockets.exceptions.ConnectionClosed):
            await asyncio.wait_for(socket.recv(), 5)

    # ---- 故障注入辅助 -------------------------------------------------------

    def wait_for_marker(self, point, timeout=20.0):
        marker = marker_path(self.tmp.name, point)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if marker.is_file():
                return marker
            time.sleep(0.05)
        self.fail(f"故障注入标记未出现（{point}）：{marker}")

    def write_release(self, point):
        release_path(self.tmp.name, point).write_text("go", encoding="utf-8")

    def clear_fault_files(self, point):
        for path in (marker_path(self.tmp.name, point), release_path(self.tmp.name, point)):
            path.unlink(missing_ok=True)

    # ---- V16.01 ------------------------------------------------------------

    def test_v16_01_real_process_kills_at_three_boundaries_then_restart_and_retry(self):
        """V16.01: 真实进程终止在 备份前 / 备份后未提交 / 关闭提交后回复丢失
        三个边界；重启后逐项核对可加入性、占用与备份，未完成关闭可安全重试。"""
        from blood_bound import load_game

        point_labels = {"before-backup": "备份前", "after-backup": "备份后", "after-commit": "提交后"}
        for point in ("before-backup", "after-backup", "after-commit"):
            with self.subTest(boundary=point):
                self.start_server({FAULT_ENV: point})
                host_account, host_cookie = self.signup(f"边界房主{point_labels[point]}")
                code, game_id = self.create_room(host_cookie)
                guest_account, guest_cookie = self.signup(f"边界玩家{point_labels[point]}")
                asyncio.run(self.state_of(code, guest_cookie))
                self.assertEqual(self.occupancy_of(host_cookie),
                                 {"code": code, "status": "waiting"})

                saves = Path(self.tmp.name)
                backup_dir = saves / "admin-backup" / game_id
                active_save = saves / f"{game_id}.json.gz"
                active_meta = saves / f"{game_id}.meta.json"

                async def interrupt_mid_close():
                    close_task = asyncio.ensure_future(
                        self.run_cli_online("close-room", code, confirmation=f"{code}\n"))
                    await asyncio.get_running_loop().run_in_executor(
                        None, partial(self.wait_for_marker, point))
                    # 边界处的文件系统事实（进程仍停在边界上）。
                    if point == "before-backup":
                        self.assertFalse((backup_dir / "closure.json").exists(),
                                         "备份前边界不得已写任何备份内容")
                    elif point == "after-backup":
                        for name in ("game.json.gz", "meta.json", "closure.json"):
                            self.assertTrue((backup_dir / name).is_file(),
                                            f"备份后边界必须已有备份文件 {name}")
                        self.assertTrue(active_save.is_file() and active_meta.is_file(),
                                        "备份后未提交边界：活动存档必须仍在")
                    closure_before_kill = None
                    if point == "after-commit":
                        for name in ("game.json.gz", "meta.json", "closure.json"):
                            self.assertTrue((backup_dir / name).is_file())
                        self.assertFalse(active_save.exists() or active_meta.exists(),
                                         "提交后边界：活动存档必须已移出")
                        closure_before_kill = (backup_dir / "closure.json").read_bytes()
                    # 真实整树终止进程。
                    await asyncio.get_running_loop().run_in_executor(None, self.stop_server)
                    return await close_task, closure_before_kill

                close_result, closure_before_kill = asyncio.run(interrupt_mid_close())

                # 回复丢失：CLI 非零退出、中文失败说明、绝无成功摘要。
                self.assertNotEqual(close_result.returncode, 0,
                                    close_result.stdout + close_result.stderr)
                self.assertFalse(self.lines_with(close_result.stdout, "已关闭"),
                                 "中断的关闭不得输出成功摘要")

                # ---- 重启（同一存档目录，清洁环境）----
                self.start_server()
                self.assertEqual(self.request("/health")[0], 200)

                if point in ("before-backup", "after-backup"):
                    # 未完成关闭：房间恢复、占用恢复、可再加入；重试后成功关闭。
                    self.assertEqual(self.request(f"/api/rooms/{code}")[0], 200)
                    state = asyncio.run(self.state_of(code, host_cookie))
                    self.assertEqual(state["roomStatus"], "waiting")
                    for cookie in (host_cookie, guest_cookie):
                        self.assertEqual(self.occupancy_of(cookie),
                                         {"code": code, "status": "waiting"})
                    if point == "after-backup":
                        # 中断尝试的关闭记录必须被重启愈合：它描述的关闭从未提交。
                        self.assertFalse((backup_dir / "closure.json").exists(),
                                         "未提交关闭的 stale closure.json 不得在重启后继续冒充已关闭")
                    retry = self.run_cli("close-room", code, confirmation=f"{code}\n")
                    self.assertEqual(retry.returncode, 0, retry.stderr + retry.stdout)
                    self.assertEqual(self.request(f"/api/rooms/{code}")[0], 404)
                    for cookie in (host_cookie, guest_cookie):
                        self.assertIsNone(self.occupancy_of(cookie), "成功重试后占用必须释放")
                    self.assertFalse(list(saves.glob(f"{game_id}.*")), "成功重试后活动存档必须移出")
                    closure = json.loads((backup_dir / "closure.json").read_text(encoding="utf-8"))
                    self.assertEqual(closure["gameId"], game_id)
                    engine = load_game(backup_dir / "game.json.gz")
                    self.assertNotEqual(engine.state.status, "ended")
                else:
                    # 已提交但回复丢失：房间不得复活、占用不得恢复、备份原样。
                    self.assertEqual(self.request(f"/api/rooms/{code}")[0], 404, "重启不得恢复已关闭房间")
                    for cookie in (host_cookie, guest_cookie):
                        self.assertIsNone(self.occupancy_of(cookie), "重启不得重新占用已关房玩家")
                    status, room, _ = self.request("/api/rooms", {}, host_cookie)
                    self.assertEqual(status, 200, "已关房玩家必须能开新房")
                    self.assertNotEqual(room["code"], code)
                    status, replay, _ = self.request(f"/api/rooms/{code}/replay", None, host_cookie)
                    self.assertEqual(status, 404, replay)
                    # 重试明确报告已关闭（不是笼统不存在），且无第二次破坏。
                    retry = self.run_cli("close-room", code, confirmation=f"{code}\n")
                    self.assertNotEqual(retry.returncode, 0)
                    self.assertIn("被管理关闭", retry.stderr)
                    self.assertIn("无需重复处理", retry.stderr)
                    self.assertEqual((backup_dir / "closure.json").read_bytes(),
                                     closure_before_kill, "重复处理不得改写既有关闭记录")
                    self.assertTrue((backup_dir / "game.json.gz").is_file())

                # 收尾，进入下一个边界。
                self.stop_server()

    # ---- V16.02 ------------------------------------------------------------

    def test_v16_02_repeat_calls_and_stale_commands_stay_idempotent_and_scoped(self):
        """V16.02: 回复丢失后的重复调用明确已关闭且无第二次破坏；旧命令的
        对局引用不能作用到其他房间。"""
        self.start_server()
        host_account, host_cookie = self.signup("幂等房主")
        code_a, game_a = self.create_room(host_cookie)
        guest_account, guest_cookie = self.signup("幂等玩家")
        asyncio.run(self.state_of(code_a, guest_cookie))

        other_account, other_cookie = self.signup("相邻房主")
        code_b, game_b = self.create_room(other_cookie)

        first = self.run_cli("close-room", code_a, confirmation=f"{code_a}\n")
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        backup_dir = Path(self.tmp.name) / "admin-backup" / game_a
        closure_bytes = (backup_dir / "closure.json").read_bytes()

        # 重复 CLI 处理：明确已关闭，关闭记录一字不改，无第二个备份目录。
        repeat = self.run_cli("close-room", code_a, confirmation=f"{code_a}\n")
        self.assertNotEqual(repeat.returncode, 0)
        self.assertIn("被管理关闭", repeat.stderr)
        self.assertIn("无需重复处理", repeat.stderr)
        self.assertEqual((backup_dir / "closure.json").read_bytes(), closure_bytes)
        self.assertEqual([entry.name for entry in (Path(self.tmp.name) / "admin-backup").iterdir()],
                         [game_a], "重复处理不得新建第二个备份目录")

        token = self.admin_token()
        # 持有旧确认信息（指向别的对局引用）的重复 POST：已关闭优先明确报告，不做任何动作。
        stale_cross_game = self.admin_http(
            "/admin/close-room", token=token, method="POST",
            data={"code": code_a, "expectedGameId": game_b, "expectedRevision": 1})
        self.assertEqual(stale_cross_game[0], 409, stale_cross_game[1])
        self.assertEqual(stale_cross_game[1]["error"], "room.admin-closed")
        self.assertEqual((backup_dir / "closure.json").read_bytes(), closure_bytes)

        # 旧命令指向仍活跃的相邻房：对局引用不符即拒绝，相邻房原样可用。
        wrong_reference = self.admin_http(
            "/admin/close-room", token=token, method="POST",
            data={"code": code_b, "expectedGameId": game_a, "expectedRevision": 1})
        self.assertEqual(wrong_reference[0], 409, wrong_reference[1])
        self.assertEqual(wrong_reference[1]["error"], "admin.target-changed")
        stale_revision = self.admin_http(
            "/admin/close-room", token=token, method="POST",
            data={"code": code_b, "expectedGameId": game_b, "expectedRevision": 99999})
        self.assertEqual(stale_revision[0], 409, stale_revision[1])
        self.assertEqual(stale_revision[1]["error"], "admin.target-changed")
        self.assertEqual(self.request(f"/api/rooms/{code_b}")[1]["status"], "waiting")
        self.assertEqual(self.occupancy_of(other_cookie), {"code": code_b, "status": "waiting"})
        self.assertTrue((Path(self.tmp.name) / f"{game_b}.json.gz").is_file())

        # 重启后同一语义：已关房不再复活，重复处理仍明确报告已关闭。
        self.stop_server()
        self.start_server()
        self.assertEqual(self.request(f"/api/rooms/{code_a}")[0], 404)
        after_restart = self.admin_http(
            "/admin/close-room", token=token, method="POST",
            data={"code": code_a, "expectedGameId": game_a, "expectedRevision": 1})
        self.assertEqual(after_restart[0], 409, after_restart[1])
        self.assertEqual(after_restart[1]["error"], "room.admin-closed")
        self.assertEqual(after_restart[1]["details"].get("backupPath"), str(backup_dir.resolve()))
        self.assertEqual((backup_dir / "closure.json").read_bytes(), closure_bytes,
                         "重启后的重复处理同样不得改写关闭记录")

    # ---- V16.03 ------------------------------------------------------------

    def test_v16_03_close_races_settle_into_one_unambiguous_state(self):
        """V16.03: 关闭与玩家动作、开局、正常终局、重连竞争——最终状态明确，
        关闭后没有新事件、没有私有帧、活动存档不被重建。"""
        from blood_bound import load_game

        self.start_server()
        host_account, host_cookie = self.signup("并发房主")
        code, game_id = self.create_room(host_cookie)
        saves = Path(self.tmp.name)
        backup_dir = saves / "admin-backup" / game_id

        # (1) 动作先落、关闭随后：备份必须包含已接受动作的修订号。
        async def action_then_close():
            started, member_cookies = await self.fill_and_start(code, host_cookie, 6, "并发成员")
            room_cookies = [host_cookie, *member_cookies]
            sockets = [await self.connect(code, cookie) for cookie in room_cookies]
            states = [await self.hello(socket) for socket in sockets]
            # 攻击一次打开干涉请求（gate）窗口：攻击者用既有连接，避免接管。
            attacker_index = next(index for index, state in enumerate(states)
                                  if any(action["type"] == "attack" for action in state["game"]["legalActions"]))
            attack = next(action for action in states[attacker_index]["game"]["legalActions"]
                          if action["type"] == "attack")
            await sockets[attacker_index].send(json.dumps({
                "type": "command", "command": "attack",
                "payload": {"targetPlayerId": attack["targetPlayerId"]},
                "commandId": "v16-03-attack",
                "expectedRevision": states[attacker_index]["game"]["revision"]}))
            attack_revision = None
            while True:
                message = json.loads(await asyncio.wait_for(sockets[attacker_index].recv(), 5))
                self.assertNotEqual(message.get("type"), "error", message)
                if message.get("type") == "ack" and message.get("commandId") == "v16-03-attack":
                    self.assertEqual(message["status"], "accepted", message)
                    attack_revision = message["revision"]
                    break
            # 广播后每人先收公开事件再收新状态：跳过 hello 期积压的旧状态，
            # 从攻击后的状态里找到可应答的当事人并应答。
            accepted_revision = None
            answered = False
            for socket in sockets:
                message = None
                while True:
                    message = json.loads(await asyncio.wait_for(socket.recv(), 5))
                    self.assertNotEqual(message.get("type"), "error", message)
                    if (message.get("type") == "state"
                            and message["game"]["revision"] >= attack_revision):
                        break
                if answered or not any(action["type"] == "answer-intervention-request"
                                       for action in message["game"]["legalActions"]):
                    continue
                answered = True
                await socket.send(json.dumps({
                    "type": "command", "command": "answer-intervention-request",
                    "payload": {"need": True}, "commandId": "v16-03-answer",
                    "expectedRevision": message["game"]["revision"]}))
                while True:
                    reply = json.loads(await asyncio.wait_for(socket.recv(), 5))
                    if reply.get("type") == "ack" and reply.get("commandId") == "v16-03-answer":
                        self.assertEqual(reply["status"], "accepted", reply)
                        accepted_revision = reply["revision"]
                        break
            self.assertTrue(answered and accepted_revision is not None, "并发房未能进入可应答窗口")
            close_result = await self.run_cli_online("close-room", code, confirmation=f"{code}\n")
            for socket in sockets:
                await self.expect_close_notice(socket)
                await socket.close()
            return close_result, accepted_revision

        close_result, accepted_revision = asyncio.run(action_then_close())
        self.assertEqual(close_result.returncode, 0, close_result.stderr + close_result.stdout)
        engine = load_game(backup_dir / "game.json.gz")
        self.assertGreaterEqual(engine.state.revision, accepted_revision,
                                "已接受动作必须已包含在备份里（不得回退或丢帧）")
        self.assertFalse(list(saves.glob(f"{game_id}.*")), "关闭后不得重建活动存档")
        self.assertEqual(self.request(f"/api/rooms/{code}")[0], 404)

        # (2)(3)(4) 故障门控的确定性交错：关闭停在提交前，玩家流量在窗口里排队。
        self.stop_server()
        self.start_server({FAULT_ENV: "after-backup"})

        race_host_account, race_host_cookie = self.signup("竞速房主")
        code_race, game_race = self.create_room(race_host_cookie)
        race_members = []
        for index in range(5):
            _, cookie = self.signup(f"竞速成员{index}")
            race_members.append(cookie)
            asyncio.run(self.state_of(code_race, cookie))
        race_backup = saves / "admin-backup" / game_race

        async def queued_traffic_during_close():
            await self.fill_and_start(code_race, race_host_cookie, 6, "竞速补位")
            room_cookies = [race_host_cookie, *race_members]
            # 攻击一次打开干涉请求（gate）窗口（临时连接，用后即关）。
            revision_before = None
            for cookie in room_cookies:
                async with self.connect(code_race, cookie) as socket:
                    state = await self.hello(socket)
                    attacks = [action for action in state["game"]["legalActions"]
                               if action["type"] == "attack"]
                    if not attacks:
                        continue
                    await socket.send(json.dumps({
                        "type": "command", "command": "attack",
                        "payload": {"targetPlayerId": attacks[0]["targetPlayerId"]},
                        "expectedRevision": state["game"]["revision"]}))
                    while True:
                        message = json.loads(await asyncio.wait_for(socket.recv(), 5))
                        if message.get("type") == "state" and message["game"].get("pending"):
                            revision_before = message["game"]["revision"]
                            break
                    break
            self.assertIsNotNone(revision_before, "竞速房未能进入决策窗口")

            # 当事人（受攻击的目标）持有 answer-intervention-request 合法动作；
            # 该连接完成 hello 后保持打开，稍后在关闭窗口里排队一条命令。
            queued_socket = None
            queued_revision = None
            for cookie in room_cookies:
                candidate = await self.connect(code_race, cookie)
                state = await self.hello(candidate)
                if any(action["type"] == "answer-intervention-request"
                       for action in state["game"]["legalActions"]):
                    queued_socket = candidate
                    queued_revision = state["game"]["revision"]
                    break
                await candidate.close()
            self.assertIsNotNone(queued_socket, "未能找到可应答的当事人")
            # 预建重连与旁观连接（只完成握手，hello 稍后排队）。
            reconnect_socket = await self.connect(code_race, race_members[0])
            spectator_account, spectator_cookie = self.signup("竞速旁观")
            spectator_socket = await self.connect(code_race, spectator_cookie)

            self.clear_fault_files("after-backup")
            close_task = asyncio.ensure_future(
                self.run_cli_online("close-room", code_race, confirmation=f"{code_race}\n"))
            await asyncio.get_running_loop().run_in_executor(
                None, partial(self.wait_for_marker, "after-backup"))

            # 关闭停在提交前：排队的玩家合法动作、重连 hello 与旁观 hello。
            await queued_socket.send(json.dumps({
                "type": "command", "command": "answer-intervention-request",
                "payload": {"need": True}, "commandId": "v16-03-queued",
                "expectedRevision": queued_revision}))
            await reconnect_socket.send(json.dumps({"type": "hello", "mode": "player",
                                                    "protocolVersion": "4"}))
            await spectator_socket.send(json.dumps({"type": "hello", "mode": "spectator",
                                                    "protocolVersion": "4"}))

            # 放行关闭：提交完成后排队的流量才被处理。
            await asyncio.get_running_loop().run_in_executor(
                None, partial(self.write_release, "after-backup"))
            close_result = await close_task

            # 排队的玩家命令被丢弃：只允许关闭终止帧，绝无该命令的 ack/事件。
            frames = []
            try:
                while True:
                    frames.append(json.loads(await asyncio.wait_for(queued_socket.recv(), 3)))
            except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError):
                pass
            self.assertFalse([frame for frame in frames
                              if frame.get("type") in ("ack", "event")],
                             f"关闭后排队的命令不得有任何确认或事件：{frames}")
            self.assertTrue(any(frame.get("code") == "room.admin-closed" for frame in frames),
                            frames)

            # 排队的重连/旁观 hello：第一条帧必须是关闭错误（不得呈现已关房为可用状态）。
            reconnect_first = json.loads(await asyncio.wait_for(reconnect_socket.recv(), 3))
            self.assertEqual(reconnect_first.get("type"), "error", reconnect_first)
            self.assertEqual(reconnect_first.get("code"), "room.admin-closed", reconnect_first)
            spectator_first = json.loads(await asyncio.wait_for(spectator_socket.recv(), 3))
            self.assertEqual(spectator_first.get("code"), "room.admin-closed", spectator_first)

            for socket in (queued_socket, reconnect_socket, spectator_socket):
                await socket.close()
            return close_result, revision_before

        close_result, revision_before = asyncio.run(queued_traffic_during_close())
        self.assertEqual(close_result.returncode, 0, close_result.stderr + close_result.stdout)
        engine = load_game(race_backup / "game.json.gz")
        self.assertEqual(engine.state.revision, revision_before,
                         "提交前排队的玩家命令不得写进已备份的对局")
        self.assertFalse(list(saves.glob(f"{game_race}.*")),
                         "关闭提交后不得因排队流量重建活动存档")
        self.assertEqual(self.request(f"/api/rooms/{code_race}")[0], 404)

        # (3b) 开局与关闭竞争（同门控）：提交前排队的 start 不生效。
        start_host_account, start_host_cookie = self.signup("开局房主")
        code_start, game_start = self.create_room(start_host_cookie)
        for index in range(5):
            _, cookie = self.signup(f"开局成员{index}")
            asyncio.run(self.state_of(code_start, cookie))

        async def queued_start_during_close():
            host_socket = await self.connect(code_start, start_host_cookie)
            await self.hello(host_socket)
            self.clear_fault_files("after-backup")
            close_task = asyncio.ensure_future(
                self.run_cli_online("close-room", code_start, confirmation=f"{code_start}\n"))
            await asyncio.get_running_loop().run_in_executor(
                None, partial(self.wait_for_marker, "after-backup"))
            await host_socket.send(json.dumps({"type": "host", "action": "start"}))
            await asyncio.get_running_loop().run_in_executor(
                None, partial(self.write_release, "after-backup"))
            close_result = await close_task
            frames = []
            try:
                while True:
                    frames.append(json.loads(await asyncio.wait_for(host_socket.recv(), 3)))
            except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError):
                pass
            self.assertFalse([frame for frame in frames if frame.get("type") == "event"],
                             f"关闭后不得出现开局事件：{frames}")
            await host_socket.close()
            return close_result

        close_result = asyncio.run(queued_start_during_close())
        self.assertEqual(close_result.returncode, 0, close_result.stderr + close_result.stdout)
        engine = load_game((saves / "admin-backup" / game_start) / "game.json.gz")
        self.assertEqual(engine.state.status, "setup", "提交前排队开局不得生效")
        self.assertFalse(list(saves.glob(f"{game_start}.*")))

        # (5) 正常终局与关闭竞争的另一种落点：真实打完整局后关闭被明确拒绝。
        self.stop_server()
        self.start_server()
        ended_host_account, ended_host_cookie = self.signup("终局房主")
        code_end, game_end = self.create_room(ended_host_cookie)
        asyncio.run(self.play_full_game(code_end, ended_host_cookie))
        refused = self.run_cli("close-room", code_end, confirmation=f"{code_end}\n")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("已正常结束", refused.stderr)
        status, replay, _ = self.request(f"/api/rooms/{code_end}/replay", None, ended_host_cookie)
        self.assertEqual(status, 200, replay)
        self.assertTrue((saves / f"{game_end}.json.gz").is_file(), "终局回放不得被误关清理")
        self.assertEqual(self.request(f"/api/rooms/{code_end}")[1]["status"], "ended")

    async def play_full_game(self, code, host_cookie, max_commands=120):
        """用真实 WS 命令把一局打到正常终局（与发布 smoke 同一推进策略）。"""
        from scripts.release_smoke import next_action

        _, member_cookies = await self.fill_and_start(code, host_cookie, 6, "终局成员")
        cookies = [host_cookie, *member_cookies]
        sockets = [await self.connect(code, cookie) for cookie in cookies]
        states = []
        for socket in sockets:
            states.append(await self.hello(socket))
        commands = 0
        while states[0]["roomStatus"] != "ended":
            self.assertLess(commands, max_commands, "终局对局超出命令上限")
            index, action = next_action(states)
            command_id = f"v16-03-full-{commands}"
            revision = states[index]["game"]["revision"]
            await sockets[index].send(json.dumps({
                "type": "command", "command": action["type"],
                "payload": {key: value for key, value in action.items() if key != "type"},
                "commandId": command_id, "expectedRevision": revision}))
            ack_revision = None
            while True:
                message = json.loads(await asyncio.wait_for(sockets[index].recv(), 5))
                self.assertNotEqual(message.get("type"), "error", message)
                if message.get("type") == "ack" and message.get("commandId") == command_id:
                    self.assertEqual(message["status"], "accepted", message)
                    ack_revision = message["revision"]
                    break
            commands += 1
            # 每条命令后每人一条新状态；跳过此前积压的旧状态帧。
            states = []
            for socket in sockets:
                while True:
                    message = json.loads(await asyncio.wait_for(socket.recv(), 5))
                    self.assertNotEqual(message.get("type"), "error", message)
                    if (message.get("type") == "state"
                            and message["game"]["revision"] >= ack_revision):
                        states.append(message)
                        break
        for socket in sockets:
            await socket.close()
        self.assertEqual(states[0]["roomStatus"], "ended")
        return states[0]

    # ---- V16.04 ------------------------------------------------------------

    def test_v16_04_restart_retention_and_cleanup_never_resurrect_closed_rooms(self):
        """V16.04: 重启、正常终局超过保留上限、游戏清理都不让关闭房复活，
        不删管理备份或账号。"""
        from server.rooms import FINISHED_GAMES_TO_KEEP, RoomManager

        self.start_server()
        host_account, host_cookie = self.signup("隔离房主")
        code, game_id = self.create_room(host_cookie)
        guest_account, guest_cookie = self.signup("隔离玩家")
        asyncio.run(self.state_of(code, guest_cookie))
        close_result = self.run_cli("close-room", code, confirmation=f"{code}\n")
        self.assertEqual(close_result.returncode, 0, close_result.stderr + close_result.stdout)

        saves = Path(self.tmp.name)
        backup_dir = saves / "admin-backup" / game_id
        closure_bytes = (backup_dir / "closure.json").read_bytes()
        account_db = saves / "accounts" / "accounts.sqlite3"
        account_bytes = account_db.read_bytes()

        # 重启：关闭房不复活、占用不恢复、账号与会话照旧。
        self.stop_server()
        self.start_server()
        self.assertEqual(self.request(f"/api/rooms/{code}")[0], 404)
        self.assertIsNone(self.occupancy_of(host_cookie))
        self.assertIsNone(self.occupancy_of(guest_cookie))
        self.assertEqual(self.request("/api/auth/session", cookie=host_cookie)[0], 200)
        users_listing = self.run_cli("users")
        self.assertEqual(users_listing.returncode, 0)
        self.assertTrue(self.lines_with(users_listing.stdout, "隔离房主"))
        self.assertTrue(self.lines_with(users_listing.stdout, "（未占用）"))

        # 正常终局超过保留上限：在同一存档目录上用真实文件驱动存储契约层。
        self.stop_server()
        manager = RoomManager(saves)
        manager.restore()
        self.assertNotIn(code, manager.rooms, "恢复扫描不得复活已关闭房间")
        self._create_finished_rooms(manager, FINISHED_GAMES_TO_KEEP + 3)
        finished = [room for room in manager.rooms.values() if room.status == "ended"]
        self.assertEqual(len(finished), FINISHED_GAMES_TO_KEEP, "保留上限照常生效")
        # 管理备份与账号存储在清理后原样。
        self.assertEqual((backup_dir / "closure.json").read_bytes(), closure_bytes)
        for name in ("game.json.gz", "meta.json"):
            self.assertTrue((backup_dir / name).is_file())
        self.assertEqual(account_db.read_bytes(), account_bytes, "游戏清理不得改动账号存储")
        self.assertNotIn(code, manager.rooms)

        # 再重启真实服务：关闭房仍然关闭，恢复的只有正常终局房。
        self.start_server()
        self.assertEqual(self.request(f"/api/rooms/{code}")[0], 404)
        self.assertIsNone(self.occupancy_of(host_cookie))
        metrics = self.request("/metrics")[1]
        self.assertEqual(metrics["activeRooms"], FINISHED_GAMES_TO_KEEP)
        self.assertEqual((backup_dir / "closure.json").read_bytes(), closure_bytes)
        self.assertEqual(account_db.read_bytes(), account_bytes)

    def _create_finished_rooms(self, manager, count):
        """存储契约层真实文件：确定性打完 `count` 个正常终局（同 test_server_rooms 手法）。"""
        for room_index in range(count):
            room = manager.create_room(fixture_account(f"保留房主{room_index}"))
            for index in range(5):
                manager.join_or_resume(room, fixture_account(f"保留玩家{room_index}_{index}"))
            manager.start_game(room)
            holder = room.engine.state.dagger_holder_id
            victim = next(pid for pid in room.engine.state.players if pid != holder)
            for turn in range(40):
                current = room.engine.state.dagger_holder_id
                if current != holder:
                    manager.apply_command(room, room_command(
                        room.engine, f"pass-{turn}", current, "pass-dagger",
                        targetPlayerId=holder))
                manager.apply_command(room, room_command(
                    room.engine, f"attack-{turn}", holder, "attack", targetPlayerId=victim))
                while room.engine.state.pending and room.engine.state.pending.kind == "intervention":
                    pending = room.engine.state.pending
                    stage = pending.context.get("stage")
                    if stage == "gate":
                        manager.apply_command(room, room_command(
                            room.engine, f"gate-{turn}-{room.engine.state.revision}",
                            pending.actor_player_id, "answer-intervention-request", need=True))
                    elif stage == "poll":
                        responses = pending.context["responses"]
                        responder = next(pid for pid in pending.eligible_player_ids
                                         if pid not in responses)
                        manager.apply_command(room, room_command(
                            room.engine, f"respond-{turn}-{responder}", responder,
                            "respond-intervention", volunteer=False))
                    else:
                        manager.apply_command(room, room_command(
                            room.engine, f"decline-{turn}", victim, "decline-intervention"))
                resolve_reveal_windows(manager, room, victim, f"reveal-{room_index}-{turn}")
                if room.engine.state.pending and room.engine.state.pending.kind == "skill":
                    manager.apply_command(room, room_command(
                        room.engine, f"skill-{turn}", victim, "choose-skill", use=False))
                if room.status == "ended":
                    break
            self.assertEqual(room.status, "ended")

    # ---- V16.05 ------------------------------------------------------------

    def test_v16_05_failure_reports_match_reality_and_toolkit_stays_truthful(self):
        """V16.05: 故障报告、查询状态和恢复后实际结果一致；失败退出不会被
        测试工具箱误记为成功。"""
        from scripts import test_toolkit

        self.start_server()
        host_account, host_cookie = self.signup("一致房主")
        code, game_id = self.create_room(host_cookie)
        guest_account, guest_cookie = self.signup("一致玩家")
        asyncio.run(self.state_of(code, guest_cookie))

        other_account, other_cookie = self.signup("对照房主")
        code_other, game_other = self.create_room(other_cookie)

        saves = Path(self.tmp.name)
        backup_root = saves / "admin-backup"

        with mock.patch.object(test_toolkit, "SAVES_DIR", saves):
            self.assertEqual(test_toolkit.count_saved_rooms(), 2, "关闭前活动房应被计入")

        # (a) 备份目录不可写：失败报告必须与事实一致（房间未关闭、保持可用）。
        backup_root.write_text("占位文件，不是目录", encoding="utf-8")
        failed = self.run_cli("close-room", code, confirmation=f"{code}\n")
        self.assertNotEqual(failed.returncode, 0, "失败退出必须以非零状态传播")
        self.assertIn("备份失败", failed.stderr)
        self.assertIn("未关闭", failed.stderr)
        self.assertFalse(self.lines_with(failed.stdout, "已关闭"))
        # 查询状态与实际结果一致：房间在、占用在、活动存档在。
        self.assertEqual(self.request(f"/api/rooms/{code}")[1]["status"], "waiting")
        self.assertEqual(self.occupancy_of(host_cookie), {"code": code, "status": "waiting"})
        self.assertTrue((saves / f"{game_id}.json.gz").is_file())
        rooms_listing = self.run_cli("rooms")
        self.assertTrue(self.lines_with(rooms_listing.stdout, code), "失败后房间仍应被列出")
        # 工具箱视图同样不得误记：失败关闭后活动房数量不变。
        with mock.patch.object(test_toolkit, "SAVES_DIR", saves):
            self.assertEqual(test_toolkit.count_saved_rooms(), 2)

        # 重启后事实仍与失败报告一致（未留下半关闭的可操作房间状态）。
        backup_root.unlink()
        self.stop_server()
        self.start_server()
        self.assertEqual(self.request(f"/api/rooms/{code}")[1]["status"], "waiting")
        self.assertEqual(self.occupancy_of(guest_cookie), {"code": code, "status": "waiting"})

        # (b) 重试成功：成功摘要与事实一致，查询状态随之更新。
        success = self.run_cli("close-room", code, confirmation=f"{code}\n")
        self.assertEqual(success.returncode, 0, success.stderr + success.stdout)
        backup_dir = backup_root / game_id
        closure_bytes = (backup_dir / "closure.json").read_bytes()
        closure = json.loads(closure_bytes.decode("utf-8"))
        self.assertEqual(set(closure["affectedPlayers"]), {"一致房主", "一致玩家"})
        self.assertEqual(closure["code"], code)
        self.assertEqual(self.request(f"/api/rooms/{code}")[0], 404)
        self.assertIsNone(self.occupancy_of(host_cookie))
        self.assertIsNone(self.occupancy_of(guest_cookie))
        users_listing = self.run_cli("users")
        for name in ("一致房主", "一致玩家"):
            line = self.lines_with(users_listing.stdout, name)[0]
            self.assertIn("（未占用）", line, f"成功关闭后 {name} 应显示未占用")
        rooms_listing = self.run_cli("rooms")
        self.assertFalse(self.lines_with(rooms_listing.stdout, code), "成功后查询不得再列出该房")
        self.assertTrue(self.lines_with(rooms_listing.stdout, code_other), "对照房不受影响")

        # (c) 工具箱计数与清理隔离：成功关闭后活动计数不含备份；清理只清
        # 活动存档，不动管理备份与账号。
        with mock.patch.object(test_toolkit, "SAVES_DIR", saves):
            self.assertEqual(test_toolkit.count_saved_rooms(), 1, "只剩对照房的活动存档")
            removed = test_toolkit.clear_saves()
        self.assertEqual(removed, 2, "只移除对照房的两个活动存档文件")
        self.assertEqual((backup_dir / "closure.json").read_bytes(), closure_bytes,
                         "工具箱清理不得改写管理备份")
        self.assertTrue((backup_dir / "game.json.gz").is_file(), "清理不得删管理备份")
        self.assertTrue((saves / "accounts" / "accounts.sqlite3").is_file(),
                        "清理不得删账号存储")
        self.assertEqual(self.request(f"/api/rooms/{code}")[0], 404, "清理后关闭房仍不复活")


if __name__ == "__main__":
    unittest.main()
