# 局域网与内网穿透部署

## 局域网

1. 在主机创建虚拟环境并安装 `server/requirements.txt`。
2. 在 `client/` 执行 `npm ci && npm run build`。
3. 设置 `BLOOD_BOUND_SAVES_DIR` 为独立的可备份目录。
4. 启动 `uvicorn server.app:app --host 0.0.0.0 --port 8000`。
5. 其他设备访问 `http://<主机局域网 IP>:8000/`。

## 内网穿透

穿透服务必须终止 TLS，并把 HTTPS 转发到主机的 HTTP、把 WSS 转发到主机的 WS。客户端根据页面协议自动选择 `wss`，不需要额外配置。禁止将明文 WS 直接暴露到公网。

建议只转发 8000 端口，使用随机房间号和独立 host token；穿透服务的访问控制、证书续期和审计日志由部署方负责。

## 更新

先运行发布检查表和 smoke 脚本，再滚动替换服务进程。保留 saves 目录不变，协议版本不兼容时客户端会收到明确错误；回滚代码时同时恢复匹配的静态资源版本。
