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

  return (
    <>
      <a className="skip-link" href="#main-content">跳转到主要内容</a>
      <main id="main-content">
        {restoring ? <p role="status">正在恢复登录……</p> : !account ? <AccountEntry onAuthenticated={next => {
          setAccount(next);
          setCredentials(null);
          setScreen("lobby");
        }} /> : <>
        <p className="current-account">当前账号：{account.username}</p>
        {screen === "lobby" ? (
      <Lobby
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
        credentials={credentials}
        onLeave={() => {
          setCredentials(null);
          setScreen("lobby");
        }}
        onReturnToRoom={(code) => {
          setCredentials({ code, accountId: account.accountId, mode: "player" });
          setScreen("room");
        }}
      />
        ) : null}
        </>}
      </main>
    </>
  );
}
