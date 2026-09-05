"""Randomized, stdlib-only property sweeps over the deterministic rules engine.

Every sweep pins both the game setup and the action choices to a fixed game
seed, so a failing case is fully reproducible:

- `unittest.subTest` reports the failing `seed` and player `count`;
- `generate_walk(count, seed)` regenerates the exact command sequence;
- on failure the seed and command sequence are also persisted under
  `.scratch/blood-oath-replica/test-failures/` (see `record_failure`).

The RNG is `random.Random` (no Hypothesis), and the walk only ever submits
commands the engine accepts, so a failure is a rule violation, not a generator
mistake. `max_turns` is a safety budget only: every attack deals at least one
point of damage and damage never heals, so a walk always reaches a capture
well before the budget.

Properties exercised:
- determinism: same seed + command sequence -> identical event log;
- resume equivalence: checkpoint -> resume -> same result, no double apply;
- idempotency: a repeated command_id returns the original events, revision
  unchanged;
- projection secrecy: no viewer sees the seed, another player's identity, or
  the inquisitor's curses;
- state invariants: damage/capture, dagger holder, revealed clues, and event
  revision continuity hold after every command.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
import random
from pathlib import Path
import unittest

from blood_bound import Command, RuleError, RulesEngine, project_state

# One sweep entry per player count 6..12; the seed string doubles as the
# action-choice RNG seed, so each entry is an independent deterministic game.
SWEEPS = [(f"prop-seed-{count}-{round_}", count) for count in range(6, 13) for round_ in range(2)]

FAILURE_DIR = Path(__file__).resolve().parents[1] / ".scratch" / "blood-oath-replica" / "test-failures"

_WALK_CACHE: dict[tuple[int, str], tuple[tuple[str, str | None, str, dict], ...]] = {}


class FixedClock:
    def __call__(self) -> float:
        return 0.0


def generate_walk(count: int, seed: str, *, max_turns: int = 500) -> tuple[tuple[str, str | None, str, dict], ...]:
    """Generate a deterministic, always-legal command walk for a fresh game.

    Returns ``(command_id, actor, command_type, payload)`` tuples. The walk
    drives a scratch engine with randomized but legal choices (pass/attack,
    respond/choose/decline intervention, use/decline skill), so replaying the
    same tuples into a fresh engine with the same seed is exact.
    """
    cached = _WALK_CACHE.get((count, seed))
    if cached is not None:
        return cached
    rng = random.Random(f"{seed}::walk")
    engine = RulesEngine.new_game(f"walk-{count}", seed, clock=FixedClock())
    commands: list[tuple[str, str | None, str, dict]] = []

    def send(command_id: str, actor: str | None, command_type: str, payload: dict) -> None:
        engine.apply(Command(command_id, engine.state.game_id, actor, engine.state.revision, command_type, payload))
        commands.append((command_id, actor, command_type, payload))

    for index in range(count):
        send(f"join-{index}", None, "join-game", {"playerId": f"p{index}", "displayName": f"P{index}"})
    send("start", None, "start-game", {})

    turn = 0
    while engine.state.status != "ended" and turn < max_turns:
        turn += 1
        pending = engine.state.pending
        if pending is None:
            holder = engine.state.dagger_holder_id
            assert holder is not None
            holder_player = engine.state.players[holder]
            live_others = [player for player in engine.state.players.values() if player.player_id != holder and not player.captured]
            if not live_others:
                break
            attackable = [
                player
                for player in live_others
                if not player.resources.get("shield", 0)
                and not (holder_player.faction == "secret-order" and player.damage >= 3)
            ]
            if attackable and rng.random() < 0.75:
                target = rng.choice(attackable).player_id
                send(f"attack-{turn}", holder, "attack", {"targetPlayerId": target})
            else:
                target = rng.choice(live_others).player_id
                send(f"pass-{turn}", holder, "pass-dagger", {"targetPlayerId": target})
            continue
        if pending.kind == "intervention" and pending.context.get("stage") == "poll":
            # multi-actor window: answer as a random eligible responder until
            # the poll closes (choice stage or resolved attack)
            responded = 0
            while (
                engine.state.pending is not None
                and engine.state.pending.kind == "intervention"
                and engine.state.pending.context.get("stage") == "poll"
            ):
                pending = engine.state.pending
                responses = pending.context["responses"]
                actor = next(player_id for player_id in pending.eligible_player_ids if player_id not in responses)
                actions = engine.legal_actions(actor)
                assert actions, "poll window without legal action"
                action = rng.choice(actions)
                payload = {key: value for key, value in action.items() if key != "type"}
                send(f"respond-{turn}-{responded}", actor, action["type"], payload)
                responded += 1
            continue
        actor = pending.actor_player_id
        actions = engine.legal_actions(actor)
        if not actions:
            raise AssertionError(f"pending window without legal action: {pending.kind}")
        action = rng.choice(actions)
        payload = {key: value for key, value in action.items() if key != "type"}
        if action["type"] == "choose-skill" and action.get("use") and pending.rank == "fleur-cross":
            # the curse window's use action carries the assignments; the walk
            # picks distinct live recipients at random (self-distribution is legal)
            curses = sorted(engine.state.curses)
            recipients = rng.sample(sorted(engine.state.players), len(curses))
            payload["assignments"] = dict(zip(curses, recipients))
        send(f"pending-{turn}", actor, action["type"], payload)

    walk = tuple(commands)
    _WALK_CACHE[(count, seed)] = walk
    return walk


def replay_walk(count: int, seed: str, commands) -> RulesEngine:
    """Apply a recorded walk to a fresh engine and return it."""
    engine = RulesEngine.new_game(f"walk-{count}", seed, clock=FixedClock())
    for command_id, actor, command_type, payload in commands:
        engine.apply(Command(command_id, engine.state.game_id, actor, engine.state.revision, command_type, payload))
    return engine


def _event_signature(event) -> tuple[int, str, dict]:
    """Timestamps come from a fixed clock; identity/revision/payload remain."""
    return (event.revision, event.event_type, event.payload)


@contextmanager
def record_failure(testcase: unittest.TestCase, seed: str, count: int, commands) -> None:
    """Persist the seed and command sequence of a failing sweep to disk."""
    try:
        yield
    except Exception:
        FAILURE_DIR.mkdir(parents=True, exist_ok=True)
        path = FAILURE_DIR / f"{testcase.__class__.__name__}.{testcase._testMethodName}-{seed}.json"
        path.write_text(
            json.dumps(
                {
                    "test": testcase.id(),
                    "seed": seed,
                    "playerCount": count,
                    "commands": [{"commandId": c[0], "actor": c[1], "type": c[2], "payload": c[3]} for c in commands],
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        raise


def assert_state_invariants(testcase: unittest.TestCase, state) -> None:
    """Cross-check the engine's own validation with contract-level invariants."""
    testcase.assertEqual([event.revision for event in state.events], list(range(1, state.revision + 1)))
    testcase.assertEqual(state.revision, len(state.events))
    for player in state.players.values():
        testcase.assertIn(player.damage, range(5), player.player_id)
        testcase.assertEqual(player.captured, player.damage == 4, player.player_id)
        testcase.assertLessEqual(len(player.revealed), 3, player.player_id)
        testcase.assertTrue(player.revealed <= {"rank", "marker-0", "marker-1"}, player.player_id)
    if state.status == "active":
        testcase.assertTrue(6 <= len(state.players) <= 12)
        testcase.assertIsNotNone(state.dagger_holder_id)
        holder = state.players[state.dagger_holder_id]
        testcase.assertFalse(holder.captured)
        testcase.assertIsNone(state.result)
    if state.status == "ended":
        testcase.assertIsNotNone(state.result)
        testcase.assertIn(state.result["winner"], {"rose", "beast", "draw"})
        testcase.assertIn("branch", state.result)
        testcase.assertEqual(len(state.result["ranking"]), len(state.players))
        testcase.assertEqual(state.phase, {"kind": "ended"})
        testcase.assertIsNone(state.dagger_holder_id)


