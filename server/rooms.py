"""In-memory room registry and persistence for the authoritative web server.

This module is pure standard-library plus `blood_bound`: it owns room state,
host credentials, seat assignment, auto-save, recovery after restart, and
finished-game retention. It has no web or WebSocket dependency, so it can be
unit-tested without a running server.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import secrets
import time
from pathlib import Path
from typing import Any

from blood_bound import (
    Command,
    Event,
    ReplayPlayer,
    RuleError,
    RulesEngine,
    SaveError,
    create_save_document,
    load_game,
    project_state,
    save_game,
)

from .deadlines import SINGLE_WINDOW_KINDS

FINISHED_GAMES_TO_KEEP = 20


@dataclass
class Room:
    code: str
    game_id: str
    host_token: str
    locked: bool
    status: str  # waiting | playing | ended
    engine: RulesEngine
    created_at: float
    finished_at: float | None = None
    host_player_id: str | None = None
    # Wall-clock expiry of the engine's current decision window (intervention
    # poll/choice or one of the single-player windows). The engine stays
    # deterministic (no real time in state); the room owns the countdown and
    # the server injects the deadline into projections.
    window_deadline: float | None = None
    window_stage: str | None = None

    def player_id_for_name(self, name: str) -> str | None:
        for player_id, player in self.engine.state.players.items():
            if player.display_name == name:
                return player_id
        return None

    def sync_window_deadline(self) -> None:
        """Track the current decision window's expiry; re-arms per window change."""
        key, seconds = self._window_identity(self.engine.state.pending)
        if key is None:
            self.window_deadline = None
            self.window_stage = None
            return
        if self.window_stage != key:
            self.window_stage = key
            self.window_deadline = time.time() + seconds

    def _window_identity(self, pending: Any) -> tuple[str | None, int]:
        """Stable identity of the pending window: same key = same countdown.

        The intervention stages keep their bare legacy keys ("poll"/"choice")
        so a stored meta re-arms without resetting the countdown after a
        restart. The three single-player windows (issue 05 / ADR 0011) key on
        the actor plus the eligibility frozen at open, so a damage chain that
        re-opens the same actor's reveal window re-arms a fresh countdown
        instead of inheriting a possibly-expired deadline.
        """
        state = self.engine.state
        if pending is None:
            return None, 0
        if pending.kind == "intervention":
            stage = pending.context.get("stage")
            if stage in {"poll", "choice"}:
                return str(stage), state.intervention_timeout_seconds
            return None, 0
        if pending.kind in SINGLE_WINDOW_KINDS:
            # Read the engine-frozen eligibility (context / eligible ids), the
            # same source the expiry submission guards on — never a second
            # recomputation of the rules.
            suffix = ""
            if pending.kind == "reveal":
                suffix = ":" + ",".join(pending.context.get("eligibleTokens", []))
            elif pending.kind == "token-return":
                suffix = ":" + ",".join(pending.eligible_player_ids)
            return f"{pending.kind}:{pending.actor_player_id}{suffix}", state.single_window_timeout_seconds
        return None, 0


