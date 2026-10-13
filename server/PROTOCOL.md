# Blood Bound 网页协议（PROTOCOL）

服务器（FastAPI/uvicorn）是权威节点：全部规则由 `blood_bound` 引擎裁决，浏览器只收到
**按连接投影后**的状态。对局进行中，其他玩家的身份（阵营/位阶）、诅咒真/假之分与私密事件都不会
下发到其他浏览器（ADR 0014：诅咒卡的归属例外——谁持卡是公开对局事实，经
`CurseDistributed` 广播与 `players[].holdsCurseCard` 下发，真/假仅审判者可见、终局翻开）；
随机种子也永不进入投影。开局徽记按规则只对本人和其右邻可见：`viewer`
块带本人 `clueIcon` 与右邻徽记 `seenNeighbourClue`，公共 `players[]` 条目不含任何
徽记字段。房主只有管理权（开始/锁定房间），不能替其他玩家操作。

终局身份揭晓（ADR 0015）：仅 `status="ended"` 的公共 `players[]` 增加
`identity: {"faction": "rose|beast|secret-order", "rank": 1..9|"fleur-cross"}`。
玩家、旁观者、刷新与重连、回放末帧都能读取全员真实身份；进行中和回放此前各帧不带
此字段。个人胜负读取 `result.ranking[].score`（1 胜、0 负），`place` 是排序序号，
不是角色等级。新增字段不改变存档或胜负规则。

协议版本：当前 v4（2026-10-13，ADR 0016）。v3 → v4 切换到 Cookie 账号会话，
旧姓名/房主令牌握手及缺失版本均须刷新客户端。此前 v2 → v3（ADR 0012）在干涉投票前新增被攻击者
挡刀请求门控（`answer-intervention-request` 命令、`InterventionGate*` 三个事件、
pending `stage:"gate"`、错误码 `intervention.not-gate` / `intervention.not-target`），
旧版本客户端与旧服务端互拒。

## REST API

### 注册与登录身份

`POST /api/auth/register` 接收 JSON `{username, password, confirmPassword}`。用户名为
2–16 个中文、ASCII 英文字母、数字或下划线，英文字母不区分大小写，公开名字保留注册写法。
密码为 6–12 个原字符，确认须完全相同，不截断、不去空白。
成功返回 201 `{account: {accountId, username}}`，同时设置 `bloodbound_session` Cookie
（HttpOnly、SameSite=strict、Path=/、Max-Age=2592000）。服务端固定 30 天到期，不滚动续期。
账号与会话持久化在存档目录独立的 `accounts/accounts.sqlite3`，与房间清理隔离。

`GET /api/auth/session` 使用 Cookie 恢复身份，成功返回相同公开账号对象，未登录或过期返回
401 `auth.login-required`。响应不含密码摘要或会话凭证，身份响应禁用缓存。
注册错误为 400 `auth.invalid-username` / `auth.invalid-password` / `auth.password-mismatch`
/ `auth.invalid-input`，重名为 409 `auth.username-taken`，存储不可用为
503 `auth.service-unavailable`；`message` 均为中文且不回显输入。

`POST /api/auth/login` 接收 JSON `{username, password}`，用户名英文大小写变体登录同一账号，
密码精确匹配原字符。成功返回 200 `{account: {accountId, username}}`，用户名保留注册写法，
并建立新的固定 30 天 Cookie 会话；独立设备的既有会话仍有效，查询身份不会续期。
未知账号、错误密码或缺失凭证均返回 401 `auth.invalid-credentials`，反馈为“账号或密码不正确”。
非对象或无效 JSON 返回 400 `auth.invalid-input`，存储不可用返回 503 `auth.service-unavailable`。
失败不设置或替换 Cookie，也不改变已有有效身份。注册与登录均拒绝非本站 Origin（403
`auth.invalid-origin`）；密码只放 JSON 请求体，不进入 URL 或响应。

