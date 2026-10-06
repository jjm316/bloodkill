# -*- coding: utf-8 -*-
"""一次性截图布景：开新房、8 人入座开局，打出一个"有伤害、有亮牌、
干涉投票进行中"的中局，然后全部断线退出，留给浏览器截图。

产出打印：房间号 / 各玩家名。最后一击目标是 阿玫（投票保持未表态）。
"""
import io
import json
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"

NAMES = ["阿玫", "小兽", "老K", "阿紫", "大猫", "阿飞", "咪咪", "团子"]
TARGET = "阿玫"


def http_json(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


class Client:
    def __init__(self, name, token=None):
        from websockets.sync.client import connect

        self.ws = connect(f"{WS}/ws/{CODE}", open_timeout=10)
        hello = {"type": "hello", "name": name, "protocolVersion": "2"}
        if token:
            hello["token"] = token
        self.ws.send(json.dumps(hello))
        self.name = name
        self.state = None
        self.events = []
        self._drain()

    def _drain(self):
        import threading

        def reader():
            try:
                for raw in self.ws:
                    message = json.loads(raw)
                    kind = message.get("type")
                    if kind == "state":
                        self.state = message
                    elif kind == "event":
                        self.events.extend(message.get("events") or [])
            except Exception:
                pass

        threading.Thread(target=reader, daemon=True).start()
        deadline = time.time() + 8
        while self.state is None and time.time() < deadline:
            time.sleep(0.05)
        if self.state is None:
            raise TimeoutError(f"{self.name}: 未收到首份状态")

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
            if self.state and self.state["game"]["revision"] != before:
                return self.state
            time.sleep(0.05)
        raise TimeoutError(f"{self.name}: {command} 后 revision 未推进")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def pid_of(client, name):
    return next(p["playerId"] for p in client.state["game"]["players"] if p["displayName"] == name)


def name_of(client, pid):
    return next(p["displayName"] for p in client.state["game"]["players"] if p["playerId"] == pid)


def as_client(name):
    return Client(name)


def answer_poll_all_decline(client):
    pending = client.state["game"]["pending"]
    assert pending and pending["kind"] == "intervention"
    answered = set(pending.get("responses") or {})
    for p in pending["eligiblePlayerIds"]:
        if p in answered:
            continue
        responder = Client(name_of(client, p))
        responder.send("respond-intervention", {"volunteer": False})
        responder.close()
    return as_client(client.name)


def resolve_reveal(client):
    pending = client.state["game"]["pending"]
    actor = name_of(client, pending["actorPlayerId"])
    revealer = Client(actor)
    tokens = pending.get("eligibleTokens") or []
    markers = [t for t in tokens if t.startswith("marker-")]
    token = markers[0] if markers else tokens[0]
    return revealer.send("choose-reveal", {"token": token})


def settle_all(client):
    """把一切 pending 结算完（技能一律放弃），直到无 pending 或终局。"""
    for _ in range(60):
        state = client.state["game"]
        pending = state["pending"]
        if state["status"] == "ended" or pending is None:
            return client
        kind = pending["kind"]
        actor = name_of(client, pending["actorPlayerId"])
        if kind == "intervention":
            client = answer_poll_all_decline(client)
        elif kind == "reveal":
            client = Client(actor) if actor != client.name else client
            resolve_reveal(client)
        elif kind == "skill":
            client = Client(actor) if actor != client.name else client
            client.send("choose-skill", {"use": False})
        elif kind == "token-return":
            client = Client(actor) if actor != client.name else client
            tokens = pending.get("eligibleTokens") or []
            client.send("choose-return", {"token": tokens[0]})
        else:
            raise AssertionError(f"未知 pending {kind}")
    raise AssertionError("settle_all 迭代超限")


def hand_dagger(client, name):
    holder_id = client.state["game"]["daggerHolderId"]
    if holder_id == pid_of(client, name):
        return client
    holder = Client(name_of(client, holder_id))
    holder.send("pass-dagger", {"targetPlayerId": pid_of(holder, name)})
    holder.close()
    return as_client(client.name)


def main():
    global CODE
    room = http_json("/api/rooms", method="POST")
    CODE = room["code"]
    host_token = room["hostToken"]
    print("房间号:", CODE)

    host = Client(NAMES[0], host_token)
    for name in NAMES[1:]:
        Client(name).close()
    ref = Client(NAMES[1])
    assert len(ref.state["game"]["players"]) == 8
    ref.close()
    host.send_host_start = None
    host.ws.send(json.dumps({"type": "host", "action": "start", "interventionTimeoutSeconds": 120}))
    deadline = time.time() + 8
    while time.time() < deadline:
        if host.state and host.state["roomStatus"] == "playing":
            break
        time.sleep(0.05)
    assert host.state["roomStatus"] == "playing"
    print("已开局, 8 人")

    # 第 1 轮：阿玫 持刀攻击 小兽 → 全员不干涉 → 小兽受伤亮牌
    client = hand_dagger(host, NAMES[0])
    client = Client(NAMES[0])
    client.send("attack", {"targetPlayerId": pid_of(client, NAMES[1])})
    client = answer_poll_all_decline(client)
    settle_all(client)
    print("第 1 轮完成, revision", client.state["game"]["revision"])

    # 第 2 轮：小兽 持刀攻击 老K → 全员不干涉 → 老K 受伤亮牌
    client = hand_dagger(client, NAMES[1])
    client = Client(NAMES[1])
    client.send("attack", {"targetPlayerId": pid_of(client, NAMES[2])})
    client = answer_poll_all_decline(client)
    settle_all(client)
    print("第 2 轮完成, revision", client.state["game"]["revision"])

    # 最后一击：老K 把刀传给 大猫，大猫攻击 阿玫，投票保持打开
    client = hand_dagger(client, NAMES[4])
    client = Client(NAMES[4])
    client.send("attack", {"targetPlayerId": pid_of(client, TARGET)})
    pending = as_client(NAMES[2]).state["game"]["pending"]
    assert pending and pending["kind"] == "intervention" and pending.get("stage") == "poll"
    print("干涉投票已打开, 目标:", TARGET)

    for c in (host, client):
        c.close()
    print("布景完成。房间:", CODE, "目标:", TARGET)
    print("玩家名单:", "、".join(NAMES))


if __name__ == "__main__":
    main()
