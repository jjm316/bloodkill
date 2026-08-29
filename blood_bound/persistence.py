"""Versioned local saves and deterministic replay for the domain engine."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit
import base64

from .engine import Command, EngineState, Event, Pending, Player, RuleError, RulesEngine


SAVE_SCHEMA_VERSION = 2
_HASH_ALGORITHM = "sha256"


class SaveError(Exception):
    """Stable, user-presentable rejection for unreadable or incompatible saves."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        self.code = code
        self.details = details
        super().__init__(message)


@dataclass(frozen=True)
class ReplayStep:
    command: Command
    events: tuple[Event, ...]
    revision: int


class ReplayPlayer:
    """Steps through a saved command stream without mutating the saved game."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        verified = validate_save_document(document)
        self._document = verified
        self._commands = tuple(_command_from_dict(item) for item in verified["commands"])
        game = verified["game"]
        self.engine = RulesEngine.new_game(str(game["gameId"]), str(game["seed"]), clock=lambda: 0.0)
        ruleset = verified["ruleset"]
        if (ruleset["id"], ruleset["version"]) != (self.engine.state.ruleset_id, self.engine.state.ruleset_version):
            raise SaveError("save.ruleset-unsupported", "This engine cannot safely replay the save's ruleset.")
        self.position = 0

    @property
    def complete(self) -> bool:
        return self.position == len(self._commands)

    def step(self) -> ReplayStep | None:
        if self.complete:
            return None
        command = self._commands[self.position]
        events = self.engine.apply(command)
        self.position += 1
        return ReplayStep(command, events, self.engine.state.revision)

    def play_to_end(self) -> RulesEngine:
        while self.step() is not None:
            pass
        return self.engine


def create_save_document(engine: RulesEngine) -> dict[str, Any]:
    """Create a portable save document from an authoritative engine state."""
    state = engine.checkpoint()
    if not state.commands and state.revision:
        raise SaveError("save.command-history-missing", "This game cannot be replayed because its command history is missing.")
    events = _event_records(state.events)
    snapshot = _state_to_dict(state)
    document = {
        "schemaVersion": SAVE_SCHEMA_VERSION,
        "ruleset": {"id": state.ruleset_id, "version": state.ruleset_version},
        "game": {"gameId": state.game_id, "seed": state.seed},
        "snapshot": snapshot,
        "events": events,
        "commands": [_command_to_dict(command) for command in state.commands],
        "integrity": {
            "algorithm": _HASH_ALGORITHM,
            "eventHead": events[-1]["hash"] if events else _empty_hash(),
            "snapshotHash": _hash(snapshot),
        },
    }
    return document


def dump_game(engine: RulesEngine, *, compressed: bool = False) -> bytes:
    payload = _canonical_json(create_save_document(engine)).encode("utf-8")
    return gzip.compress(payload, mtime=0) if compressed else payload


def save_game(engine: RulesEngine, path: str | Path, *, compressed: bool | None = None) -> Path:
    """Atomically write a JSON (or .gz) save and return its resolved path."""
    target = Path(path)
    use_gzip = target.suffix.lower() == ".gz" if compressed is None else compressed
    return _write_save_bytes(target, dump_game(engine, compressed=use_gzip))


def load_game(path: str | Path) -> RulesEngine:
    source = Path(path)
    try:
        payload = source.read_bytes()
    except OSError as error:
        raise SaveError("save.read-failed", "The save file could not be read.", path=str(source)) from error
    return load_game_bytes(payload)


def migrate_save_file(source: str | Path, target: str | Path, *, compressed: bool | None = None) -> Path:
    """Validate and rewrite a v1 or v2 save in the current portable format."""
    source_path = Path(source)
    target_path = Path(target)
    try:
        document = load_save_document(source_path.read_bytes())
    except OSError as error:
        raise SaveError("save.read-failed", "The save file could not be read.", path=str(source_path)) from error
    use_gzip = target_path.suffix.lower() == ".gz" if compressed is None else compressed
    payload = _canonical_json(document).encode("utf-8")
    return _write_save_bytes(target_path, gzip.compress(payload, mtime=0) if use_gzip else payload)


def load_game_bytes(payload: bytes) -> RulesEngine:
    document = load_save_document(payload)
    player = ReplayPlayer(document)
    try:
        engine = player.play_to_end()
    except (RuleError, ValueError, TypeError) as error:
        raise SaveError("save.replay-invalid", "The saved commands cannot be replayed by this ruleset.") from error
    if _events_without_timestamps(engine.state.events) != [
        _event_without_timestamp(record["event"]) for record in document["events"]
    ]:
        raise SaveError("save.event-replay-mismatch", "The event log does not match the recorded commands.")
    snapshot = _state_to_dict(engine.state)
    if snapshot != document["snapshot"]:
        raise SaveError("save.replay-mismatch", "The save does not reproduce its recorded game state.")
    return engine


def create_debug_link(engine: RulesEngine, base_url: str) -> str:
    """Embed a compressed save in a URL fragment, which is not sent to a server."""
    parsed = urlsplit(base_url)
    if not parsed.scheme or parsed.fragment:
        raise ValueError("base_url must be absolute and cannot already contain a fragment")
    encoded = base64.urlsafe_b64encode(dump_game(engine, compressed=True)).rstrip(b"=").decode("ascii")
    return f"{base_url}#save={encoded}"


def load_debug_link(link: str) -> RulesEngine:
    fragment = urlsplit(link).fragment
    if not fragment.startswith("save=") or "&" in fragment:
        raise SaveError("save.invalid-link", "The debug link does not contain a valid save payload.")
    encoded = fragment.removeprefix("save=")
    try:
        padding = "=" * (-len(encoded) % 4)
        payload = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as error:
        raise SaveError("save.invalid-link", "The debug link does not contain a valid save payload.") from error
    return load_game_bytes(payload)


def load_save_document(payload: bytes) -> dict[str, Any]:
    try:
        raw = gzip.decompress(payload) if payload.startswith(b"\x1f\x8b") else payload
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SaveError("save.invalid-json", "The save file is not valid JSON or gzip data.") from error
    if not isinstance(document, Mapping):
        raise SaveError("save.invalid-shape", "The save file must contain an object.")
    return validate_save_document(document)


def validate_save_document(document: Mapping[str, Any]) -> dict[str, Any]:
    migrated = migrate_save_document(document)
    _require_keys(migrated, "schemaVersion", "ruleset", "game", "snapshot", "events", "commands", "integrity")
    if migrated["schemaVersion"] != SAVE_SCHEMA_VERSION:
        raise SaveError("save.unsupported-schema", "This save was made by an unsupported version.")
    if not isinstance(migrated["events"], list) or not isinstance(migrated["commands"], list):
        raise SaveError("save.invalid-shape", "The save event and command logs must be arrays.")
    _validate_hash_chain(migrated["events"], migrated["integrity"])
    if migrated["integrity"].get("snapshotHash") != _hash(migrated["snapshot"]):
        raise SaveError("save.snapshot-corrupt", "The saved checkpoint has been changed or damaged.")
    _validate_log_shape(migrated)
    return migrated


def migrate_save_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Migrate the immediately previous save schema without changing ruleset meaning."""
    version = document.get("schemaVersion")
    if version == SAVE_SCHEMA_VERSION:
        return deepcopy(dict(document))
    if version != 1:
        raise SaveError("save.unsupported-schema", "This save was made by an unsupported version.", schemaVersion=version)
    _require_keys(document, "gameId", "seed", "rulesetId", "rulesetVersion", "checkpoint", "eventLog", "commandLog")
    events = _event_records(_event_from_dict(event) for event in document["eventLog"])
    snapshot = deepcopy(document["checkpoint"])
    migrated = {
        "schemaVersion": SAVE_SCHEMA_VERSION,
        "ruleset": {"id": document["rulesetId"], "version": document["rulesetVersion"]},
        "game": {"gameId": document["gameId"], "seed": document["seed"]},
        "snapshot": snapshot,
        "events": events,
        "commands": deepcopy(document["commandLog"]),
        "integrity": {
            "algorithm": _HASH_ALGORITHM,
            "eventHead": events[-1]["hash"] if events else _empty_hash(),
            "snapshotHash": _hash(snapshot),
        },
        "migration": {"fromSchemaVersion": 1, "toSchemaVersion": SAVE_SCHEMA_VERSION},
    }
    return migrated


