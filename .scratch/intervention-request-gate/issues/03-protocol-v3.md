# 03 协议 v3：版本硬切与文档

Status: resolved

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

## Comments

- 2026-10-04 implemented in commit `8977bab` (branch `gate/03-protocol`, merged to `spec/intervention-request-gate`). `PROTOCOL_VERSION` "2"→"3" server + client hello; three new hello mutual-rejection tests (old→new literal "2" rejected before seat resume; current "3" accepted; new→old via scoped version patch). PROTOCOL.md rewritten for the v3 gate contract (command/event/error/pending-stage/三段窗口 + ADR 0012 pointer + preamble version-history note); every documented field self-audited against engine/projection/rooms source. Suite 211 tests, reds = the 14 known golden subTests only. Frontend suite deferred to 04/05 (client change is a one-character constant).
