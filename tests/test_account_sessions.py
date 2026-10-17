"""Ticket 14: fixed 30-day login expiry, logout and account switching.

Real uvicorn/HTTP/WS boundary (same isolated fixtures as 09/10): a session is
valid until its fixed 30-day point and no later (controlled clock / expiry
fixture, never a real 30-day wait); logout revokes only the current device's
session and stops its established room connection; expiry and revocation bind
HTTP and already-connected WebSockets alike while a retained valid session
keeps operating; re-login restores the original seat and host authority.
"""

import asyncio
import hashlib
import json
import sqlite3
import time
import unittest
from contextlib import closing
from pathlib import Path

import websockets

from tests import test_accounts as account_tests


class AccountSessionHTTPTests(unittest.TestCase):
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

    async def hello(self, socket, mode="player"):
        await socket.send(json.dumps({"type": "hello", "mode": mode, "protocolVersion": "4"}))
        return json.loads(await asyncio.wait_for(socket.recv(), 3))

    async def state_of(self, code, cookie, **fields):
        async with self.connect(code, cookie) as socket:
            return await self.hello(socket, **fields)

    # ---- 会话时点 fixture（受控到期点，不真实等待 30 天，无生产调时间入口） ----

    def _token_hash(self, cookie):
        token = cookie.split("=", 1)[1]
        return hashlib.sha256(token.encode()).hexdigest()

    def session_expiry(self, cookie):
        with closing(sqlite3.connect(Path(self.tmp.name) / "accounts" / "accounts.sqlite3")) as db:
            return db.execute("SELECT expires_at FROM sessions WHERE token_hash = ?", (self._token_hash(cookie),)).fetchone()[0]

    def set_session_expiry(self, cookie, value):
        """测试时钟推进：直接把该会话的固定到期点写成给定时刻（隔离测试库）。"""
        with closing(sqlite3.connect(Path(self.tmp.name) / "accounts" / "accounts.sqlite3")) as db:
            db.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?", (value, self._token_hash(cookie)))
            db.commit()

    # ---- V08.01 受控时钟/时点 fixture ------------------------------------

    def test_v08_01_fixed_expiry_boundary_uses_controlled_clock(self):
        """存储契约（公共 AccountStore 边界）：截止前一瞬有效、恰到期及之后失效；多次使用不续期。"""
        from server.accounts import AccountStore, SESSION_SECONDS
        _, cookie = self.signup("到期玩家")
        store = AccountStore(Path(self.tmp.name))
        token = cookie.split("=", 1)[1]
        with closing(sqlite3.connect(store.path)) as db:
            created_at, expires_at = db.execute(
                "SELECT created_at, expires_at FROM sessions WHERE token_hash = ?",
                (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        self.assertAlmostEqual(expires_at - created_at, SESSION_SECONDS, delta=1, msg="有效期必须是自登录时刻起固定 30 天")
        for now in (created_at, created_at + 60, expires_at - 1, expires_at - 0.001):
            self.assertIsNotNone(store.get_session(token, now=now), msg="截止前一瞬必须仍然有效")
        self.assertIsNone(store.get_session(token, now=expires_at), msg="恰到期必须已失效")
        self.assertIsNone(store.get_session(token, now=expires_at + 0.001), msg="到期后必须已失效")
        for _ in range(3):
            self.assertIsNotNone(store.get_session(token, now=created_at + 60))
        with closing(sqlite3.connect(store.path)) as db:
            unchanged = db.execute("SELECT expires_at FROM sessions WHERE token_hash = ?",
                                   (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()[0]
        self.assertEqual(unchanged, expires_at, "日常使用不得滚动续期")

    def test_v08_01_expiry_point_survives_usage_and_restart(self):
        """真实服务 + 时点 fixture：期间多次使用不续期；推进到过期后全部视为未登录；重启不改变到期点。"""
        _, cookie = self.signup("重启到期玩家")
        for _ in range(3):
            self.assertEqual(self.request("/api/auth/session", cookie=cookie)[0], 200)
        original = self.session_expiry(cookie)
        # 推进到截止前一瞬（仍余数秒）→ 仍有效
        self.set_session_expiry(cookie, time.time() + 5)
        self.assertEqual(self.request("/api/auth/session", cookie=cookie)[0], 200, "截止前一瞬必须仍然有效")
        # 推进到已过期 → 所有请求视为未登录
        expired_point = time.time() - 0.001
        self.set_session_expiry(cookie, expired_point)
        self.assertEqual(self.request("/api/auth/session", cookie=cookie)[0], 401)
        status, body, _ = self.request("/api/auth/session", cookie=cookie)
        self.assertEqual(body["code"], "auth.login-required")
        self.assertEqual(self.request("/api/rooms", {}, cookie)[0], 401, "过期必须同样约束受保护入口")
        # 重启后到期点不改变：仍过期，且到期点数值保持
        self.stop_server()
        self.start_server()
        status, body, _ = self.request("/api/auth/session", cookie=cookie)
        self.assertEqual(status, 401)
        self.assertEqual(body["code"], "auth.login-required")
        self.assertEqual(self.session_expiry(cookie), expired_point, "重启不得改变或重算到期点")
        self.assertNotEqual(self.session_expiry(cookie), original)

    # ---- V08.03 多会话退出 -----------------------------------------------

    def test_v08_03_logout_revokes_only_current_device(self):
        """退出当前设备只撤销当前登录：另一设备独立登录不受影响；已退出凭证重放 HTTP/WS 不能恢复。"""
        account, first = self.signup("多设备玩家")
        second = self.login("多设备玩家")
        status, body, headers = self.request("/api/auth/logout", {}, first)
        self.assertEqual(status, 200)
        self.assertEqual(body["account"], account, "退出响应只携带公开账号对象，不回显凭证")
        # 已退出凭证：HTTP 重放不能恢复身份
        self.assertEqual(self.request("/api/auth/session", cookie=first)[0], 401)
        # 重放退出请求同样按未登录处理
        self.assertEqual(self.request("/api/auth/logout", {}, first)[0], 401)
        # 其他设备的独立登录不受影响
        status, body, _ = self.request("/api/auth/session", cookie=second)
        self.assertEqual(status, 200)
        self.assertEqual(body["account"], account)
        # WS 重放已退出凭证：未登录拒绝并关闭
        async def replay():
            async with self.connect("000000", first) as socket:
                return json.loads(await asyncio.wait_for(socket.recv(), 3))
        rejection = asyncio.run(replay())
        self.assertEqual(rejection["code"], "auth.login-required")

    def test_v08_03_logout_clears_browser_cookie_and_does_not_log(self):
        """退出成功清除浏览器 Cookie；凭证与密码不进入服务日志。"""
        _, cookie = self.signup("清凭证玩家")
        status, _, headers = self.request("/api/auth/logout", {}, cookie)
        self.assertEqual(status, 200)
        set_cookie = headers.get("Set-Cookie") or ""
        self.assertIn("Max-Age=0", set_cookie, "退出必须清除浏览器中的会话 Cookie")
        token = cookie.split("=", 1)[1]
        self.stop_server()
        output = self.log_path.read_text()
        self.assertNotIn(token, output, "会话凭证不得写入服务日志")

    # ---- V08.02 真实已连接 WS：退出/过期约束已建立连接 -------------------

    async def _prepare_playing_room_with_dagger_on(self, host_cookie, target_cookie, extra_cookies):
        """开局到 playing 并把匕首交到 target 手里，使 target 持有原本合法动作。

        返回 (sockets, target_socket, host_socket, target_state, code)；sockets 由调用方关闭。
        """
        code = self.create_room(host_cookie)
        sockets = []

        async def join(cookie):
            socket = await self.connect(code, cookie)
            sockets.append(socket)
            return await self.hello(socket)

        async def next_state(socket, status=None, revision=0):
            while True:
                message = json.loads(await asyncio.wait_for(socket.recv(), 5))
                if message.get("type") == "state" and (status is None or message.get("roomStatus") == status) \
                        and message["game"]["revision"] >= revision:
                    return message
                if message.get("type") == "error":
                    raise AssertionError(message)

        try:
            await join(host_cookie)
            host_socket = sockets[0]
            target_state = await join(target_cookie)
            target_socket = sockets[-1]
            for cookie in extra_cookies:
                await join(cookie)
            await host_socket.send(json.dumps({"type": "host", "action": "start"}))
            states = await asyncio.gather(*(next_state(socket, status="playing") for socket in sockets))
            target_id = target_state["yourPlayerId"]
            # 统一取开局后（playing）target 自己视角的 state：开局后匕首可能本来就在 target 手里
            target_state = next(state for state in states if state["yourPlayerId"] == target_id)
            holder_state = next(state for state in states if state["game"]["daggerHolderId"] == state["yourPlayerId"])
            if holder_state["yourPlayerId"] != target_id:
                # 匕首在别人手里：让持有者把它传给 target，使 target 拥有原本合法动作
                holder_socket = sockets[states.index(holder_state)]
                if not any(a["type"] == "pass-dagger" and a["targetPlayerId"] == target_id
                           for a in holder_state["game"]["legalActions"]):
                    raise AssertionError("匕首持有者的合法动作必须能传给目标")
                await holder_socket.send(json.dumps({
                    "type": "command", "command": "pass-dagger",
                    "payload": {"targetPlayerId": target_id},
                    "commandId": "handover-to-target", "expectedRevision": holder_state["game"]["revision"],
                }))
                refreshed = await asyncio.gather(*(
                    next_state(socket, revision=states[0]["game"]["revision"] + 1) for socket in sockets))
                target_state = next(state for state in refreshed if state["yourPlayerId"] == target_id)
            self.assertEqual(target_state["game"]["daggerHolderId"], target_id, "匕首必须已传到目标手里")
            return sockets, target_socket, host_socket, target_state, code
        except Exception:
            await asyncio.gather(*(socket.close() for socket in sockets), return_exceptions=True)
            raise

    def test_v08_02_logout_stops_established_playing_connection_without_releasing_seat(self):
        """退出登录停止其已建立的房间连接：后续操作失败、私有帧停止；合法连接不受影响；座位保留。"""
        _, host_cookie = self.signup("撤销房主")
        _, b_cookie = self.signup("被撤销玩家")
        extras = [self.signup(f"撤销补位{i}") for i in range(4)]

        async def scenario():
            sockets, b_socket, host_socket, b_state, code = await self._prepare_playing_room_with_dagger_on(
                host_cookie, b_cookie, [cookie for _, cookie in extras])
            try:
                self.assertEqual(b_state["game"]["daggerHolderId"], b_state["yourPlayerId"])
                b_id = b_state["yourPlayerId"]
                # B 在本设备退出登录（其他设备/账号的登录不受影响）
                status, _, _ = self.request("/api/auth/logout", {}, b_cookie)
                self.assertEqual(status, 200)
                # 已建立的旧连接收到撤销说明并被关闭
                message = json.loads(await asyncio.wait_for(b_socket.recv(), 3))
                self.assertEqual(message["type"], "error")
                self.assertEqual(message["code"], "auth.session-revoked")
                self.assertIn("重新登录", message["message"], "撤销原因必须是简体中文")
                with self.assertRaises(websockets.ConnectionClosed):
                    await asyncio.wait_for(b_socket.recv(), 3)
                # 旧连接再发原本合法动作：连接已停止，操作失败
                with self.assertRaises(websockets.ConnectionClosed):
                    await b_socket.send(json.dumps({"type": "host", "action": "lock"}))
                # 对照组：保留的合法连接（房主）仍能操作
                await host_socket.send(json.dumps({"type": "host", "action": "lock"}))
                while True:
                    message = json.loads(await asyncio.wait_for(host_socket.recv(), 5))
                    if message.get("type") == "state" and message.get("locked"):
                        break
                # 私有帧停止：B 的旧连接收不到这次广播
                with self.assertRaises(websockets.ConnectionClosed):
                    await asyncio.wait_for(b_socket.recv(), 1)
                # 退出不移除座位、不改归属：占用与人数保留
                self.assertEqual(self.request(f"/api/rooms/{code}", None, host_cookie)[1]["playerCount"], 6)
                # 重新登录同账号恢复原座位（V08.05 的退出路径）
                b_new = self.login("被撤销玩家")
                room = self.request("/api/account/room", cookie=b_new)[1]["room"]
                self.assertEqual((room or {}).get("code"), code, "退出不能释放座位占用")
                async with self.connect(code, b_new) as resumed_socket:
                    resumed = await self.hello(resumed_socket)
                self.assertEqual(resumed["yourPlayerId"], b_id, "重新登录必须恢复原座位")
                self.assertEqual(self.request(f"/api/rooms/{code}", None, host_cookie)[1]["playerCount"], 6, "恢复不得新建重复玩家")
                # 其他账号的独立登录不受影响（补位玩家仍有效）
                self.assertEqual(self.request("/api/auth/session", cookie=extras[0][1])[0], 200)
                # 房主归属不变：房主自己的连接仍持有管理权
                await host_socket.send(json.dumps({"type": "host", "action": "unlock"}))
                while True:
                    message = json.loads(await asyncio.wait_for(host_socket.recv(), 5))
                    if message.get("type") == "state" and not message.get("locked"):
                        break
            finally:
                await asyncio.gather(*(socket.close() for socket in sockets), return_exceptions=True)

        asyncio.run(scenario())

    def test_v08_02_expiry_stops_established_connection_and_private_frames(self):
        """推进至过期：已建立连接原本合法的动作被拒为登录过期，私有帧停止；对照组连接仍能操作。"""
        _, host_cookie = self.signup("过期房主")
        _, b_cookie = self.signup("过期玩家")
        extras = [self.signup(f"过期补位{i}") for i in range(4)]

        async def scenario():
            sockets, b_socket, host_socket, b_state, code = await self._prepare_playing_room_with_dagger_on(
                host_cookie, b_cookie, [cookie for _, cookie in extras])
            try:
                b_id = b_state["yourPlayerId"]
                action = next(a for a in b_state["game"]["legalActions"] if a["type"] == "pass-dagger")
                # 测试时钟推进：B 的会话到点
                self.set_session_expiry(b_cookie, time.time() - 0.001)
                # 旧连接发送原本合法的动作 → 被拒为登录过期，而不是执行
                await b_socket.send(json.dumps({
                    "type": "command", "command": "pass-dagger",
                    "payload": {"targetPlayerId": action["targetPlayerId"]},
                    "commandId": "action-after-expiry",
                    "expectedRevision": b_state["game"]["revision"],
                }))
                message = json.loads(await asyncio.wait_for(b_socket.recv(), 3))
                self.assertEqual(message["type"], "error", "过期的已建立连接必须收到错误而非 ack/state")
                self.assertEqual(message["code"], "auth.session-expired")
                self.assertIn("重新登录", message["message"], "过期原因必须是简体中文")
                with self.assertRaises(websockets.ConnectionClosed):
                    await asyncio.wait_for(b_socket.recv(), 3)
                # 对照组：保留的合法连接（房主）仍能操作
                await host_socket.send(json.dumps({"type": "host", "action": "lock"}))
                host_locked = None
                while True:
                    message = json.loads(await asyncio.wait_for(host_socket.recv(), 5))
                    if message.get("type") == "state" and message.get("locked"):
                        host_locked = message
                        break
                # B 的命令没有被执行：匕首仍在 B 手里
                self.assertEqual(host_locked["game"]["daggerHolderId"], b_id, "过期连接的动作不得被引擎执行")
                # 私有帧停止：B 的旧连接收不到这次广播
                with self.assertRaises(websockets.ConnectionClosed):
                    await asyncio.wait_for(b_socket.recv(), 1)
                # 过期同样约束 HTTP：B 的 Cookie 不能再查询身份或占用
                self.assertEqual(self.request("/api/auth/session", cookie=b_cookie)[0], 401)
                self.assertEqual(self.request("/api/account/room", cookie=b_cookie)[0], 401)
            finally:
                await asyncio.gather(*(socket.close() for socket in sockets), return_exceptions=True)

        asyncio.run(scenario())

    # ---- V08.05 失效后重新登录恢复 ---------------------------------------

    def test_v08_05_relogin_after_expiry_restores_seat_and_host(self):
        """到期后重新登录同账号：恢复原座位与房主身份，不新建重复玩家、不释放占用。"""
        _, host_cookie = self.signup("过期房主")
        code = self.create_room(host_cookie)
        _, b_cookie = self.signup("过期玩家")
        before = asyncio.run(self.state_of(code, b_cookie))
        # 两个会话都推进到过期
        self.set_session_expiry(host_cookie, time.time() - 0.001)
        self.set_session_expiry(b_cookie, time.time() - 0.001)
        self.assertEqual(self.request("/api/auth/session", cookie=host_cookie)[0], 401)
        self.assertEqual(self.request("/api/auth/session", cookie=b_cookie)[0], 401)
        self.assertEqual(self.request("/api/account/room", cookie=b_cookie)[0], 401, "过期后占用查询同样视为未登录")
        # 重新登录同账号
        host_new = self.login("过期房主")
        b_new = self.login("过期玩家")
        self.assertEqual(self.request("/api/account/room", cookie=b_new)[1]["room"]["code"], code, "重新登录必须恢复原房间占用")
        self.assertEqual(self.request("/api/account/room", cookie=host_new)[1]["room"]["code"], code)
        resumed = asyncio.run(self.state_of(code, b_new))
        self.assertEqual(resumed["yourPlayerId"], before["yourPlayerId"], "重新登录必须恢复原座位")
        host_resumed = asyncio.run(self.state_of(code, host_new))
        self.assertTrue(host_resumed["isHost"], "重新登录必须恢复房主身份")
        self.assertEqual(self.request(f"/api/rooms/{code}", None, host_new)[1]["playerCount"], 2, "恢复不得新建重复玩家")


if __name__ == "__main__":
    unittest.main()
