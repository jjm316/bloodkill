import json
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request


class RegistrationHTTPTests(unittest.TestCase):
    """Exercise the deployed HTTP boundary with an isolated persistent directory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.start_server()
        self.addCleanup(self.stop_server)

    def start_server(self):
        self.log_path = Path(self.tmp.name) / "server.log"
        self.log = self.log_path.open("ab")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", str(self.port)],
            env={**os.environ, "BLOOD_BOUND_SAVES_DIR": self.tmp.name},
            stdout=self.log, stderr=self.log,
        )
        for _ in range(100):
            try:
                self.request("/health")
                return
            except OSError:
                time.sleep(.05)
        self.fail("隔离 HTTP 服务未启动")

    def stop_server(self):
        if os.name == "nt" and self.process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            self.process.wait(timeout=10)
            self.log.close()
            return
        self.process.terminate()
        self.process.wait(timeout=10)
        self.log.close()

    def request(self, path, data=None, cookie=None):
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers,
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            response = opener.open(request)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response), response.headers

    def register(self, username="小明_Alice", password="Ab 12 ", confirmation=None):
        return self.request("/api/auth/register", {
            "username": username, "password": password,
            "confirmPassword": password if confirmation is None else confirmation,
        })

    def test_registration_automatically_authenticates_after_process_restart(self):
        status, body, headers = self.register()
        self.assertEqual(status, 201)
        self.assertEqual(body["account"]["username"], "小明_Alice")
        self.assertEqual(set(body["account"]), {"accountId", "username"})
        cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertIn("Max-Age=2592000", cookie)
        self.stop_server()
        self.start_server()
        restored = self.request("/api/auth/session", cookie=cookie.split(";", 1)[0])
        self.assertEqual(restored[0], 200)
        self.assertEqual(restored[1]["account"], body["account"])
        self.assertNotIn("Ab 12 ", json.dumps(body))

    def test_username_and_password_boundaries_with_chinese_feedback(self):
        for name in ["a", "a" * 17, "有 空格", " 张三", "张三 ", "bad!", "Éclair", "😀😀"]:
            with self.subTest(username=name):
                status, body, _ = self.register(name)
                self.assertEqual(status, 400)
                self.assertEqual(body["code"], "auth.invalid-username")
                self.assertIn("用户名", body["message"])
        for name in ["张三", "a" * 16, "中文Ab_12"]:
            with self.subTest(username=name):
                self.assertEqual(self.register(name)[0], 201)
        for password in ["12345", "1234567890123"]:
            status, body, _ = self.register("边界用户", password)
            self.assertEqual(status, 400)
            self.assertIn("6–12", body["message"])
        self.assertEqual(self.register("边界用户", "123456", "12345A")[1]["code"], "auth.password-mismatch")
        self.assertEqual(self.register("边界用户", "123456")[0], 201)
        self.assertEqual(self.register("长密码", "123456789012")[0], 201)

    def test_concurrent_case_variants_create_only_one_persistent_account(self):
        from threading import Barrier
        barrier = Barrier(2)
        def attempt(name):
            barrier.wait(timeout=5)
            return self.register(name)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, ["Alice", "alice"]))
        self.assertEqual(sorted(result[0] for result in outcomes), [201, 409])
        rejected = next(result for result in outcomes if result[0] == 409)
        self.assertEqual(rejected[1]["code"], "auth.username-taken")
        self.assertIn("用户名已被使用", rejected[1]["message"])
        self.stop_server()
        self.start_server()
        self.assertEqual(self.register("ALICE")[0], 409)
        from contextlib import closing
        import sqlite3
        with closing(sqlite3.connect(Path(self.tmp.name) / "accounts" / "accounts.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 1)
        winner = next(result for result in outcomes if result[0] == 201)
        restored = self.request("/api/auth/session", cookie=winner[2]["Set-Cookie"].split(";", 1)[0])
        self.assertEqual(restored[1]["account"], winner[1]["account"])

    def test_storage_contract_preserves_raw_password_and_uses_distinct_salts(self):
        from server.accounts import AccountStore
        import sqlite3
        password = " Ab12 "
        for username in ["密码甲", "密码乙"]:
            status, body, _ = self.register(username, password)
            self.assertEqual(status, 201)
            self.assertNotIn(password, json.dumps(body))
        store = AccountStore(Path(self.tmp.name))
        self.assertEqual(store.verify_credentials("密码甲", password).username, "密码甲")
        self.assertIsNone(store.verify_credentials("密码甲", password.strip()))
        self.assertIsNone(store.verify_credentials("密码甲", password.lower()))
        from contextlib import closing
        with closing(sqlite3.connect(store.path)) as db:
            rows = db.execute("SELECT password_salt, password_hash FROM accounts").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0], rows[1])
        self.assertNotIn(password.encode(), store.path.read_bytes())
        self.stop_server()
        output = self.log_path.read_bytes()
        self.assertNotIn(password.encode(), output)
        for salt, digest in rows:
            self.assertNotIn(digest.hex().encode(), output)

    def test_malformed_registration_is_chinese_and_does_not_echo_credentials(self):
        status, body, _ = self.request("/api/auth/register", ["SecretPass!"])
        self.assertEqual(status, 400)
        self.assertIn("格式", body["message"])
        self.assertNotIn("SecretPass!", json.dumps(body))

    def test_session_write_failure_rolls_back_entire_registration_and_allows_retry(self):
        import sqlite3
        from contextlib import closing
        path = Path(self.tmp.name) / "accounts" / "accounts.sqlite3"
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TRIGGER fail_session BEFORE INSERT ON sessions BEGIN SELECT RAISE(FAIL, 'test failure'); END")
            db.commit()
        status, body, _ = self.register("失败后重试")
        self.assertEqual(status, 503)
        self.assertIn("服务", body["message"])
        with closing(sqlite3.connect(path)) as db:
            db.execute("DROP TRIGGER fail_session")
            db.commit()
        self.assertEqual(self.register("失败后重试")[0], 201)

    def test_login_case_variant_issues_a_new_persistent_session(self):
        _, registered, registration_headers = self.register("Mixed_Alice", " Ab12 ")
        status, body, headers = self.request("/api/auth/login", {"username": "MIXED_alice", "password": " Ab12 "})
        self.assertEqual(status, 200)
        self.assertEqual(body, registered)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertNotEqual(cookie, registration_headers["Set-Cookie"].split(";", 1)[0])
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("Max-Age=2592000", headers["Set-Cookie"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.request("/api/auth/session", cookie=cookie)[1], registered)
        self.stop_server()
        self.start_server()
        restored = self.request("/api/auth/session", cookie=cookie)
        self.assertEqual(restored[0], 200)
        self.assertEqual(restored[1], registered)
        self.assertIsNone(restored[2].get("Set-Cookie"))

    def test_failed_login_does_not_create_or_replace_identity_or_echo_password(self):
        _, original, headers = self.register("Mixed_Alice", " Ab12 ")
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        failures = [
            {"username": "unknown", "password": " Ab12 "},
            {"username": "Mixed_Alice", "password": " ab12 "},
            {"username": "Mixed_Alice", "password": "Ab12"},
            {"username": "Mixed_Alice", "password": "wrong!"},
            {"username": "Mixed_Alice"}, {},
            {"username": ["Mixed_Alice"], "password": 123456},
        ]
        for payload in failures:
            with self.subTest(payload=payload):
                for existing in [None, cookie]:
                    status, body, failed_headers = self.request("/api/auth/login", payload, cookie=existing)
                    self.assertEqual(status, 401)
                    self.assertEqual(body["code"], "auth.invalid-credentials")
                    self.assertIn("账号或密码不正确", body["message"])
                    self.assertIsNone(failed_headers.get("Set-Cookie"))
                    self.assertNotIn("password", json.dumps(body))
                self.assertEqual(self.request("/api/auth/session")[0], 401)
                self.assertEqual(self.request("/api/auth/session", cookie=cookie)[1], original)
        self.assertEqual(self.request("/api/auth/session", cookie="bloodbound_session=invalid")[0], 401)
        self.stop_server()
        output = self.log_path.read_text()
        for secret in [" Ab12 ", " ab12 ", "wrong!", cookie.split("=", 1)[1]]:
            self.assertNotIn(secret, output)
        self.start_server()

    def test_login_write_failure_does_not_replace_session_and_can_retry(self):
        import sqlite3
        from contextlib import closing
        _, original, headers = self.register("Fault_Alice", "123456")
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        path = Path(self.tmp.name) / "accounts" / "accounts.sqlite3"
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TRIGGER fail_login BEFORE INSERT ON sessions BEGIN SELECT RAISE(FAIL, 'test failure'); END")
            db.commit()
        status, body, headers = self.request("/api/auth/login", {"username": "fault_alice", "password": "123456"}, cookie=cookie)
        self.assertEqual(status, 503)
        self.assertIn("服务暂时不可用", body["message"])
        self.assertIsNone(headers.get("Set-Cookie"))
        self.assertEqual(self.request("/api/auth/session", cookie=cookie)[1], original)
        with closing(sqlite3.connect(path)) as db:
            db.execute("DROP TRIGGER fail_login")
            db.commit()
        status, body, headers = self.request("/api/auth/login", {"username": "fault_alice", "password": "123456"})
        self.assertEqual(status, 200)
        self.assertEqual(body, original)
        self.assertEqual(self.request("/api/auth/session", cookie=headers["Set-Cookie"].split(";", 1)[0])[1], original)

    def test_malformed_and_cross_origin_login_does_not_issue_a_session(self):
        status, body, headers = self.request("/api/auth/login", ["private!"])
        self.assertEqual(status, 400)
        self.assertIn("格式", body["message"])
        self.assertIsNone(headers.get("Set-Cookie"))
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/auth/login",
                                         data=b'{"username":"Alice","password":"private!"}',
                                         headers={"Origin": "http://other-site.invalid", "Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request)
        self.assertEqual(rejected.exception.code, 403)
        self.assertIsNone(rejected.exception.headers.get("Set-Cookie"))
        rejected.exception.close()
