# 自动检查与 AI 评审

## 工作流程

修改代码后运行 `python scripts/check.py`，修复失败后再评审。脚本按顺序执行差异空白检查、Python 全部测试、前端全部测试，以及包含 TypeScript 检查的生产构建；第一个失败步骤立即返回非零退出码。完整 Python 测试不允许零用例或跳过，缺依赖时补齐环境再运行。

检查子进程的回环地址固定直连，保留现有其他代理排除项，避免本机代理接管临时 HTTP/WebSocket 服务。此设置仅影响检查进程；[websockets 官方代理说明](https://websockets.readthedocs.io/en/stable/topics/proxies.html)定义了系统代理与 no_proxy 的行为。

脚本自动使用仓库 `.venv` 运行 Python 测试；没有 `.venv` 时使用调用脚本的 Python。准备依赖与安装本地守门：

```text
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
npm ci --prefix client
python scripts/check.py install-hooks
```

macOS/Linux 的虚拟环境解释器为 `.venv/bin/python`。安装 hooks 只修改本仓库配置，已有自定义 hooks 时拒绝覆盖。新克隆需要安装一次。

- `pre-commit` 只检查实际暂存差异的空白，保证提交操作快速。
- `pre-push` 对干净工作区的当前 HEAD 跑完整检查；非当前提交的推送须先检出该提交。仅删除远端引用时无需运行测试。工作区修改可先提交，或用 Git stash 保留后再推送。
- GitHub CI 在 push、pull_request 和手动触发时，使用同一脚本验证检出的提交，在 Windows/Linux 上分别运行。PR 检查基准为目标分支 SHA，push 为推送前 SHA，新分支以远端默认分支的共同祖先为基准；始终检查当前提交的差异，不因建立新分支而重新审查历史素材的格式。

本地 hooks 可以被绕过，远端 CI 是提交证据。需要强制阻止未通过检查的合并时，将两个“自动检查”任务配置为目标分支的必需状态检查；仓库中的工作流文件本身不会自动设置分支保护。

开发途中可在 `client/` 运行 `npm run typecheck` 或单文件测试；最终验收使用完整入口。检查命令以脚本与 package.json 为准，不在评审提示里重复维护命令清单。

## 确定性判断交给脚本

脚本负责已编码的行为回归、类型错误、生产构建、差异空白、检查失败状态和测试跳过。评审引用脚本结果及其覆盖范围，不用 AI 重复扫描这些机械问题，也不以 AI 判断覆盖失败退出码。

规则在语料与 ADR 中明确后，能稳定复现的验收条件应变成测试或确定性检查。当前没有统一代码风格配置，不凭空增加格式或 lint 规则；出现明确且工具未覆盖的机械约束时，优先接入对应检查。

## 不确定性判断交给 AI

AI 评审负责需求与规格是否匹配、规则语料和 ADR 的解释、跨文件行为一致性、隐私边界、设计取舍，以及测试遗漏的场景。自动检查通过仅证明已有检查通过；AI 仍需判断断言是否有效、哪些行为尚未覆盖。

AI 识别断言盲点时，应给出可执行的验收条件，再沉淀成确定性检查。例如，事件映射完整性要验证已知事件的准确类别和文案，单纯检查返回合法类别会被未知事件的兜底逻辑掩盖；接入 CI 不能代替检查测试本身的有效性。
