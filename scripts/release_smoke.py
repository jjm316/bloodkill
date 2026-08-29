"""自托管服务发布 smoke 检查。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import websockets


def request(url: str, method: str = "GET") -> tuple[int, dict]:
    try:
        with urlopen(Request(url, method=method), timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8")
        return error.code, json.loads(body) if body else {}


async def websocket_smoke(base: str, room: dict) -> None:
    """Exercise join, start, an action, and same-name reconnect over WebSocket."""
    code, host_token = room["code"], room["hostToken"]
    endpoint = base.replace("https://", "wss://").replace("http://", "ws://")
    sockets = []
    names = ["Smoke房主", "Smoke玩家2", "Smoke玩家3", "Smoke玩家4", "Smoke玩家5", "Smoke玩家6"]

    async def recv_state(socket, status: str | None = None):
        while True:
            message = json.loads(await socket.recv())
            if message.get("type") == "state" and (status is None or message.get("roomStatus") == status):
                return message

    async def recv_type(socket, expected_type: str):
        while True:
            message = json.loads(await socket.recv())
            if message.get("type") == expected_type:
                return message
    try:
        for index, name in enumerate(names):
            socket = await websockets.connect(f"{endpoint}/ws/{code}")
            await socket.send(json.dumps({"type": "hello", "name": name, "token": host_token if index == 0 else None, "protocolVersion": "1"}))
            message = await recv_state(socket)
            assert message.get("type") == "state", message
            sockets.append(socket)
        await sockets[0].send(json.dumps({"type": "host", "action": "start"}))
        states = [await recv_state(socket, "playing") for socket in sockets]
        assert all(state.get("roomStatus") == "playing" for state in states), states
        by_player = {state["yourPlayerId"]: socket for state, socket in zip(states, sockets)}
        game = states[0]["game"]
        holder = game["daggerHolderId"]
        target = next(player["playerId"] for player in game["players"] if player["playerId"] != holder)
        await by_player[holder].send(json.dumps({"type": "command", "command": "pass-dagger", "payload": {"targetPlayerId": target}, "commandId": "release-smoke-pass", "expectedRevision": game["revision"]}))
        ack = await recv_type(by_player[holder], "ack")
        assert ack.get("type") == "ack" and ack.get("status") == "accepted", ack
        holder_index = next(index for index, state in enumerate(states) if state["yourPlayerId"] == holder)
        await sockets[holder_index].close()
        resumed = await websockets.connect(f"{endpoint}/ws/{code}")
        await resumed.send(json.dumps({"type": "hello", "name": names[holder_index], "token": host_token if holder_index == 0 else None, "protocolVersion": "1"}))
        resumed_state = json.loads(await resumed.recv())
        assert resumed_state.get("yourPlayerId") == holder, resumed_state
        await resumed.close()
    finally:
        await asyncio.gather(*(socket.close() for socket in sockets), return_exceptions=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="鲜血盟约自托管发布 smoke 检查")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    try:
        status, health = request(f"{base}/health")
        assert status == 200 and health.get("status") == "ok", (status, health)
        status, room = request(f"{base}/api/rooms", method="POST")
        assert status == 200 and len(room.get("code", "")) == 6 and room.get("hostToken"), (status, room)
        status, info = request(f"{base}/api/rooms/{room['code']}")
        assert status == 200 and info.get("status") == "waiting", (status, info)
        status, _ = request(f"{base}/api/rooms/{room['code']}/replay")
        assert status == 409, status
        status, metrics = request(f"{base}/metrics")
        assert status == 200 and "hostToken" not in json.dumps(metrics), metrics
        asyncio.run(websocket_smoke(base, room))
    except (AssertionError, KeyError, URLError, TimeoutError, json.JSONDecodeError) as error:
        print(f"smoke 失败：{error}", file=sys.stderr)
        return 1
    print(f"smoke 通过：房间 {room['code']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
