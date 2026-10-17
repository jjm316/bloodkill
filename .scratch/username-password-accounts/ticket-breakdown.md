# 账号功能与管理工具：正式工单索引

Status: ready-for-agent
实施启动：2026-10-13 用户调用 implement-spec；集成分支为 `codex/username-password-accounts`，从 07 开始按依赖推进。
日期：2026-10-12
发布记录：用户已确认拆分并要求发布；21 个正式子 ticket 编号为 07–27，包含 98 组验证场景。功能和测试尚未实现或执行。

## 实施队列与执行约束

**以后实现整个 spec 时，只执行 07–27。原 01–06 仅保留历史范围与追溯，不另行领取或再次实现，也不作为子 ticket 的阻塞依赖。** 父项内容和状态保持；Parent 字段只说明来源关系，实际顺序仅以 Blocked by 为准。

业务决策见 [已确认规格](spec.md)，验证要求见 [validation-plan.md](validation-plan.md)。用户“先别开始做”的指令仍有效；发布仅代表需求文档完备，必须等待后续明确启动开发的指令。

每个子 ticket 沿一个用户或管理者行为交付必要的数据、服务、界面/CLI 和测试，能在隔离环境独立演示。测试及前序协议改变影响的既有调用方适配随各切片完成。25 收敛完整测试工具流程，27 验收账号与管理工具一起交付，不替代前序验证。

## 正式子 ticket 与阻塞关系

7. **[07 注册账号并自动进入大厅](issues/07-register-and-auto-login.md)**
   阻塞：无。
   交付：新玩家从注册入口填写用户名和自设密码，成功后自动登录并在大厅看到自己的用户名；重复或非法输入得到可纠正的中文反馈。
   验证：5 组，编号 V01.01–V01.05；原草案 01 → 正式 07。

8. **[08 已有账号登录与持续显示当前身份](issues/08-login-and-current-account.md)**
   阻塞：07。
   交付：已有玩家使用用户名和密码登录，大厅始终清楚显示是谁；刷新后恢复该账号，未登录请求不能假装已登录。
   验证：4 组，编号 V02.01–V02.04；原草案 02 → 正式 08。

9. **[09 登录账号创建房间并成为房主](issues/09-create-room-as-account-host.md)**
   阻塞：08。
   交付：玩家登录后创建六位房间，立即看到自己的座位和房主标记；房主可以使用现有开始、锁定、解锁操作。
   验证：4 组，编号 V03.01–V03.04；原草案 03 → 正式 09。

10. **[10 按账号加入房间及跨设备恢复座位](issues/10-join-and-resume-account-seat.md)**
   阻塞：09。
   交付：玩家输入房号加入，在其他设备重新登录相同账号后回到原座位；锁房或开局后仍能恢复，其他人不能按同名冒领。
   验证：4 组，编号 V04.01–V04.04；原草案 04 → 正式 10。

11. **[11 新连接接管座位并停止旧连接争抢](issues/11-seat-takeover-and-reconnect.md)**
   阻塞：10。
   交付：同账号在手机或新标签页进入同一座位时，新连接接管；旧页面明确提示已在别处进入，并停止操作和自动重连。
   验证：4 组，编号 V05.01–V05.04；原草案 05 → 正式 11。

12. **[12 一人一个未结束房间及并发占用限制](issues/12-one-active-room-and-races.md)**
   阻塞：10。
   交付：大厅显示自己的当前房间；已有占用时创建或加入别的房间会被解释并引导返回，多个设备同时请求也不能占两个房间。
   验证：4 组，编号 V06.01–V06.04；原草案 06 → 正式 12。

13. **[13 等待玩家退座与房主返回大厅](issues/13-waiting-seat-exit-and-host-return.md)**
   阻塞：12。
   交付：普通等待玩家主动退出后让出座位并可换房；房主返回大厅保留座位和身份，对局中的离开则只断开连接。
   验证：5 组，编号 V07.01–V07.05；原草案 07 → 正式 13。

14. **[14 固定 30 天登录、退出与切换账号](issues/14-fixed-expiry-logout-and-account-switch.md)**
   阻塞：10。
   交付：登录有效期固定为 30 天；退出或过期后已有游戏连接停止操作，重新登录能恢复座位，切换账号立即换成正确身份。
   验证：5 组，编号 V08.01–V08.05；原草案 08 → 正式 14。

