# -*- coding: utf-8 -*-
"""事件日志验收补丁：让持有授予类技能（等级 1/6/8/9）的玩家被攻击后亮等级并使用技能，
产生 ResourceGranted（羽毛笔即得即耗 / 盾剑 / 法杖 / 扇），补齐"资源"类事件。

注意：受伤后亮牌、开技能窗口的都是被攻击者，不是攻击方。

前置：e2e-curse.py setup + start 已跑完（存档里能查到暗置等级）。
"""
import gzip
import importlib.util
import json

spec = importlib.util.spec_from_file_location("e2ecurse", ".scratch/e2e-curse.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

GRANT_RANKS = (1, 6, 8, 9)


def save_players():
    gid = base.load()["gameId"]
    data = json.load(gzip.open(f"saves/{gid}.json.gz", "rt", encoding="utf-8"))
    return data["snapshot"]["players"]


def main():
    players = save_players()
    victim = next(p for p in players.values() if p["rank"] in GRANT_RANKS)
    victim_name, rank = victim["displayName"], victim["rank"]
    print("grant-rank victim:", victim_name, rank)

    client = base.Client("P1")
    attacker = next(n for n in base.live_names(client) if n not in (victim_name, base.load()["inquisitor"]))
    base.hand_dagger(client, attacker)
    striker = base.Client(attacker)
    striker.send("attack", {"targetPlayerId": base.player_id_of(striker, victim_name)})

    # 全员不干涉 → 攻击结算 → 被攻击者亮牌窗口
    pending = base.Client(victim_name).state["game"]["pending"]
    assert pending["kind"] == "intervention", pending["kind"]
    base.answer_poll(base.Client(attacker))

    # 被攻击者亮"等级"token（亮标记不会开技能窗口）
    probe = base.Client(victim_name)
    pending = probe.state["game"]["pending"]
    assert pending["kind"] == "reveal" and pending["actorPlayerId"] == victim["playerId"], pending
    base.Client(victim_name).send("choose-reveal", {"token": "rank"})

    # 技能窗口（属被攻击者）→ 使用技能 → 资源授予
    pending = base.Client(victim_name).state["game"]["pending"]
    assert pending["kind"] == "skill" and pending.get("rank") == rank, pending
    payload = {"use": True}
    if rank != 1:
        skill_target = next(n for n in base.live_names(probe) if n not in (victim_name, base.load()["inquisitor"]))
        payload["targetPlayerId"] = base.player_id_of(probe, skill_target)
    state = base.Client(victim_name).send("choose-skill", payload)
    print("done, revision", state["revision"])


if __name__ == "__main__":
    main()
