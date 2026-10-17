# 云服务器部署（阿里云轻量）

2026-10-04 拍板：公网访问不走内网穿透（cloudflared 实测 WSS 往返 0.8–1 秒），改为直部署**阿里云轻量应用服务器**，裸 IP `http://<IP>:8000` 免域名、免备案、免证书。明文暴露已由产品方接受（便利性优先，见 [局域网与穿透部署](deployment-lan.md) 的选型调研）。

## 前提

- 轻量应用服务器，镜像 **Ubuntu 24.04**（自带 Python 3.12；引擎要求 ≥3.11，22.04 只有 3.10 不达标）。
- 阿里云控制台 → 服务器详情 → **防火墙** → 添加规则放行 **TCP 8000**。这是轻量控制台层防火墙，与系统内 `ufw` 独立（默认镜像 ufw 未启用，可用 `sudo ufw status` 确认）。
- 本机能 `ssh root@<IP>` 登录（密钥或密码，购买时设置的凭据）。

## 部署与更新（同一条命令）

```bash
scripts/deploy-cloud.sh <服务器IP>            # 默认 root 用户
scripts/deploy-cloud.sh ubuntu@<服务器IP>     # 自定义用户时
```

脚本在本机完成前端构建，服务器上的一切（venv、依赖、systemd）自动准备：

1. 本机 `npm ci && npm run build`（产出 `client/dist`；本机有残留 vite dev server 锁着 node_modules 会报 EPERM，先关掉）。
2. 打包 `server/`、`blood_bound/`（引擎包，运行时 import）、`client/dist/`、systemd unit，scp 上传。
3. 服务器解包到 `/opt/bloodkill`，创建 `.venv` 并安装 `server/requirements.txt`（服务器不需要 Node）。
4. 安装 `/etc/systemd/system/bloodkill.service`，`systemctl enable --now` + `restart`，最后 curl `/health` 自检。

更新代码后重跑同一条命令即可；服务器上的 `saves/`（`/opt/bloodkill/saves`）不在打包清单里，更新不触碰。回滚 = 本机 `git checkout <旧提交>` 后重跑脚本。

## 两条架构约束（改 unit 前必读）

- **必须单进程**：WebSocket 连接表和 deadline 定时器都在进程内存，加 `--workers` 会状态分裂（连不上的玩家、不触发的超时）。
- **`WorkingDirectory` 必须指向 `/opt/bloodkill`**：未设 `BLOOD_BOUND_SAVES_DIR` 时 `saves/` 相对工作目录解析。

## 日常运维

```bash
ssh root@<IP> journalctl -u bloodkill -f        # 看日志
ssh root@<IP> systemctl restart bloodkill       # 重启
scp -r root@<IP>:/opt/bloodkill/saves ./backup  # 备份存档（房间元数据 + 引擎快照）
```

账号管理命令也在部署根目录运行（查看账号与房间、重置玩家密码、确认并备份
关闭弃局房间），完整用法见 [账号管理工具使用指南](account-admin.md)：

```bash
ssh root@<IP>
cd /opt/bloodkill
.venv/bin/python -m server.admin users
.venv/bin/python -m server.admin rooms
.venv/bin/python -m server.admin reset-password 小明
.venv/bin/python -m server.admin close-room 123456
```

`saves/` 不在打包清单里，更新不会触碰：账号、登录会话、房间占用、管理凭证
（`admin/`）与管理备份（`admin-backup/`、`legacy-backup/`）在更新后全部保留。

## 公网风险面（朋友局先观察）

与局域网的本质差异：`POST /api/rooms` 建房无门槛，且 waiting/playing 房间不回收（`server/rooms.py` 只清已结束局），扫描器批量建房会撑大 saves 目录。先上线观察，真遇到再加建房口令。`/health` 端点已具备，需要时可接监控。升级路径（域名 + TLS 终止）作为加分项保留，不阻塞上线。
