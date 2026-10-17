"""Ticket 11: a new connection takes over the seat and the old one stops racing.

Real uvicorn/HTTP/WS boundary (same isolated fixtures as 09/10): a second
device entering the same account-bound seat takes it over; the old connection
receives `taken-over`, loses its operating rights (late messages included) and
receives no further frames, while the account itself stays logged in. Ordinary
reconnect (no takeover frame) keeps the existing backoff-resume path, and the
surviving connection keeps the existing idempotency / revision-conflict
protocol behaviour.
"""

import asyncio
import json
import unittest

import websockets

from tests import test_accounts as account_tests


async def drain_inflight(socket):
    """Discard frames already in flight (broadcasts triggered by others)."""
    while True:
        try:
            await asyncio.wait_for(socket.recv(), 0.3)
        except asyncio.TimeoutError:
            return


class SeatTakeoverHTTPTests(unittest.TestCase):
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
        while True:
            message = json.loads(await asyncio.wait_for(socket.recv(), 5))
            if message.get("type") == "state":
                return message
            if message.get("type") == "error":
                raise AssertionError(message)

    async def read_state(self, socket):
        """Read until the next state projection (skipping events/acks)."""
        while True:
            message = json.loads(await asyncio.wait_for(socket.recv(), 5))
            if message.get("type") == "state":
                return message

    async def read_until(self, socket, predicate, timeout=5):
        """Read frames until predicate holds, returning the matching frame."""
        while True:
            message = json.loads(await asyncio.wait_for(socket.recv(), timeout))
            if predicate(message):
                return message

    async def collect(self, socket, seconds=1.0):
        """Collect every frame arriving within the window, then return them."""
        frames = []
        deadline = asyncio.get_event_loop().time() + seconds
        while asyncio.get_event_loop().time() < deadline:
            try:
                frames.append(json.loads(await asyncio.wait_for(socket.recv(), deadline - asyncio.get_event_loop().time())))
            except asyncio.TimeoutError:
                break
        return frames

    async def started_room_with_dagger_holder(self, prefix):
        """Six real accounts start a game.

        Returns (code, holder_cookie, holder_display, host_cookie, other_cookies):
        the dagger holder is the takeover subject because it always holds a
        legal action right after the start; the host cookie is returned
        separately because the holder may itself be the host, and
        other_cookies excludes the holder's account (usable as unaffected
        control connections without re-taking-over the seat under test).
        """
        _, host_cookie = self.signup(f"{prefix}房主")
        code = self.create_room(host_cookie)
        cookies = [host_cookie]
        displays = [f"{prefix}房主"]
        for index in range(5):
            _, cookie = self.signup(f"{prefix}成员{index}")
            cookies.append(cookie)
            displays.append(f"{prefix}成员{index}")
            async with self.connect(code, cookie) as socket:
                await self.hello(socket)
        async with self.connect(code, host_cookie) as socket:
            await self.hello(socket)
            await socket.send(json.dumps({"type": "host", "action": "start"}))
            started = await self.read_state(socket)
        self.assertEqual(started["roomStatus"], "playing")
        holder_id = started["game"]["daggerHolderId"]
        for cookie, display in zip(cookies, displays):
            async with self.connect(code, cookie) as socket:
                state = await self.hello(socket)
            if state["yourPlayerId"] == holder_id:
                others = [c for c in cookies if c is not cookie]
                return code, cookie, display, host_cookie, others
        raise AssertionError("匕首持有者账号未匹配到座位")

    def occupancy_of(self, cookie):
        return self.request("/api/account/room", cookie=cookie)[1]["room"]

    # ---- V05.01 ---------------------------------------------------------

    def test_v05_01_second_device_takes_over_seat_old_stops_new_acts(self):
        """两设备依次进入同一座位：旧连接收到接管提示并失去操作权限，新连接保持投影并可继续合法操作。"""
        code, first_cookie, first_display, host_cookie, others = asyncio.run(self.started_room_with_dagger_holder("接管"))

        async def scenario():
            async with self.connect(code, first_cookie) as first:
                first_state = await self.hello(first)
                seat_id = first_state["yourPlayerId"]
                identity = first_state["game"]["viewer"]["identity"]
                revision = first_state["game"]["revision"]
                self.assertTrue(any(a["type"] == "pass-dagger" for a in first_state["game"]["legalActions"]),
                                "开局后匕首持有者必须原本就有合法动作")

                second_cookie = self.login(first_display)
                # 对照账号：与被测座位不同账号的普通成员，接管不影响它。
                control_cookie = others[-1]
                async with self.connect(code, control_cookie) as control:
                    control_state = await self.hello(control)
                    control_id = control_state["yourPlayerId"]
                    self.assertNotEqual(control_id, seat_id)
                    # 传匕首不能传给自己：对照目标取第一名非本人玩家。
                    target = next(p["playerId"] for p in first_state["game"]["players"] if p["playerId"] != seat_id)
                    # 排空对照连接入座广播给 first 带来的额外 state。
                    await drain_inflight(first)

                    async with self.connect(code, second_cookie) as second:
                        second_state = await self.hello(second)
                        # 新连接接管同一座位，保持正确私有投影；接管本身不推进对局。
                        self.assertEqual(second_state["yourPlayerId"], seat_id)
                        self.assertEqual(second_state["game"]["viewer"]["identity"], identity)
                        self.assertEqual(second_state["game"]["revision"], revision)
                        self.assertTrue(second_state["connected"][seat_id])
                        await drain_inflight(control)

                        # 旧连接收到接管提示随后被关闭。
                        taken = json.loads(await asyncio.wait_for(first.recv(), 5))
                        self.assertEqual(taken["type"], "taken-over")
                        with self.assertRaises(websockets.ConnectionClosed):
                            await asyncio.wait_for(first.recv(), 5)
                        # 排空旧连接断开触发的常规 connected 广播（既有行为，与接管无关）。
                        await drain_inflight(second)
                        await drain_inflight(control)

                        # 接管后旧连接再发原本合法的命令：不得产生任何效果（其他连接无新帧）。
                        try:
                            await first.send(json.dumps({
                                "type": "command", "commandId": "late-pass", "command": "pass-dagger",
                                "payload": {"targetPlayerId": target}, "expectedRevision": revision,
                            }))
                        except websockets.ConnectionClosed:
                            pass  # 发不出去同样证明连接已死；两种时序都不得改变引擎状态。
                        self.assertEqual(await self.collect(second, 0.5), [], "旧连接的迟到命令不得触发任何广播")
                        self.assertEqual(await self.collect(control, 0.5), [], "旧连接的迟到命令不得影响对照连接")

                        # 新连接继续合法操作：由接管座位把匕首传给对照座位。
                        await second.send(json.dumps({
                            "type": "command", "commandId": "takeover-pass", "command": "pass-dagger",
                            "payload": {"targetPlayerId": control_id},
                            "expectedRevision": revision,
                        }))
                        ack = await self.read_until(second, lambda m: m.get("type") == "ack")
                        self.assertEqual(ack["status"], "accepted", "接管后的新连接必须能继续合法操作")
                        await self.read_until(second, lambda m: m.get("type") == "state" and m["game"]["revision"] > revision)
                        # 对照连接实时收到传递广播（私有投影流不受接管影响）。
                        control_after = await self.read_until(
                            control, lambda m: m.get("type") == "state" and m["game"]["daggerHolderId"] == control_id)
                        self.assertIn("pass-dagger", [a["type"] for a in control_after["game"]["legalActions"]],
                                     "对照座位拿到匕首后必须有合法动作")

                        # 被接管旧连接不再收到任何新帧（无后续私有信息/状态）。
                        with self.assertRaises((websockets.ConnectionClosed, asyncio.TimeoutError)):
                            await asyncio.wait_for(first.recv(), 0.5)

                        # 对照连接（接管目标之外的合法连接）仍能继续操作。
                        await control.send(json.dumps({
                            "type": "command", "commandId": "control-pass", "command": "pass-dagger",
                            "payload": {"targetPlayerId": target},
                            "expectedRevision": control_after["game"]["revision"],
                        }))
                        control_ack = await self.read_until(control, lambda m: m.get("type") == "ack")
                        self.assertEqual(control_ack["status"], "accepted", "接管之外的合法连接必须仍能操作")
                        self.assertEqual(self.request(f"/api/rooms/{code}", None, host_cookie)[1]["playerCount"], 6)

        asyncio.run(scenario())
        # 旧设备账号仍保持登录，占用指向原房（可返回大厅并恢复）。
        status, session, _ = self.request("/api/auth/session", cookie=first_cookie)
        self.assertEqual(status, 200, "接管只断开座位连接，不得撤销旧设备登录")
        self.assertEqual(self.occupancy_of(first_cookie)["code"], code)

    # ---- V05.02 ---------------------------------------------------------

    def test_v05_02_three_concurrent_connections_only_one_keeps_operating(self):
        """三个客户端同时进入同账号座位：最后仅一个有操作能力，其余连接无后续私有帧。"""
        code, holder_cookie, holder_display, host_cookie, others = asyncio.run(self.started_room_with_dagger_holder("并发"))

        async def final_fate(socket):
            """'taken'：收到 taken-over 或连接被关；'alive'：静默期后仍在。"""
            try:
                while True:
                    message = json.loads(await asyncio.wait_for(socket.recv(), 1.5))
                    if message.get("type") == "taken-over":
                        return socket, "taken"
            except websockets.ConnectionClosed:
                return socket, "taken"
            except asyncio.TimeoutError:
                return socket, "alive"

        async def scenario():
            sessions = [self.login(holder_display) for _ in range(3)]
            self.assertEqual(len(set(sessions)), 3, "三个独立登录会话模拟三台设备")
            sockets = []
            try:
                for cookie in sessions:
                    connection = await self.connect(code, cookie)
                    sockets.append(await connection.__aenter__())
                # 三台设备同时 hello：服务端串行裁决，最后一个完成的接管前面的。
                async def enter(socket):
                    await socket.send(json.dumps({"type": "hello", "mode": "player", "protocolVersion": "4"}))
                    return json.loads(await asyncio.wait_for(socket.recv(), 5))
                first_frames = await asyncio.gather(*(enter(socket) for socket in sockets))
                seat_ids = {frame["yourPlayerId"] for frame in first_frames}
                self.assertEqual(len(seat_ids), 1, "三个会话进入的必须是同一座位")
                seat_id = seat_ids.pop()

                fates = await asyncio.gather(*(final_fate(socket) for socket in sockets))
                outcomes = [fate for _, fate in fates]
                self.assertEqual(outcomes.count("taken"), 2, "三个并发连接中恰好两个被接管")
                self.assertEqual(outcomes.count("alive"), 1, "必须恰好留下一个活动连接")
                survivor = next(socket for socket, fate in fates if fate == "alive")

                # 幸存者保持私有投影并能继续合法操作。
                await drain_inflight(survivor)
                await survivor.send(json.dumps({
                    "type": "command", "commandId": "probe-pass", "command": "pass-dagger",
                    "payload": {"targetPlayerId": next(p["playerId"] for p in first_frames[0]["game"]["players"] if p["playerId"] != seat_id)},
                    "expectedRevision": first_frames[0]["game"]["revision"],
                }))
                ack = await self.read_until(survivor, lambda m: m.get("type") == "ack")
                self.assertEqual(ack["status"], "accepted", "唯一幸存连接必须能完成合法操作")

                # 被接管的两个连接不再有任何后续帧（状态、事件、私有投影）。
                for socket, fate in fates:
                    if fate == "taken":
                        with self.assertRaises((websockets.ConnectionClosed, asyncio.TimeoutError)):
                            await asyncio.wait_for(socket.recv(), 0.5)

                # 对照：目标之外的合法账号连接不受并发接管影响（不同账号，不参与争抢）。
                async with self.connect(code, others[0]) as other:
                    other_state = await self.hello(other)
                    self.assertIsNotNone(other_state["yourPlayerId"], "并发接管不得影响其他账号的正常座位")
                    self.assertIsNotNone(other_state["game"]["viewer"], "其他账号的私有投影不受影响")
            finally:
                for socket in sockets:
                    try:
                        await socket.close()
                    except Exception:
                        pass

        asyncio.run(scenario())
        self.assertEqual(self.request(f"/api/rooms/{code}", None, host_cookie)[1]["playerCount"], 6, "并发接管不得增删座位")

    # ---- V05.04 ---------------------------------------------------------

    def test_v05_04_new_connection_retransmit_and_stale_revision_follow_existing_protocol(self):
        """新连接重复投递已确认命令沿用幂等（不重放公开事件），携带旧 revision 沿用冲突行为。"""
        code, holder_cookie, holder_display, host_cookie, others = asyncio.run(self.started_room_with_dagger_holder("回归"))

        async def scenario():
            # 观察连接用与被测座位不同账号的成员（持有者可能就是房主）。
            async with self.connect(code, others[0]) as host, self.connect(code, holder_cookie) as first:
                first_state = await self.hello(first)
                seat_id = first_state["yourPlayerId"]
                target = next(p["playerId"] for p in first_state["game"]["players"] if p["playerId"] != seat_id)
                revision = first_state["game"]["revision"]
                confirmed = {
                    "type": "command", "commandId": "confirmed-pass", "command": "pass-dagger",
                    "payload": {"targetPlayerId": target}, "expectedRevision": revision,
                }
                await first.send(json.dumps(confirmed))
                ack = await self.read_until(first, lambda m: m.get("type") == "ack")
                self.assertEqual(ack["status"], "accepted")
                confirmed_revision = (await self.read_state(first))["game"]["revision"]
                self.assertGreater(confirmed_revision, revision)
                await drain_inflight(host)  # 排空第一条 pass 的公开广播

                # 新设备接管。
                async with self.connect(code, self.login(holder_display)) as second:
                    await self.hello(second)
                    taken = json.loads(await asyncio.wait_for(first.recv(), 5))
                    self.assertEqual(taken["type"], "taken-over")
                    await drain_inflight(host)  # 排空接管广播

                    # 幂等重传：同 commandId 同内容 → accepted、revision 不变、不重放公开事件。
                    await second.send(json.dumps(confirmed))
                    frames = await self.collect(second)
                    ack = next(m for m in frames if m.get("type") == "ack")
                    self.assertEqual(ack["status"], "accepted", "已确认命令的重传必须幂等接受")
                    state = next(m for m in frames if m.get("type") == "state")
                    self.assertEqual(state["game"]["revision"], confirmed_revision, "幂等重传不得推进修订号")
                    # 房主（其他合法连接）不得收到该命令的公开事件重放。
                    with self.assertRaises(asyncio.TimeoutError):
                        await asyncio.wait_for(host.recv(), 0.5)

                    # 旧 revision：新 commandId 携带过期 expectedRevision → 冲突拒绝 + 最新 state。
                    await second.send(json.dumps({
                        "type": "command", "commandId": "stale-pass", "command": "pass-dagger",
                        "payload": {"targetPlayerId": target}, "expectedRevision": revision,
                    }))
                    frames = await self.collect(second)
                    self.assertEqual(next(m for m in frames if m.get("type") == "error")["code"],
                                     "game.revision-conflict")
                    self.assertEqual(next(m for m in frames if m.get("type") == "ack")["status"], "rejected")
                    self.assertEqual(next(m for m in frames if m.get("type") == "state")["game"]["revision"],
                                     confirmed_revision)

                    # 规则拒绝路径不受接管影响：非持有者传匕首仍按引擎规则拒绝。
                    await second.send(json.dumps({
                        "type": "command", "commandId": "not-holder", "command": "pass-dagger",
                        "payload": {"targetPlayerId": target}, "expectedRevision": confirmed_revision,
                    }))
                    frames = await self.collect(second)
                    self.assertEqual(next(m for m in frames if m.get("type") == "error")["code"],
                                     "player.not-dagger-holder")

        asyncio.run(scenario())

    # ---- 接管与普通断线的边界 -------------------------------------------

    def test_waiting_room_second_session_takes_over_and_keeps_host_authority(self):
        """等待阶段同账号新会话接管房主座位：旧连接停止，新连接保留房主操作；普通断线仍走恢复路径。"""
        account, first_cookie = self.signup("等待房主")
        code = self.create_room(first_cookie)

        async def scenario():
            async with self.connect(code, first_cookie) as first:
                await self.hello(first)
                async with self.connect(code, self.login("等待房主")) as second:
                    second_state = await self.hello(second)
                    self.assertTrue(second_state["isHost"], "接管的新连接保留房主身份")
                    taken = json.loads(await asyncio.wait_for(first.recv(), 5))
                    self.assertEqual(taken["type"], "taken-over")
                    with self.assertRaises(websockets.ConnectionClosed):
                        await asyncio.wait_for(first.recv(), 5)
                    # 新连接可继续合法的房主操作。
                    await second.send(json.dumps({"type": "host", "action": "lock"}))
                    await self.read_until(second, lambda m: m.get("type") == "state" and m["locked"])
                    self.assertTrue(self.request(f"/api/rooms/{code}", None, first_cookie)[1]["locked"])

        asyncio.run(scenario())
        # 普通断线（未被接管）：同 cookie 重连恢复原座位，与接管的终止路径可区分。
        state = asyncio.run(self._resume(code, first_cookie))
        self.assertTrue(state["isHost"], "普通断线重连走既有恢复路径，仍是房主")
        self.assertEqual(state["game"]["revision"], 1)

    async def _resume(self, code, cookie):
        async with self.connect(code, cookie) as again:
            return await self.hello(again)


if __name__ == "__main__":
    unittest.main()
