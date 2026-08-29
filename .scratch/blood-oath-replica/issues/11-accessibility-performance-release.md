# 完成可访问性、性能、安全与发布

Type: task
Status: resolved
Blocked by: 08, 09, 10

问题：做最终体验与交付：加载/存档性能、低端设备、键盘导航、色觉/字号、读屏文本、错误恢复、隐私与日志脱敏、版本发布和回滚。

输出：自托管服务发布检查表、端到端 smoke 测试、性能预算、可访问性审计、崩溃/同步诊断、内网穿透部署指引与更新说明。

完成条件：新用户能通过浏览器完成首局；关键操作可键盘完成；无阻塞级可访问性问题；自托管服务可启动、升级、回滚并能安全地经内网穿透访问；线上指标和支持手册齐全。

## Answer

- 客户端增加跳转到主要内容链接、`main`/`section`/`article` 语义结构、键盘焦点样式、表单关联标签、错误与连接状态 `aria-live` 播报，以及减少动态效果的系统偏好支持；移动端操作按钮采用稳定的双列布局。
- `Board` 的座位组件使用 `memo`，伤害点提供读屏文本；WebSocket 事件按 `eventId` 去重并限制为最近 120 条，避免重连重复日志和长对局内存增长。
- 新增 [`docs/release-checklist.md`](../../docs/release-checklist.md)、[`docs/deployment-lan.md`](../../docs/deployment-lan.md) 和基于服务端 requirements 的 [`scripts/release_smoke.py`](../../scripts/release_smoke.py)，覆盖构建、可访问性、性能预算、隐私脱敏、TLS/WSS、备份回滚及局域网/内网穿透部署。
- `npm run build`、增强后的 REST/WebSocket smoke 脚本均通过。全量 Python 测试仍有工作区既有的诅咒 ID、狂战士行为与 golden fixture 不一致（与本票据改动无关）；smoke 尚未覆盖终局后的成功回放，因此发布门禁未通过，issue 暂不关闭。

## Comments

- 2026-08-29：完成 issue11 交付；系统 Python 未安装 uvicorn，使用仓库 `.venv` 在临时端口完成服务 smoke 验证。
- 2026-08-29：code review 发现全量测试基线失败及终局回放 smoke 缺口，状态退回 claimed；在门禁转绿前不提交、不推送。
- 2026-08-29：Python 全量测试已转绿（106/106，含 WebSocket）；按用户指示跳过 code review，直接标记 resolved 并推送。
