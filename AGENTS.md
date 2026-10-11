## Agent skills

### Automated checks

提交或评审代码前运行 `python scripts/check.py`；确定性检查与 AI 评审的分工见 `docs/agents/quality-checks.md`。

### Issue tracker

Issues and specs live as Markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Worktrees

实现工作树里直接 `npm ci --prefix client`（热缓存约 3 秒），不为 node_modules 建 junction 指向主仓：`git worktree remove --force` 会穿透 junction 清空被指向的目录（2026-10-05 主仓依赖被这样清空过一次）。

### Triage labels

Use the default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository using root `CONTEXT.md` and `docs/adr/`. See `docs/agents/domain.md`.

规则争议以规则语料（`.scratch/blood-oath-replica/rules-corpus-user-extract.md`）+ ADR 为准，不得在代码里临时发明规则。

### Deployment and server ops

生产环境在阿里云轻量服务器 `http://47.111.11.55:8000`。部署/更新走 `.zcode/skills/deploy` 技能（用户说「部署」即执行）或 `scripts/deploy-cloud.sh 47.111.11.55`。查日志、存档、服务管理等运维按 `.agents/skills/server-ops/SKILL.md` 执行；委托其他 agent 运维时把该路径交给对方。

### Prototypes

丢弃用原型统一放仓库根 `prototypes/`（已 gitignore）：运行入口在 `prototypes/prototype.html`，验收产物按主题分子目录。新原型不再散落 `client/` 或 `.scratch/`。

### Chinese audience and UI language

本项目面向中国用户（中国大陆）。所有左右布局的前端页面、按钮、状态、错误提示、事件日志和帮助文案必须使用简体中文；协议字段、规则 ID、代码标识符可以继续使用英文。新增或修改界面时，优先复用中文本地化名称，不要把内部英文 ID 直接展示给用户。
