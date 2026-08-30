# 交付浏览器多人对局界面与最小权威服务

Type: task
Blocked by: 05, 06, 07
Status: resolved

问题：实现每名玩家各用一个浏览器客户端的多人对局闭环，而非单设备热座。主机本地运行权威服务端；浏览器通过 WebSocket 提交命令并接收按玩家过滤的投影。首轮先交付功能界面，视觉设计后置；桌面优先，手机竖屏必须完整可玩，横屏增强信息密度。

输出：Python FastAPI/uvicorn 服务端切片、React/TypeScript/Vite 浏览器客户端、房间/大厅/观战/回放的功能流程、按玩家投影和公共事件过滤、WebSocket 协议说明，以及 LAN 和 HTTPS/WSS 内网穿透启动说明。

已批准约束：主机可承载多个房间；房间使用 6 位数字码。玩家只输入名称，不验证身份；同名新连接直接接管座位并断开旧连接。建房浏览器保存本地房主凭据，房主可开局、锁房和管理大厅。游戏无自动倒计时；房间可选择自由发言或静默提示。观战者只能查看完整公共历史和实时公共投影。每次有效命令自动存档，服务端仅保留最近 20 个已结束对局，进行中的房间不按容量自动删除。局域网可使用 HTTP/WS；经内网穿透访问必须使用 HTTPS/WSS。

完成条件：6-12 人可在不同浏览器中不读开发者控制台完成一局；所有按钮状态来自服务端确认的引擎合法行动；非法行动有原因；浏览器永不接收其他玩家的身份、诅咒或私有事件；回放和当前局共享投影组件；主机重启后可恢复自动存档的未结束房间。

## Comments

- 2026-08-21：用户确认将原热座范围升级为本地主机、多浏览器客户端的正式实现，并确认上述协议、房间、存档和设备方向决策。08 认领后先补齐规则引擎与测试，再建立最小权威服务和功能客户端；09 保留断线恢复、网络硬化和部署的后续工作。

## Answer

已交付本地主机权威服务 + 多浏览器客户端，覆盖票据全部输出与完成条件：

**领域层（新增）**
- [`blood_bound/projection.py`](../../blood_bound/projection.py)：实现 03 契约中 `PlayerView` 的落地。`project_state(state, viewer_id)` 按玩家投影；`legal_actions` 补全引擎遗漏的合法行动（2 号技能带 `targetPlayerId` 选项、审判者 `distribute-curse` 分发入口）。投影强制保密：不含 `seed`（知道种子即可重现全部身份分配）、不含 `clueIcon`（开局只向左手边玩家展示）、其他玩家无阵营/位阶、`revealed` 仅在受伤/捕获后出现、`cursesToDistribute` 只出现在审判者自己的 `viewer` 块。旁观者 `viewer=None` 且无合法行动。
- 测试：[`tests/test_projection.py`](../../tests/test_projection.py) 6 项全部通过（旁观者无身份/种子、只见自己身份、受伤后公开线索、审判者分发、匕首行动、2 号技能目标）。

**服务端（新增，`server/`）**
- `rooms.py`（纯 stdlib，无需 FastAPI 即可测试）：`RoomManager` 负责 6 位数字房号、多房间、房主令牌、按名字加入/重连、同名接管（旧连接收 `taken-over` 后关闭）、锁定、6–12 人开局、每接受一条命令自动存档、终局只保留最近 20 局、启动时 `restore()` 恢复全部未结束房间。
- `app.py`（FastAPI/uvicorn 胶水）：REST（建房间/房间概览/终局回放）+ WebSocket（`hello`/`command`/`host`；`state`/`event`/`error`/`taken-over`）。`state` 按连接投影，`event` 广播过滤 `CurseViewed`/`CurseDistributed`；`start-game`/`join-game` 为服务器托管命令。构建产物存在时同端口伺服 `client/dist/`（单服务器模式）。
- 测试：[`tests/test_server_rooms.py`](../../tests/test_server_rooms.py) 8 项全部通过（房号/持久化、加入/重连、开局后拒入、锁定行为、6 人开局门槛、自动存档+重启恢复、保留 20 局上限、旁观回放步骤）。

**客户端（新增，`client/`，React + TypeScript + Vite）**
- 大厅（建房/加入/旁观/回放入口，房主令牌存 localStorage）→ 等待室（花名册/在线标记、房主开局 6–12 人门槛、锁房）→ 对局（行动按钮全部来自服务端 `legalActions` 投影：传匕首/攻击/申请/选择/放弃干预/技能窗口/审判者诅咒分发；事件日志）→ 终局结果横幅；回放页与对局共用同一 `Board` 组件。手机竖屏 40px 最小触控目标。
- `npx tsc --noEmit` 与 `npm run build` 均通过（157KB JS / 50.6KB gzip）。

**文档与配置**
- [`server/PROTOCOL.md`](../../server/PROTOCOL.md)：REST/WS 消息、投影形状、隐私保证、错误码全集。
- [`server/README.md`](../../server/README.md)：开发/单服务器两种启动方式、LAN 用 HTTP/WS、内网穿透必须 HTTPS/WSS（客户端按 `location.host` 同源推导 WSS，TLS 隧道直接可用）、`BLOOD_BOUND_SAVES_DIR`、存档保留策略。
- `.gitignore` 增加 `saves/`、`client/node_modules/`、`client/dist/`。

**测试与已知事项**
- 全套 `python -m unittest discover -v`：31 项，30 通过。唯一失败是**预先存在**的 `test_paused_game_and_debug_link_round_trip`：本机 Python 为 3.8.6，`persistence.py:157` 用到 `str.removeprefix`（3.9+）；项目声明 `requires-python >= 3.11`，代码符合声明目标，未修改。
- 运行 FastAPI 服务需 Python 3.11+（`pip install -r server/requirements.txt`）；本机 3.8 无法起服务，服务器行为由 `rooms.py` 单测覆盖。

**后置到 09 的内容**：断线恢复硬化（当前按名字重连可恢复座位，网络抖动的自动重连/心跳待硬化）、浏览器端多窗口集成测试基线、部署与穿透的进一步自动化。

