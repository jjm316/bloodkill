"""Ticket 12: one unfinished room per account, on every device and under races.

Real uvicorn/HTTP/WS boundary (same isolated fixtures as 09/10). V06.01 races
use independent authenticated clients launched from real threads that meet at
a barrier, so the requests hit the live server concurrently; the assertions
are about final ownership, success/failure outcomes, and restart state — never
"no exception was raised".
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json
import unittest

import websockets

from tests import test_accounts as account_tests


class AccountOccupancyHTTPTests(unittest.TestCase):
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

    def occupancy_of(self, cookie):
        return self.request("/api/account/room", cookie=cookie)[1]["room"]

    def player_count(self, code, cookie):
        return self.request(f"/api/rooms/{code}", None, cookie)[1]["playerCount"]

    async def fill_to(self, code, host_cookie, total, prefix):
        """Join extra accounts until the room holds `total` seats, then start via the host."""
        current = self.player_count(code, host_cookie)
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

    # ---- V06.01: real concurrent requests, one effective occupancy --------

    def test_v06_01_concurrent_create_from_two_sessions_collapses_to_one_room(self):
        _, first_cookie = self.signup("并发建房者")
        second_cookie = self.login("并发建房者")
        self.assertNotEqual(first_cookie, second_cookie, "必须用两个独立会话制造跨设备竞争")
        barrier = Barrier(2)

        def attempt(cookie):
            barrier.wait(timeout=5)
            return self.request("/api/rooms", {}, cookie)

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, [first_cookie, second_cookie]))
        for status, body, _ in outcomes:
            self.assertEqual(status, 200, "同账号并发建房要么复得同一房，要么房主幂等重试，不得出现失败")
        codes = {body["code"] for _, body, _ in outcomes}
        self.assertEqual(len(codes), 1, "所有成功响应必须指向同一房间")
        code = codes.pop()
        self.assertEqual(self.occupancy_of(first_cookie)["code"], code, "并发后占用唯一")
        self.assertEqual(self.occupancy_of(second_cookie)["code"], code, "另一会话看到的也是同一房间")
        self.assertEqual(self.player_count(code, first_cookie), 1, "不能借并发多建座位")

    def test_v06_01_concurrent_join_of_two_rooms_yields_single_occupancy(self):
        _, host_a = self.signup("并加房主A")
        _, host_b = self.signup("并加房主B")
        room_a, room_b = self.create_room(host_a), self.create_room(host_b)
        _, first_cookie = self.signup("并加玩家")
        second_cookie = self.login("并加玩家")
        barrier = Barrier(2)
        outcomes = {}

        def attempt(key, code, cookie):
            barrier.wait(timeout=5)
            try:
                outcomes[key] = asyncio.run(self.state_of(code, cookie))
            except Exception as error:  # websockets 在被服务端拒绝时以 ConnectionClosed 结束
                outcomes[key] = error

        with ThreadPoolExecutor(max_workers=2) as pool:
            pool.submit(attempt, "a", room_a, first_cookie)
            pool.submit(attempt, "b", room_b, second_cookie)

        states = {key: value for key, value in outcomes.items() if isinstance(value, dict) and value.get("type") == "state"}
        rejections = {}
        for key, value in outcomes.items():
            if not isinstance(value, dict):
                continue
            if value.get("type") == "error":
                rejections[key] = value
        self.assertEqual(len(states) + len(rejections), 2, "每个并发请求都要有明确结果")
        self.assertEqual(len(states), 1, "并发加入两房必须恰好成功一个")
        winner_code = next(iter(states.values()))["roomCode"]
        self.assertIn(winner_code, {room_a, room_b})
        self.assertEqual(len(rejections), 1, "另一个请求必须被明确拒绝")
        rejection = next(iter(rejections.values()))
        self.assertEqual(rejection["code"], "account.room-occupied")
        self.assertIn("返回原房间", rejection["message"], "拒绝原因必须是简体中文并引导返回")
        self.assertEqual(rejection["details"]["roomCode"], winner_code, "失败方得到原房返回入口")
        # 最终归属与无残留。
        occupied = self.occupancy_of(first_cookie)
        self.assertEqual(occupied["code"], winner_code)
        self.assertEqual(self.occupancy_of(second_cookie)["code"], winner_code)
        loser_code = room_b if winner_code == room_a else room_a
        self.assertEqual(self.player_count(loser_code, first_cookie), 1, "失败方不能在目标房留下幽灵座位")
        # 失败方按引导返回原房仍能恢复座位。
        resumed = asyncio.run(self.state_of(winner_code, second_cookie))
        self.assertEqual(resumed["yourPlayerId"], next(iter(states.values()))["yourPlayerId"])

    def test_v06_01_concurrent_create_and_join_mixed_race_leaves_single_occupancy(self):
        _, host = self.signup("混合房主")
        other_room = self.create_room(host)
        _, cookie = self.signup("混合玩家")
        second_cookie = self.login("混合玩家")
        barrier = Barrier(2)
        outcomes = {}

        def create_attempt():
            barrier.wait(timeout=5)
            outcomes["create"] = self.request("/api/rooms", {}, cookie)

        def join_attempt():
            barrier.wait(timeout=5)
            try:
                outcomes["join"] = asyncio.run(self.state_of(other_room, second_cookie))
            except Exception as error:
                outcomes["join_error"] = error

        with ThreadPoolExecutor(max_workers=2) as pool:
            pool.submit(create_attempt)
            pool.submit(join_attempt)

        create_status, create_body, _ = outcomes["create"]
        join = outcomes.get("join")
        join_error = outcomes.get("join_error")
        self.assertTrue(create_status in (200, 409) and (join is not None or join_error is not None))
        occupied = self.occupancy_of(cookie)
        self.assertIsNotNone(occupied, "混合竞争后必须仍有唯一占用")
        winners = [code for code in (create_body.get("code") if create_status == 200 else None,
                                     join.get("roomCode") if isinstance(join, dict) else None) if code]
        if create_status == 409:
            # 加入成功：建房被拒，必须给出原房引导。
            self.assertEqual(create_body["code"], "account.room-occupied")
            self.assertEqual(create_body["details"]["roomCode"], occupied["code"])
            self.assertEqual(self.player_count(other_room, host), 2)
        else:
            # 建房成功：加入被服务端拒绝（错误帧），目标房不残留座位。
            self.assertEqual(occupied["code"], create_body["code"])
            rejection = join_error if isinstance(join_error, dict) else join
            self.assertIsNotNone(rejection, "失败方必须有明确失败结果")
            if isinstance(rejection, dict):
                self.assertEqual(rejection["code"], "account.room-occupied")
                self.assertEqual(rejection["details"]["roomCode"], create_body["code"])
            self.assertEqual(self.player_count(other_room, host), 1, "失败方不能在目标房留下幽灵座位")

    # ---- V06.02: second device rejected with a return entry, restart safe --

    def test_v06_02_second_session_rejection_has_return_entry_and_survives_restart(self):
        _, first_cookie = self.signup("跨设备房主")
        code = self.create_room(first_cookie)
        second_cookie = self.login("跨设备房主")
        # 第二设备再请求创建：幂等复得同一房，不会出现第二间未结束房。
        status, body, _ = self.request("/api/rooms", {}, second_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(body["code"], code)
        # 第二设备转而加入别人的房：这才是失败方，必须被拒并拿到原房入口。
        _, host_b = self.signup("跨设备房主B")
        other_room = self.create_room(host_b)

        async def rejected():
            async with self.connect(other_room, second_cookie) as socket:
                await socket.send(json.dumps({"type": "hello", "mode": "player", "protocolVersion": "4"}))
                return json.loads(await asyncio.wait_for(socket.recv(), 3))

        rejection = asyncio.run(rejected())
        self.assertEqual(rejection["code"], "account.room-occupied")
        self.assertIn("返回原房间", rejection["message"])
        self.assertEqual(rejection["details"]["roomCode"], code)
        # 失败方从占用查询获得当前房入口（前端“返回房间”按钮的数据来源）。
        self.assertEqual(self.occupancy_of(second_cookie), {"code": code, "status": "waiting"})
        # 拒绝不产生新房或幽灵座位，重启后占用仍唯一。
        self.assertEqual(self.player_count(other_room, host_b), 1)
        before = self.player_count(code, first_cookie)
        self.stop_server()
        self.start_server()
        self.assertEqual(self.occupancy_of(first_cookie)["code"], code, "重启后占用仍唯一")
        self.assertEqual(self.occupancy_of(second_cookie)["code"], code)
        self.assertEqual(self.player_count(code, first_cookie), before, "拒绝后重启不能出现幽灵座位或第二个房")
        self.assertEqual(self.player_count(other_room, host_b), 1, "重启后目标房仍无幽灵座位")
        resumed = asyncio.run(self.state_of(code, second_cookie))
        self.assertTrue(resumed["isHost"], "重启后失败方按入口返回原房仍是房主")

    def test_v06_02_join_rejection_survives_restart_with_single_occupancy(self):
        _, host_a = self.signup("重启房主A")
        _, host_b = self.signup("重启房主B")
        room_a, room_b = self.create_room(host_a), self.create_room(host_b)
        _, cookie = self.signup("重启玩家")
        asyncio.run(self.state_of(room_a, cookie))

        async def rejected():
            async with self.connect(room_b, cookie) as socket:
                await socket.send(json.dumps({"type": "hello", "mode": "player", "protocolVersion": "4"}))
                return json.loads(await asyncio.wait_for(socket.recv(), 3))

        rejection = asyncio.run(rejected())
        self.assertEqual(rejection["code"], "account.room-occupied")
        self.assertEqual(rejection["details"]["roomCode"], room_a)
        self.assertEqual(self.player_count(room_b, host_b), 1, "被拒时目标房不残留座位")

        self.stop_server()
        self.start_server()
        self.assertEqual(self.occupancy_of(cookie), {"code": room_a, "status": "waiting"}, "重启后占用仍指向原房")
        self.assertEqual(self.player_count(room_b, host_b), 1, "重启后不能出现幽灵座位")
        resumed = asyncio.run(self.state_of(room_a, cookie))
        self.assertNotIn(resumed["yourPlayerId"], [None], "重启后仍可恢复原座位")

    # ---- V06.03: state transitions of the occupancy ------------------------

    def test_v06_03_playing_disconnect_and_host_lobby_keep_occupancy_blocking_others(self):
        _, host_cookie = self.signup("占用房主")
        code = self.create_room(host_cookie)
        _, member_cookie = self.signup("占用玩家")
        asyncio.run(self.state_of(code, member_cookie))
        started = asyncio.run(self.fill_to(code, host_cookie, 6, "占用补位"))
        self.assertEqual(started["roomStatus"], "playing")
        # 对局中玩家断线（掉线/临时关闭页面）：占用保留，不能加入别房。
        _, other_cookie = self.signup("别房房主")
        other_room = self.create_room(other_cookie)

        async def try_other(cookie, code_other):
            async with self.connect(code_other, cookie) as socket:
                await socket.send(json.dumps({"type": "hello", "mode": "player", "protocolVersion": "4"}))
                return json.loads(await asyncio.wait_for(socket.recv(), 3))

        member_rejection = asyncio.run(try_other(member_cookie, other_room))
        self.assertEqual(member_rejection["code"], "account.room-occupied")
        self.assertEqual(member_rejection["details"]["roomCode"], code)
        self.assertEqual(self.occupancy_of(member_cookie), {"code": code, "status": "playing"})
        # 房主等待阶段“返回大厅”（断开连接）同样保留占用与房主身份。
        _, second_host_cookie = self.signup("等待房主")
        waiting_code = self.create_room(second_host_cookie)

        async def host_leaves_lobby():
            async with self.connect(waiting_code, second_host_cookie) as socket:
                await self.hello(socket)  # 进入后直接断开 = 界面上的“返回大厅”
        asyncio.run(host_leaves_lobby())
        host_rejection = asyncio.run(try_other(second_host_cookie, other_room))
        self.assertEqual(host_rejection["code"], "account.room-occupied", "房主返回大厅后也不能进别房")
        self.assertEqual(self.occupancy_of(second_host_cookie)["code"], waiting_code)
        back = asyncio.run(self.state_of(waiting_code, second_host_cookie))
        self.assertTrue(back["isHost"], "返回原房保留房主身份")
        # 其他玩家照常可加入别房（对照账号不受影响）。
        _, outsider_cookie = self.signup("局外玩家")
        outsider_state = asyncio.run(self.state_of(other_room, outsider_cookie))
        self.assertIsNotNone(outsider_state["yourPlayerId"])

    def test_v06_03_normal_end_releases_every_occupant_for_next_room(self):
        from scripts.account_client import AccountClient
        from scripts.release_smoke import websocket_smoke
        base = f"http://127.0.0.1:{self.port}"
        sessions = [AccountClient(base).register_test_account() for _ in range(7)]
        status, room = sessions[0].request("/api/rooms", "POST", {})
        self.assertEqual(status, 200)
        final_game = asyncio.run(websocket_smoke(base, room, sessions))
        self.assertEqual(final_game["status"], "ended")

        cookies = [session.cookie_header for session in sessions[:6]]
        for cookie in cookies:
            self.assertIsNone(self.request("/api/account/room", cookie=cookie)[1]["room"], "正常终局必须释放全员占用")
        # 释放后加入别的未结束房可行（加入路径先验证，随后该账号会被新房占用）。
        _, last_cookie = self.signup("终局后房主")
        last_room = self.create_room(last_cookie)
        rejoined = asyncio.run(self.state_of(last_room, cookies[0]))
        self.assertIsNotNone(rejoined["yourPlayerId"], "终局释放后加入路径也必须可用")
        # 其余玩家都能开下一房间（创建路径不再被占用拒绝）。
        for cookie in cookies[1:]:
            status, body, _ = self.request("/api/rooms", {}, cookie)
            self.assertEqual(status, 200, "终局后必须能进入下一房间")
            self.assertNotEqual(body["code"], room["code"])
        # 原房仍保留结果浏览。
        info = self.request(f"/api/rooms/{room['code']}", None, sessions[0].cookie_header)[1]
        self.assertEqual(info["status"], "ended")

    # ---- V06.04: the limit is server-enforced, clients cannot bypass it ----

    def test_v06_04_occupancy_limit_enforced_on_direct_api_and_ws(self):
        _, host_a = self.signup("强制房主A")
        _, host_b = self.signup("强制房主B")
        room_a, room_b = self.create_room(host_a), self.create_room(host_b)
        _, cookie = self.signup("强制玩家")
        first = asyncio.run(self.state_of(room_a, cookie))

        # 绕过前端按钮直接发 REST 建房 → 409。
        status, body, _ = self.request("/api/rooms", {}, cookie)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "account.room-occupied")
        self.assertEqual(body["details"]["roomCode"], room_a)

        # 绕过客户端状态直接发 WS hello 到别房 → 错误帧 + 原房引导。
        async def direct():
            async with self.connect(room_b, cookie) as socket:
                await socket.send(json.dumps({"type": "hello", "mode": "player", "protocolVersion": "4"}))
                return json.loads(await asyncio.wait_for(socket.recv(), 3))

        rejection = asyncio.run(direct())
        self.assertEqual(rejection["code"], "account.room-occupied")
        self.assertEqual(rejection["details"]["roomCode"], room_a)
        self.assertEqual(self.player_count(room_b, host_b), 1, "直接请求不能在别房占座")

        # 本人恢复原房不算新占用，不因占用限制被误伤。
        resumed = asyncio.run(self.state_of(room_a, cookie))
        self.assertEqual(resumed["yourPlayerId"], first["yourPlayerId"])


if __name__ == "__main__":
    unittest.main()
