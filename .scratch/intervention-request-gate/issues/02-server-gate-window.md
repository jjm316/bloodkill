# 02 服务端：门控窗口的墙钟调度与投影注入

Status: ready-for-agent

Blocked by: 01

spec: `.scratch/intervention-request-gate/spec.md`（引擎不存墙钟约束下的窗口接力）

## 改动清单

- 房间窗口身份（poll/choice 之外）认第三种 `stage="gate"`：门控窗按对局配置的 `interventionTimeoutSeconds` 起算。
- 门控关闭按答案接力：接受 → 重臂 poll 窗（现有逻辑）；拒绝/超时 → 窗口清除，走结算链后续窗口（受害者亮牌窗等，同现有「无人自愿」路径）。
- 投影 `pending` 视图新增 `stage: "gate"`：下发 `eligiblePlayerIds` 与注入的 `deadline`（Unix 秒）；`responses`/`volunteerPlayerIds` 仅 poll 之后存在。
- 重启恢复：已过期的门控窗照旧立即补发 `timeout-intervention {stage:"gate"}`（现有补发机制扩展认 gate）。
- 客户端直发 `timeout-intervention` 照旧拒绝（`command.server-managed`），无需新检查。

## 验收

- DeadlineWindowTests 风格用例：门控窗跟踪并写入 meta、投影携带 deadline、静默到期调度器结算、接受后接力 poll 窗、重启补发。
- `python -m unittest discover` 全绿（golden 归 05）。
