"""Ticket 17: invitation links carry only the room code through authentication.

Real uvicorn/HTTP/WS boundary (same isolated fixtures as 09/10/12): a friend who
opens an invitation with just the six-digit code registers or logs in, then
joins the target room bound to their own account; a target that cannot be
joined (unknown code, or the account already occupies another unfinished room)
reports the Chinese reason without ghost seats, and the original room keeps its
host and seats. Old name/token URL fields never authorize anything at the
protocol boundary.
"""

import asyncio
import json
import unittest

import websockets

from tests import test_accounts as account_tests


class AccountInvitationHTTPTests(unittest.TestCase):
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
        status, _, headers = self.request("/api/auth/login", {"username": name, "password": password})
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def create_room(self, cookie):
        status, room, _ = self.request("/api/rooms", {}, cookie)
        self.assertEqual(status, 200)
        return room["code"]

    def connect(self, code, cookie):
        return websockets.connect(f"ws://127.0.0.1:{self.port}/ws/{code}", additional_headers={"Cookie": cookie}, proxy=None)

    async def hello(self, code, cookie, **fields):
        """A hello with only account-cookie identity (the invitation client)."""
        async with self.connect(code, cookie) as socket:
            await socket.send(json.dumps({"type": "hello", "mode": "player", "protocolVersion": "4", **fields}))
            return json.loads(await asyncio.wait_for(socket.recv(), 3))

    def occupancy_of(self, cookie):
        return self.request("/api/account/room", cookie=cookie)[1]["room"]

    def test_invitation_room_code_joins_with_registered_identity_not_url_fields(self):
        # 邀请链接只携带房号：房主建房，拿到链接的新人注册后经房号加入，
        # 座位与 displayName 都来自注册账号，而不是链接里可能残留的旧字段。
        host_account, host_cookie = self.signup("邀请房主")
        code = self.create_room(host_cookie)
        guest_account, guest_cookie = self.signup("链接访客")

        state = asyncio.run(self.hello(code, guest_cookie))
        self.assertEqual(state["type"], "state")
        self.assertNotEqual(state["yourPlayerId"], None)
        self.assertEqual(
            [p["displayName"] for p in state["game"]["players"]],
            [host_account["username"], guest_account["username"]],
        )
        self.assertEqual(self.occupancy_of(guest_cookie)["code"], code)

        # 旧式链接的姓名/令牌若被旧客户端塞进 hello，一律拒绝且不认领他人身份。
        rejection = asyncio.run(self.hello(
            code, guest_cookie, name=host_account["username"], token="legacy-host-token",
        ))
        self.assertEqual(rejection["type"], "error")
        self.assertEqual(rejection["code"], "protocol.legacy-identity")
        self.assertIn("刷新", rejection["message"])
        # 被拒后房主座位与名册不变，访客占用仍是自己的座位。
        host_state = asyncio.run(self.hello(code, host_cookie))
        self.assertTrue(host_state["isHost"])
        self.assertEqual([p["displayName"] for p in host_state["game"]["players"]], [host_account["username"], guest_account["username"]])

    def test_invitation_while_occupied_keeps_single_seat_and_original_room_intact(self):
        # 已占其他未结束房间：邀请不创建第二个座位，按 roomCode 引导返回原房，
        # 原房的房主与座位保持，对照座位不受影响。
        host_account, host_cookie = self.signup("原房房主")
        original = self.create_room(host_cookie)
        _, member_cookie = self.signup("原房成员")
        member_first = asyncio.run(self.hello(original, member_cookie))
        _, witness_cookie = self.signup("对照成员")
        witness_first = asyncio.run(self.hello(original, witness_cookie))
        _, target_host_cookie = self.signup("目标房主")
        target = self.create_room(target_host_cookie)

        rejection = asyncio.run(self.hello(target, member_cookie))
        self.assertEqual(rejection["type"], "error")
        self.assertEqual(rejection["code"], "account.room-occupied")
        self.assertIn("返回原房间", rejection["message"])
        self.assertEqual(rejection["details"]["roomCode"], original)
        # 邀请不创建第二个座位：目标房只有房主，原房名册不变，成员占用未迁移。
        self.assertEqual(self.request(f"/api/rooms/{target}", None, host_cookie)[1]["playerCount"], 1)
        self.assertEqual(self.request(f"/api/rooms/{original}", None, host_cookie)[1]["playerCount"], 3)
        self.assertEqual(self.occupancy_of(member_cookie)["code"], original)

        # 按引导返回原房：恢复的是原座位，房主身份与对照座位保持。
        member_again = asyncio.run(self.hello(original, member_cookie))
        self.assertEqual(member_again["yourPlayerId"], member_first["yourPlayerId"])
        self.assertFalse(member_again["isHost"])
        host_state = asyncio.run(self.hello(original, host_cookie))
        self.assertTrue(host_state["isHost"])
        self.assertEqual(
            [p["displayName"] for p in host_state["game"]["players"]],
            [host_account["username"], "原房成员", "对照成员"],
        )
        witness_again = asyncio.run(self.hello(original, witness_cookie))
        self.assertEqual(witness_again["yourPlayerId"], witness_first["yourPlayerId"])

    def test_invitation_to_unknown_room_reports_chinese_reason_without_occupancy(self):
        # 不存在的房号（含已被管理关闭、不再活动的房间）：REST 概览 404 与
        # WS 错误帧都落在 room.not-found（前端映射为中文「房间不存在，请核对
        # 房间号。」，见 invitation.test.tsx / joinFailure.test.tsx），不产生
        # 座位或占用。
        _, cookie = self.signup("迷路访客")
        status, body, _ = self.request("/api/rooms/999999", None, cookie)
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "room.not-found")

        rejection = asyncio.run(self.hello("999999", cookie))
        self.assertEqual(rejection["type"], "error")
        self.assertEqual(rejection["code"], "room.not-found")
        self.assertIsNone(self.occupancy_of(cookie))


if __name__ == "__main__":
    unittest.main()
