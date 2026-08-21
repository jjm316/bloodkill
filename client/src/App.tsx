import { useState } from "react";
import { GameScreen } from "./GameScreen";
import { Lobby, type RoomCredentials } from "./Lobby";
import { ReplayScreen } from "./ReplayScreen";

type Screen = "lobby" | "room" | "replay";

export default function App() {
  const [screen, setScreen] = useState<Screen>("lobby");
  const [credentials, setCredentials] = useState<RoomCredentials | null>(null);

  if (screen === "lobby") {
    return (
      <Lobby
        onJoin={(next) => {
          setCredentials(next);
          setScreen("room");
        }}
        onReplay={() => setScreen("replay")}
      />
    );
  }
  if (screen === "replay") {
    return <ReplayScreen onBack={() => setScreen("lobby")} />;
  }
  if (credentials) {
    return (
      <GameScreen
        credentials={credentials}
        onLeave={() => {
          setCredentials(null);
          setScreen("lobby");
        }}
      />
    );
  }
  return null;
}
