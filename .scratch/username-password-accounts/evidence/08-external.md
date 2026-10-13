# 08：外部 Chrome 的手机与历史补充验收

日期：2026-10-13。产品版本 `b1a4b280fc44742950e763e701e96dca3f37513c`，集成分支 `codex/username-password-accounts`。本次只补验收证据，不改变产品实现。

环境：Windows、Node 24.14.0、外部 Chrome 154.0.8037.99。采用独立 headless profile、动态且仅监听本机的 CDP 端口；两个隔离 browser context 分别为桌面 1440×900 与手机 390×844。服务端口 29208，独立数据目录 `D:/AIProj/bloodkill/prototypes/account-08-external-saves`；构建的前端为该集成版本。没有使用内置浏览器、用户 Chrome profile 或用户浏览历史。

命令：仓库根执行 `node prototypes/account-08/external-browser-check.mjs`。程序通过真实鼠标/键盘输入操作界面，使用账号测试 fixture，凭证不放命令参数、URL、输出或截图；截图在保存时掩蔽输入框。执行退出码 0，实际耗时约 2 秒。原默认沙箱构建因 Vite realpath 的 EPERM 被拒，按授权范围在沙箱外构建后通过；外部 Chrome 验收也在沙箱外执行。

## V02.03：真实手机控件、输入、错误与恢复

准备：桌面 context 从默认登录切到注册，以独立测试账号注册并自动进入大厅；手机 context 没有该登录 Cookie，仍显示默认登录表单。

输入与操作：手机使用注册用户名的英文小写变体，先填大小写不同的错误密码并按回车；观察中文错误且没有当前账号。切换密码显隐，检查 input type 为 text/password；填原密码连续按两次回车，进入大厅；随后真实页面刷新。

预期：中文错误可纠正、显隐正常、成功仍显示注册写法；两次连续回车只提交一次成功登录；刷新保留身份。手机表单、大厅和所有按钮均可见、可点且不横向裁剪。

实际：全部断言通过。CDP 的实际网络请求只计路由，共 2 次登录请求（一次失败、一次成功），没有输出请求体或 Cookie。刷新时等待新的 `performance.timeOrigin` 与身份恢复，排除了刷新前旧 DOM 的假通过。手机 documentElement/innerWidth/scrollWidth 均 390，height 844；所有表单输入、显隐和提交按钮均 x=16、right=374、width=358、height=40，大厅关键控件边界也在视口内。自动填充属性真实读取为 username/current-password；本次不冒称密码管理器已保存凭证后的自动填充 UI 已验证。

## V02.04：仅自有测试页的真实导航历史

操作：使用 CDP `Page.getNavigationHistory` 分别读取本脚本创建的两个页面，范围只在自己的 target；不调用用户浏览器全站 history。

预期：注册、错误登录、成功登录、刷新均不将密码、账号或会话写入 URL/历史。

实际：两份历史均只包含 `about:blank` 与 `http://127.0.0.1:29208/`，无查询参数、URL 用户名/密码或凭证。断言通过，退出 0。服务端日志与响应隐私的真实验证继续见 [08 主证据](08.md) 中 V02.04。

## 证据与清理

- [脱敏结果及实际控件边界](D:/AIProj/bloodkill/prototypes/account-08/external-results.json)
- [手机错误反馈](D:/AIProj/bloodkill/prototypes/account-08/external-mobile-error.png)
- [手机刷新后大厅](D:/AIProj/bloodkill/prototypes/account-08/external-mobile-lobby.png)
- [桌面注册后大厅](D:/AIProj/bloodkill/prototypes/account-08/external-desktop-lobby.png)

截图已经目视检查，表单与大厅正常排布。脚本 finally 停止了自己创建的 Chrome 并清理独立 profile；隔离服务仅停止已记录的自有 PID 12084。未改用户 Chrome、未操作生产。08 的 IAB 历史挂起及异常手机截图保留为失败/未验证记录，完整手机房间和密码流程仍由 26 验收。

此后未改产品代码或自动测试，沿用 08 已实际通过的 272 Python（无跳过）、205 前端、TypeScript 和生产构建，不重复全量检查。
