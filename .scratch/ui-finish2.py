# -*- coding: utf-8 -*-
import io, sys, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".scratch")
from websockets.sync.client import connect
CODE = "706432"
def client(name):
    ws = connect(f"ws://127.0.0.1:8000/ws/{CODE}", open_timeout=10, legacy=True)
    ws.send(json.dumps({"type": "hello", "name": name, "protocolVersion": "2"}))
    st = None; deadline = time.time() + 8
    while st is None and time.time() < deadline:
        try:
            m = json.loads(ws.recv(timeout=1))
            if m.get("type") == "state": st = m
        except Exception: pass
    return ws, st
def pid(st, name):
    return next(p["playerId"] for p in st["game"]["players"] if p["displayName"] == name)
def send(ws, st, cmd, payload):
    before = st["game"]["revision"]
    ws.send(json.dumps({"type": "command", "commandId": f"{cmd}-{time.time_ns()}", "command": cmd, "payload": payload, "expectedRevision": before}))
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            m = json.loads(ws.recv(timeout=1))
            if m.get("type") == "state" and m["game"]["revision"] != before: return m
        except Exception: pass
    raise TimeoutError(cmd)
def attack_round(attacker, target):
    w, s = client(attacker)
    s2 = send(w, s, "attack", {"targetPlayerId": pid(s, target)})
    for _ in range(8):
        p = s2["game"]["pending"]
        if s2["game"]["status"] == "ended" or p is None: break
        if p["kind"] == "intervention":
            answered = set((p.get("responses") or {}).keys())
            names = {q["playerId"]: q["displayName"] for q in s2["game"]["players"]}
            for who in p["eligiblePlayerIds"]:
                if who in answered: continue
                w2, s3 = client(names[who]); s2 = send(w2, s3, "respond-intervention", {"volunteer": False}); w2.close()
        elif p["kind"] == "reveal":
            actor = next(q["displayName"] for q in s2["game"]["players"] if q["playerId"] == p["actorPlayerId"])
            w3, s4 = client(actor)
            pp = s4["game"]["pending"]
            toks = [t for t in (pp.get("eligibleTokens") or []) if t.startswith("marker-")] or (pp.get("eligibleTokens") or ["rank"])
            s2 = send(w3, s4, "choose-reveal", {"token": toks[0]}); w3.close()
        elif p["kind"] in ("skill", "token-return"):
            actor = next(q["displayName"] for q in s2["game"]["players"] if q["playerId"] == p["actorPlayerId"])
            w4, s5 = client(actor)
            if p["kind"] == "skill": s2 = send(w4, s5, "choose-skill", {"use": False})
            else:
                toks = p.get("eligibleTokens") or []
                s2 = send(w4, s5, "choose-return", {"token": toks[0]})
            w4.close()
        else: break
    w.close()
    return s2
s = attack_round("阿紫", "阿玫")
print("r1:", s["game"]["status"], (s["game"]["pending"] or {}).get("kind"))
holder = next(q["displayName"] for q in s["game"]["players"] if q["playerId"] == s["game"]["daggerHolderId"]) if s["game"]["status"] != "ended" else "-"
print("holder:", holder)
if s["game"]["status"] != "ended":
    s = attack_round(holder, "阿紫")
print("status:", s["game"]["status"])
g = s["game"]
print("result:", json.dumps(g["result"], ensure_ascii=False)[:300] if g["result"] else None)
for q in g["players"]: print(q["displayName"], q["damage"], q["captured"])
