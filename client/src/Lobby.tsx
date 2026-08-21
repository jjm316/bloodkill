import { useState } from "react";

export interface RoomCredentials {
  code: string;
  name: string; // empty string = spectator
  token: string | null;
}

const NAME_KEY = "bloodbound:name";
const hostTokenKey = (code: string) => `bloodbound:host:${code}`;

export function Lobby({ onJoin, onReplay }: { onJoin: (c: RoomCredentials) => void; onReplay: () => void }) {
  const [name, setName] = useState(() => localStorage.getItem(NAME_KEY) ?? "");
  const [joinCode, setJoinCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createRoom = async () => {
    if (!name.trim()) {
      setError("Enter your name first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/rooms", { method: "POST" });
      if (!response.ok) throw new Error(`create failed (${response.status})`);
      const data = (await response.json()) as { code: string; hostToken: string };
      localStorage.setItem(hostTokenKey(data.code), data.hostToken);
      localStorage.setItem(NAME_KEY, name.trim());
      onJoin({ code: data.code, name: name.trim(), token: data.hostToken });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const joinRoom = (asSpectator: boolean) => {
    const code = joinCode.trim();
    if (!code || (!asSpectator && !name.trim())) {
      setError(asSpectator ? "Enter the room code." : "Enter the room code and your name.");
      return;
    }
    if (!asSpectator) localStorage.setItem(NAME_KEY, name.trim());
    onJoin({ code, name: asSpectator ? "" : name.trim(), token: localStorage.getItem(hostTokenKey(code)) });
  };

  return (
    <div className="lobby">
      <h1>Blood Bound</h1>
      <label className="field">
        Your name
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="name shown to other players"
          maxLength={32}
        />
      </label>
      <div className="lobby-actions">
        <button disabled={busy} onClick={createRoom}>
          Create room
        </button>
        <label className="field">
          Room code
          <input
            value={joinCode}
            onChange={(e) => setJoinCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            placeholder="6-digit code"
            inputMode="numeric"
          />
        </label>
        <div className="lobby-actions">
          <button disabled={busy} onClick={() => joinRoom(false)}>
            Join room
          </button>
          <button disabled={busy} onClick={() => joinRoom(true)}>
            Spectate
          </button>
        </div>
        <button onClick={onReplay}>Watch a replay</button>
      </div>
      {error && <div className="error">{error}</div>}
      <p className="hint">
        Rooms are hosted locally by the room creator. Players only need the 6-digit code and a name —
        no account. If you created a room, this browser remembers your host key.
      </p>
    </div>
  );
}
