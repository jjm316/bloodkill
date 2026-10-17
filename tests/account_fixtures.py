"""Real registered identities reused by pure room/projection fixtures."""

from functools import lru_cache
from pathlib import Path
import tempfile

from server.accounts import AccountStore, SESSION_COOKIE

_directory = tempfile.TemporaryDirectory()
store = AccountStore(Path(_directory.name))


@lru_cache(maxsize=None)
def identity(name):
    return store.register(name, "fixture-pass", "fixture-pass")


def account(name):
    return identity(name)[0]


def token(name):
    """该 fixture 账号的会话凭证（Conn 需要它证明登录仍有效，工单 14）。"""
    return identity(name)[1]


def cookie(name):
    return {SESSION_COOKIE: identity(name)[1]}


def account_for_player(room, player_id):
    return account(room.engine.state.players[player_id].display_name)


def token_for_player(room, player_id):
    return token(room.engine.state.players[player_id].display_name)
