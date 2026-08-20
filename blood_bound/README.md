# Blood Bound domain engine

`RulesEngine` is a pure Python command processor. It has no web, database, or UI dependency.

```python
from blood_bound import Command, RulesEngine

engine = RulesEngine.new_game("game-1", "seed-1")
engine.apply(Command("join-1", "game-1", None, 0, "join-game", {
    "playerId": "p1", "displayName": "Player 1"
}))
```

The engine deep-copies authority before dispatching a command. A rejected command leaves the prior state untouched. Accepted commands append an ordered event batch, advance `revision`, and remember the command body hash for idempotent retries. Event timestamps come from an injectable clock; event IDs and revisions are assigned at commit time, so deterministic comparisons can ignore timestamps.

Implemented command paths cover setup, deterministic faction/rank assignment, dagger passing, attack resolution, intervention request/selection/decline, attack-triggered skill windows, the first two resource-producing/damaging skill paths, curse distribution, stable rule errors, and end-game branches. `legal_actions(player_id)` is derived from authority and is intended only as a client affordance; it does not bypass validation.

`run_deterministic_game()` is a headless smoke/golden-replay runner. It submits only legal public commands to finish a fixture game without UI or human input. It is not an AI player and its fixed strategy is only for proving the command loop, event ordering, terminal result, and ranking are closed.

For a process restart, persist `engine.checkpoint()` and construct a new engine with `RulesEngine.resume_from_checkpoint(checkpoint)`. The checkpoint retains the last event revision and idempotency keys, so a retried command cannot double-apply after recovery.

For a portable local save, use `save_game(engine, "game.json")`; a `.gz` filename writes deterministic gzip-compressed JSON. `load_game()` verifies the SHA-256 event chain, snapshot checksum, continuous revisions, and deterministic command replay before returning an engine. `ReplayPlayer(load_save_document(...))` exposes `step()` for a replay UI. `create_debug_link(engine, "https://host/replay")` produces a URL fragment containing the compressed save, so the payload stays client-side; `load_debug_link()` verifies it the same way. Save schema 2 accepts and explicitly migrates the immediately preceding schema-1 fixture format; migration preserves the original ruleset version instead of silently applying new rules. Convert files directly with `python -m blood_bound.migrate_save old-save.json upgraded-save.json.gz`.

Whenever a command changes `phase`, the engine appends a `PhaseChanged` event after that command's domain events. Replay consumers can therefore audit action, intervention, skill, and ended transitions without reading private state mutations.

The current ruleset intentionally does not invent behavior for source-C gaps. Additional abilities should be added as explicit command/event handlers with focused fixtures.
