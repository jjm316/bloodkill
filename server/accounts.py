"""Persistent account and login identity boundary, independent of room saves."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sqlite3
import time


SESSION_COOKIE = "bloodbound_session"
SESSION_SECONDS = 30 * 24 * 60 * 60
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 5


class AccountError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.status = code, status


@dataclass(frozen=True)
class Account:
    account_id: str
    username: str

    def public(self) -> dict[str, str]:
        return {"accountId": self.account_id, "username": self.username}


def validate_username(username: object) -> str:
    if not isinstance(username, str) or not re.fullmatch(r"[\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9_]{2,16}", username):
        raise AccountError("auth.invalid-username", "用户名须为 2–16 个中文、英文字母、数字或下划线，不能含空格。")
    return username


def validate_password(password: object, confirmation: object) -> str:
    if not isinstance(password, str) or not 6 <= len(password) <= 12:
        raise AccountError("auth.invalid-password", "密码须为 6–12 个字符。")
    if password != confirmation:
        raise AccountError("auth.password-mismatch", "两次输入的密码不一致。")
    return password


def password_digest(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R,
                          p=SCRYPT_P, maxmem=64 * 1024 * 1024)


class AccountStore:
    def __init__(self, saves_dir: Path):
        directory = Path(saves_dir) / "accounts"
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "accounts.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY, username TEXT NOT NULL,
                    username_key TEXT NOT NULL UNIQUE, password_salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(account_id),
                    created_at REAL NOT NULL, expires_at REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def register(self, username: object, password: object, confirmation: object) -> tuple[Account, str]:
        name = validate_username(username)
        raw_password = validate_password(password, confirmation)
        salt = secrets.token_bytes(16)
        digest = password_digest(raw_password, salt)
        account = Account(secrets.token_hex(16), name)
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.connect() as db:
            try:
                db.execute("INSERT INTO accounts VALUES (?, ?, ?, ?, ?)",
                           (account.account_id, name, name.lower(), salt, digest))
            except sqlite3.IntegrityError:
                raise AccountError("auth.username-taken", "用户名已被使用，请换一个用户名。", 409) from None
            db.execute("INSERT INTO sessions (token_hash, account_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                       (hashlib.sha256(token.encode()).hexdigest(), account.account_id, now, now + SESSION_SECONDS))
        return account, token

    def get_session(self, token: str | None, *, now: float | None = None) -> Account | None:
        if not token:
            return None
        with self.connect() as db:
            row = db.execute("""SELECT accounts.account_id, username FROM sessions
                JOIN accounts USING (account_id)
                WHERE token_hash = ? AND revoked = 0 AND expires_at > ?""",
                (hashlib.sha256(token.encode()).hexdigest(), time.time() if now is None else now)).fetchone()
        return Account(row["account_id"], row["username"]) if row else None

    def verify_credentials(self, username: object, password: object) -> Account | None:
        if not isinstance(username, str) or not isinstance(password, str):
            return None
        with self.connect() as db:
            row = db.execute("SELECT * FROM accounts WHERE username_key = ?", (username.lower(),)).fetchone()
        if row is None or not hmac.compare_digest(password_digest(password, row["password_salt"]), row["password_hash"]):
            return None
        return Account(row["account_id"], row["username"])

    def login(self, username: object, password: object) -> tuple[Account, str]:
        account = self.verify_credentials(username, password)
        if account is None:
            raise AccountError("auth.invalid-credentials", "账号或密码不正确，请重新输入。", 401)
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.connect() as db:
            db.execute("INSERT INTO sessions (token_hash, account_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                       (hashlib.sha256(token.encode()).hexdigest(), account.account_id, now, now + SESSION_SECONDS))
        return account, token
