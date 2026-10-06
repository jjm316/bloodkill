# -*- coding: utf-8 -*-
"""ui-true-color 视觉验收布景。

为三种真实阵营各刷一间 7 人局，浏览器座位（阿紫）的身份 faction 命中目标才算成功：
  rose / beast   —— 玫红 / 兽蓝色徽
  order          —— 审判者（secret-order，灰色徽，拍板 Q3c）

发牌随机，按重试刷房；命中的房间号写 state.json，浏览器用 ?room=&name=阿紫 同名接管。

运行：python .scratch/ui-true-color/scene.py
"""
import io
import json
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"

NAMES = ["阿玫", "小兽", "老K", "阿紫", "大猫", "阿飞", "咪咪"]  # 7 人局：必含 1 名审判者
BROWSER = "阿紫"
TARGETS = ["rose", "beast", "secret-order"]
MAX_TRIES_PER_TARGET = 30
STATE_FILE = ".scratch/ui-true-color/state.json"


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

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def browser_faction():
    """以阿紫同名接入，读 viewer.identity.faction（其他玩家的投影不含身份）。"""
    c = Client(BROWSER)
    faction = c.state["game"]["viewer"]["identity"]["faction"]
    c.close()
    return faction


def make_room(target):
    """开一局 7 人局，浏览器座位 faction 命中 target 则返回房间号，否则 None。"""
    global CODE
    room = http_json("/api/rooms", method="POST")
    CODE = room["code"]
    host = Client(NAMES[0], room["hostToken"])
    for name in NAMES[1:]:
        Client(name).close()
    host.ws.send(json.dumps({"type": "host", "action": "start", "interventionTimeoutSeconds": 180}))
    deadline = time.time() + 8
    ok = False
    while time.time() < deadline:
        if host.state and host.state["roomStatus"] == "playing":
            ok = True
            break
        time.sleep(0.05)
    host.close()
    if not ok:
        return None
    return browser_faction() == target


def main():
    result = {}
    for target in TARGETS:
        for attempt in range(1, MAX_TRIES_PER_TARGET + 1):
            hit = None
            try:
                if make_room(target):
                    hit = CODE
            except Exception as exc:  # 单次失败换房重试
                print(f"  [{target}] 第 {attempt} 次异常：{exc}")
                time.sleep(0.3)
                continue
            if hit:
                print(f"[{target}] 命中：房间 {hit}（第 {attempt} 次发牌）")
                result[target] = {"code": hit, "browser": BROWSER}
                break
        if target not in result:
            raise SystemExit(f"[{target}] {MAX_TRIES_PER_TARGET} 次未刷出，中止")
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print("布景完成 →", STATE_FILE)
    for target, info in result.items():
        print(f"  {target}: http://127.0.0.1:8000/?room={info['code']}&name={info['browser']}")


if __name__ == "__main__":
    main()
