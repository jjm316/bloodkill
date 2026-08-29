import { useState } from "react";

export interface RoomCredentials { code: string; name: string; token: string | null; }
const NAME_KEY = "bloodbound:name";
const hostTokenKey = (code: string) => `bloodbound:host:${code}`;

export function Lobby({ onJoin, onReplay }: { onJoin: (c: RoomCredentials) => void; onReplay: () => void }) {
  const [name, setName] = useState(() => localStorage.getItem(NAME_KEY) ?? "");
  const [joinCode, setJoinCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const createRoom = async () => {
    if (!name.trim()) { setError("请先输入姓名。"); return; }
    setBusy(true); setError(null);
    try {
      const response = await fetch("/api/rooms", { method: "POST" });
      if (!response.ok) throw new Error(`创建房间失败（${response.status}）`);
      const data = (await response.json()) as { code: string; hostToken: string };
      localStorage.setItem(hostTokenKey(data.code), data.hostToken); localStorage.setItem(NAME_KEY, name.trim());
      onJoin({ code: data.code, name: name.trim(), token: data.hostToken });
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  };
  const joinRoom = (asSpectator: boolean) => {
    const code = joinCode.trim();
    if (!code || (!asSpectator && !name.trim())) { setError(asSpectator ? "请输入房间号。" : "请输入房间号和姓名。"); return; }
    if (!asSpectator) localStorage.setItem(NAME_KEY, name.trim());
    onJoin({ code, name: asSpectator ? "" : name.trim(), token: localStorage.getItem(hostTokenKey(code)) });
  };
  return <div className="lobby">
    <h1>鲜血盟约</h1>
    <label className="field">姓名<input value={name} onChange={(e) => setName(e.target.value)} placeholder="其他玩家看到的名称" maxLength={32} /></label>
    <div className="lobby-actions">
      <button disabled={busy} onClick={createRoom}>创建房间</button>
      <label className="field">房间号<input value={joinCode} onChange={(e) => setJoinCode(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="6位数字房间号" inputMode="numeric" /></label>
      <div className="lobby-actions"><button disabled={busy} onClick={() => joinRoom(false)}>加入房间</button><button disabled={busy} onClick={() => joinRoom(true)}>旁观</button></div>
      <button onClick={onReplay}>观看回放</button>
    </div>
    {error && <div className="error">{error}</div>}
    <p className="hint">房间由创建者在本地托管。玩家只需房间号和姓名，无需注册账号；创建房间后，本浏览器会记住房主凭据。</p>
  </div>;
}
