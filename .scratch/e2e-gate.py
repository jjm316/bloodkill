# -*- coding: utf-8 -*-
"""干涉请求门控（挡刀请求确认，ADR 0012 / ticket 05）e2e 验收驱动。

对真实 uvicorn 服务端（协议 v3）分步执行；浏览器侧的弹窗/横幅/按钮点击由
chrome-devtools 驱动完成（证据截图见 .scratch/e2e-gate/）。本脚本只负责
协议层准备与观众只读断言，仿 e2e-curse.py / e2e25.py 的连接骨架
（每条子命令独立连接、同名 hello 自动恢复座位、状态由服务端持有），
但 hello 一律携带 protocolVersion "3"（协议 v3 硬切，ticket 03）。

子命令：
  open           建房 + P1..P7 入座 + 开局（干涉时限 180 秒、单人窗口 180 秒），
                 逐一连接记录每人 faction/rank 与开局匕首持有者 —— 主房间
                 （路径一 请求挡刀 / 路径二 自己承受 / 路径三 no-assist）
  open-short     同上但干涉时限 30 秒 —— 超时房间（门控静默到期路径）
  pass <name>    把匕首传给 <name>（仅在浏览器接管座位之前使用；
                 以当前持有者名义连接会把其同名浏览器会话顶下线）
  status [short] 观众只读查房（不接管任何座位）：匕首归属、pending 的
                 kind/stage/deadline/资格名单/responses、每人的
                 damage/captured/已亮线索；顺带断言观众投影无私密泄露

运行前置（在本 worktree 内）：
  client 已 `npm run build`；服务端已起：
  /d/AIProj/bloodkill/.venv/Scripts/python.exe scripts/test_toolkit.py serve --port 8010
浏览器窗口统一用 http://127.0.0.1:8010/?room=<code>&name=<Pn> 进入。
"""
import io
import json
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8010"
WS = "ws://127.0.0.1:8010"
STATE_FILE = ".scratch/e2e-gate.json"
PROTOCOL = "3"  # 协议 v3：门控契约（ticket 03 硬切，v2 会被拒）


def load():
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def save(data):
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


class Client:
    """一条玩家/观众连接；短生命周期，用完即 close。"""

    def __init__(self, slot, name, token=None):
        from websockets.sync.client import connect

        info = load()[slot]
        self.ws = connect(f"{WS}/ws/{info['code']}", open_timeout=10)
        hello = {"type": "hello", "name": name, "protocolVersion": PROTOCOL}
        if token:
            hello["token"] = token
        self.ws.send(json.dumps(hello))
        self.name = name
        self.state = None
        self.events = []
        import threading

        def reader():
            try:
                for raw in self.ws:
                    message = json.loads(raw)
                    if message.get("type") == "state":
                        self.state = message
                    elif message.get("type") == "event":
                        self.events.extend(message.get("events") or [])
            except Exception:
                pass

        threading.Thread(target=reader, daemon=True).start()
        deadline = time.time() + 5
        while self.state is None and time.time() < deadline:
            time.sleep(0.05)
        if self.state is None:
            raise TimeoutError(f"{name}: 未收到初始状态")

    def send(self, command, payload=None, timeout=6.0):
        before = self.state["game"]["revision"]
        self.ws.send(json.dumps({
            "type": "command",
            "commandId": f"{command}-{time.time_ns()}",
            "command": command,
            "payload": payload or {},
            "expectedRevision": before,
        }))
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = self.state
            if state is not None and state["game"]["revision"] != before:
                return state
            time.sleep(0.05)
        raise TimeoutError(f"{self.name}: {command} 后 revision 未推进（当前 {before}）")

    def send_host(self, action, payload=None):
        self.ws.send(json.dumps({"type": "host", "action": action, **(payload or {})}))
        deadline = time.time() + 8
        while time.time() < deadline:
            if self.state and self.state.get("roomStatus") == "playing":
                return self.state
            time.sleep(0.05)
        return self.state

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def game_of(client):
    return client.state["game"]


def names_of(client):
    return {p["playerId"]: p["displayName"] for p in game_of(client)["players"]}


