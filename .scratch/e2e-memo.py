# -*- coding: utf-8 -*-
"""备忘标记 e2e 驱动：7 人局，浏览器用同名接管「备忘甲」座位做 UI 验收（issue 01）。

连接纪律（重要）：脚本的一切读写都走一次性连接（连上→读/发→断开），
绝不与浏览器争抢「备忘甲」座位——同名 hello 会接管座位。基准座位用 P2。
干涉投票只代答机器人座位，浏览器座位靠界面「默认不挡刀」自动表态；
若匕首/窗口落到浏览器座位，脚本报错交人工处理，不抢操作。

子命令：
- setup [浏览器名]：建房，加入浏览器座位 + P2..P7（默认浏览器名=备忘甲）；
- start：开局，读出浏览器座位的 seenNeighbourClue（右邻名字 + 徽记色）；
- status：打印局面摘要（revision / pending / 是否已结束）；
- endgame：把审判者打到被捕获，驱动对局到 ended（供回放与终局角标验收）。

备忘数据本身不经过协议（ADR 0004），脚本不读写任何备忘。
运行（先起服务端）：.venv/Scripts/python.exe .scratch/e2e-memo.py <cmd>
"""
import io
import json
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"
STATE_FILE = ".scratch/e2e-memo.json"


def load():
    with open(STATE_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def save(data):
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


class Client:
    """一次性连接：构造时收初始状态，send 等 revision 推进后由调用方 close。"""

    def __init__(self, name, token=None):
        from websockets.sync.client import connect

        self.ws = connect(f"{WS}/ws/{load()['code']}", open_timeout=10)
        hello = {"type": "hello", "name": name, "protocolVersion": "2"}
        if token:
            hello["token"] = token
        self.ws.send(json.dumps(hello))
        self.name = name
        self.state = None
        deadline = time.time() + 5
        while self.state is None and time.time() < deadline:
            try:
                message = json.loads(self.ws.recv(timeout=1))
            except Exception:
                continue
            if message.get("type") == "state":
                self.state = message
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
            try:
                message = json.loads(self.ws.recv(timeout=1))
            except Exception:
                continue
            kind = message.get("type")
            if kind == "state" and message["game"]["revision"] != before:
                self.state = message
                return message
            if kind == "ack" and message.get("status") == "rejected":
                raise RuntimeError(f"{self.name}: {command} 被拒：{message.get('error')}")
        raise TimeoutError(f"{self.name}: {command} 后 revision 未推进")

    def send_host(self, action, payload=None):
        self.ws.send(json.dumps({"type": "host", "action": action, **(payload or {})}))
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                message = json.loads(self.ws.recv(timeout=1))
            except Exception:
                continue
            if message.get("type") == "state" and message.get("roomStatus") == "playing":
                self.state = message
                return message
        return self.state

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def read(name="P2"):
    client = Client(name)
    state = client.state
    client.close()
    return state


def do(name, command, payload=None, *, retries=3):
    # 拒绝多半是读发之间 revision 被超时结算等推进（stale expectedRevision），换新连接重试
    for attempt in range(retries):
        client = Client(name)
        try:
            return client.send(command, payload)
        except (RuntimeError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(1.0)
        finally:
            client.close()


def names_of(state):
    return {p["playerId"]: p["displayName"] for p in state["game"]["players"]}


def pid_of(state, name):
    return next(p["playerId"] for p in state["game"]["players"] if p["displayName"] == name)


def brief(state):
    game = state["game"]
    holder = next((p["displayName"] for p in game["players"] if p["playerId"] == game["daggerHolderId"]), None)
    return {"revision": game["revision"], "status": game["status"],
            "pending": (game.get("pending") or {}).get("kind"), "dagger": holder}


def cmd_setup(browser_name="备忘甲"):
    request = urllib.request.Request(f"{BASE}/api/rooms", method="POST")
    with urllib.request.urlopen(request) as response:
        room = json.load(response)
    save({"code": room["code"], "hostToken": room["hostToken"], "browserName": browser_name})
    print(f"room {room['code']}")
    for name in [browser_name] + [f"P{i}" for i in range(2, 8)]:
        client = Client(name)
        client.close()
    print(f"joined {browser_name} + P2..P7")


def cmd_start(seconds=30):
    info = load()
    client = Client(info["browserName"], info["hostToken"])
    state = client.send_host("start", {"interventionTimeoutSeconds": seconds})
    client.close()
    assert state["roomStatus"] == "playing", state["roomStatus"]
    clue = state["game"]["viewer"]["seenNeighbourClue"]
    info["gameId"] = state["game"]["gameId"]
    info["neighbour"] = {
        "playerId": clue["playerId"],
        "name": names_of(state)[clue["playerId"]],
        "icon": clue["icon"],
    }
    save(info)
    print(json.dumps({
        "browserName": info["browserName"],
        "neighbour": info["neighbour"],
        "note": "浏览器加入后：右邻角标应自动填该徽记色（rose→玫红/beast→兽蓝）",
    }, ensure_ascii=False))


def cmd_status():
    print(json.dumps(brief(read()), ensure_ascii=False))


def actor_markers(actor):
    """读 actor 的未亮标记原始值（wild 需要选阵营）。"""
    client = Client(actor)
    raw = client.state["game"]["viewer"]["identityMarkers"]
    client.close()
    return list(raw)


def resolve_windows(timeout=60):
    """把可代答窗口清完：投票只代答机器人，浏览器座位靠「默认不挡刀」自动表态。"""
    browser = load()["browserName"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = read()
        game = state["game"]
        pending = game["pending"]
        if game["status"] == "ended" or pending is None:
            return state
        names = names_of(state)
        actor = names[pending["actorPlayerId"]]
        assert actor != browser, f"{pending['kind']} 窗口落在浏览器座位（{browser}），请在界面处理后重跑"
        kind = pending["kind"]
        if kind == "intervention":
            answered = set(pending.get("responses") or {})
            for pid in pending["eligiblePlayerIds"]:
                if names[pid] != browser and pid not in answered:
                    do(names[pid], "respond-intervention", {"volunteer": False})
        elif kind == "reveal":
            tokens = sorted(pending.get("eligibleTokens") or [])
            if actor == load().get("inquisitor"):
                token = "rank" if "rank" in tokens else tokens[0]
            else:
                token = next((t for t in tokens if t.startswith("marker-")), tokens[0])
            payload = {"token": token}
            if token.startswith("marker-") and actor_markers(actor)[int(token.split("-")[1])] == "wild":
                payload["color"] = "rose"
            do(actor, "choose-reveal", payload)
        elif kind == "skill":
            do(actor, "choose-skill", {"use": False})
        elif kind == "token-return":
            token = (pending.get("eligibleTokens") or ["marker-0"])[0]
            payload = {"token": token}
            if token.startswith("marker-") and actor_markers(actor)[int(token.split("-")[1])] == "wild":
                payload["color"] = "rose"
            do(actor, "choose-return", payload)
        else:
            raise AssertionError(f"未知窗口 {kind}")
        time.sleep(0.4)
    raise TimeoutError("窗口未在时限内清完")


def wound_once(target, attacker):
    """递匕首 → 攻击 → 清窗口；全程一次性连接。"""
    browser = load()["browserName"]
    state = resolve_windows()  # 先清掉上一轮可能遗留的窗口
    if state["game"]["status"] == "ended":
        return state
    holder = names_of(state)[state["game"]["daggerHolderId"]]
    assert holder != browser, "匕首在浏览器座位，请先在界面把匕首传出去再重跑"
    if holder != attacker:
        do(holder, "pass-dagger", {"targetPlayerId": pid_of(state, attacker)})
    state = read()
    do(attacker, "attack", {"targetPlayerId": pid_of(state, target)})
    return resolve_windows()


def cmd_endgame():
    info = load()
    victim = info.get("inquisitor")
    if not victim:
        for p in read()["game"]["players"]:
            if p["captured"] or p["displayName"] == info["browserName"]:
                continue
            client = Client(p["displayName"])
            faction = client.state["game"]["viewer"]["identity"]["faction"]
            client.close()
            if faction == "secret-order":
                victim = p["displayName"]
                break
        info["inquisitor"] = victim
        save(info)
    assert victim, "未找到审判者"
    attacker = next(n for n in (f"P{i}" for i in range(2, 8)) if n != victim)
    state = None
    for _ in range(12):
        state = read()
        if state["game"]["status"] == "ended":
            break
        state = wound_once(victim, attacker)
    print(json.dumps({"status": state["game"]["status"], "result": state["game"].get("result")}, ensure_ascii=False))
    assert state["game"]["status"] == "ended", "对局未结束"


def cmd_dagger():
    """让持匕首的机器人把匕首传出去（触发一次真实事件，验证浏览器侧反应）。"""
    state = read()
    holder = names_of(state)[state["game"]["daggerHolderId"]]
    assert holder != load()["browserName"], "匕首在浏览器座位"
    target = next(p["displayName"] for p in state["game"]["players"]
                  if p["playerId"] != state["game"]["daggerHolderId"] and not p["captured"])
    do(holder, "pass-dagger", {"targetPlayerId": pid_of(state, target)})
    print(json.dumps({"before": brief(state), "after": brief(read())}, ensure_ascii=False))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "setup":
        cmd_setup(*sys.argv[2:3])
    elif cmd == "start":
        cmd_start()
    elif cmd == "status":
        cmd_status()
    elif cmd == "dagger":
        cmd_dagger()
    elif cmd == "endgame":
        cmd_endgame()
    else:
        raise SystemExit(f"未知命令 {cmd}")


if __name__ == "__main__":
    main()
