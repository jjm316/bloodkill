# Blood Bound 网页协议（PROTOCOL）

服务器（FastAPI/uvicorn）是权威节点：全部规则由 `blood_bound` 引擎裁决，浏览器只收到
**按连接投影后**的状态。任何玩家的身份（阵营/位阶）、诅咒分配、私密事件都不会下发到
其他浏览器；随机种子也永不进入投影。开局徽记按规则只对本人和其右邻可见：`viewer`
块带本人 `clueIcon` 与右邻徽记 `seenNeighbourClue`，公共 `players[]` 条目不含任何
徽记字段。房主只有管理权（开始/锁定房间），不能替其他玩家操作。

## REST API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | `{"status": "ok"}` |
| `GET` | `/metrics` | 无身份信息的进程内运行指标，见“运行指标与公开部署边界”。 |
| `POST` | `/api/rooms` | 创建房间 → `{"code", "hostToken", "gameId"}`。`code` 为 6 位数字房号；`hostToken` 由房主浏览器保存在 localStorage。 |
| `GET` | `/api/rooms/{code}` | 房间概览 → `{"code", "status": "waiting|playing|ended", "locked", "playerCount"}`。不存在 → 404 `room.not-found`。 |
| `GET` | `/api/rooms/{code}/replay` | 终局回放 → `{"gameId", "steps": [GameState]}`，每步都是旁观者投影。未结束 → 409 `room.not-ended`。只保留最近 20 个已结束对局。 |

## WebSocket

连接 `ws://<host>/ws/{code}`（客户端按 `location.host` 同源推导，HTTP 页面用 ws，HTTPS 页面用 wss）。
连上后**第一条消息必须是 `hello`**。
房间不存在：accept 后先返回 `room.not-found` 错误帧（details 带 `roomCode`），随后关闭连接。

### 客户端 → 服务器

```json
{"type": "hello", "name": "小明", "token": "<hostToken 或省略>", "clientRevision": 12, "protocolVersion": "2"}
```

- `name` 为空字符串 → 旁观者（`yourPlayerId = null`，不可操作）。
- `token` 等于房主的 `hostToken` → 该连接获得 `isHost`。
- `name` 已存在于房间 → 断线重连，恢复座位（`roomStatus = playing` 时也可恢复）。
- 同一座位被新连接以同名登录 → 旧连接收到 `taken-over` 并关闭。
- `clientRevision` 为客户端最后收到的 `game.revision`，只用于诊断；服务端始终以 `state` 全量投影完成恢复。
- `protocolVersion` 与服务端不匹配时连接被拒绝，返回 `protocol.version-mismatch` 及期望版本；缺省仅用于兼容早期客户端。
- `name` 是新人：房间已开始 → 400 `room.already-started`；房间已锁定 → 403 `room.locked`；名字为空 → 400 `player.name-required`。

```json
{"type": "command", "command": "pass-dagger", "payload": {"targetPlayerId": "p-…"}, "commandId": "uuid", "expectedRevision": 12}
```

- 浏览器为每个命令生成稳定的 `commandId`；旧客户端可省略，服务器会补一个，但该命令不可安全重传。
- `expectedRevision` 必须是生成操作时看到的修订号。省略时为兼容旧客户端按服务端当前 revision 处理。
- `start-game` / `join-game` 由服务器托管，直接发送会得到 `command.server-managed`。
- 旁观者发送任何 command → `player.not-eligible`。
- 引擎拒绝的命令 → 对应 `RuleError` 错误码原样转发（见下），服务器状态不变。

```json
{"type": "host", "action": "start" | "lock" | "unlock"}
```

- 仅 `isHost` 连接可用；否则 → `room.not-host`。
- `start` 需要 6–12 名玩家，不足 → 引擎 `game.player-count`；`start` 可在消息上附带 `interventionTimeoutSeconds` 字段（干涉投票时限，开局接受一次，可选 30/60/90/120/180，缺省 90）。整数但不在可选集 → `game.invalid-timeout`；非整数类型 → `command.invalid-shape`。开始后固定，覆盖投票与三选一两阶段。

**命令清单**（其余全部由引擎拒绝）：

