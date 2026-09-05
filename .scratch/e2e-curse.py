# -*- coding: utf-8 -*-
"""诅咒技能 e2e：7 人局打出「亮等级 → 技能分发诅咒 → 真诅咒夺胜」全路径。

对真实 uvicorn 服务端分步执行（仿 e2e23.py 模式：每条子命令独立连接、
同名 hello 自动恢复座位、状态由服务端持有）。场景：

1. 建房加入 7 名玩家，房主开局；
2. 逐一连接读出各自身份（viewer.identity），定位审判者与两家族；
3. 把三名玫瑰玩家各打到 3 伤（亮出等级）→ 玫瑰领袖=最小等级者；
4. 攻击审判者一次并亮出等级 → 诅咒技能窗口开启；
5. 两步发动：choose-skill use=true 携 assignments（真诅咒→玫瑰领袖，
   假诅咒→任意他人）；
6. 野兽攻击者捕获等级最高的玫瑰玩家（非领袖捕获 → 玫瑰正常获胜）；
7. 终局断言：winner=secret-order、branch=inquisitor-true-curse。

全程所有非审判者连接与观众连接在读取线程内做泄露断言：
cursesToDistribute 恒空、legalActions 永无 distribute-curse、
广播事件永无 Curse* 类型。UI 两步发动（按钮→选择器→确认弹窗）由
浏览器人工验收覆盖，本脚本只驱动协议层。

运行（先起服务端）：python .scratch/e2e-curse.py <cmd>
一键全流程：python .scratch/e2e-curse.py drive
"""
import io
import json
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"
STATE_FILE = ".scratch/e2e-curse.json"