`POST /api/auth/logout` 撤销**当前设备**的登录会话：成功返回 200 `{account}` 并以 Max-Age=0
清除浏览器 Cookie；其他设备的独立登录不受影响。退出同时停止该会话已建立的房间 WebSocket
（连接收到 `auth.session-revoked` 错误帧后关闭），但不移除座位、不改变房主归属；重新登录
同账号可恢复原座位。无会话或已退出的凭证返回 401 `auth.login-required`，重放不能恢复身份。

`POST /api/auth/password` 接收 JSON `{oldPassword, newPassword, confirmPassword}`，验证旧密码后
设置新密码（6–12 个字符、确认完全相同，规则与注册一致）。成功返回 200 `{account}`：**当前
登录保留原有效期**（Cookie 与固定 30 天到期点均不变），同账号**其他设备的全部登录被撤销**
并停止其已建立的房间 WebSocket（连接收到 `auth.password-changed` 中文错误帧后关闭）；座位
与房主归属不变，其他设备用新密码重新登录即可恢复原身份。旧密码不正确返回 400
`auth.wrong-old-password`；新密码越界/确认不一致返回 400 `auth.invalid-password` /
`auth.password-mismatch`；未登录 401 `auth.login-required`；非本站 Origin 403
`auth.invalid-origin`；存储不可用 503 `auth.service-unavailable`。任何失败都不改变原密码与
既有会话；密码只放 JSON 请求体，不进入 URL、日志或响应。

会话到期（固定 30 天，不滚动续期）后所有 HTTP 请求视为未登录；**此前已建立的 WebSocket**
在下一条消息或房间广播时被终止（`auth.session-expired` 错误帧 + 关闭），旧连接不能再发送
合法动作、也收不到后续私有投影；同房其他有效会话的连接不受影响。

本节覆盖工单 07–08 注册、登录、身份恢复、工单 14 退出/过期切片与工单 15 主动改密；管理重置密码由后续账号工单扩展。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | `{"status": "ok"}` |
| `GET` | `/metrics` | 无身份信息的进程内运行指标，见“运行指标与公开部署边界”。 |
| `POST` | `/api/rooms` | 当前登录账号创建房间并立即成为房主、占据自己的座位 → `{"code", "gameId"}`。`code` 为 6 位数字房号；同一房主重试返回既有未结束房间。没有会话 → 401 `auth.login-required`；已有普通玩家占用 → 409 `account.room-occupied`，details.roomCode 提供恢复目标。 |
| `GET` | `/api/account/room` | 当前登录账号的未结束占用 → `{"room": {"code", "status"} | null}`；用于刷新及创建回复丢失后的恢复。没有会话 → 401。 |
| `GET` | `/api/rooms/{code}` | 房间概览 → `{"code", "status": "waiting|playing|ended", "locked", "playerCount"}`。不存在 → 404 `room.not-found`。 |
| `GET` | `/api/rooms/{code}/replay` | 登录可看的终局回放 → `{"gameId", "steps": [GameState]}`，每步都是旁观者投影；任意已登录账号（含非参与者）知道房号即可观看。没有会话 → 401 `auth.login-required`；未正常结束（等待/进行，将来的管理关闭也非正常终局）→ 409 `room.not-ended`；不存在 → 404 `room.not-found`，`message` 均为中文。只保留最近 20 个已结束对局；清理只删除对局存档，不触碰账号、会话、占用或管理备份数据。 |

## WebSocket

连接 `ws://<host>/ws/{code}`（客户端按 `location.host` 同源推导，HTTP 页面用 ws，HTTPS 页面用 wss）。
连上后**第一条消息必须是 `hello`**。
房间不存在：accept 后先返回 `room.not-found` 错误帧（details 带 `roomCode`），随后关闭连接。

### 客户端 → 服务器

```json
{"type": "hello", "mode": "player", "clientRevision": 12, "protocolVersion": "4"}
```