def player_id_of(client, name):
    return next(p["playerId"] for p in game_of(client)["players"] if p["displayName"] == name)


def name_of(client, pid):
    return names_of(client).get(pid, "?")


def cmd_setup(state, slot, intervention_seconds, single_seconds=180):
    request = urllib.request.Request(f"{BASE}/api/rooms", method="POST")
    with urllib.request.urlopen(request) as response:
        room = json.load(response)
    state[slot] = {"code": room["code"], "hostToken": room["hostToken"], "gameId": room["gameId"]}
    save(state)
    for index in range(1, 8):
        client = Client(slot, f"P{index}")
        client.close()
    host = Client(slot, "P1", state[slot]["hostToken"])
    started = host.send_host("start", {
        "interventionTimeoutSeconds": intervention_seconds,
        "singleWindowTimeoutSeconds": single_seconds,
    })
    assert started and started.get("roomStatus") == "playing", started and started.get("roomStatus")
    host.close()
    # 逐一连接读取各自身份（viewer.identity 含 faction 与 rank），供断言
    # 「挡刀强制亮出真实 rank」与终局说明使用。
    info = state[slot]
    for index in range(1, 8):
        name = f"P{index}"
        probe = Client(slot, name)
        identity = game_of(probe)["viewer"]["identity"]
        info[name] = {"faction": identity["faction"], "rank": identity["rank"]}
        probe.close()
    spectator = Client(slot, "")
    info["holder"] = name_of(spectator, game_of(spectator)["daggerHolderId"])
    spectator.close()
    save(state)
    print(json.dumps({
        "slot": slot,
        "code": info["code"],
        "url": f"{BASE}/?room={info['code']}&name=P1",
        "holder": info["holder"],
        "identities": {n: info[n] for n in (f"P{i}" for i in range(1, 8))},
    }, ensure_ascii=False))


def cmd_open():
    state = load()
    cmd_setup(state, "main", 180)


def cmd_open_short():
    state = load()
    cmd_setup(state, "short", 30)


def cmd_pass(name):
    state = load()
    spectator = Client("main", "")
    holder = name_of(spectator, game_of(spectator)["daggerHolderId"])
    spectator.close()
    if holder == name:
        print(json.dumps({"holder": holder, "passed": False}))
        return
    passer = Client("main", holder)
    passer.send("pass-dagger", {"targetPlayerId": player_id_of(passer, name)})
    passer.close()
    print(json.dumps({"holder": holder, "passed": True, "to": name}))


def cmd_status(slot="main"):
    client = Client(slot, "")
    game = game_of(client)
    pending = game["pending"]
    # 观众无私密泄露：pending 无私有 context，观众无 legalActions。
    assert pending is None or "context" not in pending, pending
    assert game["legalActions"] == [], game["legalActions"]
    view = {
        "slot": slot,
        "revision": game["revision"],
        "status": game["status"],
        "holder": name_of(client, game["daggerHolderId"]) if game["daggerHolderId"] else None,
        "pending": None,
        "players": [
            {
                "name": p["displayName"],
                "damage": p["damage"],
                "captured": p["captured"],
                "revealed": p.get("revealed") or {},
            }
            for p in game["players"]
        ],
    }
    if pending:
        view["pending"] = {
            "kind": pending["kind"],
            "stage": pending.get("stage"),
            "target": name_of(client, pending.get("targetPlayerId")),
            "actor": name_of(client, pending.get("actorPlayerId")) if pending.get("actorPlayerId") else None,
            "deadline": pending.get("deadline"),
            "eligible": [name_of(client, pid) for pid in pending.get("eligiblePlayerIds") or []],
            "responses": {name_of(client, k): v for k, v in (pending.get("responses") or {}).items()},
            "rank": pending.get("rank"),
        }
    client.close()
    print(json.dumps(view, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "open":
        cmd_open()
    elif command == "open-short":
        cmd_open_short()
    elif command == "pass":
        cmd_pass(sys.argv[2])
    elif command == "status":
        cmd_status(sys.argv[2] if len(sys.argv) > 2 else "main")
    else:
        raise SystemExit(f"unknown command {command}")
