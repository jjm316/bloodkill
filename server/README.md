# Blood Bound 网页服务端（server/）

权威服务器 + 多浏览器客户端，实现 08 工单的本地主机联网玩法：大厅/建房、6–12 人游戏、
旁观、终局回放、按玩家投影（浏览器永远看不到其他玩家的身份）、自动存档与重启恢复。

- 规则引擎：[`blood_bound/`](../blood_bound/)（纯 stdlib，可独立运行）
- 协议说明：[`PROTOCOL.md`](PROTOCOL.md)
- 浏览器客户端：[`client/`](../client/)（React + TypeScript + Vite）

## 环境要求

- **Python 3.11+**（项目声明 `requires-python >= 3.11`；服务器用到 3.9+ 语法）
- Node 18+（仅开发客户端时需要）

## 安装与运行

### 方式一：开发模式（推荐调试时）

终端 1 —— 启动服务器（在仓库根目录）：

```text
pip install -r server/requirements.txt
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

终端 2 —— 启动 Vite 开发服务器：

```text
cd client
npm install
npm run dev
```

打开 http://localhost:5173 。Vite 会把 `/api` 与 `/ws` 代理到 8000 端口。

### 方式二：单服务器模式（局域网开玩）

构建客户端后，FastAPI 直接把 `client/dist/` 作为静态站点伺服：

```text
cd client
npm run build
cd ..
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

同一局域网内所有玩家（含手机）打开 `http://<主机IP>:8000/` 即可，
无需任何其他安装。先注册或登录账号；创建房间立即绑定房主账号和自己的座位，
浏览器通过 HttpOnly 登录 Cookie 恢复身份，不保存旧房主令牌。登录有效期自登录时刻
起固定 30 天，不滚动续期；到期或主动退出登录后需重新登录，重新登录可恢复原座位与
房主身份；退出只撤销当前设备的登录，其他设备不受影响，也不移除座位。修改密码在
当前账号行操作：验证旧密码并设置新密码后本机保持登录，其他设备全部退出，需要用
新密码重新登录（座位与房主归属不变）。

### 本地测试工具箱（子命令 + 双击 bat）

手动联机测试的全部日常操作集中在 `scripts/test_toolkit.py`，覆盖：开新局、
启动/重启/关闭服务端、只构建前端、看状态、关测试窗口。不带子命令时默认等价于 `up`：

```text
.venv/Scripts/python.exe scripts/test_toolkit.py up --players 6   # 开新局（偶数局）
.venv/Scripts/python.exe scripts/test_toolkit.py up --players 7   # 开新局（奇数局：含审判者）
.venv/Scripts/python.exe scripts/test_toolkit.py up --no-build    # 开新局（跳过前端构建）
.venv/Scripts/python.exe scripts/test_toolkit.py serve            # 只启动服务端
.venv/Scripts/python.exe scripts/test_toolkit.py restart          # 重启服务端（存档房间自动恢复）
.venv/Scripts/python.exe scripts/test_toolkit.py down             # 关闭服务端
.venv/Scripts/python.exe scripts/test_toolkit.py down --clear-saves  # 关服并清空存档
.venv/Scripts/python.exe scripts/test_toolkit.py build            # 只构建前端
.venv/Scripts/python.exe scripts/test_toolkit.py status           # 服务端/存档/测试窗口状态
.venv/Scripts/python.exe scripts/test_toolkit.py close            # 只关闭测试窗口
```

不想开终端的话，`scripts/` 目录下有成对的中文双击 bat 薄壳（`测试工具箱-开新局.bat`、
`测试工具箱-重启服务端.bat` 等），双击即执行对应子命令；`开新局` 默认 6 人，
其余参数可整行追加。

- 测试窗口使用固定 profile 目录 `.scratch/chrome-profiles/`（已 gitignore），重复运行复用，
  删除该目录即恢复全新环境。
- 工具箱使用 `.scratch/toolkit-saves/` 独立数据，核验服务归属后才注册测试账号。
  自有浏览器 profile 通过本地 CDP 安装真实登录 Cookie，自动进入 `?room=` 房号链接；
  姓名、密码、会话和旧房主令牌均不放 URL 或浏览器启动参数。
- 服务端以独立进程运行（日志在 `.scratch/uvicorn.log`），不随终端/会话关闭，用
  `down`/`restart` 子命令管理，无需去任务管理器找进程。
- 每次 `up` 都会新建一个房间；waiting/playing 房间不会自动过期，堆积多了可用
  `down --clear-saves` 清空后重新开局。

