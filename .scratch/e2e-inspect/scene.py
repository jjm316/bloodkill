# -*- coding: utf-8 -*-
"""小丑检视（等级3技能）e2e 布景：摆出「阿丑的技能窗口已开启」状态。

对真实 uvicorn 服务端（协议 v3）执行，仿 ui-true-color/scene.py 的
刷房重试与 e2e-curse.py 的攻击编排（gate 由目标答 need=false 跳过投票）：

  open   建房 + 7 人入座 + 开局（干涉/单人窗口时限 180 秒），按重试刷房
         直到浏览器座位（阿丑）的 rank == 3；
  wound  把阿丑打到 3 伤（第 1/2 点亮身份标记、第 3 点被迫亮等级）→
         等级3技能窗口开启后停下（不代答，交给浏览器驱动）；
         顺带记录两名检视目标（审判者 + 一名普通玩家）的真实 faction/rank
         （各自由其本人连接读出，隐私边界不破），写 state.json 供驱动断言。

运行（先起服务端）：python .scratch/e2e-inspect/scene.py <open|wound>
"""
import io
import json
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"
STATE_FILE = ".scratch/e2e-inspect/state.json"
PROTOCOL = "3"

NAMES = ["阿玫", "小兽", "老K", "阿丑", "大猫", "阿飞", "咪咪"]  # 7 人局：1 名审判者
BROWSER = "阿丑"  # 浏览器接管的座位：必须是 rank 3（小丑）
MAX_TRIES = 40


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
        self.ws = connect(f"{WS}/ws/{info['code']}", open_timeout=10)
        hello = {"type": "hello", "name": name, "protocolVersion": PROTOCOL}
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
            state = self.state
            if state is not None and state["game"]["revision"] != before:
                return state
            time.sleep(0.05)
        raise TimeoutError(f"{self.name}: {command} 后 revision 未推进")

    def send_host(self, action, payload=None):
        self.ws.send(json.dumps({"type": "host", "action": action, **(payload or {})}))
        deadline = time.time() + 8
        while time.time() < deadline:
            if self.state and self.state["roomStatus"] == "playing":
                return self.state
            time.sleep(0.05)
        return self.state

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def pid_of(client, name):
    return next(p["playerId"] for p in client.state["game"]["players"] if p["displayName"] == name)


def holder_name(client):
    return next(p["displayName"] for p in client.state["game"]["players"] if p["playerId"] == client.state["game"]["daggerHolderId"])


def hand_dagger(name):
    observer = Client("咪咪")
    try:
        if holder_name(observer) == name:
            return
        holder = Client(holder_name(observer))
        holder.send("pass-dagger", {"targetPlayerId": pid_of(holder, name)})
        holder.close()
    finally:
        observer.close()


def advance():
    """把所有可代答窗口推进；阿丑的等级3技能窗口停下（留给浏览器）。"""
    for _ in range(30):
        client = Client("咪咪")  # 任意非阿丑座位，只读公共状态
        try:
            pending = client.state["game"]["pending"]
            if client.state["game"]["status"] == "ended" or pending is None:
                return
            actor = next(p["displayName"] for p in client.state["game"]["players"] if p["playerId"] == pending["actorPlayerId"])
            kind = pending["kind"]
            if kind == "intervention" and pending.get("stage") == "gate":
                target = Client(actor)  # actor = 被攻击者，答不需要 → 直接结算
                target.send("answer-intervention-request", {"need": False})
                target.close()
            elif kind == "intervention":
                raise AssertionError(f"意外的投票阶段：{pending}")
            elif kind == "reveal":
                revealer = Client(actor)
                tokens = sorted(pending.get("eligibleTokens") or [])
                markers = [t for t in tokens if t.startswith("marker-")]
                revealer.send("choose-reveal", {"token": markers[0] if markers else tokens[0]})
                revealer.close()
            elif kind == "skill":
                if actor == BROWSER and pending.get("rank") == 3:
                    return  # 目标状态：阿丑的等级3技能窗已开
                decliner = Client(actor)
                decliner.send("choose-skill", {"use": False})
                decliner.close()
            else:
                raise AssertionError(f"未知窗口 {kind}/{pending}")
        finally:
            client.close()


def wound(target):
    hand_dagger("老K")
    attacker = Client("老K")
    attacker.send("attack", {"targetPlayerId": pid_of(attacker, target)})
    attacker.close()
    advance()


def read_identity(name):
    probe = Client(name)
    try:
        return probe.state["game"]["viewer"]["identity"]
    finally:
        probe.close()


def cmd_open():
    for attempt in range(1, MAX_TRIES + 1):
        request = urllib.request.Request(f"{BASE}/api/rooms", method="POST")
        with urllib.request.urlopen(request) as response:
            room = json.load(response)
        save({"code": room["code"], "hostToken": room["hostToken"], "gameId": room["gameId"]})
        for name in NAMES:
            Client(name).close()
        host = Client(NAMES[0], load()["hostToken"])
        state = host.send_host("start", {"interventionTimeoutSeconds": 180, "singleWindowTimeoutSeconds": 180})
        if state["roomStatus"] != "playing":
            raise AssertionError(state["roomStatus"])
        identity = read_identity(BROWSER)
        if identity["rank"] == 3:
            info = load()
            info["browserIdentity"] = identity
            save(info)
            print(f"第 {attempt} 次刷房命中：阿丑 rank=3（{identity['faction']}）房间 {info['code']}")
            return
        print(f"第 {attempt} 次刷房阿丑 rank={identity['rank']}，重试")
    raise AssertionError(f"{MAX_TRIES} 次未刷到 rank 3")


def cmd_wound():
    for _ in range(3):
        wound(BROWSER)
    observer = Client("咪咪")
    try:
        pending = observer.state["game"]["pending"]
        browser = next(p for p in observer.state["game"]["players"] if p["displayName"] == BROWSER)
        assert pending and pending["kind"] == "skill" and pending.get("rank") == 3 and pending["actorPlayerId"] == browser["playerId"], pending
        assert browser["damage"] == 3, browser
    finally:
        observer.close()

    # 两名检视目标：审判者（紫「审」徽）+ 一名普通玩家（阵营色数字徽）
    info = load()
    identities = {}
    inquisitor = None
    for name in NAMES:
        identities[name] = read_identity(name)
        if identities[name]["faction"] == "secret-order":
            inquisitor = name
    assert inquisitor is not None and inquisitor != BROWSER, "7 人局必有审判者且不是阿丑"
    ordinary = next(n for n in NAMES if n not in (BROWSER, inquisitor))
    observer = Client("咪咪")
    try:
        pid = {p["displayName"]: p["playerId"] for p in observer.state["game"]["players"]}
    finally:
        observer.close()
    info["targets"] = [
                {"name": inquisitor, "playerId": pid[inquisitor], **identities[inquisitor]},
                {"name": ordinary, "playerId": pid[ordinary], **identities[ordinary]},
    ]
    save(info)
    print(json.dumps(info["targets"], ensure_ascii=False))
    print(f"技能窗口已开（房间 {info['code']}），180 秒内完成浏览器驱动")


if __name__ == "__main__":
    {"open": cmd_open, "wound": cmd_wound}[sys.argv[1]]()
