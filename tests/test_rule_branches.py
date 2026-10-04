"""Focused tests for every implemented rule branch, filling the gaps left by
test_engine / test_projection.

A few branches are defensive gates whose triggers are not grantable through
public commands yet (shield/fan are granted by ranks 6/9 in issue 14, a second
skill window needs the alchemist's token return). Those tests inject the
trigger directly into the authority state and are commented as such; they
prove the gate, not the granting path.

Two tests document known defects found by the property net and are marked
`expectedFailure`; the referenced tickets remove the marker when fixed.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from blood_bound import Command, RuleError, RulesEngine, legal_actions, project_state, run_deterministic_game
from blood_bound.engine import Pending


class FixedClock:
    def __call__(self):
        return 0.0


def command(engine, command_id, actor, kind, **payload):
    return Command(command_id, engine.state.game_id, actor, engine.state.revision, kind, payload)


def started(count=6, seed="branch-seed"):
    engine = RulesEngine.new_game("branch-game", seed, clock=FixedClock())
    for index in range(count):
        engine.apply(command(engine, f"join-{index}", None, "join-game", playerId=f"p{index}", displayName=f"P{index}"))
    engine.apply(command(engine, "start", None, "start-game"))
    return engine


def started_with_ranks(count, *ranks, max_probes=200):
    """Probe seeds until every requested rank is dealt; returns (engine, {rank: player})."""
    for probe in range(max_probes):
        engine = started(count, seed=f"branch-probe-{probe}")
        found = {
            rank: next((player for player in engine.state.players.values() if player.rank == rank), None)
            for rank in ranks
        }
        if all(found.values()):
            return engine, found
    raise AssertionError(f"no probed seed dealt ranks {ranks} in a {count}-player game")


def give_dagger_to(engine, player_id):
    holder = engine.state.dagger_holder_id
    if holder != player_id:
        engine.apply(command(engine, f"pass-to-{player_id}-{engine.state.revision}", holder, "pass-dagger", targetPlayerId=player_id))


def mark_three_damage(engine, player_id):
    """Set a player to 3 damage with both clues revealed, as two resolved attacks would."""
    player = engine.state.players[player_id]
    player.damage = 3
    player.revealed = {"rank", "marker-0", "marker-1"}


def mark_two_damage(engine, player_id):
    """Set a player to 2 damage with both markers revealed, as two resolved attacks would."""
    player = engine.state.players[player_id]
    player.damage = 2
    player.revealed = {"marker-0", "marker-1"}
    player.revealed_values = {"marker-0": player.identity_markers[0], "marker-1": player.identity_markers[1]}


def reveal_rank(engine, player_id, command_id="reveal-rank"):
    if engine.state.pending and engine.state.pending.kind == "reveal" and "rank" in {"rank", "marker-0", "marker-1"} - engine.state.players[player_id].revealed:
        engine.apply(command(engine, command_id, player_id, "choose-reveal", token="rank"))


def answer_poll(engine, *volunteers):
    """Walk an attack's request gate and answer the poll in seat order; named
    players volunteer, the rest decline.

    The target first accepts the request gate (ADR 0012), which opens the
    poll. Stops once the poll stage closes (all answered), leaving a
    choice-stage pending when two or more players volunteered. Returns the
    last command's events, which carry the poll's resolution (or the
    choice-stage opening).
    """
    events: tuple = ()
    while engine.state.pending and engine.state.pending.kind == "intervention":
        pending = engine.state.pending
        stage = pending.context.get("stage")
        if stage == "gate":
            events = engine.apply(
                command(engine, f"gate-{engine.state.revision}", pending.actor_player_id, "answer-intervention-request", need=True)
            )
            continue
        if stage != "poll":
            break
        responses = pending.context["responses"]
        responder = next(pid for pid in pending.eligible_player_ids if pid not in responses)
        events = engine.apply(
            command(engine, f"respond-{engine.state.revision}", responder, "respond-intervention", volunteer=responder in volunteers)
        )
    return events


def attack_and_poll(engine, victim_id, command_id):
    """Declare a real attack on victim_id — rerouting the dagger if the victim
    holds it — and decline the poll. Returns the combined events, so the poll
    resolution (forced reveals, resource returns) stays assertable."""
    holder = engine.state.dagger_holder_id
    if holder == victim_id:
        give_dagger_to(engine, next(pid for pid, player in engine.state.players.items() if pid != victim_id and not player.captured))
    attacker = engine.state.dagger_holder_id
    events = list(engine.apply(command(engine, command_id, attacker, "attack", targetPlayerId=victim_id)))
    events += answer_poll(engine)
    return events


def attack_wound(engine, victim_id, prefix, reveal_token=None, color=None):
    """Resolve one real attack on victim_id end to end: declare it, decline the
    poll, then let the victim answer their reveal window with the given token.

    A wound the engine resolves directly (the last plain marker at the forced
    third point) opens no window and needs no token; a wound that opens the
    victim's skill window leaves it open for the caller to answer.
    """
    events = attack_and_poll(engine, victim_id, f"{prefix}-attack")
    pending = engine.state.pending
    if pending is not None and pending.kind == "reveal":
        assert reveal_token is not None, f"{prefix}: reveal window opened but no token given"
        payload = {"token": reveal_token}
        if color is not None:
            payload["color"] = color
        events += engine.apply(command(engine, f"{prefix}-reveal", pending.actor_player_id, "choose-reveal", **payload))
    return events


def arm_guardian_ward(engine, guardian_id, ward_id, prefix):
    """Walk the guardian's first wound through a real attack: the guardian
    shows the rank, the rank-6 skill window opens on that reveal, and using it
    hands the ward target the shield and the guardian the sword."""
    attack_wound(engine, guardian_id, prefix, reveal_token="rank")
    pending = engine.state.pending
    assert pending is not None and pending.kind == "skill" and pending.rank == 6, f"{prefix}: expected the guardian's skill window"
    return engine.apply(command(engine, f"{prefix}-skill", guardian_id, "choose-skill", use=True, targetPlayerId=ward_id))


def assert_ward_returned(testcase, events, guardian_id, ward_id):
    """The rank-6 third-point settlement: exactly one sword and one shield
    return, both reasoned guardian-ward-complete, sword before shield."""
    testcase.assertEqual(
        [event.payload for event in events if event.event_type == "ResourceReturned"],
        [
            {"playerId": guardian_id, "resource": "sword", "amount": 1, "reason": "guardian-ward-complete"},
            {"playerId": ward_id, "resource": "shield", "amount": 1, "reason": "guardian-ward-complete"},
        ],
    )


def assert_ward_settled(testcase, engine, guardian_id, ward_id, prefix):
    """The shared B7 tail after the third point: the guardian sits at exactly
    3 damage with both resources back to zero, and the fourth point captures
    without re-emitting the ward return."""
    guardian_player = engine.state.players[guardian_id]
    testcase.assertEqual(guardian_player.damage, 3)
    testcase.assertEqual(guardian_player.resources["sword"], 0)
    testcase.assertEqual(engine.state.players[ward_id].resources["shield"], 0)
    capture_events = capture_at_three_damage(engine, guardian_id, prefix)
    testcase.assertEqual(engine.state.status, "ended")
    testcase.assertIn("PlayerCaptured", [event.event_type for event in capture_events])
    testcase.assertNotIn("ResourceReturned", [event.event_type for event in capture_events])


def capture_at_three_damage(engine, victim_id, prefix):
    """Take a 3-damage victim through the fourth point with a real attack: the
    capture settles the game."""
    return attack_and_poll(engine, victim_id, f"{prefix}-capture")


def assassin_skill_scenario_log() -> list[list]:
    """Drive the assassin skill to completion and return its full event log.

    Wounds the assassin to open the rank-2 skill window, uses it on a fresh
    victim, then answers every victim-choice reveal window deterministically
    (first eligible token, rose for wild markers). Returns [event_type,
    payload] pairs for every command; the hash-seed regression test compares
    this log across PYTHONHASHSEED values — the pre-ADR-0006 engine picked
    the auto-revealed token with next(iter(available)), which flipped with
    the hash seed (coupling point A2).
    """
    engine, found = started_with_ranks(6, 2)
    assassin = found[2]
    attacker = engine.state.dagger_holder_id
    if attacker == assassin.player_id:
        give_dagger_to(engine, next(pid for pid in engine.state.players if pid != assassin.player_id))
        attacker = engine.state.dagger_holder_id
    victim = next(
        pid for pid, player in engine.state.players.items()
        if pid not in (attacker, assassin.player_id) and player.damage == 0
    )
    log: list[list] = []

    def record(events) -> None:
        log.extend([event.event_type, event.payload] for event in events)

    record(engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=assassin.player_id)))
    record(answer_poll(engine))
    record(engine.apply(command(engine, "reveal-rank", assassin.player_id, "choose-reveal", token="rank")))
    record(engine.apply(command(engine, "use", assassin.player_id, "choose-skill", use=True, targetPlayerId=victim)))
    while engine.state.pending and engine.state.pending.kind == "reveal":
        token = engine.state.pending.context["eligibleTokens"][0]
        payload = {"token": token}
        if token.startswith("marker-") and engine.state.players[victim].identity_markers[int(token[-1])] == "wild":
            payload["color"] = "rose"
        record(engine.apply(command(engine, f"reveal-{engine.state.revision}", victim, "choose-reveal", **payload)))
    return log


class SetupBranchTests(unittest.TestCase):
    def test_join_after_start_is_rejected(self):
        engine = started()
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "late", None, "join-game", playerId="late"))
        self.assertEqual(error.exception.code, "game.not-setup")

    def test_join_without_player_id_is_rejected(self):
        engine = RulesEngine.new_game("g", "seed", clock=FixedClock())
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "empty", None, "join-game"))
        self.assertEqual(error.exception.code, "player.not-eligible")

    def test_duplicate_player_is_rejected(self):
        engine = RulesEngine.new_game("g", "seed", clock=FixedClock())
        engine.apply(command(engine, "j0", None, "join-game", playerId="p0"))
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "j0-again", None, "join-game", playerId="p0"))
        self.assertEqual(error.exception.code, "game.duplicate-player")

    def test_thirteenth_player_is_rejected(self):
        engine = RulesEngine.new_game("g", "seed", clock=FixedClock())
        for index in range(12):
            engine.apply(command(engine, f"join-{index}", None, "join-game", playerId=f"p{index}"))
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "join-12", None, "join-game", playerId="p12"))
        self.assertEqual(error.exception.code, "game.player-count")

    def test_seat_conflict_and_out_of_range_are_rejected(self):
        engine = RulesEngine.new_game("g", "seed", clock=FixedClock())
        engine.apply(command(engine, "j0", None, "join-game", playerId="p0", seat=3))
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "j1", None, "join-game", playerId="p1", seat=3))
        self.assertEqual(error.exception.code, "game.seat-occupied")
        for bad_seat in (12, -1):
            with self.subTest(seat=bad_seat):
                with self.assertRaises(RuleError) as error:
                    engine.apply(command(engine, f"j-{bad_seat}", None, "join-game", playerId=f"p-{bad_seat}", seat=bad_seat))
                self.assertEqual(error.exception.code, "game.seat-occupied")

    def test_auto_seat_assigns_lowest_free_seat(self):
        engine = RulesEngine.new_game("g", "seed", clock=FixedClock())
        engine.apply(command(engine, "j0", None, "join-game", playerId="p0"))
        engine.apply(command(engine, "j1", None, "join-game", playerId="p1", seat=4))
        engine.apply(command(engine, "j2", None, "join-game", playerId="p2"))
        self.assertEqual(
            {player.seat for player in engine.state.players.values()},
            {0, 1, 4},
        )

    def test_start_with_fewer_than_six_is_rejected(self):
        engine = RulesEngine.new_game("g", "seed", clock=FixedClock())
        for index in range(5):
            engine.apply(command(engine, f"join-{index}", None, "join-game", playerId=f"p{index}"))
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "start", None, "start-game"))
        self.assertEqual(error.exception.code, "game.player-count")

    def test_second_start_is_rejected(self):
        engine = started()
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "restart", None, "start-game"))
        self.assertEqual(error.exception.code, "game.not-setup")


class CommandGuardBranchTests(unittest.TestCase):
    def test_command_for_another_game_is_rejected(self):
        engine = started()
        with self.assertRaises(RuleError) as error:
            engine.apply(Command("x", "other-game", None, 0, "join-game", {"playerId": "p0"}))
        self.assertEqual(error.exception.code, "game.not-found")

    def test_reused_command_id_with_different_body_is_rejected(self):
        engine = started()
        holder = engine.state.dagger_holder_id
        first_target = next(pid for pid in engine.state.players if pid != holder)
        second_target = next(pid for pid in engine.state.players if pid not in (holder, first_target))
        engine.apply(command(engine, "pass-1", holder, "pass-dagger", targetPlayerId=first_target))
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "pass-1", holder, "pass-dagger", targetPlayerId=second_target))
        self.assertEqual(error.exception.code, "command.id-reuse")

    def test_command_after_game_end_is_rejected(self):
        engine, _ = run_deterministic_game(6, game_id="done", seed="done-seed")
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "late", None, "join-game", playerId="late"))
        self.assertEqual(error.exception.code, "game.already-ended")

    def test_pass_by_non_holder_is_rejected(self):
        engine = started()
        holder = engine.state.dagger_holder_id
        other = next(pid for pid in engine.state.players if pid != holder)
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "sneak", other, "pass-dagger", targetPlayerId=holder))
        self.assertEqual(error.exception.code, "player.not-dagger-holder")

    def test_pass_to_self_is_rejected(self):
        engine = started()
        holder = engine.state.dagger_holder_id
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "self", holder, "pass-dagger", targetPlayerId=holder))
        self.assertEqual(error.exception.code, "target.not-eligible")

    def test_attack_to_self_is_rejected(self):
        engine = started()
        holder = engine.state.dagger_holder_id
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "self", holder, "attack", targetPlayerId=holder))
        self.assertEqual(error.exception.code, "target.not-eligible")

    def test_action_command_during_intervention_window_is_rejected(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "rush", attacker, "pass-dagger", targetPlayerId=target))
        self.assertEqual(error.exception.code, "game.not-active")


class AttackBranchTests(unittest.TestCase):
    def test_attack_opens_gate_then_poll_hands_dagger_and_lists_eligible(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        events = engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        self.assertEqual(events[0].event_type, "AttackDeclared")
        self.assertEqual(events[0].payload, {"attackerPlayerId": attacker, "targetPlayerId": target})
        self.assertEqual(events[1].event_type, "InterventionGateOpened")
        self.assertEqual(events[1].payload["targetPlayerId"], target)
        self.assertEqual(events[1].payload["attackerPlayerId"], attacker)
        self.assertEqual(engine.state.dagger_holder_id, target)
        self.assertEqual(engine.state.phase, {"kind": "intervention", "stage": "gate", "activePlayerId": target})
        # the target's accept relays into the poll with its fields unchanged
        events = engine.apply(command(engine, "gate-yes", target, "answer-intervention-request", need=True))
        self.assertEqual(events[1].event_type, "InterventionPollOpened")
        self.assertEqual(events[1].payload["targetPlayerId"], target)
        self.assertEqual(events[1].payload["attackerPlayerId"], attacker)
        self.assertEqual(engine.state.phase, {"kind": "intervention", "stage": "poll", "activePlayerId": target})
        pending = engine.state.pending
        self.assertEqual(pending.kind, "intervention")
        self.assertEqual(pending.context["attackerPlayerId"], attacker)
        self.assertEqual(pending.context["stage"], "poll")
        self.assertEqual(pending.context["responses"], {})
        self.assertNotIn(attacker, pending.eligible_player_ids)
        self.assertNotIn(target, pending.eligible_player_ids)
        for pid in pending.eligible_player_ids:
            self.assertNotIn("rank", engine.state.players[pid].revealed)
        self.assertEqual(
            set(pending.eligible_player_ids),
            {pid for pid in engine.state.players if pid not in (attacker, target)},
        )

    def test_all_declining_attack_leaves_dagger_with_wounded_target(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        answer_poll(engine)
        # corpus combat/attack-handoff and intervention/refused: once the attack
        # resolves without intervention, the wounded target keeps the dagger.
        engine.apply(command(engine, "reveal-marker", target, "choose-reveal", token="marker-0"))
        self.assertIsNone(engine.state.pending)
        self.assertEqual(engine.state.players[target].damage, 1)
        self.assertEqual(engine.state.dagger_holder_id, target)
        self.assertEqual(engine.state.phase, {"kind": "action", "activePlayerId": target})
        self.assertIn("pass-dagger", [action["type"] for action in legal_actions(engine.state, target)])
        self.assertEqual(legal_actions(engine.state, attacker), [])

    def test_shielded_target_is_rejected(self):
        # shields are granted by rank 6 in issue 14; inject the resource directly
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.state.players[target].resources["shield"] = 1
        revision = engine.state.revision
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        self.assertEqual(error.exception.code, "target.shielded")
        self.assertEqual(engine.state.revision, revision)

    def test_shield_does_not_block_volunteering_as_responder(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        responder = next(pid for pid in engine.state.players if pid not in (attacker, target))
        engine.state.players[responder].resources["shield"] = 1
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        answer_poll(engine, responder)
        self.assertEqual(engine.state.players[responder].damage, 1)

    def test_inquisitor_cannot_attack_target_with_three_damage(self):
        engine = started(7)
        inquisitor = next(pid for pid, player in engine.state.players.items() if player.faction == "secret-order")
        victim = next(pid for pid in engine.state.players if pid != inquisitor)
        mark_three_damage(engine, victim)
        give_dagger_to(engine, inquisitor)
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "attack", inquisitor, "attack", targetPlayerId=victim))
        self.assertEqual(error.exception.code, "target.already-three-damage")

    def test_fan_target_blocks_all_intervention_responders(self):
        # fans are granted by rank 9 in issue 14; inject the resource directly
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.state.players[target].resources["fan"] = 1
        events = engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        # every other player still holds an unrevealed rank, yet nobody is
        # eligible: no gate and no poll open (ADR 0012 moves the empty-set
        # short-circuit ahead of the gate), the attack resolves immediately
        self.assertNotIn("InterventionGateOpened", [event.event_type for event in events])
        self.assertNotIn("InterventionPollOpened", [event.event_type for event in events])
        self.assertEqual(engine.state.players[target].damage, 1)

    def test_attack_with_no_eligible_resolves_damage_directly(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(
            pid for pid, player in engine.state.players.items()
            if pid != attacker and player.rank not in (1, 2)
        )
        for pid in engine.state.players:
            if pid not in (attacker, target):
                player = engine.state.players[pid]
                player.damage = 1
                player.revealed = {"rank"}
        events = engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        self.assertNotIn("InterventionGateOpened", [event.event_type for event in events])
        self.assertNotIn("InterventionPollOpened", [event.event_type for event in events])
        self.assertIn("DamageApplied", [event.event_type for event in events])
        self.assertEqual(engine.state.players[target].damage, 1)
        self.assertEqual(engine.state.pending.kind, "reveal")
        engine.apply(command(engine, "reveal-marker", target, "choose-reveal", token="marker-0"))
        # the directly resolved attack wound also leaves the dagger with the target
        self.assertEqual(engine.state.dagger_holder_id, target)

    def test_respond_guards_target_attacker_and_double_answers(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        engine.apply(command(engine, "gate-yes", target, "answer-intervention-request", need=True))
        for actor in (attacker, target):
            with self.subTest(actor=actor):
                with self.assertRaises(RuleError) as error:
                    engine.apply(command(engine, f"wrong-{actor}", actor, "respond-intervention", volunteer=True))
                self.assertEqual(error.exception.code, "intervention.not-eligible")
        responder = next(pid for pid in engine.state.pending.eligible_player_ids)
        engine.apply(command(engine, "first", responder, "respond-intervention", volunteer=False))
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "again", responder, "respond-intervention", volunteer=True))
        self.assertEqual(error.exception.code, "intervention.already-responded")

    def test_respond_without_window_is_rejected(self):
        engine = started()
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "nothing", "p0", "respond-intervention", volunteer=True))
        self.assertEqual(error.exception.code, "intervention.not-open")

    def test_choose_or_decline_during_poll_stage_is_rejected(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        engine.apply(command(engine, "gate-yes", target, "answer-intervention-request", need=True))
        responder = next(pid for pid in engine.state.pending.eligible_player_ids)
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "jump", target, "choose-intervention", responderPlayerId=responder))
        self.assertEqual(error.exception.code, "intervention.not-choice")
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "early", target, "decline-intervention"))
        self.assertEqual(error.exception.code, "intervention.not-choice")

    def test_choose_intervention_without_window_is_rejected(self):
        engine = started()
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "nothing", "p0", "choose-intervention", responderPlayerId="p1"))
        self.assertEqual(error.exception.code, "intervention.not-open")

    def test_choose_non_volunteer_responder_is_rejected(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        eligible = list(engine.state.pending.eligible_player_ids)
        answer_poll(engine, eligible[0], eligible[1])
        self.assertEqual(engine.state.pending.context["stage"], "choice")
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "choose-silent", target, "choose-intervention", responderPlayerId=eligible[2]))
        self.assertEqual(error.exception.code, "intervention.not-eligible")

    def test_intervention_damage_reveals_responder_rank_and_opens_skill_window(self):
        engine, found = started_with_ranks(6, 2)
        responder = found[2].player_id
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid not in (attacker, responder))
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        events = answer_poll(engine, responder)
        reveal_rank(engine, responder)
        damage = next(event for event in events if event.event_type == "DamageApplied")
        self.assertEqual(damage.payload["source"], "intervention")
        self.assertEqual(engine.state.players[responder].damage, 1)
        self.assertIn("rank", engine.state.players[responder].revealed)
        # intervention's forced rank reveal opens the rank's one-time skill window.
        self.assertEqual(engine.state.pending.kind, "skill")

    def test_intervention_responder_takes_the_dagger(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        responder = next(pid for pid in engine.state.players if pid not in (attacker, target))
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        answer_poll(engine, responder)
        # corpus scenario intervention/selected-responder: "C 接过匕首并承受该点伤害"
        if engine.state.pending and engine.state.pending.kind == "skill":
            engine.apply(command(engine, "decline-responder-skill", responder, "choose-skill", use=False))
        self.assertEqual(engine.state.dagger_holder_id, responder)
        self.assertEqual(engine.state.phase, {"kind": "action", "activePlayerId": responder})


class SkillBranchTests(unittest.TestCase):
    def test_berserker_reaction_damages_attacker_without_new_window(self):
        engine, found = started_with_ranks(6, 7)
        berserker = found[7]
        attacker = engine.state.dagger_holder_id
        if attacker == berserker.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != berserker.player_id))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack-7", attacker, "attack", targetPlayerId=berserker.player_id))
        answer_poll(engine)
        reveal_rank(engine, berserker.player_id)
        self.assertEqual(engine.state.pending.rank, 7)
        events = engine.apply(command(engine, "use-7", berserker.player_id, "choose-skill", use=True))
        self.assertEqual(engine.state.players[berserker.player_id].damage, 1)
        self.assertEqual(engine.state.players[attacker].damage, 1)
        self.assertNotIn("SkillWindowOpened", [event.event_type for event in events])
        reaction = next(event for event in events if event.event_type == "DamageApplied")
        self.assertEqual(reaction.payload, {"targetPlayerId": attacker, "amount": 1, "source": "reaction", "triggerContext": None})
        self.assertEqual(engine.state.pending.kind, "reveal")
        engine.apply(command(engine, "reveal-reaction", attacker, "choose-reveal", token="marker-0"))
        self.assertIsNone(engine.state.pending)
        self.assertEqual(engine.state.dagger_holder_id, berserker.player_id)

    def test_berserker_reaction_capture_uses_berserker_as_active_player(self):
        engine, found = started_with_ranks(6, 7)
        berserker = found[7]
        attacker = engine.state.dagger_holder_id
        if attacker == berserker.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != berserker.player_id))
            attacker = engine.state.dagger_holder_id
        engine.state.players[attacker].damage = 3
        engine.apply(command(engine, "attack-7-capture", attacker, "attack", targetPlayerId=berserker.player_id))
        answer_poll(engine)
        reveal_rank(engine, berserker.player_id)
        events = engine.apply(command(engine, "use-7-capture", berserker.player_id, "choose-skill", use=True))
        self.assertEqual(engine.state.status, "ended")
        ended = next(event for event in events if event.event_type == "GameEnded")
        self.assertEqual(ended.payload["activePlayerId"], berserker.player_id)
        self.assertEqual(engine.state.result["capturedPlayerId"], attacker)

    def test_shielded_berserker_volunteer_can_react(self):
        # ADR 0010: the shield only blocks being targeted, so a shielded
        # berserker who volunteers as responder keeps the reaction — the old
        # owner check left "decline" as the only choice, permanently sealing
        # the skill under ADR 0008 after a window the shield itself opened
        engine, found = started_with_ranks(6, 7)
        berserker = found[7]
        attacker = engine.state.dagger_holder_id
        if attacker == berserker.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != berserker.player_id))
            attacker = engine.state.dagger_holder_id
        victim = next(pid for pid in engine.state.players if pid not in (attacker, berserker.player_id))
        # shields are granted by rank 6 in issue 14; inject the resource directly
        engine.state.players[berserker.player_id].resources["shield"] = 1
        engine.apply(command(engine, "attack-7-shielded", attacker, "attack", targetPlayerId=victim))
        answer_poll(engine, berserker.player_id)
        # intervention wounds force the rank outright: no reveal window is
        # offered, the rank lands revealed and the window opens in-command
        self.assertEqual(engine.state.players[berserker.player_id].revealed, {"rank"})
        self.assertEqual(engine.state.pending.rank, 7)
        self.assertIn({"type": "choose-skill", "use": True}, legal_actions(engine.state, berserker.player_id))
        engine.apply(command(engine, "use-7-shielded", berserker.player_id, "choose-skill", use=True))
        self.assertEqual(engine.state.players[berserker.player_id].damage, 1)
        self.assertEqual(engine.state.players[attacker].damage, 1)
        self.assertIn("7", engine.state.players[berserker.player_id].skills_used)
        self.assertEqual(engine.state.pending.kind, "reveal")
        engine.apply(command(engine, "reveal-reaction", attacker, "choose-reveal", token="marker-0"))
        self.assertIsNone(engine.state.pending)
        self.assertEqual(engine.state.dagger_holder_id, berserker.player_id)

    def test_shielded_attacker_blocks_berserker_reaction(self):
        # coupling point B1 (kept by ADR 0010): the reaction targets the
        # attacker, so a shielded attacker intercepts it; the failed command
        # burns nothing
        engine, found = started_with_ranks(6, 7)
        berserker = found[7]
        attacker = engine.state.dagger_holder_id
        if attacker == berserker.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != berserker.player_id))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack-7-b1", attacker, "attack", targetPlayerId=berserker.player_id))
        answer_poll(engine)
        reveal_rank(engine, berserker.player_id)
        self.assertEqual(engine.state.pending.rank, 7)
        # shields are granted by rank 6 in issue 14; inject the resource directly
        engine.state.players[attacker].resources["shield"] = 1
        revision = engine.state.revision
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "use-7-b1", berserker.player_id, "choose-skill", use=True))
        self.assertEqual(error.exception.code, "target.shielded")
        self.assertEqual(engine.state.revision, revision)
        self.assertNotIn("7", engine.state.players[berserker.player_id].skills_used)

    def test_alchemist_harm_targets_protected_player_without_skill_window(self):
        engine, found = started_with_ranks(6, 4)
        alchemist = found[4]
        attacker = engine.state.dagger_holder_id
        if attacker == alchemist.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != alchemist.player_id))
            attacker = engine.state.dagger_holder_id
        protected = next(player for player in engine.state.players.values() if player.player_id not in {attacker, alchemist.player_id})
        protected.revealed = {"marker-0"}
        protected.revealed_values["marker-0"] = protected.identity_markers[0]
        engine.apply(command(engine, "attack-4", attacker, "attack", targetPlayerId=protected.player_id))
        answer_poll(engine, alchemist.player_id)
        reveal_rank(engine, alchemist.player_id, "reveal-alchemist")
        events = list(engine.apply(command(engine, "harm-4", alchemist.player_id, "choose-skill", use=True, mode="harm")))
        # ADR 0006: the harm wound opens a victim-choice reveal window for
        # the protected player, exactly like any other damage
        self.assertEqual(engine.state.players[protected.player_id].damage, 1)
        self.assertEqual(engine.state.pending.kind, "reveal")
        self.assertEqual(engine.state.pending.actor_player_id, protected.player_id)
        self.assertEqual(engine.state.pending.context["eligibleTokens"], ["marker-1", "rank"])
        events += engine.apply(command(engine, "answer-harm", protected.player_id, "choose-reveal", token="marker-1"))
        # the harm never opens a skill window and the alchemist keeps the dagger
        self.assertIsNone(engine.state.pending)
        self.assertEqual(engine.state.dagger_holder_id, alchemist.player_id)
        self.assertNotIn("SkillWindowOpened", [event.event_type for event in events])

    def test_alchemist_harm_affordance_filters_shielded_protected_player(self):
        # issue 06 (coupling point B1 alignment): the harm affordance filters a
        # shielded protected player exactly like the assassin/mentalist target
        # lists, instead of offering a button the engine rejects at submit time
        engine, found = started_with_ranks(6, 4)
        alchemist = found[4]
        attacker = engine.state.dagger_holder_id
        if attacker == alchemist.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != alchemist.player_id))
            attacker = engine.state.dagger_holder_id
        protected = next(player for player in engine.state.players.values() if player.player_id not in {attacker, alchemist.player_id})
        engine.apply(command(engine, "attack-4-filter", attacker, "attack", targetPlayerId=protected.player_id))
        answer_poll(engine, alchemist.player_id)
        reveal_rank(engine, alchemist.player_id, "reveal-alchemist-filter")
        harm = {"type": "choose-skill", "use": True, "mode": "harm"}
        self.assertIn(harm, legal_actions(engine.state, alchemist.player_id))
        # a live attack on a shielded player is rejected up front, so only an
        # injected shield can put the two facts together today; inject directly
        engine.state.players[protected.player_id].resources["shield"] = 1
        actions = legal_actions(engine.state, alchemist.player_id)
        self.assertNotIn(harm, actions)
        self.assertIn({"type": "choose-skill", "use": False}, actions)
        # the engine keeps its defensive rejection and burns nothing on it
        revision = engine.state.revision
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "harm-shielded", alchemist.player_id, "choose-skill", use=True, mode="harm"))
        self.assertEqual(error.exception.code, "target.shielded")
        self.assertEqual(engine.state.revision, revision)
        self.assertNotIn("4", engine.state.players[alchemist.player_id].skills_used)

    def test_alchemist_heal_opens_token_return_and_returns_marker(self):
        engine, found = started_with_ranks(6, 4)
        alchemist = found[4]
        attacker = engine.state.dagger_holder_id
        if attacker == alchemist.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != alchemist.player_id))
            attacker = engine.state.dagger_holder_id
        protected = next(player for player in engine.state.players.values() if player.player_id not in {attacker, alchemist.player_id})
        protected.damage = 1
        protected.revealed = {"marker-0"}
        protected.revealed_values["marker-0"] = protected.identity_markers[0]
        engine.apply(command(engine, "attack-heal", attacker, "attack", targetPlayerId=protected.player_id))
        answer_poll(engine, alchemist.player_id)
        reveal_rank(engine, alchemist.player_id, "reveal-heal-alchemist")
        engine.apply(command(engine, "heal", alchemist.player_id, "choose-skill", use=True, mode="heal"))
        self.assertEqual(engine.state.pending.kind, "token-return")
        self.assertEqual(legal_actions(engine.state, protected.player_id), [{"type": "choose-return", "token": "marker-0"}])
        events = engine.apply(command(engine, "return", protected.player_id, "choose-return", token="marker-0"))
        protected_after = engine.state.players[protected.player_id]
        self.assertEqual(protected_after.damage, 0)
        self.assertNotIn("marker-0", protected_after.revealed)
        self.assertEqual([event.event_type for event in events], ["DamageHealed", "TokenReturned", "PhaseChanged"])

    def test_alchemist_does_not_open_from_direct_attack(self):
        engine, found = started_with_ranks(6, 4)
        alchemist = found[4]
        attacker = engine.state.dagger_holder_id
        if attacker == alchemist.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != alchemist.player_id))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack-direct-4", attacker, "attack", targetPlayerId=alchemist.player_id))
        answer_poll(engine)
        reveal_rank(engine, alchemist.player_id, "reveal-direct-4")
        self.assertIsNone(engine.state.pending)

    def open_skill(self, engine, player):
        engine.state.pending = Pending("skill", player.player_id, player.player_id, rank=player.rank, trigger="attack")
        engine.state.phase = {"kind": "skill", "activePlayerId": player.player_id}

    def test_choose_skill_without_window_is_rejected(self):
        engine = started()
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "nothing", "p0", "choose-skill", use=False))
        self.assertEqual(error.exception.code, "skill.not-open")

    def test_wrong_actor_cannot_choose_skill(self):
        engine, found = started_with_ranks(6, 1)
        elder = found[1]
        attacker = engine.state.dagger_holder_id
        if attacker == elder.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != elder.player_id))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=elder.player_id))
        answer_poll(engine)
        reveal_rank(engine, elder.player_id)
        bystander = next(pid for pid in engine.state.players if pid != elder.player_id)
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "steal", bystander, "choose-skill", use=True))
        self.assertEqual(error.exception.code, "player.not-actor")

    def test_elder_skill_grants_quill(self):
        engine, found = started_with_ranks(6, 1)
        elder = found[1]
        attacker = engine.state.dagger_holder_id
        if attacker == elder.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != elder.player_id))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=elder.player_id))
        answer_poll(engine)
        reveal_rank(engine, elder.player_id)
        events = engine.apply(command(engine, "use", elder.player_id, "choose-skill", use=True))
        self.assertIn("SkillUsed", [event.event_type for event in events])
        self.assertIn("ResourceGranted", [event.event_type for event in events])
        self.assertIn("ResourceSpent", [event.event_type for event in events])
        spent = next(event for event in events if event.event_type == "ResourceSpent")
        self.assertEqual(spent.payload, {"playerId": elder.player_id, "resource": "quill", "amount": 1, "reason": "leader-succession"})
        self.assertEqual(engine.state.players[elder.player_id].resources["quill"], 0)
        self.assertIn(elder.faction, engine.state.max_leader_factions)
        self.assertIn("1", engine.state.players[elder.player_id].skills_used)

    def test_elder_succession_changes_leader_to_highest_rank(self):
        engine, found = started_with_ranks(6, 1)
        elder = found[1]
        family = elder.faction
        captured_elder = deepcopy(elder)
        captured_elder.captured = True
        captured_elder.damage = 4
        self.assertTrue(engine._is_leader(engine.state, captured_elder))
        engine.state.max_leader_factions.add(family)
        highest = max(
            (player for player in engine.state.players.values() if player.faction == family and player.player_id != elder.player_id and isinstance(player.rank, int)),
            key=lambda player: player.rank,
        )
        self.assertFalse(engine._is_leader(engine.state, captured_elder))
        captured_highest = deepcopy(highest)
        captured_highest.captured = True
        captured_highest.damage = 4
        self.assertTrue(engine._is_leader(engine.state, captured_highest))

    def test_harlequin_inspects_two_targets_with_private_feedback(self):
        engine, found = started_with_ranks(6, 3)
        owner = found[3]
        targets = [player for player in engine.state.players.values() if player.player_id != owner.player_id][:2]
        self.open_skill(engine, owner)
        events = engine.apply(command(engine, "inspect", owner.player_id, "choose-skill", use=True, targetPlayerIds=[p.player_id for p in targets]))
        self.assertEqual(events[1].event_type, "HarlequinInspected")
        self.assertNotIn("faction", events[1].payload)
        owner = engine.state.players[owner.player_id]
        self.assertEqual(set(owner.inspections), {p.player_id for p in targets})
        self.assertEqual(project_state(engine.state, owner.player_id)["viewer"]["inspections"][targets[0].player_id]["rank"], engine.state.players[targets[0].player_id].rank)

    def test_mentalist_damages_target_forces_rank_and_hands_dagger(self):
        engine, found = started_with_ranks(6, 5)
        owner = found[5]
        target = next(player for player in engine.state.players.values() if player.player_id != owner.player_id)
        self.open_skill(engine, owner)
        events = engine.apply(command(engine, "mentalist", owner.player_id, "choose-skill", use=True, targetPlayerId=target.player_id))
        # the force-reveal comes from the mentalist's skill text (ADR 0006),
        # not the generic third-point rule: the rank is shown directly with
        # no victim-choice window
        self.assertEqual(engine.state.players[target.player_id].damage, 1)
        self.assertIn("rank", engine.state.players[target.player_id].revealed)
        self.assertNotIn("RevealWindowOpened", [event.event_type for event in events])
        # ADR 0009 plan A: the forced reveal is the sole window exception and
        # seals the victim's skill by writing the rank into the same
        # never-cleared lock as used/declined skills
        self.assertIn(str(target.rank), engine.state.players[target.player_id].skills_used)
        self.assertNotIn("SkillWindowOpened", [event.event_type for event in events])
        self.assertIsNone(engine.state.pending)
        self.assertEqual(engine.state.dagger_holder_id, target.player_id)

    def test_mentalist_wound_on_shown_rank_falls_back_to_victim_choice(self):
        engine, found = started_with_ranks(6, 5)
        owner = found[5]
        target = next(player for player in engine.state.players.values() if player.player_id != owner.player_id)
        target.revealed = {"rank"}
        target.revealed_values["rank"] = target.rank
        self.open_skill(engine, owner)
        engine.apply(command(engine, "mentalist", owner.player_id, "choose-skill", use=True, targetPlayerId=target.player_id))
        # nothing left to force once the rank is already shown: the wound
        # rides the generic victim-choice pipeline (corpus rank 5 text)
        self.assertEqual(engine.state.pending.kind, "reveal")
        self.assertEqual(engine.state.pending.context["eligibleTokens"], ["marker-0", "marker-1"])
        engine.apply(command(engine, "reveal-marker", target.player_id, "choose-reveal", token="marker-0"))
        self.assertEqual(engine.state.players[target.player_id].damage, 1)
        # nothing was newly rank-revealed, so there is no seal and no window
        self.assertEqual(engine.state.players[target.player_id].skills_used, set())
        self.assertIsNone(engine.state.pending)
        self.assertEqual(engine.state.dagger_holder_id, target.player_id)

    def test_guardian_returns_sword_and_shield_on_third_attack_damage(self):
        # B7 (corpus rank 6 / batch confirmation "含技能/反伤源"): the return
        # rides the third damage point whatever its source. This scenario walks
        # a plain attack through real commands — the old whitebox test called
        # the private _after_damage on a hand-set damage total instead.
        engine, found = started_with_ranks(6, 6)
        guardian = found[6]
        ward = next(pid for pid in engine.state.players if pid != guardian.player_id)
        skill_events = arm_guardian_ward(engine, guardian.player_id, ward, "guardian-a")
        self.assertEqual(
            [event.event_type for event in skill_events],
            ["SkillUsed", "ResourceGranted", "ResourceGranted", "PhaseChanged"],
        )
        self.assertEqual(engine.state.players[guardian.player_id].resources["sword"], 1)
        self.assertEqual(engine.state.players[ward].resources["shield"], 1)
        attack_wound(engine, guardian.player_id, "guardian-a2", reveal_token="marker-0")
        events = attack_wound(engine, guardian.player_id, "guardian-a3")
        assert_ward_returned(self, events, guardian.player_id, ward)
        self.assertIsNone(engine.state.players[guardian.player_id].shield_ward_id)
        # the fourth point captures and must never re-emit the ward return
        assert_ward_settled(self, engine, guardian.player_id, ward, "guardian-a4")

    def test_guardian_returns_sword_and_shield_on_intervention_damage(self):
        # B7 via the blocking source: the guardian volunteers as responder and
        # the intervention wound is the third point. C1 keeps rank-shown
        # players off the volunteer list, so the witness first hides the
        # guardian's rank again the only way the rules allow — the alchemist
        # heals the token back (which also heals a point) — and then re-takes
        # the wounds before blocking.
        engine, found = started_with_ranks(6, 6, 4)
        guardian = found[6]
        alchemist = found[4]
        ward = next(pid for pid in engine.state.players if pid not in (guardian.player_id, alchemist.player_id))
        arm_guardian_ward(engine, guardian.player_id, ward, "guardian-b")
        attack_wound(engine, guardian.player_id, "guardian-b2", reveal_token="marker-0")
        self.assertEqual(engine.state.players[guardian.player_id].damage, 2)
        # the alchemist blocks a third attack aimed at the guardian and heals
        # the rank token back: damage 2 -> 1, rank hidden, sword and ward alive
        give_dagger_to(engine, next(pid for pid, player in engine.state.players.items() if pid not in (guardian.player_id, alchemist.player_id) and not player.captured))
        attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "guardian-b3-attack", attacker, "attack", targetPlayerId=guardian.player_id))
        answer_poll(engine, alchemist.player_id)
        self.assertEqual(engine.state.pending.kind, "skill")
        self.assertEqual(engine.state.pending.rank, 4)
        engine.apply(command(engine, "guardian-b3-heal", alchemist.player_id, "choose-skill", use=True, mode="heal"))
        self.assertEqual(engine.state.pending.kind, "token-return")
        engine.apply(command(engine, "guardian-b3-return", guardian.player_id, "choose-return", token="rank"))
        guardian_player = engine.state.players[guardian.player_id]
        self.assertEqual(guardian_player.damage, 1)
        self.assertNotIn("rank", guardian_player.revealed)
        # back to two wounds with the rank still hidden, then block for a victim
        attack_wound(engine, guardian.player_id, "guardian-b4", reveal_token="marker-1")
        self.assertEqual(engine.state.players[guardian.player_id].damage, 2)
        give_dagger_to(engine, next(pid for pid, player in engine.state.players.items() if pid not in (guardian.player_id, ward) and not player.captured))
        attacker = engine.state.dagger_holder_id
        victim = next(pid for pid, player in engine.state.players.items() if pid not in (attacker, guardian.player_id, ward) and not player.captured)
        engine.apply(command(engine, "guardian-b5-attack", attacker, "attack", targetPlayerId=victim))
        events = answer_poll(engine, guardian.player_id)
        damage = next(event for event in events if event.event_type == "DamageApplied")
        self.assertEqual(damage.payload["source"], "intervention")
        self.assertEqual(damage.payload["targetPlayerId"], guardian.player_id)
        assert_ward_returned(self, events, guardian.player_id, ward)
        # the intervention wound force-reveals the rank on its way through
        self.assertIn("rank", engine.state.players[guardian.player_id].revealed)
        assert_ward_settled(self, engine, guardian.player_id, ward, "guardian-b6")

    def test_guardian_returns_sword_and_shield_on_mentalist_skill_damage(self):
        # B7 via the skill-damage source: the mentalist's wound is the third
        # point; with the guardian's rank already shown, the forced-rank text
        # falls back to the last plain marker, revealed with no window.
        engine, found = started_with_ranks(6, 6, 5)
        guardian = found[6]
        mentalist = found[5]
        ward = next(pid for pid in engine.state.players if pid not in (guardian.player_id, mentalist.player_id))
        arm_guardian_ward(engine, guardian.player_id, ward, "guardian-c")
        attack_wound(engine, guardian.player_id, "guardian-c2", reveal_token="marker-0")
        attack_wound(engine, mentalist.player_id, "mentalist-c", reveal_token="rank")
        self.assertEqual(engine.state.pending.kind, "skill")
        self.assertEqual(engine.state.pending.rank, 5)
        events = engine.apply(command(engine, "mentalist-c-skill", mentalist.player_id, "choose-skill", use=True, targetPlayerId=guardian.player_id))
        guardian_player = engine.state.players[guardian.player_id]
        self.assertEqual(
            [(event.event_type, event.payload) for event in events if event.event_type == "ClueRevealed"],
            [("ClueRevealed", {"playerId": guardian.player_id, "kind": "marker-1", "value": guardian_player.identity_markers[1]})],
        )
        assert_ward_returned(self, events, guardian.player_id, ward)
        assert_ward_settled(self, engine, guardian.player_id, ward, "guardian-c4")

    def test_guardian_returns_sword_and_shield_on_berserker_reaction_damage(self):
        # B7 via the reaction source: the guardian attacks the berserker and
        # the counter wound is the third point.
        engine, found = started_with_ranks(6, 6, 7)
        guardian = found[6]
        berserker = found[7]
        ward = next(pid for pid in engine.state.players if pid not in (guardian.player_id, berserker.player_id))
        arm_guardian_ward(engine, guardian.player_id, ward, "guardian-d")
        attack_wound(engine, guardian.player_id, "guardian-d2", reveal_token="marker-0")
        give_dagger_to(engine, guardian.player_id)
        engine.apply(command(engine, "guardian-d3-attack", guardian.player_id, "attack", targetPlayerId=berserker.player_id))
        answer_poll(engine)
        reveal_rank(engine, berserker.player_id, "guardian-d3-reveal")
        self.assertEqual(engine.state.pending.kind, "skill")
        self.assertEqual(engine.state.pending.rank, 7)
        events = engine.apply(command(engine, "guardian-d3-counter", berserker.player_id, "choose-skill", use=True))
        reaction = next(event for event in events if event.event_type == "DamageApplied")
        self.assertEqual(reaction.payload, {"targetPlayerId": guardian.player_id, "amount": 1, "source": "reaction", "triggerContext": None})
        assert_ward_returned(self, events, guardian.player_id, ward)
        assert_ward_settled(self, engine, guardian.player_id, ward, "guardian-d4")

    def test_mage_obscures_markers_and_grants_staff(self):
        engine, found = started_with_ranks(6, 8)
        owner = found[8]
        target = next(player for player in engine.state.players.values() if player.player_id != owner.player_id)
        target.revealed = {"marker-0"}
        target.revealed_values["marker-0"] = "rose"
        self.open_skill(engine, owner)
        events = engine.apply(command(engine, "mage", owner.player_id, "choose-skill", use=True, targetPlayerId=target.player_id))
        self.assertEqual(engine.state.players[target.player_id].resources["staff"], 1)
        self.assertEqual(engine.state.players[target.player_id].identity_markers, ["unknown", "unknown"])
        self.assertIn("IdentityMarkersObscured", [event.event_type for event in events])
        self.assertEqual(engine.state.players[target.player_id].revealed_values["marker-0"], "unknown")

    def test_mage_erasure_turns_unlit_wild_markers_into_plain_question_marks(self):
        # B9 (corpus ruling: 法杖把审判者 wild 标记变普通问号、自选色永久丧失,
        # kept deliberately as the families' answer to the inquisitor). With
        # both wild markers unlit, the erasure leaves plain question marks and
        # the next wound's reveal window offers them bare — the rose/beast/
        # question-mark colour window of issue 26 is gone for good.
        engine, found = started_with_ranks(7, "fleur-cross", 8)
        mage = found[8]
        inquisitor = found["fleur-cross"]
        self.assertEqual(engine.state.players[inquisitor.player_id].identity_markers, ["wild", "wild"])
        attack_wound(engine, mage.player_id, "mage-a", reveal_token="rank")
        self.assertEqual(engine.state.pending.rank, 8)
        events = engine.apply(command(engine, "mage-a-skill", mage.player_id, "choose-skill", use=True, targetPlayerId=inquisitor.player_id))
        obscured = next(event for event in events if event.event_type == "IdentityMarkersObscured")
        self.assertEqual(obscured.payload, {"playerId": inquisitor.player_id})
        granted = next(event for event in events if event.event_type == "ResourceGranted")
        self.assertEqual(granted.payload, {"playerId": inquisitor.player_id, "resource": "staff", "amount": 1})
        target = engine.state.players[inquisitor.player_id]
        self.assertEqual(target.identity_markers, ["unknown", "unknown"])
        self.assertEqual(target.resources["staff"], 1)
        # the next wound reveals a marker straight as the question mark: no
        # colour choice is offered and none is needed
        give_dagger_to(engine, next(pid for pid, player in engine.state.players.items() if pid not in (mage.player_id, inquisitor.player_id) and not player.captured))
        attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "inq-a-attack", attacker, "attack", targetPlayerId=inquisitor.player_id))
        answer_poll(engine)
        self.assertEqual(engine.state.pending.kind, "reveal")
        actions = legal_actions(engine.state, inquisitor.player_id)
        self.assertEqual(
            [action for action in actions if action.get("token") == "marker-0"],
            [{"type": "choose-reveal", "token": "marker-0"}],
        )
        self.assertEqual(
            [action for action in actions if action.get("token") == "marker-1"],
            [{"type": "choose-reveal", "token": "marker-1"}],
        )
        revealed_events = engine.apply(command(engine, "inq-a-reveal", inquisitor.player_id, "choose-reveal", token="marker-0"))
        revealed = next(event for event in revealed_events if event.event_type == "ClueRevealed")
        self.assertEqual(revealed.payload, {"playerId": inquisitor.player_id, "kind": "marker-0", "value": "unknown"})
        self.assertEqual(engine.state.players[inquisitor.player_id].revealed_values["marker-0"], "unknown")

    def test_mage_erasure_rewrites_a_public_wild_colour_to_the_question_mark(self):
        # B8 × B9 crossover: a wild marker already shown with a chosen colour
        # is public information the erasure rewrites — the token stays in the
        # revealed set, its public value becomes the question mark, and the
        # surviving wild marker loses the colour window too.
        engine, found = started_with_ranks(7, "fleur-cross", 8)
        mage = found[8]
        inquisitor = found["fleur-cross"]
        attack_wound(engine, inquisitor.player_id, "inq-b1", reveal_token="marker-0", color="rose")
        target = engine.state.players[inquisitor.player_id]
        self.assertEqual(target.revealed_values["marker-0"], "rose")
        self.assertEqual(target.damage, 1)
        attack_wound(engine, mage.player_id, "mage-b", reveal_token="rank")
        events = engine.apply(command(engine, "mage-b-skill", mage.player_id, "choose-skill", use=True, targetPlayerId=inquisitor.player_id))
        self.assertIn("IdentityMarkersObscured", [event.event_type for event in events])
        target = engine.state.players[inquisitor.player_id]
        self.assertEqual(target.identity_markers, ["unknown", "unknown"])
        self.assertIn("marker-0", target.revealed)
        self.assertEqual(target.revealed_values["marker-0"], "unknown")
        self.assertEqual(target.resources["staff"], 1)
        # the surviving wild marker reveals bare: the colour choice is gone
        give_dagger_to(engine, next(pid for pid, player in engine.state.players.items() if pid not in (mage.player_id, inquisitor.player_id) and not player.captured))
        attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "inq-b2-attack", attacker, "attack", targetPlayerId=inquisitor.player_id))
        answer_poll(engine)
        self.assertEqual(engine.state.pending.kind, "reveal")
        actions = legal_actions(engine.state, inquisitor.player_id)
        self.assertEqual(
            [action for action in actions if action.get("token") == "marker-1"],
            [{"type": "choose-reveal", "token": "marker-1"}],
        )
        revealed_events = engine.apply(command(engine, "inq-b2-reveal", inquisitor.player_id, "choose-reveal", token="marker-1"))
        revealed = next(event for event in revealed_events if event.event_type == "ClueRevealed")
        self.assertEqual(revealed.payload["value"], "unknown")
        self.assertEqual(engine.state.players[inquisitor.player_id].revealed_values["marker-1"], "unknown")

    def test_rank_shown_player_is_never_listed_as_intervention_volunteer(self):
        # C1/C2 machine note: the eligibility gate excludes rank-shown players
        # outright. Together with the property invariant "damage 3 always
        # shows the rank" this is what keeps "a 3-damage volunteer blocks for
        # the inquisitor's victim" (corpus C2) unreachable.
        engine = started(6)
        attacker = engine.state.dagger_holder_id
        shown = next(pid for pid in engine.state.players if pid != attacker)
        engine.apply(command(engine, "wound-shown", attacker, "attack", targetPlayerId=shown))
        answer_poll(engine)
        reveal_rank(engine, shown)
        engine.apply(command(engine, "no-skill", shown, "choose-skill", use=False))
        self.assertIn("rank", engine.state.players[shown].revealed)
        give_dagger_to(engine, next(pid for pid in engine.state.players if pid not in (attacker, shown)))
        second_attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid not in (second_attacker, shown))
        engine.apply(command(engine, "wound-second", second_attacker, "attack", targetPlayerId=target))
        pending = engine.state.pending
        self.assertIsNotNone(pending)
        self.assertNotIn(shown, pending.eligible_player_ids)
        # the gate is total: no legal action, not even a decline
        self.assertEqual(legal_actions(engine.state, shown), [])
        for pid in pending.eligible_player_ids:
            self.assertNotIn("rank", engine.state.players[pid].revealed)

    def test_courtesan_grants_fan_and_blocks_intervention(self):
        engine, found = started_with_ranks(6, 9)
        owner = found[9]
        target = next(player for player in engine.state.players.values() if player.player_id != owner.player_id)
        self.open_skill(engine, owner)
        engine.apply(command(engine, "courtesan", owner.player_id, "choose-skill", use=True, targetPlayerId=target.player_id))
        self.assertEqual(engine.state.players[target.player_id].resources["fan"], 1)

    def test_assassin_skill_deals_two_damage_opens_victim_choice_windows_and_hands_dagger(self):
        engine, found = started_with_ranks(6, 2)
        assassin = found[2]
        attacker = engine.state.dagger_holder_id
        if attacker == assassin.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != assassin.player_id))
            attacker = engine.state.dagger_holder_id
        victim = next(
            pid for pid, player in engine.state.players.items()
            if pid not in (attacker, assassin.player_id) and player.damage == 0
        )
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=assassin.player_id))
        answer_poll(engine)
        reveal_rank(engine, assassin.player_id)
        events = list(
            engine.apply(
                command(engine, "use", assassin.player_id, "choose-skill", use=True, targetPlayerId=victim)
            )
        )
        # ADR 0006: each of the two wounds opens a victim-choice reveal
        # window; the second point only applies after the first is answered.
        self.assertEqual(engine.state.players[victim].damage, 1)
        self.assertEqual(engine.state.pending.kind, "reveal")
        self.assertEqual(engine.state.pending.actor_player_id, victim)
        self.assertEqual(engine.state.pending.context["eligibleTokens"], ["marker-0", "marker-1", "rank"])
        self.assertFalse(engine.state.pending.context["forceRank"])
        self.assertEqual(
            [event.payload.get("eligibleTokens") for event in events if event.event_type == "RevealWindowOpened"],
            [["marker-0", "marker-1", "rank"]],
        )
        events += engine.apply(command(engine, "reveal-1", victim, "choose-reveal", token="marker-0"))
        self.assertEqual(engine.state.players[victim].damage, 2)
        self.assertEqual(engine.state.pending.kind, "reveal")
        events += engine.apply(command(engine, "reveal-2", victim, "choose-reveal", token="marker-1"))
        # the victim chose markers, so the rank stays hidden and no skill
        # window can open (its general trigger rule is re-judged by issue 02);
        # skill damage never creates an intervention either
        self.assertIsNone(engine.state.pending)
        self.assertNotIn("rank", engine.state.players[victim].revealed)
        self.assertEqual(engine.state.dagger_holder_id, victim)
        self.assertEqual(engine.state.phase, {"kind": "action", "activePlayerId": victim})
        event_types = [event.event_type for event in events]
        self.assertNotIn("InterventionPollOpened", event_types)
        self.assertNotIn("SkillWindowOpened", event_types)

    def test_assassin_victim_self_chosen_rank_reveal_opens_skill_window_and_defers_dagger(self):
        # ADR 0009 general rule: a rank newly revealed by skill damage opens
        # the victim's window (trigger=None); the rank-2 dagger handoff
        # (corpus B12) settles only after that window closes
        engine, found = started_with_ranks(6, 2, 1)
        assassin = found[2]
        victim = found[1]
        attacker = engine.state.dagger_holder_id
        if attacker in (assassin.player_id, victim.player_id):
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid not in (assassin.player_id, victim.player_id)))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=assassin.player_id))
        answer_poll(engine)
        reveal_rank(engine, assassin.player_id, "reveal-assassin")
        events = list(engine.apply(command(engine, "use", assassin.player_id, "choose-skill", use=True, targetPlayerId=victim.player_id)))
        # point 1: the victim self-chooses the rank; point 2: a marker
        events += engine.apply(command(engine, "reveal-victim-rank", victim.player_id, "choose-reveal", token="rank"))
        events += engine.apply(command(engine, "reveal-victim-marker", victim.player_id, "choose-reveal", token="marker-0"))
        self.assertEqual(engine.state.players[victim.player_id].damage, 2)
        self.assertEqual(engine.state.pending.kind, "skill")
        self.assertEqual(engine.state.pending.rank, 1)
        self.assertIsNone(engine.state.pending.trigger)
        self.assertIn("SkillWindowOpened", [event.event_type for event in events])
        # B12: the handoff to the victim is deferred until the window closes
        self.assertEqual(engine.state.dagger_holder_id, assassin.player_id)
        events += engine.apply(command(engine, "decline", victim.player_id, "choose-skill", use=False))
        self.assertEqual(engine.state.dagger_holder_id, victim.player_id)
        self.assertEqual(engine.state.phase, {"kind": "action", "activePlayerId": victim.player_id})
        self.assertIn("1", engine.state.players[victim.player_id].skills_used)

    def test_alchemist_harm_third_point_forced_rank_opens_victim_window(self):
        # ADR 0009: the harm wound's forced third-point rank reveal opens the
        # protected player's window (trigger=None); the alchemist keeps the dagger
        engine, found = started_with_ranks(6, 4, 1)
        alchemist = found[4]
        protected = found[1]
        mark_two_damage(engine, protected.player_id)
        attacker = engine.state.dagger_holder_id
        if attacker in (alchemist.player_id, protected.player_id):
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid not in (alchemist.player_id, protected.player_id)))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack-4", attacker, "attack", targetPlayerId=protected.player_id))
        answer_poll(engine, alchemist.player_id)
        reveal_rank(engine, alchemist.player_id, "reveal-alchemist")
        events = list(engine.apply(command(engine, "harm-4", alchemist.player_id, "choose-skill", use=True, mode="harm")))
        self.assertEqual(engine.state.players[protected.player_id].damage, 3)
        self.assertIn("rank", engine.state.players[protected.player_id].revealed)
        self.assertEqual(engine.state.pending.kind, "skill")
        self.assertEqual(engine.state.pending.rank, 1)
        self.assertIsNone(engine.state.pending.trigger)
        self.assertIn("SkillWindowOpened", [event.event_type for event in events])
        events += engine.apply(command(engine, "decline", protected.player_id, "choose-skill", use=False))
        self.assertIsNone(engine.state.pending)
        self.assertEqual(engine.state.dagger_holder_id, alchemist.player_id)

    def test_berserker_reaction_third_point_forced_rank_opens_attacker_window(self):
        # ADR 0009 B4: the counter wound's forced third-point rank reveal
        # opens the attacker's window (trigger=None reaction source); the
        # berserker keeps the dagger after the window closes
        engine, found = started_with_ranks(6, 7, 1)
        berserker = found[7]
        attacker = found[1]
        mark_two_damage(engine, attacker.player_id)
        give_dagger_to(engine, attacker.player_id)
        engine.apply(command(engine, "attack", attacker.player_id, "attack", targetPlayerId=berserker.player_id))
        answer_poll(engine)
        reveal_rank(engine, berserker.player_id)
        events = list(engine.apply(command(engine, "use-7", berserker.player_id, "choose-skill", use=True)))
        self.assertEqual(engine.state.players[attacker.player_id].damage, 3)
        self.assertIn("rank", engine.state.players[attacker.player_id].revealed)
        self.assertEqual(engine.state.pending.kind, "skill")
        self.assertEqual(engine.state.pending.rank, 1)
        self.assertIsNone(engine.state.pending.trigger)
        opened = next(event for event in events if event.event_type == "SkillWindowOpened")
        self.assertEqual(opened.payload, {"playerId": attacker.player_id, "rank": 1, "trigger": None})
        events += engine.apply(command(engine, "decline", attacker.player_id, "choose-skill", use=False))
        self.assertIsNone(engine.state.pending)
        self.assertEqual(engine.state.dagger_holder_id, berserker.player_id)

    def test_berserker_window_from_skill_damage_counters_the_skill_user(self):
        # the general rule opens the berserker's window from skill damage too;
        # rank 7 resolves against the context attacker (the skill user)
        engine, found = started_with_ranks(6, 2, 7)
        assassin = found[2]
        berserker = found[7]
        attacker = engine.state.dagger_holder_id
        if attacker in (assassin.player_id, berserker.player_id):
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid not in (assassin.player_id, berserker.player_id)))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=assassin.player_id))
        answer_poll(engine)
        reveal_rank(engine, assassin.player_id, "reveal-assassin")
        engine.apply(command(engine, "use", assassin.player_id, "choose-skill", use=True, targetPlayerId=berserker.player_id))
        # point 1: the berserker self-chooses the rank; point 2: a marker;
        # the chain then settles into the berserker's own window
        engine.apply(command(engine, "reveal-victim-rank", berserker.player_id, "choose-reveal", token="rank"))
        engine.apply(command(engine, "reveal-victim-marker", berserker.player_id, "choose-reveal", token="marker-0"))
        self.assertEqual(engine.state.pending.kind, "skill")
        self.assertEqual(engine.state.pending.rank, 7)
        self.assertIsNone(engine.state.pending.trigger)
        events = list(engine.apply(command(engine, "counter", berserker.player_id, "choose-skill", use=True)))
        counter = next(event for event in events if event.event_type == "DamageApplied")
        self.assertEqual(counter.payload, {"targetPlayerId": assassin.player_id, "amount": 1, "source": "reaction", "triggerContext": None})
        # the assassin answers the wound's victim-choice reveal; the berserker
        # (rank-2 handoff target) keeps the dagger through the counter
        engine.apply(command(engine, "reveal-counter", assassin.player_id, "choose-reveal", token="marker-0"))
        self.assertIsNone(engine.state.pending)
        self.assertEqual(engine.state.dagger_holder_id, berserker.player_id)

    def test_assassin_skill_scenario_log_is_identical_across_hash_seeds(self):
        # A2 regression: the assassin scenario must yield one identical log
        # under PYTHONHASHSEED=0..5 (ADR 0001 replay determinism)
        script = (
            "import json\n"
            "from tests.test_rule_branches import assassin_skill_scenario_log\n"
            "print(json.dumps(assassin_skill_scenario_log(), sort_keys=True))\n"
        )
        cwd = str(Path(__file__).resolve().parents[1])
        logs = []
        for hash_seed in range(6):
            env = dict(os.environ, PYTHONHASHSEED=str(hash_seed))
            completed = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                env=env,
                cwd=cwd,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            logs.append(completed.stdout)
        self.assertEqual(len(set(logs)), 1)
        # one window for the assassin's own attack wound plus one per skill point
        self.assertEqual(logs[0].count("RevealWindowOpened"), 3)

    def test_assassin_skill_cannot_target_self(self):
        engine, found = started_with_ranks(6, 2)
        assassin = found[2]
        attacker = engine.state.dagger_holder_id
        if attacker == assassin.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != assassin.player_id))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=assassin.player_id))
        answer_poll(engine)
        reveal_rank(engine, assassin.player_id)
        with self.assertRaises(RuleError) as error:
            engine.apply(
                command(engine, "use", assassin.player_id, "choose-skill", use=True, targetPlayerId=assassin.player_id)
            )
        self.assertEqual(error.exception.code, "skill.invalid-target")

    def test_skill_already_used_is_rejected(self):
        # unreachable through public commands until the alchemist returns a
        # revealed rank token (issue 14); inject the open window directly
        engine, found = started_with_ranks(6, 1)
        elder = found[1]
        elder.skills_used.add("1")
        engine.state.pending = Pending("skill", elder.player_id, elder.player_id, rank=1, trigger="attack")
        engine.state.phase = {"kind": "skill", "activePlayerId": elder.player_id}
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "reuse", elder.player_id, "choose-skill", use=True))
        self.assertEqual(error.exception.code, "skill.already-used")

    def test_skill_window_only_opens_once_per_rank_reveal(self):
        engine, found = started_with_ranks(6, 1)
        elder = found[1]
        attacker = engine.state.dagger_holder_id
        if attacker == elder.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != elder.player_id))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack-1", attacker, "attack", targetPlayerId=elder.player_id))
        answer_poll(engine)
        reveal_rank(engine, elder.player_id, "reveal-1")
        self.assertEqual(engine.state.pending.kind, "skill")
        engine.apply(command(engine, "skill-decline", elder.player_id, "choose-skill", use=False))
        # second resolved attack reveals affiliation, not rank: no new window
        give_dagger_to(engine, attacker)
        engine.apply(command(engine, "attack-2", attacker, "attack", targetPlayerId=elder.player_id))
        answer_poll(engine)
        if engine.state.pending and engine.state.pending.kind == "reveal":
            engine.apply(command(engine, "reveal-2", elder.player_id, "choose-reveal", token="marker-0"))
        self.assertIsNone(engine.state.pending)

    def test_assassin_skill_capture_leaves_ended_phase(self):
        engine, found = started_with_ranks(6, 2)
        assassin = found[2]
        victim = next(player for player in engine.state.players.values() if player.player_id != assassin.player_id)
        attacker = next(
            player for player in engine.state.players.values()
            if player.player_id not in (assassin.player_id, victim.player_id)
        )
        for _ in range(2):
            give_dagger_to(engine, attacker.player_id)
            engine.apply(command(engine, f"hit-{_}", attacker.player_id, "attack", targetPlayerId=victim.player_id))
            answer_poll(engine)
            reveal_rank(engine, victim.player_id, f"reveal-{_}")
            if engine.state.pending and engine.state.pending.kind == "reveal":
                engine.apply(command(engine, f"reveal-marker-{_}", victim.player_id, "choose-reveal", token="marker-0"))
            if engine.state.pending and engine.state.pending.kind == "skill":
                engine.apply(command(engine, f"no-skill-{_}", victim.player_id, "choose-skill", use=False))
        give_dagger_to(engine, attacker.player_id)
        engine.apply(command(engine, "attack-ass", attacker.player_id, "attack", targetPlayerId=assassin.player_id))
        answer_poll(engine)
        reveal_rank(engine, assassin.player_id, "reveal-ass")
        engine.apply(
            command(engine, "use-ass", assassin.player_id, "choose-skill", use=True, targetPlayerId=victim.player_id)
        )
        self.assertEqual(engine.state.status, "ended")
        self.assertEqual(engine.state.phase, {"kind": "ended"})
        self.assertNotEqual(engine.state.dagger_holder_id, victim.player_id)


def inquisitor_of(engine):
    return next(
        player for player in engine.state.players.values() if player.faction == "secret-order"
    )


def open_curse_window(engine, command_prefix="curse"):
    """Wound the inquisitor once and reveal their rank, opening the curse skill window."""
    inquisitor = inquisitor_of(engine)
    attacker = engine.state.dagger_holder_id
    if attacker == inquisitor.player_id:
        give_dagger_to(engine, next(pid for pid in engine.state.players if pid != inquisitor.player_id))
    engine.apply(command(engine, f"{command_prefix}-attack", engine.state.dagger_holder_id, "attack", targetPlayerId=inquisitor.player_id))
    answer_poll(engine)
    reveal_rank(engine, inquisitor.player_id, f"{command_prefix}-reveal")
    assert engine.state.pending and engine.state.pending.kind == "skill" and engine.state.pending.rank == "fleur-cross"
    return inquisitor


class CurseBranchTests(unittest.TestCase):
    """ADR 0003: curse distribution rides the reveal-triggered skill window."""

    def test_self_chosen_rank_reveal_opens_the_curse_window(self):
        engine = started(7)
        inquisitor = open_curse_window(engine)
        self.assertEqual(engine.state.pending.rank, "fleur-cross")
        self.assertEqual(engine.state.pending.trigger, "attack")
        self.assertEqual(engine.state.players[inquisitor.player_id].damage, 1)

    def test_third_damage_forced_rank_reveal_opens_the_curse_window(self):
        engine = started(7)
        inquisitor = inquisitor_of(engine)
        mark_two_damage(engine, inquisitor.player_id)
        give_dagger_to(engine, next(pid for pid in engine.state.players if pid != inquisitor.player_id))
        engine.apply(command(engine, "attack-3", engine.state.dagger_holder_id, "attack", targetPlayerId=inquisitor.player_id))
        answer_poll(engine)
        # the third wound force-reveals the rank without a reveal window
        self.assertEqual(engine.state.pending.kind, "skill")
        self.assertEqual(engine.state.pending.rank, "fleur-cross")

    def test_intervention_damage_opens_the_curse_window(self):
        engine = started(7)
        inquisitor = inquisitor_of(engine)
        attacker = engine.state.dagger_holder_id
        if attacker == inquisitor.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != inquisitor.player_id))
            attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid not in (attacker, inquisitor.player_id))
        engine.apply(command(engine, "attack-other", attacker, "attack", targetPlayerId=target))
        answer_poll(engine, inquisitor.player_id)
        reveal_rank(engine, inquisitor.player_id, "reveal-intervention")
        self.assertEqual(engine.state.pending.kind, "skill")
        self.assertEqual(engine.state.pending.rank, "fleur-cross")
        self.assertEqual(engine.state.pending.trigger, "intervention")

    def test_skill_damage_self_chosen_rank_reveal_opens_the_curse_window(self):
        engine, found = started_with_ranks(7, 2)
        assassin = found[2]
        inquisitor = inquisitor_of(engine)
        attacker = engine.state.dagger_holder_id
        if attacker == assassin.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != assassin.player_id))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack-assassin", attacker, "attack", targetPlayerId=assassin.player_id))
        answer_poll(engine)
        reveal_rank(engine, assassin.player_id, "reveal-assassin")
        self.assertEqual(engine.state.pending.rank, 2)
        events = list(
            engine.apply(command(engine, "use-assassin", assassin.player_id, "choose-skill", use=True, targetPlayerId=inquisitor.player_id))
        )
        # ADR 0006: skill wounds are the victim's choice; the inquisitor
        # self-chooses the rank for the first point and a wild marker for the
        # second. ADR 0009 (D1): the newly revealed fleur-cross then opens the
        # curse window like any other rank, with trigger None (skill source)
        self.assertEqual(engine.state.pending.kind, "reveal")
        self.assertEqual(engine.state.pending.actor_player_id, inquisitor.player_id)
        events += engine.apply(command(engine, "reveal-rank", inquisitor.player_id, "choose-reveal", token="rank"))
        self.assertIn("rank", engine.state.players[inquisitor.player_id].revealed)
        events += engine.apply(command(engine, "reveal-marker", inquisitor.player_id, "choose-reveal", token="marker-0", color="rose"))
        self.assertEqual(engine.state.pending.kind, "skill")
        self.assertEqual(engine.state.pending.rank, "fleur-cross")
        self.assertIsNone(engine.state.pending.trigger)
        opened = next(event for event in events if event.event_type == "SkillWindowOpened")
        self.assertEqual(opened.payload, {"playerId": inquisitor.player_id, "rank": "fleur-cross", "trigger": None})
        # the rank-2 dagger handoff waits for the window to close (B12)
        self.assertEqual(engine.state.dagger_holder_id, assassin.player_id)
        events += engine.apply(command(engine, "decline", inquisitor.player_id, "choose-skill", use=False))
        self.assertEqual(engine.state.dagger_holder_id, inquisitor.player_id)
        self.assertEqual(engine.state.curses, ["true-curse-1", "false-curse-1"])

    def test_mentalist_seal_kills_the_curse_path_and_heal_cannot_unseal(self):
        # ADR 0009 D1: sealing the inquisitor writes fleur-cross into
        # skills_used, so the curse win path is dead for good; returning the
        # rank token (alchemist heal) and re-revealing it never reopens the
        # window — the seal is not the alchemist's to undo
        engine, found = started_with_ranks(7, 4, 5)
        alchemist = found[4]
        mentalist = found[5]
        inquisitor = inquisitor_of(engine)
        attacker = engine.state.dagger_holder_id
        if attacker == mentalist.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != mentalist.player_id))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack-mentalist", attacker, "attack", targetPlayerId=mentalist.player_id))
        answer_poll(engine)
        reveal_rank(engine, mentalist.player_id, "reveal-mentalist")
        events = list(
            engine.apply(command(engine, "use-mentalist", mentalist.player_id, "choose-skill", use=True, targetPlayerId=inquisitor.player_id))
        )
        # forced reveal: sealed, no window, dagger already handed over
        self.assertIsNone(engine.state.pending)
        self.assertIn("fleur-cross", engine.state.players[inquisitor.player_id].skills_used)
        self.assertIn("rank", engine.state.players[inquisitor.player_id].revealed)
        self.assertNotIn("SkillWindowOpened", [event.event_type for event in events])
        self.assertEqual(engine.state.dagger_holder_id, inquisitor.player_id)
        # the alchemist blocks a later attack on the inquisitor and heals the
        # sealed rank token back
        give_dagger_to(engine, next(pid for pid in engine.state.players if pid not in (alchemist.player_id, inquisitor.player_id)))
        engine.apply(command(engine, "attack-heal", engine.state.dagger_holder_id, "attack", targetPlayerId=inquisitor.player_id))
        answer_poll(engine, alchemist.player_id)
        reveal_rank(engine, alchemist.player_id, "reveal-alchemist")
        self.assertEqual(engine.state.pending.rank, 4)
        engine.apply(command(engine, "heal", alchemist.player_id, "choose-skill", use=True, mode="heal"))
        self.assertEqual(engine.state.pending.kind, "token-return")
        engine.apply(command(engine, "return-rank", inquisitor.player_id, "choose-return", token="rank"))
        self.assertNotIn("rank", engine.state.players[inquisitor.player_id].revealed)
        self.assertEqual(engine.state.players[inquisitor.player_id].damage, 0)
        # the seal survives the heal: skills_used still holds fleur-cross
        self.assertIn("fleur-cross", engine.state.players[inquisitor.player_id].skills_used)
        # two marker wounds bring the inquisitor to the forced third point
        for index in range(2):
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid not in (inquisitor.player_id,)))
            engine.apply(command(engine, f"wound-{index}", engine.state.dagger_holder_id, "attack", targetPlayerId=inquisitor.player_id))
            answer_poll(engine)
            engine.apply(command(engine, f"reveal-marker-{index}", inquisitor.player_id, "choose-reveal", token=f"marker-{index}", color="rose"))
        self.assertEqual(engine.state.players[inquisitor.player_id].damage, 2)
        give_dagger_to(engine, next(pid for pid in engine.state.players if pid not in (inquisitor.player_id,)))
        events = list(engine.apply(command(engine, "wound-rank", engine.state.dagger_holder_id, "attack", targetPlayerId=inquisitor.player_id)))
        # the poll resolution carries the forced rank reveal and its shut window
        events += answer_poll(engine)
        # the third point force-reveals fleur-cross again; the seal keeps the
        # window shut and the curses stay undistributable for the rest of the game
        self.assertEqual(engine.state.players[inquisitor.player_id].damage, 3)
        self.assertIn("rank", engine.state.players[inquisitor.player_id].revealed)
        self.assertIsNone(engine.state.pending)
        self.assertNotIn("SkillWindowOpened", [event.event_type for event in events])
        self.assertEqual(engine.state.curses, ["true-curse-1", "false-curse-1"])

    def test_decline_keeps_curses_in_supply_and_closes_the_window_for_good(self):
        engine = started(7)
        inquisitor = open_curse_window(engine)
        events = engine.apply(command(engine, "decline", inquisitor.player_id, "choose-skill", use=False))
        self.assertEqual([event.event_type for event in events], ["SkillDeclined", "PhaseChanged"])
        self.assertIn("fleur-cross", engine.state.players[inquisitor.player_id].skills_used)
        self.assertEqual(engine.state.curses, ["true-curse-1", "false-curse-1"])
        self.assertEqual(engine.state.curse_assignments, {})
        # a later wound reveals affiliation only: the window never reopens
        give_dagger_to(engine, next(pid for pid in engine.state.players if pid != inquisitor.player_id))
        engine.apply(command(engine, "attack-again", engine.state.dagger_holder_id, "attack", targetPlayerId=inquisitor.player_id))
        answer_poll(engine)
        if engine.state.pending and engine.state.pending.kind == "reveal":
            # the inquisitor's markers are wild, so revealing one needs a colour
            engine.apply(command(engine, "reveal-again", inquisitor.player_id, "choose-reveal", token="marker-0", color="rose"))
        self.assertIsNone(engine.state.pending)

    def test_distribute_then_decline_is_rejected_as_window_closed(self):
        engine = started(7)
        inquisitor = open_curse_window(engine)
        recipients = [pid for pid in sorted(engine.state.players) if pid != inquisitor.player_id]
        assignments = {"true-curse-1": recipients[0], "false-curse-1": recipients[1]}
        engine.apply(command(engine, "use", inquisitor.player_id, "choose-skill", use=True, assignments=assignments))
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "decline", inquisitor.player_id, "choose-skill", use=False))
        self.assertEqual(error.exception.code, "skill.not-open")

    def test_standalone_distribute_curse_command_is_gone(self):
        engine = started(7)
        inquisitor = inquisitor_of(engine)
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "curse", inquisitor.player_id, "distribute-curse", assignments={"true-curse-1": "p0", "false-curse-1": "p1"}))
        self.assertEqual(error.exception.code, "command.unknown")

    def test_distribute_with_no_curses_is_rejected(self):
        engine = started(7)
        inquisitor = open_curse_window(engine)
        engine.state.curses = []  # synthetic: curses already gone (multi-inquisitor games are out of scope)
        recipients = [pid for pid in sorted(engine.state.players) if pid != inquisitor.player_id]
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "use", inquisitor.player_id, "choose-skill", use=True, assignments={"true-curse-1": recipients[0], "false-curse-1": recipients[1]}))
        self.assertEqual(error.exception.code, "curse.invalid-count")

    def test_distribute_by_non_inquisitor_is_rejected(self):
        engine = started(7)
        other = next(player for player in engine.state.players.values() if player.faction != "secret-order")
        engine.state.pending = Pending("skill", other.player_id, other.player_id, rank="fleur-cross", trigger="attack")
        engine.state.phase = {"kind": "skill", "activePlayerId": other.player_id}
        victims = [pid for pid in sorted(engine.state.players) if pid != other.player_id]
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "use", other.player_id, "choose-skill", use=True, assignments={"true-curse-1": victims[0], "false-curse-1": victims[1]}))
        self.assertEqual(error.exception.code, "player.not-eligible")

    def test_distribute_with_wrong_assignment_keys_is_rejected(self):
        engine = started(7)
        inquisitor = open_curse_window(engine)
        recipients = [pid for pid in sorted(engine.state.players) if pid != inquisitor.player_id]
        for assignments in ({"true-curse-1": recipients[0]}, ["p0"], {}):
            with self.subTest(assignments=assignments):
                with self.assertRaises(RuleError) as error:
                    engine.apply(command(engine, "use", inquisitor.player_id, "choose-skill", use=True, assignments=assignments))
                self.assertEqual(error.exception.code, "curse.invalid-count")

    def test_distribute_to_unknown_or_captured_recipient_is_rejected(self):
        engine = started(7)
        inquisitor = open_curse_window(engine)
        victims = [pid for pid in sorted(engine.state.players) if pid != inquisitor.player_id]
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "use", inquisitor.player_id, "choose-skill", use=True, assignments={"true-curse-1": "ghost", "false-curse-1": victims[0]}))
        self.assertEqual(error.exception.code, "target.not-found")
        engine.state.players[victims[0]].captured = True  # synthetic: captures end games, so this never occurs live
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "use-captured", inquisitor.player_id, "choose-skill", use=True, assignments={"true-curse-1": victims[0], "false-curse-1": victims[1]}))
        self.assertEqual(error.exception.code, "target.captured")

    def test_distribute_duplicate_recipient_is_rejected(self):
        engine = started(7)
        inquisitor = open_curse_window(engine)
        victim = next(pid for pid in sorted(engine.state.players) if pid != inquisitor.player_id)
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "use", inquisitor.player_id, "choose-skill", use=True, assignments={"true-curse-1": victim, "false-curse-1": victim}))
        self.assertEqual(error.exception.code, "curse.duplicate-recipient")

    def test_repeated_use_in_a_reopened_window_is_rejected(self):
        engine = started(7)
        inquisitor = open_curse_window(engine)
        engine.state.players[inquisitor.player_id].skills_used.add("fleur-cross")  # synthetic: declined earlier
        victims = [pid for pid in sorted(engine.state.players) if pid != inquisitor.player_id]
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "use", inquisitor.player_id, "choose-skill", use=True, assignments={"true-curse-1": victims[0], "false-curse-1": victims[1]}))
        self.assertEqual(error.exception.code, "skill.already-used")

    def test_distribute_does_not_disturb_dagger_or_open_new_windows(self):
        engine = started(7)
        inquisitor = open_curse_window(engine)
        holder = engine.state.dagger_holder_id
        victims = [pid for pid in sorted(engine.state.players) if pid != inquisitor.player_id]
        events = engine.apply(command(engine, "use", inquisitor.player_id, "choose-skill", use=True, assignments={"true-curse-1": victims[0], "false-curse-1": victims[1]}))
        self.assertEqual([event.event_type for event in events], ["SkillUsed", "CurseDistributed", "CurseDistributed", "PhaseChanged"])
        self.assertEqual(engine.state.dagger_holder_id, holder)
        self.assertEqual(engine.state.phase, {"kind": "action", "activePlayerId": holder})
        self.assertIsNone(engine.state.pending)
        self.assertEqual(engine.state.curses, [])
        self.assertEqual(
            engine.state.curse_assignments,
            {"true-curse-1": victims[0], "false-curse-1": victims[1]},
        )

    def test_declined_curse_never_judges_a_family_win(self):
        engine = started(7)
        inquisitor = open_curse_window(engine)
        engine.apply(command(engine, "decline", inquisitor.player_id, "choose-skill", use=False))
        victim = min(
            (player for player in engine.state.players.values() if player.faction == "rose"),
            key=lambda player: player.rank,
        )
        attacker = next(player for player in engine.state.players.values() if player.faction == "beast")
        mark_three_damage(engine, victim.player_id)
        give_dagger_to(engine, attacker.player_id)
        engine.apply(command(engine, "attack-leader", attacker.player_id, "attack", targetPlayerId=victim.player_id))
        answer_poll(engine)
        self.assertEqual(engine.state.result["branch"], "captured-leader")
        self.assertEqual(engine.state.result["winner"], attacker.faction)

    def test_winning_leader_holding_true_curse_gives_the_inquisitor_a_solo_win(self):
        engine = started(7)
        inquisitor = open_curse_window(engine)
        rose_players = sorted(
            (player for player in engine.state.players.values() if player.faction == "rose"),
            key=lambda player: player.rank,
        )
        leader, highest_rose = rose_players[0], rose_players[-1]
        victims = [pid for pid in sorted(engine.state.players) if pid != inquisitor.player_id]
        assignments = {"true-curse-1": leader.player_id, "false-curse-1": victims[0] if victims[0] != leader.player_id else victims[1]}
        engine.apply(command(engine, "use", inquisitor.player_id, "choose-skill", use=True, assignments=assignments))
        # a beast attacker captures the highest-ranked rose player: a non-leader
        # capture, so the rose family wins normally before the curse overrides
        beast = next(player for player in engine.state.players.values() if player.faction == "beast")
        mark_three_damage(engine, highest_rose.player_id)
        give_dagger_to(engine, beast.player_id)
        engine.apply(command(engine, "attack-rose", beast.player_id, "attack", targetPlayerId=highest_rose.player_id))
        answer_poll(engine)
        self.assertEqual(engine.state.status, "ended")
        self.assertEqual(engine.state.result["branch"], "inquisitor-true-curse")
        self.assertEqual(engine.state.result["winner"], "secret-order")


class EndGameBranchTests(unittest.TestCase):
    def test_captured_leader_branch(self):
        engine = started()
        victim = min(
            (player for player in engine.state.players.values() if player.faction == "rose"),
            key=lambda player: player.rank,
        )
        attacker = next(player for player in engine.state.players.values() if player.faction == "beast")
        mark_three_damage(engine, victim.player_id)
        give_dagger_to(engine, attacker.player_id)
        engine.apply(command(engine, "attack", attacker.player_id, "attack", targetPlayerId=victim.player_id))
        answer_poll(engine)
        self.assertEqual(engine.state.status, "ended")
        self.assertEqual(engine.state.result["branch"], "captured-leader")
        self.assertEqual(engine.state.result["winner"], attacker.faction)

    def test_captured_non_leader_branch(self):
        engine = started()
        rose_players = [player for player in engine.state.players.values() if player.faction == "rose"]
        leader_rank = min(player.rank for player in rose_players)
        victim = next(player for player in rose_players if player.rank != leader_rank)
        attacker = next(player for player in engine.state.players.values() if player.faction == "beast")
        mark_three_damage(engine, victim.player_id)
        give_dagger_to(engine, attacker.player_id)
        engine.apply(command(engine, "attack", attacker.player_id, "attack", targetPlayerId=victim.player_id))
        answer_poll(engine)
        self.assertEqual(engine.state.status, "ended")
        self.assertEqual(engine.state.result["branch"], "captured-player")
        # capturing a non-leader makes the attacker's clan lose
        self.assertEqual(engine.state.result["winner"], "rose")

    def test_inquisitor_captured_gives_the_inquisitor_a_solo_win(self):
        # ADR 0007: capturing the inquisitor is the inquisitor's solo win,
        # not a draw; the true-curse override never applies here because it
        # only rewrites rose/beast winners.
        engine = started(7)
        inquisitor = next(
            player for player in engine.state.players.values() if player.faction == "secret-order"
        )
        attacker = next(player for player in engine.state.players.values() if player.faction != "secret-order")
        mark_three_damage(engine, inquisitor.player_id)
        give_dagger_to(engine, attacker.player_id)
        engine.apply(command(engine, "attack", attacker.player_id, "attack", targetPlayerId=inquisitor.player_id))
        answer_poll(engine)
        self.assertEqual(engine.state.status, "ended")
        self.assertEqual(engine.state.result["branch"], "inquisitor-captured")
        self.assertEqual(engine.state.result["winner"], "secret-order")

    def test_inquisitor_active_capture_branch(self):
        # reachable once the alchemist can return a revealed rank token
        # (issue 14); the responder keeps 3 damage with an unrevealed rank
        engine = started(7)
        inquisitor = next(
            player for player in engine.state.players.values() if player.faction == "secret-order"
        )
        responder = next(player for player in engine.state.players.values() if player.faction != "secret-order")
        responder.damage = 3  # rank token returned: still unrevealed and eligible
        target = next(
            player for player in engine.state.players.values()
            if player.faction != "secret-order" and player.player_id != responder.player_id
        )
        give_dagger_to(engine, inquisitor.player_id)
        engine.apply(command(engine, "attack", inquisitor.player_id, "attack", targetPlayerId=target.player_id))
        answer_poll(engine, responder.player_id)
        self.assertEqual(engine.state.status, "ended")
        self.assertEqual(engine.state.result["branch"], "inquisitor-active-capture")
        expected_winner = "rose" if responder.faction == "beast" else "beast"
        self.assertEqual(engine.state.result["winner"], expected_winner)


class ProjectionBranchTests(unittest.TestCase):
    def test_legal_actions_empty_for_unknown_player_and_ended_game(self):
        engine, _ = run_deterministic_game(6, game_id="proj", seed="proj-seed")
        self.assertEqual(legal_actions(engine.state, "p0"), [])
        self.assertEqual(legal_actions(engine.state, "ghost"), [])

    def test_elder_skill_window_offers_use_without_a_target(self):
        engine, found = started_with_ranks(6, 1)
        elder = found[1]
        attacker = engine.state.dagger_holder_id
        if attacker == elder.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != elder.player_id))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=elder.player_id))
        answer_poll(engine)
        reveal_rank(engine, elder.player_id)
        actions = legal_actions(engine.state, elder.player_id)
        self.assertEqual(
            actions,
            [{"type": "choose-skill", "use": False}, {"type": "choose-skill", "use": True}],
        )
        # only the pending actor is offered anything
        self.assertEqual(legal_actions(engine.state, attacker), [])

    def test_wild_marker_colour_window_offers_the_question_mark(self):
        # Issue 26: the inquisitor's wild colour window carries a third option
        # — the question mark, which leans to neither faction — and choosing it
        # records the neutral value on the revealed marker.
        engine, found = started_with_ranks(7, "fleur-cross")
        inquisitor = found["fleur-cross"]
        attacker = engine.state.dagger_holder_id
        if attacker == inquisitor.player_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != inquisitor.player_id))
            attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=inquisitor.player_id))
        answer_poll(engine)
        actions = legal_actions(engine.state, inquisitor.player_id)
        self.assertEqual(
            [action.get("color") for action in actions if action["type"] == "choose-reveal" and action["token"] == "marker-0"],
            ["rose", "beast", "unknown"],
        )
        events = engine.apply(
            command(engine, "reveal-question", inquisitor.player_id, "choose-reveal", token="marker-0", color="unknown")
        )
        revealed = next(event for event in events if event.event_type == "ClueRevealed")
        self.assertEqual(revealed.payload["value"], "unknown")
        self.assertEqual(engine.state.players[inquisitor.player_id].revealed_values["marker-0"], "unknown")
        # the plain token action stays bare: no colour choice on a rank reveal
        self.assertNotIn("color", next(action for action in actions if action["token"] == "rank"))

    def test_pending_intervention_actions_across_gate_poll_and_choice_stages(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        eligible = list(engine.state.pending.eligible_player_ids)
        # gate stage: the answer actions belong to the target alone; the
        # attacker, the eligibles and every other bystander hold nothing
        self.assertEqual(
            legal_actions(engine.state, target),
            [
                {"type": "answer-intervention-request", "need": True},
                {"type": "answer-intervention-request", "need": False},
            ],
        )
        for watcher in (attacker, eligible[0], eligible[1]):
            self.assertEqual(legal_actions(engine.state, watcher), [])
        engine.apply(command(engine, "gate-yes", target, "answer-intervention-request", need=True))
        # poll stage: each unanswered eligible player holds their own respond
        # actions; the target and the attacker hold nothing
        self.assertEqual(
            legal_actions(engine.state, eligible[0]),
            [
                {"type": "respond-intervention", "volunteer": True},
                {"type": "respond-intervention", "volunteer": False},
            ],
        )
        self.assertEqual(legal_actions(engine.state, target), [])
        self.assertEqual(legal_actions(engine.state, attacker), [])
        # after answering, the responder's actions are gone (no take-backs)
        engine.apply(command(engine, "first", eligible[0], "respond-intervention", volunteer=True))
        self.assertEqual(legal_actions(engine.state, eligible[0]), [])
        self.assertEqual(
            legal_actions(engine.state, eligible[1]),
            [
                {"type": "respond-intervention", "volunteer": True},
                {"type": "respond-intervention", "volunteer": False},
            ],
        )
        # two volunteers move the window to the target's choice stage
        engine.apply(command(engine, "second", eligible[1], "respond-intervention", volunteer=True))
        for player_id in eligible[2:]:
            engine.apply(command(engine, f"rest-{player_id}", player_id, "respond-intervention", volunteer=False))
        self.assertEqual(engine.state.pending.context["stage"], "choice")
        actions = legal_actions(engine.state, target)
        self.assertEqual(actions[0], {"type": "decline-intervention"})
        self.assertEqual(
            {action["responderPlayerId"] for action in actions[1:]},
            {eligible[0], eligible[1]},
        )
        # only the target chooses; volunteers and bystanders wait
        self.assertEqual(legal_actions(engine.state, eligible[0]), [])
        self.assertEqual(legal_actions(engine.state, eligible[2]), [])

    def test_pending_view_hides_private_context_and_publishes_votes(self):
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        # during the gate the vote fields do not exist yet (ADR 0012)
        gate_view = project_state(engine.state, target)
        self.assertEqual(gate_view["pending"]["stage"], "gate")
        self.assertNotIn("responses", gate_view["pending"])
        self.assertNotIn("volunteerPlayerIds", gate_view["pending"])
        engine.apply(command(engine, "gate-yes", target, "answer-intervention-request", need=True))
        eligible = list(engine.state.pending.eligible_player_ids)
        engine.apply(command(engine, "yes", eligible[0], "respond-intervention", volunteer=True))
        view = project_state(engine.state, target)
        self.assertNotIn("context", view["pending"])
        # stage, live votes, and the shared countdown deadline are public
        self.assertEqual(view["pending"]["stage"], "poll")
        self.assertEqual(view["pending"]["responses"], {eligible[0]: True})
        self.assertEqual(view["pending"]["volunteerPlayerIds"], [eligible[0]])
        # spectators see the same public vote state
        spectator = project_state(engine.state, None)
        self.assertEqual(spectator["pending"]["responses"], {eligible[0]: True})


class InterventionGateBranchTests(unittest.TestCase):
    """The target's request gate before the volunteer poll (ADR 0012)."""

    def attack(self, engine):
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        events = engine.apply(command(engine, "attack-1", attacker, "attack", targetPlayerId=target))
        return events, attacker, target

    def test_gate_opens_with_target_as_actor_and_the_eligible_list(self):
        engine = started()
        events, attacker, target = self.attack(engine)
        self.assertEqual(events[0].event_type, "AttackDeclared")
        self.assertEqual(events[1].event_type, "InterventionGateOpened")
        pending = engine.state.pending
        self.assertEqual(
            events[1].payload,
            {"targetPlayerId": target, "attackerPlayerId": attacker, "eligiblePlayerIds": list(pending.eligible_player_ids)},
        )
        # the poll is not open yet: only the confirmation window stands
        self.assertNotIn("InterventionPollOpened", [event.event_type for event in events])
        # the dagger still moves to the target at declaration time
        self.assertEqual(engine.state.dagger_holder_id, target)
        self.assertEqual(engine.state.phase, {"kind": "intervention", "stage": "gate", "activePlayerId": target})
        self.assertEqual(pending.kind, "intervention")
        self.assertEqual(pending.actor_player_id, target)
        self.assertEqual(pending.target_player_id, target)
        self.assertEqual(pending.context["attackerPlayerId"], attacker)
        self.assertEqual(pending.context["stage"], "gate")
        self.assertNotIn("responses", pending.context)
        # eligibility conditions are unchanged: attacker, target, rank-shown
        # and captured players are never on the list
        self.assertNotIn(attacker, pending.eligible_player_ids)
        self.assertNotIn(target, pending.eligible_player_ids)
        self.assertEqual(
            set(pending.eligible_player_ids),
            {pid for pid in engine.state.players if pid not in (attacker, target)},
        )

    def test_empty_eligible_set_skips_the_gate_with_zero_gate_events(self):
        # a fan-holding target makes the eligible set empty (rank 9, injected
        # directly): the 0.5 short-circuit moves ahead of the gate — no
        # confirmation window, no gate events, the attack settles at once
        engine = started()
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.state.players[target].resources["fan"] = 1
        events = engine.apply(command(engine, "attack", attacker, "attack", targetPlayerId=target))
        self.assertNotIn("InterventionGateOpened", [event.event_type for event in events])
        self.assertNotIn("InterventionPollOpened", [event.event_type for event in events])
        self.assertIn("DamageApplied", [event.event_type for event in events])
        self.assertEqual(engine.state.players[target].damage, 1)
        self.assertEqual(engine.state.pending.kind, "reveal")

    def test_gate_accept_relays_into_the_unchanged_poll(self):
        engine = started()
        _, attacker, target = self.attack(engine)
        eligible = list(engine.state.pending.eligible_player_ids)
        events = engine.apply(command(engine, "gate-yes", target, "answer-intervention-request", need=True))
        self.assertEqual(events[0].event_type, "InterventionGateAccepted")
        self.assertEqual(events[0].payload, {"targetPlayerId": target})
        self.assertEqual(events[1].event_type, "InterventionPollOpened")
        # the poll opens with exactly the fields it always had
        self.assertEqual(
            events[1].payload,
            {"targetPlayerId": target, "attackerPlayerId": attacker, "eligiblePlayerIds": eligible},
        )
        pending = engine.state.pending
        self.assertEqual(pending.context["stage"], "poll")
        self.assertEqual(pending.context["responses"], {})
        self.assertEqual(pending.eligible_player_ids, tuple(eligible))
        self.assertEqual(pending.actor_player_id, target)
        self.assertEqual(engine.state.phase, {"kind": "intervention", "stage": "poll", "activePlayerId": target})

    def test_gate_decline_settles_the_attack_on_the_target(self):
        engine = started()
        _, attacker, target = self.attack(engine)
        events = engine.apply(command(engine, "gate-no", target, "answer-intervention-request", need=False))
        declined = next(event for event in events if event.event_type == "InterventionGateDeclined")
        self.assertEqual(declined.payload, {"targetPlayerId": target, "reason": "target-declined"})
        # the gate decline replaces the poll-decline event: nobody was polled
        self.assertNotIn("InterventionDeclined", [event.event_type for event in events])
        damage = next(event for event in events if event.event_type == "DamageApplied")
        self.assertEqual(damage.payload["targetPlayerId"], target)
        self.assertEqual(damage.payload["source"], "attack")
        # the settlement drives the usual wound windows and dagger hand-off
        self.assertEqual(engine.state.players[target].damage, 1)
        self.assertEqual(engine.state.pending.kind, "reveal")
        engine.apply(command(engine, "reveal", target, "choose-reveal", token="marker-0"))
        self.assertEqual(engine.state.dagger_holder_id, target)
        self.assertEqual(engine.state.phase, {"kind": "action", "activePlayerId": target})

    def test_only_the_target_may_answer_the_gate(self):
        engine = started()
        _, attacker, target = self.attack(engine)
        bystander = next(pid for pid in engine.state.pending.eligible_player_ids)
        for actor in (attacker, bystander):
            with self.subTest(actor=actor):
                with self.assertRaises(RuleError) as error:
                    engine.apply(command(engine, f"wrong-{actor}", actor, "answer-intervention-request", need=True))
                self.assertEqual(error.exception.code, "intervention.not-target")
        # the window is still armed and untouched after the rejections
        self.assertEqual(engine.state.pending.context["stage"], "gate")

    def test_answer_outside_the_gate_stage_is_rejected(self):
        engine = started()
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "nothing", "p0", "answer-intervention-request", need=True))
        self.assertEqual(error.exception.code, "intervention.not-open")
        _, _, target = self.attack(engine)
        engine.apply(command(engine, "gate-yes", target, "answer-intervention-request", need=True))
        # once the poll stage took over, the answer command is stage-locked out
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "again", target, "answer-intervention-request", need=False))
        self.assertEqual(error.exception.code, "intervention.not-gate")

    def test_other_commands_are_rejected_while_the_gate_is_pending(self):
        engine = started()
        _, attacker, target = self.attack(engine)
        responder = next(pid for pid in engine.state.pending.eligible_player_ids)
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "early-respond", responder, "respond-intervention", volunteer=True))
        self.assertEqual(error.exception.code, "intervention.not-poll")
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "early-choose", target, "choose-intervention", responderPlayerId=responder))
        self.assertEqual(error.exception.code, "intervention.not-choice")
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "early-decline", target, "decline-intervention"))
        self.assertEqual(error.exception.code, "intervention.not-choice")
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "rush", attacker, "pass-dagger", targetPlayerId=target))
        self.assertEqual(error.exception.code, "game.not-active")

    def test_gate_timeout_declines_and_settles_the_attack(self):
        # Q1:A — an unanswered gate counts as "no assistance needed": the
        # timeout emits GateDeclined(timeout) and the attack settles
        engine = started()
        _, attacker, target = self.attack(engine)
        events = engine.apply(command(engine, "timeout", None, "timeout-intervention", stage="gate"))
        declined = next(event for event in events if event.event_type == "InterventionGateDeclined")
        self.assertEqual(declined.payload, {"targetPlayerId": target, "reason": "timeout"})
        self.assertNotIn("InterventionDeclined", [event.event_type for event in events])
        self.assertIn("DamageApplied", [event.event_type for event in events])
        self.assertEqual(engine.state.players[target].damage, 1)
        self.assertEqual(engine.state.pending.kind, "reveal")

    def test_gate_timeout_payload_stage_must_match_the_armed_window(self):
        engine = started()
        _, _, _target = self.attack(engine)
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "wrong-stage", None, "timeout-intervention", stage="poll"))
        self.assertEqual(error.exception.code, "intervention.not-open")


