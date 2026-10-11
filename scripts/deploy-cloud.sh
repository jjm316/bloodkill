#!/usr/bin/env bash
# 一键部署/更新 bloodkill 到阿里云轻量服务器（Ubuntu 24.04）。
#
# 用法：
#   scripts/deploy-cloud.sh [user@]主机IP
#   不带 user@ 时默认 root@<IP>（阿里云轻量 Ubuntu 默认 root 登录）。
#
# 首次部署与日常更新是同一条命令：本机构建前端 → 打包运行时文件 → scp 上传
# → 服务器解包到 /opt/bloodkill、准备 venv、安装 systemd unit 并重启。
# 服务器上的 saves/ 目录不在打包清单里，更新不会动它。
#
# 注意：本机若有残留的 vite dev server 锁着 client/node_modules，npm ci 会报
# EPERM，先 taskkill 掉再跑。
set -euo pipefail

DEST="${1:-}"
if [ -z "$DEST" ]; then
  echo "用法: scripts/deploy-cloud.sh [user@]主机IP" >&2
  exit 1
fi
case "$DEST" in
  *@*) ;;
  *) DEST="root@$DEST" ;;
esac
REMOTE_DIR="/opt/bloodkill"

cd "$(git rev-parse --show-toplevel)"

echo "==> [1/4] 构建前端（client/dist）"
npm ci --prefix client --no-fund --no-audit --silent
npm run build --prefix client --silent

echo "==> [2/4] 打包运行时文件（server/ blood_bound/ client/dist/ unit）"
TARBALL="/tmp/bloodkill-deploy.tar.gz"
tar -czf "$TARBALL" server blood_bound client/dist scripts/bloodkill.service

echo "==> [3/4] 上传到 $DEST"
ssh "$DEST" "mkdir -p $REMOTE_DIR"
scp -q "$TARBALL" "$DEST:/tmp/bloodkill-deploy.tar.gz"
scp -q scripts/bloodkill.service "$DEST:/tmp/bloodkill.service"

echo "==> [4/4] 远端安装并重启"
ssh "$DEST" "REMOTE_DIR='$REMOTE_DIR' bash -s" <<'REMOTE'
set -euo pipefail
REMOTE_DIR="${REMOTE_DIR:?}"

# 引擎要求 Python >= 3.11；Ubuntu 24.04 自带 3.12，22.04 只有 3.10 会在这一步报错。
python3 - <<'PY'
import sys
assert sys.version_info >= (3, 11), f"需要 Python >= 3.11，当前 {sys.version}"
PY

mkdir -p "$REMOTE_DIR"
tar -xzf /tmp/bloodkill-deploy.tar.gz -C "$REMOTE_DIR"

if [ ! -x "$REMOTE_DIR/.venv/bin/pip" ]; then
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv
  python3 -m venv "$REMOTE_DIR/.venv"
fi
"$REMOTE_DIR/.venv/bin/pip" install -q -r "$REMOTE_DIR/server/requirements.txt"

install -m 644 /tmp/bloodkill.service /etc/systemd/system/bloodkill.service
systemctl daemon-reload
systemctl enable --now bloodkill >/dev/null
systemctl restart bloodkill
sleep 1
systemctl --no-pager -l status bloodkill | sed -n '1,5p'
curl -fsS http://127.0.0.1:8000/health && echo "  <- /health OK"
rm -f /tmp/bloodkill-deploy.tar.gz /tmp/bloodkill.service
REMOTE

echo "==> 完成。阿里云控制台防火墙放行 TCP 8000 后，手机浏览器直接开 http://<服务器IP>:8000/"