- WebSocket 握手必须携带有效 `bloodbound_session` Cookie；身份不放 URL 或 hello。
- 会话过期或被退出撤销后：重连被 `auth.login-required` 拒绝；**此前已建立的连接**在发送任何
  消息或房间下一次广播时收到 `auth.session-expired`（过期）或 `auth.session-revoked`（退出撤销，
  工单 14）错误帧并关闭，不能再发送合法动作、收不到后续私有投影；同房其他有效会话不受影响。
  改密撤销（工单 15）同理：其他设备的已建立连接收到 `auth.password-changed` 后关闭，
  当前设备的连接照常使用。
- `mode="spectator"` → 公开投影（`yourPlayerId = null`，不可发送玩家命令）。
- 房主账号的稳定引用与房间 hostAccountId 相等 → `isHost`；其他账号不能开始或锁定。
- `mode="player"` 按当前账号恢复或建立座位，不按客户端姓名认领；同账号已有座位在锁房/开局后可恢复。
- hello 中出现旧 `name` 或 `token` 字段 → `protocol.legacy-identity`，中文提示刷新。
- 同一座位只允许一个活动玩家连接：新设备/新会话以 player 进入后接管座位，旧连接收到
  `taken-over` 并被关闭，不再有后续投影、事件或私有帧；接管不撤销旧设备的账号登录，
  旧设备返回大厅后可再进入（再次接管）。旧连接在关闭竞态窗口内挤入的命令或房主消息
  一律收到 `seat.taken-over` 拒绝（命令拒绝仍带 ack），不改变引擎状态。
- `clientRevision` 为客户端最后收到的 `game.revision`，只用于诊断；服务端始终以 `state` 全量投影完成恢复。
- `protocolVersion` 与服务端不匹配或缺失时连接被拒绝，返回 `protocol.version-mismatch` 及期望版本。
- 当前账号没有本房座位时按新人加入判断：账号在**其他**未结束房间已占座 → `account.room-occupied`（你已有未结束房间，请返回原房间），details.roomCode 提供恢复目标；
  房间已结束 → `room.ended`（对局已结束，不能加入；可观看回放）；
  已开始 → `room.already-started`（游戏已开始，不能加入；若已在房间，返回原房间即可恢复座位）；
  已锁定 → `room.locked`（房间已锁定，暂不能加入）；已满 12 人 → `room.full`（房间已满员，不能加入）。
  拒绝均为中文 `message`，被拒连接随即关闭且不产生座位或占用。
- 一个账号同时最多占据一个未结束房间的玩家座位（工单 12）：创建与加入共用同一原子占用检查，多个设备并发创建或加入不同房间时最终只有一次有效占用；本人恢复原房不算新占用。正常终局自动释放该房全部玩家的占用。

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
- `start` 需要 6–12 名玩家，不足 → 引擎 `game.player-count`；`start` 可在消息上附带 `interventionTimeoutSeconds`（干涉投票时限）与 `singleWindowTimeoutSeconds`（单人窗口超时，ADR 0011）两个字段（各自在开局接受一次，可选 30/60/90/120/180，缺省 90）。整数但不在可选集 → `game.invalid-timeout`；非整数类型 → `command.invalid-shape`。开始后固定。

**命令清单**（其余全部由引擎拒绝）：

