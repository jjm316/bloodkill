"""Ticket 21: admin close-room — preview, confirm, backup, then close one room.

Real uvicorn process + real CLI subprocess (``python -m server.admin
close-room <code>``) + real WebSocket connections. The CLI must show a
preview and require retyping the room code before the service backs the room
up into the isolated ``admin-backup/`` directory and closes it. A closed room
is not a normal endgame: no winner, no identity reveal, no rejoin, no replay,
no occupancy. Other rooms keep running.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import websockets

from tests import test_accounts as account_tests

REPO_ROOT = Path(__file__).resolve().parents[1]
_CLI_POOL = ThreadPoolExecutor(max_workers=1)


class AdminCloseRoomTests(unittest.TestCase):
    setUp = account_tests.RegistrationHTTPTests.setUp
    start_server = account_tests.RegistrationHTTPTests.start_server
    stop_server = account_tests.RegistrationHTTPTests.stop_server
    request = account_tests.RegistrationHTTPTests.request
    register = account_tests.RegistrationHTTPTests.register

    def signup(self, name, password="123456"):
        status, body, headers = self.register(name, password)
        self.assertEqual(status, 201)
        return body["account"], headers["Set-Cookie"].split(";", 1)[0]

    def create_room(self, cookie):
        status, room, _ = self.request("/api/rooms", {}, cookie)
        self.assertEqual(status, 200)
        return room["code"], room["gameId"]

    def connect(self, code, cookie, mode="player"):
        return websockets.connect(f"ws://127.0.0.1:{self.port}/ws/{code}", additional_headers={"Cookie": cookie}, proxy=None)

    async def hello(self, socket, **fields):
        await socket.send(json.dumps({"type": "hello", "mode": "player", "protocolVersion": "4", **fields}))
        return json.loads(await asyncio.wait_for(socket.recv(), 3))

    async def state_of(self, code, cookie, **fields):
        async with self.connect(code, cookie) as socket:
            return await self.hello(socket, **fields)

    async def fill_and_start(self, code, host_cookie, total, prefix, start_payload=None):
        """Join accounts until the room holds `total` seats, then start via the host.

        Returns the final state broadcast and the newcomers' cookies."""
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

    # ---- CLI 子进程辅助 ----------------------------------------------------

    def run_cli_in(self, saves_dir, *arguments, confirmation=None, timeout=180):
        """Run the real CLI subprocess; `confirmation` feeds its stdin prompt."""
        command = [sys.executable, "-m", "server.admin", *map(str, arguments)]
        if saves_dir is not None:
            command += ["--saves-dir", str(saves_dir)]
        environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        return subprocess.run(command, cwd=str(REPO_ROOT), env=environment,
                              capture_output=True, text=True, encoding="utf-8",
                              input=None if confirmation is None else confirmation,
                              timeout=timeout)

    def run_cli(self, *arguments, confirmation=None):
        return self.run_cli_in(self.tmp.name, *arguments, confirmation=confirmation)

    async def run_cli_online(self, *arguments, confirmation=None):
        """Run the CLI while this coroutine's event loop keeps serving WS traffic."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_CLI_POOL, partial(self.run_cli, *arguments, confirmation=confirmation))

    def lines_with(self, output, needle):
        return [line for line in output.splitlines() if needle in line]

    # ---- 管理端口直连辅助 --------------------------------------------------

    def admin_port(self):
        installation = json.loads(
            (Path(self.tmp.name) / "admin" / "installation.json").read_text(encoding="utf-8"))
        return installation["adminPort"]

    def admin_token(self):
        return (Path(self.tmp.name) / "admin" / "admin-token").read_text(encoding="utf-8").strip()

    def admin_http(self, path, token=None, cookie=None, extra_headers=None, method="GET", data=None):
        import urllib.error
        import urllib.request
        headers = dict(extra_headers or {})
        if token is not None:
            headers["X-Admin-Token"] = token
        if cookie is not None:
            headers["Cookie"] = cookie
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

    def occupancy_of(self, cookie):
        return self.request("/api/account/room", cookie=cookie)[1]["room"]

    async def expect_close_notice(self, socket):
        """被关闭房间的连接必须收到中文终止帧并被服务端关闭。

        关闭前排队的正常帧（如 state 广播）先排空；随后必须是关闭终止帧，
        不允许出现任何新的对局推进（事件/命令确认）。
        """
        deadline = asyncio.get_running_loop().time() + 5
        message = None
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            self.assertGreater(remaining, 0, "关闭通知超时未到达")
            message = json.loads(await asyncio.wait_for(socket.recv(), remaining))
            if message.get("type") == "error":
                break
            self.assertIn(message.get("type"), ("state",),
                          f"关闭后不得再收到对局推进帧：{message}")
        self.assertEqual(message.get("code"), "room.admin-closed", message)
        self.assertIn("管理员", message.get("message", ""))
        with self.assertRaises(websockets.exceptions.ConnectionClosed):
            await asyncio.wait_for(socket.recv(), 5)

    # ---- V15.01 ------------------------------------------------------------

    def test_v15_01_real_cli_closes_waiting_and_playing_rooms(self):
        """V15.01: close a waiting room and a playing room through the real CLI;
        every member connection gets the Chinese close notice, occupancy is
        released, and the closed rooms cannot be rejoined or replayed."""
        from blood_bound import load_game

        # -- 等待房：2 名玩家保持真实 WS 在线 --
        host_account, host_cookie = self.signup("关闭房主")
        code_waiting, game_waiting = self.create_room(host_cookie)
        guest_account, guest_cookie = self.signup("关闭玩家")

        # -- 进行房：6 名账号真实开局 --
        play_host_account, play_cookie = self.signup("进行关闭房主")
        code_playing, game_playing = self.create_room(play_cookie)

        async def scenario():
            guest_socket = await self.connect(code_waiting, guest_cookie)
            host_socket = await self.connect(code_waiting, host_cookie)
            host_state = await self.hello(host_socket)
            await self.hello(guest_socket)

            # 没有房主解散按钮：等待房可用的房主动作只有开始/锁定。
            self.assertTrue({action["type"] for action in host_state["hostActions"]}
                            <= {"start-game", "lock", "unlock"},
                            "房主不得拥有解散房间的按钮")

            started, member_cookies = await self.fill_and_start(
                code_playing, play_cookie, 6, "进行关闭成员")
            self.assertEqual(started["roomStatus"], "playing")
            play_sockets = []
            for cookie in member_cookies:
                socket = await self.connect(code_playing, cookie)
                await self.hello(socket)
                play_sockets.append(socket)
            play_host_socket = await self.connect(code_playing, play_cookie)

            # 关闭前占用在案。
            self.assertEqual(self.occupancy_of(host_cookie), {"code": code_waiting, "status": "waiting"})
            self.assertEqual(self.occupancy_of(member_cookies[0]), {"code": code_playing, "status": "playing"})

            waiting_close = await self.run_cli_online("close-room", code_waiting,
                                                      confirmation=f"{code_waiting}\n")
            # 等待房两条连接都收到中文关闭通知并被断开。
            await self.expect_close_notice(guest_socket)
            await self.expect_close_notice(host_socket)
            await guest_socket.close()
            await host_socket.close()

            playing_close = await self.run_cli_online("close-room", code_playing,
                                                      confirmation=f"{code_playing}\n")
            await self.expect_close_notice(play_host_socket)
            for socket in play_sockets:
                await self.expect_close_notice(socket)
            await play_host_socket.close()
            for socket in play_sockets:
                await socket.close()
            return waiting_close, playing_close, member_cookies

        waiting_close, playing_close, member_cookies = asyncio.run(scenario())

        # -- CLI 输出与退出码：预览 + 确认 + 成功摘要（房号/受影响玩家/备份绝对路径） --
        for result, code, game_id, affected in (
            (waiting_close, code_waiting, game_waiting, ["关闭房主", "关闭玩家"]),
            (playing_close, code_playing, game_playing,
             ["进行关闭房主"] + [f"进行关闭成员{index}" for index in range(5)]),
        ):
            with self.subTest(room=code):
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertIn(f"房间 {code}", result.stdout)
                for name in affected:
                    self.assertTrue(self.lines_with(result.stdout, name),
                                    f"成功输出必须列出受影响玩家 {name}")
                backup_lines = self.lines_with(result.stdout, "备份")
                self.assertTrue(backup_lines, "成功输出必须说明备份位置")
                backup_line = backup_lines[-1]
                backup_path = Path(backup_line.split("：", 1)[1].strip())
                self.assertTrue(backup_path.is_absolute(), "备份位置必须是绝对路径")
                self.assertIn("admin-backup", backup_path.parts)
                self.assertTrue(backup_path.exists(), f"备份目录必须真实存在：{backup_path}")
                # 备份事实：游戏存档、元数据与关闭记录都在隔离目录里。
                self.assertTrue((backup_path / "game.json.gz").is_file())
                self.assertTrue((backup_path / "meta.json").is_file())
                closure = json.loads((backup_path / "closure.json").read_text(encoding="utf-8"))
                self.assertEqual(closure["code"], code)
                self.assertEqual(closure["gameId"], game_id)
                self.assertFalse(closure.get("result"), "管理关闭不得伪造胜负结果")
                # 备份存档可读取，且不是正常终局。
                engine = load_game(backup_path / "game.json.gz")
                self.assertNotEqual(engine.state.status, "ended", "关闭不是正常终局")

        # -- 活动目录不再保留被关房的存档（单房清理，不是清空整个目录） --
        saves = Path(self.tmp.name)
        self.assertFalse(list(saves.glob(f"{game_waiting}.*")), "被关房的活动存档必须移出存档目录")
        self.assertFalse(list(saves.glob(f"{game_playing}.*")), "被关房的活动存档必须移出存档目录")

        # -- 占用释放：全员可开新房 --
        for name, cookie in [("关闭房主", host_cookie), ("关闭玩家", guest_cookie),
                             ("进行关闭房主", play_cookie), ("进行关闭成员", member_cookies[0])]:
            with self.subTest(release=name):
                self.assertIsNone(self.occupancy_of(cookie))
                status, room, _ = self.request("/api/rooms", {}, cookie)
                self.assertEqual(status, 200, f"被关房玩家必须能创建新房：{room}")

        # -- 被关房不能重新加入，也不能在线回放 --
        for code in (code_waiting, code_playing):
            with self.subTest(closed(code)):
                self.assertEqual(self.request(f"/api/rooms/{code}")[0], 404)
                status, body, _ = self.request(f"/api/rooms/{code}/replay", None, host_cookie)
                self.assertEqual(status, 404, body)

        # -- 被断开的玩家重连同一房间也被拒绝（房已不存在） --
        async def rejoin_rejected():
            socket = await self.connect(code_waiting, guest_cookie)
            message = json.loads(await asyncio.wait_for(socket.recv(), 3))
            await socket.close()
            return message
        message = asyncio.run(rejoin_rejected())
        self.assertEqual(message.get("code"), "room.not-found", message)


    # ---- V15.02 ------------------------------------------------------------

    def test_v15_02_other_playing_room_keeps_running_after_close(self):
        """V15.02: with a second playing room holding a real decision window,
        closing the target leaves the control room fully operable: same
        revision, same countdown deadline, legal action accepted, occupancy
        and active save file untouched."""
        from pathlib import Path

        target_host_account, target_cookie = self.signup("弃局房主")
        code_target, game_target = self.create_room(target_cookie)

        control_host_account, control_cookie = self.signup("对照房主")
        code_control, game_control = self.create_room(control_cookie)

        async def scenario():
            await self.fill_and_start(code_target, target_cookie, 6, "弃局成员")
            control_member_cookies = (await self.fill_and_start(
                code_control, control_cookie, 6, "对照成员"))[1]

            # 对照房真实攻击一次，进入干涉三段窗口（真实决策倒计时）。
            control_cookie_sockets = [control_cookie, *control_member_cookies]
            pending_state = None
            for cookie in control_cookie_sockets:
                async with self.connect(code_control, cookie) as socket:
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
                            pending_state = message
                            break
                    break
            self.assertIsNotNone(pending_state, "对照房未能推进到决策窗口")
            pending_before = pending_state["game"]["pending"]
            revision_before = pending_state["game"]["revision"]

            # 对照房保持一条真实连接在线，跨越目标房的关闭时刻。
            holder_socket = await self.connect(code_control, control_cookie)
            await self.hello(holder_socket)

            target_close = await self.run_cli_online("close-room", code_target,
                                                     confirmation=f"{code_target}\n")

            # 关闭后：对照房同连接仍收到自己的状态广播（重读 state）。
            await holder_socket.send(json.dumps({"type": "host", "action": "unlock"}))
            refreshed = None
            while True:
                message = json.loads(await asyncio.wait_for(holder_socket.recv(), 5))
                if message.get("type") == "state":
                    refreshed = message
                    break
                if message.get("type") == "error":
                    raise AssertionError(message)
            # 计时器未改变：窗口种类/阶段与截止时间戳保持原样。
            pending_after = refreshed["game"]["pending"]
            self.assertEqual(pending_after["kind"], pending_before["kind"])
            self.assertEqual(pending_after.get("stage"), pending_before.get("stage"))
            self.assertEqual(pending_after["deadline"], pending_before["deadline"])

            # 合法操作仍被接受：当事人应答干涉请求（gate 窗口的合法动作）。
            answered = False
            for cookie in control_cookie_sockets:
                async with self.connect(code_control, cookie) as socket:
                    state = await self.hello(socket)
                    self.assertEqual(state["roomStatus"], "playing")
                    self.assertEqual(state["game"]["revision"], revision_before)
                    answers = [action for action in state["game"]["legalActions"]
                               if action["type"] == "answer-intervention-request"]
                    if not answers:
                        continue
                    await socket.send(json.dumps({
                        "type": "command", "command": "answer-intervention-request",
                        "payload": {"need": True},
                        "commandId": "v15-02-control-answer",
                        "expectedRevision": state["game"]["revision"],
                    }))
                    while True:
                        message = json.loads(await asyncio.wait_for(socket.recv(), 5))
                        if (message.get("type") == "ack"
                                and message.get("commandId") == "v15-02-control-answer"):
                            self.assertEqual(message["status"], "accepted", message)
                            answered = True
                            break
                    break
            self.assertTrue(answered, "对照房当事人在目标房关闭后必须仍能完成合法操作")
            await holder_socket.close()
            return target_close

        target_close = asyncio.run(scenario())
        self.assertEqual(target_close.returncode, 0, target_close.stderr + target_close.stdout)

        # 占用与活动存档不变；CLI rooms 仍列出对照房。
        self.assertEqual(self.occupancy_of(control_cookie),
                         {"code": code_control, "status": "playing"})
        saves = Path(self.tmp.name)
        self.assertTrue((saves / f"{game_control}.json.gz").is_file(), "对照房活动存档必须保留")
        self.assertFalse(list(saves.glob(f"{game_target}.*")), "目标房活动存档必须移出")
        rooms_listing = self.run_cli("rooms")
        self.assertEqual(rooms_listing.returncode, 0, rooms_listing.stderr)
        self.assertTrue(self.lines_with(rooms_listing.stdout, code_control),
                        "关闭目标后 rooms 仍必须列出对照房")
        self.assertFalse(self.lines_with(rooms_listing.stdout, code_target),
                         "已关闭的目标房不得再出现在 rooms 列表中")


    # ---- V15.03 ------------------------------------------------------------

    def test_v15_03_confirmation_and_negative_cases_never_close_wrong_target(self):
        """V15.03: wrong-code confirmation, cancellation, unknown code, an ended
        room, a target that changed after preview, credential failures and a
        stale retry must all refuse in Chinese with a non-zero status — and
        never touch the target or the neighbouring room."""
        from scripts.account_client import AccountClient
        from scripts.release_smoke import websocket_smoke

        host_account, host_cookie = self.signup("反例房主")
        code, game_id = self.create_room(host_cookie)
        guest_account, guest_cookie = self.signup("反例玩家")

        neighbour_account, neighbour_cookie = self.signup("相邻房主")
        code_neighbour, game_neighbour = self.create_room(neighbour_cookie)

        # 目标房 2 名玩家在线，随时可验证“仍然可用”。
        async def target_still_usable():
            state = await self.state_of(code, host_cookie)
            self.assertEqual(state["roomStatus"], "waiting")
            self.assertEqual(self.occupancy_of(host_cookie), {"code": code, "status": "waiting"})
        asyncio.run(target_still_usable())

        # (a) 错误房号确认：不关闭、中文说明、非零退出。
        wrong = self.run_cli("close-room", code, confirmation="000000\n")
        self.assertNotEqual(wrong.returncode, 0)
        self.assertIn("已取消", wrong.stderr)
        self.assertIn(code, wrong.stderr)
        asyncio.run(target_still_usable())

        # (b) 直接回车取消（EOF 同路径）。
        empty = self.run_cli("close-room", code, confirmation="\n")
        self.assertNotEqual(empty.returncode, 0)
        self.assertIn("已取消", empty.stderr)
        asyncio.run(target_still_usable())

        # (c) 不存在的房号：预览即拒绝。
        unknown = self.run_cli("close-room", "654321", confirmation="654321\n")
        self.assertNotEqual(unknown.returncode, 0)
        self.assertIn("654321", unknown.stderr)
        self.assertIn("不存在", unknown.stderr)
        self.assertFalse(self.lines_with(unknown.stdout, "已关闭"))

        # (d) 预览后目标变化：开局使状态与修订号同时前进，用预览时记下的
        # 确认信息提交 → 拒绝且房间照常（API 层防线；CLI 每次运行都会重新
        # 预览，因此该防线保护的是持有旧确认信息的任何重试方）。
        token = self.admin_token()
        preview = self.admin_http(f"/admin/close-room/preview?code={code}", token=token)
        self.assertEqual(preview[0], 200)
        self.assertEqual(preview[1]["status"], "waiting")
        asyncio.run(self.fill_and_start(code, host_cookie, 6, "反例补位"))
        stale_after_start = self.admin_http(
            "/admin/close-room", token=token, method="POST",
            data={"code": code, "expectedGameId": preview[1]["gameId"],
                  "expectedRevision": preview[1]["revision"]})
        self.assertEqual(stale_after_start[0], 409, stale_after_start[1])
        self.assertEqual(stale_after_start[1]["error"], "admin.target-changed")
        self.assertIn("已发生变化", stale_after_start[1]["message"])
        state = asyncio.run(self.state_of(code, host_cookie))
        self.assertEqual(state["roomStatus"], "playing", "目标变化后确认必须被拒绝且房间照常")

        # (e) 同房正常终局竞争：预览后真实打完整局，旧确认与重新预览都拒绝。
        base = f"http://127.0.0.1:{self.port}"
        sessions = [AccountClient(base).register_test_account() for _ in range(7)]
        status, ended_room = sessions[0].request("/api/rooms", "POST", {})
        self.assertEqual(status, 200)
        code_ended = ended_room["code"]
        final = asyncio.run(websocket_smoke(base, ended_room, sessions))
        self.assertEqual(final["status"], "ended")
        retry_after_end = self.run_cli("close-room", code_ended, confirmation=f"{code_ended}\n")
        self.assertNotEqual(retry_after_end.returncode, 0)
        self.assertIn("已正常结束", retry_after_end.stderr)
        # 终局房回放照常可读，未被清理或误关。
        status, replay = sessions[1].request(f"/api/rooms/{code_ended}/replay")
        self.assertEqual(status, 200, replay)

        # (f) 权限反例：管理端点的预览与确认都要求独立管理凭证。
        for path, kwargs in (
            (f"/admin/close-room/preview?code={code}", {}),
            (f"/admin/close-room/preview?code={code}", {"token": "wrong-admin-token"}),
            (f"/admin/close-room/preview?code={code}", {"cookie": host_cookie}),
            ("/admin/close-room", {"method": "POST", "data": {"code": code}}),
            ("/admin/close-room", {"method": "POST", "data": {"code": code}, "token": "wrong"}),
            ("/admin/close-room", {"method": "POST", "data": {"code": code}, "cookie": host_cookie}),
        ):
            with self.subTest(permission=path):
                status_code, body = self.admin_http(path, **kwargs)
                self.assertEqual(status_code, 401, body)
        # 公网入口没有管理路由：带正确凭证也不能从公网关闭房间。
        self.assertEqual(self.public_http(
            "/admin/close-room", {"X-Admin-Token": token})[0], 404)

        # (g) 真正关闭目标后，用关闭前的旧确认信息再提交：明确报告已关闭，
        # 而非笼统不存在；也绝不能误当作新目标处理。
        first = self.run_cli("close-room", code, confirmation=f"{code}\n")
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        stale_after_close = self.admin_http(
            "/admin/close-room", token=token, method="POST",
            data={"code": code, "expectedGameId": preview[1]["gameId"],
                  "expectedRevision": preview[1]["revision"]})
        self.assertEqual(stale_after_close[0], 409, stale_after_close[1])
        self.assertEqual(stale_after_close[1]["error"], "room.admin-closed")
        backup_path = self.lines_with(first.stdout, "备份")[-1].split("：", 1)[1].strip()
        self.assertEqual(stale_after_close[1]["details"].get("backupPath"), backup_path)

        # (h) CLI 重复处理同一已关房号：中文明确报告已关闭。
        repeat = self.run_cli("close-room", code, confirmation=f"{code}\n")
        self.assertNotEqual(repeat.returncode, 0)
        self.assertIn("被管理关闭", repeat.stderr)
        self.assertIn("无需重复处理", repeat.stderr)
        repeat_record = self.admin_http(f"/admin/close-room/preview?code={code}", token=token)
        self.assertEqual(repeat_record[0], 409)
        self.assertEqual(repeat_record[1]["details"].get("backupPath"), backup_path)

        # 相邻房间自始至终未受影响。
        self.assertEqual(self.request(f"/api/rooms/{code_neighbour}")[1]["status"], "waiting")
        self.assertEqual(self.occupancy_of(neighbour_cookie),
                         {"code": code_neighbour, "status": "waiting"})
        from pathlib import Path
        self.assertTrue((Path(self.tmp.name) / f"{game_neighbour}.json.gz").is_file())


    # ---- V15.04 ------------------------------------------------------------

    def test_v15_04_backup_failures_keep_room_available_and_backup_replays(self):
        """V15.04: an unwritable backup root, an interrupted backup write and a
        failure after backup-but-before-commit each refuse loudly and leave the
        room usable and occupied; a successful backup replays up to the exact
        pre-close revision with no private facts."""
        import os as os_module
        from blood_bound import ReplayPlayer, create_save_document, load_game, project_state
        from scripts.release_smoke import check_private_fields

        host_account, host_cookie = self.signup("注入房主")
        code, game_id = self.create_room(host_cookie)
        neighbour_account, neighbour_cookie = self.signup("注入相邻房主")
        code_neighbour, game_neighbour = self.create_room(neighbour_cookie)

        saves = Path(self.tmp.name)
        backup_root = saves / "admin-backup"
        backup_dir = backup_root / game_id
        active_meta = saves / f"{game_id}.meta.json"
        active_save = saves / f"{game_id}.json.gz"

        async def room_still_usable():
            """读路径可用 + 占用在 + 一条合法操作被接受。"""
            state = await self.state_of(code, host_cookie)
            self.assertEqual(state["roomStatus"], "playing")
            self.assertEqual(self.occupancy_of(host_cookie), {"code": code, "status": "playing"})
            return state

        probe_counter = iter(range(1000))

        async def legal_action_accepted(room_cookies):
            """任一玩家完成一条合法操作，证明进行房完全可用（动作视图按人投影）。"""
            for cookie in room_cookies:
                async with self.connect(code, cookie) as socket:
                    state = await self.hello(socket)
                    actions = [action for action in state["game"]["legalActions"]
                               if action["type"] in ("pass-dagger", "attack",
                                                     "answer-intervention-request")]
                    if not actions:
                        continue
                    action = actions[0]
                    command_id = f"v15-04-probe-{next(probe_counter)}"
                    await socket.send(json.dumps({
                        "type": "command", "command": action["type"],
                        "payload": {key: value for key, value in action.items() if key != "type"},
                        "commandId": command_id, "expectedRevision": state["game"]["revision"],
                    }))
                    while True:
                        message = json.loads(await asyncio.wait_for(socket.recv(), 5))
                        if (message.get("type") == "ack" and message.get("commandId") == command_id):
                            if message.get("status") != "accepted":
                                self.fail(f"合法操作被拒绝：{json.dumps(message, ensure_ascii=False)}")
                            return message
            self.fail("进行房没有任何玩家可完成合法操作")

        async def scenario():
            _, member_cookies = await self.fill_and_start(code, host_cookie, 6, "注入成员")
            room_cookies = [host_cookie, *member_cookies]
            state = await room_still_usable()
            revision_before = state["game"]["revision"]

            # (1) 备份根目录不可写：用同名文件占位。
            backup_root.write_text("占位文件，不是目录", encoding="utf-8")
            unwritable = await self.run_cli_online("close-room", code, confirmation=f"{code}\n")
            await room_still_usable()
            backup_root.unlink()

            # (2) 写入中断：备份目标被同名目录占位，第一份复制就失败。
            backup_dir.mkdir(parents=True)
            (backup_dir / "game.json.gz").mkdir()
            interrupted = await self.run_cli_online("close-room", code, confirmation=f"{code}\n")
            await room_still_usable()
            import shutil
            shutil.rmtree(backup_dir)

            # (3) 备份完成但关闭未提交：活动 meta 设为只读，移出存档一步失败。
            ack = await legal_action_accepted(room_cookies)
            self.assertEqual(ack["status"], "accepted", ack)
            revision_before = ack["revision"]
            os_module.chmod(active_meta, 0o444)
            uncommitted = await self.run_cli_online("close-room", code, confirmation=f"{code}\n")
            after_failure = await room_still_usable()
            self.assertEqual(after_failure["game"]["revision"], revision_before,
                             "关闭未提交时房间状态不得被改动")
            # 失败期间活动存档始终原样（备份失败/关闭未提交都不得动它）。
            self.assertTrue(active_save.is_file() and active_meta.is_file(),
                            "关闭未提交时活动存档必须保留在存档目录")
            os_module.chmod(active_meta, 0o666)
            ack2 = await legal_action_accepted(room_cookies)
            self.assertEqual(ack2["status"], "accepted", "还原注入后房间必须完全可用")

            # (4) 一切正常后重试关闭成功（同一备份目录被整目录重写）。
            success = await self.run_cli_online("close-room", code, confirmation=f"{code}\n")
            return unwritable, interrupted, uncommitted, success, ack2["revision"]

        unwritable, interrupted, uncommitted, success, revision_at_close = asyncio.run(scenario())

        # -- 失败分支：中文原因、非零退出、绝不静默报成功 --
        for label, result in (("目录不可写", unwritable), ("写入中断", interrupted)):
            with self.subTest(failure=label):
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("备份失败", result.stderr)
                self.assertFalse(self.lines_with(result.stdout, "已关闭"),
                                 f"{label}时不得输出成功摘要")
        self.assertNotEqual(uncommitted.returncode, 0, uncommitted.stdout + uncommitted.stderr)
        self.assertIn("关闭未完成", uncommitted.stderr)
        self.assertFalse(self.lines_with(uncommitted.stdout, "已关闭"))

        # -- 成功分支：退出 0，备份三件套齐备 --
        self.assertEqual(success.returncode, 0, success.stderr + success.stdout)
        for name in ("game.json.gz", "meta.json", "closure.json"):
            self.assertTrue((backup_dir / name).is_file(), f"备份缺少 {name}")

        # -- 备份可读取并重放到关闭前事实 --
        engine = load_game(backup_dir / "game.json.gz")
        self.assertEqual(engine.state.revision, revision_at_close,
                         "备份必须停在关闭那一刻的修订号")
        self.assertNotEqual(engine.state.status, "ended", "管理关闭不得把对局写成正常终局")
        player = ReplayPlayer(create_save_document(engine))
        steps = []
        while player.step() is not None:
            steps.append(project_state(player.engine.state, None))
        self.assertTrue(steps, "备份必须可重放出公开步骤")
        revisions = [step["revision"] for step in steps]
        self.assertEqual(revisions, sorted(revisions), "重放修订号必须单调")
        for step in steps:
            self.assertNotEqual(step["status"], "ended")
            self.assertFalse(step.get("result"), "重放中不得出现胜负结果")
            check_private_fields(step)
        # 归属记录：备份 meta 的座位归属与关闭前一致。
        meta = json.loads((backup_dir / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(len(meta["seatAccounts"]), 6, "备份必须保存全部座位归属记录")

        # -- 相邻房间从头到尾未受影响 --
        self.assertEqual(self.occupancy_of(neighbour_cookie),
                         {"code": code_neighbour, "status": "waiting"})
        self.assertTrue((saves / f"{game_neighbour}.json.gz").is_file())


    # ---- V15.05 ------------------------------------------------------------

    def test_v15_05_deadline_passes_after_close_and_restart_does_not_restore(self):
        """V15.05: with a real decision window armed, closing the room cancels
        the countdown — after the original deadline passes there is no late
        timeout command, broadcast or rebuilt active file, no fabricated
        result or identity reveal; a real restart does not restore the room
        or its occupancy."""
        import time as time_module
        from blood_bound import ReplayPlayer, create_save_document, load_game, project_state
        from scripts.release_smoke import check_private_fields

        host_account, host_cookie = self.signup("倒计时房主")
        code, game_id = self.create_room(host_cookie)
        saves = Path(self.tmp.name)
        backup_dir = saves / "admin-backup" / game_id

        async def scenario():
            started, member_cookies = await self.fill_and_start(
                code, host_cookie, 6, "倒计时成员",
                start_payload={"interventionTimeoutSeconds": 30})
            self.assertEqual(started["game"]["interventionTimeoutSeconds"], 30)

            # 真实攻击进入干涉请求（gate）窗口：真实决策倒计时开始计时。
            pending_state = None
            for cookie in [host_cookie, *member_cookies]:
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
                            pending_state = message
                            break
                    break
            self.assertIsNotNone(pending_state, "未能进入真实决策窗口")
            pending = pending_state["game"]["pending"]
            self.assertEqual((pending["kind"], pending.get("stage")), ("intervention", "gate"))
            deadline = pending["deadline"]
            self.assertIsNotNone(deadline, "决策窗口必须带真实截止时间")
            revision_at_close = pending_state["game"]["revision"]

            # 窗口开着、玩家在线时关闭房间。
            sockets = [await self.connect(code, cookie) for cookie in [host_cookie, *member_cookies]]
            for socket in sockets:
                await self.hello(socket)
            result = await self.run_cli_online("close-room", code, confirmation=f"{code}\n")
            for socket in sockets:
                await self.expect_close_notice(socket)
                await socket.close()

            # 原倒计时截止后再等 2 秒：迟到超时不得发生。
            remaining = deadline - time_module.time() + 2.0
            if remaining > 0:
                await asyncio.sleep(remaining)
            else:
                await asyncio.sleep(0.5)
            return result, revision_at_close

        result, revision_at_close = asyncio.run(scenario())
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

        # 无迟到动作：备份停在关闭那一刻，截止时间过后 revision 未被超时命令推进。
        engine = load_game(backup_dir / "game.json.gz")
        self.assertEqual(engine.state.revision, revision_at_close,
                         "原截止已过，迟到的超时命令不得再推进对局")
        self.assertIsNotNone(engine.state.pending, "关闭不清空引擎窗口（引擎无墙钟）")
        self.assertNotEqual(engine.state.status, "ended")

        # 无迟到广播/文件重建：活动存档目录没有任何该房文件。
        self.assertFalse(list(saves.glob(f"{game_id}.*")),
                         "倒计时截止后不得重建活动存档文件")

        # 没有伪造结果或身份揭晓：旁观投影逐步检查。
        player = ReplayPlayer(create_save_document(engine))
        steps = []
        while player.step() is not None:
            steps.append(project_state(player.engine.state, None))
        for step in steps:
            self.assertNotEqual(step["status"], "ended")
            self.assertFalse(step.get("result"))
            for entry in step["players"]:
                self.assertNotIn("identity", entry, "管理关闭不得公开任何隐藏身份")
            check_private_fields(step)

        # ---- 真实进程重启：被关房不得恢复、不得重新占用 ----
        self.stop_server()
        self.start_server()
        self.assertEqual(self.request("/health")[0], 200)
        self.assertEqual(self.request(f"/api/rooms/{code}")[0], 404, "重启不得恢复被关房")
        self.assertIsNone(self.occupancy_of(host_cookie), "重启不得重新占用被关房玩家")
        status, room, _ = self.request("/api/rooms", {}, host_cookie)
        self.assertEqual(status, 200, "重启后被关房玩家必须仍能开新房")
        code_new = room["code"]
        status, replay_body, _ = self.request(f"/api/rooms/{code}/replay", None, host_cookie)
        self.assertEqual(status, 404, "被关房重启后仍不能在线回放")

        # 重启后重新查询关闭事实：重复处理报告保持，备份原样。
        repeat = self.run_cli("close-room", code, confirmation=f"{code}\n")
        self.assertNotEqual(repeat.returncode, 0)
        self.assertIn("被管理关闭", repeat.stderr)
        self.assertTrue((backup_dir / "game.json.gz").is_file(), "重启不得动管理备份")
        closure = json.loads((backup_dir / "closure.json").read_text(encoding="utf-8"))
        self.assertEqual(closure["gameId"], game_id)
        # 新房照常（与被关房互不影响）。
        self.assertEqual(self.request(f"/api/rooms/{code_new}")[1]["status"], "waiting")


def closed(code):
    return f"closed-room-{code}"
