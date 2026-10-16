"""自托管服务发布 smoke：握手、建局、确认、重连、终局与公开回放。"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import websockets
from websockets.exceptions import WebSocketException

# 同时支持从任意目录直接运行和作为模块导入。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.protocol import PROTOCOL_VERSION
from scripts.account_client import AccountClient


class SmokeFailure(Exception):
    """发布验收失败；只携带诊断，不输出令牌或私有状态。"""


def require(condition: bool, description: str) -> None:
    if not condition:
        raise SmokeFailure(description)


def request(url: str, method: str = "GET", timeout: float = 5) -> tuple[int, dict]:
    try:
        with urlopen(Request(url, method=method), timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8")
        return error.code, json.loads(body) if body else {}


async def receive(socket, predicate, description: str, timeout: float = 5):
    """整个等待共用一个期限，无关广播不能重置倒计时。"""
    try:
        async with asyncio.timeout(timeout):
            while True:
                message = json.loads(await socket.recv())
                require(isinstance(message, dict), f"{description}收到非对象消息")
                if message.get("type") == "error":
                    code = message.get("code", "unknown")
                    expected = message.get("details", {}).get("expected")
                    raise SmokeFailure(f"{description}被服务端拒绝：{code}" + (f"（期望版本 {expected}）" if expected else ""))
                if message.get("type") == "taken-over":
                    raise SmokeFailure(f"{description}失败：座位被其他连接接管")
                if message.get("type") == "ack" and message.get("status") == "rejected":
                    raise SmokeFailure(f"命令被拒绝：{message.get('error', {}).get('code', 'unknown')}")
                if predicate(message):
                    return message
    except TimeoutError as error:
        raise SmokeFailure(f"等待{description}超时（{timeout:g} 秒）") from error


def next_action(states: list[dict]) -> tuple[int, dict]:
    """只选择投影提供的合法动作，开票后全部拒绝挡刀，技能选择放弃。"""
    game = states[0]["game"]
    pending = game.get("pending")
    if pending:
        kind = pending["kind"]
        if kind == "intervention":
            command, field, value = {
                "gate": ("answer-intervention-request", "need", True),
                "poll": ("respond-intervention", "volunteer", False),
                "choice": ("decline-intervention", None, None),
            }[pending["stage"]]
        else:
            command = {"reveal": "choose-reveal", "skill": "choose-skill", "token-return": "choose-return"}[kind]
            field, value = ("use", False) if kind == "skill" else (None, None)
        for index, state in enumerate(states):
            for action in state["game"]["legalActions"]:
                if action["type"] == command and (field is None or action.get(field) == value):
                    return index, action
    else:
        damage = {player["playerId"]: player["damage"] for player in game["players"]}
        attacks = [
            (index, action)
            for index, state in enumerate(states)
            for action in state["game"]["legalActions"]
            if action["type"] == "attack"
        ]
        if attacks:
            return max(attacks, key=lambda item: damage[item[1]["targetPlayerId"]])
    raise SmokeFailure("对局无法推进：当前投影没有可用的合法动作")


async def websocket_smoke(base: str, room: dict, sessions: list[AccountClient], *, timeout: float = 5, game_timeout: float = 60, max_commands: int = 100, player_count: int | None = None) -> dict:
    if player_count is None:
        player_count = len(sessions) - 1
    if not 6 <= player_count <= 12:
        raise SmokeFailure("玩家人数必须在 6-12 之间")
    if len(sessions) < player_count + 1:
        raise SmokeFailure("账号会话不足以覆盖全部玩家与旁观者")
    code = room["code"]
    endpoint = base.replace("https://", "wss://").replace("http://", "ws://")
    sockets = []

    async def connect(session, mode="player"):
        socket = await websockets.connect(f"{endpoint}/ws/{code}", additional_headers={"Cookie": session.cookie_header}, open_timeout=timeout, close_timeout=timeout)
        sockets.append(socket)
        await socket.send(json.dumps({"type": "hello", "mode": mode, "protocolVersion": PROTOCOL_VERSION}))
        return socket

    async def state(socket, *, status=None, revision=0):
        return await receive(
            socket,
            lambda message: message.get("type") == "state"
            and (status is None or message.get("roomStatus") == status)
            and message["game"]["revision"] >= revision,
            "房间状态", timeout,
        )

    try:
        async with asyncio.timeout(game_timeout):
            players = []
            for session in sessions[:player_count]:
                socket = await connect(session)
                joined = await state(socket, status="waiting")
                require(bool(joined["yourPlayerId"]), "首次握手未获得玩家座位")
                players.append(socket)
            spectator = await connect(sessions[player_count], "spectator")
            require((await state(spectator))["yourPlayerId"] is None, "旁观者握手错误")
            print(f"smoke：首次握手成功（协议 v{PROTOCOL_VERSION}，{player_count} 名玩家与旁观者）")
            await players[0].send(json.dumps({"type": "host", "action": "start"}))
            states = list(await asyncio.gather(*(state(socket, status="playing") for socket in players)))
            public = await state(spectator, status="playing")
            print("smoke：建局成功")
            command_count = 0

            async def command(index, action):
                nonlocal command_count, states, public
                require(command_count < max_commands, f"对局超过命令上限（{max_commands} 条）")
                command_count += 1
                command_id = f"release-smoke-{command_count}"
                revision = states[index]["game"]["revision"]
                await players[index].send(json.dumps({
                    "type": "command", "command": action["type"],
                    "payload": {key: value for key, value in action.items() if key != "type"},
                    "commandId": command_id, "expectedRevision": revision,
                }))
                ack = await receive(players[index], lambda message: message.get("type") == "ack" and message.get("commandId") == command_id, "命令确认", timeout)
                require(ack.get("status") == "accepted" and ack["revision"] > revision, "命令未被接受或未推进修订号")
                states = list(await asyncio.gather(*(state(socket, revision=ack["revision"]) for socket in players)))
                public = await state(spectator, revision=ack["revision"])
                require(all(item["game"]["revision"] == ack["revision"] for item in [*states, public]), "各连接修订号不同步")

            holder = states[0]["game"]["daggerHolderId"]
            index = next(index for index, item in enumerate(states) if item["yourPlayerId"] == holder)
            action = next(action for action in states[index]["game"]["legalActions"] if action["type"] == "pass-dagger")
            await command(index, action)
            print("smoke：命令确认成功（传递匕首）")
            before = states[index]
            await players[index].close()
            players[index] = await connect(sessions[index])
            resumed = await state(players[index], status="playing", revision=before["game"]["revision"])
            require(resumed["yourPlayerId"] == holder and resumed["game"] == before["game"] and resumed["isHost"] == before["isHost"], "账号重连未恢复座位、权限或完整状态")
            states[index] = resumed
            print("smoke：账号重连成功（座位与状态一致）")
            while public["roomStatus"] != "ended":
                index, action = next_action(states)
                await command(index, action)
            game = public["game"]
            require(game["status"] == "ended" and bool(game["result"]), "终局未提供结果")
            require(any(player["captured"] and player["damage"] == 4 for player in game["players"]), "终局没有第 4 点伤害捕获")
            if player_count % 2:
                # 规则语料：奇数人数对局必有 1 名审判者（secret-order），
                # 终局帧按 ADR 0015 公开身份。
                inquisitors = [player for player in game["players"] if player.get("identity", {}).get("faction") == "secret-order"]
                require(len(inquisitors) == 1, "奇数局终局未公开恰好 1 名审判者")
                print("smoke：奇数局含 1 名审判者")
            for item in states:
                require({key: value for key, value in item["game"].items() if key not in {"viewer", "legalActions"}} == {key: value for key, value in game.items() if key not in {"viewer", "legalActions"}}, "玩家终局与旁观终局不一致")
            print(f"smoke：终局成功（{command_count} 条命令，修订号 {game['revision']}）")
            return game
    except TimeoutError as error:
        raise SmokeFailure(f"对局超过总时限（{game_timeout:g} 秒）") from error
    finally:
        await asyncio.gather(*(socket.close() for socket in sockets), return_exceptions=True)


def validate_replay(replay: dict, final: dict) -> None:
    require(replay["gameId"] == final["gameId"], "回放对局 ID 不一致")
    steps = replay["steps"]
    require(bool(steps), "终局回放为空")
    require(steps[-1] == final, "回放末尾与实测旁观终局不一致")
    revision = -1
    for step in steps:
        require(step["revision"] > revision, "回放修订号未递增")
        revision = step["revision"]
        require(step.get("viewer") is None and step.get("legalActions") == [], "回放不是旁观者投影")
        public_players = []
        for player in step["players"]:
            require("rank" not in player and "faction" not in player and player.get("identityMarkers") == [None, None], "回放泄露未公开的玩家身份或标记")
            if "identity" in player:
                # ADR 0015 的例外只允许结束帧 players[].identity；其他路径
                # 和进行中的帧仍经过原有递归保密检查。
                identity = player["identity"]
                require(step["status"] == "ended" and isinstance(identity, dict), "回放提前揭晓身份")
                require(set(identity) == {"faction", "rank"}, "终局身份包含额外字段")
                faction, rank = identity["faction"], identity["rank"]
                require(
                    (faction in {"rose", "beast"} and type(rank) is int and 1 <= rank <= 9)
                    or (faction == "secret-order" and rank == "fleur-cross"),
                    "终局身份不合法",
                )
            public_players.append({key: value for key, value in player.items() if key != "identity"})
        check_private_fields({**step, "players": public_players})


def check_private_fields(value) -> None:
    if isinstance(value, dict):
        require(not {"seed", "identity", "clueIcon", "seenNeighbourClue", "cursesToDistribute", "inspections", "hostToken"}.intersection(value), "回放包含私有字段")
        for child in value.values():
            check_private_fields(child)
    elif isinstance(value, list):
        for child in value:
            check_private_fields(child)


def positive_seconds(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("时限必须是有限正数")
    return seconds


def positive_count(value: str) -> int:
    count = int(value)
    if count <= 0:
        raise argparse.ArgumentTypeError("命令上限必须是正整数")
    return count


def player_count(value: str) -> int:
    count = int(value)
    if not 6 <= count <= 12:
        raise argparse.ArgumentTypeError("玩家人数必须在 6-12 之间")
    return count


def find_unused_code(base: str, created: str, timeout: float) -> str:
    """取一个房间概览 404 的房号，用于未知房回放反例。"""
    for offset in range(1, 11):
        candidate = f"{(int(created) + offset) % 10 ** 6:06d}"
        if candidate != created and request(f"{base}/api/rooms/{candidate}", timeout=timeout)[0] == 404:
            return candidate
    raise SmokeFailure("找不到不存在的房号用于未知房检查")


def main() -> int:
    parser = argparse.ArgumentParser(description="鲜血盟约自托管发布 smoke 检查")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="服务地址")
    parser.add_argument("--timeout", type=positive_seconds, default=5, help="单次 HTTP/连接/消息等待上限（秒，默认 5）")
    parser.add_argument("--game-timeout", type=positive_seconds, default=60, help="WebSocket 完整流程总时限（秒，默认 60）")
    parser.add_argument("--max-commands", type=positive_count, default=100, help="对局命令上限（默认 100）")
    parser.add_argument("--players", type=player_count, default=6, help="玩家人数 6-12（奇数局含审判者），默认 6")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    try:
        status, health = request(f"{base}/health", timeout=args.timeout)
        require(status == 200 and health.get("status") == "ok", "健康检查失败")
        sessions = [AccountClient(base, args.timeout).register_test_account() for _ in range(args.players + 1)]
        status, room = sessions[0].request("/api/rooms", method="POST")
        require(status == 200 and len(room.get("code", "")) == 6 and "hostToken" not in room, "创建房间失败")
        status, info = request(f"{base}/api/rooms/{room['code']}", timeout=args.timeout)
        require(status == 200 and info.get("status") == "waiting", "等待房间概览检查失败")
        # 回放要求登录（工单 23）：匿名被拒，登录后按房号给出明确拒绝原因。
        unknown = find_unused_code(base, room["code"], args.timeout)
        status, replay_error = request(f"{base}/api/rooms/{room['code']}/replay", timeout=args.timeout)
        require(status == 401 and replay_error.get("code") == "auth.login-required", "未登录未拒绝回放")
        status, replay_error = request(f"{base}/api/rooms/{unknown}/replay", timeout=args.timeout)
        require(status == 401, "未登录请求未知房回放必须先拒登录")
        status, replay_error = sessions[args.players].request(f"/api/rooms/{room['code']}/replay")
        require(status == 409 and replay_error.get("code") == "room.not-ended", "未结束房间未拒绝回放")
        status, replay_error = sessions[args.players].request(f"/api/rooms/{unknown}/replay")
        require(status == 404 and replay_error.get("code") == "room.not-found", "未知房间未给出明确原因")
        status, metrics = request(f"{base}/metrics", timeout=args.timeout)
        require(status == 200 and "hostToken" not in json.dumps(metrics), "运行指标检查失败")
        final = asyncio.run(websocket_smoke(base, room, sessions, timeout=args.timeout, game_timeout=args.game_timeout, max_commands=args.max_commands, player_count=args.players))
        status, info = request(f"{base}/api/rooms/{room['code']}", timeout=args.timeout)
        require(status == 200 and info.get("status") == "ended", "终局房间概览检查失败")
        # 参与者与登录的非参与者账号都能读取同一份正常终局公开回放。
        status, replay = sessions[0].request(f"/api/rooms/{room['code']}/replay")
        require(status == 200, f"终局回放请求失败（HTTP {status}）")
        outsider = AccountClient(base, args.timeout).register_test_account()
        status, outsider_replay = outsider.request(f"/api/rooms/{room['code']}/replay")
        require(status == 200 and outsider_replay == replay, "非参与者登录后必须能读到相同回放")
        validate_replay(replay, final)
        print(f"smoke：公开回放成功（{len(replay['steps'])} 步，末尾与终局一致）")
    except (SmokeFailure, WebSocketException, KeyError, ValueError, OSError, RuntimeError) as error:
        print(f"smoke 失败：{error}", file=sys.stderr)
        return 1
    print(f"smoke 通过：房间 {room['code']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
