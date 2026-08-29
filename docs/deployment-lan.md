# 局域网与内网穿透部署

## 局域网

1. 在主机创建虚拟环境并安装 `server/requirements.txt`。
2. 在 `client/` 执行 `npm ci && npm run build`。
3. 设置 `BLOOD_BOUND_SAVES_DIR` 为独立的可备份目录。
4. 启动 `uvicorn server.app:app --host 0.0.0.0 --port 8000`。
5. 其他设备访问 `http://<主机局域网 IP>:8000/`。

## 内网穿透

项目定位为个人学习与朋友间分享，明文暴露已由产品方接受（2026-08-29）：选型以便利性优先，TLS 是顺带的加分项而非硬门槛。明文下的实际泄露面（房间号、房主令牌、玩家秘密身份）与完整方案对比见[穿透选型调研](../.scratch/blood-oath-replica/research-02-public-access-tunnel.md)。

### 推荐方案：cloudflared 快速隧道（免费、手机直接开链接）

1. 安装（大陆网络 GitHub 直连易超时，winget 可用且带哈希校验）：`winget install Cloudflare.cloudflared`。
2. 启动服务端：`uvicorn server.app:app --host 127.0.0.1 --port 8000`。
3. 启动隧道：`"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://127.0.0.1:8000`。
4. 把输出中的 `https://*.trycloudflare.com` 链接发给朋友；PC/手机浏览器直接打开即可。

特点：免账号、免域名、自动 HTTPS/WSS（顺带规避明文泄露面）。代价：URL 每次重启随机变化（每局重发链接）；大陆到 Cloudflare 边缘延迟偏高（2026-08-29 本机实测 WSS 指令往返约 0.8–1 秒，回合制可玩但不跟手）；官方定位仅测试用途、无 SLA。

### 备选方案

- **要更流畅**：frp + 国内轻量服务器（约百元/年）明文转发 `http://服务器IP:8000`，免域名免证书，预期几十毫秒级延迟；购前建议先用按量实例实测延迟与端口可用性，香港轻量服务器可完全避开备案问题。
- **朋友全在 PC 且已有 Radmin VPN**（本机已装，虚拟网卡 26.x 段）：直接开 `http://26.x.x.x:8000`；注意 Radmin 无手机客户端。
- **路由器有真公网 IP 时**：端口转发 8000 到主机是零成本、延迟最低的方案；先在小米路由器后台核对 WAN IP 是否等于出口 IP（`curl ifconfig.me`），再用手机流量实测入站是否放行。

### 若需要加密（建议优先，非强制）

穿透服务终止 TLS，把 HTTPS 转发到主机的 HTTP、把 WSS 转发到主机的 WS。客户端根据页面协议自动选择 `wss`，不需要额外配置。cloudflared / Tailscale Funnel 免费自带证书；frp 需自备域名与证书走 `https2http` 插件。

建议只转发 8000 端口，使用随机房间号和独立 host token；穿透服务的访问控制、证书续期和审计日志由部署方负责。

## 更新

先运行发布检查表和 smoke 脚本，再滚动替换服务进程。保留 saves 目录不变，协议版本不兼容时客户端会收到明确错误；回滚代码时同时恢复匹配的静态资源版本。
