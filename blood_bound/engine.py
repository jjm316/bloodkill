from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import random
import time
from typing import Any, Callable, Mapping

from .projection import legal_actions as _legal_actions, project_state as _project_state


Clock = Callable[[], float]

# Host-configurable intervention timeout (issue 23 / ADR 0002, ADR 0012). The
# value is fixed at start-game time and covers all three intervention windows,
# each with its own independent countdown: the target's request gate
# (unanswered counts as no assistance needed, ADR 0012), the volunteer vote
# (unanswered players count as not volunteering) and the target's choice among
# >=2 volunteers (timeout declines all of them).
INTERVENTION_TIMEOUT_CHOICES = (30, 60, 90, 120, 180)
DEFAULT_INTERVENTION_TIMEOUT_SECONDS = 90

# Host-configurable single-player window timeout (issue 05 / ADR 0011). One
# value covers the three solo decision windows (reveal / skill / token-return);
# expiry auto-resolves a deterministic default so a disconnected player can no
# longer stall the table. The wild color sub-window defaults to "unknown"
# (question mark), which is why the engine accepts it as a wild reveal color
# (the player-facing option itself is blood-oath-replica issue 26).
SINGLE_WINDOW_TIMEOUT_CHOICES = (30, 60, 90, 120, 180)
DEFAULT_SINGLE_WINDOW_TIMEOUT_SECONDS = 90

# ADR 0011 deterministic default order for timed-out reveals and returns:
# marker-0 → marker-1 → rank, so auto-resolution never depends on set order.
_TOKEN_TIMEOUT_ORDER = ("marker-0", "marker-1", "rank")


class RuleError(Exception):
    """Stable, client-safe rule rejection."""

    def __init__(self, code: str, message: str = "", **details: Any) -> None:
        self.code = code
        self.details = details
        super().__init__(message or code)


@dataclass(frozen=True)
class Command:
    command_id: str
    game_id: str
    actor_player_id: str | None
    expected_revision: int
    type: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class Player:
    player_id: str
    seat: int
    display_name: str
    faction: str | None = None
    rank: int | str | None = None
    clue_icon: str | None = None
    identity_markers: list[str] = field(default_factory=lambda: ["unknown", "unknown"])
    damage: int = 0
    captured: bool = False
    revealed: set[str] = field(default_factory=set)
    revealed_values: dict[str, str | int] = field(default_factory=dict)
    inspections: dict[str, dict[str, str | int | None]] = field(default_factory=dict)
    shield_ward_id: str | None = None
    resources: dict[str, int] = field(
        default_factory=lambda: {name: 0 for name in ("quill", "shield", "sword", "staff", "fan")}
    )
    skills_used: set[str] = field(default_factory=set)


@dataclass
class Pending:
    kind: str
    actor_player_id: str
    target_player_id: str | None = None
    eligible_player_ids: tuple[str, ...] = ()
    rank: int | str | None = None
    trigger: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class Event:
    event_id: str
    event_type: str
    game_id: str
    revision: int
    timestamp: float
    command_id: str
    payload: dict[str, Any]


@dataclass
class EngineState:
    schema_version: int
    ruleset_id: str
    ruleset_version: str
    game_id: str
    seed: str
    revision: int = 0
    status: str = "setup"
    players: dict[str, Player] = field(default_factory=dict)
    dagger_holder_id: str | None = None
    phase: dict[str, Any] = field(default_factory=lambda: {"kind": "setup"})
    pending: Pending | None = None
    result: dict[str, Any] | None = None
    curses: list[str] = field(default_factory=list)
    curse_assignments: dict[str, str] = field(default_factory=dict)
    max_leader_factions: set[str] = field(default_factory=set)
    intervention_timeout_seconds: int = DEFAULT_INTERVENTION_TIMEOUT_SECONDS
    single_window_timeout_seconds: int = DEFAULT_SINGLE_WINDOW_TIMEOUT_SECONDS
    events: list[Event] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)
    command_results: dict[str, tuple[tuple[Event, ...], str]] = field(default_factory=dict)


# Ranks whose reveal-triggered skill is implemented in this ruleset version.
# Issue 14 expands this to ranks 1--9 as abilities land; ADR 0003 (2026-09-05
# product ruling) adds the Inquisitor's fleur-cross: its reveal opens the
# one-time curse-distribution skill window like any other rank's skill.
_REVEAL_SKILL_RANKS = frozenset({*range(1, 10), "fleur-cross"})


def _markers_for(rank: int | str | None, faction: str | None) -> list[str]:
    if rank == "fleur-cross" or faction == "secret-order":
        return ["wild", "wild"]
    if not isinstance(rank, int) or faction not in {"rose", "beast"}:
        return ["unknown", "unknown"]
    if rank in {1, 5, 6}:
        return [faction, faction]
    if rank in {2, 3, 4}:
        return ["unknown", "unknown"]
    return [faction, "unknown"]