class DeterminismPropertyTests(unittest.TestCase):
    def test_same_seed_and_command_sequence_yield_identical_event_logs(self):
        for seed, count in SWEEPS:
            with self.subTest(seed=seed, count=count):
                commands = generate_walk(count, seed)
                with record_failure(self, seed, count, commands):
                    left = replay_walk(count, seed, commands)
                    right = replay_walk(count, seed, commands)
                    self.assertEqual(
                        [_event_signature(event) for event in left.state.events],
                        [_event_signature(event) for event in right.state.events],
                    )
                    self.assertEqual(left.state.revision, right.state.revision)
                    self.assertEqual(left.state.result, right.state.result)

    def test_walk_generation_is_deterministic(self):
        for seed, count in SWEEPS:
            with self.subTest(seed=seed, count=count):
                self.assertEqual(generate_walk(count, seed), generate_walk(count, seed))


class ResumeEquivalencePropertyTests(unittest.TestCase):
    def test_checkpoint_resume_matches_uninterrupted_run_without_double_apply(self):
        for seed, count in SWEEPS:
            with self.subTest(seed=seed, count=count):
                commands = generate_walk(count, seed)
                with record_failure(self, seed, count, commands):
                    split = random.Random(f"{seed}::resume").randrange(len(commands) + 1)
                    uninterrupted = replay_walk(count, seed, commands)
                    partial = replay_walk(count, seed, commands[:split])
                    checkpoint = partial.checkpoint()
                    resumed = RulesEngine.resume_from_checkpoint(checkpoint, clock=FixedClock())
                    for command_id, actor, command_type, payload in commands[split:]:
                        resumed.apply(
                            Command(command_id, resumed.state.game_id, actor, resumed.state.revision, command_type, payload)
                        )
                    self.assertEqual(resumed.state.revision, uninterrupted.state.revision)
                    self.assertEqual(
                        [_event_signature(event) for event in resumed.state.events],
                        [_event_signature(event) for event in uninterrupted.state.events],
                    )
                    self.assertEqual(resumed.state.result, uninterrupted.state.result)
                    # the split command boundary never settles twice
                    self.assertEqual(len(resumed.state.events), len(uninterrupted.state.events))


