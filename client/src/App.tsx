import { useState } from "react";
import { GameScreen } from "./GameScreen";
import { Lobby, type RoomCredentials } from "./Lobby";
import { ReplayScreen } from "./ReplayScreen";

type Screen = "lobby" | "room" | "replay";

// 一键进房链接（?room=&name=&token=），供 scripts/launch_test_env.py 批量开窗和
// 局域网分享加入链接使用；缺少合法房间号或姓名时回退到普通大厅。
function autoJoinCredentials(): RoomCredentials | null {
  const params = new URLSearchParams(window.location.search);
  const code = (params.get("room") ?? "").trim();
  const name = (params.get("name") ?? "").trim().slice(0, 32);
  if (!/^\d{6}$/.test(code) || !name) return null;
  return { code, name, token: params.get("token") };
}

export default function App() {
  const [credentials, setCredentials] = useState<RoomCredentials | null>(autoJoinCredentials);
  const [screen, setScreen] = useState<Screen>(() => (credentials ? "room" : "lobby"));

  return (
    <>
      <a className="skip-link" href="#main-content">跳转到主要内容</a>
      <main id="main-content">
        {screen === "lobby" ? (
      <Lobby
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
      />
        ) : null}
      </main>
    </>
  );
}
