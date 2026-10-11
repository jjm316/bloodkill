---
name: server-ops
description: 查询与运维 bloodkill 阿里云生产服务器（47.111.11.55）。Use when 需要上服务器查日志、查存档、看服务状态、重启服务、备份，或用户说 运维、线上、服务器状态、查日志、备份存档。
---

# bloodkill 服务器运维手册

所有命令在本机（用户的 Windows，Git Bash）执行；SSH 密钥和阿里云凭据都只存在于这台机器，换机器即无访问权。

## 访问通道

主通道 SSH（免密，密钥 `~/.ssh/id_ed25519_aliyun` 已绑定 `~/.ssh/config`）：

```bash
ssh root@47.111.11.55 "<命令>"
```

备用通道云助手（SSH 不通时用；凭据是 `~/.aliyun` 的 OAuth，`D:\AliyunCLI\aliyun.exe` 或 PATH 里的 aliyun 均可）：

```bash
aliyun swas-open RunCommand --RegionId cn-hangzhou \
  --InstanceId b48cab27631349d6916fff73c4a01686 \
  --Type RunShellScript --Name ops --CommandContent "<命令>"
# 取 InvokeId 后轮询，Output 是 base64，解码才是真实输出：
aliyun swas-open DescribeCommandInvocations --RegionId cn-hangzhou --InvokeId <InvokeId>
```

坑位：产品码是 `swas-open`（不是 swopen）；列实例/防火墙的 API 名是 `ListInstances`/`ListFirewallRules`（没有 Describe 前缀）。

服务器：阿里云轻量 Ubuntu 24.04、cn-hangzhou、2核2G/40G，**2027-10-11 到期**。部署与更新流程不在此手册，见 `docs/deployment-cloud.md`。

## 日志（只读，直接执行）

日志在 journald（systemd 收 uvicorn 的 stdout），持久化于 `/var/log/journal`，服务器重启不丢。没有单独的日志文件。

```bash
ssh root@47.111.11.55 "journalctl -u bloodkill -n 100 --no-pager"          # 最近 100 行
ssh root@47.111.11.55 "journalctl -u bloodkill -f"                          # 实时跟踪
ssh root@47.111.11.55 "journalctl -u bloodkill --since '2 hours ago' --no-pager"
ssh root@47.111.11.55 "journalctl -u bloodkill --no-pager | grep '<IP或关键词>'"
ssh root@47.111.11.55 "journalctl --disk-usage"                             # journal 占用
```

访问日志格式 `INFO: <来源IP>:<端口> - "GET /路径" 200`，可直接按 IP 或路径 grep。

## 存档（只读，直接执行）

位置 `/opt/bloodkill/saves/`，每局两个文件：`g-<局ID>.json.gz`（引擎快照）与 `g-<局ID>.meta.json`（房间元数据）。服务启动时扫描 `*.meta.json` 恢复房间列表。

```bash
ssh root@47.111.11.55 "ls -lat /opt/bloodkill/saves | head -20"            # 最近对局
ssh root@47.111.11.55 "du -sh /opt/bloodkill/saves"                         # 总占用
scp -r root@47.111.11.55:/opt/bloodkill/saves <本地目录>                    # 备份拉回本地
```

waiting/playing 状态的房间不回收（只清已结束局），存档目录只增不减是正常现象；真被扫描器撑大时先报告用户再处理。

## 服务管理（改状态，先报告再执行）

```bash
ssh root@47.111.11.55 "systemctl status bloodkill --no-pager"
ssh root@47.111.11.55 "systemctl restart bloodkill"    # 卡死/更新配置后
ssh root@47.111.11.55 "systemctl stop bloodkill"       # 停服 = 线上不可玩，需用户明确同意
```

硬约束：服务必须单进程。改 `/etc/systemd/system/bloodkill.service` 时禁止加 `--workers`——连接表和回合定时器都在进程内存，多进程会状态分裂。改完 unit 要 `systemctl daemon-reload && systemctl restart bloodkill`。

## 排障套路

线上打不开时按序执行，每步结果决定下一步：

1. `curl -fsS -m 10 http://47.111.11.55:8000/health` —— 通则问题在客户端/网络，去用户侧排查
2. `ssh root@47.111.11.55 "systemctl is-active bloodkill && systemctl status bloodkill --no-pager | head -15"` —— 死则看下一步，活则跳到日志
3. `ssh root@47.111.11.55 "journalctl -u bloodkill -n 100 --no-pager"` —— 定位异常后：代码问题走部署回滚（见 deployment-cloud.md），资源问题看下一条
4. 资源水位：`df -h /`（磁盘，journal 和 saves 都在上面）+ `free -h`（2G 内存，uvicorn 常驻约几百 MB）

## 红线

- `saves/` 里的文件是玩家对局记录，删除即不可恢复。
- 防火墙 8000/80/443/22 已放行且够用；动防火墙、换实例、升配等阿里云侧变更超出本手册，回报用户拍板。
