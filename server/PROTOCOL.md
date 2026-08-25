# Blood Bound 网页协议（PROTOCOL）

服务器（FastAPI/uvicorn）是权威节点：全部规则由 `blood_bound` 引擎裁决，浏览器只收到
**按连接投影后**的状态。任何玩家的身份（阵营/位阶）、诅咒分配、私密事件都不会下发到
其他浏览器；随机种子、clue icon 也永不进入投影。房主只有管理权（开始/锁定房间），
不能替其他玩家操作。

## REST API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | `{"status": "ok"}` |
| `POST` | `/api/rooms` | 创建房间 → `{"code", "hostToken", "gameId"}`。`code` 为 6 位数字房号；`hostToken` 由房主浏览器保存在 localStorage。 |
| `GET` | `/api/rooms/{code}` | 房间概览 → `{"code", "status": "waiting|playing|ended", "locked", "playerCount"}`。不存在 → 404 `room.not-found`。 |
| `GET` | `/api/rooms/{code}/replay` | 终局回放 → `{"gameId", "steps": [GameState]}`，每步都是旁观者投影。未结束 → 409 `room.not-ended`。只保留最近 20 个已结束对局。 |

## WebSocket

连接 `ws://<host>/ws/{code}`（客户端按 `location.host` 同源推导，HTTP 页面用 ws，HTTPS 页面用 wss）。
连上后**第一条消息必须是 `hello`**。

### 客户端 → 服务器

```json
{"type": "hello", "name": "小明", "token": "<hostToken 或省略>"}
```

- `name` 为空字符串 → 旁观者（`yourPlayerId = null`，不可操作）。
- `token` 等于房主的 `hostToken` → 该连接获得 `isHost`。
- `name` 已存在于房间 → 断线重连，恢复座位（`roomStatus = playing` 时也可恢复）。
- 同一座位被新连接以同名登录 → 旧连接收到 `taken-over` 并关闭。
- `name` 是新人：房间已开始 → 400 `room.already-started`；房间已锁定 → 403 `room.locked`；名字为空 → 400 `player.name-required`。

```json
{"type": "command", "command": "pass-dagger", "payload": {"targetPlayerId": "p-…"}, "commandId": "可选"}
```

- `commandId` 可省略（服务器补一个）；引擎保证命令幂等与修订号校验。
- `start-game` / `join-game` 由服务器托管，直接发送会得到 `command.server-managed`。
- 旁观者发送任何 command → `player.not-eligible`。
- 引擎拒绝的命令 → 对应 `RuleError` 错误码原样转发（见下），服务器状态不变。

```json
{"type": "host", "action": "start" | "lock" | "unlock"}
```

- 仅 `isHost` 连接可用；否则 → `room.not-host`。
- `start` 需要 6–12 名玩家，不足 → 引擎 `game.player-count`。

**命令清单**（其余全部由引擎拒绝）：

| 命令 | payload | 说明 |
| --- | --- | --- |
| `pass-dagger` | `{"targetPlayerId"}` | 匕首持有者传递匕首 |
| `attack` | `{"targetPlayerId"}` | 攻击目标（护盾/满 3 伤/已捕获 → 引擎报错） |
| `request-intervention` | `{}` | 受攻击者申请干预 |
| `choose-intervention` | `{"responderPlayerId"}` | 匕首持有者选择干预响应人 |
| `decline-intervention` | `{}` | 受攻击者放弃干预 |
| `choose-skill` | `{"use": true\|false, "targetPlayerId"?, "targetPlayerIds"?}` | 技能窗口；2/5/6/8/9 使用单目标，3 使用两个目标 |
| `distribute-curse` | `{"assignments": {"curseId": "playerId"}}` | 仅审判官；数量/重复校验由引擎完成 |

### 服务器 → 客户端

