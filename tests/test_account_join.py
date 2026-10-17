"""Ticket 10: joining by room code and resuming the account-bound seat.

Real uvicorn/HTTP/WS boundary (same isolated fixtures as 09): a player joins a
waiting room with the six-digit code and claims the seat bound to the current
account; the same account on a second device session resumes that seat (locked
or after start) with its private projection intact.
"""

import asyncio
import json
import unittest

import websockets

from tests import test_accounts as account_tests


class AccountJoinHTTPTests(unittest.TestCase):
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
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def create_room(self, cookie):
        status, room, _ = self.request("/api/rooms", {}, cookie)
        self.assertEqual(status, 200)
        return room["code"]

    def connect(self, code, cookie):
        return websockets.connect(f"ws://127.0.0.1:{self.port}/ws/{code}", additional_headers={"Cookie": cookie}, proxy=None)

    async def hello(self, socket, **fields):
        await socket.send(json.dumps({"type": "hello", "mode": "player", "protocolVersion": "4", **fields}))
        return json.loads(await asyncio.wait_for(socket.recv(), 3))

    async def state_of(self, code, cookie, **fields):
        async with self.connect(code, cookie) as socket:
            return await self.hello(socket, **fields)

    async def fill_to(self, code, host_cookie, total, prefix):
        """Join extra accounts until the room holds `total` seats, then start via the host."""
        current = self.request(f"/api/rooms/{code}", None, host_cookie)[1]["playerCount"]
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

    def test_same_account_second_session_resumes_waiting_seat_without_duplicate_player(self):
        host_account, host_cookie = self.signup("恢复房主")
        code = self.create_room(host_cookie)
        account, first_cookie = self.signup("恢复玩家")
        first = asyncio.run(self.state_of(code, first_cookie))
        self.assertFalse(first["isHost"])
        self.assertEqual([p["displayName"] for p in first["game"]["players"]], [host_account["username"], account["username"]])
        second_cookie = self.login("恢复玩家")
        self.assertNotEqual(second_cookie, first_cookie)
        second = asyncio.run(self.state_of(code, second_cookie))
        self.assertEqual(second["yourPlayerId"], first["yourPlayerId"])
        self.assertEqual(len(second["game"]["players"]), 2)
        self.assertEqual(
            self.request(f"/api/rooms/{code}", None, host_cookie)[1]["playerCount"], 2,
            "同账号第二会话恢复不能生成重复玩家座位",
        )

    async def rejection_of(self, code, cookie, **fields):
        """A refused hello must land an error frame with a Chinese reason."""
        async with self.connect(code, cookie) as socket:
            await socket.send(json.dumps({"type": "hello", "mode": "player", "protocolVersion": "4", **fields}))
            return json.loads(await asyncio.wait_for(socket.recv(), 3))

    def occupancy_of(self, cookie):
        return self.request("/api/account/room", cookie=cookie)[1]["room"]

    def test_locked_waiting_room_keeps_owner_resume_but_rejects_newcomer_with_reason(self):
        _, host_cookie = self.signup("锁房房主")
        code = self.create_room(host_cookie)
        _, member_cookie = self.signup("锁房老成员")
        member = asyncio.run(self.state_of(code, member_cookie))

        async def lock_room():
            async with self.connect(code, host_cookie) as socket:
                await self.hello(socket)
                await socket.send(json.dumps({"type": "host", "action": "lock"}))
                while True:
                    message = json.loads(await asyncio.wait_for(socket.recv(), 3))
                    if message.get("type") == "state" and message["locked"]:
                        return
        asyncio.run(lock_room())
        resumed = asyncio.run(self.state_of(code, member_cookie))
        self.assertEqual(resumed["yourPlayerId"], member["yourPlayerId"], "锁房后本人必须能恢复自己的座位")
        _, newcomer_cookie = self.signup("锁房新人")
        rejection = asyncio.run(self.rejection_of(code, newcomer_cookie))
        self.assertEqual(rejection["type"], "error")
        self.assertEqual(rejection["code"], "room.locked")
        self.assertIn("锁定", rejection["message"], "拒绝原因必须是简体中文")
        self.assertIsNone(self.occupancy_of(newcomer_cookie), "被拒新人不能残留幽灵座位占用")
        self.assertEqual(self.request(f"/api/rooms/{code}", None, host_cookie)[1]["playerCount"], 2)

    def test_started_room_rejects_newcomer_with_chinese_reason_and_no_ghost_seat(self):
        _, host_cookie = self.signup("开局拒客房主")
        code = self.create_room(host_cookie)
        started = asyncio.run(self.fill_to(code, host_cookie, 6, "拒客补位"))
        self.assertEqual(started["roomStatus"], "playing")
        _, newcomer_cookie = self.signup("开局拒客新人")
        rejection = asyncio.run(self.rejection_of(code, newcomer_cookie))
        self.assertEqual(rejection["type"], "error")
        self.assertEqual(rejection["code"], "room.already-started")
        self.assertIn("开始", rejection["message"], "拒绝原因必须是简体中文")
        self.assertIsNone(self.occupancy_of(newcomer_cookie))
        self.assertEqual(self.request(f"/api/rooms/{code}", None, host_cookie)[1]["playerCount"], 6)

    def test_full_room_rejects_newcomer_with_reason_and_no_ghost_seat(self):
        _, host_cookie = self.signup("满员房主")
        code = self.create_room(host_cookie)
        for index in range(11):
            _, cookie = self.signup(f"满员成员{index}")
            asyncio.run(self.state_of(code, cookie))
        self.assertEqual(self.request(f"/api/rooms/{code}", None, host_cookie)[1]["playerCount"], 12)
        _, newcomer_cookie = self.signup("满员新人")
        rejection = asyncio.run(self.rejection_of(code, newcomer_cookie))
        self.assertEqual(rejection["type"], "error")
        self.assertEqual(rejection["code"], "room.full", "满员必须给出明确的满员原因")
        self.assertIn("满", rejection["message"])
        self.assertIsNone(self.occupancy_of(newcomer_cookie))
        self.assertEqual(self.request(f"/api/rooms/{code}", None, host_cookie)[1]["playerCount"], 12)

    def test_ended_room_rejects_newcomer_with_reason_and_no_ghost_seat(self):
        from scripts.account_client import AccountClient
        from scripts.release_smoke import websocket_smoke
        base = f"http://127.0.0.1:{self.port}"
        sessions = [AccountClient(base).register_test_account() for _ in range(7)]
        status, room = sessions[0].request("/api/rooms", "POST", {})
        self.assertEqual(status, 200)
        final_game = asyncio.run(websocket_smoke(base, room, sessions))
        self.assertEqual(final_game["status"], "ended")
        _, newcomer_cookie = self.signup("终局后新人")
        rejection = asyncio.run(self.rejection_of(room["code"], newcomer_cookie))
        self.assertEqual(rejection["type"], "error")
        self.assertEqual(rejection["code"], "room.ended", "已结束房间必须与开局中区别解释")
        self.assertIn("结束", rejection["message"])
        self.assertIsNone(self.occupancy_of(newcomer_cookie))
        self.assertEqual(sessions[0].request(f"/api/rooms/{room['code']}")[1]["status"], "ended")

        host_account, host_cookie = self.signup("开局房主")
        code = self.create_room(host_cookie)
        account, cookie = self.signup("开局玩家")
        before = asyncio.run(self.state_of(code, cookie))
        started = asyncio.run(self.fill_to(code, host_cookie, 6, "开局补位"))
        self.assertEqual(started["roomStatus"], "playing")
        second_cookie = self.login("开局玩家")
        resumed = asyncio.run(self.state_of(code, second_cookie))
        self.assertEqual(resumed["roomStatus"], "playing")
        self.assertEqual(resumed["yourPlayerId"], before["yourPlayerId"])
        self.assertIsNotNone(resumed["game"]["viewer"], "开局后本人恢复必须保持私有投影")
        identity = resumed["game"]["viewer"]["identity"]
        again = asyncio.run(self.state_of(code, second_cookie))
        self.assertEqual(again["game"]["viewer"]["identity"], identity, "重复恢复不得改写私有身份")
        host_second = self.login("开局房主")
        host_state = asyncio.run(self.state_of(code, host_second))
        self.assertTrue(host_state["isHost"], "原房主换设备恢复必须保留管理权")
        self.assertEqual(len(host_state["game"]["players"]), 6)

    def test_v04_03_authorization_negatives_on_join_and_resume(self):
        """另一账号提交目标用户名、玩家引用或旧 token 均不能取得目标的座位、私有身份或房主操作。"""
        target_account, target_cookie = self.signup("被冒领目标")
        code = self.create_room(target_cookie)
        _, attacker_cookie = self.signup("冒领者")
        # REST：另一账号在创建入口提交目标用户名或旧 token 载荷 → 载荷被拒，不建新房。
        for data in [{"username": "被冒领目标"}, {"hostToken": "legacy-token"}, {"playerId": "p-anything"}]:
            status, body, _ = self.request("/api/rooms", data, attacker_cookie)
            self.assertEqual(status, 400, data)
            self.assertEqual(body["code"], "protocol.legacy-identity")
        # WS：hello 携带目标用户名或旧 token → 旧身份协议被拒，不能进入。
        for fields in [{"name": "被冒领目标"}, {"token": "legacy-token"}]:
            rejection = asyncio.run(self.rejection_of(code, attacker_cookie, **fields))
            self.assertEqual(rejection["code"], "protocol.legacy-identity", fields)
        self.assertIsNone(self.occupancy_of(attacker_cookie))
        # WS：hello 携带目标玩家引用 playerId → 字段被忽略，仍按当前账号分配自己的新座位。
        impersonation = asyncio.run(self.state_of(code, attacker_cookie, playerId="p-forged"))
        self.assertNotEqual(impersonation["yourPlayerId"], "p-forged")
        target_state = asyncio.run(self.state_of(code, target_cookie))
        self.assertNotEqual(impersonation["yourPlayerId"], target_state["yourPlayerId"], "玩家引用不能冒领他人座位")
        self.assertFalse(impersonation["isHost"])
        async def host_attempt(action):
            async with self.connect(code, attacker_cookie) as socket:
                await self.hello(socket)
                await socket.send(json.dumps({"type": "host", "action": action}))
                return json.loads(await asyncio.wait_for(socket.recv(), 3))
        for action in ["start", "lock", "unlock"]:
            self.assertEqual(asyncio.run(host_attempt(action))["code"], "room.not-host")
        self.assertFalse(self.request(f"/api/rooms/{code}", None, target_cookie)[1]["locked"])

    def test_v04_03_attacker_cannot_observe_targets_private_identity(self):
        _, host_cookie = self.signup("隐私房主")
        code = self.create_room(host_cookie)
        _, target_cookie = self.signup("隐私目标")
        target_before = asyncio.run(self.state_of(code, target_cookie))
        asyncio.run(self.fill_to(code, host_cookie, 6, "隐私补位"))
        target_started = asyncio.run(self.state_of(code, target_cookie))
        self.assertEqual(target_started["yourPlayerId"], target_before["yourPlayerId"])
        identity = target_started["game"]["viewer"]["identity"]
        self.assertTrue(identity, "开局后目标本人必须有私有身份")
        _, attacker_cookie = self.signup("隐私攻击者")
        # 开局后新人以 player 模式进入被拒，拿不到任何 state。
        rejection = asyncio.run(self.rejection_of(code, attacker_cookie))
        self.assertEqual(rejection["code"], "room.already-started")
        # 旁观连接只能得到公开投影：无 viewer、无任何 players[].identity。
        async def spectate():
            async with self.connect(code, attacker_cookie) as socket:
                await socket.send(json.dumps({"type": "hello", "mode": "spectator", "protocolVersion": "4"}))
                return json.loads(await asyncio.wait_for(socket.recv(), 3))
        spectator_state = asyncio.run(spectate())
        self.assertIsNone(spectator_state["yourPlayerId"])
        self.assertIsNone(spectator_state["game"]["viewer"])
        for player in spectator_state["game"]["players"]:
            self.assertNotIn("identity", player, "进行中的公开投影不得泄露任何玩家身份")
        # 冒领失败不影响目标本人随后的恢复。
        target_again = asyncio.run(self.state_of(code, target_cookie))
        self.assertEqual(target_again["game"]["viewer"]["identity"], identity)

    def _restart_during_play_and_resume(self, total):
        """V04.04: stop the whole server process tree mid-game, restart on the same
        saves directory, and verify every account resumes its own seat/identity."""
        _, host_cookie = self.signup(f"重启房主{total}")
        code = self.create_room(host_cookie)
        members = [self.signup(f"重启玩家{total}_{index}") for index in range(total - 1)]
        for _, cookie in members:
            asyncio.run(self.state_of(code, cookie))
        started = asyncio.run(self.fill_to(code, host_cookie, total, f"重启补位{total}"))
        self.assertEqual(started["roomStatus"], "playing")

        async def snapshot():
            snapshots = {}
            async def grab(cookie):
                async with self.connect(code, cookie) as socket:
                    state = await self.hello(socket)
                    snapshots[cookie] = state
            await asyncio.gather(*(grab(cookie) for cookie in [host_cookie, *(cookie for _, cookie in members)]))
            return snapshots
        before = asyncio.run(snapshot())
        roster_before = [(p["playerId"], p["displayName"]) for p in started["game"]["players"]]
        for _, cookie in members:
            self.assertIsNotNone(before[cookie]["game"]["viewer"], "开局后本人必须有私有投影")
        identities_before = {
            cookie: (state["yourPlayerId"], state["game"]["viewer"]["identity"])
            for cookie, state in before.items()
        }
        # 各账号身份互不相同：恢复后看到"自己而非别人"的强断言前提。
        self.assertEqual(len({repr(v) for v in identities_before.values()}), total)

        self.stop_server()  # Windows 下 taskkill /T /F：完整终止进程树
        self.start_server()
        self.assertEqual(self.request("/api/account/room", cookie=host_cookie)[1]["room"]["code"], code)
        after = asyncio.run(snapshot())
        for cookie, state in after.items():
            expected_id, expected_identity = identities_before[cookie]
            self.assertEqual(state["yourPlayerId"], expected_id, "重启后必须恢复原玩家引用")
            self.assertEqual(state["game"]["viewer"]["identity"], expected_identity, "重启后必须看到自己的私有身份")
            self.assertIn((state["yourPlayerId"], next(
                name for player_id, name in roster_before if player_id == state["yourPlayerId"])), roster_before)
        self.assertEqual(self.request(f"/api/rooms/{code}", None, host_cookie)[1]["status"], "playing")
        self.assertTrue(after[host_cookie]["isHost"], "重启后房主恢复管理权")

    def test_v04_04_restart_restores_six_player_game_seats_and_identities(self):
        self._restart_during_play_and_resume(6)

    def test_v04_04_restart_restores_odd_seven_player_game_seats_and_identities(self):
        self._restart_during_play_and_resume(7)

    def test_connection_receives_no_frames_before_hello_completes(self):
        """已 accept 但未完成 hello 的连接不得收到按空视角生成的投影广播。"""
        _, host_cookie = self.signup("握手房主")
        code = self.create_room(host_cookie)
        _, other_cookie = self.signup("握手玩家")
        asyncio.run(self.state_of(code, other_cookie))
        async def scenario():
            async with self.connect(code, other_cookie) as silent, self.connect(code, host_cookie) as active:
                await self.hello(active)  # 触发对房间内所有连接的广播
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(silent.recv(), 0.5)
                return await self.hello(silent)  # 自己的 hello 仍应得到正确投影
        state = asyncio.run(scenario())
        self.assertEqual(state["yourPlayerId"], asyncio.run(self.state_of(code, other_cookie))["yourPlayerId"])
        self.assertTrue(state["isHost"] is False)