| 命令 | payload | 说明 |
| --- | --- | --- |
| `pass-dagger` | `{"targetPlayerId"}` | 匕首持有者传递匕首 |
| `attack` | `{"targetPlayerId"}` | 攻击目标（护盾/已捕获 → 引擎报错；审判者不可攻击已受 3 伤者，其投影攻击列表已预先过滤）；声明后先开被攻击者的挡刀请求门控（ADR 0012），资格集为空时不开门控直接结算 |
| `answer-intervention-request` | `{"need": true\|false}` | 挡刀请求门控确认，仅门控阶段的被攻击者本人；「请求挡刀」开启干涉投票，「自己承受」攻击立即在原目标结算 |
| `respond-intervention` | `{"volunteer": true\|false}` | 干涉投票表态，仅投票阶段的有资格未表态玩家；答后不可反悔 |
| `choose-intervention` | `{"responderPlayerId"}` | ≥2 人自愿后，被攻击者从自愿者中选一人承伤（完成干涉） |
| `decline-intervention` | `{}` | ≥2 人自愿后，被攻击者拒绝全部自愿者，攻击正常结算 |
| `choose-skill` | `{"use": true\|false, "targetPlayerId"?, "targetPlayerIds"?, "mode"?, "assignments"?}` | 技能窗口；2/5/6/8/9 使用单目标，3 使用两个目标，4 使用 `mode=heal|harm`；审判者（亮出 fleur-cross 等级开启的诅咒技能窗口）发动时携带 `assignments`（`{"curseId": "playerId"}`，键须与待分发诅咒完全一致、收件人存活且互不相同），放弃走 `use=false` |
| `choose-return` | `{"token": "rank|marker-0|marker-1"}` | rank 4 治疗窗口，治疗者退回一张已展示标记 |

规则版本 0.4 起（ADR 0003），旧的全时段常驻 `distribute-curse` 命令已移除：
诅咒分发只由审判者技能窗口内的 `choose-skill` 承载，旧命令将得到 `command.unknown`。

`start-game`、`join-game`、`timeout-intervention`、`timeout-reveal`、`timeout-skill`、
`timeout-return` 由服务器托管：直接发送会得到 `command.server-managed`。
`timeout-intervention` 是干涉三段窗口到期时由服务端定时器（`server/deadlines.py`，可复用抽象）
代为提交的系统命令，payload 为 `{"stage": "gate"|"poll"|"choice"}`；门控阶段到期未确认
视为不需要挡刀并立即结算，投票阶段到期未表态视为不干涉，
三选一阶段到期视为全部拒绝。

三条单人窗口超时命令（issue 05 / ADR 0011）走同一套定时器抽象，payload 携带窗口身份
（`{"actorPlayerId", "eligibleTokens"?}`，引擎与权威状态复核，过期/错窗提交被拒）：

| 命令 | 到期默认 |
| --- | --- |
| `timeout-reveal` | 自动亮排序第一张（marker-0 → marker-1 → rank 确定序；wild 标记取「？」） |
| `timeout-skill` | 视为放弃：按 ADR 0008 写入 `skills_used`，技能永久失去 |
| `timeout-return` | 自动退排序第一张已亮标记（marker 先于 rank，保持亮槽数 = 伤害数） |

超时自动结算的 `ClueRevealed` / `SkillDeclined` / `TokenReturned` 事件携带
`"reason": "timeout"`，事件日志据此后缀显示「（超时自动）」。

### 干涉三段窗口：请求门控 → 全员投票 → 三选一（协议 v3，ADR 0012）

2026-10-04 裁决（ADR 0012）：攻击声明后不再自动开启全员投票，先开**仅被攻击者本人**
作答的挡刀请求门控；门控放行后投票与三选一照 ADR 0002 原样运行。三个窗口依次为：

1. **gate（请求门控）**：`attack` 后若挡刀资格集非空，引擎广播
   `InterventionGateOpened {targetPlayerId, attackerPlayerId, eligiblePlayerIds}` 并进入
   `stage:"gate"` 的 pending；资格集为空（如目标持扇）则**不开门控**、攻击直接结算。
   门控期间只有被攻击者持有 `answer-intervention-request` 动作，其余玩家（含攻击者与
   有资格玩家）无任何动作，只看到等待；
   - `need=true` → `InterventionGateAccepted {targetPlayerId}`，随后紧跟
     `InterventionPollOpened {targetPlayerId, attackerPlayerId, eligiblePlayerIds}`（字段
     与 GateOpened 相同），进入全员投票；
   - `need=false` → `InterventionGateDeclined {targetPlayerId, reason:"target-declined"}`，
     攻击立即在原目标按无人自愿的既有路径结算（此路径不发 `InterventionDeclined`）；
   - 到期未答 → 服务端代发 `timeout-intervention {"stage": "gate"}`，
     `InterventionGateDeclined {targetPlayerId, reason:"timeout"}`，同样立即结算。
