# 闭合建局、回合、轮次与终局计分

Type: task
Blocked by: 04
Status: resolved

问题：把规则引擎接成完整流程：玩家加入、随机/固定准备、阶段推进、玩家顺序、跳过与超时、轮次结束、终局和排名。

输出：6-12 人流程（含奇数人数审判者局）、调试命令、整局 golden replay、家族/审判者胜负解释数据。

完成条件：测试脚本可无人值守完成 6-12 人一局；每次阶段变化可追溯；家族或审判者终局结果与规则场景一致；异常退出后可从最后事件继续。

## Answer

已在现有 `RulesEngine` 之上增加 `blood_bound.game_loop.run_deterministic_game()`。这里的“可无人值守整局”是 CI/golden replay 定义：脚本从加入玩家开始，只提交合法的 `join-game`、`start-game`、`pass-dagger`、`attack`、`decline-intervention`、`choose-skill(use=false)` 命令，自动走完 6--12 人局并得到 `GameEnded`、`ranking` 和 `explanationKey`。它不是 AI，也不替 UI 写状态。

终局结果现在包含稳定的 `ranking`（玩家 ID、名次、胜方阵营得分）和结构化解释键；事件序列保留每个命令与 revision，可直接作为 golden replay 输入。引擎在每个命令造成 phase 字段变化时追加 `PhaseChanged` 事件，因此阶段转移可逐步回放。通过固定 seed 和 clock，runner 输出可重复。攻击结束时保留 active player 上下文，确保审判者主动造成第 4 点伤害使用独立终局分支。

测试位于 `tests/test_engine.py`，覆盖 6、7、12 人完整局、奇数审判者、结果解释、revision 连续性，以及 `checkpoint()` / `resume_from_checkpoint()` 恢复后幂等重试。运行 `python -m unittest discover -v` 已通过 9 项。

## Comments

- 2026-08-20：从 frontier 认领；“无人值守”限定为无 UI 的规则 smoke/golden replay，不等同于自动玩家或正式 AI。
- 2026-08-20：完成实现并解决；checkpoint 保留事件 revision 和 command idempotency 表，进程重启后可继续且不会重复结算。