def _validate_log_shape(document: Mapping[str, Any]) -> None:
    game = document["game"]
    ruleset = document["ruleset"]
    snapshot = document["snapshot"]
    if not isinstance(game, Mapping) or not isinstance(ruleset, Mapping) or not isinstance(snapshot, Mapping):
        raise SaveError("save.invalid-shape", "The save metadata is malformed.")
    _require_keys(game, "gameId", "seed")
    _require_keys(ruleset, "id", "version")
    _require_keys(snapshot, "gameId", "seed", "revision", "rulesetId", "rulesetVersion")
    if (snapshot["gameId"], snapshot["seed"]) != (game["gameId"], game["seed"]):
        raise SaveError("save.metadata-mismatch", "The save checkpoint belongs to a different game.")
    if (snapshot["rulesetId"], snapshot["rulesetVersion"]) != (ruleset["id"], ruleset["version"]):
        raise SaveError("save.metadata-mismatch", "The save checkpoint uses a different ruleset.")
    last_revision = 0
    for record in document["events"]:
        event = record.get("event") if isinstance(record, Mapping) else None
        if not isinstance(event, Mapping):
            raise SaveError("save.invalid-event", "An event entry is malformed.")
        _require_keys(event, "eventId", "eventType", "gameId", "revision", "timestamp", "commandId", "payload")
        if event["gameId"] != game["gameId"] or event["revision"] != last_revision + 1:
            raise SaveError("save.event-order", "The event revisions are not continuous.")
        last_revision = event["revision"]
    if snapshot["revision"] != last_revision:
        raise SaveError("save.revision-mismatch", "The checkpoint revision does not match the event log.")


