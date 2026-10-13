import { useEffect, useState } from "react";
import { AccountEntry, type Account } from "./AccountEntry";
import { GameScreen } from "./GameScreen";
import { Lobby, type RoomCredentials } from "./Lobby";
import { ReplayScreen } from "./ReplayScreen";

type Screen = "lobby" | "room" | "replay";

// 房号是加入意图，身份始终来自当前登录；URL 中的旧姓名/令牌不参与授权。
function inviteRoomCode(): string | null {
  const params = new URLSearchParams(window.location.search);
  const code = (params.get("room") ?? "").trim();
  return /^\d{6}$/.test(code) ? code : null;
}

export default function App() {
  const [account, setAccount] = useState<Account | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [loggingOut, setLoggingOut] = useState(false);
  // 邀请链接只携带房号（工单 17）：挂载时读取一次，登录/注册成功或会话恢复后
  // 以 player 模式自动进入目标房；表单切换、刷新与登录失败重试不改目标。
  const [inviteCode, setInviteCode] = useState<string | null>(() => inviteRoomCode());
  useEffect(() => {
    let active = true;
    fetch("/api/auth/session", { credentials: "same-origin" }).then(async response => {
      if (response.ok) { const body = await response.json(); if (active) {
        setAccount(body.account);
        if (inviteCode) { setCredentials({ code: inviteCode, accountId: body.account.accountId, mode: "player" }); setScreen("room"); }
      } }
    }).catch(() => {}).finally(() => { if (active) setRestoring(false); });
    return () => { active = false; };
  }, []);
  const [credentials, setCredentials] = useState<RoomCredentials | null>(null);
  const [screen, setScreen] = useState<Screen>("lobby");

  // 取消邀请：清除目标并从地址栏移除房号参数，之后的刷新不再自动进目标房。
  const cancelInvite = () => {
    if (!inviteCode) return;
    setInviteCode(null);
    window.history.replaceState(null, "", window.location.pathname);
  };

  // 退出登录（工单 14）：撤销服务端当前登录并清除本机身份与房间状态。
  // 服务端会停止该登录的房间连接；本地清理只影响显示，撤销以服务端为准。
  const logout = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
    } catch { /* 网络不可达时同样回到登录页；服务端会话最迟自然到期 */ }
    setLoggingOut(false);
    setAccount(null);
    setCredentials(null);
    setScreen("lobby");
  };
  // 会话在服务端失效（过期/撤销/接管后的登录要求）：回到登录页重新登录。
  const authLost = () => {
    setAccount(null);
    setCredentials(null);
    setScreen("lobby");
  };

  return (
    <>
      <a className="skip-link" href="#main-content">跳转到主要内容</a>
      <main id="main-content">
        {restoring ? <p role="status">正在恢复登录……</p> : !account ? <AccountEntry inviteCode={inviteCode} onAuthenticated={next => {
          setAccount(next);
          if (inviteCode) { setCredentials({ code: inviteCode, accountId: next.accountId, mode: "player" }); setScreen("room"); }
          else { setCredentials(null); setScreen("lobby"); }
        }} /> : <>
        <p className="current-account">当前账号：{account.username}<button type="button" className="logout-button" disabled={loggingOut} onClick={() => { void logout(); }}>{loggingOut ? "正在退出……" : "退出登录"}</button></p>
        {screen === "lobby" ? (
      <Lobby
        key={account.accountId}
        account={account}
        onJoin={(next) => {
          setCredentials(next);
          setScreen("room");
        }}
        onReplay={() => setScreen("replay")}
      />
        ) : screen === "replay" ? (
          <ReplayScreen onBack={() => setScreen("lobby")} />
        ) : credentials ? (
      <GameScreen
        key={credentials.accountId}
        credentials={credentials}
        onLeave={() => {
          setCredentials(null);
          setScreen("lobby");
          // 明确离开邀请目标房 = 取消邀请；成功进房后离开同样不再保留深链。
          cancelInvite();
        }}
        onReturnToRoom={(code) => {
          // 返回原房 = 放弃本次邀请目标，直接恢复原房座位。
          cancelInvite();
          setCredentials({ code, accountId: account.accountId, mode: "player" });
          setScreen("room");
        }}
        onAuthLost={authLost}
      />
        ) : null}
        </>}
      </main>
    </>
  );
}
