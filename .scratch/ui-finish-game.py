# -*- coding: utf-8 -*-
"""把 706432 打到终局：反复攻击阿飞直到其被捕获。"""
import io
import json
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from websockets.sync.client import connect

CODE = "706432"


def client(name):
    ws = connect(f"ws://127.0.0.1:8000/ws/{CODE}", open_timeout=10, legacy=True)
    ws.send(json.dumps({"type": "hello", "name": name, "protocolVersion": "2"}))
    st = None
    deadline = time.time() + 8
    while st is None and time.time() < deadline:
        try:
            m = json.loads(ws.recv(timeout=1))
            if m.get("type") == "state":
                st = m
        except Exception:
            pass
    return ws, st


def pid(st, name):
    return next((p["playerId"] for p in st["game"]["players"] if p["displayName"] == name), None)


def send(ws, st, cmd, payload):
    before = st["game"]["revision"]
    ws.send(json.dumps({"type": "command", "commandId": f"{cmd}-{time.time_ns()}", "command": cmd, "payload": payload, "expectedRevision": before}))
    deadline = time.time() + 6
    while time.time() < deadline:
        try:
            m = json.loads(ws.recv(timeout=1))
            if m.get("type") == "state" and m["game"]["revision"] != before:
                return m
        except Exception:
            pass
    raise TimeoutError(cmd)


def poll_decline(st):
    p = st["game"]["pending"]
    answered = set((p.get("responses") or {}).keys())
    names = {q["playerId"]: q["displayName"] for q in st["game"]["players"]}
    for who in p["eligiblePlayerIds"]:
        if who in answered:
            continue
        w, s = client(names[who])
        send(w, s, "respond-intervention", {"volunteer": False})
        w.close()
    return client("大猫")


def main():
    _, st = client("大猫")
    TARGET = "阿紫"
    for _ in range(60):
        try:
            g = st["game"]
            if g["status"] == "ended":
                break
            p = g["pending"]
            if p is None:
                holder = next(q["displayName"] for q in g["players"] if q["playerId"] == g["daggerHolderId"])
                w, s = client(holder)
                if s["game"]["status"] == "ended":
                    st = s
                    w.close()
                    break
                if s["game"]["pending"] is not None:
                    st = s
                    w.close()
                    continue
                st = send(w, s, "attack", {"targetPlayerId": pid(s, TARGET)})
                w.close()
            elif p["kind"] == "intervention":
                _, st = poll_decline(st)
            elif p["kind"] == "reveal":
                actor = next(q["displayName"] for q in st["game"]["players"] if q["playerId"] == p["actorPlayerId"])
                w, s = client(actor)
                pp = s["game"]["pending"]
                toks = [t for t in (pp.get("eligibleTokens") or []) if t.startswith("marker-")] or (pp.get("eligibleTokens") or ["rank"])
                st = send(w, s, "choose-reveal", {"token": toks[0]})
                w.close()
            elif p["kind"] == "skill":
                actor = next(q["displayName"] for q in st["game"]["players"] if q["playerId"] == p["actorPlayerId"])
                w, s = client(actor)
                st = send(w, s, "choose-skill", {"use": False})
                w.close()
            elif p["kind"] == "token-return":
                actor = next(q["displayName"] for q in st["game"]["players"] if q["playerId"] == p["actorPlayerId"])
                w, s = client(actor)
                toks = st["game"]["pending"].get("eligibleTokens") or []
                st = send(w, s, "choose-return", {"token": toks[0]})
                w.close()
            else:
                raise AssertionError(p["kind"])
        except (TimeoutError, KeyError, StopIteration):
            _, st = client("大猫")
    g = st["game"]
    print("status:", g["status"], "| winner:", (g["result"] or {}).get("winner"), "| explanation:", (g["result"] or {}).get("explanationKey"))


if __name__ == "__main__":
    main()
