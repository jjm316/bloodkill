"""发布脚本经真实 HTTP/WebSocket 接口完成对局的回归测试。"""

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest

SERVER_AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("fastapi", "uvicorn", "websockets"))

if SERVER_AVAILABLE:
    import websockets
    from websockets.exceptions import ConnectionClosed

    from scripts.release_smoke import SmokeFailure, request, validate_replay
    from scripts.account_client import AccountClient
    from server.protocol import PROTOCOL_VERSION


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release_smoke.py"


def run_cli(base, *arguments, cwd=ROOT):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--base-url", base, *arguments],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=15,
    )


@unittest.skipUnless(SERVER_AVAILABLE, "requires server/requirements.txt")
class ReleaseSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        cls.base = f"http://127.0.0.1:{port}"
        environment = {**os.environ, "BLOOD_BOUND_SAVES_DIR": temporary.name}
        log_path = Path(temporary.name) / "server.log"
        log = log_path.open("w", encoding="utf-8")
        cls.addClassCleanup(log.close)
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        cls.addClassCleanup(cls.stop_server, server)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError("测试服务启动失败：" + log_path.read_text(encoding="utf-8"))
            try:
                if request(f"{cls.base}/health")[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(0.05)
        raise RuntimeError("测试服务启动超时：" + log_path.read_text(encoding="utf-8"))

    @staticmethod
    def stop_server(server):
        if os.name == "nt":
            # Windows 虚拟环境解释器可能启动子进程；整棵树退出后日志句柄才会释放。
            subprocess.run(
                ["taskkill", "/PID", str(server.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        else:
            server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)

    def test_old_protocol_is_rejected_with_expected_version(self):
        session = AccountClient(self.base).register_test_account()
        _, room = session.request("/api/rooms", method="POST")

        async def old_hello():
            async with websockets.connect(f"{self.base.replace('http:', 'ws:')}/ws/{room['code']}", additional_headers={"Cookie": session.cookie_header}) as connection:
                await connection.send(json.dumps({"type": "hello", "mode": "player", "protocolVersion": "1"}))
                return json.loads(await asyncio.wait_for(connection.recv(), timeout=2))

        message = asyncio.run(old_hello())
        self.assertEqual(message["code"], "protocol.version-mismatch")
        self.assertEqual(message["details"]["expected"], PROTOCOL_VERSION)

    def test_cli_completes_game_and_downloads_public_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_cli(self.base, cwd=directory)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for stage in ("首次握手成功", "建局成功", "命令确认成功", "账号重连成功", "终局成功", "公开回放成功"):
            self.assertIn(stage, result.stdout)
        print(result.stdout, end="")
        code = re.search(r"房间 (\d{6})", result.stdout).group(1)
        # 回放要求登录：匿名被拒，登录的非参与者可读（工单 23）。
        self.assertEqual(request(f"{self.base}/api/rooms/{code}/replay")[0], 401)
        session = AccountClient(self.base).register_test_account()
        status, replay = session.request(f"/api/rooms/{code}/replay")
        self.assertEqual(status, 200)
        self.assertTrue(replay["steps"])
        self.assertEqual(replay["steps"][-1]["status"], "ended")
        self.assertTrue(replay["steps"][-1]["result"])
        for step in replay["steps"]:
            self.assertIsNone(step["viewer"])
            self.assertEqual(step["legalActions"], [])
            self.assertNotIn("seed", step)

    def test_command_limit_exits_without_fetching_successful_replay(self):
        result = run_cli(self.base, "--max-commands", "1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("命令上限（1 条）", result.stderr)
        self.assertNotIn("公开回放成功", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_connection_failure_is_reported_without_traceback(self):
        with socket.socket() as unused:
            unused.bind(("127.0.0.1", 0))
            base = f"http://127.0.0.1:{unused.getsockname()[1]}"
            result = run_cli(base, "--timeout", "0.2")
        self.assertEqual(result.returncode, 1)
        self.assertIn("smoke 失败：", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


@unittest.skipUnless(SERVER_AVAILABLE, "requires server/requirements.txt")
class ReleaseFailureTests(unittest.IsolatedAsyncioTestCase):
    async def run_failing_service(self, mode, *arguments):
        """只替代远端 HTTP/WS 边界，脚本以真实 CLI 子进程运行。"""
        from fastapi import FastAPI, Request, WebSocket
        from fastapi.responses import JSONResponse
        import uvicorn

        fixture = FastAPI()
        room = {"code": "123456", "gameId": "test-game"}
        secret_token = "不可记录的令牌"

        @fixture.post("/api/auth/register")
        async def register():
            response = JSONResponse({"account": {"accountId": "fixture-account", "username": "边界测试"}}, status_code=201)
            response.set_cookie("bloodbound_session", "fixture-session", httponly=True)
            return response

        @fixture.get("/health")
        async def health():
            return {"status": "ok"}

        @fixture.post("/api/rooms")
        async def create():
            return room

        @fixture.get("/api/rooms/123456")
        async def info():
            return {"status": "waiting"}

        @fixture.get("/api/rooms/{code}/replay")
        async def replay(code: str, request: Request):
            # 与真实服务一致的顺序：无有效会话先拒 401，再区分未知房/未终局。
            if request.cookies.get("bloodbound_session") != "fixture-session":
                return JSONResponse({"code": "auth.login-required"}, status_code=401)
            if code != "123456":
                return JSONResponse({"code": "room.not-found"}, status_code=404)
            return JSONResponse({"code": "room.not-ended"}, status_code=409)

        @fixture.get("/metrics")
        async def metrics():
            return {}

        @fixture.websocket("/ws/{code}")
        async def websocket_response(connection: WebSocket, code: str):
            await connection.accept()
            await connection.receive_text()
            if mode == "protocol":
                await connection.send_text(json.dumps({"type": "error", "code": "protocol.version-mismatch", "details": {"expected": "999", "hostToken": secret_token}}))
            elif mode == "rejected-ack":
                await connection.send_text(json.dumps({"type": "ack", "status": "rejected", "error": {"code": "game.revision-conflict"}}))
            elif mode == "closed":
                await connection.close()
            else:
                try:
                    while True:
                        await connection.send_text(json.dumps({"type": "event", "events": []}))
                        await asyncio.sleep(0.01)
                except Exception:
                    pass

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(fixture, host="127.0.0.1", port=port, log_level="critical"))
        task = asyncio.create_task(server.serve())
        try:
            while not server.started:
                await asyncio.sleep(0.01)
            base = f"http://127.0.0.1:{port}"
            process = await asyncio.create_subprocess_exec(
                sys.executable, str(SCRIPT), "--base-url", base, "--timeout", "0.2", *arguments,
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=3)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        finally:
            server.should_exit = True
            await task
        output = (stdout + stderr).decode("utf-8")
        self.assertEqual(process.returncode, 1, output)
        self.assertIn("smoke 失败：", output)
        self.assertNotIn("Traceback", output)
        self.assertNotIn(secret_token, output)
        return output

    async def test_protocol_rejection_reports_code_and_expected_version(self):
        output = await self.run_failing_service("protocol")
        self.assertIn("protocol.version-mismatch", output)
        self.assertIn("期望版本 999", output)

    async def test_rejected_ack_is_reported(self):
        self.assertIn("game.revision-conflict", await self.run_failing_service("rejected-ack"))

    async def test_unrelated_messages_do_not_extend_receive_deadline(self):
        self.assertIn("等待房间状态超时", await self.run_failing_service("events"))

    async def test_game_time_limit_bounds_the_whole_flow(self):
        self.assertIn("对局超过总时限", await self.run_failing_service("events", "--game-timeout", "0.05"))

    async def test_closed_connection_is_reported(self):
        await self.run_failing_service("closed")


@unittest.skipUnless(SERVER_AVAILABLE, "requires server/requirements.txt")
class ReplayValidationTests(unittest.TestCase):
    def test_identity_is_allowed_only_in_ended_player_entries(self):
        player = {"playerId": "p1", "identityMarkers": [None, None]}
        active = {"gameId": "game", "revision": 4, "status": "active", "result": None, "viewer": None, "legalActions": [], "players": [player]}
        final = {**active, "revision": 5, "status": "ended", "result": {"winner": "rose"}, "players": [{**player, "identity": {"faction": "rose", "rank": 3}}]}
        validate_replay({"gameId": "game", "steps": [active, final]}, final)
        bad_steps = [
            {**active, "players": final["players"]},
            {**final, "revision": 4, "identity": {"faction": "rose", "rank": 3}},
            {**final, "revision": 4, "players": [{**player, "identity": {"faction": "rose", "rank": 3, "seed": "private"}}]},
            {**final, "revision": 4, "players": [{**player, "identity": {"faction": "secret-order", "rank": 1}}]},
        ]
        for step in bad_steps:
            with self.subTest(step=step), self.assertRaises(SmokeFailure):
                validate_replay({"gameId": "game", "steps": [step, final]}, final)

    def test_empty_mismatched_and_private_replays_are_rejected(self):
        final = {"gameId": "game", "revision": 5, "status": "ended", "result": {"winner": "rose"}, "viewer": None, "legalActions": [], "players": [{"playerId": "p1", "identityMarkers": [None, None]}]}
        public = {**final, "revision": 4, "status": "active", "result": None}
        validate_replay({"gameId": "game", "steps": [public, final]}, final)
        bad_replays = [
            {"gameId": "game", "steps": []},
            {"gameId": "other", "steps": [final]},
            {"gameId": "game", "steps": [public]},
            {"gameId": "game", "steps": [final, public, final]},
        ]
        for field, value in (("seed", 123), ("viewer", {"identity": {"rank": 3}}), ("legalActions", [{"type": "attack"}]), ("clueIcon", "rose"), ("cursesToDistribute", ["curse"])):
            bad_replays.append({"gameId": "game", "steps": [{**public, field: value}, final]})
        bad_replays.append({"gameId": "game", "steps": [{**public, "players": [{"rank": 3, "identityMarkers": [None, None]}]}, final]})
        bad_replays.append({"gameId": "game", "steps": [{**public, "players": [{"identityMarkers": ["rose", "beast"]}]}, final]})
        for replay in bad_replays:
            with self.subTest(replay=replay), self.assertRaises(SmokeFailure):
                validate_replay(replay, final)


if __name__ == "__main__":
    unittest.main()