2. **poll（全员公开自愿投票，ADR 0002 语义原样）**：有资格玩家逐人
   `respond-intervention` 表态，`InterventionResponded` 实时公开广播；全员表态完毕后：
   无人自愿 → `InterventionDeclined`（reason=no-volunteers）+ 攻击正常结算；恰一人自愿 →
   `InterventionSelected`，干涉必然发生；≥2 人自愿 → `InterventionChoiceOpened` 进入
   被攻击者三选一阶段（`choose-intervention` / `decline-intervention`）。
3. **choice（三选一）**：与 v2 完全一致，无改动。

三个窗口各自独立起算倒计时，且都复用房主开局配置的 `interventionTimeoutSeconds`
（不新增配置项）。deadline 由服务端注入每个投影的 `pending.deadline`（Unix 秒），配合
`serverTime` 对齐本地时钟；引擎状态本身不含墙钟，到期由服务端代发对应 timeout 命令。
单人窗口（亮牌/技能/退牌，ADR 0011）同样携带 `pending.deadline`，到期由服务端代发
上表的 timeout 命令自动结算，对局不停摆。

### 服务器 → 客户端

| 类型 | 说明 |
| --- | --- |
| `state` | 每次命令/主持操作/进出后向房间内所有**已完成 hello** 的连接广播（未完成握手的连接不参与，不会收到空视角投影），每人收到按自己视角投影的 `game`，并附服务端墙钟 `serverTime`（倒计时对齐用）。 |
| `event` | `{"events": [...]}`，仅公开事件；`CurseViewed`（保留字）被过滤。诅咒归属已公开（ADR 0014）：`CurseDistributed` 为公开广播，payload 只含 `{"recipientPlayerId": "p-…"}`（每卡一条，不含 curseId，真/假之分不进公开事件流）。开局批量事件 `ClueIconsShown` 为公开事件，但 payload 只含"谁向谁展示"的关系（`pairs`），不含任何徽记内容。干涉的请求门控事件（`InterventionGateOpened` / `InterventionGateAccepted` / `InterventionGateDeclined`）与投票表态事件（`InterventionResponded` 等）全部公开。 |
| `error` | `{"code", "message", "details"}`。 |
| `ack` | `{"commandId", "status": "accepted|rejected", "revision", "error"?}`，只确认对应客户端命令。 |
| `taken-over` | `{"reason": "seat taken over by a new connection"}`，随后连接被关闭；旧连接不再收到任何后续帧，客户端必须停止操作与自动重连（与普通断线的退避重连是不同路径）。 |

### `state` 消息形状

```json
{
  "type": "state",
  "roomCode": "123456",
  "roomStatus": "waiting | playing | ended",
  "locked": false,
  "isHost": true,
  "yourPlayerId": "p-… | null（旁观者）",
  "hostPlayerId": "p-…（创建时建立的房主座位）",
  "connected": {"p-…": true},
  "hostActions": [{"type": "start-game"}, {"type": "lock"}],
  "game": { /* GameState 投影；waiting 时也有（setup 阶段） */ },
  "serverTime": 1788537000.0
}
```

### 断线恢复与命令确认