class RoomManager:
    """Owns room state, persistence, and the finished-game retention window."""

    def __init__(self, saves_dir: str | Path) -> None:
        self.saves_dir = Path(saves_dir)
        self.saves_dir.mkdir(parents=True, exist_ok=True)
        self.rooms: dict[str, Room] = {}

    # ---- creation ------------------------------------------------------

    def create_room(self) -> Room:
        code = self._new_code()
        game_id = f"g-{secrets.token_hex(6)}"
        host_token = secrets.token_urlsafe(24)
        engine = RulesEngine.new_game(game_id, secrets.token_hex(16))
        room = Room(
            code=code,
            game_id=game_id,
            host_token=host_token,
            locked=False,
            status="waiting",
            engine=engine,
            created_at=time.time(),
        )
        self.rooms[code] = room
        self._persist(room)
        return room

    def get_room(self, code: str) -> Room | None:
        return self.rooms.get(code)

    # ---- joining -------------------------------------------------------

    def join_or_resume(self, room: Room, name: str) -> tuple[str, bool]:
        """Return ``(player_id, is_new)`` for a name, joining or resuming a seat."""
        name = name.strip()
        if not name:
            raise RuleError("player.name-required")
        existing = room.player_id_for_name(name)
        if existing is not None:
            return existing, False
        if room.status != "waiting":
            raise RuleError("room.already-started")
        if room.locked:
            raise RuleError("room.locked")
        player_id = f"p-{secrets.token_hex(6)}"
        command = Command(
            f"join-{secrets.token_hex(4)}",
            room.game_id,
            None,
            room.engine.state.revision,
            "join-game",
            {"playerId": player_id, "displayName": name},
        )
        self.apply_command(room, command)
        return player_id, True

    # ---- commands ------------------------------------------------------

    def apply_command(self, room: Room, command: Command) -> tuple[Event, ...]:
        events = room.engine.apply(command)
        room.sync_window_deadline()
        status = room.engine.state.status
        if status == "active" and room.status == "waiting":
            room.status = "playing"
        elif status == "ended" and room.status != "ended":
            room.status = "ended"
            room.finished_at = time.time()
        self._persist(room)
        if room.status == "ended":
            self._prune_finished()
        return events

    def start_game(
        self,
        room: Room,
        *,
        intervention_timeout_seconds: int | None = None,
        single_window_timeout_seconds: int | None = None,
    ) -> tuple[Event, ...]:
        payload: dict[str, Any] = {}
        if intervention_timeout_seconds is not None:
            payload["interventionTimeoutSeconds"] = int(intervention_timeout_seconds)
        if single_window_timeout_seconds is not None:
            payload["singleWindowTimeoutSeconds"] = int(single_window_timeout_seconds)
        command = Command(
            f"start-{secrets.token_hex(4)}",
            room.game_id,
            None,
            room.engine.state.revision,
            "start-game",
            payload,
        )
        return self.apply_command(room, command)

    def set_locked(self, room: Room, locked: bool) -> None:
        room.locked = locked
        self._persist(room)

    def bind_host(self, room: Room, player_id: str) -> None:
        """Record the seat held by the host-token bearer so every client can label it."""
        if room.host_player_id == player_id:
            return
        room.host_player_id = player_id
        self._write_meta(room)

    # ---- persistence ---------------------------------------------------

    def _persist(self, room: Room) -> None:
        save_game(room.engine, self._save_path(room))
        self._write_meta(room)

    def _write_meta(self, room: Room) -> None:
        meta = {
            "code": room.code,
            "gameId": room.game_id,
            "hostToken": room.host_token,
            "hostPlayerId": room.host_player_id,
            "locked": room.locked,
            "status": room.status,
            "createdAt": room.created_at,
            "finishedAt": room.finished_at,
            "windowDeadline": room.window_deadline,
            "windowStage": room.window_stage,
        }
        self._meta_path(room).write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")

    def _save_path(self, room: Room) -> Path:
        return self.saves_dir / f"{room.game_id}.json.gz"

    def _meta_path(self, room: Room) -> Path:
        return self.saves_dir / f"{room.game_id}.meta.json"

    # ---- recovery & retention -----------------------------------------

    def restore(self) -> list[Room]:
        """Load persisted rooms after a restart; finished rooms are pruned to the cap."""
        for meta_path in sorted(self.saves_dir.glob("*.meta.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            code, game_id = meta.get("code"), meta.get("gameId")
            if not code or not game_id:
                continue
            try:
                engine = load_game(self.saves_dir / f"{game_id}.json.gz")
            except (SaveError, OSError):
                continue
            self.rooms[code] = Room(
                code=code,
                game_id=game_id,
                host_token=meta.get("hostToken", ""),
                locked=bool(meta.get("locked", False)),
                status=meta.get("status", "waiting"),
                engine=engine,
                created_at=float(meta.get("createdAt", 0.0)),
                finished_at=meta.get("finishedAt"),
                host_player_id=meta.get("hostPlayerId"),
                window_deadline=meta.get("windowDeadline"),
                window_stage=meta.get("windowStage"),
            )
        self._prune_finished()
        return list(self.rooms.values())

    def _prune_finished(self) -> None:
        finished = sorted(
            (room for room in self.rooms.values() if room.status == "ended"),
            key=lambda room: room.finished_at or 0.0,
        )
        for room in finished[:-FINISHED_GAMES_TO_KEEP]:
            for path in (self._save_path(room), self._meta_path(room)):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            del self.rooms[room.code]

    # ---- replay --------------------------------------------------------

    def replay(self, room: Room) -> list[dict[str, Any]]:
        """Public (spectator) projections at each command boundary, for the replay UI."""
        player = ReplayPlayer(create_save_document(room.engine))
        steps: list[dict[str, Any]] = []
        while player.step() is not None:
            steps.append(project_state(player.engine.state, None))
        return steps

    # ---- helpers -------------------------------------------------------

    def _new_code(self) -> str:
        for _ in range(1000):
            code = f"{secrets.randbelow(10 ** 6):06d}"
            if code not in self.rooms:
                return code
        raise RuntimeError("could not allocate a unique room code")
