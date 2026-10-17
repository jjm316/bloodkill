"""工单 23：登录观看公开回放及保留规则。

真实 uvicorn/HTTP/WS 边界（同 09/10 的隔离 fixture）：正常结束对局的公开回放
对任意已登录账号（参与者或非参与者）开放；未登录/篡改会话被拒并给出中文原因；
最近 20 局的清理只作用于对局存档，不影响账号、会话、占用与管理数据。
"""

import asyncio
import json
import unittest

import websockets

from tests import test_accounts as account_tests


class ReplayAuthHTTPTests(unittest.TestCase):
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
        """补足到 total 个座位后由房主开局，返回开局后的 state。"""
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

    def play_full_game(self):
        """用 release_smoke 的真实 WS 流程打一整局到正常终局，留下可回放的存档。"""
        from scripts.account_client import AccountClient
        from scripts.release_smoke import websocket_smoke
        base = f"http://127.0.0.1:{self.port}"
        sessions = [AccountClient(base).register_test_account() for _ in range(7)]
        status, room = sessions[0].request("/api/rooms", "POST", {})
        self.assertEqual(status, 200)
        final = asyncio.run(websocket_smoke(base, room, sessions))
        self.assertEqual(final["status"], "ended")
        return room, sessions, final

    # ---- V17.01：未登录/失效会话不可读回放 --------------------------------

    def test_anonymous_and_tampered_sessions_cannot_read_replay(self):
        room, sessions, final = self.play_full_game()
        self.assertEqual(final["status"], "ended")
        for cookie in (None, "bloodbound_session=tampered", "bloodbound_session="):
            with self.subTest(cookie=cookie):
                status, body, _ = self.request(f"/api/rooms/{room['code']}/replay", cookie=cookie)
                self.assertEqual(status, 401, "未登录/失效会话必须被拒绝读取回放")
                self.assertEqual(body["code"], "auth.login-required")
                self.assertIn("登录", body["message"], "拒绝原因必须是简体中文")


    # ---- V17.01：参与者与非参与者登录后均可读正常回放 ---------------------

    def test_participant_spectator_and_outsider_read_the_same_ended_replay(self):
        from scripts.release_smoke import validate_replay
        room, sessions, final = self.play_full_game()
        code = room["code"]
        seen = []
        for session in (sessions[0], sessions[5], sessions[6]):
            status, replay = session.request(f"/api/rooms/{code}/replay")
            self.assertEqual(status, 200, "已登录的参与者/旁观者必须能读回放")
            seen.append(replay)
        _, outsider_cookie = self.signup("非参与者观众")
        status, replay, _ = self.request(f"/api/rooms/{code}/replay", cookie=outsider_cookie)
        self.assertEqual(status, 200, "已登录的非参与者必须能按房号读回放")
        seen.append(replay)
        self.assertEqual(len({json.dumps(item, sort_keys=True) for item in seen}), 1,
                        "不同登录身份读到的必须是同一份公开回放")
        validate_replay(replay, final)

    # ---- V17.01：进行中/未终局/未知房给出明确中文原因 ---------------------

    def unused_code(self, cookie):
        """取一个确实不存在的房号（登录后房间概览 404）用于未知房反例。"""
        for candidate in (f"{index:06d}" for index in range(424242, 424282)):
            if self.request(f"/api/rooms/{candidate}", None, cookie)[0] == 404:
                return candidate
        self.fail("找不到不存在的房号")

    def test_waiting_playing_and_unknown_rooms_are_rejected_with_chinese_reasons(self):
        _, host_cookie = self.signup("回放房主")
        code = self.create_room(host_cookie)
        # 等待房：尚无终局，不能在线回放。
        status, body, _ = self.request(f"/api/rooms/{code}/replay", cookie=host_cookie)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "room.not-ended")
        self.assertIn("结束", body["message"], "等待房拒绝原因必须是简体中文")
        # 进行房：同样没有完整回放。
        started = asyncio.run(self.fill_to(code, host_cookie, 6, "进行房补位"))
        self.assertEqual(started["roomStatus"], "playing")
        status, body, _ = self.request(f"/api/rooms/{code}/replay", cookie=host_cookie)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "room.not-ended")
        self.assertIn("结束", body["message"], "进行房拒绝原因必须是简体中文")
        # 未知房：明确说明房间不存在。
        unknown = self.unused_code(host_cookie)
        status, body, _ = self.request(f"/api/rooms/{unknown}/replay", cookie=host_cookie)
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "room.not-found")
        self.assertIn("房间", body["message"], "未知房拒绝原因必须是简体中文")
        # 匿名请求未知房：登录门槛在前，仍是 401。
        status, body, _ = self.request(f"/api/rooms/{unknown}/replay")
        self.assertEqual(status, 401)


    # ---- V17.02：公开回放不含私有身份、备忘或会话信息 ---------------------

    def test_replay_leaks_no_private_identity_memos_or_session_material(self):
        from scripts.release_smoke import validate_replay
        room, sessions, final = self.play_full_game()
        _, sentinel_cookie = self.signup("回放隐私哨兵", password="Zz9xQq7wPw")
        status, replay, _ = self.request(f"/api/rooms/{room['code']}/replay", cookie=sentinel_cookie)
        self.assertEqual(status, 200)
        # validate_replay 覆盖投影级保密：旁观者投影、无私有字段键、
        # 身份仅在终局帧按 ADR 0015 公开且形状合法。
        validate_replay(replay, final)
        for step in replay["steps"]:
            self.assertIsNone(step.get("viewer"), "回放必须是旁观者投影")
            self.assertEqual(step.get("legalActions"), [])
            if step["status"] != "ended":
                for player in step["players"]:
                    self.assertNotIn("identity", player, "非终局帧不得公开玩家身份")
                    self.assertNotIn("rank", player)
                    self.assertNotIn("faction", player)
        # 终局身份展示仍正确（ADR 0015）：末帧全员公开身份事实。
        last = replay["steps"][-1]
        self.assertEqual(last["status"], "ended")
        self.assertTrue(last["result"])
        for player in last["players"]:
            identity = player["identity"]
            self.assertIsInstance(identity, dict)
            self.assertEqual(set(identity), {"faction", "rank"})
        # 会话/凭证/账号引用对照：回放文本不得包含任何会话 Cookie、密码或账号 ID。
        text = json.dumps(replay, ensure_ascii=False)
        secrets = [sessions[i].cookie_header.split("=", 1)[1] for i in range(7)]
        secrets += [session.account["accountId"] for session in sessions]
        secrets += [sentinel_cookie.split("=", 1)[1], "Zz9xQq7wPw"]
        for secret in secrets:
            self.assertNotIn(secret, text)
        self.assertNotIn("memo", text, "回放不得携带任何备忘内容")
        self.assertNotIn("bloodbound_session", text)


    # ---- V17.03/V17.04：保留 20 局边界与清理的数据保护 ---------------------

    def assert_protected_data_intact(self, keeper_cookie, occupied_cookie, occupied_code, occupied_player_id, admin_file):
        """清理/重启目标之外的数据必须原样保持：会话、可再登录、未结束占用、管理数据。"""
        status, body, _ = self.request("/api/auth/session", cookie=keeper_cookie)
        self.assertEqual(status, 200, "清理/重启后既有登录会话必须仍有效")
        status, body, _ = self.request("/api/auth/login", {"username": "保留账号", "password": "123456"})
        self.assertEqual(status, 200, "清理/重启后账号必须仍可登录")
        room = self.request("/api/account/room", cookie=occupied_cookie)[1]["room"]
        self.assertEqual((room["code"], room["status"]), (occupied_code, "waiting"), "未结束占用不得被清理影响")
        after = asyncio.run(self.state_of(occupied_code, occupied_cookie))
        self.assertEqual(after["yourPlayerId"], occupied_player_id, "清理/重启后必须能恢复原座位")
        self.assertEqual(admin_file.read_text(encoding="utf-8"), '{"roomCode": "654321"}', "管理备份数据不得被游戏清理删除")

    def test_retention_prunes_only_finished_games_and_preserves_protected_data(self):
        from pathlib import Path
        from scripts.account_client import AccountClient
        from scripts.release_smoke import validate_replay, websocket_smoke
        from server.rooms import FINISHED_GAMES_TO_KEEP
        base = f"http://127.0.0.1:{self.port}"

        _, keeper_cookie = self.signup("保留账号")
        _, occupied_host_cookie = self.signup("占用房主")
        occupied_code = self.create_room(occupied_host_cookie)
        _, occupied_cookie = self.signup("占用玩家")
        occupied_player_id = asyncio.run(self.state_of(occupied_code, occupied_cookie))["yourPlayerId"]
        # 独立管理数据：规格规定的管理备份子目录（21/24 的 close-room 备份落点）与无关文件。
        admin_dir = Path(self.tmp.name) / "admin-backup"
        admin_dir.mkdir()
        admin_file = admin_dir / "closed-room.json"
        admin_file.write_text('{"roomCode": "654321"}', encoding="utf-8")
        unrelated = Path(self.tmp.name) / "unrelated.txt"
        unrelated.write_text("与对局存档无关的文件", encoding="utf-8")

        sessions = [AccountClient(base).register_test_account() for _ in range(7)]
        codes = []
        for _ in range(FINISHED_GAMES_TO_KEEP):
            status, room = sessions[0].request("/api/rooms", "POST", {})
            self.assertEqual(status, 200)
            final = asyncio.run(websocket_smoke(base, room, sessions))
            codes.append((room["code"], final))

        # 正好 20 局：没有任何清理，全部可读。
        for code, _ in codes:
            status, replay = sessions[1].request(f"/api/rooms/{code}/replay")
            self.assertEqual(status, 200, f"第 20 局边界内 {code} 必须仍可回放")
        self.assert_protected_data_intact(keeper_cookie, occupied_cookie, occupied_code, occupied_player_id, admin_file)

        # V17.04 第一次重启：清理前核对 20 局回放、账号、会话、占用与管理数据均保持。
        self.stop_server()
        self.start_server()
        for code, _ in codes:
            status, replay = sessions[1].request(f"/api/rooms/{code}/replay")
            self.assertEqual(status, 200, f"重启后 {code} 回放必须仍可读")
        self.assert_protected_data_intact(keeper_cookie, occupied_cookie, occupied_code, occupied_player_id, admin_file)

        # 第 21 局：最旧正常终局被清理，最新回放完整，其余保持。
        status, room = sessions[0].request("/api/rooms", "POST", {})
        self.assertEqual(status, 200)
        final = asyncio.run(websocket_smoke(base, room, sessions))
        latest_code = room["code"]
        status, replay = sessions[1].request(f"/api/rooms/{latest_code}/replay")
        self.assertEqual(status, 200)
        validate_replay(replay, final)
        latest_replay_text = json.dumps(replay, sort_keys=True)
        status, body, _ = self.request(f"/api/rooms/{codes[0][0]}/replay", cookie=keeper_cookie)
        self.assertEqual((status, body["code"]), (404, "room.not-found"), "第 21 局后最旧正常终局必须被清理")
        for code, _ in codes[1:]:
            status, kept = sessions[1].request(f"/api/rooms/{code}/replay")
            self.assertEqual(status, 200, f"除最旧外其余 {code} 必须保留")
        self.assert_protected_data_intact(keeper_cookie, occupied_cookie, occupied_code, occupied_player_id, admin_file)
        self.assertTrue(unrelated.exists(), "清理不得删除对局存档之外的无关文件")

        # V17.04 第二次重启：清理后核对账号、会话、占用、管理数据与最新回放仍保持。
        self.stop_server()
        self.start_server()
        status, replay = sessions[1].request(f"/api/rooms/{latest_code}/replay")
        self.assertEqual(status, 200, "重启后最新回放必须仍可读")
        self.assertEqual(json.dumps(replay, sort_keys=True), latest_replay_text, "重启后回放内容必须一致")
        self.assert_protected_data_intact(keeper_cookie, occupied_cookie, occupied_code, occupied_player_id, admin_file)
        self.assertTrue(unrelated.exists())
        # 存档目录边界：恰好 20 个已结束对局 + 1 个未结束房；账号库与管理目录原样。
        meta_files = list(Path(self.tmp.name).glob("*.meta.json"))
        self.assertEqual(len(meta_files), FINISHED_GAMES_TO_KEEP + 1, "已结束对局必须收敛到保留上限")
        self.assertTrue((Path(self.tmp.name) / "accounts" / "accounts.sqlite3").exists(), "账号库不得被清理删除")


    # ---- V17.05：有未结束占用仍可看回放，回放不改变占用 -------------------

    def test_occupied_player_views_ended_replay_and_returns_to_original_room(self):
        _, host_cookie = self.signup("原房房主")
        code = self.create_room(host_cookie)
        _, player_cookie = self.signup("原房玩家")
        before = asyncio.run(self.state_of(code, player_cookie))
        # 另一房间的正常终局回放（真实完整局产生）。
        room, sessions, final = self.play_full_game()
        ended_code = room["code"]
        # 有未结束玩家占用时仍能看已结束回放。
        status, replay, _ = self.request(f"/api/rooms/{ended_code}/replay", cookie=player_cookie)
        self.assertEqual(status, 200, "有未结束占用的玩家必须仍能看已结束回放")
        self.assertTrue(replay["steps"])
        # 回放是静态公开步骤：重复读取结果一致，不存在实时状态流。
        status, again, _ = self.request(f"/api/rooms/{ended_code}/replay", cookie=player_cookie)
        self.assertEqual(again, replay)
        # 回放读取不给本人任何座位/占用变化，也不影响回放房名册。
        self.assertEqual(self.request(f"/api/rooms/{ended_code}", None, player_cookie)[1]["playerCount"], 6)
        occupied = self.request("/api/account/room", cookie=player_cookie)[1]["room"]
        self.assertEqual((occupied["code"], occupied["status"]), (code, "waiting"),
                         "回放路径不得改变未结束占用归属")
        # 未结束的原房不能借回放路径旁观：只给明确拒绝，不产生任何对局内容。
        status, body, _ = self.request(f"/api/rooms/{code}/replay", cookie=player_cookie)
        self.assertEqual((status, body["code"]), (409, "room.not-ended"))
        # 观看完回放后返回原房：恢复原座位与名册。
        after = asyncio.run(self.state_of(code, player_cookie))
        self.assertEqual(after["yourPlayerId"], before["yourPlayerId"], "返回原房必须恢复原座位")
        self.assertEqual(len(after["game"]["players"]), 2)


if __name__ == "__main__":
    unittest.main()