| 类型 | 说明 |
| --- | --- |
| `state` | 每次命令/主持操作/进出后向房间内所有连接广播，每人收到按自己视角投影的 `game`。 |
| `event` | `{"events": [...]}`，仅公开事件；`CurseViewed`、`CurseDistributed` 被过滤。 |
| `error` | `{"code", "message", "details"}`。 |
| `taken-over` | `{"reason": "seat taken over by a new connection"}`，随后连接被关闭。 |

### `state` 消息形状

```json
{
  "type": "state",
  "roomCode": "123456",
  "roomStatus": "waiting | playing | ended",
  "locked": false,
  "isHost": true,
  "yourPlayerId": "p-… | null（旁观者）",
  "connected": {"p-…": true},
  "hostActions": [{"type": "start-game"}, {"type": "lock"}],
  "game": { /* GameState 投影；waiting 时也有（setup 阶段） */ }
}
```

### GameState 投影形状（`blood_bound/projection.py`）

```json
{
  "gameId": "g-…",
  "revision": 12,
  "status": "setup | active | ended",
  "players": [
    {
      "playerId": "p-…", "seat": 0, "displayName": "小明",
      "damage": 1, "captured": false,
      "revealed": {"rank": 3} | {"affiliation": "beast"} | {"rank": 3, "affiliation": "beast"} | null,
      "resources": ["curse"]
    }
  ],
  "daggerHolderId": "p-…",
  "phase": {"kind": "action", "…"} | {"kind": "intervention", "…"} | {"kind": "skill", "…"},
  "pending": { /* 无上下文参数的待处理窗口，例如 {"kind":"intervention"} */ },
  "result": null | {"winner": "rose|beast|inquisitor", "explanationKey": "capture|…", "ranking": [{"playerId","seat"}]},
  "viewer": null | {
    "playerId": "p-…",
    "identity": {"faction": "rose", "rank": 5},
    "resources": ["curse"],
    "skillsUsed": false,
    "cursesToDistribute": ["c-…"]   // 仅审判官在分发阶段非空
  },
  "legalActions": [
    {"type": "pass-dagger", "targetPlayerId": "p-…"},
    {"type": "attack", "targetPlayerId": "p-…"},
    {"type": "request-intervention"},
    {"type": "decline-intervention"},
    {"type": "choose-intervention", "responderPlayerId": "p-…"},
    {"type": "choose-skill", "use": true, "targetPlayerId": "p-…"},
    {"type": "distribute-curse"}
  ]
}
```

### 隐私保证（服务器强制，客户端无法绕过）

- `viewer.identity` 只出现在投影接收者自己的 `viewer` 块里；其他玩家的 `players[]` 项**不含**阵营/位阶。
- `revealed` 只在身份被公开（受伤/被捕获）后出现。
- 投影**不含**随机种子 `seed`（知道种子即可用 `random.Random(seed)` 重现全部身份分配）与 `clueIcon`（规则：开局只向左手边玩家展示）。
- `cursesToDistribute` 只在审判官自己的 `viewer` 块里。
- 事件广播过滤 `CurseViewed` / `CurseDistributed`；服务器端存档保留完整事件流，用于回放校验。

### 错误码

**服务器层**：`room.not-found`、`room.not-ended`、`room.not-host`、`room.locked`、
`room.already-started`、`player.name-required`、`player.not-eligible`（旁观者操作）、
`command.server-managed`、`command.invalid-shape`。

**引擎层**（`RuleError` 原样转发）：`state.invalid`、`game.not-found`、`command.id-reuse`、
`game.already-ended`、`command.unknown`、`game.not-setup`、`game.duplicate-player`、
`game.player-count`、`game.seat-occupied`、`target.not-eligible`、`target.shielded`、
`target.already-three-damage`、`player.not-actor`、`intervention.not-open`、
`intervention.not-eligible`、`skill.already-used`、`skill.invalid-target`、
`curse.invalid-count`、`curse.duplicate-recipient`、`game.not-active`、
`player.not-dagger-holder`、`target.not-found`、`target.captured`。
