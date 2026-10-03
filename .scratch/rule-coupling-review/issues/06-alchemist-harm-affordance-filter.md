# 06 炼金 harm 选项过滤盾目标（projection 小修）

Status: ready-for-agent

## 背景

耦合点 B1 的口径不一致小修（2026-10-03 批量确认附带）：刺客（projection.py:73）、感应者（projection.py:120）的合法目标列表已过滤持盾者，炼金 harm 的选项生成（projection.py:63-65）没滤——玩家可以点到持盾的被保护者，提交才报 `target.shielded`。

## 改动

- projection.py:63-65 的炼金 harm 选项过滤持盾目标，与其他技能 affordance 口径对齐。纯投影改动，引擎校验逻辑不动。

## 验收

- 持盾者不出现在炼金 harm 的可选列表；引擎行为不变（仍拒绝该命令，防御性保留）。