15. **[15 主动改密码并撤销其他设备登录](issues/15-change-password-and-revoke-other-logins.md)**
   阻塞：14。
   交付：玩家在界面验证旧密码并设置新密码，当前设备继续使用，其他设备退出并用新密码重新登录。
   验证：4 组，编号 V09.01–V09.04；原草案 09 → 正式 15。

16. **[16 登录旁观、公开投影与玩家旁观互斥](issues/16-spectator-access-and-seat-exclusion.md)**
   阻塞：12。
   交付：无玩家占用的已登录用户能旁观公开对局；已占座的账号不能同时旁观，旁观中的账号成为玩家后旧旁观连接停止。
   验证：5 组，编号 V10.01–V10.05；原草案 10 → 正式 16。

17. **[17 邀请链接跨登录注册自动进入目标房](issues/17-invitation-through-auth.md)**
   阻塞：12。
   交付：朋友打开只有房号的邀请，登录或注册成功后自动进目标房；已有其他房间或目标不可进入时看到原因和恢复入口。
   验证：5 组，编号 V11.01–V11.05；原草案 11 → 正式 17。

18. **[18 切换账号隔离本地备忘及行动偏好](issues/18-account-local-preferences.md)**
   阻塞：14。
   交付：同一浏览器切换账号后看到各自的备忘、挡刀偏好和日志筛选；回到原账号仍保留自己的记录，其他设备不同步。
   验证：5 组，编号 V12.01–V12.05；原草案 12 → 正式 18。

19. **[19 管理工具在线查看账号和房间](issues/19-admin-inspect-users-and-rooms.md)**
   阻塞：10。
   交付：管理者在服务器终端查看账号占用、房间状态、房主和在线玩家，获得后续重置及清理的明确目标。
   验证：4 组，编号 V13.01–V13.04；原草案 13 → 正式 19。

20. **[20 管理工具重置密码并撤销全部登录](issues/20-admin-reset-password.md)**
   阻塞：14、19。
   交付：管理者确认本人后在终端隐藏输入新密码，重置指定账号；该账号所有设备重新登录，仍可恢复原座位。
   验证：5 组，编号 V14.01–V14.05；原草案 14 → 正式 20。

21. **[21 管理工具确认并备份关闭指定弃局](issues/21-admin-close-single-room.md)**
   阻塞：12、19。
   交付：管理者预览一个等待或进行房间，输入房号确认；备份成功后关闭该房，玩家获通知并能进入新房，其他房间照常运行。
   验证：5 组，编号 V15.01–V15.05；原草案 15 → 正式 21。

22. **[22 清理中断后的恢复与关闭房间不复活](issues/22-closed-room-recovery-and-failures.md)**
   阻塞：21。
   交付：清理过程中服务异常或重启后，已确认关闭的房间不会复活，占用与备份仍一致；未完成关闭明确报告并可以安全重试。
   验证：5 组，编号 V16.01–V16.05；原草案 16 → 正式 22。

23. **[23 登录观看公开回放及保留规则](issues/23-authenticated-replay-and-retention.md)**
   阻塞：10。
   交付：已登录用户知道房号即可看正常结束对局的公开回放；保留最近 20 局时不删除账号或管理数据。
   验证：5 组，编号 V17.01–V17.05；原草案 17 → 正式 23。

24. **[24 旧房间备份停用并只切换一次](issues/24-legacy-cutover-once.md)**
   阻塞：22、23。
   交付：首次启用账号机制时停用旧未结束房间并保留已结束回放，玩家重新注册开房；以后重启不再次停用新房。
   验证：5 组，编号 V18.01–V18.05；原草案 18 → 正式 24。

25. **[25 测试工具用真实账号开局并完成发布 smoke](issues/25-authenticated-test-toolkit-and-smoke.md)**
   阻塞：23。
   交付：开发者用既有测试入口开出多玩家局，玩家走真实账号流程；发布 smoke 经真实请求完成对局并验证回放，测试不会动真实账号。
   验证：5 组，编号 V19.01–V19.05；原草案 19 → 正式 25。

