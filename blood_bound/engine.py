from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import random
import time
from typing import Any, Callable, Mapping

from .projection import legal_actions as _legal_actions, project_state as _project_state


Clock = Callable[[], float]


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
    damage: int = 0
    captured: bool = False
    revealed: set[str] = field(default_factory=set)
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
    events: list[Event] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)
    command_results: dict[str, tuple[tuple[Event, ...], str]] = field(default_factory=dict)


# Ranks whose reveal-triggered skill is implemented in this ruleset version.
# Issue 14 expands this to ranks 1--9 as abilities land; the Inquisitor's
# fleur-cross rank is a setup-phase curse ability, never a reveal-triggered skill.
_IMPLEMENTED_SKILL_RANKS = frozenset({1, 2})


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
                schema_version=1,
                ruleset_id="blood-bound-compatible",
                ruleset_version="0.1",
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
        if checkpoint.schema_version != 1:
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
            "request-intervention": self._request_intervention,
            "choose-intervention": self._choose_intervention,
            "decline-intervention": self._decline_intervention,
            "choose-skill": self._choose_skill,
            "distribute-curse": self._distribute_curse,
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
        holder = rng.choice(ordered)
        state.status = "active"
        state.dagger_holder_id = holder.player_id
        state.phase = {"kind": "action", "activePlayerId": holder.player_id}
        if count % 2:
            state.curses = ["curse-1"]
        return [
            self._event(
                state,
                command,
                "GameStarted",
                {
                    "playerCount": count,
                    "daggerHolderId": holder.player_id,
                    "curseCount": len(state.curses),
                },
            )
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
        state.pending = Pending("intervention", target.player_id, target.player_id, eligible, context={"attackerPlayerId": actor.player_id})
        state.phase = {"kind": "intervention", "activePlayerId": target.player_id}
        return [self._event(state, command, "AttackDeclared", {"attackerPlayerId": actor.player_id, "targetPlayerId": target.player_id})]

    def _request_intervention(self, state: EngineState, command: Command) -> list[Event]:
        pending = self._require_pending(state, command, "intervention")
        if pending.actor_player_id != command.actor_player_id:
            raise RuleError("player.not-actor")
        if not pending.eligible_player_ids:
            return self._resolve_damage(state, command, pending.target_player_id or "", "attack")
        pending.context["requested"] = True
        return [self._event(state, command, "InterventionOpened", {"targetPlayerId": pending.target_player_id, "eligiblePlayerIds": list(pending.eligible_player_ids)})]

    def _choose_intervention(self, state: EngineState, command: Command) -> list[Event]:
        pending = self._require_pending(state, command, "intervention")
        if not pending.context.get("requested"):
            raise RuleError("intervention.not-open")
        if pending.actor_player_id != command.actor_player_id:
            raise RuleError("player.not-actor")
        responder = self._live_player(state, command.payload.get("responderPlayerId"))
        if responder.player_id not in pending.eligible_player_ids:
            raise RuleError("intervention.not-eligible", player_id=responder.player_id)
        active_player_id = pending.context.get("attackerPlayerId", command.actor_player_id)
        state.pending = None
        state.phase = {"kind": "action", "activePlayerId": responder.player_id}
        events = [self._event(state, command, "InterventionSelected", {"responderPlayerId": responder.player_id})]
        events.extend(
            self._apply_damage(
                state,
                command,
                responder.player_id,
                1,
                "intervention",
                trigger="intervention",
                active_player_id=active_player_id,
            )
        )
        return events

    def _decline_intervention(self, state: EngineState, command: Command) -> list[Event]:
        pending = self._require_pending(state, command, "intervention")
        if pending.actor_player_id != command.actor_player_id:
            raise RuleError("player.not-actor")
        active_player_id = pending.context.get("attackerPlayerId", command.actor_player_id)
        state.pending = None
        target_id = pending.target_player_id or ""
        state.phase = {"kind": "action", "activePlayerId": target_id}
        return [self._event(state, command, "InterventionDeclined", {"targetPlayerId": target_id})] + self._resolve_damage(
            state, command, target_id, "attack", active_player_id=active_player_id
        )

    def _choose_skill(self, state: EngineState, command: Command) -> list[Event]:
        pending = self._require_pending(state, command, "skill")
        if pending.actor_player_id != command.actor_player_id:
            raise RuleError("player.not-actor")
        owner = state.players[pending.actor_player_id]
        use = bool(command.payload.get("use", False))
        state.pending = None
        state.phase = {"kind": "action", "activePlayerId": state.dagger_holder_id}
        if not use:
            return [self._event(state, command, "SkillDeclined", {"playerId": owner.player_id, "rank": owner.rank})]
        skill_id = str(owner.rank)
        if skill_id in owner.skills_used:
            raise RuleError("skill.already-used")
        owner.skills_used.add(skill_id)
        events = [self._event(state, command, "SkillUsed", {"playerId": owner.player_id, "rank": owner.rank})]
        if owner.rank == 1:
            owner.resources["quill"] += 1
            events.append(self._event(state, command, "ResourceGranted", {"playerId": owner.player_id, "resource": "quill", "amount": 1}))
        elif owner.rank == 2:
            target = self._live_player(state, command.payload.get("targetPlayerId"))
            if target.player_id == owner.player_id:
                raise RuleError("skill.invalid-target")
            events.extend(self._apply_damage(state, command, target.player_id, 2, "skill", trigger=None))
            state.dagger_holder_id = target.player_id
            state.phase = {"kind": "action", "activePlayerId": target.player_id}
        return events

    def _distribute_curse(self, state: EngineState, command: Command) -> list[Event]:
        if state.status != "active" or not state.curses:
            raise RuleError("curse.invalid-count")
        actor = state.players.get(command.actor_player_id or "")
        if not actor or actor.faction != "secret-order":
            raise RuleError("player.not-eligible")
        assignments = command.payload.get("assignments")
        if not isinstance(assignments, Mapping) or set(assignments) != set(state.curses):
            raise RuleError("curse.invalid-count")
        recipients = list(assignments.values())
        if len(set(recipients)) != len(recipients):
            raise RuleError("curse.duplicate-recipient")
        for player_id in recipients:
            self._live_player(state, player_id)
        events = [
            self._event(
                state,
                command,
                "CurseDistributed",
                {"curseId": curse_id, "recipientPlayerId": assignments[curse_id]},
            )
            for curse_id in state.curses
        ]
        state.curses = []
        return events

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
    ) -> list[Event]:
        target = self._live_player(state, target_id)
        if target.resources.get("shield", 0) and source in {"attack", "skill", "reaction"}:
            raise RuleError("target.shielded", player_id=target_id)
        events = [self._event(state, command, "DamageApplied", {"targetPlayerId": target_id, "amount": amount, "source": source, "triggerContext": trigger})]
        rank_revealed_by_this_damage = False
        for _ in range(amount):
            target.damage += 1
            clue = "rank" if "rank" not in target.revealed else "affiliation"
            target.revealed.add(clue)
            rank_revealed_by_this_damage = rank_revealed_by_this_damage or clue == "rank"
            events.append(self._event(state, command, "ClueRevealed", {"playerId": target_id, "kind": clue, "value": target.rank if clue == "rank" else target.faction}))
            if target.damage >= 4:
                target.captured = True
                events.append(self._event(state, command, "PlayerCaptured", {"playerId": target_id}))
                events.append(self._end_game(state, command, target_id, active_player_id=active_player_id))
                break
        if (
            target.damage < 4
            and source == "attack"
            and trigger == "attack"
            and rank_revealed_by_this_damage
            and target.rank in _IMPLEMENTED_SKILL_RANKS
        ):
            target_rank = target.rank
            state.pending = Pending("skill", target_id, target_id, rank=target_rank, trigger="attack")
            state.phase = {"kind": "skill", "activePlayerId": target_id}
            events.append(self._event(state, command, "SkillWindowOpened", {"playerId": target_id, "rank": target_rank, "trigger": "attack"}))
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
            winner = "draw"
            branch = "inquisitor-captured"
        state.status = "ended"
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
        ranks = [p.rank for p in state.players.values() if p.faction == family and not p.captured and isinstance(p.rank, int)]
        return isinstance(captured.rank, int) and captured.rank == min(ranks + [captured.rank])

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
            if len(player.revealed) > 2:
                raise RuleError("state.invalid", reason="revealed clues", player_id=player.player_id)
