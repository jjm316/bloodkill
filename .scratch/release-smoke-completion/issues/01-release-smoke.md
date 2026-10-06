# 修复发布握手并验收终局公开回放

Type: task
Status: resolved
Label: ready-for-agent

## 工作内容

见 [spec](../spec.md)。拥有 `scripts/release_smoke.py`、专用回归测试、发布检查表和本项目录。

## Comments

- 2026-10-06：实际基线 `80a71e2`，初始工作区干净。原 issue11 的关闭历史保留，本票独立补齐验证缺口。
- 红灯复现：`.venv/Scripts/python.exe -m unittest tests.test_release_smoke -v`。v1 hello 得到 `protocol.version-mismatch`、expected=`3`；旧 CLI 忽略错误帧后抛出未处理的 `ConnectionClosedError`。同步版本与接收错误处理后，专项测试继续以 replay HTTP 409（期望 200）失败，证明仅修版本不足以补齐验收。
- 网络实测需在沙箱外运行：Windows asyncio 的本地 socketpair 在沙箱内阻塞。服务只绑定 127.0.0.1，存档位于系统临时目录，后台窗口隐藏，进程由测试清理。

## Answer

- 首次连接、旁观和同名重连统一导入 `server.protocol.PROTOCOL_VERSION`。每条命令使用唯一 ID、当前修订号，匹配 accepted ack 并等待所有视角同步到该修订号。
- 服务端投影中的合法动作推进 gate → poll（逐人拒绝挡刀）、亮牌与放弃技能，按公开伤害优先攻击；6 人局合法到达第 4 点伤害捕获。旁观连接全程读取，终局与所有玩家公开部分一致。
- 保留未结束 replay 的 HTTP 409 + `room.not-ended`，终局要求 HTTP 200、非空、递增修订号、无私有字段、完整末尾等于实时旁观终局。
- 默认每次网络等待 5 秒、WebSocket 流程 60 秒、100 条命令；无关事件不重置等待期限。错误只输出诊断码，不打印收到的状态/令牌。

### 验证记录（2026-10-06）

- `.venv/Scripts/python.exe -m unittest tests.test_release_smoke -v`：10 项通过，4.009 秒；CLI 从临时工作目录运行也通过。
- `.venv/Scripts/python.exe -m unittest tests.test_release_smoke tests.test_server_rooms tests.test_server_sync tests.test_engine tests.test_projection tests.test_rule_branches -v`：198 项通过，13.922 秒。
- `.venv/Scripts/python.exe -X utf8 -m unittest discover -v`：223 项通过，29.640 秒，无跳过；包含属性回归与 golden 6–12。真实服务 smoke 的 CLI 在独立端口和临时存档中运行，输出：

```text
smoke：首次握手成功（协议 v3，6 名玩家与旁观者）
smoke：建局成功
smoke：命令确认成功（传递匕首）
smoke：同名重连成功（座位与状态一致）
smoke：终局成功（49 条命令，修订号 124）
smoke：公开回放成功（56 步，末尾与终局一致）
smoke 通过：房间 114205
```

- 错误场景通过真实 CLI 与网络边界验证：旧 v1 被真实服务拒绝；协议错误、拒绝 ack、连接关闭、持续事件不重置等待超时、WebSocket 总时限、命令上限、HTTP 连接失败，均有限返回退出码 1，无 traceback，无令牌泄露。
- `.venv/Scripts/python.exe -m compileall -q scripts/release_smoke.py tests/test_release_smoke.py`、`git diff --check`：通过。仓库无 Python 静态类型检查配置，`.venv` 未安装 mypy/pyright，未声称完成 Python 静态类型检查。
- 本项是服务发布验收，未执行浏览器人工可访问性、前端构建、移动设备性能或公网 TLS 验收；发布检查表保留这些独立门禁。

### 评审与提交

- 实现提交：`86da6d7`（`fix: complete v3 release smoke and public replay validation`）。
- code-review Standards：零发现。简体中文诊断、协议与合法动作来源、隐私检查、临时资源清理符合仓库标准，无值得报告的代码味道。
- code-review Spec：零发现。交接要求的握手、确认、重连、有界终局与公开回放均落实，无缺失或越界行为。
- 评审固定本项提交与五个文件范围。期间并行交接提交/合并了耦合测试，已保留，不计入本项改动或评审。
- 本票 resolved，原 issue11 的关闭历史不变；发布 smoke 终局回放缺口已补齐。
