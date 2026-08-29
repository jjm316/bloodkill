## Agent skills

### Issue tracker

Issues and specs live as Markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository using root `CONTEXT.md` and `docs/adr/`. See `docs/agents/domain.md`.

### Chinese audience and UI language

本项目面向中国用户（中国大陆）。所有左右布局的前端页面、按钮、状态、错误提示、事件日志和帮助文案必须使用简体中文；协议字段、规则 ID、代码标识符可以继续使用英文。新增或修改界面时，优先复用中文本地化名称，不要把内部英文 ID 直接展示给用户。