## 网络访问与安全

- **局域网内**：HTTP/WS 明文即可（局域网环境可接受）。
- **经内网穿透/公网访问**：本次按 ADR 0016 继续 HTTP/WS。客户端按 `location.host`
  同源推导 WebSocket 地址，HTTPS 页面自动用 WSS；账号存储、会话与调试端点不公开。

## 服务器管理命令（本机终端）

运维用查看、重置密码与关闭房间命令随服务端一起交付（`server/admin.py`），在部署根目录运行。完整的中文用法指南（本地与云服务器布局、互动输入、备份位置与故障处理）见 [docs/account-admin.md](../docs/account-admin.md)：

```text
.venv/Scripts/python.exe -m server.admin users                     # 查看账号及当前房间占用
.venv/Scripts/python.exe -m server.admin rooms                     # 查看房间状态、房主与在线玩家
.venv/Scripts/python.exe -m server.admin reset-password 用户名     # 重置密码并撤销该账号全部登录
.venv/Scripts/python.exe -m server.admin close-room 123456         # 预览、确认并备份关闭一个弃局房间
```

云服务器在 `/opt/bloodkill` 部署根用 `.venv/bin/python -m server.admin <命令>`，行为一致（见 [云服务器部署](../docs/deployment-cloud.md)）。

- 命令不直接读改存档：服务启动时在同一进程打开一个**只绑定 127.0.0.1** 的管理
  监听，CLI 请求它读取实时状态（含在线连接）、执行重置密码与管理关闭。公网应用不注册任何管理路由。
- 独立管理凭证与实例记录存放在存档目录的 `admin/` 子目录（`admin-token`、
  `installation.json`）；凭证不进命令行参数、不出现在输出中，普通账号或房主
  身份拿不到管理权限。
- `--saves-dir`（默认环境变量 `BLOOD_BOUND_SAVES_DIR` 或 `./saves`）与 `--port`
  可显式指定；端口上若不是目标实例（安装标识/存档目录不符）会拒绝操作，
  避免误连同一台机器上的另一个服务。
- `reset-password 用户名`：防误连核对通过后隐藏输入新密码与确认密码（终端走
  getpass 不回显，stdin 为管道/重定向时逐行读取，等价安全：密码不进命令行参数、
  不写入输出或日志）。校验 6–12 个字符且两次一致，中文报错可重试；直接回车或
  Ctrl-C 取消，非零退出且不修改任何账号。确认后经回环管理端点重置：该账号全部
  登录（所有设备）撤销、已建立的房间连接停止；座位与房主归属保持不变，用新密码
  重新登录可恢复原座位。用户名不存在时明确中文报错，不会自动创建账号。
- 服务未运行、配置缺失或凭证错误均有中文提示并非零退出。

### close-room：确认并备份关闭指定弃局

- 先 `rooms` 查看要处理的房间号，再运行 `close-room 房间号`：CLI 显示该房当前
  信息（房号、状态、房主、玩家与在线情况），要求**再次输入同一房号**确认；输入
  其他内容或直接回车即取消，不会改动任何房间。
- 房间不存在、已正常结束或已被管理关闭时拒绝处理并中文说明；预览后房间发生了
  变化（有人开局或行动）时确认会被拒绝，需重新预览。
- 确认后服务先把该房存档、元数据与座位归属备份到存档目录下隔离的
  `admin-backup/<对局号>/` 子目录（`game.json.gz`、`meta.json`、`closure.json`），
  **备份失败则不关闭**；备份成功后停止该房操作与计时器、断开全部连接（玩家会
  收到中文通知并可返回大厅开新房）、把活动存档移出存档目录并释放全部座位占用。
- 管理关闭不是正常终局：不产生胜负或身份揭晓，被关房不能重新加入或在线回放，
  服务重启也不会恢复它；「最近 20 个正常终局」的回放清理不触碰管理备份。
- 成功输出包含房号、受影响玩家与备份绝对路径；部分失败（如备份完成但移出活动
  存档失败）会明确报告且不输出成功，处理后续试会整目录重写同一备份。
- 其他房间不受影响，无需整台停服。
- 清理中断的恢复语义（工单 22）：备份前或备份后未提交时中断，重启后房间照常恢复、
  可安全重试关闭；关闭已提交但回复丢失时中断，重启后房间不复活、占用不恢复，重试
  会明确报告已于何时被管理关闭。中断尝试若留下了未提交的关闭记录，服务重启恢复该
  房时会自动作废该记录，不会把活房误报成已关闭。
