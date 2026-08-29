# 03 领域模型与状态契约

状态契约面向规则引擎、存档和回放。字段名使用 ASCII `camelCase`；枚举值使用小写 kebab-free ID。契约版本独立于规则版本：`schemaVersion` 变更表示序列化形状变更，`rulesetVersion` 变更表示规则行为变更。

## 权威状态快照

`EngineState` 是服务端唯一可写状态，包含私有信息；它不能直接发送给玩家。

```json
{
  "schemaVersion": 1,
  "rulesetId": "blood-bound-compatible",
  "rulesetVersion": "0.1",
  "gameId": "g-7f3a",
  "seed": "demo-7p-001",
  "revision": 12,
  "status": "active",
  "players": {
    "p1": {
      "seat": 0,
      "displayName": "A",
      "identity": {"faction": "rose", "rank": 1},
      "clueIcon": "rose",
      "damage": 0,
      "captured": false,
      "clues": {
        "rank": {"state": "supply", "revealed": false},
        "identityMarkers": [
          {"color": "rose", "state": "supply", "revealed": false},
          {"color": "unknown", "state": "supply", "revealed": false}
        ]
      },
      "resources": {"quill": 0, "shield": 0, "sword": 0, "staff": 0, "fan": 0},
      "skills": {"elder": "available"}
    }
  },
  "factions": {
    "rose": {"playerIds": ["p1", "p3", "p5"], "active": true},
    "beast": {"playerIds": ["p2", "p4", "p6"], "active": true},
    "secret-order": {"playerIds": ["p7"], "active": true}
  },
  "supply": {
    "rankTokens": [{"playerId": "p1", "rank": 1}],
    "identityMarkers": [
      {"playerId": "p1", "color": "rose"},
      {"playerId": "p1", "color": "unknown"}
    ],
    "curses": [
      {"curseId": "true-curse-1", "kind": "true", "state": "undistributed"},
      {"curseId": "false-curse-1", "kind": "false", "state": "undistributed"}
    ]
  },
  "daggerHolderId": "p1",
  "phase": {"kind": "action", "activePlayerId": "p1"},
  "pending": null,
  "result": null
}
```

The example is abbreviated to one player; a valid snapshot always has a complete player map and token inventory. `identity` and undisplayed token values are never included in a player projection.

> 2026-08-22：线索模型由「1 rank + 1 affiliation」更正为「1 rank + 2 身份标记（红/蓝/？）」，随 [14](issues/14-abilities-resource-economy.md) 落地（含 schemaVersion 递增）。当前引擎代码仍是旧的单一 `affiliation` 形状，实现前不视为一致。

### Stable entity rules

- `playerId`, `gameId`, `curseId` and token IDs are opaque stable strings. Seat numbers are unique integers from `0` through `playerCount - 1`.
- `playerCount` is 6--12. Even games have `n/2` Rose and `n/2` Beast players. Odd games have `floor(n/2)` Rose, `floor(n/2)` Beast and exactly one Inquisitor; each Inquisitor receives one True Curse and one False Curse for distribution.
- Each family has unique ranks 1--9. An odd game has exactly one `inquisitor` identity and one `fleur-cross` rank token; the two possible Inquisitor clue icons are presentation data.
- Every player has exactly one rank token and two identity markers (each `rose`, `beast`, or `unknown`; the composition is fixed by rank — 1/5/6 two faction colors, 2/3/4 two unknowns, 7/8/9 one faction + one unknown). A token is in exactly one of `supply`, `revealed`, or `returned`; `revealed` is terminal for that token except an explicit `alchemist` return event.
- `damage` is an integer 0--4. `captured` is true iff damage is 4. A captured player cannot receive commands or be selected as a live target.
- Exactly one live player holds the dagger while `status = active`; no dagger exists after `status = ended`.
- `pending` is non-null only for an open response/choice window and includes the originating command event ID. At most one window is open.
- A `shield` blocks attack and forced-damage targeting but does not block being chosen as an intervention responder. A `fan` blocks other players from intervening for its holder. A Guardian's `sword`/matching `shield` return is represented by events, not inferred by clients.
- A skill's direct damage is marked `source = skill` and cannot open an intervention or skill window. Rank revealed by attack damage is marked `trigger = attack`; only that path can open a skill window.
- Once `status = ended`, `result` is complete and every gameplay command is rejected.

## Player projection

`PlayerView` is derived per request from `EngineState` and `viewerPlayerId`. It may contain public player IDs, seats, display names, clue icons, damage, captured state, revealed token kinds/values, resources visible to that viewer, phase, pending window eligible actions, and result. It must omit:

- every other player's hidden `identity`;
- values of rank/identity-marker tokens whose state is `supply` or `returned`;
- the Inquisitor's private curse assignments and any private Harlequin inspection;
- commands or choices for which the viewer is not eligible.

The projection is not persisted as authority. A stale projection is replaced by a fresh projection after each accepted event.

## Commands

