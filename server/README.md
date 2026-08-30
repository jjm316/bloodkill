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
无需任何其他安装。第一次建房的主机浏览器把 `hostToken` 保存在 localStorage。

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
- 自动进房依赖客户端的 URL 参数入口（`?room=&name=&token=`，见 `client/src/App.tsx`），
  也可以手工拼这种链接分享给局域网玩家一键加入。
- 服务端以独立进程运行（日志在 `.scratch/uvicorn.log`），不随终端/会话关闭，用
  `down`/`restart` 子命令管理，无需去任务管理器找进程。
- 每次 `up` 都会新建一个房间；waiting/playing 房间不会自动过期，堆积多了可用
  `down --clear-saves` 清空后重新开局。

## 网络访问与安全

- **局域网内**：HTTP/WS 明文即可（局域网环境可接受）。
- **经内网穿透/公网访问**：**必须使用 HTTPS/WSS**。客户端按 `location.host` 同源推导
  WebSocket 地址（HTTPS 页面自动用 WSS），所以任何终止 TLS 的隧道（cloudflared、
  ngrok、frp + 证书等）都能直接工作。不要用明文隧道把游戏暴露到公网——身份、房主令牌
  与存档会裸奔。

## 数据与存档

- 存档目录默认 `saves/`，可用环境变量 `BLOOD_BOUND_SAVES_DIR` 覆盖。
- 每接受一条命令自动存档（gzip + meta 侧车文件）；服务器重启时自动恢复全部房间，
  进行中的对局可断线重连继续。
- 已结束的对局保留最近 **20** 个（超出自动清理），用于回放页。

## 游戏流程

1. 主机建房 → 得到 6 位房号，分享给其他玩家。
2. 其他玩家输入房号 + 昵称加入（可旁观）；房主可锁定房间、在 6–12 人时开始游戏。
3. 游戏开始后：匕首持有者行动 → 攻击/干预/技能窗口 → 按引擎规则推进，
   直到某阵营达到胜利条件。
4. 结束后房主/任何玩家可离开；回放页输入房号可查看旁观视角的完整对局过程。

## 测试

```text
python -m pytest tests/          # 引擎 + 投影 + 房间管理（不依赖 FastAPI）
cd client && npx tsc --noEmit   # 客户端类型检查
```
