# -*- coding: utf-8 -*-
"""Issue 23 端到端驱动：对真实 uvicorn 服务端分步执行干涉投票场景。

每条子命令独立连接（同名 hello 自动恢复座位），状态由服务端持有，
因此可以配合浏览器手动操作交替进行。运行：python .scratch/e2e23.py <cmd>
"""
import io
import json
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8000"
STATE_FILE = ".scratch/e2e23.json"


def load():
    with open(STATE_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def save(data):
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


class Client:
    def __init__(self, name, token=None):
        from websockets.sync.client import connect

        info = load()
        url = f"ws://127.0.0.1:8000/ws/{info['code']}"
        self.ws = connect(url, open_timeout=10)
        hello = {"type": "hello", "name": name, "protocolVersion": "2"}
        if token:
            hello["token"] = token
        self.ws.send(json.dumps(hello))
        self.name = name
        self.state = None
        self._drain()

    def _drain(self):
        import threading

        def reader():
            try:
                for raw in self.ws:
                    message = json.loads(raw)
                    if message["type"] == "state":
                        self.state = message
            except Exception:
                pass

        self.thread = threading.Thread(target=reader, daemon=True)
        self.thread.start()
        deadline = time.time() + 5
        while self.state is None and time.time() < deadline:
            time.sleep(0.05)

    def send(self, command, payload=None):
        info = load()
        self.ws.send(json.dumps({
            "type": "command",
            "commandId": f"{command}-{time.time_ns()}",
            "command": command,
            "payload": payload or {},
            "expectedRevision": self.state["game"]["revision"],
        }))
        time.sleep(0.6)
        return self.state

    def send_host(self, action, payload=None):
        self.ws.send(json.dumps({"type": "host", "action": action, **(payload or {})}))
        time.sleep(0.8)
        return self.state

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def brief(state, viewer=None):
    game = state["game"]
    pending = game["pending"]
    summary = {
        "revision": game["revision"],
        "phase": game["phase"],
        "dagger": game["daggerHolderId"],
        "viewer": viewer,
        "legalActions": [a["type"] for a in game["legalActions"]],
        "serverTime": round(state["serverTime"], 1),
    }
    if pending and pending.get("kind") == "intervention":
        summary["intervention"] = {
            "stage": pending.get("stage"),
            "responses": {pid.split("-")[0]: v for pid, v in (pending.get("responses") or {}).items()},
            "deadline": pending.get("deadline"),
            "volunteers": [pid.split("-")[0] for pid in (pending.get("volunteerPlayerIds") or [])],
        }
    return summary


def cmd_setup():
    request = urllib.request.Request(f"{BASE}/api/rooms", method="POST")
    with urllib.request.urlopen(request) as response:
        room = json.load(response)
    save({"code": room["code"], "hostToken": room["hostToken"], "gameId": room["gameId"]})
    print(f"room {room['code']}")
    names = [f"P{i}" for i in range(1, 8)]
    for name in names:
        client = Client(name)
        client.close()
    print("joined P1..P7（P7 留给浏览器）")


def cmd_start(seconds=30):
    info = load()
    client = Client("P1", info["hostToken"])
    state = client.send_host("start", {"interventionTimeoutSeconds": seconds})
    game = state["game"]
    holder = next(p["displayName"] for p in game["players"] if p["playerId"] == game["daggerHolderId"])
    info["holder"] = holder
    save(info)
    print(json.dumps({"timeoutSeconds": game.get("interventionTimeoutSeconds"), "holder": holder}, ensure_ascii=False))


def cmd_attack(target):
    client = Client("P1")  # 任意已入座名字，只为读取公共状态
    game = client.state["game"]
    holder_id = game["daggerHolderId"]
    holder = next(p["displayName"] for p in game["players"] if p["playerId"] == holder_id)
    info = load()
    info["holder"] = holder
    save(info)
    client.close()
    client = Client(holder)
    target_id = next(p["playerId"] for p in client.state["game"]["players"] if p["displayName"] == target)
    state = client.send("attack", {"targetPlayerId": target_id})
    print(json.dumps(brief(state, holder), ensure_ascii=False, indent=1))


def cmd_respond(who, volunteer):
    client = Client(who)
    state = client.send("respond-intervention", {"volunteer": volunteer})
    print(json.dumps(brief(state, who), ensure_ascii=False, indent=1))


def cmd_respond_all(volunteers):
    """让当前 poll 里除指定自愿者与 P7 外的所有人表态。"""
    info = load()
    client = Client("P1", info["hostToken"])
    game = client.state["game"]
    pending = game["pending"]
    assert pending and pending["kind"] == "intervention" and pending["stage"] == "poll", brief(client.state)
    ids = {p["playerId"]: p["displayName"] for p in game["players"]}
    for pid in pending["eligiblePlayerIds"]:
        name = ids[pid]
        if name == "P7" or name in volunteers:
            continue
        # 每人一条独立连接，避免 revision 竞速
        responder = Client(name)
        responder.send("respond-intervention", {"volunteer": False})
        responder.close()
    for name in volunteers:
        responder = Client(name)
        responder.send("respond-intervention", {"volunteer": True})
        responder.close()
    client.close()
    watcher = Client("P1", info["hostToken"])
    print(json.dumps(brief(watcher.state, "P1"), ensure_ascii=False, indent=1))


def cmd_decline_all(who):
    client = Client(who)
    state = client.send("decline-intervention")
    print(json.dumps(brief(state, who), ensure_ascii=False, indent=1))


def cmd_choose(who, responder_name):
    client = Client(who)
    responder_id = next(p["playerId"] for p in client.state["game"]["players"] if p["displayName"] == responder_name)
    state = client.send("choose-intervention", {"responderPlayerId": responder_id})
    print(json.dumps(brief(state, who), ensure_ascii=False, indent=1))


def cmd_status(viewer):
    client = Client(viewer)
    print(json.dumps(brief(client.state, viewer), ensure_ascii=False, indent=1))


def cmd_skill(who, use):
    client = Client(who)
    state = client.send("choose-skill", {"use": use in ("true", "1", "yes")})
    print(json.dumps(brief(state, who), ensure_ascii=False, indent=1))


def cmd_wait_timeout(viewer, seconds):
    client = Client(viewer)
    before = brief(client.state, viewer)
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(1)
        snapshot = client.state
        if snapshot["game"]["pending"] is None or snapshot["game"]["pending"]["kind"] != "intervention":
            break
    after = brief(client.state, viewer)
    events = None
    print(json.dumps({"before": before, "after": after}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "setup":
        cmd_setup()
    elif command == "start":
        cmd_start(int(sys.argv[2]) if len(sys.argv) > 2 else 30)
    elif command == "attack":
        cmd_attack(sys.argv[2])
    elif command == "respond":
        cmd_respond(sys.argv[2], sys.argv[3] in ("true", "1", "yes"))
    elif command == "respond-all":
        cmd_respond_all(sys.argv[2:])
    elif command == "decline-all":
        cmd_decline_all(sys.argv[2])
    elif command == "choose":
        cmd_choose(sys.argv[2], sys.argv[3])
    elif command == "skill":
        cmd_skill(sys.argv[2], sys.argv[3])
    elif command == "status":
        cmd_status(sys.argv[2])
    elif command == "wait-timeout":
        cmd_wait_timeout(sys.argv[2], int(sys.argv[3]))
    else:
        raise SystemExit(f"unknown command {command}")