| 命令 | payload | 说明 |
| --- | --- | --- |
| `pass-dagger` | `{"targetPlayerId"}` | 匕首持有者传递匕首 |
| `attack` | `{"targetPlayerId"}` | 攻击目标（护盾/已捕获 → 引擎报错；审判者不可攻击已受 3 伤者，其投影攻击列表已预先过滤）；声明后自动开启干涉投票，资格集为空时直接结算 |
| `respond-intervention` | `{"volunteer": true\|false}` | 干涉投票表态，仅投票阶段的有资格未表态玩家；答后不可反悔 |
| `choose-intervention` | `{"responderPlayerId"}` | ≥2 人自愿后，被攻击者从自愿者中选一人承伤（完成干涉） |
| `decline-intervention` | `{}` | ≥2 人自愿后，被攻击者拒绝全部自愿者，攻击正常结算 |
| `choose-skill` | `{"use": true\|false, "targetPlayerId"?, "targetPlayerIds"?, "mode"?, "assignments"?}` | 技能窗口；2/5/6/8/9 使用单目标，3 使用两个目标，4 使用 `mode=heal|harm`；审判者（亮出 fleur-cross 等级开启的诅咒技能窗口）发动时携带 `assignments`（`{"curseId": "playerId"}`，键须与待分发诅咒完全一致、收件人存活且互不相同），放弃走 `use=false` |
| `choose-return` | `{"token": "rank|marker-0|marker-1"}` | rank 4 治疗窗口，治疗者退回一张已展示标记 |

规则版本 0.4 起（ADR 0003），旧的全时段常驻 `distribute-curse` 命令已移除：
诅咒分发只由审判者技能窗口内的 `choose-skill` 承载，旧命令将得到 `command.unknown`。

`start-game`、`join-game`、`timeout-intervention` 由服务器托管：直接发送会得到
`command.server-managed`。`timeout-intervention` 是干涉窗口到期时由服务端定时器
（`server/deadlines.py`，可复用抽象）代为提交的系统命令，payload 为
`{"stage": "poll"|"choice"}`；投票阶段到期未表态视为不干涉，三选一阶段到期视为全部拒绝。

### 干涉投票（协议 v2，ADR 0002）

攻击声明后服务器自动开启全员公开自愿投票（`InterventionPollOpened`，含资格名单）。
有资格玩家逐人 `respond-intervention` 表态，`InterventionResponded` 实时公开广播；
全员表态完毕后：无人自愿 → `InterventionDeclined`（reason=no-volunteers）+ 攻击正常
结算；恰一人自愿 → `InterventionSelected`，干涉必然发生；≥2 人自愿 →
`InterventionChoiceOpened` 进入被攻击者三选一阶段（`choose-intervention` /
`decline-intervention`）。倒计时 deadline 由服务端注入每个投影的
`pending.deadline`（Unix 秒），配合 `serverTime` 对齐本地时钟；引擎状态本身不含墙钟。

### 服务器 → 客户端

