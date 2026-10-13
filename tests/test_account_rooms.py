import asyncio
import json
import unittest

import websockets

from tests import test_accounts as account_tests


class AccountRoomHTTPTests(unittest.TestCase):
    setUp = account_tests.RegistrationHTTPTests.setUp
    start_server = account_tests.RegistrationHTTPTests.start_server
    stop_server = account_tests.RegistrationHTTPTests.stop_server
    request = account_tests.RegistrationHTTPTests.request
    register = account_tests.RegistrationHTTPTests.register

    def signup(self, name):
        status, body, headers = self.register(name)
        self.assertEqual(status, 201)
        return body["account"], headers["Set-Cookie"].split(";", 1)[0]

    def connect(self, code, cookie):
        return websockets.connect(f"ws://127.0.0.1:{self.port}/ws/{code}", additional_headers={"Cookie": cookie}, proxy=None)

    async def hello(self, socket, **fields):
        await socket.send(json.dumps({"type": "hello", "mode": "player", "protocolVersion": "4", **fields}))
        return json.loads(await asyncio.wait_for(socket.recv(), 3))

    def test_create_automatically_binds_account_host_and_player_seat(self):
        account, cookie = self.signup("房主小明")
        status, room, _ = self.request("/api/rooms", {}, cookie)
        self.assertEqual(status, 200)
        self.assertNotIn("hostToken", room)
        async def observe():
            async with self.connect(room["code"], cookie) as socket:
                state = await self.hello(socket)
                self.assertEqual(state["type"], "state")
                self.assertTrue(state["isHost"])
                self.assertEqual(state["yourPlayerId"], state["hostPlayerId"])
                self.assertEqual(len(state["game"]["players"]), 1)
                self.assertEqual(state["game"]["players"][0]["displayName"], account["username"])
                self.assertEqual(state["hostActions"], [{"type": "start-game"}, {"type": "lock"}])
                await socket.send(json.dumps({"type": "host", "action": "lock"}))
                locked = json.loads(await asyncio.wait_for(socket.recv(), 3))
                self.assertTrue(locked["locked"])
                await socket.send(json.dumps({"type": "host", "action": "unlock"}))
                unlocked = json.loads(await asyncio.wait_for(socket.recv(), 3))
                self.assertFalse(unlocked["locked"])
        asyncio.run(observe())

    def test_creation_retry_and_restart_restore_same_host_room_and_seat(self):
        _, cookie = self.signup("重试房主")
        _, room, _ = self.request("/api/rooms", {}, cookie)
        self.assertEqual(self.request("/api/rooms", {}, cookie)[1], room)
        async def seat():
            async with self.connect(room["code"], cookie) as socket:
                return await self.hello(socket)
        before = asyncio.run(seat())
        self.stop_server()
        self.start_server()
        self.assertEqual(self.request("/api/account/room", cookie=cookie)[1]["room"]["code"], room["code"])
        after = asyncio.run(seat())
        self.assertTrue(after["isHost"])
        self.assertEqual(after["yourPlayerId"], before["yourPlayerId"])
        self.assertEqual(len(after["game"]["players"]), 1)

    def test_guest_occupancy_cannot_be_misreported_as_a_created_host_room(self):
        _, host_cookie = self.signup("原房主")
        _, room, _ = self.request("/api/rooms", {}, host_cookie)
        _, guest_cookie = self.signup("普通玩家")
        async def join():
            async with self.connect(room["code"], guest_cookie) as socket:
                self.assertFalse((await self.hello(socket))["isHost"])
        asyncio.run(join())
        status, error, _ = self.request("/api/rooms", {}, guest_cookie)
        self.assertEqual(status, 409)
        self.assertEqual(error["details"]["roomCode"], room["code"])
        self.assertIn("已有", error["message"])

    def test_anonymous_invalid_cookie_and_legacy_identity_cannot_create_or_manage(self):
        _, host_cookie = self.signup("真正房主")
        _, room, _ = self.request("/api/rooms", {}, host_cookie)
        for cookie in [None, "bloodbound_session=invalid"]:
            self.assertEqual(self.request("/api/rooms", {}, cookie)[0], 401)
        _, guest_cookie = self.signup("伪造玩家")
        for data in [{"username": "真正房主"}, {"hostToken": "legacy-token"}]:
            self.assertEqual(self.request("/api/rooms", data, guest_cookie)[0], 400)
        async def attack():
            for cookie in ["", "bloodbound_session=invalid"]:
                async with self.connect(room["code"], cookie) as socket:
                    self.assertEqual(json.loads(await socket.recv())["code"], "auth.login-required")
            async with self.connect(room["code"], guest_cookie) as socket:
                self.assertEqual((await self.hello(socket, name="真正房主", token="legacy-token"))["code"], "protocol.legacy-identity")
            async with self.connect(room["code"], guest_cookie) as socket:
                self.assertFalse((await self.hello(socket))["isHost"])
                for action in ["start", "lock", "unlock"]:
                    await socket.send(json.dumps({"type": "host", "action": action}))
                    self.assertEqual(json.loads(await socket.recv())["code"], "room.not-host")
        asyncio.run(attack())
        self.assertEqual(self.request(f"/api/rooms/{room['code']}")[1]["status"], "waiting")
        self.assertFalse(self.request(f"/api/rooms/{room['code']}")[1]["locked"])

    def test_actual_filesystem_failure_does_not_leave_half_room_and_retry_succeeds(self):
        from pathlib import Path
        from server.accounts import AccountStore
        from server.rooms import RoomManager
        from blood_bound import SaveError
        root = Path(self.tmp.name)
        account, _ = AccountStore(root).register("故障房主", "123456", "123456")
        directory = root / "room-storage"
        manager = RoomManager(directory)
        directory.rmdir()
        directory.write_text("真实文件阻止房间目录写入", encoding="utf-8")
        with self.assertRaises((OSError, SaveError)):
            manager.create_room(account)
        self.assertIsNone(manager.room_for_account(account.account_id))
        directory.unlink()
        directory.mkdir()
        room = manager.create_room(account)
        restored = RoomManager(directory)
        restored.restore()
        self.assertEqual(restored.room_for_account(account.account_id).code, room.code)
        self.assertEqual(len(restored.rooms), 1)
