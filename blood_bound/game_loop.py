"""Deterministic, headless game-loop helpers used by fixtures and smoke tests."""

from __future__ import annotations

from dataclasses import dataclass

from .engine import Command, Event, RulesEngine


@dataclass(frozen=True)
class Replay:
    game_id: str
    seed: str
    command_ids: tuple[str, ...]
    event_types: tuple[str, ...]
    final_revision: int
    result: dict


def run_deterministic_game(player_count: int, *, game_id: str = "golden", seed: str = "golden-seed") -> tuple[RulesEngine, Replay]:
    """Run a complete no-UI game by repeatedly feeding legal commands.

    The runner uses ordinary public commands only. Beyond the historical
    skeleton (pass the dagger to a fixed attacker, attack one victim, everyone
    declines to volunteer, decline skills — except the inquisitor, whose
    reveal-triggered curse window distributes the curses deterministically,
    ADR 0003) it deliberately crosses the rule-coupling batch's new branches
    so the golden replays cover them (issue 07):

    - the first intervention poll volunteers the first eligible rank-5 player,
      whose forced rank reveal opens the mentalist's skill window (trigger
      "intervention"); the mentalist then uses the skill once — the victim's
      rank is force-revealed and sealed into ``skills_used`` (ADR 0009 plan A);
    - rank-2 and rank-5 windows are used once each on the first fresh
      (zero-damage, non-owner, non-victim) player, so the assassin's two
      wounds run through the victim-choice reveal windows (ADR 0006);
    - the run's first reveal window and first declined skill window resolve
      through the scheduler's timeout commands (ADR 0011 determinism);
    - wild markers are revealed as the question mark (issue 26).

    It exists for golden replay and CI smoke coverage, not as an AI strategy.
    """
    engine = RulesEngine.new_game(game_id, seed, clock=lambda: 0.0)
    commands: list[str] = []
    events: list[Event] = []

    def send(command_id: str, actor: str | None, command_type: str, **payload) -> None:
        command = Command(command_id, game_id, actor, engine.state.revision, command_type, payload)
        commands.append(command_id)
        events.extend(engine.apply(command))

    for index in range(player_count):
        send(f"join-{index}", None, "join-game", playerId=f"p{index}", displayName=f"P{index}")
    send("start", None, "start-game")

    attacker = engine.state.dagger_holder_id
    assert attacker is not None
    inquisitor = next(
        (player.player_id for player in engine.state.players.values() if player.faction == "secret-order"),
        None,
    )
    # Odd games attack the inquisitor so the replay exercises the curse path
    # (wound -> fleur-cross reveal -> distribute -> capture); even games keep
    # the historical first-other-seat victim.
    victim = inquisitor or next(player_id for player_id in engine.state.players if player_id != attacker)

    used_skill_ranks: set[int] = set()
    seen_timeout_reveal = False
    seen_timeout_skill = False
    volunteer_pid: str | None = None
    volunteer_planned = False

    def fresh_target(owner_id: str) -> str:
        """First live zero-damage player that is neither the window owner nor the fixed victim."""
        return next(
            player_id
            for player_id in sorted(engine.state.players)
            if player_id not in (owner_id, victim) and not engine.state.players[player_id].captured and engine.state.players[player_id].damage == 0
        )

    turn = 0
    while engine.state.status != "ended":
        turn += 1
        if turn > 100:
            raise RuntimeError("deterministic runner exceeded turn budget")
        holder = engine.state.dagger_holder_id
        if holder != attacker:
            send(f"pass-{turn}", holder, "pass-dagger", targetPlayerId=attacker)
        send(f"attack-{turn}", attacker, "attack", targetPlayerId=victim)
        # Resolve every window the attack opened, including windows opened by
        # the skills used below (the assassin's wounds defer the dagger
        # hand-off until their victim-choice reveal windows close, B12).
        steps = 0
        while engine.state.pending:
            steps += 1
            if steps > 50:
                raise RuntimeError("deterministic runner exceeded window budget")
            pending = engine.state.pending
            if pending.kind == "intervention":
                stage = pending.context.get("stage")
                if stage == "gate":
                    # ADR 0012 request gate: the walker always asks for the
                    # poll, so the fixtures keep their volunteer-branch
                    # coverage; the gate decline path mixes in when ticket 05
                    # regenerates the goldens.
                    send(
                        f"gate-yes-{engine.state.revision}",
                        pending.actor_player_id,
                        "answer-intervention-request",
                        need=True,
                    )
                elif stage == "poll":
                    responses: dict[str, bool] = pending.context["responses"]
                    # The volunteering plan is made once, when the game's first
                    # poll opens, and survives across the per-responder
                    # iterations until the poll closes.
                    if not volunteer_planned:
                        volunteer_planned = True
                        volunteer_pid = next(
                            (player_id for player_id in pending.eligible_player_ids if engine.state.players[player_id].rank == 5),
                            None,
                        )
                    responder = next(player_id for player_id in pending.eligible_player_ids if player_id not in responses)
                    send(f"respond-{turn}-{responder}", responder, "respond-intervention", volunteer=responder == volunteer_pid)
                else:
                    send(f"decline-{turn}", victim, "decline-intervention")
            elif pending.kind == "reveal":
                target = pending.actor_player_id
                if not seen_timeout_reveal:
                    # The first reveal window resolves the way the server's
                    # DeadlineScheduler would on expiry (ADR 0011): the timeout
                    # command carries the window identity (payload shape
                    # mirrored from server/deadlines.py single_window) and
                    # defaults a wild marker to the question mark (issue 26).
                    seen_timeout_reveal = True
                    send(
                        f"timeout-reveal-{engine.state.revision}",
                        None,
                        "timeout-reveal",
                        actorPlayerId=target,
                        eligibleTokens=list(pending.context.get("eligibleTokens", [])),
                    )
                    continue
                token = pending.context["eligibleTokens"][0]
                payload = {"token": token}
                if token.startswith("marker-") and engine.state.players[target].identity_markers[int(token[-1])] == "wild":
                    payload["color"] = "unknown"
                send(f"reveal-{turn}-{engine.state.revision}", target, "choose-reveal", **payload)
            elif pending.kind == "skill":
                if pending.rank == "fleur-cross":
                    # deterministic distribution over the first live non-inquisitor seats
                    recipients = [pid for pid in sorted(engine.state.players) if pid != pending.actor_player_id]
                    assignments = {
                        curse_id: recipients[index % len(recipients)]
                        for index, curse_id in enumerate(engine.state.curses)
                    }
                    send(f"curse-{turn}", pending.actor_player_id, "choose-skill", use=True, assignments=assignments)
                elif pending.rank in {2, 5} and pending.rank not in used_skill_ranks:
                    used_skill_ranks.add(pending.rank)
                    send(
                        f"use-rank-{pending.rank}-{turn}",
                        pending.actor_player_id,
                        "choose-skill",
                        use=True,
                        targetPlayerId=fresh_target(pending.actor_player_id),
                    )
                elif not seen_timeout_skill:
                    # First declined window resolves as the scheduler's timeout
                    # would: an automatic decline that permanently spends the
                    # skill (ADR 0011 + ADR 0008).
                    seen_timeout_skill = True
                    send(
                        f"timeout-skill-{engine.state.revision}",
                        None,
                        "timeout-skill",
                        actorPlayerId=pending.actor_player_id,
                    )
                else:
                    send(f"skill-decline-{turn}", pending.actor_player_id, "choose-skill", use=False)
            else:
                raise RuntimeError(f"deterministic runner cannot resolve a {pending.kind} window")

    replay = Replay(
        game_id=game_id,
        seed=seed,
        command_ids=tuple(commands),
        event_types=tuple(event.event_type for event in events),
        final_revision=engine.state.revision,
        result=engine.state.result or {},
    )
    return engine, replay
