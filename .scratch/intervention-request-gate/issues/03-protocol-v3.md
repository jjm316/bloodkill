# 03 协议 v3：版本硬切与文档

Status: ready-for-agent

Blocked by: 01, 02

spec: `.scratch/intervention-request-gate/spec.md`（协议字段英文、界面文案中文）

## 改动清单

- 协议版本 `"2"` → `"3"`：服务端常量与客户端 hello 上送值同步；版本不匹配照旧拒绝。
- `server/PROTOCOL.md`：
  - 命令表新增 `answer-intervention-request {need: bool}`（目标专属、门控阶段专属）；
  - `timeout-intervention` 载荷补 `{stage: "gate"}` 取值；
  - 事件表新增 `InterventionGateOpened` / `InterventionGateAccepted` / `InterventionGateDeclined {reason: target-declined|timeout}`；
  - 干涉专节改写为三段窗口（gate → poll → choice），记录 2026-10-04 门控裁决与 ADR 0012 指针；
  - 错误码表补 `intervention.not-gate`、`intervention.not-target`；
  - pending state 字段说明补 `stage: "gate"`。
- 版本历史注记：v2 → v3 变更摘要一行。

## 验收

- 新旧版本 hello 互拒测试（既有模式扩展）。
- PROTOCOL.md 与实际消息字段逐一对得上（评审抽查）。