def _validate_hash_chain(events: Iterable[Any], integrity: Any) -> None:
    if not isinstance(integrity, Mapping) or integrity.get("algorithm") != _HASH_ALGORITHM:
        raise SaveError("save.integrity-unsupported", "The save uses an unsupported integrity algorithm.")
    previous = _empty_hash()
    last = previous
    for index, record in enumerate(events):
        if not isinstance(record, Mapping) or record.get("previousHash") != previous:
            raise SaveError("save.hash-chain-broken", "The save event chain is damaged.", eventIndex=index)
        expected = _hash({"previousHash": previous, "event": record.get("event")})
        if record.get("hash") != expected:
            raise SaveError("save.hash-chain-broken", "The save event chain is damaged.", eventIndex=index)
        previous = expected
        last = expected
    if integrity.get("eventHead") != last:
        raise SaveError("save.hash-chain-broken", "The save event chain is incomplete.")


def _state_to_dict(state: EngineState) -> dict[str, Any]:
    return {
        "schemaVersion": state.schema_version,
        "rulesetId": state.ruleset_id,
        "rulesetVersion": state.ruleset_version,
        "gameId": state.game_id,
        "seed": state.seed,
        "revision": state.revision,
        "status": state.status,
        "players": {
            player_id: {
                "playerId": player.player_id,
                "seat": player.seat,
                "displayName": player.display_name,
                "faction": player.faction,
                "rank": player.rank,
                "clueIcon": player.clue_icon,
                "identityMarkers": list(player.identity_markers),
                "damage": player.damage,
                "captured": player.captured,
                "revealed": sorted(player.revealed),
                "revealedValues": deepcopy(player.revealed_values),
                "inspections": deepcopy(player.inspections),
                "shieldWardId": player.shield_ward_id,
                "resources": deepcopy(player.resources),
                "skillsUsed": sorted(player.skills_used),
            }
            for player_id, player in sorted(state.players.items())
        },
        "daggerHolderId": state.dagger_holder_id,
        "phase": deepcopy(state.phase),
        "pending": _pending_to_dict(state.pending),
        "result": deepcopy(state.result),
        "curses": list(state.curses),
        "curseAssignments": dict(sorted(state.curse_assignments.items())),
        "maxLeaderFactions": sorted(state.max_leader_factions),
        "lastEventRevision": state.revision,
    }


