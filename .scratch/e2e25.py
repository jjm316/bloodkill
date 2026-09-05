# -*- coding: utf-8 -*-
"""issue 25 UI 验收驱动：把真实对局推进到亮牌/归还窗口后停下，交给浏览器验收。

复用 e2e-curse.py 的连接骨架（importlib 加载，主流程有 __main__ 保护）。
与 e2e-curse 的区别：hit 在伤害结算后的第一个 reveal / token-return 窗口
停下不代答，留给浏览器里以当事玩家身份加入的会话做槽位点击验收。

子命令：
  open         建房 + P1..P7 入座 + 开局（干涉时限 30 秒），记录身份与匕首
  hit <name>   匕首交给一名存活非 <name> 玩家发起攻击、全员不干涉，
               停在 <name> 的 reveal / token-return 窗口（不代答）
  status       打印当前 pending 摘要
"""
import importlib.util
import json
import sys

# 注意：不要在此脚本里再包一层 sys.stdout（e2e-curse 导入时会包一层，
# 叠两层会因前一层被 GC 关闭底层缓冲而炸 I/O）。utf-8 包装由 e2e-curse 完成。
spec = importlib.util.spec_from_file_location("e2ecurse", ".scratch/e2e-curse.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def name_of_pid(client, pid):
    return next(p["displayName"] for p in client.state["game"]["players"] if p["playerId"] == pid)


def answer_poll_decline(snapshot):
    """把当前 poll 全员表态为不干涉（逐个短连接）。"""
    names = {p["playerId"]: p["displayName"] for p in snapshot.state["game"]["players"]}
    answered = set(snapshot.state["game"]["pending"].get("responses") or {})
    for pid in snapshot.state["game"]["pending"]["eligiblePlayerIds"]:
        if pid in answered:
            continue
        responder = base.Client(names[pid])
        responder.send("respond-intervention", {"volunteer": False})
        responder.close()


def cmd_open():
    base.cmd_setup()
    base.cmd_start(30)
    client = base.Client("P1")
    print(json.dumps({
        "holder": name_of_pid(client, client.state["game"]["daggerHolderId"]),
        "inquisitor": base.load()["inquisitor"],
    }, ensure_ascii=False))


def cmd_hit(target):
    client = base.Client("P1")
    target_id = base.player_id_of(client, target)
    holder = name_of_pid(client, client.state["game"]["daggerHolderId"])
    attacker = next(n for n in base.live_names(client) if n not in (target, holder))
    if holder != target:
        base.hand_dagger(client, attacker)
    else:
        # 目标本人持匕首：先让目标把匕首传给攻击者（目标无浏览器会话时才可用）
        passer = base.Client(target)
        passer.send("pass-dagger", {"targetPlayerId": base.player_id_of(passer, attacker)})
        passer.close()
    striker = base.Client(attacker)
    striker.send("attack", {"targetPlayerId": target_id})
    while True:
        cur = base.Client(attacker)
        pending = cur.state["game"]["pending"]
        if cur.state["game"]["status"] == "ended" or pending is None:
            print(json.dumps({"stopped": None}))
            return
        kind = pending["kind"]
        if kind == "intervention":
            if pending.get("stage") == "poll":
                answer_poll_decline(cur)
                continue
            raise AssertionError(f"干涉进入 choice 阶段，驱动未覆盖：{pending}")
        if kind in ("reveal", "token-return"):
            actor = name_of_pid(cur, pending["actorPlayerId"])
            print(json.dumps({
                "stopped": kind,
                "actor": actor,
                "eligibleTokens": pending.get("eligibleTokens"),
                "forceRank": pending.get("forceRank"),
                "damage": next(p["damage"] for p in cur.state["game"]["players"] if p["playerId"] == pending["actorPlayerId"]),
            }, ensure_ascii=False))
            return
        if kind == "skill":
            actor = name_of_pid(cur, pending["actorPlayerId"])
            decliner = base.Client(actor)
            decliner.send("choose-skill", {"use": False})
            decliner.close()
            continue
        raise AssertionError(f"未知窗口 {kind}")


def cmd_status(name=None):
    client = base.Client(name or "P1")
    game = client.state["game"]
    print(json.dumps({
        "status": game["status"],
        "holder": name_of_pid(client, game["daggerHolderId"]) if game["daggerHolderId"] else None,
        "pending": game["pending"],
        "legalActions": [a["type"] for a in game["legalActions"]],
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "open":
        cmd_open()
    elif command == "hit":
        cmd_hit(sys.argv[2])
    elif command == "status":
        cmd_status(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        raise SystemExit(f"unknown command {command}")
