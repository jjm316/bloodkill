# 02 公网访问与内网穿透选型：研究笔记

日期：2026-08-29  
状态：已完成 9 类候选的一手/二手来源核对，且 cloudflared 快速隧道已于 2026-08-29 在本机完成端到端实测（功能全通、延迟约 1 秒）。按"便利性优先、明文可接受、手机朋友零安装开 URL"排序给出结论；路由器 WAN IP 归属与其余免费档实测项待人工验证（见文末）

## 结论

本次选型的第一原则（用户已拍板）：**明文暴露可接受，怎么方便怎么来**；且访问者里有人用手机浏览器，**"手机朋友零安装、只开一个 URL"是首要约束**。原 `docs/deployment-lan.md` 的"隧道必须终止 TLS"条款按用户决定同步放宽（文档修改由主线完成，本笔记不改 docs）。TLS 方案降级为"顺带就有的免费加分项"。

### 前提 A：有手机朋友（首要前提）——只考虑"开 URL 即用"方案

**首选是一个二选一：免费省事（cloudflared）vs 花小钱流畅（frp+国内 VPS）**。本机端到端实测证明 cloudflared 功能全通但大陆到 CF 边缘延迟约 1 秒；国内 VPS 明文直连预期几十毫秒级（定性推断，未实测）。两者都满足"手机零安装开 URL"，取舍点只在钱与延迟：

1. **"免费省事"路线：cloudflared quick tunnel（trycloudflare.com）**。零账号、零域名、零证书、零费用、零实名，`winget install cloudflared` 后一条命令 `cloudflared tunnel --url http://localhost:8000` 即得一个自动 HTTPS/WSS 的 URL，手机浏览器直接打开，TLS 免费附赠（顺带消除明文风险）。**2026-08-29 本机实测：协议全链路（HTTPS 建房 → WSS 连接 → 加入 → 状态推送 → 双玩家广播 → 错误响应）全部通过，WSS 长连接稳定；但新 HTTPS 请求 1.3–2.2 秒（含 TLS 握手）、已建连 WSS 指令往返 0.8–1 秒（本地对照 3–10ms），回合制可玩但明显不跟手。** 代价还包括：URL 每次重启随机变化（每局开始往群里发新链接，可接受）、官方定位仅测试用途无 SLA。
2. **"花小钱流畅"路线：frp + 国内轻量 VPS（约百元/年档）**。明文 TCP 直接转发 `IP:8000`，免域名免证书，流量终止在国内机房，预期几十毫秒级延迟（对照实测的 trycloudflare 约 1 秒；定性推断，建议购前先开一台按量实例实测）；长期玩、一劳永逸。代价：约百元/年 + 配 frps/frpc/自启动的动手成本（全场合最高），备案处于灰区但无域名+非标端口+非网站用途在腾讯云官方口径下不触发（见合规节）。
3. **备选（要固定 URL）：Tailscale Funnel**。免域名、自动 `*.ts.net` 证书、访问者零安装、URL 固定；但要注册账号并在控制台开启 Funnel，大陆登录与 `*.ts.net` 入口可达性待实测（二手资料显示大陆无官方节点）。注意其入口同样在境外，延迟预期与 cloudflared 同量级。
4. **备选（零费用+国内速度）：cpolar 免费档**。注册+客户端+authtoken 即用，国内节点延迟好（预期明显优于 1 秒档）；免费档 1Mbps、随机 URL（重启变）、实名要求待验证。是"不花钱又想国内速度"的折中，值得与 cloudflared 并行实测后二选一。natapp 排其后（HTTP 隧道要人脸识别、域名/端口"不定时强制更换"有断局风险）；花生壳免费档 5 并发连接 < 6 人局下限，直接不合格。
5. **潜在零成本黑马（先验证再定）：路由器端口转发 + DDNS**。本机出口 IPv4 为 101.68.127.41（内网 192.168.31.36，小米路由器网段），若路由器 WAN IP 等于出口 IP 且无运营商上层 NAT，朋友直接开 `http://101.68.127.41:8000`，是所有方案里延迟最低的零成本方案；当前归属未核实，先测再排位。

