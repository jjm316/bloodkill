# -*- coding: utf-8 -*-
"""ui-table-theme 视觉验收布景。

scene   ：8 人中局——两轮攻击已结算（有伤害/亮牌），最后由 阿紫（浏览器座位）
          持刀攻击 大猫，干涉投票保持打开（时限 180s），全部机器人断线，
          浏览器用 ?room=&name=阿紫 同名接管入座。
waiting ：另开一间 7 人等待房，浏览器作为第 8 人加入看等待房主题。

运行：python .scratch/ui-table-theme/scene.py scene|waiting
"""
import io
import json
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"

# 入座顺序即座位顺序；阿紫 = 浏览器座位（与参考稿 mockup 同构）
NAMES = ["阿玫", "小兽", "老K", "阿紫", "大猫", "阿飞", "咪咪", "团子"]
BROWSER = "阿紫"
STATE_FILE = ".scratch/ui-table-theme/state.json"


def http_json(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def save(data):
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


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
        self._drain()

    def _drain(self):
        import threading

        def reader():
            try:
                for raw in self.ws:
                    message = json.loads(raw)
                    if message.get("type") == "state":
                        self.state = message
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
    """client 必须就是亮牌当事者。wild 标记的 choose-reveal 带 color（rose/beast 二选一）。"""
    actions = client.state["game"]["legalActions"]
    reveals = [a for a in actions if a["type"] == "choose-reveal"]
    assert reveals, "无 choose-reveal 动作"
    pick = reveals[0]
    payload = {"token": pick["token"]}
    if "color" in pick:
        payload["color"] = pick["color"]
    return client.send("choose-reveal", payload)


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
            actions = client.state["game"]["legalActions"]
            returns = [a for a in actions if a["type"] == "choose-return"]
            assert returns, "无 choose-return 动作"
            client.send("choose-return", {"token": returns[0]["token"]})
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


def cmd_scene():
    room = http_json("/api/rooms", method="POST")
    globals()["CODE"] = room["code"]
    print("房间号:", CODE)

    host = Client(NAMES[0], room["hostToken"])
    for name in NAMES[1:]:
        Client(name).close()
    assert len(Client(NAMES[1]).state["game"]["players"]) == len(NAMES)
    host.ws.send(json.dumps({"type": "host", "action": "start", "interventionTimeoutSeconds": 180}))
    deadline = time.time() + 8
    while time.time() < deadline:
        if host.state and host.state["roomStatus"] == "playing":
            break
        time.sleep(0.05)
    assert host.state["roomStatus"] == "playing"
    print(f"已开局, {len(NAMES)} 人")

    # 第 1 轮：阿玫 持刀攻击 小兽 → 全员不干涉 → 小兽受伤亮牌
    client = hand_dagger(host, NAMES[0])
    client = Client(NAMES[0])
    client.send("attack", {"targetPlayerId": pid_of(client, NAMES[1])})
    client = answer_poll_all_decline(client)
    settle_all(client)
    print("第 1 轮完成")

    # 第 2 轮：小兽 持刀攻击 老K → 全员不干涉 → 老K 受伤亮牌
    client = hand_dagger(client, NAMES[1])
    client = Client(NAMES[1])
    client.send("attack", {"targetPlayerId": pid_of(client, NAMES[2])})
    client = answer_poll_all_decline(client)
    settle_all(client)
    print("第 2 轮完成")

    # 最后一击：刀交给 阿紫（浏览器座位），攻击 大猫，投票保持打开
    client = hand_dagger(client, BROWSER)
    client = Client(BROWSER)
    client.send("attack", {"targetPlayerId": pid_of(client, NAMES[4])})
    pending = as_client(NAMES[0]).state["game"]["pending"]
    assert pending and pending["kind"] == "intervention" and pending.get("stage") == "poll"
    client.close()

    save({"code": CODE, "kind": "scene", "browser": BROWSER})
    print("布景完成：浏览器用 ?room=" + CODE + "&name=" + BROWSER + " 接管入座")
    print("干涉投票已打开（180s 时限），目标:", NAMES[4])


def cmd_waiting():
    room = http_json("/api/rooms", method="POST")
    globals()["CODE"] = room["code"]
    host = Client(NAMES[0], room["hostToken"])
    for name in NAMES[1:7]:  # 6 个机器人 + 房主 = 7，浏览器是第 8 人
        Client(name).close()
    host.close()
    save({"code": CODE, "kind": "waiting", "browser": "团子", "hostToken": room["hostToken"]})
    print("等待房就绪：浏览器用 ?room=" + CODE + "&name=团子 加入（当前 7 人）")
    print("浏览器入座并截图后，跑 waiting-lock 让锁图标出现")


def cmd_waiting_lock():
    with open(STATE_FILE, encoding="utf-8") as fh:
        info = json.load(fh)
    globals()["CODE"] = info["code"]
    host = Client(NAMES[0], info["hostToken"])
    host.ws.send(json.dumps({"type": "host", "action": "lock"}))
    time.sleep(0.8)
    host.close()
    print("已锁房：已入座的浏览器应看到房间号旁出现锁图标")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("scene", "waiting", "waiting-lock"):
        print(__doc__)
        sys.exit(2)
    {"scene": cmd_scene, "waiting": cmd_waiting, "waiting-lock": cmd_waiting_lock}[sys.argv[1]]()


if __name__ == "__main__":
    main()
