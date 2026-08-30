# 01 - 搭建 vitest + RTL 并为等待名册写首批测试

Type: task
Status: ready-for-agent

## 背景

前端没有测试设施（`client/package.json` 无 test script、无框架依赖、无测试文件）。等待房间名册的「自己高亮 / 房主标记 / 离线后缀」功能已在 `client/src/GameScreen.tsx` 的 `WaitingRoom` 组件实现，但没有自动化覆盖。本 issue 把测试基建建起来，并用这批测试当首个真实用例。背景与选型决策见 [../spec.md](../spec.md)。

## 任务

1. **基建**：`client/` 安装 devDependencies：`vitest`、`jsdom`、`@testing-library/react`、`@testing-library/jest-dom`（如需再配 `@testing-library/user-event`）；`package.json` 加 `"test": "vitest run"`；vitest 配置 `environment: "jsdom"`（可在 `vite.config.ts` 或独立 `vitest.config.ts`）。
2. **首批测试**（渲染 `WaitingRoom` 或经 `GameScreen` 渲染，直接构造 `RoomState` 假对象，类型见 `client/src/types.ts`）：
   - 自己的行：`className` 含 `self`，文本含「（你）」。
   - 房主的行：文本含「（房主）」，且**任何视角**（房主自己、其他玩家、旁观者）都能看到该标记。
   - 离线玩家（`connected[playerId] === false`）：该行含「（离线）」。
   - 旁观者视角（`yourPlayerId === null`）：没有任何行带 `self` class，页面不含「（你）」。
   - 同一人既是自己又是房主：该行同时含「（你）」「（房主）」，顺序为「（你）」在前。
   - 标记顺序契约：一行同时满足三个条件时，文本顺序为 昵称 →（你）→（房主）→（离线）。

## 边界与注意

- `GameScreen.tsx` 是单行密集风格，`WaitingRoom` 为模块内私有函数：可以导出它供测试使用，但**不要**重排或格式化整个文件，diff 必须最小。
- 界面文案必须是简体中文（见 AGENTS.md），测试断言直接用中文字面量。
- CSS 视觉样式（黄色描边等）不在测试范围，只断言 class 与文本。
- 不改变任何现有功能行为；若发现测试暴露功能 bug，停下来在 issue 评论区报告，不要顺手改行为。

## 完成条件

- `cd client && npm test` 全绿。
- 上述每条行为至少有一条断言覆盖。
- `cd client && npm run build` 与 `npx tsc --noEmit` 仍通过。
- 后端 `python -m pytest tests/ -q` 不受影响，仍全绿。
