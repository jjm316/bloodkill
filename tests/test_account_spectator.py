"""Ticket 16: logged-in spectating, public projection, and the player/spectator
mutual exclusion.

Real uvicorn/HTTP/WS boundary (same isolated fixtures as 09–12): an account
without a player seat can spectate public rooms and receives only public
projections/events; an account holding an unfinished player seat is refused
spectating on every device (server-enforced), and a spectating account that
becomes a player has its established spectator connections stopped.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json
import unittest

import websockets

from tests import test_accounts as account_tests


class AccountSpectatorHTTPTests(unittest.TestCase):
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

    async def hello(self, socket, mode="player", **fields):
        await socket.send(json.dumps({"type": "hello", "mode": mode, "protocolVersion": "4", **fields}))
        return json.loads(await asyncio.wait_for(socket.recv(), 3))

    async def state_of(self, code, cookie, mode="player", **fields):
        async with self.connect(code, cookie) as socket:
            return await self.hello(socket, mode=mode, **fields)

    async def spectate_of(self, code, cookie, **fields):
        return await self.state_of(code, cookie, mode="spectator", **fields)

    async def rejection_of(self, code, cookie, mode="spectator", **fields):
        """A refused hello must land an error frame with a Chinese reason."""
        async with self.connect(code, cookie) as socket:
            await socket.send(json.dumps({"type": "hello", "mode": mode, "protocolVersion": "4", **fields}))
            return json.loads(await asyncio.wait_for(socket.recv(), 3))

    def occupancy_of(self, cookie):
        return self.request("/api/account/room", cookie=cookie)[1]["room"]

    def player_count(self, code):
        return self.request(f"/api/rooms/{code}")[1]["playerCount"]

    # ---- V10.03: a seated account cannot spectate, on any device ----------

    def test_seated_account_cannot_spectate_on_any_device_or_room(self):
        _, host_a = self.signup("互斥房主A")
        room_a = self.create_room(host_a)
        _, member_cookie = self.signup("互斥成员")
        asyncio.run(self.state_of(room_a, member_cookie))  # 普通玩家占座
        _, host_b = self.signup("互斥房主B")
        room_b = self.create_room(host_b)

        # 直接请求：已占座账号旁观其他房间被服务端拒绝，给中文原因与返回原房入口。
        rejection = asyncio.run(self.rejection_of(room_b, member_cookie))
        self.assertEqual(rejection["type"], "error")
        self.assertEqual(rejection["code"], "spectator.seat-held")
        self.assertIn("旁观", rejection["message"], "拒绝原因必须说明不能旁观")
        self.assertIn("返回原房间", rejection["message"], "拒绝原因必须引导返回原房间")
        self.assertEqual(rejection["details"]["roomCode"], room_a, "details 提供返回原房入口")
        self.assertEqual(self.player_count(room_b), 1, "被拒旁观不能在目标房留下座位")

        # 跨设备：同一账号的第二会话同样被拒（服务端校验，非仅前端）。
        second_cookie = self.login("互斥成员")
        self.assertNotEqual(second_cookie, member_cookie)
        again = asyncio.run(self.rejection_of(room_b, second_cookie))
        self.assertEqual(again["code"], "spectator.seat-held")
        self.assertEqual(again["details"]["roomCode"], room_a)

        # 旁观自己占座的房间同样被拒：在原房应走玩家恢复路径。
        own = asyncio.run(self.rejection_of(room_a, member_cookie))
        self.assertEqual(own["code"], "spectator.seat-held")
        self.assertEqual(own["details"]["roomCode"], room_a)

        # 对照：无玩家座位的已登录账号可以旁观同一房间。
        _, outsider_cookie = self.signup("无座观众")
        spectator = asyncio.run(self.spectate_of(room_b, outsider_cookie))
        self.assertEqual(spectator["type"], "state")
        self.assertIsNone(spectator["yourPlayerId"])

        # 被拒账号的占用保持原房不变，可按入口恢复玩家座位。
        self.assertEqual(self.occupancy_of(member_cookie), {"code": room_a, "status": "waiting"})
        resumed = asyncio.run(self.state_of(room_a, member_cookie))
        self.assertIsNotNone(resumed["yourPlayerId"], "被拒旁观后仍能以玩家恢复原房座位")

    # ---- V10.03: becoming a player stops established spectator conns ------

    async def read_until(self, socket, predicate, timeout=5):
        while True:
            message = json.loads(await asyncio.wait_for(socket.recv(), timeout))
            if predicate(message):
                return message

    def test_becoming_player_by_join_stops_established_spectator_connection(self):
        _, host_a = self.signup("转玩房主A")
        room_a = self.create_room(host_a)
        _, host_b = self.signup("转玩房主B")
        room_b = self.create_room(host_b)
        _, watcher_cookie = self.signup("转玩旁观者")
        _, keeper_cookie = self.signup("保留观众")

        async def scenario():
            # 两个已建立的旁观连接：目标账号与对照账号各一。
            async with self.connect(room_b, watcher_cookie) as watcher, self.connect(room_b, keeper_cookie) as keeper:
                self.assertEqual((await self.hello(watcher, mode="spectator"))["type"], "state")
                self.assertEqual((await self.hello(keeper, mode="spectator"))["type"], "state")
                # 同账号另一会话以玩家身份加入别房（先旁观、后加入）。
                second_cookie = self.login("转玩旁观者")
                async with self.connect(room_a, second_cookie) as joiner:
                    joined = await self.hello(joiner)
                    self.assertIsNotNone(joined["yourPlayerId"])
                    # 旧旁观连接收到停止帧并被关闭。
                    stop = await self.read_until(
                        watcher,
                        lambda message: message.get("type") == "error" and message.get("code") == "spectator.became-player",
                    )
                    self.assertIn("玩家", stop["message"])
                    self.assertIn("旁观", stop["message"], "停止原因必须是简体中文")
                    with self.assertRaises(websockets.exceptions.ConnectionClosed):
                        await asyncio.wait_for(watcher.recv(), 3)
                    # 停止后的旧连接再试动作失败：连接已关，命令不能送达引擎。
                    with self.assertRaises(Exception):
                        await asyncio.wait_for(watcher.send(json.dumps({
                            "type": "command", "command": "pass-dagger", "payload": {}, "commandId": "late",
                        })), 3)
                    # 停止后不再收到新帧：目标房广播只到达对照旁观连接。
                    async with self.connect(room_b, host_b) as actor:
                        await self.hello(actor)
                        await actor.send(json.dumps({"type": "host", "action": "lock"}))
                        frame = await self.read_until(keeper, lambda message: message.get("type") == "state" and message.get("locked"))
                    self.assertTrue(frame["locked"], "对照旁观连接必须继续收到目标房广播")
                    with self.assertRaises(websockets.exceptions.ConnectionClosed):
                        await asyncio.wait_for(watcher.recv(), 1)
                    return joined["yourPlayerId"]

        player_id = asyncio.run(scenario())
        # 最终归属：账号只保留玩家占用，无活动旁观。
        self.assertEqual(self.occupancy_of(watcher_cookie), {"code": room_a, "status": "waiting"})
        resumed = asyncio.run(self.state_of(room_a, watcher_cookie))
        self.assertEqual(resumed["yourPlayerId"], player_id)

    def test_becoming_player_by_create_stops_established_spectator_connection(self):
        _, host_b = self.signup("建房旁观房主")
        room_b = self.create_room(host_b)
        _, watcher_cookie = self.signup("建房旁观者")

        async def scenario():
            async with self.connect(room_b, watcher_cookie) as watcher:
                self.assertEqual((await self.hello(watcher, mode="spectator"))["type"], "state")
                status, room, _ = self.request("/api/rooms", {}, watcher_cookie)
                self.assertEqual(status, 200)
                stop = await self.read_until(
                    watcher,
                    lambda message: message.get("type") == "error" and message.get("code") == "spectator.became-player",
                )
                self.assertIn("旁观", stop["message"])
                with self.assertRaises(websockets.exceptions.ConnectionClosed):
                    await asyncio.wait_for(watcher.recv(), 3)
                return room["code"]

        created = asyncio.run(scenario())
        self.assertEqual(self.occupancy_of(watcher_cookie)["code"], created)
        self.assertEqual(self.player_count(room_b), 1, "建房的账号不能在旁观房留下座位")

    # ---- V10.02: authorization negatives leave the game untouched ---------

    async def fill_to(self, code, host_cookie, total, prefix):
        """Join extra accounts until the room holds `total` seats, then start via the host."""
        current = self.player_count(code)
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

    def test_anonymous_invalid_session_and_spectator_commands_are_refused_without_state_changes(self):
        _, host_cookie = self.signup("授权房主")
        code = self.create_room(host_cookie)
        started = asyncio.run(self.fill_to(code, host_cookie, 6, "授权补位"))
        self.assertEqual(started["roomStatus"], "playing")
        revision_before = started["game"]["revision"]

        # 匿名与无效会话：未登录旁观在 hello 前即被拒并关闭。
        async def refused(cookie):
            async with websockets.connect(
                f"ws://127.0.0.1:{self.port}/ws/{code}",
                additional_headers={"Cookie": cookie} if cookie else {}, proxy=None,
            ) as socket:
                return json.loads(await asyncio.wait_for(socket.recv(), 3))

        for cookie in [None, "bloodbound_session=not-a-real-session"]:
            rejection = asyncio.run(refused(cookie))
            self.assertEqual(rejection["code"], "auth.login-required", cookie)
            self.assertIn("登录", rejection["message"])

        # 已登录旁观者发玩家命令与房主管理命令：被拒且对局状态不变。
        _, spectator_cookie = self.signup("越权观众")
        async def overreach():
            async with self.connect(code, spectator_cookie) as socket:
                state = await self.hello(socket, mode="spectator")
                await socket.send(json.dumps({
                    "type": "command", "command": "pass-dagger", "payload": {},
                    "commandId": "spectator-1", "expectedRevision": state["game"]["revision"],
                }))
                frames = []
                while len(frames) < 2:
                    message = json.loads(await asyncio.wait_for(socket.recv(), 3))
                    frames.append(message)
                await socket.send(json.dumps({"type": "host", "action": "lock"}))
                host_rejection = json.loads(await asyncio.wait_for(socket.recv(), 3))
                return state, frames, host_rejection

        state, frames, host_rejection = asyncio.run(overreach())
        self.assertIsNone(state["yourPlayerId"])
        error, ack = frames[0], frames[1]
        self.assertEqual(error["code"], "player.not-eligible", "旁观者不能发玩家命令")
        self.assertEqual(ack["status"], "rejected")
        self.assertEqual(ack["error"]["code"], "player.not-eligible")
        self.assertEqual(host_rejection["code"], "room.not-host", "旁观者不能用房主管理命令")
        info = self.request(f"/api/rooms/{code}")[1]
        self.assertEqual((info["status"], info["locked"]), ("playing", False), "被拒操作不得改变对局状态")
        after = asyncio.run(self.spectate_of(code, spectator_cookie))
        self.assertEqual(after["game"]["revision"], revision_before, "拒绝路径不推进修订号")

    # ---- V10.01: the spectator stream is public-only ------------------------

    def test_spectator_stream_carries_public_projection_and_events_only(self):
        from scripts.account_client import AccountClient
        from scripts.release_smoke import websocket_smoke, check_private_fields
        base = f"http://127.0.0.1:{self.port}"
        sessions = [AccountClient(base).register_test_account() for _ in range(7)]
        _, watcher_cookie = self.signup("隐私对照观众")
        status, room = sessions[0].request("/api/rooms", "POST", {})
        self.assertEqual(status, 200)
        code = room["code"]

        async def scenario():
            # 对照旁观连接全程在线：从等待房到终局收集服务端发来的每一帧。
            watcher = await self.connect(code, watcher_cookie)
            collected = [await self.hello(watcher, mode="spectator")]

            async def collect():
                try:
                    while True:
                        collected.append(json.loads(await asyncio.wait_for(watcher.recv(), 30)))
                except (websockets.exceptions.ConnectionClosed, TimeoutError):
                    pass

            collector = asyncio.create_task(collect())
            final = await websocket_smoke(base, room, sessions)
            # 终局后关闭对照连接；collector 捕获关闭后自然结束，collected 已含全部帧。
            await watcher.close()
            await asyncio.wait_for(collector, 10)
            return collected, final

        collected, final = asyncio.run(scenario())
        self.assertGreater(len(collected), 2, "旁观连接必须持续收到公开状态与事件帧")
        self.assertTrue(all(frame.get("type") in {"state", "event"} for frame in collected),
                        "旁观连接只能收到公开投影与公开事件")
        # 已知私有事实对照：终局公开揭晓的完整身份（阵营+位阶绑定）在开局后
        # 即已确定；旁观流的终局前帧不得出现任何一项完整绑定。公开的亮牌
        # 事件允许携带单个标记值（规则已公开的事实），但绝不携带完整身份。
        known_identities = {
            json.dumps(player["identity"], sort_keys=True, ensure_ascii=False)
            for player in final["players"]
        }
        self.assertEqual(len(known_identities), 6, "六名玩家的真实身份互不相同（对照前提）")
        pre_end = [frame for frame in collected if frame.get("type") != "state" or frame.get("roomStatus") != "ended"]
        for frame in pre_end:
            text = json.dumps(frame, ensure_ascii=False)
            for secret in known_identities:
                self.assertNotIn(secret, text, "旁观流的终局前帧不得泄露任何完整身份绑定")
            check_private_fields(frame)
            if frame.get("type") == "state":
                self.assertIsNone(frame["game"]["viewer"], "旁观投影没有私有视角块")
                self.assertEqual(frame["game"]["legalActions"], [], "旁观投影没有玩家操作")
            for event in (frame.get("events") or []):
                self.assertNotEqual(event["eventType"], "CurseViewed", "私有事件不得广播给旁观者")
                self.assertNotIn("curseId", json.dumps(event["payload"], ensure_ascii=False),
                                 "公开事件载荷不得携带诅咒真假线索")
        # 允许按规则已公开的事实：终局帧按 ADR 0015 公开全员身份。
        ended = [frame for frame in collected
                 if frame.get("type") == "state" and frame.get("roomStatus") == "ended"]
        self.assertTrue(ended, "旁观连接必须收到终局投影")
        self.assertTrue(all(player.get("identity") for player in ended[-1]["game"]["players"]))

    # ---- V10.04: spectate and seat-claim race never leaves both alive ------

    def test_concurrent_spectate_and_join_race_never_keeps_seat_plus_spectator(self):
        _, host_a = self.signup("竞争房主A")
        room_a = self.create_room(host_a)
        _, host_b = self.signup("竞争房主B")
        room_b = self.create_room(host_b)
        _, first_cookie = self.signup("竞争玩家")
        second_cookie = self.login("竞争玩家")
        self.assertNotEqual(first_cookie, second_cookie, "必须用两个独立会话制造跨设备竞争")
        barrier = Barrier(2)
        outcomes = {}

        def spectate_attempt():
            barrier.wait(timeout=5)

            async def run():
                async with self.connect(room_a, first_cookie) as socket:
                    await socket.send(json.dumps({"type": "hello", "mode": "spectator", "protocolVersion": "4"}))
                    first = json.loads(await asyncio.wait_for(socket.recv(), 5))
                    if first.get("type") == "error":
                        return {"rejected": first}
                    # 旁观已建立：与占座竞争的另一方若成功，本连接必须被停止。
                    while True:
                        message = json.loads(await asyncio.wait_for(socket.recv(), 10))
                        if message.get("type") == "error":
                            return {"stopped": message}
            try:
                outcomes["spectate"] = asyncio.run(run())
            except Exception as error:  # 服务端关闭后 recv/send 以异常结束
                outcomes["spectate"] = {"closed": repr(error)}

        def join_attempt():
            barrier.wait(timeout=5)
            try:
                outcomes["join"] = asyncio.run(self.state_of(room_b, second_cookie))
            except Exception as error:
                outcomes["join_error"] = repr(error)

        with ThreadPoolExecutor(max_workers=2) as pool:
            pool.submit(spectate_attempt)
            pool.submit(join_attempt)

        join = outcomes.get("join")
        self.assertIsInstance(join, dict, f"占座方必须有明确成功结果：{outcomes}")
        self.assertEqual(join["type"], "state")
        spectate = outcomes.get("spectate", {})
        # 不变量：占座成功后不存在仍活动的旁观连接。
        if "rejected" in spectate:
            self.assertEqual(spectate["rejected"]["code"], "spectator.seat-held",
                             f"竞争失败方必须是占座互斥拒绝：{spectate}")
            self.assertEqual(spectate["rejected"]["details"]["roomCode"], room_b)
        else:
            self.assertIn("stopped", spectate, f"先建立的旁观连接必须被停止：{spectate}")
            self.assertEqual(spectate["stopped"]["code"], "spectator.became-player")
        # 最终归属唯一：占用指向成功加入的房间，无幽灵座位，可恢复。
        self.assertEqual(self.occupancy_of(first_cookie), {"code": room_b, "status": "waiting"})
        self.assertEqual(self.occupancy_of(second_cookie)["code"], room_b)
        self.assertEqual(self.player_count(room_a), 1, "旁观方不能在旁观房留下座位")
        self.assertEqual(self.player_count(room_b), 2)
        resumed = asyncio.run(self.state_of(room_b, first_cookie))
        self.assertEqual(resumed["yourPlayerId"], join["yourPlayerId"], "竞争后仍能恢复唯一座位")
        # 竞争落败的旁观入口对该账号已不可用：再试仍被互斥拒绝。
        again = asyncio.run(self.rejection_of(room_a, first_cookie))
        self.assertEqual(again["code"], "spectator.seat-held")

    # ---- ended rooms: live spectating closes, the replay entry stays open --

    def test_ended_room_rejects_live_spectating_but_keeps_replay_entry_open(self):
        from scripts.account_client import AccountClient
        from scripts.release_smoke import websocket_smoke
        base = f"http://127.0.0.1:{self.port}"
        sessions = [AccountClient(base).register_test_account() for _ in range(7)]
        status, room = sessions[0].request("/api/rooms", "POST", {})
        self.assertEqual(status, 200)
        final = asyncio.run(websocket_smoke(base, room, sessions))
        self.assertEqual(final["status"], "ended")
        code = room["code"]

        # 实时旁观只针对未结束房间：结束房的 WS 旁观被拒并指向回放。
        rejection = asyncio.run(self.rejection_of(code, sessions[6].cookie_header))
        self.assertEqual(rejection["code"], "room.ended")
        self.assertIn("旁观", rejection["message"], "结束房拒绝必须按旁观语境解释")
        self.assertIn("回放", rejection["message"], "结束房拒绝必须引导到回放入口")
        # 已结束对局的公开回放入口不受实时旁观限制影响（工单 23 行为保持）。
        status, replay, _ = self.request(f"/api/rooms/{code}/replay", cookie=sessions[6].cookie_header)
        self.assertEqual(status, 200, "同一账号按房号读回放必须仍然可用")
        self.assertEqual(replay["steps"][-1]["status"], "ended")


if __name__ == "__main__":
    unittest.main()