| 类型 | 说明 |
| --- | --- |
| `state` | 每次命令/主持操作/进出后向房间内所有连接广播，每人收到按自己视角投影的 `game`，并附服务端墙钟 `serverTime`（倒计时对齐用）。 |
| `event` | `{"events": [...]}`，仅公开事件；`CurseViewed`、`CurseDistributed` 被过滤。开局批量事件 `ClueIconsShown` 为公开事件，但 payload 只含"谁向谁展示"的关系（`pairs`），不含任何徽记内容。干涉投票的表态事件（`InterventionResponded` 等）全部公开。 |
| `error` | `{"code", "message", "details"}`。 |
| `ack` | `{"commandId", "status": "accepted|rejected", "revision", "error"?}`，只确认对应客户端命令。 |
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
  "hostPlayerId": "p-… | null（房主尚未以玩家身份连接时为 null）",
  "connected": {"p-…": true},
  "hostActions": [{"type": "start-game"}, {"type": "lock"}],
  "game": { /* GameState 投影；waiting 时也有（setup 阶段） */ },
  "serverTime": 1788537000.0
}
```

### 断线恢复与命令确认

1. 浏览器在连接关闭后以退避重连；同名 `hello` 恢复原座位。房主离开不会结束或转移房间，持有原 `hostToken` 的重连仍为房主。房主令牌持有者以玩家身份 `hello` 时，服务器把该座位记为 `hostPlayerId`（写入房间 meta，重启后保留），所有客户端据此显示房主标记。
2. `hello` 后服务器总会发送完整、按接收者投影的 `state`。客户端以它替换本地状态，不尝试补造事件；因此重连前后的 `game.revision` 与状态哈希以服务器为准。
3. 客户端仅保留尚未收到 `ack` 的命令，并以原 `commandId`、原 `expectedRevision` 重传。相同命令重复到达时服务端返回 `accepted`，但不再次广播事件或结算。
4. 新 `commandId` 携带过期 `expectedRevision` 时服务端返回 `game.revision-conflict`、`ack.status = rejected` 和最新 `state`；客户端丢弃该命令，等待用户基于新状态再次操作。
5. 同一 `commandId` 若内容不同，服务端返回 `command.id-reuse`。所有拒绝均有 `ack`，因此不会永久卡在客户端发件箱。

### 运行指标与公开部署边界

- `GET /metrics` 返回无身份信息的进程内计数：连接数、座位恢复/接管数、命令接受/拒绝数及当前连接、房间数量；进程重启后清零。它用于观察重连风暴和非法命令，不记录昵称、令牌、命令内容或私密状态。
- 局域网可使用 HTTP/WS；任何内网穿透或公网入口必须由 HTTPS/WSS 终止 TLS。不要将明文隧道、`hostToken`、存档目录或调试端点暴露到公网。

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
  "phase": {"kind": "action", "…"} | {"kind": "intervention", "stage": "poll|choice", "activePlayerId": "p-…"} | {"kind": "skill", "…"},
  "pending": {
    /* 干涉窗口额外携带：stage（poll|choice）、responses（{playerId: volunteer}，实时公开）、
       volunteerPlayerIds（自愿者名单）、deadline（服务端注入的到期 Unix 秒） */
    "kind": "intervention", "stage": "poll", "responses": {"p-…": true}, "deadline": 1788537090.0
  },
  "result": null | {"winner": "rose|beast|inquisitor", "explanationKey": "capture|…", "ranking": [{"playerId","seat"}]},
  "interventionTimeoutSeconds": 90,
  "viewer": null | {
    "playerId": "p-…",
    "identity": {"faction": "rose", "rank": 5},
    "resources": ["curse"],
    "skillsUsed": false,
    "cursesToDistribute": ["c-…"],   // 待分发诅咒卡 ID，仅审判者可见（分发后清空）；分发动作经技能窗口的 choose-skill
    "clueIcon": "rose",              // 本人阵营徽记
    "seenNeighbourClue": {"playerId": "p-…", "icon": "beast"}  // 右邻徽记，仅此一处
  },
  "legalActions": [
    {"type": "pass-dagger", "targetPlayerId": "p-…"},
    {"type": "attack", "targetPlayerId": "p-…"},
    {"type": "respond-intervention", "volunteer": true | false},
    {"type": "decline-intervention"},
    {"type": "choose-intervention", "responderPlayerId": "p-…"},
    {"type": "choose-skill", "use": true, "targetPlayerId": "p-…"}
  ]
}
```

### 隐私保证（服务器强制，客户端无法绕过）

- `viewer.identity` 只出现在投影接收者自己的 `viewer` 块里；其他玩家的 `players[]` 项**不含**阵营/位阶。
- `revealed` 只在身份被公开（受伤/被捕获）后出现。
- 投影**不含**随机种子 `seed`（知道种子即可用 `random.Random(seed)` 重现全部身份分配）。
- 阵营徽记按规则只向左邻展示：徽记只出现在被展示者的 `viewer` 块里（本人 `clueIcon` + 右邻 `seenNeighbourClue`）；`players[]` 条目、旁观者投影与回放步骤均**不含**任何徽记字段。
- `cursesToDistribute` 只在审判者自己的 `viewer` 块里。
- 事件广播过滤 `CurseViewed` / `CurseDistributed`；服务器端存档保留完整事件流，用于回放校验。

### 错误码

**服务器层**：`room.not-found`、`room.not-ended`、`room.not-host`、`room.locked`、
`room.already-started`、`player.name-required`、`player.not-eligible`（旁观者操作）、
`command.server-managed`、`command.invalid-shape`、`protocol.version-mismatch`。

**引擎层**（`RuleError` 原样转发）：`state.invalid`、`game.not-found`、`command.id-reuse`、
`game.already-ended`、`command.unknown`、`game.not-setup`、`game.duplicate-player`、
`game.player-count`、`game.seat-occupied`、`game.invalid-timeout`、`target.not-eligible`、
`target.shielded`、`target.already-three-damage`、`player.not-actor`、
`intervention.not-open`、`intervention.not-poll`、`intervention.not-choice`、
`intervention.not-eligible`、`intervention.already-responded`、`skill.already-used`、
`skill.invalid-target`、`curse.invalid-count`、`curse.duplicate-recipient`、
`game.not-active`、`player.not-dagger-holder`、`target.not-found`、`target.captured`。