### 前提 B：朋友全在 PC、且本来就用 Radmin 联机（次前提，装客户端不算负担）

- **Radmin VPN（本机已装并激活，虚拟网卡 IP 26.2.194.13）**：官方免费且不限网络人数，PC 朋友装 Radmin 加入同一网络后直接开 `http://26.2.194.13:8000`。本机 Windows 防火墙已实测放行 python.exe 入站（Public/Private 均 Allow），不会被系统防火墙挡。**但官方客户端仅 Windows，无 iOS/Android，手机朋友进不来**——只能当"PC 圈子方案"，不能当主推。

### 不推荐（及理由）

- **ngrok 免费档**：免费版 HTTP(S) 端点带"拦截提示页"（interstitial，朋友每次先看 ngrok 警告页再点进去，劝退）；月数据传输仅 1GB；二手资料普遍反映大陆直连反复重连。三项叠加不适合。
- **花生壳（贝锐 Oray）免费档**：免费版并发连接数仅 5，低于本项目 6 人下限，人数上直接出局（另有 1Mbps、1G/月流量限制；付费档 ¥1299/年起，远超预算）。
- **natapp 免费档**：HTTP 隧道需人脸识别（官方 FAQ），免费随机域名/端口"不定时强制更换"，有游戏中途断链风险。
- **ZeroTier / Tailscale 纯组网模式**：要求每个访问者装客户端+注册，违反"手机朋友零安装"首要约束；且免费档容量不够 12 人局（ZeroTier 免费 10 设备、Tailscale 免费 6 用户，均含主机）。
- **Hamachi 免费档**：免费 5 人/网络 < 6 人下限。
- **IPv6 直连 + DDNS**：本机实测**无公网 IPv6**（仅有 fd00::/8 ULA 私有地址，IPv6 出口 curl 超时），除非用户在光猫/小米路由器上另行开启，否则不可用。降级为附注，不作为正式选项。

## 对比表一：开 URL 即用方案（手机零安装，全部满分）

| 维度 | cloudflared quick | Tailscale Funnel | ngrok 免费 | frp+国内轻量VPS | cpolar 免费 | natapp 免费 | 花生壳免费 | 路由器端口转发 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 费用（首年/持续） | 0 / 0 | 0 / 0 | 0 / 0（超额停） | 约 ¥100+/年（轻量活动档，需核对） | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 账号要求 | 无 | 要（注册+控制台开 Funnel） | 要 | 无（VPS 账号即可） | 要（注册+authtoken） | 要（注册+实名） | 要（注册+疑似实名，待验证） | 无 |
| 域名要求 | 无 | 无（自动 *.ts.net） | 无 | 无（IP:端口） | 无（随机二级域名） | 无（随机域名） | 无（随机壳域名） | 无（IP 或 DDNS） |
| 证书/自动 TLS | 自动 HTTPS+WSS | 自动 HTTPS+WSS | 自动 HTTPS | 无（明文）；要 TLS 须自购域名+证书走 https2http | 免费 HTTP（HTTPS 仅付费档） | 免费 HTTP（HTTPS 仅付费档） | 免费 HTTP（HTTPS 为付费配件） | 无（明文；自签证书会告警） |
| 明文模式可用性/便利性 | 强制走 HTTPS，无明文（反而更安全） | 强制 TLS，无明文 | 自动 HTTPS，但免费档有拦截页 | **明文即默认模式**，免域名免证书直接跑 | **免费档就是 HTTP 隧道**，直接用 | **免费档就是 HTTP 隧道**，但需人脸识别 | 免费 HTTP 隧道，但 5 并发不够 | **纯明文**，零依赖 |
| URL 稳定性 | 每次重启随机变 | **固定** | 每次重启随机变（1 个固定 dev 域名） | **固定**（IP:端口） | 随机，重启变（二手，待验证） | 随机，且**不定时强制更换**（官方原文） | 随机壳域名，随映射保留 | IP 随家宽变化（需 DDNS 或每晚重发） |
| 手机访问者 | 零安装，开 URL | 零安装，开 URL | 零安装，但先过拦截页 | 零安装，开 URL | 零安装，开 URL | 零安装，开 URL | 零安装，开 URL | 零安装，开 URL |
| 大陆可达性/延迟 | **本机实测通，WSS 往返 0.8–1s、新请求 1.3–2.2s**（2026-08-29） | 入口可达性未知，大陆无官方节点（二手）；待实测 | 反复重连、慢（二手） | **预期最好**（国内机房直连，几十毫秒级；未实测） | 预期好（国内节点） | 预期好（国内节点） | 预期好（体验线路） | **最好**（直连家宽，若成立） |
| Windows 安装/自启 | winget 装（本机 GitHub 直连已超时）；一条命令；自启用任务计划/服务 | 装客户端+登录；后台服务常驻 | 装+登录；有偿活跃小时计费 | 下载 frpc+配置文件+任务计划/NSSM；VPS 上跑 frps | 客户端+authtoken | 客户端+authtoken | 图形客户端 | 路由器后台配端口转发 |
| 免费档关键限制 | 并发在途请求 200 上限；无 SLA；仅测试定位（官方） | 免费 6 用户（含主机）；端口仅 443/8443/10000 | 1GB/月流量；20k 请求/月；拦截页 | 无带宽限制（受服务器带宽约束） | 1Mbps；4 隧道；无保留域名 | http/tcp/udp 无 HTTPS；域名不定期强制换 | **并发连接 5**；1Mbps；1G/月；2 映射 | 无（取决于家宽） |
| 主要风险 | 服务免费无 SLA；大陆质量波动 | 控制面/入口大陆可达性；免费档商用限制 | 流量 1GB 极易超；大陆不稳 | 服务器被扫描（明文 HTTP 暴露 8000）；备案灰区 | 随机 URL 每局重发；1Mbps 首载慢 | 人脸识别门槛；断局风险 | 人数上限不合格 | WAN IP 可能非真公网（CGNAT）；家宽封端口风险 |