26. **[26 手机及键盘完成账号房间流程并恢复失败](issues/26-browser-mobile-keyboard-and-recovery.md)**
   阻塞：11、13、15、16、17、18。
   交付：在真实手机宽度和桌面浏览器中，用户能靠可见界面完成注册、登录、邀请进房、退座、改密及连接恢复，身份始终清楚。
   验证：5 组，编号 V20.01–V20.05；原草案 20 → 正式 26。

27. **[27 更新包、管理用法和完整验证证据交付](issues/27-package-admin-guide-and-final-evidence.md)**
   阻塞：20、24、25、26。
   交付：从更新包启动服务，按中文用法实际查看、重置和清理；账号功能与管理工具一起通过完整验收并交付可复用证据。
   验证：5 组，编号 V21.01–V21.05；原草案 21 → 正式 27。

## 原父项的范围归属

下面是追溯关系，不是另一套实施队列。原父项不再单独实现。

- [原 01 聚合范围](issues/01-accounts-and-sessions.md) → [07](issues/07-register-and-auto-login.md)、[08](issues/08-login-and-current-account.md)、[14](issues/14-fixed-expiry-logout-and-account-switch.md)、[15](issues/15-change-password-and-revoke-other-logins.md)。
- [原 02 聚合范围](issues/02-room-ownership-and-protocol.md) → [09](issues/09-create-room-as-account-host.md)、[10](issues/10-join-and-resume-account-seat.md)、[11](issues/11-seat-takeover-and-reconnect.md)、[12](issues/12-one-active-room-and-races.md)、[13](issues/13-waiting-seat-exit-and-host-return.md)、[16](issues/16-spectator-access-and-seat-exclusion.md)、[23](issues/23-authenticated-replay-and-retention.md)。
- [原 03 聚合范围](issues/03-auth-and-room-ui.md) → [07](issues/07-register-and-auto-login.md)、[08](issues/08-login-and-current-account.md)、[09](issues/09-create-room-as-account-host.md)、[10](issues/10-join-and-resume-account-seat.md)、[11](issues/11-seat-takeover-and-reconnect.md)、[12](issues/12-one-active-room-and-races.md)、[13](issues/13-waiting-seat-exit-and-host-return.md)、[14](issues/14-fixed-expiry-logout-and-account-switch.md)、[15](issues/15-change-password-and-revoke-other-logins.md)、[16](issues/16-spectator-access-and-seat-exclusion.md)、[17](issues/17-invitation-through-auth.md)、[18](issues/18-account-local-preferences.md)、[26](issues/26-browser-mobile-keyboard-and-recovery.md)。
- [原 04 聚合范围](issues/04-account-admin-tool.md) → [19](issues/19-admin-inspect-users-and-rooms.md)、[20](issues/20-admin-reset-password.md)、[21](issues/21-admin-close-single-room.md)、[22](issues/22-closed-room-recovery-and-failures.md)、[27](issues/27-package-admin-guide-and-final-evidence.md)。
- [原 05 聚合范围](issues/05-legacy-room-cutover.md) → [23](issues/23-authenticated-replay-and-retention.md)、[24](issues/24-legacy-cutover-once.md)。
- [原 06 聚合范围](issues/06-tooling-docs-and-acceptance.md) → [25](issues/25-authenticated-test-toolkit-and-smoke.md)、[26](issues/26-browser-mobile-keyboard-and-recovery.md)、[27](issues/27-package-admin-guide-and-final-evidence.md)。

## 验证编号与证据

V01.xx–V21.xx 是稳定的验证需求编号，保留发布前编号以免丢失引用，**不是当前正式工单号**。每项的正式归属以上述映射和其 ticket 内容为准。98 组场景全部已写入正式子 ticket，复选框保持未完成，文档数量不能当成已通过测试的数量。

共同的级别、临时数据隔离、时间/并发控制、故障注入与证据格式见 [验证要求](validation-plan.md)。实现后实际执行并登记结果，只有满足当前子项条件才能完成该项。

## 启动后的顺序

收到明确实施指令后，从正式子 ticket 07 开始，后续只从 07–27 中选择 Blocked by 全部完成的项。Parent 或原父项的 ready-for-agent 状态不能用于另开重复任务。最后通过 27 的完整更新包、管理用法和整体证据验收，账号功能与管理工具一起交付。

本次发布未开始开发、测试实现或线上操作。

原 ticket-drafts 文件只保留草案编号到正式工单的历史跳转入口，完整要求已迁入正式子 ticket；它们不属于待确认或实施队列。
