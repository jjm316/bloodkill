# 鲜血盟约（Blood Bound）数字复刻

浏览器多人联机桌游实现：6–12 人在线对局、中文界面、纯 Python 确定性规则引擎、
按玩家投影（身份/诅咒对其他人保密）、自动存档、断线重连与终局回放。

- 规则引擎：[`blood_bound/`](blood_bound/README.md)（纯标准库，可独立运行）
- 权威服务端：[`server/`](server/README.md)（FastAPI + WebSocket）
- 浏览器客户端：[`client/`](client/)（React + TypeScript + Vite）
- 协议说明：[`server/PROTOCOL.md`](server/PROTOCOL.md)

## 环境要求

- **Python 3.11+**（仓库已自带 `.venv`，本机验证为 Python 3.11.4）
- **Node 18+**（仅开发、构建客户端时需要；普通玩家不需要）

## 启动

所有命令都在仓库根目录执行；如未使用仓库自带 `.venv`，先执行一次：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r server/requirements.txt
```

macOS/Linux 激活命令为 `source .venv/bin/activate`。如果不想激活虚拟环境，
可以把下面命令里的 `uvicorn` 换成 `.\.venv\Scripts\python.exe -m uvicorn`。

### 方式一：开发模式（推荐调试时）

终端 1 —— 启动权威服务器：

```text
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

终端 2 —— 启动前端开发服务器：

```text
cd client
npm install
npm run dev
```

浏览器打开 http://localhost:5173 。Vite 会把 `/api` 与 `/ws` 代理到
`http://localhost:8000`（代理地址在 [`client/vite.config.ts`](client/vite.config.ts)）。

### 方式二：单服务器模式（局域网直接开玩）

构建客户端后，FastAPI 直接把 `client/dist/` 作为静态站点伺服，局域网玩家无需
安装任何东西：

```text
cd client
npm run build
cd ..
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

同一局域网内的玩家（含手机）打开 `http://<主机IP>:8000/` 即可加入。第一次建房的
主机会把 `hostToken` 保存在浏览器 localStorage，之后刷新可恢复房主身份。

## 怎么开始一局

1. 房主打开页面 → 创建房间 → 得到 6 位房号，分享给其他玩家。
2. 其他玩家输入房号 + 昵称加入（可旁观）；6–12 人时房主可开始游戏。
3. 游戏开始后按规则推进：匕首持有者行动 → 攻击/干涉/技能窗口 → 直到终局。
4. 结束后可在回放页输入房号查看完整对局（旁观视角）。

## 数据与存档

- 存档目录默认 `saves/`，可用环境变量 `BLOOD_BOUND_SAVES_DIR` 覆盖。
- 每接受一条命令自动存档；服务端重启后自动恢复全部房间，进行中的对局可断线重连继续。
- 已结束的对局保留最近 20 个（超出自动清理），用于回放。

## 网络访问与安全

- **局域网内**：HTTP/WS 明文即可。
- **内网穿透/公网访问**：推荐 cloudflared 快速隧道（免费、免账号、自动 HTTPS/WSS，
  手机浏览器直接开链接，启动命令见 [`docs/deployment-lan.md`](docs/deployment-lan.md)）。
  本项目定位为个人学习与朋友间分享，明文方案可接受，加密降级为建议项；各方案对比与
  实测数据见[穿透选型调研](.scratch/blood-oath-replica/research-02-public-access-tunnel.md)。

## 测试

```text
python -m unittest discover -v          # 引擎 + 投影 + 房间 + WebSocket（共 106 项）
cd client && npx tsc --noEmit           # 客户端类型检查
```

发布前请按 [`docs/release-checklist.md`](docs/release-checklist.md) 逐项验证。
