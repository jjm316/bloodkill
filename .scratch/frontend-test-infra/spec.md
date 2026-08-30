# Spec: 前端测试基建

## 背景

`client/` 目前没有任何测试设施：`package.json` 无 test script、无测试框架依赖、`client/src/` 下没有任何测试文件。等待房间名册的「自己高亮 / 房主标记 / 离线后缀」功能（见下方"现状"）已实现但完全没有自动化覆盖，之后任何前端改动都只能靠手工验证。

## 目标

- 在 `client/` 引入 **vitest + @testing-library/react + jsdom**（Vite + React 生态标准搭配，已在拷问中确认选型），`npm test` 一条命令可运行。
- 首批真实测试直接覆盖等待名册功能（见 [issues/01](issues/01-vitest-rtl-waiting-room-tests.md)），基建落地的同时立刻产生价值。
- 不改变任何现有功能行为；本 spec 是纯基建 + 回归覆盖。

## 非目标

- 不引入 Playwright/Cypress 等 E2E 框架。
- 不做视觉回归（截图比对）测试。
- 不给后端补测试（后端已有 pytest 且覆盖房主绑定）。

## 现状（功能代码事实，供实现者参考）

- 等待名册渲染在 `client/src/GameScreen.tsx` 的 `WaitingRoom` 函数（模块内私有，单行密集风格）。
- 判定逻辑全部在客户端：`p.playerId === state.yourPlayerId` → 自己（`self` class + 「（你）」）；`p.playerId === state.hostPlayerId` → 「（房主）」；`!state.connected[p.playerId]` → 「（离线）」。标记顺序固定：你 → 房主 → 离线。
- `RoomState` 类型在 `client/src/types.ts`，测试可直接构造假状态对象，无需真实服务端。

## 决策记录（拷问结论，2026-08-30）

- 选型 vitest + RTL + jsdom，由用户确认（Q9）。
- 首批测试就测等待名册功能，而不是 hello-world 样例（Q9）。
- 测试基建不在功能实现窗口内完成，单独 issue 执行（Q9）。