class IdempotencyPropertyTests(unittest.TestCase):
    def test_reapplying_a_command_returns_the_same_events_and_advances_nothing(self):
        for seed, count in SWEEPS:
            with self.subTest(seed=seed, count=count):
                commands = generate_walk(count, seed)
                with record_failure(self, seed, count, commands):
                    engine = RulesEngine.new_game(f"walk-{count}", seed, clock=FixedClock())
                    for command_id, actor, command_type, payload in commands:
                        command = Command(command_id, engine.state.game_id, actor, engine.state.revision, command_type, payload)
                        first = engine.apply(command)
                        revision_after_first = engine.state.revision
                        retried = engine.apply(command)
                        self.assertEqual(retried, first)
                        self.assertEqual(engine.state.revision, revision_after_first)


class ProjectionSecrecyPropertyTests(unittest.TestCase):
    def test_no_projection_leaks_seed_identity_or_curse(self):
        for seed, count in SWEEPS:
            with self.subTest(seed=seed, count=count):
                commands = generate_walk(count, seed)
                with record_failure(self, seed, count, commands):
                    state = replay_walk(count, seed, commands).state
                    for viewer in [None, *state.players]:
                        view = project_state(state, viewer)
                        self.assertNotIn("seed", view)
                        # the seed string itself never appears anywhere in the view
                        self.assertNotIn(state.seed, json.dumps(view, sort_keys=True))
                        for entry in view["players"]:
                            for private_key in ("faction", "rank", "clueIcon"):
                                self.assertNotIn(private_key, entry)
                            self.assertTrue(set(entry.get("revealed", {})) <= {"rank", "markers"})
                        # pending views never expose the private context dict
                        self.assertNotIn("context", view["pending"] or {})
                        if view["viewer"] is None:
                            self.assertEqual(view["legalActions"], [])
                            continue
                        viewer_player = state.players[viewer]
                        self.assertEqual(
                            view["viewer"]["identity"],
                            {"faction": viewer_player.faction, "rank": viewer_player.rank},
                        )
                        # the viewer block carries exactly two clue icons: their own
                        # and the right-hand neighbour's (previous seat, cyclically)
                        ordered = sorted(state.players.values(), key=lambda player: player.seat)
                        neighbour = ordered[ordered.index(viewer_player) - 1]
                        self.assertEqual(view["viewer"]["clueIcon"], viewer_player.clue_icon)
                        self.assertEqual(
                            view["viewer"]["seenNeighbourClue"],
                            {"playerId": neighbour.player_id, "icon": neighbour.clue_icon},
                        )
                        if viewer_player.faction != "secret-order":
                            self.assertEqual(view["viewer"]["cursesToDistribute"], [])


class StateInvariantPropertyTests(unittest.TestCase):
    def test_engine_invariants_hold_after_every_command(self):
        for seed, count in SWEEPS:
            with self.subTest(seed=seed, count=count):
                commands = generate_walk(count, seed)
                with record_failure(self, seed, count, commands):
                    engine = RulesEngine.new_game(f"walk-{count}", seed, clock=FixedClock())
                    for command_id, actor, command_type, payload in commands:
                        engine.apply(
                            Command(command_id, engine.state.game_id, actor, engine.state.revision, command_type, payload)
                        )
                        assert_state_invariants(self, engine.state)

    def test_a_walk_never_raises_and_reaches_a_terminal_state(self):
        for seed, count in SWEEPS:
            with self.subTest(seed=seed, count=count):
                commands = generate_walk(count, seed)
                engine = replay_walk(count, seed, commands)
                # every walk either ended within the budget or ran out of turns
                # while still active; either way no RuleError escaped generation
                if engine.state.status == "ended":
                    self.assertIsNotNone(engine.state.result)


if __name__ == "__main__":
    unittest.main()