- 验证专用的故障注入钩子：以环境变量 `BLOOD_BOUND_ADMIN_CLOSE_FAULT=
  before-backup|after-backup|after-commit` 启动服务后，管理关闭会在对应边界写
  `<存档目录>/.admin-close-fault.<边界>.marker` 并阻塞等待同名 `.release` 文件，
  供测试在精确边界真实终止进程或门控并发交错；生产不设置该变量，行为不受影响。

### 旧房间切换：账号机制首次启用时一次性停用旧未结束房间

- 存档目录里由旧免账号服务端写下的房间（元数据带 `hostToken`、无
  `hostAccountId`）在服务启动时自动切换：等待/进行的旧房**只备份**到隔离的
  `legacy-backup/<对局号>/` 子目录（`game.json.gz`、`meta.json` 与
  `cutover.json` 停用事实），随后移出活动存档。停用不是正常终局：不产生胜负、
  身份揭晓或中止回放，被停用的旧房不能再加入、旁观或在线回放。
- 旧**已结束**对局不属于切换范围：照常恢复并按「最近 20 个正常终局」保留规则
  供登录用户按房号观看回放，无需迁移到任何账号。
- 切换只做一次且可安全重复启动：账号方案的新房间（元数据带 `hostAccountId`）
  永不在处理范围；已停用的旧房与已管理关闭的房间不会被再次处理。全部旧房处理
  成功后写 `<存档目录>/legacy-cutover.json` 完成标记（之后保持字节不变）。
- 部分失败如实报告且可恢复：某房备份或移出失败时原存档保留原样、输出中文失败
  说明、不写完成标记，下次启动继续处理剩余旧房（重试会整目录重写同一备份）；
  坏旧存档（存档读不出）按字节原样备份并停用，停用记录会如实标注。备份前、
  备份后或写完成标记前中断（断电/杀进程），重启后都会继续或补完，不会误处理
  任何账号方案的房间。
- 玩家侧衔接：旧姓名/旧房主令牌与旧协议客户端不再获得授权（建房请求体或
  WS hello 携带旧字段会收到「请刷新页面」提示；旧邀请链接只承接房号，登录后
  以自己的账号进入）。旧未结束房间的玩家重新注册、重新开房。
- 验证专用的故障注入钩子：以环境变量 `BLOOD_BOUND_LEGACY_CUTOVER_FAULT=
  before-backup|after-backup|before-marker` 启动服务后，旧房间切换会在对应
  边界写 `<存档目录>/.legacy-cutover-fault.<边界>.marker` 并阻塞等待同名
  `.release` 文件（每个边界每进程只挂起一次）；生产不设置该变量，行为不受影响。

## 数据与存档

- 存档目录默认 `saves/`，可用环境变量 `BLOOD_BOUND_SAVES_DIR` 覆盖。
- 账号与会话位于独立的 `accounts/accounts.sqlite3`；回放清理不删除账号。
- 管理安装记录与凭证位于 `admin/` 子目录，回放清理不触碰；`installation.json`
  记录实例标识与当前管理端口，`admin-token` 仅服务器本机可用。
- 管理关闭的备份位于 `admin-backup/` 子目录（按对局号隔离），与房间恢复扫描和
  回放清理互不相干。
- 旧房间切换的备份位于 `legacy-backup/` 子目录（按对局号隔离，含 `cutover.json`
  停用事实），完成标记为存档根的 `legacy-cutover.json`；两者同样不被房间恢复
  扫描和回放清理触碰。
- 每接受一条命令自动存档（gzip + meta 侧车文件）；服务器重启时自动恢复全部房间，
  进行中的对局可断线重连继续；已被管理关闭的房间与已停用的旧免账号房间不恢复。
- 已结束的对局保留最近 **20** 个（超出自动清理），用于回放页。

## 游戏流程

1. 登录账号后建房 → 立即获得房主座位和 6 位房号，分享给其他玩家。
2. 其他玩家使用自己的账号输入房号加入（可旁观）；房主可锁定房间、在 6–12 人时开始游戏。
3. 游戏开始后：匕首持有者行动 → 攻击/干涉投票/技能窗口 → 按引擎规则推进，
   直到某阵营达到胜利条件。
4. 结束后房主/任何玩家可离开；回放页输入房号可查看旁观视角的完整对局过程。

## 测试

```text
python -m pytest tests/          # 引擎 + 投影 + 房间管理（不依赖 FastAPI）
cd client && npx tsc --noEmit   # 客户端类型检查
```
