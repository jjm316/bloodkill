import { useEffect, useState } from "react";
import { AccountEntry, type Account } from "./AccountEntry";
import { GameScreen } from "./GameScreen";
import { Lobby, type RoomCredentials } from "./Lobby";
import { ReplayScreen } from "./ReplayScreen";

type Screen = "lobby" | "room" | "replay";

// 房号是加入意图，身份始终来自当前登录；URL 中的旧姓名/令牌不参与授权。
function autoJoinCredentials(account: Account): RoomCredentials | null {
  const params = new URLSearchParams(window.location.search);
  const code = (params.get("room") ?? "").trim();
  if (!/^\d{6}$/.test(code)) return null;
  return { code, accountId: account.accountId, mode: "player" };
}

export default function App() {
  const [account, setAccount] = useState<Account | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [loggingOut, setLoggingOut] = useState(false);
  useEffect(() => {
    let active = true;
    fetch("/api/auth/session", { credentials: "same-origin" }).then(async response => {
      if (response.ok) { const body = await response.json(); if (active) {
        setAccount(body.account);
        const room = autoJoinCredentials(body.account);
        if (room) { setCredentials(room); setScreen("room"); }
      } }
    }).catch(() => {}).finally(() => { if (active) setRestoring(false); });
    return () => { active = false; };
  }, []);
  const [credentials, setCredentials] = useState<RoomCredentials | null>(null);
  const [screen, setScreen] = useState<Screen>("lobby");

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
        {restoring ? <p role="status">正在恢复登录……</p> : !account ? <AccountEntry onAuthenticated={next => {
          setAccount(next);
          setCredentials(null);
          setScreen("lobby");
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
        }}
        onAuthLost={authLost}
      />
        ) : null}
        </>}
      </main>
    </>
  );
}
