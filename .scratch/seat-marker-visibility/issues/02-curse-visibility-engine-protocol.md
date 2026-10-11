# 02 诅咒卡归属公开：引擎/协议/投影/ruleset 0.7

Status: ready-for-agent

实现 `.scratch/seat-marker-visibility/spec.md` **Part B「引擎与协议」**。03 的前置；01 与本票互不依赖。

要点（全量见 spec Part B）：

- ruleset bump：`blood_bound/engine.py:169` `0.6`→`0.7`，:182 检查同步，:158 changelog 注释补一行。
- CurseDistributed 改公开，**载荷去 curseId**（只含 recipientPlayerId）；`server/protocol.py:20-22` PRIVATE_EVENT_TYPES 收缩为 `{"CurseViewed"}`。
- 投影：`_public_player` 增 `holdsCurseCard`；审判者 viewer 块增 `curseAssignments`（同 cursesToDistribute 门控）；GameEnded result 增 `curseAssignments`。
- golden 重生成，并**顺带落地挂起的 B9 golden 分支锁**（`.scratch/coupling-test-hardening/spec.md:53`，约定挂至下次 bump，即本次）。
- PROTOCOL.md 同步（新字段、PRIVATE_EVENT_TYPES、修正 :179/:199 陈旧 `"resources": ["curse"]` 示例）；CONTEXT.md 诅咒卡词条按 spec「文档同步」草稿落。
- 测试：引擎与投影（全员/旁观者见持卡、审判者独见归属、公开事件无真假）；`.venv` unittest discover，没装 pytest 别装；提交前 `python scripts/check.py`。