class InterventionPollBranchTests(unittest.TestCase):
    """The volunteer poll model (issue 23 / ADR 0002)."""

    def started_with_timeout(self, seconds, count=6, seed="poll-seed"):
        engine = RulesEngine.new_game("poll-game", seed, clock=FixedClock())
        for index in range(count):
            engine.apply(command(engine, f"join-{index}", None, "join-game", playerId=f"p{index}", displayName=f"P{index}"))
        engine.apply(command(engine, "start", None, "start-game", interventionTimeoutSeconds=seconds))
        return engine

    def attack(self, engine):
        """Open a poll-window test baseline: attack, then accept the gate."""
        attacker = engine.state.dagger_holder_id
        target = next(pid for pid in engine.state.players if pid != attacker)
        engine.apply(command(engine, "attack-1", attacker, "attack", targetPlayerId=target))
        engine.apply(command(engine, "gate-accept-1", target, "answer-intervention-request", need=True))
        return attacker, target

    def test_host_timeout_configuration_is_fixed_at_start(self):
        engine = self.started_with_timeout(30)
        self.assertEqual(engine.state.intervention_timeout_seconds, 30)
        started_event = next(event for event in engine.state.events if event.event_type == "GameStarted")
        self.assertEqual(started_event.payload["interventionTimeoutSeconds"], 30)
        _, target = self.attack(engine)

    def test_default_timeout_is_ninety_seconds(self):
        engine = started()
        self.assertEqual(engine.state.intervention_timeout_seconds, 90)

    def test_invalid_timeout_choice_is_rejected(self):
        engine = RulesEngine.new_game("poll-game", "poll-seed", clock=FixedClock())
        for index in range(6):
            engine.apply(command(engine, f"join-{index}", None, "join-game", playerId=f"p{index}", displayName=f"P{index}"))
        for bad in (0, 45, "90", True):
            with self.subTest(bad=bad):
                with self.assertRaises(RuleError) as error:
                    engine.apply(command(engine, f"start-{bad}", None, "start-game", interventionTimeoutSeconds=bad))
                self.assertEqual(error.exception.code, "game.invalid-timeout")
        engine.apply(command(engine, "start-ok", None, "start-game"))

    def test_poll_timeout_with_no_volunteers_resolves_the_attack(self):
        engine = started()
        attacker, target = self.attack(engine)
        pending = engine.state.pending
        responder = pending.eligible_player_ids[0]
        engine.apply(command(engine, "one-no", responder, "respond-intervention", volunteer=False))
        events = engine.apply(command(engine, "timeout", None, "timeout-intervention", stage="poll"))
        declined = next(event for event in events if event.event_type == "InterventionDeclined")
        self.assertEqual(declined.payload["reason"], "no-volunteers")
        # the timeout treated every silent player as declining to volunteer
        self.assertEqual(engine.state.pending.kind, "reveal")

    def test_poll_timeout_keeps_a_single_volunteer_forced(self):
        engine = started()
        attacker, target = self.attack(engine)
        responder = engine.state.pending.eligible_player_ids[0]
        engine.apply(command(engine, "one-yes", responder, "respond-intervention", volunteer=True))
        events = engine.apply(command(engine, "timeout", None, "timeout-intervention", stage="poll"))
        self.assertIn("InterventionSelected", [event.event_type for event in events])
        self.assertEqual(engine.state.players[responder].damage, 1)
        self.assertEqual(engine.state.players[target].damage, 0)

    def test_poll_timeout_with_two_volunteers_opens_the_choice_stage(self):
        engine = self.started_with_timeout(120)
        attacker, target = self.attack(engine)
        eligible = engine.state.pending.eligible_player_ids
        engine.apply(command(engine, "yes-0", eligible[0], "respond-intervention", volunteer=True))
        engine.apply(command(engine, "yes-1", eligible[1], "respond-intervention", volunteer=True))
        events = engine.apply(command(engine, "timeout", None, "timeout-intervention", stage="poll"))
        opened = next(event for event in events if event.event_type == "InterventionChoiceOpened")
        self.assertEqual(opened.payload["volunteerPlayerIds"], [eligible[0], eligible[1]])
        self.assertEqual(engine.state.pending.context["stage"], "choice")

    def test_choice_timeout_auto_declines_all_volunteers(self):
        engine = started()
        attacker, target = self.attack(engine)
        eligible = list(engine.state.pending.eligible_player_ids)
        answer_poll(engine, eligible[0], eligible[1])
        events = engine.apply(command(engine, "timeout", None, "timeout-intervention", stage="choice"))
        declined = next(event for event in events if event.event_type == "InterventionDeclined")
        self.assertEqual(declined.payload["reason"], "timeout-declined")
        self.assertEqual(engine.state.players[target].damage, 1)
        self.assertEqual(engine.state.players[eligible[0]].damage, 0)

    def test_target_picks_one_volunteer_and_declines_all(self):
        engine = started()
        attacker, target = self.attack(engine)
        eligible = list(engine.state.pending.eligible_player_ids)
        answer_poll(engine, eligible[0], eligible[1])
        engine.apply(command(engine, "pick", target, "choose-intervention", responderPlayerId=eligible[1]))
        reveal_rank(engine, eligible[1])
        if engine.state.pending and engine.state.pending.kind == "skill":
            engine.apply(command(engine, "no-skill", eligible[1], "choose-skill", use=False))
        self.assertEqual(engine.state.players[eligible[1]].damage, 1)
        self.assertEqual(engine.state.players[eligible[0]].damage, 0)
        self.assertEqual(engine.state.players[target].damage, 0)

        attacker2 = engine.state.dagger_holder_id
        target2 = next(pid for pid in engine.state.players if pid != attacker2 and engine.state.players[pid].damage == 0)
        engine.apply(command(engine, "attack-2", attacker2, "attack", targetPlayerId=target2))
        eligible2 = list(engine.state.pending.eligible_player_ids)
        if len(eligible2) >= 2:
            answer_poll(engine, eligible2[0], eligible2[1])
            events = engine.apply(command(engine, "decline-all", target2, "decline-intervention"))
            declined = next(event for event in events if event.event_type == "InterventionDeclined")
            self.assertEqual(declined.payload["reason"], "target-declined")
            self.assertEqual(engine.state.players[target2].damage, 1)

    def test_respond_and_choose_stage_guards(self):
        engine = started()
        attacker, target = self.attack(engine)
        eligible = list(engine.state.pending.eligible_player_ids)
        answer_poll(engine, eligible[0], eligible[1])
        # volunteers can no longer respond once the choice stage opened
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "late", eligible[2], "respond-intervention", volunteer=True))
        self.assertEqual(error.exception.code, "intervention.not-poll")
        # only the target may choose
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "steal", eligible[0], "choose-intervention", responderPlayerId=eligible[0]))
        self.assertEqual(error.exception.code, "player.not-actor")
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "steal-decline", eligible[0], "decline-intervention"))
        self.assertEqual(error.exception.code, "player.not-actor")

    def test_timeout_guards(self):
        engine = started()
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "nothing", None, "timeout-intervention", stage="poll"))
        self.assertEqual(error.exception.code, "intervention.not-open")
        attacker, target = self.attack(engine)
        pending = engine.state.pending
        pending.context["stage"] = "choice"  # synthetic: mismatch the armed poll stage
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "wrong-stage", None, "timeout-intervention", stage="poll"))
        self.assertEqual(error.exception.code, "intervention.not-open")

    def test_responses_are_broadcast_progressively(self):
        engine = started()
        attacker, target = self.attack(engine)
        eligible = list(engine.state.pending.eligible_player_ids)
        events = engine.apply(command(engine, "r0", eligible[0], "respond-intervention", volunteer=True))
        self.assertEqual([event.event_type for event in events], ["InterventionResponded"])
        self.assertEqual(events[0].payload, {"playerId": eligible[0], "volunteer": True})
        self.assertEqual(engine.state.pending.context["responses"], {eligible[0]: True})