## 对比表二：组网方案（需装客户端，违反手机零安装前提）

| 维度 | Radmin VPN | Hamachi 免费 | ZeroTier 免费 | Tailscale 组网 |
| --- | --- | --- | --- | --- |
| 费用 | 0（官方声明免费不限制游戏人数） | 0 | 0 | 0 |
| 免费档容量 | 不限人数（官方）；150 PC/网络（二手） | **5 台/网络** | **10 设备、1 网络** | **6 用户**（设备不限） |
| 移动端 | **无**（仅 Windows，官方） | 无 | iOS/Android 有（官方） | iOS/Android 有（官方） |
| 手机访问者体验 | 不可用 | 不可用 | 可用但要装 App+注册 | 可用但要装 App+注册 |
| 加密 | 隧道加密（官方称安全连接） | 加密 | WireGuard 加密 | WireGuard 加密 |
| 大陆可用性 | 好（国内联机常用，二手） | 一般（境外服务，二手） | 控制面/Planet 节点速度波动（二手，未深查） | 打洞难、DERP 常绕美西（二手） |
| 本机现状 | **已装并激活**（26.2.194.13） | 未装 | 未装 | 未装 |
| 结论 | PC 圈子备选（手机出局） | 5 人上限不够，不推荐 | 10 设备不够 12 人局，不推荐 | 6 用户不够 12 人局，不推荐（组网形态；Funnel 另算） |

## 各方案细节与资料引用

### 1. cloudflared / Cloudflare Tunnel

**Quick tunnel（免账号）**：`cloudflared tunnel --url http://localhost:8080` 启动即生成 `trycloudflare.com` 的随机子域名，把本地端口临时暴露到公网，全程不需要账号，也不用把站点加进 Cloudflare DNS（[官方 TryCloudflare 文档](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/)）。

官方明示的限制（同上来源，一手）：

