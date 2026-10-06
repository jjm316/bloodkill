# -*- coding: utf-8 -*-
"""ui-fix-usability 视觉验收驱动：建房 / 开局 / 攻击开干涉投票。

浏览器座位固定留给 P7（用 ?room=&name=P7 自动进房）。运行：
    python .scratch/ui-usability-visual.py setup|start|attack
"""
import io
import json
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8000"
STATE_FILE = ".scratch/ui-usability.json"


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


def cmd_setup():
    request = urllib.request.Request(f"{BASE}/api/rooms", method="POST")
    with urllib.request.urlopen(request) as response:
        room = json.load(response)
    save({"code": room["code"], "hostToken": room["hostToken"], "gameId": room["gameId"]})
    print(f"room {room['code']}")
    for index in range(1, 7):
        client = Client(f"P{index}")
        client.close()
    print("joined P1..P6（P1 房主；P7 留给浏览器）")


def cmd_start():
    info = load()
    client = Client("P1", info["hostToken"])
    state = client.send_host("start", {"interventionTimeoutSeconds": 180})
    game = state["game"]
    holder = next(p["displayName"] for p in game["players"] if p["playerId"] == game["daggerHolderId"])
    client.close()
    print(json.dumps({"holder": holder}, ensure_ascii=False))


def cmd_attack():
    client = Client("P1")
    game = client.state["game"]
    holder_id = game["daggerHolderId"]
    holder = next(p["displayName"] for p in game["players"] if p["playerId"] == holder_id)
    target = next(p for p in game["players"] if p["playerId"] != holder_id and p["displayName"] != "P7")
    client.close()
    client = Client(holder)
    state = client.send("attack", {"targetPlayerId": target["playerId"]})
    pending = state["game"]["pending"]
    client.close()
    print(json.dumps({"holder": holder, "target": target["displayName"], "pending": pending and pending["kind"]}, ensure_ascii=False))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("setup", "start", "attack"):
        print(__doc__)
        sys.exit(2)
    {"setup": cmd_setup, "start": cmd_start, "attack": cmd_attack}[sys.argv[1]]()


if __name__ == "__main__":
    main()
