"""Ticket 15: proactive password change revoking other devices' logins.

Real uvicorn/HTTP/WS boundary (same isolated fixtures as 09/10/14): changing
the password verifies the old one, keeps the current login with its original
fixed 30-day expiry, revokes every other session of the same account and
stops their established room connections; any failure leaves the password
and all sessions untouched. Seats and host ownership never change here.
"""

import asyncio
import hashlib
import json
import os
import sqlite3
import stat
import unittest
from contextlib import closing
from pathlib import Path

import websockets

from server.accounts import AccountError

from tests import test_account_sessions as session_tests


class AccountPasswordChangeTests(unittest.TestCase):
    setUp = session_tests.AccountSessionHTTPTests.setUp
    start_server = session_tests.AccountSessionHTTPTests.start_server
    stop_server = session_tests.AccountSessionHTTPTests.stop_server
    request = session_tests.AccountSessionHTTPTests.request
    register = session_tests.AccountSessionHTTPTests.register
    signup = session_tests.AccountSessionHTTPTests.signup
    login = session_tests.AccountSessionHTTPTests.login
    create_room = session_tests.AccountSessionHTTPTests.create_room
    connect = session_tests.AccountSessionHTTPTests.connect
    hello = session_tests.AccountSessionHTTPTests.hello
    state_of = session_tests.AccountSessionHTTPTests.state_of
    session_expiry = session_tests.AccountSessionHTTPTests.session_expiry
    set_session_expiry = session_tests.AccountSessionHTTPTests.set_session_expiry
    _token_hash = session_tests.AccountSessionHTTPTests._token_hash

    def change(self, cookie, old_password, new_password, confirmation=None):
        return self.request("/api/auth/password", {
            "oldPassword": old_password, "newPassword": new_password,
            "confirmPassword": new_password if confirmation is None else confirmation,
        }, cookie)

    # ---- V09.01 公共存储契约 ----------------------------------------------

    def test_v09_01_change_password_store_contract(self):
        """改密存储边界：校验旧密码与新密码；成功只撤销其他会话并保留当前会话原到期点。"""
        from server.accounts import AccountStore
        _, first = self.signup("改密玩家")
        second = self.login("改密玩家")
        third = self.login("改密玩家")
        store = AccountStore(Path(self.tmp.name))
        current_token = first.split("=", 1)[1]
        expiry_before = self.session_expiry(first)
        # 旧密码错误：拒绝且不改变密码或任何会话
        with self.assertRaises(AccountError) as rejected:
            store.change_password(current_token, "错误旧码", "654321", "654321")
        self.assertEqual(rejected.exception.code, "auth.wrong-old-password")
        self.assertIn("旧密码", str(rejected.exception))
        self.assertIsNotNone(store.verify_credentials("改密玩家", "123456"), "旧密码错误不得改变原密码")
        for cookie in (first, second, third):
            self.assertEqual(self.request("/api/auth/session", cookie=cookie)[0], 200, "旧密码错误不得改动会话")
        # 新密码边界：5/13 字符与确认不一致同样拒绝且无副作用
        for new_password, confirmation, code in [
            ("12345", "12345", "auth.invalid-password"),
            ("1234567890123", "1234567890123", "auth.invalid-password"),
            ("654321", "654322", "auth.password-mismatch"),
        ]:
            with self.subTest(code=code):
                with self.assertRaises(AccountError) as rejected:
                    store.change_password(current_token, "123456", new_password, confirmation)
                self.assertEqual(rejected.exception.code, code)
        self.assertIsNotNone(store.verify_credentials("改密玩家", "123456"), "校验失败不得改变原密码")
        self.assertIsNotNone(store.get_session(second.split("=", 1)[1]))
        # 成功：撤销其他全部会话（返回其 token 摘要供服务层停止连接），当前会话保留原到期点
        account, revoked = store.change_password(current_token, "123456", "654321", "654321")
        self.assertEqual(account.username, "改密玩家")
        self.assertEqual(revoked, {self._token_hash(second), self._token_hash(third)}, "同账号其他会话必须全部撤销")
        self.assertNotIn(self._token_hash(first), revoked, "当前会话不得被撤销")
        self.assertIsNotNone(store.get_session(current_token), "改密必须保留当前登录")
        self.assertIsNone(store.get_session(second.split("=", 1)[1]))
        self.assertIsNone(store.get_session(third.split("=", 1)[1]))
        self.assertEqual(self.session_expiry(first), expiry_before, "改密不得延长当前登录原 30 天截止")
        # 新密码生效，旧密码不能再通过凭证校验
        self.assertIsNone(store.verify_credentials("改密玩家", "123456"))
        self.assertIsNotNone(store.verify_credentials("改密玩家", "654321"))
        # 未登录/已失效凭证不能改密
        with self.assertRaises(AccountError) as rejected:
            store.change_password("not-a-real-token", "123456", "654321", "654321")
        self.assertEqual(rejected.exception.code, "auth.login-required")
        self.assertEqual(rejected.exception.status, 401)
        self.assertIsNotNone(store.verify_credentials("改密玩家", "654321"), "未登录改密不得改动密码")

    # ---- V09.01 HTTP/前端边界 ----------------------------------------------

    def test_v09_01_password_change_http_boundaries(self):
        """改密 API 边界：旧密码错误、新密码 5/13 字符与确认不一致均中文拒绝且无副作用；6/12 成功。"""
        from server.accounts import AccountStore
        account, first = self.signup("边界改密")
        second = self.login("边界改密")
        store = AccountStore(Path(self.tmp.name))
        # 旧密码错误：400 中文反馈，不改密码、不动会话
        status, body, _ = self.change(first, "错误旧码", "654321")
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "auth.wrong-old-password")
        self.assertIn("旧密码", body["message"])
        # 新密码 5/13 字符：与注册同一规则
        for new_password in ("12345", "1234567890123"):
            with self.subTest(length=len(new_password)):
                status, body, _ = self.change(first, "123456", new_password)
                self.assertEqual(status, 400)
                self.assertEqual(body["code"], "auth.invalid-password")
                self.assertIn("6–12", body["message"])
        # 确认不一致
        status, body, _ = self.change(first, "123456", "654321", "654322")
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "auth.password-mismatch")
        # 失败全部无副作用：原密码仍可登录，两个会话仍有效
        self.assertIsNotNone(store.verify_credentials("边界改密", "123456"))
        self.assertEqual(self.login("边界改密").startswith("bloodbound_session="), True)
        self.assertEqual(self.request("/api/auth/session", cookie=first)[0], 200)
        self.assertEqual(self.request("/api/auth/session", cookie=second)[0], 200)
        # 成功边界：6 字符与 12 字符新密码均可设置
        status, body, headers = self.change(first, "123456", "654321")
        self.assertEqual(status, 200)
        self.assertEqual(body["account"], account, "成功响应只携带公开账号对象")
        self.assertEqual(set(body), {"account"})
        self.assertIn("no-store", headers.get("Cache-Control", ""))
        self.assertNotIn("654321", json.dumps(body), "响应不得回显密码")
        # 旧密码不能再登录，新密码可以；当前登录保留，其他设备撤销
        self.assertEqual(self.request("/api/auth/login", {"username": "边界改密", "password": "123456"})[0], 401)
        self.assertEqual(self.request("/api/auth/session", cookie=first)[0], 200)
        self.assertEqual(self.request("/api/auth/session", cookie=second)[0], 401)
        status, body, _ = self.change(first, "654321", "123456789012")
        self.assertEqual(status, 200, "12 字符新密码在边界内必须成功")
        self.assertEqual(self.request("/api/auth/login", {"username": "边界改密", "password": "123456789012"})[0], 200)
        # 未登录不能改密
        status, body, _ = self.change("bloodbound_session=forged", "123456789012", "1234567")
        self.assertEqual(status, 401)
        self.assertEqual(body["code"], "auth.login-required")
        # 无效 JSON 与非对象请求体
        for payload in (b"{broken", b"[1,2]"):
            import urllib.request, urllib.error
            request = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/auth/password", data=payload,
                headers={"Content-Type": "application/json", "Cookie": first})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                response = opener.open(request)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                self.assertEqual(response.status, 400)
                self.assertEqual(json.load(response)["code"], "auth.invalid-input")
        self.assertIsNotNone(store.verify_credentials("边界改密", "123456789012"), "无效请求不得改动密码")

    # ---- V09.02 多会话/真实 WS：改密撤销其他设备 ---------------------------

    def test_v09_02_change_password_revokes_other_devices_established_ws(self):
        """A 改密后当前设备照常操作；其他设备 HTTP 与已建 WS 均失效；新密码重登恢复原身份。"""
        account, first = self.signup("改密房主")
        second = self.login("改密房主")
        third = self.login("改密房主")
        extras = [self.signup(f"改密补位{i}") for i in range(5)]

        async def scenario():
            code = self.create_room(first)
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
                host_state = await join(first)
                host_socket = sockets[0]
                a_id = host_state["yourPlayerId"]
                for _, cookie in extras:
                    await join(cookie)
                await host_socket.send(json.dumps({"type": "host", "action": "start"}))
                playing = await asyncio.gather(*(next_state(socket, status="playing") for socket in sockets))
                # 把匕首交到 A 手里，使当前设备持有原本合法的玩家动作
                a_state = next(state for state in playing if state["yourPlayerId"] == a_id)
                holder_state = next(state for state in playing if state["game"]["daggerHolderId"] == state["yourPlayerId"])
                if holder_state["yourPlayerId"] != a_id:
                    holder_socket = sockets[playing.index(holder_state)]
                    await holder_socket.send(json.dumps({
                        "type": "command", "command": "pass-dagger",
                        "payload": {"targetPlayerId": a_id},
                        "commandId": "handover-to-a", "expectedRevision": holder_state["game"]["revision"],
                    }))
                    refreshed = await asyncio.gather(*(
                        next_state(socket, revision=playing[0]["game"]["revision"] + 1) for socket in sockets))
                    a_state = next(state for state in refreshed if state["yourPlayerId"] == a_id)
                self.assertEqual(a_state["game"]["daggerHolderId"], a_id, "匕首必须已传到改密账号手里")
                # 改密前先建立第二个设备的已连接 WS（旁观视角），第三台设备只有 HTTP 登录
                spectator_socket = await self.connect(code, second)
                sockets.append(spectator_socket)
                spectator_state = await self.hello(spectator_socket, mode="spectator")
                self.assertIsNone(spectator_state["yourPlayerId"])
                self.assertEqual(self.request("/api/auth/session", cookie=third)[0], 200)
                # 当前设备（device1）验证旧密码改密
                status, body, _ = self.change(first, "123456", "654321")
                self.assertEqual(status, 200)
                # 其他设备的已建立 WS：收到中文撤销说明并被关闭
                message = json.loads(await asyncio.wait_for(spectator_socket.recv(), 3))
                self.assertEqual(message["type"], "error")
                self.assertEqual(message["code"], "auth.password-changed")
                self.assertIn("密码已修改", message["message"])
                self.assertIn("重新登录", message["message"])
                with self.assertRaises(websockets.ConnectionClosed):
                    await asyncio.wait_for(spectator_socket.recv(), 3)
                # 旧连接再发消息：连接已停止，操作失败
                with self.assertRaises(websockets.ConnectionClosed):
                    await spectator_socket.send(json.dumps({"type": "host", "action": "lock"}))
                # 当前设备连接照常：原本合法动作被确认执行（双向对照）
                action = next(a for a in a_state["game"]["legalActions"] if a["type"] == "pass-dagger")
                await host_socket.send(json.dumps({
                    "type": "command", "command": "pass-dagger",
                    "payload": {"targetPlayerId": action["targetPlayerId"]},
                    "commandId": "current-device-after-change", "expectedRevision": a_state["game"]["revision"],
                }))
                while True:
                    message = json.loads(await asyncio.wait_for(host_socket.recv(), 5))
                    if message.get("type") == "ack" and message.get("commandId") == "current-device-after-change":
                        self.assertEqual(message["status"], "accepted", "当前设备的合法动作必须照常执行")
                        break
                    if message.get("type") == "error":
                        raise AssertionError(message)
                # 私有帧停止：其他设备的旧连接收不到这次广播
                with self.assertRaises(websockets.ConnectionClosed):
                    await asyncio.wait_for(spectator_socket.recv(), 1)
                # HTTP：其他两台设备全部失效，当前登录保留
                self.assertEqual(self.request("/api/auth/session", cookie=first)[0], 200)
                self.assertEqual(self.request("/api/auth/session", cookie=second)[0], 401)
                self.assertEqual(self.request("/api/auth/session", cookie=third)[0], 401)
                # 旧密码不能再登录（中文反馈），新密码可以
                status, body, _ = self.request("/api/auth/login", {"username": "改密房主", "password": "123456"})
                self.assertEqual(status, 401)
                self.assertEqual(body["code"], "auth.invalid-credentials")
                status, body, headers = self.request("/api/auth/login", {"username": "改密房主", "password": "654321"})
                self.assertEqual(status, 200)
                # 新密码重登恢复原身份：仍指向原房、房主与座位保持、无重复玩家
                renewed = headers["Set-Cookie"].split(";", 1)[0]
                room = self.request("/api/account/room", cookie=renewed)[1]["room"]
                self.assertEqual((room or {}).get("code"), code, "改密不能释放座位占用")
                async with self.connect(code, renewed) as resumed:
                    resumed_state = await self.hello(resumed, mode="spectator")
                self.assertEqual(resumed_state["hostPlayerId"], a_id, "房主归属保持")
                self.assertEqual(resumed_state["roomStatus"], "playing")
                self.assertEqual(self.request(f"/api/rooms/{code}")[1]["playerCount"], 6, "改密不得改变座位占用")
                # 补位对照账号不受影响
                self.assertEqual(self.request("/api/auth/session", cookie=extras[0][1])[0], 200)
            finally:
                await asyncio.gather(*(socket.close() for socket in sockets), return_exceptions=True)

        asyncio.run(scenario())

    # ---- V09.03 时钟/重启 ---------------------------------------------------

    def test_v09_03_change_password_keeps_expiry_and_survives_restart(self):
        """改密不延长当前登录原 30 天截止；重启后新密码生效、旧密码与被撤销会话仍无效。"""
        _, first = self.signup("重启改密")
        second = self.login("重启改密")
        expiry_before = self.session_expiry(first)
        status, _, _ = self.change(first, "123456", "654321")
        self.assertEqual(status, 200)
        self.assertEqual(self.session_expiry(first), expiry_before, "改密不得延长当前登录原 30 天截止")
        self.assertEqual(self.request("/api/auth/session", cookie=first)[0], 200)
        # 完整重启同存档目录（真实进程，不用内存对象替代）
        self.stop_server()
        self.start_server()
        self.assertEqual(self.request("/api/auth/session", cookie=first)[0], 200, "重启后当前登录必须保留")
        self.assertEqual(self.session_expiry(first), expiry_before, "重启不得重算或延长到期点")
        self.assertEqual(self.request("/api/auth/session", cookie=second)[0], 401, "被撤销会话重启后仍无效")
        self.assertEqual(self.request("/api/auth/login", {"username": "重启改密", "password": "123456"})[0], 401, "旧密码重启后仍不能登录")
        self.assertEqual(self.request("/api/auth/login", {"username": "重启改密", "password": "654321"})[0], 200, "新密码重启后必须生效")

    # ---- V09.04 失败注入 ----------------------------------------------------

    def test_v09_04_store_write_failure_is_atomic_and_retry_consistent(self):
        """存储写入失败（真实只读数据库）：改密抛真实 sqlite 错误，密码与会话零改动；恢复后重试一致。"""
        from server.accounts import AccountStore
        _, first = self.signup("失败改密")
        second = self.login("失败改密")
        store = AccountStore(Path(self.tmp.name))
        db_path = Path(self.tmp.name) / "accounts" / "accounts.sqlite3"
        token = first.split("=", 1)[1]
        os.chmod(db_path, stat.S_IREAD)
        try:
            with self.assertRaises(sqlite3.Error):
                store.change_password(token, "123456", "654321", "654321")
        finally:
            os.chmod(db_path, stat.S_IREAD | stat.S_IWRITE)
        # 零改动：原密码仍有效，两个会话都未被撤销
        self.assertIsNotNone(store.verify_credentials("失败改密", "123456"), "写入失败不得改变原密码")
        self.assertIsNotNone(store.get_session(token), "写入失败不得撤销当前会话")
        self.assertIsNotNone(store.get_session(second.split("=", 1)[1]), "写入失败不得撤销其他会话")
        # 恢复可写后重试成功：凭证与撤销状态和返回结果一致
        _, revoked = store.change_password(token, "123456", "654321", "654321")
        self.assertEqual(revoked, {self._token_hash(second)})
        self.assertIsNone(store.verify_credentials("失败改密", "123456"))
        self.assertIsNotNone(store.verify_credentials("失败改密", "654321"))

    def test_v09_04_http_storage_failure_reports_no_success(self):
        """HTTP 层存储失败：中文 503 不误报成功；恢复后重试，撤销与凭证状态和成功返回一致。"""
        _, first = self.signup("失败接口")
        second = self.login("失败接口")
        db_path = Path(self.tmp.name) / "accounts" / "accounts.sqlite3"
        os.chmod(db_path, stat.S_IREAD)
        try:
            status, body, _ = self.change(first, "123456", "654321")
        finally:
            os.chmod(db_path, stat.S_IREAD | stat.S_IWRITE)
        self.assertEqual(status, 503, "存储失败必须报告失败而不是成功")
        self.assertEqual(body["code"], "auth.service-unavailable")
        self.assertIn("稍后重试", body["message"], "失败反馈必须是简体中文")
        # 未误报成功：原密码仍可登录，两个会话均未被撤销
        self.assertEqual(self.request("/api/auth/login", {"username": "失败接口", "password": "123456"})[0], 200)
        self.assertEqual(self.request("/api/auth/session", cookie=first)[0], 200)
        self.assertEqual(self.request("/api/auth/session", cookie=second)[0], 200)
        # 恢复后重试成功：状态与成功返回一致
        status, body, _ = self.change(first, "123456", "654321")
        self.assertEqual(status, 200)
        self.assertEqual(self.request("/api/auth/session", cookie=first)[0], 200)
        self.assertEqual(self.request("/api/auth/session", cookie=second)[0], 401)
        self.assertEqual(self.request("/api/auth/login", {"username": "失败接口", "password": "123456"})[0], 401)
        self.assertEqual(self.request("/api/auth/login", {"username": "失败接口", "password": "654321"})[0], 200)

    def test_v09_01_passwords_never_logged(self):
        """改密请求中的旧/新密码不写入服务日志或 URL。"""
        _, first = self.signup("日志改密", "旧密码不外泄")
        status, _, _ = self.change(first, "旧密码不外泄", "新密码不外泄")
        self.assertEqual(status, 200)
        self.stop_server()
        output = self.log_path.read_text(encoding="utf-8", errors="replace")
        self.assertNotIn("旧密码不外泄", output, "旧密码不得写入服务日志或 URL")
        self.assertNotIn("新密码不外泄", output, "新密码不得写入服务日志或 URL")


if __name__ == "__main__":
    unittest.main()
