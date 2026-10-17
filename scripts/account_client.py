"""Small authenticated HTTP transport for isolated tools and release checks."""

import json
import secrets
from http.cookies import SimpleCookie
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from server.accounts import SESSION_COOKIE


class AccountClient:
    def __init__(self, base: str, timeout: float = 5):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.cookie_header = ""
        self.account = None
        self.opener = build_opener(ProxyHandler({})) if urlsplit(base).hostname in {"localhost", "127.0.0.1", "::1"} else build_opener()

    def request(self, path, method="GET", data=None):
        headers = {"Content-Type": "application/json"}
        if self.cookie_header:
            headers["Cookie"] = self.cookie_header
        outgoing = Request(self.base + path, method=method, headers=headers,
                           data=json.dumps(data).encode() if data is not None else None)
        try:
            response = self.opener.open(outgoing, timeout=self.timeout)
        except HTTPError as error:
            response = error
        with response:
            body = json.load(response)
            cookie = SimpleCookie(response.headers.get("Set-Cookie", ""))
            if SESSION_COOKIE in cookie:
                self.cookie_header = f"{SESSION_COOKIE}={cookie[SESSION_COOKIE].value}"
            return response.status, body

    def register_test_account(self):
        username = "测试" + secrets.token_hex(6)
        password = secrets.token_urlsafe(7)[:12]
        status, body = self.request("/api/auth/register", "POST", {
            "username": username, "password": password, "confirmPassword": password,
        })
        if status != 201 or not self.cookie_header or not isinstance(body.get("account"), dict):
            raise RuntimeError(f"注册测试账号失败（HTTP {status}）")
        self.account = body["account"]
        return self