1. 浏览器在连接关闭后以退避重连；有效登录账号恢复其原座位。房主离开不会结束或转移房间，房主账号重连仍为房主。创建时即建立 hostPlayerId、hostAccountId 与 seatAccounts，写入房间 meta，重启后保留；所有客户端显示同一房主座位。
2. `hello` 后服务器总会发送完整、按接收者投影的 `state`。客户端以它替换本地状态，不尝试补造事件；因此重连前后的 `game.revision` 与状态哈希以服务器为准。
3. 客户端仅保留尚未收到 `ack` 的命令，并以原 `commandId`、原 `expectedRevision` 重传。相同命令重复到达时服务端返回 `accepted`，但不再次广播事件或结算。
4. 新 `commandId` 携带过期 `expectedRevision` 时服务端返回 `game.revision-conflict`、`ack.status = rejected` 和最新 `state`；客户端丢弃该命令，等待用户基于新状态再次操作。
5. 同一 `commandId` 若内容不同，服务端返回 `command.id-reuse`。所有拒绝均有 `ack`，因此不会永久卡在客户端发件箱。

### 运行指标与公开部署边界

- `GET /metrics` 返回无身份信息的进程内计数：连接数、座位恢复/接管数、命令接受/拒绝数及当前连接、房间数量；进程重启后清零。它用于观察重连风暴和非法命令，不记录昵称、令牌、命令内容或私密状态。
- 本次按 ADR 0016 延续 HTTP/WS 部署；账号存储、会话凭证、存档目录与调试端点不提供公网访问。

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
      "holdsCurseCard": false,  // 是否持有诅咒卡（ADR 0014，归属公开：全员含旁观者可见）
      "resources": {"quill": 0, "shield": 1, "sword": 0, "staff": 0, "fan": 0}
    }
  ],
  "daggerHolderId": "p-…",
  "phase": {"kind": "action", "…"} | {"kind": "intervention", "stage": "gate|poll|choice", "activePlayerId": "p-…"} | {"kind": "skill", "…"},
  "pending": {
    /* 干涉三段窗口的 pending 额外携带：stage（gate|poll|choice）、attackerPlayerId（公开的攻击者，
       门控弹窗点名用；重连无事件回放也在）、deadline（服务端注入的到期 Unix 秒）；
       gate 期间（ADR 0012）尚未开票，只有 stage 与既有基础字段 eligiblePlayerIds，
       responses / volunteerPlayerIds 不存在；开票后才有 responses（{playerId: volunteer}，
       实时公开）与 volunteerPlayerIds（自愿者名单）；
       单人窗口（reveal|skill|token-return）同样携带 deadline */
    "kind": "intervention", "stage": "poll", "responses": {"p-…": true}, "deadline": 1788537090.0
  },
  "result": null | {"winner": "rose|beast|inquisitor", "explanationKey": "capture|…", "ranking": [{"playerId","seat"}], "curseAssignments": {"c-…": "p-…"}},  // 终局翻开诅咒归属（ADR 0014）；未分发/放弃为空 dict
  "interventionTimeoutSeconds": 90,
  "singleWindowTimeoutSeconds": 90,
  "viewer": null | {
    "playerId": "p-…",
    "identity": {"faction": "rose", "rank": 5},
    "identityMarkers": ["rose", "rose"],  // 本人身份标记原面（未亮出时也下发本人）
    "resources": {"quill": 0, "shield": 1, "sword": 0, "staff": 0, "fan": 0},
    "skillsUsed": false,
    "cursesToDistribute": ["c-…"],   // 待分发诅咒卡 ID，仅审判者可见（分发后清空）；分发动作经技能窗口的 choose-skill
    "curseAssignments": {"c-…": "p-…"},  // 诅咒真/假归属，仅审判者视角存在此字段（ADR 0014）；分发前为空 dict，投影驱动、断线重连不丢
    "inspections": {"p-…": {"faction": "rose", "rank": 5}},  // 小丑检视出的目标身份，仅检视者本人可见（ADR 0013）
    "clueIcon": "rose",              // 本人阵营徽记
    "seenNeighbourClue": {"playerId": "p-…", "icon": "beast"}  // 右邻徽记，仅此一处
  },
  "legalActions": [
    {"type": "pass-dagger", "targetPlayerId": "p-…"},
    {"type": "attack", "targetPlayerId": "p-…"},
    {"type": "answer-intervention-request", "need": true | false},
    {"type": "respond-intervention", "volunteer": true | false},
    {"type": "decline-intervention"},
    {"type": "choose-intervention", "responderPlayerId": "p-…"},
    {"type": "choose-skill", "use": true, "targetPlayerId": "p-…"},
    {"type": "choose-skill", "use": true, "targetPlayerIds": ["p-…", "p-…"]}  // 等级3：每对可选组合一个动作
  ]
}
```

### 隐私保证（服务器强制，客户端无法绕过）

- `viewer.identity` 只出现在投影接收者自己的 `viewer` 块里；`setup` / `active` 状态的公共 `players[]` **不含**真实阵营/位阶。仅 `ended` 状态通过 `players[].identity` 全员公开真实身份（ADR 0015），旁观者与回放末帧同样可见。
- `revealed` 只在身份被公开（受伤/被捕获）后出现。
- 投影**不含**随机种子 `seed`（知道种子即可用 `random.Random(seed)` 重现全部身份分配）。
- 阵营徽记按规则只向左邻展示：徽记只出现在被展示者的 `viewer` 块里（本人 `clueIcon` + 右邻 `seenNeighbourClue`）；`players[]` 条目、旁观者投影与回放步骤均**不含**任何徽记字段。
- `cursesToDistribute` 只在审判者自己的 `viewer` 块里。
- 诅咒可见性（ADR 0014，ruleset 0.7）：卡的**归属**是公开对局事实——`players[].holdsCurseCard` 全员含旁观者可见；**真/假之分**只出现在审判者自己的 `viewer.curseAssignments`（其他视角无此字段）与终局 `result.curseAssignments`（全员翻开）里；任何公开事件流不含 curseId 或真/假信息。
- `inspections`（小丑检视结果）只在检视者本人的 `viewer` 块里；`HarlequinInspected` 广播事件只含目标 playerId，不含阵营/等级。
- 事件广播只过滤保留字 `CurseViewed`；`CurseDistributed` 已是公开事件（payload 只含 recipientPlayerId）。服务器端存档保留完整事件流与命令载荷（真/假归属的权威记录），用于回放校验。

### 错误码

**服务器层**：`auth.login-required`（未登录访问需要会话的接口，如回放）、`room.not-found`、`room.not-ended`、`room.not-host`、`room.locked`、
`room.already-started`、`room.full`、`room.ended`、`seat.taken-over`（座位已被新连接接管后，
旧连接迟到的命令/房主消息一律以此拒绝，命令拒绝仍带 ack）、`player.name-required`、`player.not-eligible`（旁观者操作）、
`command.server-managed`、`command.invalid-shape`、`protocol.version-mismatch`、
`auth.session-expired`（会话到期后已建立 WS 连接被终止，工单 14）、
`auth.session-revoked`（退出撤销当前登录并停止其连接，工单 14）、
`auth.password-changed`（改密撤销其他设备登录并停止其连接，工单 15）、
`auth.wrong-old-password`（改密时旧密码不正确，工单 15）。

**引擎层**（`RuleError` 原样转发）：`state.invalid`、`game.not-found`、`command.id-reuse`、
`game.already-ended`、`command.unknown`、`game.not-setup`、`game.duplicate-player`、
`game.player-count`、`game.seat-occupied`、`game.invalid-timeout`、`target.not-eligible`、
`target.shielded`、`target.already-three-damage`、`player.not-actor`、
`intervention.not-open`、`intervention.not-poll`、`intervention.not-choice`、
`intervention.not-gate`（门控命令发在非门控阶段）、`intervention.not-target`
（门控回答非被攻击者本人发出）、
`intervention.not-eligible`、`intervention.already-responded`、`reveal.not-open`、
`skill.not-open`、`token-return.not-open`（三条单人窗口超时命令的身份守卫）、
`skill.already-used`、
`skill.invalid-target`、`curse.invalid-count`、`curse.duplicate-recipient`、
`game.not-active`、`player.not-dagger-holder`、`target.not-found`、`target.captured`。