- "Quick Tunnels are intended for testing and development only."（仅测试/开发用途）；"Free tunnels are meant to be used for testing and development, not for deploying a production website."
- "We don't guarantee any SLA or uptime of TryCloudflare."（无 SLA、无可用性保证）
- 并发在途请求硬上限 200，超出返回 429。
- 不支持 SSE（本项目用 WebSocket，不受影响；[官方](https://developers.cloudflare.com/network/websockets/)："WebSockets are supported on all Cloudflare plans"，WebSocket 在所有付费档含免费档支持——一手）。
- 子域名每次启动随机生成；`~/.cloudflared` 下存在 `config.yaml` 时 quick tunnel 不工作。
- 二手资料称 quick tunnel 链路最长约 24 小时（[腾讯云开发者社区](https://developer.cloud.tencent.com/article/2710363)，二手）。

大陆可达性：二手资料（知乎/V2EX/LINUX DO 汇总于[腾讯云开发者社区](https://developer.cloud.tencent.com/article/2710363)及搜索摘要）普遍结论是"基本可用但慢、延迟高、波动大"，大陆到 Cloudflare 边缘常绕美西，社区优化手段为优选 IP、强制 `--protocol http2` 等。**2026-08-29 本机实测（一手，环境：Windows 11、家宽出口 101.68.127.41、NAT 后、cloudflared 2026.8.2 winget 安装）**：

- **功能全通**：`cloudflared tunnel --url http://127.0.0.1:8000` 一条命令起隧道，自动分到 `https://*.trycloudflare.com`（免账号免域名，自动 HTTPS+WSS）。经隧道完成 HTTPS 建房（POST /api/rooms）→ WSS 连接 → hello 加入 → 状态推送 → 双玩家加入广播 → 指令错误响应，协议全链路正常，WSS 长连接稳定。
- **延迟偏高（大陆到 CF 边缘固有问题）**：新 HTTPS 请求 1.3–2.2 秒（含 TLS 握手）；已建连的 WSS 指令往返 0.8–1 秒；本地对照 3–10ms。回合制（<1s 容忍度）可玩但明显不跟手。定性对照：frp+国内 VPS 明文直连的延迟应为几十毫秒量级（国内机房终止，无跨境段；推断，未实测）。
- **安装渠道**：GitHub Releases 直连下载两次超时且零字节；`winget` 安装成功且带哈希校验。大陆装 cloudflared 建议 winget 或镜像源。
- 附带发现（与选型无关，记录备查）：服务端对不存在的房间码是"发一条 `room.not-found` 后立即关闭"，客户端表现为无 close frame 的异常断连；真实前端处理了 `onclose` 所以无感，但协议层不算优雅，可另开票据处理。

**Named tunnel（需免费账号+自有域名）**：官方要求"Before you publish an application through your tunnel, you must add a website to Cloudflare"（发布应用前必须把一个网站/域名加入 Cloudflare，[官方文档](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-remote-tunnel/)）——即**免域名拿固定 URL 的路线在 Cloudflare 侧不成立**，固定 URL 只能靠自有域名（域名是另外的花费），或改用 Tailscale Funnel。另注：Cloudflare 代理的 HTTPS 端口包括 443/2053/2083/2087/2096/8443（[官方网络端口文档](https://developers.cloudflare.com/fundamentals/reference/network-ports/)，一手）。

### 2. Tailscale（Funnel / Serve / 组网）

**Funnel（对公网暴露，访客免安装）**：把本机服务通过 Tailscale 中继暴露到公网，"Anyone can access a Funnel URL even if they don't use Tailscale"；自动使用 `tailnet-name.ts.net` 域名并自动配发 HTTPS 证书，无需自有域名；仅支持端口 **443、8443、10000**；要求 Tailscale ≥ v1.38.3、开启 MagicDNS、启用 HTTPS 证书，并在策略里加 funnel 节点属性（CLI 首次运行会自动加）；`tailscale funnel 8000` 一条命令即得形如 `https://主机名.tailnet.ts.net` 的固定 URL（[官方 Funnel 文档](https://tailscale.com/kb/1223/funnel)，一手）。Funnel 只走 TLS，**没有明文模式**（对本项目即"白送 TLS"）。带宽限制官方表述为不可配置（具体数值未公布）。

与 Serve 的区别：Serve 只在 tailnet 内可达（装了客户端的设备），Funnel 才对公网开放（同上官方文档）。

免费档限额（[官方定价页](https://tailscale.com/pricing)，一手）：Personal 计划 0 元，**最多 6 用户**、设备数不限、仅限非商业用途——组网形态下 6-12 人局坐不下；但 **Funnel 的访问者不算 tailnet 用户**（他们不装任何东西），只有主机自己占 1 个用户名额，故 Funnel 形态不受 6 用户限制。移动端 App：官方下载页提供 iOS/Android 客户端（[官方](https://tailscale.com/download)，一手）。

大陆可用性：Tailscale 在大陆无官方 DERP 中继节点，社区普遍报告跨运营商打洞成功率低、流量常绕旧金山 DERP 且慢，主流方案是自建国内 DERP（[知乎讨论](https://www.zhihu.com/question/1934671111506888415)、[Reddit 社区帖](https://www.reddit.com/r/Tailscale/comments/1psvnfz/)、[自建 DERP 教程](https://yelog.org/2026/03/04/Tailscale-Guide-from-Basic-to-Private-DERP/)，均为二手）。注意：**Funnel 访客流量走 Tailscale 的公网入口而非 DERP，其大陆可达性是独立问题，未见系统资料，列为待实测**；登录环节若选 Google SSO 在大陆不可直达（需选 Microsoft/GitHub，二手常识，未单独核验）。

### 3. ngrok

免费档限额（[官方定价页](https://ngrok.com/pricing)，一手，2026-08 抓取）：最多 3 个在线 endpoint、每月 20k HTTP/S 请求、**月数据传输 1GB**、附赠 1 个固定 dev 域名、一次性 $5 用量额度（活跃 endpoint 按每小时 $0.02 从额度扣，额度用尽 endpoint 停）；免费档 HTTP/S 端点带 **interstitial 拦截提示页**（朋友打开链接先看到 ngrok 警告页再继续）；TCP/TLS 端点免费档不含（TCP 需绑卡验证）。

区域：现行定价页把"区域固定路由（regional routing）"列为付费合规功能（$0.02/小时，一手）；免费档不提供区域选择，入口为全球 anycast，官方未承诺具体 PoP 位置（推断，未核验）。大陆直连可达性：二手资料反映反复 `reconnecting`、需换旧版客户端或切区域才偶尔连上（[CSDN 教程](https://blog.csdn.net/sxf1061700625/article/details/128155983)、[CSDN](https://blog.csdn.net/qq_62764416/article/details/140958623)，二手）。付费档从 $10/月起。**结论：拦截页+1GB+不稳，不推荐。**

### 4. frp + 国内轻量服务器（明文直连模式 + TLS 升级路径）

**明文模式（本项目新基线）**：frp 的 TCP 代理类型就是纯端口转发——frps 在 VPS 监听 `remotePort`，frpc 把流量透传到 `localAddr`，不过问协议、免域名免证书（[frp 官方文档目录：TCP & UDP](https://gofrp.org/zh-cn/docs/features/tcp-udp/)，一手）。访问者直接开 `http://VPS公网IP:8000/`，浏览器在同源 http 页面下自动用 `ws://` 连 `/ws/{code}`（与项目"按页面协议自动选择 wss"的行为一致）。这是全部候选里**国内延迟最低、最稳定**的形态（流量直接终止在国内机房，无跨境段）；对照 2026-08-29 本机实测 trycloudflare 的 0.8–1 秒 WSS 往返，本方案预期为几十毫秒量级（推断，建议购前用按量实例实测一次）。

**TLS 升级路径（以后想加密时）**：frp 的 `https2http` 插件支持"本地 HTTP 服务对外提供 HTTPS"——frpc 侧加载自备证书（`crtPath`/`keyPath`）做 TLS 封装，frps 开 `vhostHTTPSPort`，按 `customDomains` 域名路由（[官方示例](https://gofrp.org/zh-cn/docs/examples/https2http/)，一手）。注意该路线**必须自备域名+证书**（HTTPS 类型按域名路由，不用 remotePort），即"免域名 TLS"在 frp 侧不成立——这是明文模式下 frp 反而方便的原因。

成本：国内厂商轻量应用服务器入门档常年有约百元/年的新购活动价（价格随活动变动，需自行核对[腾讯云轻量产品页](https://cloud.tencent.com/product/lighthouse)）；frp 本身开源免费。

备案与端口（厂商官方口径，一手）：

- 腾讯云："根据国家规定，使用中国内地服务器开办网站必须进行 ICP 备案"（[轻量 ICP 备案文档](https://cloud.tencent.com/document/product/1207/45756)）；但"只购买服务器、不作为网站对外提供服务时不需要备案"（[官方 FAQ](https://cloud.tencent.com/document/product/243/19630)）；未备案/未接入备案的**域名**访问会被阻断（[官方概述](https://cloud.tencent.com/document/product/243/18907)）。
- 阻断机制针对"未备案域名"（网关从 HTTP Host 头 / HTTPS SNI 提取域名比对备案库），直接用 IP 访问一般不受影响（[腾讯云开发者社区](https://cloud.tencent.com/developer/ask/240598)、[社区讨论](https://www.nodeseek.com/post-264676-1)，二手）；社区经验称非标端口用 IP 直连通常可用，但厂商会周期扫描，未备案域名+80/443 必拦，非标端口个别情况也有拦截报告（[V2EX](https://www.v2ex.com/t/1082505)，二手）。
- 阿里云口径更严："无论网站是通过 IP 地址还是通过域名对外提供服务，未备案成功前均不允许开通网站访问"，且备案系统只支持域名备案不支持 IP 备案；"域名用于内网穿透、API 接口等非网站场景时，只要解析指向中国内地服务器 IP 地址，仍须完成 ICP 备案；使用非标准端口（如 8080）不豁免"（[阿里云 ICP 文档](https://help.aliyun.com/zh/icp-filing/basic-icp-service/product-overview/icp-filing-requirements-for-a-regular-website)、[备案流程文档](https://help.aliyun.com/zh/icp-filing/basic-icp-service/user-guide/icp-filing-application-overview)，一手）。
- 两岸口径合并结论：**无域名 + IP + 非标端口（如 8000）+ 朋友间非商业**，在腾讯云文档口径下属"不作为网站对外提供服务"的灰区，社区实践普遍可用（二手）；若要绝对稳妥，选**中国香港/境外轻量服务器**，官方明示无需备案（[腾讯云官方](https://cloud.tencent.com/document/product/1207/45756)），代价是延迟略增（仍远好于绕美西）。

### 5. 国内穿透服务商免费档

- **cpolar**（[官方定价页](https://www.cpolar.com/pricing)，一手）：免费档永久免费、**1Mbps**、4 个隧道/进程、仅"随机 URL 二级域名/随机 TCP 端口"、不限流量、不支持保留子域名（付费起）；免费档为 HTTP/TCP 隧道，端到端 HTTPS 隧道仅在付费档。随机域名每次重启变化为其教程/文档惯例说法（二手，待验证）。页面未标注免费档实名要求（待验证）。
- **natapp**（[官网首页](https://natapp.cn/) + [官方 FAQ](https://natapp.cn/article/faq)，一手）：免费档提供 http/tcp/udp 协议（**免费无 HTTPS**）、随机域名+随机 TCP/UDP 端口、"**不定时强制更换域名/端口**"、可自定义本地端口；实名规则官方明示——TCP/UDP 隧道手机号实名即可，**Web(HTTP) 隧道需人脸识别**（支付宝扫码）。免费带宽约 1Mbps、2 条隧道等说法来自第三方（[知乎](https://www.zhihu.com/question/503155934/answer/2882974080)、[博客园](https://www.cnblogs.com/kukuxjx/p/17595471.html)，二手）。
- **花生壳（贝锐 Oray）**（[官方价格页](https://hsk.oray.com/price)，一手）：免费体验版 **1Mbps、限 1G/月流量、2 条映射、并发连接数仅 5**、解析间隔 60 分钟、体验线路；HTTPS 映射为付费配件（付费档 ¥1299/年起赠 HTTPS 证书）。页面仅提供实名入口未写明是否强制（待验证）。**并发 5 连接 < 6 人下限，人数上直接不合格。**

共同点：国内节点延迟好；免费档全部是随机域名（重开变/natapp 强制轮换）；免费档基本无 HTTPS（要 HTTPS 都得付费）；都注册即可用（natapp 人脸门槛最高）。

### 6. Radmin VPN / Hamachi / ZeroTier（组网类）

- **Radmin VPN**（[官网](https://www.radmin-vpn.com/)，一手）：官方声明"免费的产品，不限制游戏人数"（Free Radmin VPN does not limit the number of gamers）、无速度限制（实际取决于网络）；支持平台仅 Windows 11/10/8.1/8/7 与 Server 系列，**无 macOS/Linux/iOS/Android 客户端**；单网络上限 150 台 PC（[Radmin 官方社区](https://radmin-club.com/radmin-vpn/max-users-for-a-network-in-radmin-vpn-/)，二手）。本机已装并激活（虚拟网卡 26.2.194.13），Windows 防火墙已实测放行 python.exe 入站。**PC 朋友装客户端加入网络后直接开 `http://26.2.194.13:8000`；手机朋友无法使用。**
- **Hamachi**（[官方 vpn.net](https://www.vpn.net/)，一手）：免费 5 台/网络，付费 $49/年 6-32 台。5 < 6 人下限，出局。
- **ZeroTier**（[官方定价页](https://www.zerotier.com/pricing/)，一手）：免费 Personal 档 **10 设备、1 网络**（注：官方已从早期 25 设备口径下调为 10）；iOS/Android 客户端存在（[官方下载页](https://www.zerotier.com/download/)，一手）。12 人局需 13 台设备，超限；且要求全员装客户端+注册。

### 7. IPv6 直连 + DDNS（附注：本机当前不可用）

本机实测**无公网 IPv6**（仅 fd00::/8 ULA 私有地址，IPv6 出口 curl 超时），除非在光猫/小米路由器上另行开启 IPv6 并放行入站，否则此路线不成立。即便开启，还需：朋友侧网络具备 IPv6 可达性（大陆手机流量与家宽 IPv6 普及度较高，属运营商推进现状，未深入核验）、Windows 防火墙放行、DDNS 跟踪地址变化，且无域名时 TLS 只能自签证书（浏览器告警，朋友需手动信任）。**结论：不值得作为正式选项投入。**

### 8. 路由器端口转发 + DDNS（零成本，先验证）

本机出口公网 IPv4 为 101.68.127.41，内网 192.168.31.36（小米路由器网段）。验证步骤：登录小米路由器后台核对 **WAN IP 是否等于 101.68.127.41**——若不相等（如 WAN 口是 100.64.x.x 或 10.x.x.x）则为 CGNAT，路线不成立；若相等，在路由器把外网端口（如 8000）转发到 192.168.31.36:8000，让朋友用手机流量实测 `http://101.68.127.41:8000`（同时验证运营商是否放行该端口入站；家宽 80/443 入站被运营商封禁是普遍社区经验，二手）。注意即使 WAN IP 与出口 IP 一致，仍可能存在运营商上层 NAT（多用户共享公网 IP），必须外部实测才能确认。成立的话：零成本、零安装、延迟全场最低、明文可接受；家宽 IP 会变，要么上免费 DDNS，要么每局往群里重发地址（与 quick tunnel 的随机 URL 代价同级）。

## 明文暴露的实际风险（用户已知情接受）

用户已明确接受明文，此处仅客观记录泄露面，不作为淘汰依据：

- **房间号与 host token**：URL、HTTP 头与 WebSocket 握手中可见，同路径抓包者可拿到房主令牌（本项目最高权限凭证）。
- **玩家秘密身份**：本作是隐藏身份游戏，每个玩家的 WebSocket 流量里含其个人视角的身份信息。公网明文下，最现实的威胁不是运营商路径上的随机人，而是**同一 Wi-Fi 里的旁观者**（宿舍/办公室同网抓包可看到他人身份牌，构成作弊渠道）。
- **存档操作流量**：明文可见操作内容（不含服务端磁盘上的存档本身）。
- 缓解事实：cloudflared quick tunnel 与 Tailscale Funnel 虽被当作"便利性方案"入选，但两者免费自带真实证书 TLS，等于零成本顺带关掉了上述泄露面——这也是它们即便在"明文可接受"的新口径下仍排前两位的原因之一。
- `docs/deployment-lan.md` 原"必须终止 TLS、禁止明文 WS 暴露"条款需按用户决定同步放宽为"建议优先、不强制"（文档修改由主线完成，本笔记不动 docs）。

## 风险与合规说明（不构成法律建议）

- **备案义务触发条件**（厂商官方口径）：使用中国大陆服务器 + 域名对外提供网站服务必须 ICP 备案（[腾讯云](https://cloud.tencent.com/document/product/1207/45756)、[阿里云](https://help.aliyun.com/zh/icp-filing/basic-icp-service/product-overview/icp-filing-requirements-for-a-regular-website)）；个人非经营性备案免费且可个人办理。不触发/灰区：境外或香港服务器（腾讯云官方明示香港轻量无需备案）；无域名纯 IP + 非标端口 + 非网站用途（腾讯云官方"只购买服务器不作为网站对外提供服务不需要备案"；阿里云口径更严，见上）；实际拦截针对未备案域名的 Host/SNI，IP 直连一般不受影响（二手）。
- **境外隧道服务**（Cloudflare/Tailscale/ngrok）：不涉及大陆服务器，无备案义务；风险是可达性与速度受网络环境影响，以及免费服务无 SLA、条款可变（Cloudflare 官方明示 quick tunnel 仅测试用途且可能先行试验新特性）。
- **国内穿透服务商**：接入侧合规由持牌服务商承担，用户侧需实名（natapp 对 HTTP 隧道要求人脸识别为官方明示）；免费档有清退/降速/域名轮换的运营风险。
- **家宽合同**：运营商用户协议普遍禁止利用家宽对公众提供网站/经营性服务；个人非商业、朋友 6-12 人、回合制低流量、非 80/443 端口的分享被实际容忍的社区案例普遍（二手），但理论违约风险存在。本段为现状描述，不构成法律建议。

## 待人工验证项

1. **trycloudflare 手机侧抽查（主机侧实测已完成，2026-08-29）**：功能与延迟已在主机侧实测（见上文）；剩余项——用大陆手机（移动数据+家宽各一次）打开 quick tunnel URL，确认手机浏览器可达性与首载体感；winget 安装已确认可用。
2. **frp+国内 VPS 延迟实测（购前）**：开一台按量计费轻量实例，跑通 frps/frpc 明文转发后用手机数据实测 `/ws` 往返，验证"几十毫秒级"预期；同时观察非标端口+无域名 IP 直连是否被拦截（验证备案灰区实践口径）。
3. **路由器 WAN IP 核对**：小米路由器后台 WAN IP 是否等于出口 IP 101.68.127.41；若相等，从手机流量直连 `http://101.68.127.41:8000` 验证端口 8000 入站是否放行（成立则此方案升为零成本首选级备选）。
4. **Tailscale Funnel 大陆链路**：本机能否用 Microsoft/GitHub 完成登录（Google SSO 预期不可达）；配好 Funnel 后手机直连 `*.ts.net` URL 的成功率与延迟；Funnel 配置重启后是否保留。
5. **cpolar 免费档细节**：是否强制实名/人脸；免费 1Mbps 下静态资源首载体感；随机 URL 是否每次重启必变；与 cloudflared 实测对比后二选一作为"免费路线"定案。
6. **natapp 断局风险**：免费域名"不定时强制更换"的实际频率是否会在单局游戏中触发。
7. **花生壳/natapp 免费档的并发与人数**：花生壳 5 并发连接限制是否确按连接数（含 WebSocket）计算（若是则 6 人局必炸，维持不推荐）。
