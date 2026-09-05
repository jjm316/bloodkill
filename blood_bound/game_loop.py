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

    The runner uses ordinary public commands only: it passes the dagger back to
    a fixed attacker, attacks one victim, has every eligible player decline to
    volunteer in the intervention poll, and declines skills — except the
    inquisitor, whose reveal-triggered curse window is used to distribute the
    curses deterministically (odd games attack the inquisitor for exactly that
    coverage; ADR 0003). It exists for golden replay and CI smoke coverage, not
    as an AI strategy.
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
    turn = 0
    while engine.state.status != "ended":
        turn += 1
        if turn > 100:
            raise RuntimeError("deterministic runner exceeded turn budget")
        holder = engine.state.dagger_holder_id
        if holder != attacker:
            send(f"pass-{turn}", holder, "pass-dagger", targetPlayerId=attacker)
        send(f"attack-{turn}", attacker, "attack", targetPlayerId=victim)
        while engine.state.pending and engine.state.pending.kind == "intervention":
            pending = engine.state.pending
            if pending.context.get("stage") == "poll":
                responses: dict[str, bool] = pending.context["responses"]
                responder = next(player_id for player_id in pending.eligible_player_ids if player_id not in responses)
                send(f"respond-{turn}-{responder}", responder, "respond-intervention", volunteer=False)
            else:
                send(f"decline-{turn}", victim, "decline-intervention")
        while engine.state.pending and engine.state.pending.kind == "reveal":
            target = engine.state.pending.actor_player_id
            token = engine.state.pending.context["eligibleTokens"][0]
            payload = {"token": token}
            if token.startswith("marker-") and engine.state.players[target].identity_markers[int(token[-1])] == "wild":
                payload["color"] = "rose"
            send(f"reveal-{turn}-{engine.state.revision}", target, "choose-reveal", **payload)
        if engine.state.pending and engine.state.pending.kind == "skill":
            pending = engine.state.pending
            if pending.rank == "fleur-cross":
                # deterministic distribution over the first live non-inquisitor seats
                recipients = [pid for pid in sorted(engine.state.players) if pid != pending.actor_player_id]
                assignments = {
                    curse_id: recipients[index % len(recipients)]
                    for index, curse_id in enumerate(engine.state.curses)
                }
                send(f"curse-{turn}", pending.actor_player_id, "choose-skill", use=True, assignments=assignments)
            else:
                send(f"skill-decline-{turn}", pending.actor_player_id, "choose-skill", use=False)

    replay = Replay(
        game_id=game_id,
        seed=seed,
        command_ids=tuple(commands),
        event_types=tuple(event.event_type for event in events),
        final_revision=engine.state.revision,
        result=engine.state.result or {},
    )
    return engine, replay
