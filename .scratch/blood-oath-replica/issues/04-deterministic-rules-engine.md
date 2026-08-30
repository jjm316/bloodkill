# 实现确定性规则引擎

Type: task
Blocked by: 03
Status: resolved

问题：实现纯领域服务，接受命令并产出事件/新状态；随机数、时钟和外部输入可注入，seed 相同则结果一致。

输出：初始化、合法行动枚举、行动结算、触发器队列、替代/响应窗口、冲突结算、资源扣除、终局判定 API；禁止 UI 直接改状态。

完成条件：无 UI 跑通最小完整局；命令幂等/拒绝语义明确；同一输入日志可得到相同事件序列；引擎可被脚本和测试直接调用。

## Answer

已完成 `blood_bound/` 纯 Python 领域引擎，选择 Python 3.11+、标准库 `unittest`，不引入 Web 框架或数据库依赖。当前 API 包含：

- `RulesEngine.new_game()` 和 `Command`/`Event`/`EngineState` 数据结构；确定性 seed 的 6--12 人建局、偶数双家族和奇数审判者分配、每名审判者一真一假两张诅咒卡；
- `join-game`、`start-game`、`pass-dagger`、`attack`、干涉请求/选择/拒绝、攻击触发技能选择、`distribute-curse` 命令；
- 攻击伤害、线索展示、捕获、审判者攻击限制、Shield/Fan 目标限制、技能窗口和家族/审判者终局分支；
- `legal_actions(player_id)` 权威派生接口；稳定 `RuleError.code`；expected revision 检查；重复命令按 body hash 幂等重放，复用 command ID 配不同 body 会拒绝；
- 事务式 deep-copy 提交：命令中途失败不改变 authority；事件在提交时按旧 revision 顺序生成唯一 ID，注入 clock 后可复现测试事件。

测试位于 `tests/test_engine.py`，覆盖确定性建局、奇数诅咒、传匕首幂等、攻击/伤害/技能窗口、干涉资格、诅咒分发和 revision 冲突。运行 `python -m unittest discover -v` 已通过 6 项。

本票据只实现来源 C 已确定的行为；没有为来源 C 未覆盖的能力细节或发言变体猜测规则。后续 05 可在此 API 上接完整回合脚本、排名和 golden replay。

## Comments

- 2026-08-20：从 frontier 认领并完成；产品方确认后端采用 Python，故未创建 TypeScript 运行时。
