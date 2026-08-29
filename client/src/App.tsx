import { useState } from "react";
import { GameScreen } from "./GameScreen";
import { Lobby, type RoomCredentials } from "./Lobby";
import { ReplayScreen } from "./ReplayScreen";

type Screen = "lobby" | "room" | "replay";

export default function App() {
  const [screen, setScreen] = useState<Screen>("lobby");
  const [credentials, setCredentials] = useState<RoomCredentials | null>(null);

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