def _pending_to_dict(pending: Pending | None) -> dict[str, Any] | None:
    if pending is None:
        return None
    return {
        "kind": pending.kind,
        "actorPlayerId": pending.actor_player_id,
        "targetPlayerId": pending.target_player_id,
        "eligiblePlayerIds": list(pending.eligible_player_ids),
        "rank": pending.rank,
        "trigger": pending.trigger,
        "context": deepcopy(pending.context),
    }


def _command_to_dict(command: Command) -> dict[str, Any]:
    return {
        "commandId": command.command_id,
        "gameId": command.game_id,
        "actorPlayerId": command.actor_player_id,
        "expectedRevision": command.expected_revision,
        "type": command.type,
        "payload": deepcopy(dict(command.payload)),
    }


def _command_from_dict(value: Any) -> Command:
    if not isinstance(value, Mapping):
        raise SaveError("save.invalid-command", "A command entry is malformed.")
    _require_keys(value, "commandId", "gameId", "actorPlayerId", "expectedRevision", "type", "payload")
    if not isinstance(value["payload"], Mapping):
        raise SaveError("save.invalid-command", "A command payload must be an object.")
    return Command(
        str(value["commandId"]), str(value["gameId"]), value["actorPlayerId"], int(value["expectedRevision"]),
        str(value["type"]), deepcopy(dict(value["payload"])),
    )


def _event_records(events: Iterable[Event]) -> list[dict[str, Any]]:
    previous = _empty_hash()
    records: list[dict[str, Any]] = []
    for event in events:
        event_dict = _event_to_dict(event)
        digest = _hash({"previousHash": previous, "event": event_dict})
        records.append({"event": event_dict, "previousHash": previous, "hash": digest})
        previous = digest
    return records


def _event_from_dict(value: Any) -> Event:
    if not isinstance(value, Mapping):
        raise SaveError("save.invalid-event", "An event entry is malformed.")
    _require_keys(value, "eventId", "eventType", "gameId", "revision", "timestamp", "commandId", "payload")
    return Event(str(value["eventId"]), str(value["eventType"]), str(value["gameId"]), int(value["revision"]), float(value["timestamp"]), str(value["commandId"]), deepcopy(dict(value["payload"])))


def _event_to_dict(event: Event) -> dict[str, Any]:
    return {
        "eventId": event.event_id,
        "eventType": event.event_type,
        "gameId": event.game_id,
        "revision": event.revision,
        "timestamp": event.timestamp,
        "commandId": event.command_id,
        "payload": deepcopy(event.payload),
    }


def _events_without_timestamps(events: Iterable[Event]) -> list[dict[str, Any]]:
    return [_event_without_timestamp(_event_to_dict(event)) for event in events]


def _event_without_timestamp(event: Mapping[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in event.items() if key != "timestamp"}


def _require_keys(value: Mapping[str, Any], *keys: str) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        raise SaveError("save.missing-field", "The save is missing required data.", fields=missing)


def _empty_hash() -> str:
    return hashlib.sha256(b"blood-bound-save-v2").hexdigest()


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _write_save_bytes(target: Path, payload: bytes) -> Path:
    temporary = target.with_name(f"{target.name}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(target)
    except OSError as error:
        raise SaveError("save.write-failed", "The save could not be written.", path=str(target)) from error
    return target