def load():
    with open(STATE_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def save(data):
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


class Leak(Exception):
    """非审判者视角看到了诅咒秘密。"""


class Client:
    """一条玩家/观众连接；非审判者连接自带泄露断言。"""

    def __init__(self, name, token=None, *, watch_secret=False):
        from websockets.sync.client import connect

        info = load()
        self.ws = connect(f"{WS}/ws/{info['code']}", open_timeout=10)
        hello = {"type": "hello", "name": name, "protocolVersion": "2"}
        if token:
            hello["token"] = token
        self.ws.send(json.dumps(hello))
        self.name = name
        # 审判者确定后，所有非审判者玩家连接自动开启泄露断言
        self.watch_secret = watch_secret or (
            bool(name) and bool(info.get("inquisitor")) and name != info["inquisitor"]
        )
        self.events = []
        self.state = None
        self.leak_error = None
        self._reader = None
        self._drain()

    def _raise_if_leak(self):
        if self.leak_error is not None:
            raise self.leak_error

    def _check_leak(self, message):
        game = message.get("game") or {}
        viewer = game.get("viewer")
        if viewer is not None and viewer.get("cursesToDistribute"):
            raise Leak(f"{self.name} 看到 cursesToDistribute={viewer['cursesToDistribute']}")
        for action in game.get("legalActions") or []:
            if action.get("type") == "distribute-curse":
                raise Leak(f"{self.name} 看到 distribute-curse 动作")
        for event in message.get("events") or []:
            if str(event.get("eventType", "")).startswith("Curse"):
                raise Leak(f"{self.name} 收到私密事件 {event.get('eventType')}")
        for event in self.events:
            if str(event.get("eventType", "")).startswith("Curse"):
                raise Leak(f"{self.name} 曾收到私密事件 {event.get('eventType')}")

    def _drain(self):
        import threading

        def reader():
            try:
                for raw in self.ws:
                    message = json.loads(raw)
                    kind = message.get("type")
                    if kind == "state":
                        self.state = message
                        if self.watch_secret:
                            self._check_leak(message)
                    elif kind == "event":
                        self.events.extend(message.get("events") or [])
                        if self.watch_secret:
                            self._check_leak(message)
            except Leak as leak:
                self.leak_error = leak
            except Exception:
                pass

        self._reader = threading.Thread(target=reader, daemon=True)
        self._reader.start()
        deadline = time.time() + 5
        while self.state is None and time.time() < deadline:
            time.sleep(0.05)
        if self.watch_secret and self.state is not None:
            self._check_leak(self.state)
        self._raise_if_leak()

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
                self._raise_if_leak()
                return state
            time.sleep(0.05)
        self._raise_if_leak()
        raise TimeoutError(f"{self.name}: {command} 后 revision 未推进（当前 {before}）")

    def send_host(self, action, payload=None):
        self.ws.send(json.dumps({"type": "host", "action": action, **(payload or {})}))
        deadline = time.time() + 6
        while time.time() < 6 + time.time():
            if self.state and self.state["roomStatus"] == "playing":
                return self.state
            time.sleep(0.05)
        return self.state

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def player_id_of(client, name):
    return next(p["playerId"] for p in client.state["game"]["players"] if p["displayName"] == name)


def holder_of(client):
    return client.state["game"]["daggerHolderId"]


def name_of(client, pid):
    return next(p["displayName"] for p in client.state["game"]["players"] if p["playerId"] == pid)


def live_names(client):
    return [p["displayName"] for p in client.state["game"]["players"] if not p["captured"]]


def hand_dagger(client, name):
    """把匕首传给 name（若是本人则不动）。"""
    if holder_of(client) == player_id_of(client, name):
        return
    actor = name_of(client, holder_of(client))
    holder = Client(actor)
    holder.send("pass-dagger", {"targetPlayerId": player_id_of(holder, name)})
    holder.close()


def answer_poll(client):
    """把当前投票表态完：全员不干涉。"""
    pending = client.state["game"]["pending"]
    assert pending and pending["kind"] == "intervention" and pending.get("stage") == "poll"
    names = {p["playerId"]: p["displayName"] for p in client.state["game"]["players"]}
    answered = set(pending.get("responses") or {})
    for pid in pending["eligiblePlayerIds"]:
        if pid in answered:
            continue
        responder = Client(names[pid])
        responder.send("respond-intervention", {"volunteer": False})
        responder.close()
    return Client(client.name)


def resolve_reveal(client):
    """当前 reveal 窗口：审判者亮等级（开诅咒窗），其他人优先亮身份标记。"""
    pending = client.state["game"]["pending"]
    actor = next(p["displayName"] for p in client.state["game"]["players"] if p["playerId"] == pending["actorPlayerId"])
    is_inquisitor = actor == load()["inquisitor"]
    revealer = Client(actor)
    tokens = sorted(pending.get("eligibleTokens") or [])
    if is_inquisitor:
        token = "rank" if "rank" in tokens else tokens[0]
    else:
        markers = [t for t in tokens if t.startswith("marker-")]
        token = markers[0] if markers else tokens[0]
    revealer.send("choose-reveal", {"token": token})
    return revealer


def advance(client, *, stop_at_curse_window=True):
    """把所有可代答的窗口处理完；审判者诅咒窗口按需停下。"""
    while True:
        client = Client(client.name)
        pending = client.state["game"]["pending"]
        if client.state["game"]["status"] == "ended" or pending is None:
            return client
        kind = pending["kind"]
        actor = next(p["displayName"] for p in client.state["game"]["players"] if p["playerId"] == pending["actorPlayerId"])
        if kind == "intervention":
            client = answer_poll(client)
        elif kind == "reveal":
            client = resolve_reveal(client)
        elif kind == "skill":
            if pending.get("rank") == "fleur-cross":
                if stop_at_curse_window:
                    return client
                raise AssertionError("遇到诅咒窗口但场景未安排分发")
            decliner = Client(actor)
            decliner.send("choose-skill", {"use": False})
            client = decliner
        elif kind == "token-return":
            returner = Client(actor)
            returner.send("choose-return", {"token": (pending.get("eligibleTokens") or ["marker-0"])[0]})
            client = returner
        else:
            raise AssertionError(f"未知窗口 {kind}")


def wound(client, target, attacker=None):
    """一次攻击循环：递匕首 → 攻击 → 投票/亮牌/技能窗口全部推进。"""
    target_id = player_id_of(client, target)
    attacker = attacker or next(name for name in live_names(client) if name not in (target, load()["inquisitor"]))
    hand_dagger(client, attacker)
    striker = Client(attacker)
    striker.send("attack", {"targetPlayerId": target_id})
    return advance(striker)


def cmd_setup():
    request = urllib.request.Request(f"{BASE}/api/rooms", method="POST")
    with urllib.request.urlopen(request) as response:
        room = json.load(response)
    save({"code": room["code"], "hostToken": room["hostToken"], "gameId": room["gameId"]})
    print(f"room {room['code']}")
    for index in range(1, 8):
        client = Client(f"P{index}")
        client.close()
    print("joined P1..P7")


def cmd_start(seconds=30):
    info = load()
    client = Client("P1", info["hostToken"])
    state = client.send_host("start", {"interventionTimeoutSeconds": seconds})
    assert state["roomStatus"] == "playing", state["roomStatus"]
    # 逐一连接读身份：定位审判者与两家族（每人可见自己的 identity）
    factions, inquisitor = {}, None
    for index in range(1, 8):
        name = f"P{index}"
        probe = Client(name)
        identity = probe.state["game"]["viewer"]["identity"]
        factions[name] = identity["faction"]
        if identity["faction"] == "secret-order":
            inquisitor = name
        probe.close()
    info["factions"] = factions
    info["inquisitor"] = inquisitor
    info["rose"] = sorted(n for n, f in factions.items() if f == "rose")
    info["beast"] = sorted(n for n, f in factions.items() if f == "beast")
    save(info)
    print(json.dumps({"inquisitor": inquisitor, "rose": info["rose"], "beast": info["beast"]}, ensure_ascii=False))


def cmd_wound(target, attacker=None):
    client = Client(load()["inquisitor"])  # 任意已入座名字，只为读公共状态
    client = wound(client, target, attacker)
    print(json.dumps(brief(client), ensure_ascii=False))


def cmd_status(name=None):
    client = Client(name or "P1")
    print(json.dumps(brief(client), ensure_ascii=False, indent=1))


def distribute(curse_true_name, curse_false_name):
    """两步发动的第二步：choose-skill use=true 携带 assignments。"""
    info = load()
    inquisitor = info["inquisitor"]
    client = Client(inquisitor)
    pending = client.state["game"]["pending"]
    assert pending and pending["kind"] == "skill" and pending.get("rank") == "fleur-cross", brief(client)
    curses = client.state["game"]["viewer"]["cursesToDistribute"]
    true_id = next(c for c in curses if c.startswith("true-curse"))
    false_id = next(c for c in curses if c.startswith("false-curse"))
    assignments = {
        true_id: player_id_of(client, curse_true_name),
        false_id: player_id_of(client, curse_false_name),
    }
    state = client.send("choose-skill", {"use": True, "assignments": assignments})
    print(json.dumps({"assignments": assignments, "after": brief(client)}, ensure_ascii=False))
    return client


def cmd_distribute(curse_true_name, curse_false_name):
    distribute(curse_true_name, curse_false_name)


def cmd_decline():
    """放弃技能：窗口永久关闭，诅咒留供应区。"""
    info = load()
    client = Client(info["inquisitor"])
    state = client.send("choose-skill", {"use": False})
    assert state["game"]["viewer"]["cursesToDistribute"] == ["true-curse-1", "false-curse-1"]
    print(json.dumps(brief(client), ensure_ascii=False))


def cmd_run(scenario="win"):
    """整场自动驱动到终局。scenario=win：真诅咒夺胜；decline：放弃后家族照常胜。"""
    info = load()
    rose, beast, inquisitor = info["rose"], info["beast"], info["inquisitor"]

    def ranks_of(name):
        probe = Client("P1")
        view = next(p for p in probe.state["game"]["players"] if p["displayName"] == name)
        probe.close()
        return (view["revealed"] or {}).get("rank")

    client = Client("P1")
    if scenario == "decline":
        # 审判者挨一刀开窗并放弃，诅咒永留供应区；此后家族照常结算
        client = wound(client, inquisitor, beast[0])
        client = Client(inquisitor)
        assert client.state["game"]["pending"]["rank"] == "fleur-cross", brief(client)
        client.send("choose-skill", {"use": False})
        client.close()
        client = Client("P1")
        victim = rose[0]
        for _ in range(4):
            if client.state["game"]["status"] == "ended":
                break
            client = wound(client, victim, beast[0])
        client = Client("P1")
        result = client.state["game"]["result"]
        print(json.dumps({"result": result}, ensure_ascii=False))
        assert result["winner"] in ("rose", "beast"), result
        assert result["branch"] in ("captured-leader", "captured-player"), result
        print("E2E OK：放弃后家族照常获胜，无诅咒判定")
        return

    # 1) 三名玫瑰玩家各 3 伤：等级全部亮出
    for name in rose:
        for _ in range(3):
            client = Client("P1")
            if client.state["game"]["status"] == "ended":
                break
            client = wound(client, name, beast[0])
    client = Client("P1")
    ranks = {name: ranks_of(name) for name in rose}
    leader = min(rose, key=lambda n: ranks[n])
    highest = max(rose, key=lambda n: ranks[n])
    print(json.dumps({"rose ranks": ranks, "leader": leader, "highest": highest}, ensure_ascii=False))
    # 2) 审判者挨一刀亮等级 → 诅咒窗口
    client = wound(client, inquisitor, beast[0])
    client = Client(inquisitor)
    assert client.state["game"]["pending"]["rank"] == "fleur-cross", brief(client)
    # 3) 两步发动：真诅咒→玫瑰领袖，假诅咒→任意其他存活玩家
    false_recipient = next(n for n in live_names(client) if n not in (inquisitor, leader))
    distribute(leader, false_recipient)
    # 4) 野兽捕获等级最高的玫瑰玩家（非领袖捕获 → 玫瑰胜 → 被真诅咒改写）
    client = Client("P1")
    client = wound(client, highest, beast[0])
    client = Client("P1")
    result = client.state["game"]["result"]
    print(json.dumps({"result": result}, ensure_ascii=False))
    assert result["winner"] == "secret-order", result
    assert result["branch"] == "inquisitor-true-curse", result
    # 5) 观众视角终局泄露断言（构造一条观众连接读取终局状态）
    spectator = Client("")
    assert spectator.state["game"]["viewer"] is None
    spectator._check_leak(spectator.state)
    spectator.close()
    print("E2E OK：真诅咒夺胜，非审判者/观众视角无泄露")


def brief(client):
    game = client.state["game"]
    return {
        "revision": game["revision"],
        "status": game["status"],
        "phase": game["phase"],
        "dagger": name_of(client, game["daggerHolderId"]) if game["daggerHolderId"] else None,
        "pending": {k: game["pending"][k] for k in ("kind", "rank") if game["pending"] and k in game["pending"]} if game["pending"] else None,
        "legalActions": [a["type"] for a in game["legalActions"]],
        "result": game["result"],
    }


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "setup":
        cmd_setup()
    elif command == "start":
        cmd_start(int(sys.argv[2]) if len(sys.argv) > 2 else 30)
    elif command == "wound":
        cmd_wound(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif command == "distribute":
        cmd_distribute(sys.argv[2], sys.argv[3])
    elif command == "decline":
        cmd_decline()
    elif command == "status":
        cmd_status(sys.argv[2] if len(sys.argv) > 2 else None)
    elif command == "run":
        cmd_run(sys.argv[2] if len(sys.argv) > 2 else "win")
    else:
        raise SystemExit(f"unknown command {command}")