Commands have `{commandId, gameId, actorPlayerId, expectedRevision, type, payload}`. `commandId` is an idempotency key; a repeated accepted ID returns the original event result, while a reused ID with a different body is rejected.

| Type | Payload | Legal phase |
| --- | --- | --- |
| `join-game` | `playerId`, `displayName`, optional `seat` | setup |
| `start-game` | `seed` | setup, when 6--12 players joined |
| `pass-dagger` | `targetPlayerId` | action, actor is dagger holder |
| `attack` | `targetPlayerId` | action, actor is dagger holder |
| `request-intervention` | none | intervention, actor is attack target |
| `choose-intervention` | `responderPlayerId` | intervention, actor is attack target |
| `decline-intervention` | none | intervention, actor is attack target |
| `choose-skill` | `use: true/false`, optional target/option | skill window, actor is skill owner |
| `distribute-curse` | `assignments` | setup/curse window, Inquisitor only |

Ability-specific target checks are made after the skill owner chooses the ability. There is no public command to deal damage, reveal a token, grant a resource, end a game, or set a winner.

## Events

All events carry `{eventId, eventType, gameId, revision, timestamp, commandId, payload}`. The timestamp is supplied by an injected clock and is excluded from deterministic rule comparisons.

Core event types:

`GameCreated`, `PlayerJoined`, `GameStarted`, `DaggerPassed`, `AttackDeclared`, `InterventionOpened`, `InterventionSelected`, `InterventionDeclined`, `DamageApplied`, `ClueRevealed`, `SkillWindowOpened`, `SkillUsed`, `SkillDeclined`, `ResourceGranted`, `ResourceSpent`, `ResourceReturned`, `CurseViewed`, `CurseDistributed`, `PlayerCaptured`, `GameEnded`.

`DamageApplied` records `source` (`attack`, `intervention`, `skill`, `reaction`), `amount`, `targetPlayerId`, and `triggerContext`; it never silently mutates damage. `GameEnded` records a discriminated `result` with `winner` (`rose`, `beast`, `secret-order`, or `draw`), `branch`, `capturedPlayerId`, `activePlayerId`, and a human-readable explanation key plus structured arguments.

## State transitions

```text
setup --start-game--> action
action --pass-dagger--> action
action --attack--> intervention? --resolve--> damage/reveal --skill-window?--> action
action --attack (no intervention)--> damage/reveal --skill-window?--> action
damage/reveal --4th damage--> ended
curse window --publish true curse--> ended
```

The engine owns the transition from an accepted command to a sequence of events. The transition is atomic: either all events for a command are appended in order, or none are appended.

## Legality and error codes

The validator returns a stable machine code and structured details. Suggested codes are:

`game.not-found`, `game.not-setup`, `game.not-active`, `game.already-ended`, `game.player-count`, `game.duplicate-player`, `game.seat-occupied`, `game.revision-conflict`, `command.duplicate-id`, `command.id-reuse`, `player.not-actor`, `player.not-dagger-holder`, `player.not-eligible`, `target.not-found`, `target.captured`, `target.shielded`, `target.has-fan`, `target.already-three-damage`, `intervention.not-open`, `intervention.not-eligible`, `intervention.rank-not-in-supply`, `intervention.already-resolved`, `skill.not-open`, `skill.already-used`, `skill.invalid-target`, `resource.unavailable`, `curse.invalid-count`, `curse.duplicate-recipient`, `state.invalid`.

`expectedRevision` mismatches are rejected before rule evaluation. Error details include the offending player/target/token IDs and the current phase; they never disclose hidden identity or curse data to an unauthorized viewer.

## Serialization and compatibility

- JSON is the wire and fixture format. Omit no required field; use `null` only where the schema explicitly permits it. Unknown fields must be ignored by readers and preserved by read-modify-write tools.
- `schemaVersion` uses integer major versions. Additive optional fields keep the same major version; removing/renaming fields increments it. Readers must support the current and immediately previous major version.
- `rulesetVersion` is immutable on a Game. A migration may transform snapshots/events only when a declared migrator exists; it must record `Migrated` metadata with source and target versions and never reinterpret an old event silently.
- Event payloads are append-only. New event types are ignored by older projections but make an old engine refuse to continue play rather than guess.
- Snapshots contain `lastEventRevision`; recovery verifies the event hash chain (when present) and replays events after that revision.

## Minimal fixtures

`setup/even-player-factions` and `setup/odd-player-inquisitor` from [the rules corpus](rules-corpus-user-extract.md) are the canonical setup fixtures. The following 7-player fixture fixes the shape without fixing random assignment values:

```json
{
  "playerCount": 7,
  "factions": {"rose": 3, "beast": 3, "secret-order": 1},
  "curseCount": 1,
  "inquisitorRankToken": "fleur-cross",
  "daggerHolderId": "p1",
  "phase": {"kind": "action", "activePlayerId": "p1"},
  "pending": null
}
```

The fixture is intentionally identity-neutral: tests that need a specific rank use explicit player identities and token inventory, then validate the same invariants.