class SingleWindowTimeoutBranchTests(unittest.TestCase):
    """Expiry defaults for the three single-player windows (issue 05 / ADR 0011)."""

    def started(self, count=6, seed="window-seed", **start_payload):
        engine = RulesEngine.new_game("window-game", seed, clock=FixedClock())
        for index in range(count):
            engine.apply(command(engine, f"join-{index}", None, "join-game", playerId=f"p{index}", displayName=f"P{index}"))
        engine.apply(command(engine, "start", None, "start-game", **start_payload))
        return engine

    def wound(self, engine, victim_id, command_id="attack"):
        """Attack a victim and decline the poll, leaving the victim's reveal window open."""
        holder = engine.state.dagger_holder_id
        if holder == victim_id:
            give_dagger_to(engine, next(pid for pid in engine.state.players if pid != victim_id))
        attacker = engine.state.dagger_holder_id
        engine.apply(command(engine, command_id, attacker, "attack", targetPlayerId=victim_id))
        answer_poll(engine)
        return engine.state.pending

    def test_single_window_timeout_configuration_is_fixed_at_start(self):
        engine = self.started(singleWindowTimeoutSeconds=30)
        self.assertEqual(engine.state.single_window_timeout_seconds, 30)
        started_event = next(event for event in engine.state.events if event.event_type == "GameStarted")
        self.assertEqual(started_event.payload["singleWindowTimeoutSeconds"], 30)
        self.assertEqual(started_event.payload["interventionTimeoutSeconds"], 90)

    def test_default_single_window_timeout_is_ninety_seconds(self):
        engine = started()
        self.assertEqual(engine.state.single_window_timeout_seconds, 90)

    def test_invalid_single_window_timeout_choice_is_rejected(self):
        engine = RulesEngine.new_game("window-game", "window-seed", clock=FixedClock())
        for index in range(6):
            engine.apply(command(engine, f"join-{index}", None, "join-game", playerId=f"p{index}", displayName=f"P{index}"))
        for bad in (0, 45, "90", True):
            with self.subTest(bad=bad):
                with self.assertRaises(RuleError) as error:
                    engine.apply(command(engine, f"start-{bad}", None, "start-game", singleWindowTimeoutSeconds=bad))
                self.assertEqual(error.exception.code, "game.invalid-timeout")
        engine.apply(command(engine, "start-ok", None, "start-game"))

    def test_reveal_timeout_reveals_markers_in_order_across_chained_windows(self):
        engine = self.started()
        victim = next(pid for pid in engine.state.players if pid != engine.state.dagger_holder_id)
        self.wound(engine, victim, "attack-1")
        events = engine.apply(command(engine, "timeout-1", None, "timeout-reveal"))
        revealed = next(event for event in events if event.event_type == "ClueRevealed")
        # deterministic default: marker-0 before marker-1 before rank, and the
        # automatic reveal is marked in the audit trail
        self.assertEqual(revealed.payload["kind"], "marker-0")
        self.assertEqual(revealed.payload["reason"], "timeout")
        self.assertEqual(revealed.payload["value"], engine.state.players[victim].identity_markers[0])
        self.assertEqual(engine.state.players[victim].revealed, {"marker-0"})
        self.assertIsNone(engine.state.pending)

        self.wound(engine, victim, "attack-2")
        events = engine.apply(command(engine, "timeout-2", None, "timeout-reveal"))
        revealed = next(event for event in events if event.event_type == "ClueRevealed")
        self.assertEqual(revealed.payload["kind"], "marker-1")
        self.assertEqual(engine.state.players[victim].revealed, {"marker-0", "marker-1"})

    def test_reveal_timeout_on_a_wild_marker_takes_the_question_mark(self):
        engine, found = started_with_ranks(7, "fleur-cross")
        inquisitor = found["fleur-cross"]
        self.wound(engine, inquisitor.player_id)
        events = engine.apply(command(engine, "timeout", None, "timeout-reveal"))
        revealed = next(event for event in events if event.event_type == "ClueRevealed")
        self.assertEqual(revealed.payload["value"], "unknown")
        self.assertEqual(engine.state.players[inquisitor.player_id].revealed_values["marker-0"], "unknown")

    def test_reveal_timeout_guards(self):
        engine = self.started()
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "nothing", None, "timeout-reveal"))
        self.assertEqual(error.exception.code, "reveal.not-open")
        victim = next(pid for pid in engine.state.players if pid != engine.state.dagger_holder_id)
        other = engine.state.dagger_holder_id
        self.wound(engine, victim)
        # a timeout armed for another actor's window is rejected
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "wrong-actor", None, "timeout-reveal", actorPlayerId=other))
        self.assertEqual(error.exception.code, "reveal.not-open")
        # a stale timer armed for an earlier eligibility set is rejected
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "stale-tokens", None, "timeout-reveal", actorPlayerId=victim, eligibleTokens=["marker-1"]))
        self.assertEqual(error.exception.code, "reveal.not-open")
        engine.apply(command(engine, "armed-tokens", None, "timeout-reveal", actorPlayerId=victim, eligibleTokens=["marker-0", "marker-1", "rank"]))

    def test_skill_timeout_declines_and_permanently_spends_the_skill(self):
        engine, found = started_with_ranks(6, 1)
        victim = found[1]
        self.wound(engine, victim.player_id)
        engine.apply(command(engine, "reveal-rank", victim.player_id, "choose-reveal", token="rank"))
        self.assertEqual(engine.state.pending.kind, "skill")
        events = engine.apply(command(engine, "timeout", None, "timeout-skill"))
        declined = next(event for event in events if event.event_type == "SkillDeclined")
        self.assertEqual(declined.payload["reason"], "timeout")
        self.assertIn("1", engine.state.players[victim.player_id].skills_used)
        self.assertIsNone(engine.state.pending)
        self.assertEqual(engine.state.phase["kind"], "action")

    def test_skill_timeout_guards(self):
        engine = self.started()
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "nothing", None, "timeout-skill"))
        self.assertEqual(error.exception.code, "skill.not-open")

    def test_return_timeout_returns_the_first_marker_before_rank(self):
        engine, found = started_with_ranks(6, 4)
        alchemist = found[4]
        victim = next(
            pid for pid, player in engine.state.players.items()
            if pid not in (alchemist.player_id, engine.state.dagger_holder_id)
        )
        # wound 1: the victim reveals marker-0
        self.wound(engine, victim, "attack-1")
        engine.apply(command(engine, "reveal-m0", victim, "choose-reveal", token="marker-0"))
        # wound 2: the victim reveals rank (a skill window may open; decline it)
        self.wound(engine, victim, "attack-2")
        engine.apply(command(engine, "reveal-rank", victim, "choose-reveal", token="rank"))
        if engine.state.pending and engine.state.pending.kind == "skill":
            engine.apply(command(engine, "no-skill", victim, "choose-skill", use=False))
        self.assertEqual(engine.state.players[victim].damage, 2)
        # the alchemist alone takes the third attack for the victim, which
        # force-reveals the alchemist's rank and opens the heal window
        third = next(
            pid for pid in engine.state.players
            if pid not in (victim, alchemist.player_id)
        )
        give_dagger_to(engine, third)
        engine.apply(command(engine, "attack-3", third, "attack", targetPlayerId=victim))
        answer_poll(engine, alchemist.player_id)
        self.assertEqual(engine.state.pending.kind, "skill")
        engine.apply(command(engine, "heal", alchemist.player_id, "choose-skill", use=True, mode="heal"))
        self.assertEqual(engine.state.pending.kind, "token-return")
        events = engine.apply(command(engine, "timeout", None, "timeout-return"))
        returned = next(event for event in events if event.event_type == "TokenReturned")
        self.assertEqual(returned.payload["token"], "marker-0")
        self.assertEqual(returned.payload["reason"], "timeout")
        self.assertEqual(engine.state.players[victim].damage, 1)
        self.assertEqual(engine.state.players[victim].revealed, {"rank"})
        self.assertIsNone(engine.state.pending)

    def test_return_timeout_guard(self):
        engine = self.started()
        with self.assertRaises(RuleError) as error:
            engine.apply(command(engine, "nothing", None, "timeout-return"))
        self.assertEqual(error.exception.code, "token-return.not-open")

    def test_timeout_commands_replay_deterministically_through_the_save_pipeline(self):
        from blood_bound import create_save_document, load_game_bytes

        engine = self.started()
        victim = next(pid for pid in engine.state.players if pid != engine.state.dagger_holder_id)
        self.wound(engine, victim, "attack-1")
        engine.apply(command(engine, "timeout-1", None, "timeout-reveal"))
        self.wound(engine, victim, "attack-2")
        engine.apply(command(engine, "reveal-rank", victim, "choose-reveal", token="rank"))
        if engine.state.pending and engine.state.pending.kind == "skill":
            engine.apply(command(engine, "timeout-2", None, "timeout-skill"))
        document = create_save_document(engine)
        replayed = load_game_bytes(json.dumps(document, ensure_ascii=True, sort_keys=True).encode("utf-8"))
        self.assertEqual(replayed.state.revision, engine.state.revision)
        self.assertEqual(replayed.state.players[victim].revealed, engine.state.players[victim].revealed)
        self.assertEqual(replayed.state.players[victim].skills_used, engine.state.players[victim].skills_used)
        # same seed + same command order = same log, literally
        self.assertEqual(
            [(event.revision, event.event_type, event.payload) for event in replayed.state.events],
            [(event.revision, event.event_type, event.payload) for event in engine.state.events],
        )


if __name__ == "__main__":
    unittest.main()
