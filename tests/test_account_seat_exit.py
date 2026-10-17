"""Ticket 13: waiting-seat exit (real release) vs host/in-game return (keep seat).

Real uvicorn/HTTP/WS boundary (same isolated fixtures as 09–12). The three
departure flavours are decided by the server: a waiting non-host member's
`leave` truly releases the seat and occupancy; a host's "return to lobby" (or
any leave attempt) keeps the seat and host identity; an in-game departure only
drops the connection. V07.04 races meet at a barrier so the exit and the start
hit the live server concurrently; assertions are about final legal state.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json
import unittest

import websockets

from tests import test_accounts as account_tests


class SeatExitHTTPTests(unittest.TestCase):
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

    async def state_of(self, code, cookie):
        async with self.connect(code, cookie) as socket:
            return await self.hello(socket)

    def occupancy_of(self, cookie):
        return self.request("/api/account/room", cookie=cookie)[1]["room"]

    def player_count(self, code, cookie):
        return self.request(f"/api/rooms/{code}", None, cookie)[1]["playerCount"]

    async def fill_to(self, code, host_cookie, total, prefix):
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

    # ---- V07.01: a waiting member's leave truly releases ------------------

    def test_v07_01_waiting_member_leave_releases_seat_and_updates_roster(self):
        _, host_cookie = self.signup("退座房主")
        code = self.create_room(host_cookie)
        _, member_cookie = self.signup("退座玩家")
        _, other_cookie = self.signup("退座旁观员")

        async def scenario():
            async with self.connect(code, host_cookie) as host_socket, \
                    self.connect(code, member_cookie) as member_socket, \
                    self.connect(code, other_cookie) as other_socket:
                await self.hello(host_socket)
                member_state = await self.hello(member_socket)
                await self.hello(other_socket)
                old_player_id = member_state["yourPlayerId"]
                # 其他连接的 hello 广播给 member 积压了一帧 state，读掉避免与退座帧混淆。
                drained = json.loads(await asyncio.wait_for(member_socket.recv(), 3))
                self.assertEqual(drained["type"], "state")
                await member_socket.send(json.dumps({"type": "leave"}))
                confirmation = json.loads(await asyncio.wait_for(member_socket.recv(), 3))
                self.assertEqual(confirmation["type"], "left", "退座者得到服务端确认帧")
                self.assertEqual(confirmation["roomCode"], code)
                # 其余成员最终收到退座公开事件与更新后的名册（期间可能夹带
                # 积压的旧 state 帧，以 PlayerLeft 事件为锚，取其后第一帧名册）。
                saw_left_event = False
                state = None
                for _ in range(10):
                    message = json.loads(await asyncio.wait_for(host_socket.recv(), 3))
                    if message.get("type") == "event":
                        if any(event["eventType"] == "PlayerLeft" and event["payload"]["playerId"] == old_player_id
                               for event in message["events"]):
                            saw_left_event = True
                    elif message.get("type") == "state" and saw_left_event:
                        state = message
                        break
                self.assertIsNotNone(state, "名册更新帧必须到达")
                names = [player["displayName"] for player in state["game"]["players"]]
                self.assertNotIn("退座玩家", names, "名册不再包含已退出玩家")
                self.assertEqual(len(names), 2)
                # 退座者的连接被服务端关闭（真退座，不是静默断开）。
                with self.assertRaises(websockets.exceptions.ConnectionClosed):
                    await asyncio.wait_for(member_socket.recv(), 3)
                return old_player_id

        old_player_id = asyncio.run(scenario())
        # 占用释放：可查询、可加入别的房间；原房人数收缩。
        self.assertIsNone(self.occupancy_of(member_cookie), "退座释放占用")
        self.assertEqual(self.player_count(code, host_cookie), 2)
        # 重进原房：新的玩家引用，名册无重复。
        again = asyncio.run(self.state_of(code, member_cookie))
        self.assertNotEqual(again["yourPlayerId"], old_player_id, "重进生成新玩家引用")
        self.assertEqual(self.player_count(code, host_cookie), 3)
        names = [player["displayName"] for player in again["game"]["players"]]
        self.assertEqual(names.count("退座玩家"), 1, "名册无重复条目")
        # 再次退座后，还能加入别的房间。
        async def leave_again():
            async with self.connect(code, member_cookie) as socket:
                await self.hello(socket)
                await socket.send(json.dumps({"type": "leave"}))
                return json.loads(await asyncio.wait_for(socket.recv(), 3))
        confirmation = asyncio.run(leave_again())
        self.assertEqual(confirmation["type"], "left")
        _, other_host = self.signup("退座别房房主")
        other_room = self.create_room(other_host)
        joined = asyncio.run(self.state_of(other_room, member_cookie))
        self.assertIsNotNone(joined["yourPlayerId"], "退座后可加入别的房间")

    # ---- V07.05: host / in-game / disconnect branches keep the seat --------

    def test_v07_05_host_leave_attempt_is_rejected_and_lobby_return_keeps_seat(self):
        _, host_cookie = self.signup("返回房主")
        code = self.create_room(host_cookie)

        async def host_leave_rejected():
            async with self.connect(code, host_cookie) as socket:
                state = await self.hello(socket)
                await socket.send(json.dumps({"type": "leave"}))
                return state, json.loads(await asyncio.wait_for(socket.recv(), 3))

        state, rejection = asyncio.run(host_leave_rejected())
        self.assertTrue(state["isHost"])
        self.assertEqual(rejection["type"], "error")
        self.assertEqual(rejection["code"], "room.host-seat-kept")
        self.assertIn("房主", rejection["message"], "拒绝理由必须是简体中文并说明房主保留")
        self.assertEqual(self.occupancy_of(host_cookie), {"code": code, "status": "waiting"}, "房主座位与占用保留")
        self.assertEqual(self.player_count(code, host_cookie), 1)
        # 界面的“返回大厅”（直接断开，不发 leave）同样保留座位与身份。
        async def lobby_return():
            async with self.connect(code, host_cookie) as socket:
                await self.hello(socket)  # 进入后直接断开
        asyncio.run(lobby_return())
        back = asyncio.run(self.state_of(code, host_cookie))
        self.assertTrue(back["isHost"], "返回原房仍是房主")
        self.assertEqual(self.occupancy_of(host_cookie)["code"], code)

    def test_v07_05_in_game_leave_rejected_and_disconnect_keeps_occupancy(self):
        _, host_cookie = self.signup("局中房主")
        code = self.create_room(host_cookie)
        _, member_cookie = self.signup("局中玩家")
        asyncio.run(self.state_of(code, member_cookie))
        started = asyncio.run(self.fill_to(code, host_cookie, 6, "局中补位"))
        self.assertEqual(started["roomStatus"], "playing")

        async def in_game_leave_rejected():
            async with self.connect(code, member_cookie) as socket:
                await self.hello(socket)
                await socket.send(json.dumps({"type": "leave"}))
                return json.loads(await asyncio.wait_for(socket.recv(), 3))

        rejection = asyncio.run(in_game_leave_rejected())
        self.assertEqual(rejection["code"], "room.in-progress")
        self.assertIn("保留", rejection["message"], "对局中离开的提示必须说明座位保留")
        self.assertEqual(self.occupancy_of(member_cookie), {"code": code, "status": "playing"}, "占用保留")
        _, other_host = self.signup("局中别房房主")
        other_room = self.create_room(other_host)

        async def try_other(cookie, target):
            async with self.connect(target, cookie) as socket:
                await socket.send(json.dumps({"type": "hello", "mode": "player", "protocolVersion": "4"}))
                return json.loads(await asyncio.wait_for(socket.recv(), 3))

        blocked = asyncio.run(try_other(member_cookie, other_room))
        self.assertEqual(blocked["code"], "account.room-occupied", "对局中不能加入新房间")
        # 退出登录也不退座（工单 14 语义）：会话撤销后重登恢复原座位。
        self.request("/api/auth/logout", {}, member_cookie)
        self.assertEqual(self.request("/api/account/room", cookie=member_cookie)[0], 401)
        relogin = self.login("局中玩家")
        resumed = asyncio.run(self.state_of(code, relogin))
        self.assertIsNotNone(resumed["yourPlayerId"], "重登后恢复原座位")

    def test_v07_02_leave_rejoin_restart_replays_identical_roster(self):
        _, host_cookie = self.signup("重放房主")
        code = self.create_room(host_cookie)
        cookies = {}
        for name in ("重放玩家B", "重放玩家C", "重放玩家D"):
            _, cookies[name] = self.signup(name)
        async def join(name):
            return await self.state_of(code, cookies[name])
        states = {name: asyncio.run(join(name)) for name in cookies}
        old_b = states["重放玩家B"]["yourPlayerId"]
        async def leave(cookie):
            async with self.connect(code, cookie) as socket:
                await self.hello(socket)
                await socket.send(json.dumps({"type": "leave"}))
                return json.loads(await asyncio.wait_for(socket.recv(), 3))
        confirmation = asyncio.run(leave(cookies["重放玩家B"]))
        self.assertEqual(confirmation["type"], "left")
        rejoined_b = asyncio.run(join("重放玩家B"))
        self.assertNotEqual(rejoined_b["yourPlayerId"], old_b, "重进是新玩家引用")
        host_before = asyncio.run(self.state_of(code, host_cookie))

        self.stop_server()
        self.start_server()

        # 重启即完整重放（load_game 逐命令重放并校验事件/快照一致）。
        self.assertEqual(self.player_count(code, host_cookie), 4, "重启后人数与退出重加后的名册一致")
        host_after = asyncio.run(self.state_of(code, host_cookie))
        roster_before = [(player["displayName"], player["playerId"], player["seat"]) for player in host_before["game"]["players"]]
        roster_after = [(player["displayName"], player["playerId"], player["seat"]) for player in host_after["game"]["players"]]
        self.assertEqual(roster_after, roster_before, "重启重放后名册、玩家引用与顺序完全一致")
        display_names = [name for name, _, _ in roster_after]
        self.assertEqual(len(display_names), len(set(display_names)), "不能残留已退出玩家或重复座位")
        seats = [seat for _, _, seat in roster_after]
        self.assertEqual(seats, sorted(seats), "名册顺序与座位顺序一致")
        # 每个账号重连都恢复到重放后的引用，B 是新引用而非旧的。
        for name, cookie in cookies.items():
            resumed = asyncio.run(self.state_of(code, cookie))
            self.assertIsNotNone(resumed["yourPlayerId"], f"{name} 重启后仍可恢复座位")
        resumed_b = asyncio.run(self.state_of(code, cookies["重放玩家B"]))
        self.assertEqual(resumed_b["yourPlayerId"], rejoined_b["yourPlayerId"])

    def test_v07_03_start_boundary_after_exit_and_rejoin(self):
        _, host_cookie = self.signup("边界房主")
        code = self.create_room(host_cookie)
        members = {}
        for name in ("边界玩家A", "边界玩家B", "边界玩家C", "边界玩家D", "边界玩家E"):
            _, members[name] = self.signup(name)
        for name, cookie in members.items():
            asyncio.run(self.state_of(code, cookie))
        self.assertEqual(self.player_count(code, host_cookie), 6)
        async def leave(room_code, cookie):
            async with self.connect(room_code, cookie) as socket:
                await self.hello(socket)
                await socket.send(json.dumps({"type": "leave"}))
                return json.loads(await asyncio.wait_for(socket.recv(), 3))
        # 退出后 5 人：不能开始。
        asyncio.run(leave(code, members["边界玩家E"]))

        async def try_start():
            async with self.connect(code, host_cookie) as socket:
                await self.hello(socket)
                await socket.send(json.dumps({"type": "host", "action": "start"}))
                messages = []
                for _ in range(6):
                    message = json.loads(await asyncio.wait_for(socket.recv(), 3))
                    messages.append(message)
                    if message.get("type") == "error":
                        return message
                    if message.get("type") == "state" and message.get("roomStatus") == "playing":
                        return message
                raise AssertionError(messages)
        # 退出后 5 人：不能开始。
        rejected = asyncio.run(try_start())
        self.assertEqual(rejected["code"], "game.player-count")
        self.assertEqual(self.request(f"/api/rooms/{code}", None, host_cookie)[1]["status"], "waiting")
        # 补齐至 6 人：可以开始，且开局名册用当时的实际玩家集合。
        _, refill = self.signup("边界补员")
        asyncio.run(self.state_of(code, refill))
        started = asyncio.run(try_start())
        self.assertEqual(started["roomStatus"], "playing")
        self.assertEqual(len(started["game"]["players"]), 6)
        names = [player["displayName"] for player in started["game"]["players"]]
        self.assertNotIn("边界玩家E", names, "已退出玩家不在局中")
        self.assertEqual(len(names), len(set(names)), "退出重加不产生重复座位")

        # 7 人房含退出重加：规则初始化仍一致（7 人 → 3 rose + 3 beast + 1 审判者）。
        _, host7 = self.signup("七人房主")
        code7 = self.create_room(host7)
        seven = {}
        for name in ("七人A", "七人B", "七人C", "七人D", "七人E", "七人F"):
            _, seven[name] = self.signup(name)
        for name, cookie in seven.items():
            asyncio.run(self.state_of(code7, cookie))
        asyncio.run(leave(code7, seven["七人F"]))
        rejoined = asyncio.run(self.state_of(code7, seven["七人F"]))
        self.assertNotIn(rejoined["yourPlayerId"], [None])
        started7 = asyncio.run(self.fill_to(code7, host7, 7, "七人补位"))
        self.assertEqual(started7["roomStatus"], "playing")
        self.assertEqual(len(started7["game"]["players"]), 7)
        names7 = [player["displayName"] for player in started7["game"]["players"]]
        self.assertEqual(names7.count("七人F"), 1, "退出重加后开局恰有一个该玩家")

    def test_v07_04_concurrent_leave_and_start_race_has_one_legal_outcome(self):
        _, host_cookie = self.signup("竞争房主")
        code = self.create_room(host_cookie)
        _, member_cookie = self.signup("竞争退座者")
        asyncio.run(self.state_of(code, member_cookie))
        for index in range(4):
            _, filler = self.signup(f"竞争成员{index}")
            asyncio.run(self.state_of(code, filler))
        self.assertEqual(self.player_count(code, host_cookie), 6)
        barrier = Barrier(2)
        outcomes: dict[str, object] = {}

        def leave_attempt():
            async def run():
                async with self.connect(code, member_cookie) as socket:
                    await self.hello(socket)
                    # 两连接都完成 hello 后在 barrier 会合，再同时发出
                    # leave 与 start：竞争发生在真实服务端的消息处理上。
                    barrier.wait(timeout=10)
                    await socket.send(json.dumps({"type": "leave"}))
                    # 跳过对方 hello 广播积压的 state 帧与开局成功的事件广播，
                    # 只认退座结果（left 确认或错误帧）。
                    for _ in range(10):
                        message = json.loads(await asyncio.wait_for(socket.recv(), 5))
                        if message.get("type") in {"state", "event"}:
                            continue
                        return message
                    raise AssertionError("leave 未得到明确结果")
            try:
                outcomes["leave"] = asyncio.run(run())
            except Exception as error:
                outcomes["leave_error"] = error

        def start_attempt():
            async def run():
                async with self.connect(code, host_cookie) as socket:
                    await self.hello(socket)
                    barrier.wait(timeout=10)
                    await socket.send(json.dumps({"type": "host", "action": "start"}))
                    # 跳过积压 state 与退座事件广播，只认开局结果（playing 名册或错误帧）。
                    for _ in range(10):
                        message = json.loads(await asyncio.wait_for(socket.recv(), 5))
                        if message.get("type") == "error":
                            return message
                        if message.get("type") == "state" and message.get("roomStatus") == "playing":
                            return message
                    raise AssertionError("start 未得到明确结果")
            try:
                outcomes["start"] = asyncio.run(run())
            except Exception as error:
                outcomes["start_error"] = error

        with ThreadPoolExecutor(max_workers=2) as pool:
            pool.submit(leave_attempt)
            pool.submit(start_attempt)
        left = isinstance(outcomes.get("leave"), dict) and outcomes["leave"].get("type") == "left"
        started = isinstance(outcomes.get("start"), dict) and outcomes["start"].get("roomStatus") == "playing"
        self.assertTrue(left != started, f"退座与开局竞争最终恰好一种合法状态：{outcomes}")
        if left:
            # 成功退座后不在局中：开局因 5 人被拒，占用已释放。
            self.assertEqual(outcomes["start"]["code"], "game.player-count")
            self.assertEqual(self.request(f"/api/rooms/{code}", None, host_cookie)[1]["status"], "waiting")
            self.assertIsNone(self.occupancy_of(member_cookie))
        else:
            # 已开局拒绝退座：座位与占用保留，拒绝码 room.in-progress。
            self.assertEqual(outcomes["leave"]["code"], "room.in-progress")
            self.assertEqual(self.request(f"/api/rooms/{code}", None, host_cookie)[1]["status"], "playing")
            self.assertEqual(self.occupancy_of(member_cookie), {"code": code, "status": "playing"})


if __name__ == "__main__":
    unittest.main()