class RulesEngine:
    """Deterministic command processor. The state is the authority; events are its audit trail."""

    def __init__(self, state: EngineState, *, clock: Clock | None = None) -> None:
        self.state = state
        self._clock = clock or time.time

    @classmethod
    def new_game(cls, game_id: str, seed: str, *, clock: Clock | None = None) -> "RulesEngine":
        if not game_id or not seed:
            raise ValueError("game_id and seed are required")
        return cls(
            EngineState(
                schema_version=2,
                ruleset_id="blood-bound-compatible",
                # 0.6: intervention request gate (ADR 0012, 2026-10-04) — after a
                # dagger attack only the target is asked whether others may
                # volunteer (stage "gate" before the poll); timeout counts as no
                # assistance needed and settles the attack on the target.
                # 0.5: rule-coupling batch 2026-10-03 — victim-choice reveals for
                # skill damage (ADR 0006), the skill-window general rule with the
                # mentalist's seal (ADR 0009), the captured inquisitor's solo win
                # (ADR 0007), shield-blocks-targeting-only (ADR 0010), single-window
                # timeouts (ADR 0011) and the wild question-mark reveal (issue 26).
                # 0.4: curse distribution became a reveal-triggered skill (ADR 0003);
                # 0.3 saves are explicitly rejected, affected games must be rebuilt.
                ruleset_version="0.6",
                game_id=game_id,
                seed=seed,
            ),
            clock=clock,
        )

    def checkpoint(self) -> EngineState:
        """Return a persistence-ready copy at the current event revision."""
        return deepcopy(self.state)

    @classmethod
    def resume_from_checkpoint(cls, checkpoint: EngineState, *, clock: Clock | None = None) -> "RulesEngine":
        if checkpoint.schema_version != 2 or checkpoint.ruleset_version != "0.6":
            raise RuleError("state.invalid", reason="unsupported schema version")
        engine = cls(deepcopy(checkpoint), clock=clock)
        cls._validate(engine.state)
        return engine

    def apply(self, command: Command) -> tuple[Event, ...]:
        state = self.state
        if command.game_id != state.game_id:
            raise RuleError("game.not-found", game_id=command.game_id)
        previous = state.command_results.get(command.command_id)
        if previous:
            old_events, body_hash = previous
            if body_hash != self._command_hash(command):
                raise RuleError("command.id-reuse", command_id=command.command_id)
            return old_events
        if command.expected_revision != state.revision:
            raise RuleError(
                "game.revision-conflict",
                expected=command.expected_revision,
                actual=state.revision,
            )
        if state.status == "ended":
            raise RuleError("game.already-ended")

        candidate = deepcopy(state)
        previous_phase = deepcopy(candidate.phase)
        events = self._dispatch(candidate, command)
        if candidate.phase != previous_phase:
            events.append(
                self._event(
                    candidate,
                    command,
                    "PhaseChanged",
                    {"from": previous_phase, "to": deepcopy(candidate.phase)},
                )
            )
        for index, event in enumerate(events, start=1):
            event.revision = state.revision + index
            event.event_id = f"{state.game_id}:{event.revision}"
        candidate.events.extend(events)
        candidate.commands.append(deepcopy(command))
        candidate.revision += len(events)
        candidate.command_results[command.command_id] = (events, self._command_hash(command))
        self._validate(candidate)
        self.state = candidate
        return events

    def _dispatch(self, state: EngineState, command: Command) -> list[Event]:
        handlers = {
            "join-game": self._join,
            "start-game": self._start,
            "pass-dagger": self._pass_dagger,
            "attack": self._attack,
            "respond-intervention": self._respond_intervention,
            "answer-intervention-request": self._answer_intervention_request,
            "choose-intervention": self._choose_intervention,
            "decline-intervention": self._decline_intervention,
            "timeout-intervention": self._timeout_intervention,
            "timeout-reveal": self._timeout_reveal,
            "timeout-skill": self._timeout_skill,
            "timeout-return": self._timeout_return,
            "choose-skill": self._choose_skill,
            "choose-return": self._choose_return,
            "choose-reveal": self._choose_reveal,
        }
        try:
            handler = handlers[command.type]
        except KeyError:
            raise RuleError("command.unknown", command_type=command.type) from None
        return handler(state, command)

    def _join(self, state: EngineState, command: Command) -> list[Event]:
        if state.status != "setup":
            raise RuleError("game.not-setup")
        player_id = str(command.payload.get("playerId", command.actor_player_id or ""))
        if not player_id:
            raise RuleError("player.not-eligible")
        if player_id in state.players:
            raise RuleError("game.duplicate-player", player_id=player_id)
        if len(state.players) >= 12:
            raise RuleError("game.player-count", count=len(state.players))
        requested_seat = command.payload.get("seat")
        occupied = {player.seat for player in state.players.values()}
        seat = int(requested_seat) if requested_seat is not None else next(
            seat for seat in range(12) if seat not in occupied
        )
        if seat < 0 or seat >= 12 or seat in occupied:
            raise RuleError("game.seat-occupied", seat=seat)
        name = str(command.payload.get("displayName", player_id))
        state.players[player_id] = Player(player_id, seat, name)
        return [self._event(state, command, "PlayerJoined", {"playerId": player_id, "seat": seat})]

    def _start(self, state: EngineState, command: Command) -> list[Event]:
        if state.status != "setup":
            raise RuleError("game.not-setup")
        count = len(state.players)
        if count < 6 or count > 12:
            raise RuleError("game.player-count", count=count)
        timeout_seconds = command.payload.get("interventionTimeoutSeconds", DEFAULT_INTERVENTION_TIMEOUT_SECONDS)
        if isinstance(timeout_seconds, bool) or timeout_seconds not in INTERVENTION_TIMEOUT_CHOICES:
            raise RuleError("game.invalid-timeout", value=timeout_seconds, choices=list(INTERVENTION_TIMEOUT_CHOICES))
        state.intervention_timeout_seconds = int(timeout_seconds)
        # Issue 05 / ADR 0011: one shared timeout for the three single-player
        # windows (reveal / skill / token-return), configured the same way.
        single_timeout_seconds = command.payload.get("singleWindowTimeoutSeconds", DEFAULT_SINGLE_WINDOW_TIMEOUT_SECONDS)
        if isinstance(single_timeout_seconds, bool) or single_timeout_seconds not in SINGLE_WINDOW_TIMEOUT_CHOICES:
            raise RuleError("game.invalid-timeout", value=single_timeout_seconds, choices=list(SINGLE_WINDOW_TIMEOUT_CHOICES))
        state.single_window_timeout_seconds = int(single_timeout_seconds)
        rng = random.Random(state.seed)
        ordered = sorted(state.players.values(), key=lambda player: player.seat)
        rose_count = count // 2
        factions = ["rose"] * rose_count + ["beast"] * rose_count
        if count % 2:
            factions.append("secret-order")
        rng.shuffle(factions)
        rank_pool = list(range(1, 10))
        rose_ranks = rng.sample(rank_pool, rose_count)
        beast_ranks = rng.sample(rank_pool, rose_count)
        rose_i = beast_i = 0
        for player, faction in zip(ordered, factions):
            player.faction = faction
            if faction == "rose":
                player.rank = rose_ranks[rose_i]
                rose_i += 1
                player.clue_icon = "rose"
            elif faction == "beast":
                player.rank = beast_ranks[beast_i]
                beast_i += 1
                player.clue_icon = "beast"
            else:
                player.rank = "fleur-cross"
                player.clue_icon = rng.choice(("rose", "beast"))
            player.identity_markers = _markers_for(player.rank, player.faction)
            if player.rank == 3 and player.faction in {"rose", "beast"}:
                player.clue_icon = "beast" if player.faction == "rose" else "rose"
        holder = rng.choice(ordered)
        state.status = "active"
        state.dagger_holder_id = holder.player_id
        state.phase = {"kind": "action", "activePlayerId": holder.player_id}
        inquisitor_count = sum(player.faction == "secret-order" for player in ordered)
        state.curses = [curse_id for index in range(1, inquisitor_count + 1) for curse_id in (f"true-curse-{index}", f"false-curse-{index}")]
        # Each player shows their clue icon to their left neighbour (next seat in
        # clockwise order). The event records who showed to whom; icon values stay
        # private and reach only the involved players through the projection.
        pairs = [
            {"fromPlayerId": player.player_id, "toPlayerId": ordered[(index + 1) % len(ordered)].player_id}
            for index, player in enumerate(ordered)
        ]
        return [
            self._event(
                state,
                command,
                "GameStarted",
                {
                    "playerCount": count,
                    "daggerHolderId": holder.player_id,
                    "curseCount": len(state.curses),
                    "interventionTimeoutSeconds": state.intervention_timeout_seconds,
                    "singleWindowTimeoutSeconds": state.single_window_timeout_seconds,
                },
            ),
            self._event(state, command, "ClueIconsShown", {"pairs": pairs}),
        ]

    def _pass_dagger(self, state: EngineState, command: Command) -> list[Event]:
        self._require_action_actor(state, command)
        target = self._live_player(state, command.payload.get("targetPlayerId"))
        if target.player_id == command.actor_player_id:
            raise RuleError("target.not-eligible")
        state.dagger_holder_id = target.player_id
        state.phase = {"kind": "action", "activePlayerId": target.player_id}
        return [self._event(state, command, "DaggerPassed", {"fromPlayerId": command.actor_player_id, "toPlayerId": target.player_id})]

    def _attack(self, state: EngineState, command: Command) -> list[Event]:
        self._require_action_actor(state, command)
        actor = state.players[command.actor_player_id or ""]
        target = self._live_player(state, command.payload.get("targetPlayerId"))
        if target.player_id == actor.player_id:
            raise RuleError("target.not-eligible")
        if target.resources.get("shield", 0):
            raise RuleError("target.shielded", player_id=target.player_id)
        if actor.faction == "secret-order" and target.damage >= 3:
            raise RuleError("target.already-three-damage", player_id=target.player_id)
        state.dagger_holder_id = target.player_id
        eligible = tuple(
            player.player_id
            for player in state.players.values()
            if not player.captured
            and player.player_id not in {actor.player_id, target.player_id}
            and "rank" not in player.revealed
            and not target.resources.get("fan", 0)
        )
        events = [self._event(state, command, "AttackDeclared", {"attackerPlayerId": actor.player_id, "targetPlayerId": target.player_id})]
        if not eligible:
            # Nobody may volunteer (e.g. the target holds a fan): the attack
            # resolves immediately without opening a gate or a poll (ADR 0012
            # moves the empty-set short-circuit ahead of the gate; nobody
            # could answer, so the window would be pure noise).
            events.extend(
                self._resolve_damage(state, command, target.player_id, "attack", active_player_id=actor.player_id)
            )
            return events
        # ADR 0012: the attack first opens the target's request gate — only
        # the attacked player may decide whether the volunteer poll opens at
        # all. The gate reuses the intervention pending with stage "gate".
        # The engine records the window's stage but never a wall-clock
        # deadline: replay determinism forbids real time in authoritative
        # state. The server owns the countdown (deadline = window opened +
        # configured seconds) and resolves expiry via the timeout-intervention
        # command.
        state.pending = Pending(
            "intervention",
            target.player_id,
            target.player_id,
            eligible,
            context={
                "attackerPlayerId": actor.player_id,
                "stage": "gate",
            },
        )
        state.phase = {"kind": "intervention", "stage": "gate", "activePlayerId": target.player_id}
        events.append(
            self._event(
                state,
                command,
                "InterventionGateOpened",
                {
                    "targetPlayerId": target.player_id,
                    "attackerPlayerId": actor.player_id,
                    "eligiblePlayerIds": list(eligible),
                },
            )
        )
        return events

    def _respond_intervention(self, state: EngineState, command: Command) -> list[Event]:
        pending = self._require_pending(state, command, "intervention")
        if pending.context.get("stage") != "poll":
            raise RuleError("intervention.not-poll")
        player_id = command.actor_player_id or ""
        if player_id not in pending.eligible_player_ids:
            raise RuleError("intervention.not-eligible", player_id=player_id)
        responses: dict[str, bool] = pending.context["responses"]
        if player_id in responses:
            raise RuleError("intervention.already-responded", player_id=player_id)
        volunteer = bool(command.payload.get("volunteer", False))
        responses[player_id] = volunteer
        events = [self._event(state, command, "InterventionResponded", {"playerId": player_id, "volunteer": volunteer})]
        if len(responses) == len(pending.eligible_player_ids):
            events.extend(self._close_poll(state, command, pending))
        return events

    def _close_poll(self, state: EngineState, command: Command, pending: Pending) -> list[Event]:
        """Resolve a fully answered poll: forced single taker, target's choice, or nobody."""
        responses: dict[str, bool] = pending.context["responses"]
        volunteers = tuple(player_id for player_id in pending.eligible_player_ids if responses.get(player_id))
        if len(volunteers) >= 2:
            pending.context["stage"] = "choice"
            state.phase = {"kind": "intervention", "stage": "choice", "activePlayerId": pending.actor_player_id}
            return [
                self._event(
                    state,
                    command,
                    "InterventionChoiceOpened",
                    {"targetPlayerId": pending.target_player_id, "volunteerPlayerIds": list(volunteers)},
                )
            ]
        if len(volunteers) == 1:
            return self._apply_intervention(state, command, pending, volunteers[0])
        return self._decline_all(
            state,
            command,
            pending,
            reason="no-volunteers",
        )

    def _apply_intervention(self, state: EngineState, command: Command, pending: Pending, responder_id: str) -> list[Event]:
        active_player_id = pending.context.get("attackerPlayerId", command.actor_player_id)
        target_id = pending.target_player_id or ""
        state.pending = None
        state.dagger_holder_id = responder_id
        state.phase = {"kind": "action", "activePlayerId": responder_id}
        events = [
            self._event(state, command, "InterventionSelected", {"targetPlayerId": target_id, "responderPlayerId": responder_id})
        ]
        events.extend(
            self._apply_damage(
                state,
                command,
                responder_id,
                1,
                "intervention",
                trigger="intervention",
                active_player_id=active_player_id,
                protected_player_id=target_id,
            )
        )
        return events

    def _decline_all(self, state: EngineState, command: Command, pending: Pending, *, reason: str) -> list[Event]:
        active_player_id = pending.context.get("attackerPlayerId", command.actor_player_id)
        state.pending = None
        target_id = pending.target_player_id or ""
        state.phase = {"kind": "action", "activePlayerId": target_id}
        return [
            self._event(state, command, "InterventionDeclined", {"targetPlayerId": target_id, "reason": reason})
        ] + self._resolve_damage(state, command, target_id, "attack", active_player_id=active_player_id)

    def _answer_intervention_request(self, state: EngineState, command: Command) -> list[Event]:
        """The target's answer to the request gate (ADR 0012): open the poll or take the hit."""
        pending = self._require_pending(state, command, "intervention")
        if pending.context.get("stage") != "gate":
            raise RuleError("intervention.not-gate")
        if pending.actor_player_id != command.actor_player_id:
            raise RuleError("intervention.not-target")
        if bool(command.payload.get("need", False)):
            # The poll opens exactly as it did pre-gate: same pending object,
            # same fields, only the context flips to the poll stage (the stage
            # mutation mirrors _close_poll's poll -> choice relay).
            pending.context["stage"] = "poll"
            pending.context["responses"] = {}
            state.phase = {"kind": "intervention", "stage": "poll", "activePlayerId": pending.actor_player_id}
            return [
                self._event(state, command, "InterventionGateAccepted", {"targetPlayerId": pending.target_player_id}),
                self._event(
                    state,
                    command,
                    "InterventionPollOpened",
                    {
                        "targetPlayerId": pending.target_player_id,
                        "attackerPlayerId": pending.context.get("attackerPlayerId"),
                        "eligiblePlayerIds": list(pending.eligible_player_ids),
                    },
                ),
            ]
        return self._decline_gate(state, command, pending, reason="target-declined")

    def _decline_gate(self, state: EngineState, command: Command, pending: Pending, *, reason: str) -> list[Event]:
        """Close the gate with the attack settling on the original target.

        The same settlement the nobody-volunteered poll path runs, but with the
        gate's own decline event: nobody was polled, so no InterventionDeclined
        is emitted.
        """
        active_player_id = pending.context.get("attackerPlayerId", command.actor_player_id)
        state.pending = None
        target_id = pending.target_player_id or ""
        return [
            self._event(state, command, "InterventionGateDeclined", {"targetPlayerId": target_id, "reason": reason})
        ] + self._resolve_damage(state, command, target_id, "attack", active_player_id=active_player_id)

    def _choose_intervention(self, state: EngineState, command: Command) -> list[Event]:
        pending = self._require_pending(state, command, "intervention")
        if pending.context.get("stage") != "choice":
            raise RuleError("intervention.not-choice")
        if pending.actor_player_id != command.actor_player_id:
            raise RuleError("player.not-actor")
        responder = self._live_player(state, command.payload.get("responderPlayerId"))
        responses: dict[str, bool] = pending.context["responses"]
        if not responses.get(responder.player_id):
            raise RuleError("intervention.not-eligible", player_id=responder.player_id)
        return self._apply_intervention(state, command, pending, responder.player_id)

    def _decline_intervention(self, state: EngineState, command: Command) -> list[Event]:
        pending = self._require_pending(state, command, "intervention")
        if pending.context.get("stage") != "choice":
            raise RuleError("intervention.not-choice")
        if pending.actor_player_id != command.actor_player_id:
            raise RuleError("player.not-actor")
        return self._decline_all(state, command, pending, reason="target-declined")

    def _timeout_intervention(self, state: EngineState, command: Command) -> list[Event]:
        pending = self._require_pending(state, command, "intervention")
        stage = pending.context.get("stage")
        if command.payload.get("stage", stage) != stage:
            raise RuleError("intervention.not-open")
        if stage == "gate":
            # Q1 (ADR 0012): an unanswered gate counts as "no assistance
            # needed" — GateDeclined(timeout), then the attack settles on the
            # target. This branch must stay ahead of the choice fallthrough.
            return self._decline_gate(state, command, pending, reason="timeout")
        if stage == "poll":
            # Timeout counts every unanswered player as not volunteering.
            responses: dict[str, bool] = pending.context["responses"]
            for player_id in pending.eligible_player_ids:
                responses.setdefault(player_id, False)
            return self._close_poll(state, command, pending)
        return self._decline_all(state, command, pending, reason="timeout-declined")

    # The three single-window timeout handlers (issue 05 / ADR 0011): the
    # server's DeadlineScheduler submits them on expiry, so like
    # timeout-intervention they carry no actor and re-check the window's
    # identity from the payload against authority — a raced or stale timer
    # that fires after the window moved on is rejected, not misapplied.

    def _require_timeout_actor(self, pending: Pending, command: Command, code: str) -> None:
        """Guard shared by the single-window timeouts: reject raced/stale submissions."""
        if command.payload.get("actorPlayerId", pending.actor_player_id) != pending.actor_player_id:
            raise RuleError(code)

    def _timeout_reveal(self, state: EngineState, command: Command) -> list[Event]:
        pending = self._require_pending(state, command, "reveal")
        self._require_timeout_actor(pending, command, "reveal.not-open")
        target = state.players[pending.actor_player_id]
        allowed = {"rank", "marker-0", "marker-1"} - target.revealed
        if pending.context.get("forceRank") and "rank" in allowed:
            allowed = {"rank"}
        guard = command.payload.get("eligibleTokens")
        if guard is not None and list(guard) != sorted(allowed):
            raise RuleError("reveal.not-open")
        token = next((token for token in _TOKEN_TIMEOUT_ORDER if token in allowed), None)
        if token is None:
            raise RuleError("reveal.not-open")
        # The wild color sub-window defaults to the question mark: no faction
        # lean is implied by an automatic reveal (ADR 0011 / issue 26).
        color = "unknown" if token.startswith("marker-") and target.identity_markers[int(token[-1])] == "wild" else None
        return self._reveal_token(state, command, target, token, dict(pending.context), color=color, auto_reason="timeout")

    def _timeout_skill(self, state: EngineState, command: Command) -> list[Event]:
        pending = self._require_pending(state, command, "skill")
        self._require_timeout_actor(pending, command, "skill.not-open")
        # Timeout is an automatic decline, and per ADR 0008 a declined skill
        # is permanently spent — no "stall the clock to stay uncommitted".
        owner = self._close_skill_window(state, pending)
        owner.skills_used.add(str(owner.rank))
        return [self._event(state, command, "SkillDeclined", {"playerId": owner.player_id, "rank": owner.rank, "reason": "timeout"})]

    def _timeout_return(self, state: EngineState, command: Command) -> list[Event]:
        pending = self._require_pending(state, command, "token-return")
        self._require_timeout_actor(pending, command, "token-return.not-open")
        target = self._live_player(state, pending.target_player_id)
        if target.damage < 1:
            raise RuleError("skill.invalid-target")
        token = next(
            (token for token in _TOKEN_TIMEOUT_ORDER if token in pending.eligible_player_ids and token in target.revealed),
            None,
        )
        if token is None:
            raise RuleError("token-return.not-open")
        return self._return_token(state, command, target, token, reason="timeout")

    def _close_skill_window(self, state: EngineState, pending: Pending) -> Player:
        """Close the skill window: settle the dagger hand-off and re-arm the action phase.

        A damage chain that hands its dagger to the wounded victim (assassin
        and mentalist, corpus B12) settles only after every window it opened
        has closed: under ADR 0009 the victim's own rank reveal may open this
        skill window before that settlement could run in _after_damage.
        """
        owner = state.players[pending.actor_player_id]
        state.pending = None
        if pending.context.get("daggerToTarget"):
            state.dagger_holder_id = owner.player_id
        state.phase = {"kind": "action", "activePlayerId": state.dagger_holder_id}
        return owner

    def _choose_skill(self, state: EngineState, command: Command) -> list[Event]:
        pending = self._require_pending(state, command, "skill")
        if pending.actor_player_id != command.actor_player_id:
            raise RuleError("player.not-actor")
        owner = self._close_skill_window(state, pending)
        use = bool(command.payload.get("use", False))
        if not use:
            owner.skills_used.add(str(owner.rank))
            return [self._event(state, command, "SkillDeclined", {"playerId": owner.player_id, "rank": owner.rank})]
        skill_id = str(owner.rank)
        if skill_id in owner.skills_used:
            raise RuleError("skill.already-used")
        owner.skills_used.add(skill_id)
        events = [self._event(state, command, "SkillUsed", {"playerId": owner.player_id, "rank": owner.rank})]
        # The pending window defines the skill being invoked: the curse
        # distribution rides the fleur-cross window even if the owner's dealt
        # rank were an integer (only possible through synthetic state).
        if pending.rank == "fleur-cross":
            events.extend(self._distribute_curses(state, command, owner))
            return events
        if owner.rank == 1:
            owner.resources["quill"] += 1
            events.append(self._event(state, command, "ResourceGranted", {"playerId": owner.player_id, "resource": "quill", "amount": 1}))
            owner.resources["quill"] -= 1
            events.append(
                self._event(
                    state,
                    command,
                    "ResourceSpent",
                    {"playerId": owner.player_id, "resource": "quill", "amount": 1, "reason": "leader-succession"},
                )
            )
            if owner.faction in {"rose", "beast"}:
                state.max_leader_factions.add(owner.faction)
        elif owner.rank == 2:
            target = self._live_player(state, command.payload.get("targetPlayerId"))
            if target.player_id == owner.player_id:
                raise RuleError("skill.invalid-target")
            # the skill text hands the dagger to the victim after the wounds;
            # with victim-choice reveal windows pending that moment is the end
            # of the damage chain (_after_damage), not the skill command
            events.extend(
                self._apply_damage(state, command, target.player_id, 2, "skill", trigger=None, active_player_id=owner.player_id, dagger_to_target=True)
            )
        elif owner.rank == 3:
            target_ids = command.payload.get("targetPlayerIds")
            if not isinstance(target_ids, (list, tuple)) or len(target_ids) != 2 or not all(isinstance(target_id, str) for target_id in target_ids) or len(set(target_ids)) != 2:
                raise RuleError("skill.invalid-target")
            targets = [self._live_player(state, target_id) for target_id in target_ids]
            if any(target.player_id == owner.player_id for target in targets):
                raise RuleError("skill.invalid-target")
            for target in targets:
                owner.inspections[target.player_id] = {"faction": target.faction, "rank": target.rank}
            events.append(self._event(state, command, "HarlequinInspected", {"playerId": owner.player_id, "targetPlayerIds": [target.player_id for target in targets]}))
        elif owner.rank == 4:
            if pending.trigger != "intervention":
                raise RuleError("skill.invalid-target")
            target = self._live_player(state, pending.context.get("protectedPlayerId"))
            mode = command.payload.get("mode")
            if mode == "harm":
                events.extend(self._apply_damage(state, command, target.player_id, 1, "skill", trigger=None, active_player_id=owner.player_id))
            elif mode == "heal":
                if target.damage < 1:
                    raise RuleError("skill.invalid-target")
                eligible = tuple(sorted(target.revealed))
                if not eligible:
                    raise RuleError("skill.invalid-target")
                state.pending = Pending("token-return", target.player_id, target.player_id, eligible_player_ids=eligible, context={"healerPlayerId": owner.player_id})
                state.phase = {"kind": "token-return", "activePlayerId": target.player_id}
                events.append(self._event(state, command, "TokenReturnOpened", {"playerId": target.player_id}))
            else:
                raise RuleError("skill.invalid-target")
        elif owner.rank == 5:
            target = self._live_player(state, command.payload.get("targetPlayerId"))
            if target.player_id == owner.player_id or target.resources.get("shield", 0):
                raise RuleError("skill.invalid-target")
            # the mentalist's text force-reveals the victim's rank (ADR 0006);
            # once the rank is already shown the wound falls back to the
            # victim-choice reveal pipeline like any other damage. The forced
            # reveal also seals the victim's skill (ADR 0009, plan A).
            events.extend(
                self._apply_damage(
                    state,
                    command,
                    target.player_id,
                    1,
                    "skill",
                    trigger=None,
                    active_player_id=owner.player_id,
                    force_rank=True,
                    seal_skill=True,
                    dagger_to_target=True,
                )
            )
        elif owner.rank == 6:
            target = self._live_player(state, command.payload.get("targetPlayerId"))
            owner.shield_ward_id = target.player_id
            events.extend(self._grant_resource(state, command, target, "shield"))
            events.extend(self._grant_resource(state, command, owner, "sword"))
        elif owner.rank == 8:
            target = self._live_player(state, command.payload.get("targetPlayerId"))
            events.extend(self._grant_resource(state, command, target, "staff"))
            target.identity_markers = ["unknown", "unknown"]
            for token in ("marker-0", "marker-1"):
                if token in target.revealed:
                    target.revealed_values[token] = "unknown"
            events.append(self._event(state, command, "IdentityMarkersObscured", {"playerId": target.player_id}))
        elif owner.rank == 9:
            target = self._live_player(state, command.payload.get("targetPlayerId"))
            events.extend(self._grant_resource(state, command, target, "fan"))
        elif owner.rank == 7:
            attacker_id = pending.context.get("attackerPlayerId")
            attacker = self._live_player(state, attacker_id)
            events.extend(self._apply_damage(
                state, command, attacker.player_id, 1, "reaction", trigger=None,
                active_player_id=owner.player_id,
            ))
        return events

    def _choose_return(self, state: EngineState, command: Command) -> list[Event]:
        pending = self._require_pending(state, command, "token-return")
        if pending.actor_player_id != command.actor_player_id:
            raise RuleError("player.not-actor")
        token = str(command.payload.get("token", ""))
        if token not in pending.eligible_player_ids:
            raise RuleError("reveal.not-eligible", token=token)
        target = self._live_player(state, pending.target_player_id)
        if target.damage < 1 or token not in target.revealed:
            raise RuleError("skill.invalid-target")
        return self._return_token(state, command, target, token)

    def _return_token(self, state: EngineState, command: Command, target: Player, token: str, *, reason: str | None = None) -> list[Event]:
        """Return one revealed token: heal a damage, clear the slot, close the window."""
        target.damage -= 1
        target.revealed.remove(token)
        target.revealed_values.pop(token, None)
        state.pending = None
        state.phase = {"kind": "action", "activePlayerId": state.dagger_holder_id}
        payload: dict[str, Any] = {"playerId": target.player_id, "token": token}
        if reason:
            payload["reason"] = reason
        return [
            self._event(state, command, "DamageHealed", {"playerId": target.player_id, "amount": 1, "source": "skill"}),
            self._event(state, command, "TokenReturned", payload),
        ]

    def _grant_resource(self, state: EngineState, command: Command, player: Player, resource: str, amount: int = 1) -> list[Event]:
        player.resources[resource] += amount
        return [self._event(state, command, "ResourceGranted", {"playerId": player.player_id, "resource": resource, "amount": amount})]

    def _return_resource(self, state: EngineState, command: Command, player: Player, resource: str, amount: int, reason: str) -> list[Event]:
        if amount <= 0 or player.resources.get(resource, 0) < amount:
            return []
        player.resources[resource] -= amount
        return [self._event(state, command, "ResourceReturned", {"playerId": player.player_id, "resource": resource, "amount": amount, "reason": reason})]

    def _choose_reveal(self, state: EngineState, command: Command) -> list[Event]:
        pending = self._require_pending(state, command, "reveal")
        if pending.actor_player_id != command.actor_player_id:
            raise RuleError("player.not-actor")
        token = str(command.payload.get("token", ""))
        target = state.players[pending.actor_player_id]
        allowed = {"rank", "marker-0", "marker-1"} - target.revealed
        if token not in allowed:
            raise RuleError("reveal.not-eligible", token=token)
        if pending.context.get("forceRank") and token != "rank" and "rank" in allowed:
            raise RuleError("reveal.rank-required")
        color = command.payload.get("color")
        return self._reveal_token(state, command, target, token, dict(pending.context), color=color)

    def _distribute_curses(self, state: EngineState, command: Command, owner: Player) -> list[Event]:
        """Curse distribution carried by the inquisitor's skill command (ADR 0003).

        Validation semantics are the ones the removed standing distribute-curse
        command used: assignment keys must match the pending curse set exactly,
        recipients must be live and pairwise distinct, and only the inquisitor
        may distribute. Each curse emits one private CurseDistributed event and
        the supply clears on success.
        """
        if owner.faction != "secret-order":
            raise RuleError("player.not-eligible")
        if state.status != "active" or not state.curses:
            raise RuleError("curse.invalid-count")
        assignments = command.payload.get("assignments")
        if not isinstance(assignments, Mapping) or set(assignments) != set(state.curses):
            raise RuleError("curse.invalid-count")
        recipients = list(assignments.values())
        if len(set(recipients)) != len(recipients):
            raise RuleError("curse.duplicate-recipient")
        for player_id in recipients:
            self._live_player(state, player_id)
        pending_curses = list(state.curses)
        state.curse_assignments.update({str(curse_id): str(recipient_id) for curse_id, recipient_id in assignments.items()})
        state.curses = []
        return [
            self._event(
                state,
                command,
                "CurseDistributed",
                {"curseId": curse_id, "recipientPlayerId": assignments[curse_id]},
            )
            for curse_id in pending_curses
        ]

    def _resolve_damage(
        self,
        state: EngineState,
        command: Command,
        target_id: str,
        source: str,
        *,
        active_player_id: str | None = None,
    ) -> list[Event]:
        if active_player_id is None:
            active_player_id = command.actor_player_id
            if state.pending:
                active_player_id = state.pending.context.get("attackerPlayerId", active_player_id)
        state.pending = None
        state.phase = {"kind": "action", "activePlayerId": target_id}
        return self._apply_damage(
            state,
            command,
            target_id,
            1,
            source,
            trigger="attack" if source == "attack" else None,
            active_player_id=active_player_id,
        )

    def _apply_damage(
        self,
        state: EngineState,
        command: Command,
        target_id: str,
        amount: int,
        source: str,
        trigger: str | None,
        active_player_id: str | None = None,
        protected_player_id: str | None = None,
        force_rank: bool = False,
        seal_skill: bool = False,
        dagger_to_target: bool = False,
    ) -> list[Event]:
        target = self._live_player(state, target_id)
        if target.resources.get("shield", 0) and source in {"attack", "skill", "reaction"}:
            raise RuleError("target.shielded", player_id=target_id)
        events = [self._event(state, command, "DamageApplied", {"targetPlayerId": target_id, "amount": amount, "source": source, "triggerContext": trigger})]
        context = {
            "attackerPlayerId": active_player_id,
            "protectedPlayerId": protected_player_id or target_id,
            "remaining": amount,
            "source": source,
            "trigger": trigger,
            "forceRank": force_rank or trigger == "intervention",
            "sealSkill": seal_skill,
            "daggerToTarget": dagger_to_target,
            "followup": None,
            "rankRevealed": False,
        }
        events.extend(self._continue_damage(state, command, target, context))
        return events

    def _continue_damage(self, state: EngineState, command: Command, target: Player, context: dict[str, Any]) -> list[Event]:
        if not context.get("remaining") or state.status == "ended":
            return self._after_damage(state, command, target, context)
        target.damage += 1
        context["remaining"] = int(context["remaining"]) - 1
        if target.damage >= 4:
            target.captured = True
            return [
                self._event(state, command, "PlayerCaptured", {"playerId": target.player_id}),
                self._end_game(state, command, target.player_id, active_player_id=context.get("attackerPlayerId")),
            ]
        available = {"rank", "marker-0", "marker-1"} - target.revealed
        force_rank = bool(context.get("forceRank")) or target.damage >= 3
        if force_rank and "rank" in available:
            return self._reveal_token(state, command, target, "rank", context)
        if len(available) == 1:
            only = next(iter(available))
            if only.startswith("marker-") and target.identity_markers[int(only[-1])] == "wild":
                context["eligibleTokens"] = [only]
                state.pending = Pending("reveal", target.player_id, target.player_id, tuple(), context=context)
                state.phase = {"kind": "reveal", "activePlayerId": target.player_id}
                return [self._event(state, command, "RevealWindowOpened", {"playerId": target.player_id, "eligibleTokens": [only], "forceRank": force_rank})]
            return self._reveal_token(state, command, target, only, context)
        if not available:
            return self._after_damage(state, command, target, context)
        context["eligibleTokens"] = sorted(available)
        state.pending = Pending("reveal", target.player_id, target.player_id, tuple(), context=context)
        state.phase = {"kind": "reveal", "activePlayerId": target.player_id}
        return [self._event(state, command, "RevealWindowOpened", {"playerId": target.player_id, "eligibleTokens": sorted(available), "forceRank": force_rank})]

    def _reveal_token(
        self,
        state: EngineState,
        command: Command,
        target: Player,
        token: str,
        context: dict[str, Any],
        *,
        color: str | None = None,
        auto_reason: str | None = None,
    ) -> list[Event]:
        if token not in {"rank", "marker-0", "marker-1"} - target.revealed:
            raise RuleError("reveal.not-eligible", token=token)
        if token.startswith("marker-"):
            index = int(token[-1])
            marker = target.identity_markers[index]
            if marker == "wild":
                # "unknown" is the question-mark reveal: player-selectable per
                # issue 26 and the automatic timeout default per ADR 0011.
                if color not in {"rose", "beast", "unknown"}:
                    state.pending = Pending("reveal", target.player_id, target.player_id, context=context)
                    state.phase = {"kind": "reveal", "activePlayerId": target.player_id}
                    raise RuleError("reveal.color-required")
                value = color
            else:
                value = marker
        else:
            value = target.rank
        target.revealed.add(token)
        target.revealed_values[token] = value
        if token == "rank":
            context["rankRevealed"] = True
        payload: dict[str, Any] = {"playerId": target.player_id, "kind": token, "value": value}
        if auto_reason:
            # Marks an automatic (timeout) resolution in the audit trail.
            payload["reason"] = auto_reason
        events = [self._event(state, command, "ClueRevealed", payload)]
        if target.damage >= 4:
            target.captured = True
            events.append(self._event(state, command, "PlayerCaptured", {"playerId": target.player_id}))
            events.append(self._end_game(state, command, target.player_id, active_player_id=context.get("attackerPlayerId")))
            return events
        if context.get("remaining"):
            events.extend(self._continue_damage(state, command, target, context))
        else:
            events.extend(self._after_damage(state, command, target, context))
        return events

    def _after_damage(self, state: EngineState, command: Command, target: Player, context: dict[str, Any]) -> list[Event]:
        trigger = context.get("trigger")
        events: list[Event] = []
        if target.rank == 6 and target.damage >= 3 and target.shield_ward_id:
            ward = state.players.get(target.shield_ward_id)
            target.shield_ward_id = None
            if ward:
                events.extend(self._return_resource(state, command, target, "sword", 1, "guardian-ward-complete"))
                events.extend(self._return_resource(state, command, ward, "shield", 1, "guardian-ward-complete"))
        # ADR 0009 (plan A): the mentalist's forced rank reveal writes the rank
        # straight into the same never-cleared lock as used/declined skills,
        # sealing it; no separate state or event exists for the seal.
        if context.get("rankRevealed") and context.get("sealSkill"):
            target.skills_used.add(str(target.rank))
        if (
            state.status == "active"
            # ADR 0009: any damage that newly reveals the rank opens the
            # window (attack/intervention/skill/reaction, forced or chosen);
            # the mentalist's forced reveal above is the sole exception.
            and context.get("rankRevealed")
            and not context.get("sealSkill")
            and target.rank in _REVEAL_SKILL_RANKS
            # the alchemist's own window still follows only its intervention
            # (corpus rank 4: "仅在自己干涉后"); other sources never open it
            and (target.rank != 4 or trigger == "intervention")
            and str(target.rank) not in target.skills_used
        ):
            state.pending = Pending("skill", target.player_id, target.player_id, rank=target.rank, trigger=trigger, context=context)
            state.phase = {"kind": "skill", "activePlayerId": target.player_id}
            return events + [self._event(state, command, "SkillWindowOpened", {"playerId": target.player_id, "rank": target.rank, "trigger": trigger})]
        state.pending = None
        if state.status == "active":
            # Attack and intervention wounds pass the dagger to the wounded
            # player; the assassin and mentalist skills hand it to their
            # victim once the damage chain settles (corpus ranks 2/5, B12);
            # other skill and reaction sources resolve via issue 20 rules.
            source = context.get("source")
            to_wounded = source in {"attack", "intervention"} or bool(context.get("daggerToTarget"))
            holder = target.player_id if to_wounded else (context.get("attackerPlayerId") or target.player_id)
            if holder in state.players and not state.players[holder].captured:
                state.dagger_holder_id = holder
                state.phase = {"kind": "action", "activePlayerId": holder}
        return events

    def _end_game(
        self,
        state: EngineState,
        command: Command,
        captured_id: str,
        *,
        active_player_id: str | None = None,
    ) -> Event:
        active_id = active_player_id or command.actor_player_id
        active = state.players.get(active_id or "")
        captured = state.players[captured_id]
        if active and active.faction == "secret-order":
            winner = "rose" if captured.faction == "beast" else "beast"
            branch = "inquisitor-active-capture"
        elif captured.faction in {"rose", "beast"} and active and active.faction in {"rose", "beast"}:
            captured_is_leader = self._is_leader(state, captured)
            winner = active.faction if captured_is_leader else ("beast" if active.faction == "rose" else "rose")
            branch = "captured-leader" if captured_is_leader else "captured-player"
        else:
            # ADR 0007: the corpus rules the captured inquisitor's line a
            # solo win for the inquisitor, not a draw; the true-curse
            # override below only rewrites family winners, so it stays out.
            winner = "secret-order"
            branch = "inquisitor-captured"
        if winner in {"rose", "beast"} and self._winning_leader_has_true_curse(state, winner):
            winner = "secret-order"
            branch = "inquisitor-true-curse"
        state.status = "ended"
        state.dagger_holder_id = None
        state.pending = None
        state.phase = {"kind": "ended"}
        ranking = self._ranking(state, winner)
        state.result = {
            "winner": winner,
            "branch": branch,
            "capturedPlayerId": captured_id,
            "activePlayerId": active_id,
            "ranking": ranking,
            "explanationKey": f"game.end.{branch}",
        }
        return self._event(state, command, "GameEnded", state.result)

    @staticmethod
    def _ranking(state: EngineState, winner: str) -> list[dict[str, Any]]:
        """Stable outcome ordering; this is an MVP ranking, not an invented card score."""
        def key(player: Player) -> tuple[int, int, int, str]:
            won = int(player.faction == winner)
            alive = int(not player.captured)
            return (-won, -alive, player.damage, player.player_id)

        return [
            {"playerId": player.player_id, "place": place, "score": int(player.faction == winner)}
            for place, player in enumerate(sorted(state.players.values(), key=key), start=1)
        ]

    @staticmethod
    def _is_leader(state: EngineState, captured: Player) -> bool:
        family = captured.faction
        if family not in {"rose", "beast"} or not isinstance(captured.rank, int):
            return False
        ranks = [
            p.rank
            for p in state.players.values()
            if p.faction == family and (p.player_id == captured.player_id or not p.captured) and isinstance(p.rank, int)
        ]
        leader_rank = max(ranks) if family in state.max_leader_factions else min(ranks)
        return captured.rank == leader_rank

    @staticmethod
    def _winning_leader_has_true_curse(state: EngineState, faction: str) -> bool:
        leaders = [
            player for player in state.players.values()
            if player.faction == faction and not player.captured and isinstance(player.rank, int)
            and RulesEngine._is_leader(state, player)
        ]
        return any(
            any(curse_id.startswith("true-curse-") and recipient == leader.player_id for curse_id, recipient in state.curse_assignments.items())
            for leader in leaders
        )

    def _require_action_actor(self, state: EngineState, command: Command) -> None:
        if state.phase.get("kind") != "action":
            raise RuleError("game.not-active")
        if command.actor_player_id != state.dagger_holder_id:
            raise RuleError("player.not-dagger-holder")

    def _require_pending(self, state: EngineState, command: Command, kind: str) -> Pending:
        if not state.pending or state.pending.kind != kind:
            raise RuleError(f"{kind}.not-open")
        return state.pending

    def _live_player(self, state: EngineState, player_id: Any) -> Player:
        player = state.players.get(str(player_id))
        if not player:
            raise RuleError("target.not-found", player_id=player_id)
        if player.captured:
            raise RuleError("target.captured", player_id=player.player_id)
        return player

    def _event(self, state: EngineState, command: Command, event_type: str, payload: dict[str, Any]) -> Event:
        return Event("pending", event_type, state.game_id, 0, self._clock(), command.command_id, payload)

    def legal_actions(self, player_id: str) -> list[dict[str, Any]]:
        """Return actions derived from authority; this is safe to use for UI affordances."""
        return _legal_actions(self.state, player_id)

    def project_state(self, viewer_player_id: str | None = None) -> dict[str, Any]:
        """Derive the visible projection for a player, or the public view for a spectator."""
        return _project_state(self.state, viewer_player_id)

    @staticmethod
    def _command_hash(command: Command) -> str:
        body = repr((command.game_id, command.actor_player_id, command.expected_revision, command.type, sorted(command.payload.items())))
        return hashlib.sha256(body.encode()).hexdigest()

    @staticmethod
    def _validate(state: EngineState) -> None:
        if len(state.players) and not 0 <= state.revision:
            raise RuleError("state.invalid", reason="negative revision")
        if state.status == "active":
            if len(state.players) < 6 or len(state.players) > 12 or not state.dagger_holder_id:
                raise RuleError("state.invalid", reason="active game invariants")
            if state.dagger_holder_id not in state.players or state.players[state.dagger_holder_id].captured:
                raise RuleError("state.invalid", reason="dagger holder")
        for player in state.players.values():
            if not 0 <= player.damage <= 4 or player.captured != (player.damage == 4):
                raise RuleError("state.invalid", reason="damage/capture", player_id=player.player_id)
            if len(player.revealed) > 3:
                raise RuleError("state.invalid", reason="revealed clues", player_id=player.player_id)
            if not isinstance(player.identity_markers, list) or len(player.identity_markers) != 2:
                raise RuleError("state.invalid", reason="identity markers", player_id=player.player_id)
            if any(not isinstance(amount, int) or amount < 0 for amount in player.resources.values()):
                raise RuleError("state.invalid", reason="negative resource", player_id=player.player_id)
